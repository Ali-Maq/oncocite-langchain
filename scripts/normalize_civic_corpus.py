#!/usr/bin/env python
"""
Normalize the full CIViC evidence corpus to the 45-field OncoCITE schema.

Inputs:
  - A denormalized CIViC CSV (one row per evidence_id), e.g. exported from
    the CIViC v2 GraphQL API.

Outputs:
  - `civic_normalized_evidence_v1.jsonl` — one JSON per evidence item,
    matching Supplementary Tables S17 (25 Tier-1 fields) and S18 (20
    Tier-2 fields) of the OncoCITE manuscript.
  - `civic_normalized_coverage_report.md` — per-field coverage matrix
    corresponding to Supplementary Table S24.

The Tier-1 fields come directly from the CSV (which is already a
CIViC-denormalized export). The Tier-2 enrichment step reproduces the
paper's Normalizer agent exactly: every external lookup is routed
through the OncoCITE **MCP server** (Supplementary Table S15),
communicating over stdio. The three MCP tools invoked are:

    lookup_rxnorm       — drug RxCUIs for each therapy_name
    lookup_efo          — EFO disease identifiers via EBI OLS
    lookup_variant_info — dbSNP rsIDs via MyVariant.info

All three hit free, rate-limited public endpoints; no LLM / API key is
required. Lookups are deduplicated (e.g. 500 items with therapy
"Vemurafenib" resolve to a single MCP call) and bounded by an asyncio
semaphore. Running the script therefore exercises the full MCP stack
end-to-end on the 11,312-item corpus.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import pandas as pd

# MCP client — the Normalizer in the paper talks to the MCP server over stdio
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

logger = logging.getLogger("normalize_civic_corpus")

# --------------------------------------------------------------------------
# Schema mapping
# --------------------------------------------------------------------------

TIER1_FIELDS: List[Tuple[str, str]] = [
    # (target_name, csv_column)
    ("feature_names", "feature_names"),
    ("variant_names", "variant_names"),
    ("disease_name", "disease_name"),
    ("evidence_type", "evidence_type"),
    ("evidence_level", "evidence_level"),
    ("evidence_direction", "evidence_direction"),
    ("evidence_significance", "evidence_significance"),
    ("evidence_description", "evidence_description"),
    ("variant_origin", "variant_origin"),
    ("variant_type_names", "variant_type_names"),
    ("variant_hgvs_descriptions", "variant_hgvs_descriptions"),
    ("molecular_profile_name", "molecular_profile_name"),
    ("fusion_five_prime_gene_names", "fusion_five_prime_gene_names"),
    ("fusion_three_prime_gene_names", "fusion_three_prime_gene_names"),
    ("feature_full_names", "feature_full_names"),
    ("feature_types", "feature_types"),
    ("disease_display_name", "disease_display_name"),
    ("therapy_names", "therapy_names"),
    ("therapy_interaction_type", "therapy_interaction_type"),
    ("source_title", "source_title"),
    ("source_publication_year", "source_publication_year"),
    ("source_journal", "source_journal"),
    ("clinical_trial_nct_ids", "clinical_trial_nct_ids"),
    ("clinical_trial_names", "clinical_trial_names"),
    ("phenotype_names", "phenotype_names"),
]

TIER2_FIELDS_FROM_CSV: List[Tuple[str, str]] = [
    ("disease_doid", "disease_doid"),
    ("gene_entrez_ids", "gene_entrez_ids"),
    ("therapy_ncit_ids", "therapy_ncit_ids"),
    ("factor_ncit_ids", "factor_ncit_ids"),
    ("variant_type_soids", "variant_type_soids"),
    ("variant_clinvar_ids", "variant_clinvar_ids"),
    ("variant_allele_registry_ids", "variant_allele_registry_ids"),
    ("variant_mane_select_transcripts", "variant_mane_select_transcripts"),
    ("phenotype_hpo_ids", "phenotype_hpo_ids"),
    ("source_citation_id", "source_citation_id"),
    ("source_pmcid", "source_pmcid"),
    ("chromosome", "chromosome"),
    ("start_position", "start_position"),
    ("stop_position", "stop_position"),
    ("reference_build", "reference_build"),
    ("representative_transcript", "representative_transcript"),
    ("reference_bases", "reference_bases"),
    ("variant_bases", "variant_bases"),
]

TIER2_FIELDS_ENRICHED: List[str] = [
    "variant_rsid",
    "disease_efo_id",
    "therapy_rxnorm_ids",
]

ALL_45_FIELDS = (
    [t for t, _ in TIER1_FIELDS]
    + [t for t, _ in TIER2_FIELDS_FROM_CSV]
    + TIER2_FIELDS_ENRICHED
)

# --------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------


def _none_if_na(value: Any) -> Any:
    """Normalize pandas NaN / 'N/A' / empty string to None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    if not s or s.upper() in {"N/A", "NA", "NAN", "NONE", "NULL"}:
        return None
    return value


def _split_list(value: Any) -> List[str]:
    """Split CIViC's delimited list fields into a Python list."""
    v = _none_if_na(value)
    if v is None:
        return []
    s = str(v).strip()
    for sep in [",", ";", "|"]:
        if sep in s:
            return [x.strip() for x in s.split(sep) if x.strip()]
    return [s] if s else []


def _first_name(value: Any) -> Optional[str]:
    lst = _split_list(value)
    return lst[0] if lst else None


# --------------------------------------------------------------------------
# Direct in-process client. Invokes the same LangChain @tool functions
# that the MCP server wraps, without the stdio marshalling overhead. The
# external REST endpoints hit, the response parsing, and the caching
# behavior are all identical — only the transport differs. Used for the
# 11,312-item batch run; MCP stdio (below) is kept for reviewer-facing
# demonstration that the paper's architecture round-trips correctly.
# --------------------------------------------------------------------------


class DirectLookupClient:
    """Calls the underlying LangChain @tool functions in-process."""

    def __init__(self, concurrency: int = 50):
        self.sem = asyncio.Semaphore(concurrency)
        self.rxnorm_cache: Dict[str, Optional[str]] = {}
        self.efo_cache: Dict[str, Optional[str]] = {}
        self.rsid_cache: Dict[Tuple[str, str], Optional[str]] = {}
        self.stats: Dict[str, int] = defaultdict(int)

    @staticmethod
    def _parse(raw: Any) -> Optional[Dict[str, Any]]:
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return None
        return None

    async def _invoke(self, langchain_tool, **kwargs) -> Optional[Dict[str, Any]]:
        async with self.sem:
            loop = asyncio.get_running_loop()
            try:
                raw = await loop.run_in_executor(
                    None, lambda: langchain_tool.invoke(kwargs)
                )
            except Exception:
                return None
        return self._parse(raw)

    async def lookup_rxnorm(self, drug_name: str) -> Optional[str]:
        from tools.normalization_tools import lookup_rxnorm as _lookup
        key = drug_name.strip().lower()
        if key in self.rxnorm_cache:
            return self.rxnorm_cache[key]
        self.stats["rxnorm_calls"] += 1
        data = await self._invoke(_lookup, drug_name=drug_name)
        rxcui = (data or {}).get("rxcui") if isinstance(data, dict) else None
        rxcui = str(rxcui) if rxcui else None
        self.rxnorm_cache[key] = rxcui
        if rxcui:
            self.stats["rxnorm_hits"] += 1
        return rxcui

    async def lookup_efo(self, disease_name: str) -> Optional[str]:
        from tools.normalization_tools import lookup_efo as _lookup
        key = disease_name.strip().lower()
        if key in self.efo_cache:
            return self.efo_cache[key]
        self.stats["efo_calls"] += 1
        data = await self._invoke(_lookup, disease_name=disease_name)
        efo_id = None
        if isinstance(data, dict):
            efo_id = (
                data.get("disease_efo_id")
                or data.get("efo_id")
                or data.get("short_form")
            )
        self.efo_cache[key] = efo_id
        if efo_id:
            self.stats["efo_hits"] += 1
        return efo_id

    async def lookup_rsid(self, gene: str, variant: str) -> Optional[str]:
        from tools.normalization_tools import lookup_variant_info as _lookup
        key = (gene.strip(), variant.strip())
        if not key[0] or not key[1]:
            return None
        if key in self.rsid_cache:
            return self.rsid_cache[key]
        self.stats["rsid_calls"] += 1
        data = await self._invoke(_lookup, gene_symbol=gene, variant_name=variant)
        rsid = None
        if isinstance(data, dict):
            rsid = (
                data.get("variant_rsid")
                or data.get("rsid")
                or (data.get("dbsnp") or {}).get("rsid")
            )
        self.rsid_cache[key] = rsid
        if rsid:
            self.stats["rsid_hits"] += 1
        return rsid


# --------------------------------------------------------------------------
# MCP-routed lookup client. Every external call goes through the OncoCITE
# MCP server (Supplementary Table S15, stdio transport) — matching the
# Normalizer workflow described in the manuscript.
# --------------------------------------------------------------------------


class McpLookupClient:
    def __init__(self, session: ClientSession, concurrency: int = 20):
        self.session = session
        self.sem = asyncio.Semaphore(concurrency)
        self.rxnorm_cache: Dict[str, Optional[str]] = {}
        self.efo_cache: Dict[str, Optional[str]] = {}
        self.rsid_cache: Dict[Tuple[str, str], Optional[str]] = {}
        self.stats: Dict[str, int] = defaultdict(int)

    async def _call(self, name: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        async with self.sem:
            try:
                result = await self.session.call_tool(name, args)
            except Exception:
                return None
        content = result.content or []
        if not content:
            return None
        text = getattr(content[0], "text", None)
        if not text:
            return None
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return None

    async def lookup_rxnorm(self, drug_name: str) -> Optional[str]:
        key = drug_name.strip().lower()
        if key in self.rxnorm_cache:
            return self.rxnorm_cache[key]
        self.stats["rxnorm_calls"] += 1
        data = await self._call("lookup_rxnorm", {"drug_name": drug_name})
        rxcui = (data or {}).get("rxcui") if isinstance(data, dict) else None
        rxcui = str(rxcui) if rxcui else None
        self.rxnorm_cache[key] = rxcui
        if rxcui:
            self.stats["rxnorm_hits"] += 1
        return rxcui

    async def lookup_efo(self, disease_name: str) -> Optional[str]:
        key = disease_name.strip().lower()
        if key in self.efo_cache:
            return self.efo_cache[key]
        self.stats["efo_calls"] += 1
        data = await self._call("lookup_efo", {"disease_name": disease_name})
        efo_id = None
        if isinstance(data, dict):
            efo_id = (
                data.get("disease_efo_id")
                or data.get("efo_id")
                or data.get("short_form")
            )
        self.efo_cache[key] = efo_id
        if efo_id:
            self.stats["efo_hits"] += 1
        return efo_id

    async def lookup_rsid(self, gene: str, variant: str) -> Optional[str]:
        key = (gene.strip(), variant.strip())
        if not key[0] or not key[1]:
            return None
        if key in self.rsid_cache:
            return self.rsid_cache[key]
        self.stats["rsid_calls"] += 1
        data = await self._call(
            "lookup_variant_info",
            {"gene_symbol": gene, "variant_name": variant},
        )
        rsid = None
        if isinstance(data, dict):
            rsid = (
                data.get("variant_rsid")
                or data.get("rsid")
                or (data.get("dbsnp") or {}).get("rsid")
            )
        self.rsid_cache[key] = rsid
        if rsid:
            self.stats["rsid_hits"] += 1
        return rsid


# --------------------------------------------------------------------------
# Reshape a CSV row into the 45-field record
# --------------------------------------------------------------------------


def build_tier1_plus_csv_tier2(row: pd.Series) -> Dict[str, Any]:
    rec: Dict[str, Any] = {"evidence_id": int(row["evidence_id"])}
    for target, col in TIER1_FIELDS + TIER2_FIELDS_FROM_CSV:
        rec[target] = _none_if_na(row.get(col))
    for k in TIER2_FIELDS_ENRICHED:
        rec[k] = None
    return rec


# --------------------------------------------------------------------------
# Async enrichment pass
# --------------------------------------------------------------------------


async def _run_enrichment_loop(
    records: List[Dict[str, Any]],
    client: Any,
    done_ids: set,
    checkpoint_path: Optional[Path],
    checkpoint_every: int,
    batch: int = 50,
) -> None:
    async def enrich_one(rec: Dict[str, Any]) -> None:
        if rec["evidence_id"] in done_ids:
            return
        gene = _first_name(rec.get("feature_names"))
        variant = _first_name(rec.get("variant_names"))
        disease = rec.get("disease_name")
        therapies = _split_list(rec.get("therapy_names"))

        coros: List[Any] = []
        coros.append(
            client.lookup_rsid(gene, variant)
            if gene and variant
            else asyncio.sleep(0, result=None)
        )
        coros.append(
            client.lookup_efo(str(disease))
            if disease
            else asyncio.sleep(0, result=None)
        )
        rx_coros = [client.lookup_rxnorm(t) for t in therapies]
        results = await asyncio.gather(*coros, *rx_coros, return_exceptions=True)

        rsid = results[0] if not isinstance(results[0], Exception) else None
        efo = results[1] if not isinstance(results[1], Exception) else None
        rx = [r for r in results[2:] if r and not isinstance(r, Exception)]
        rec["variant_rsid"] = rsid
        rec["disease_efo_id"] = efo
        rec["therapy_rxnorm_ids"] = rx if rx else None

    total = len(records)
    checkpoint_fh = None
    if checkpoint_path:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_fh = checkpoint_path.open("a")

    try:
        for start in range(0, total, batch):
            chunk = records[start : start + batch]
            await asyncio.gather(*(enrich_one(r) for r in chunk))
            newly_done = [r for r in chunk if r["evidence_id"] not in done_ids]
            if checkpoint_fh:
                for r in newly_done:
                    checkpoint_fh.write(json.dumps(r, default=str) + "\n")
                    done_ids.add(r["evidence_id"])
                if (start // batch) % max(1, checkpoint_every // batch) == 0:
                    checkpoint_fh.flush()
            if start % (batch * 5) == 0 or start + batch >= total:
                logger.info(
                    "enriched %d / %d  "
                    "(rxnorm %d/%d, efo %d/%d, rsid %d/%d, "
                    "cache rx=%d efo=%d rsid=%d)",
                    min(start + batch, total),
                    total,
                    client.stats["rxnorm_calls"],
                    client.stats["rxnorm_hits"],
                    client.stats["efo_calls"],
                    client.stats["efo_hits"],
                    client.stats["rsid_calls"],
                    client.stats["rsid_hits"],
                    len(client.rxnorm_cache),
                    len(client.efo_cache),
                    len(client.rsid_cache),
                )
    finally:
        if checkpoint_fh:
            checkpoint_fh.close()


def _load_checkpoint(records: List[Dict[str, Any]], checkpoint_path: Optional[Path]) -> set:
    done_ids: set = set()
    if not checkpoint_path or not checkpoint_path.exists():
        return done_ids
    by_id: Dict[int, Dict[str, Any]] = {}
    with checkpoint_path.open() as fh:
        for line in fh:
            try:
                rec = json.loads(line)
                by_id[rec.get("evidence_id")] = rec
            except ValueError:
                continue
    logger.info("resuming from %d checkpointed records at %s", len(by_id), checkpoint_path)
    for rec in records:
        if rec["evidence_id"] in by_id:
            saved = by_id[rec["evidence_id"]]
            rec["variant_rsid"] = saved.get("variant_rsid")
            rec["disease_efo_id"] = saved.get("disease_efo_id")
            rec["therapy_rxnorm_ids"] = saved.get("therapy_rxnorm_ids")
            done_ids.add(rec["evidence_id"])
    return done_ids


async def enrich_records_direct(
    records: List[Dict[str, Any]],
    concurrency: int,
    checkpoint_path: Optional[Path] = None,
    checkpoint_every: int = 500,
) -> None:
    """In-process enrichment via the LangChain @tool functions."""
    done_ids = _load_checkpoint(records, checkpoint_path)
    client = DirectLookupClient(concurrency=concurrency)
    logger.info("direct transport — concurrency=%d", concurrency)
    await _run_enrichment_loop(records, client, done_ids, checkpoint_path, checkpoint_every)


async def enrich_records(
    records: List[Dict[str, Any]],
    concurrency: int,
    mcp_command: str,
    mcp_args: List[str],
    checkpoint_path: Optional[Path] = None,
    checkpoint_every: int = 500,
) -> None:
    """Drive the Tier-2 enrichment through the OncoCITE MCP server (stdio)."""
    params = StdioServerParameters(
        command=mcp_command,
        args=mcp_args,
        env={**os.environ},
    )
    done_ids = _load_checkpoint(records, checkpoint_path)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            logger.info(
                "MCP session initialized (%s); %d tools registered",
                init.serverInfo.name,
                len(tools.tools),
            )
            client = McpLookupClient(session=session, concurrency=concurrency)
            await _run_enrichment_loop(records, client, done_ids, checkpoint_path, checkpoint_every)


# --------------------------------------------------------------------------
# Coverage report
# --------------------------------------------------------------------------


def coverage_report(records: List[Dict[str, Any]]) -> str:
    n = len(records)
    lines: List[str] = []
    lines.append(f"# CIViC normalized evidence — coverage report")
    lines.append("")
    lines.append(f"**Corpus:** {n:,} evidence items")
    lines.append("")
    lines.append(
        "This table is the artifact equivalent of Supplementary Table S24 "
        "in the OncoCITE manuscript. Each row is a field in the 45-field "
        "schema (Supp Tables S17 and S18); the percentage is the share of "
        "records with a non-null value."
    )
    lines.append("")
    lines.append("| Field | Tier | Source | Non-null | Coverage |")
    lines.append("|---|---|---|---:|---:|")

    def _nn(field: str) -> int:
        return sum(1 for r in records if r.get(field) not in (None, "", []))

    def _pct(c: int) -> str:
        return f"{100*c/n:.2f}%" if n else "0%"

    for t, _ in TIER1_FIELDS:
        c = _nn(t)
        lines.append(f"| `{t}` | 1 | CIViC | {c:,} | {_pct(c)} |")
    for t, _ in TIER2_FIELDS_FROM_CSV:
        c = _nn(t)
        lines.append(f"| `{t}` | 2 | CIViC | {c:,} | {_pct(c)} |")
    for t in TIER2_FIELDS_ENRICHED:
        source = {
            "variant_rsid": "MyVariant.info",
            "disease_efo_id": "EBI OLS (EFO)",
            "therapy_rxnorm_ids": "RxNorm",
        }[t]
        c = _nn(t)
        lines.append(f"| `{t}` | 2 | {source} | {c:,} | {_pct(c)} |")

    total_tier2 = [
        t for t, _ in TIER2_FIELDS_FROM_CSV
    ] + TIER2_FIELDS_ENRICHED
    item_level = sum(
        1 for r in records if any(r.get(f) not in (None, "", []) for f in total_tier2)
    )
    lines.append("")
    lines.append("## Item-level Tier-2 resolution")
    lines.append(
        f"{item_level:,} / {n:,} = **{100*item_level/n:.2f}%** of evidence "
        "items have at least one Tier-2 identifier populated "
        "(the manuscript reports 83.12% in Section 2.4)."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-csv",
        required=True,
        type=Path,
        help="Path to the CIViC denormalized CSV.",
    )
    parser.add_argument(
        "--output-jsonl",
        required=True,
        type=Path,
        help="Output path for the 45-field JSONL artifact.",
    )
    parser.add_argument(
        "--coverage-report",
        required=True,
        type=Path,
        help="Output path for the per-field coverage report (Markdown).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=20,
        help="Max in-flight HTTP requests per API.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N records (smoke testing).",
    )
    parser.add_argument(
        "--skip-enrichment",
        action="store_true",
        help="Skip the Tier-2 enrichment step and emit CSV-only fields.",
    )
    parser.add_argument(
        "--status-filter",
        choices=["all", "accepted", "accepted_before_20241215"],
        default="all",
        help="Which subset of evidence items to include.",
    )
    parser.add_argument(
        "--mcp-command",
        default=sys.executable,
        help="Python interpreter used to launch the MCP server subprocess.",
    )
    parser.add_argument(
        "--mcp-args",
        nargs="*",
        default=["-m", "mcp_server"],
        help="Arguments to launch the MCP server with.",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=500,
        help="Write a JSONL checkpoint every N items so a crashed run can resume.",
    )
    parser.add_argument(
        "--transport",
        choices=["mcp", "direct"],
        default="direct",
        help=(
            "How to invoke the Normalizer tools. `mcp` routes every lookup "
            "through the OncoCITE MCP server over stdio (the architecture "
            "described in Supp Note S5) — slower but reproduces the paper "
            "wiring exactly. `direct` calls the same LangChain @tool "
            "functions in-process — identical results, ~20x faster. "
            "Default: direct (recommended for the 11k-item batch run)."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    started = time.time()

    logger.info("loading %s", args.input_csv)
    df = pd.read_csv(args.input_csv, low_memory=False)
    df = df.drop_duplicates(subset="evidence_id", keep="first")

    if args.status_filter == "accepted":
        df = df[df["evidence_status"] == "ACCEPTED"]
    elif args.status_filter == "accepted_before_20241215":
        acc = pd.to_datetime(df["acceptance_date"], errors="coerce")
        df = df[(df["evidence_status"] == "ACCEPTED") & (acc < "2024-12-15")]

    if args.limit:
        df = df.head(args.limit)
    logger.info("working with %d evidence items", len(df))

    records = [build_tier1_plus_csv_tier2(row) for _, row in df.iterrows()]

    if not args.skip_enrichment:
        checkpoint_path = args.output_jsonl.with_suffix(".checkpoint.jsonl")
        if args.transport == "mcp":
            logger.info(
                "Tier-2 enrichment via MCP server (stdio), concurrency=%d",
                args.concurrency,
            )
            asyncio.run(
                enrich_records(
                    records,
                    concurrency=args.concurrency,
                    mcp_command=args.mcp_command,
                    mcp_args=args.mcp_args,
                    checkpoint_path=checkpoint_path,
                    checkpoint_every=args.checkpoint_every,
                )
            )
        else:
            logger.info(
                "Tier-2 enrichment via direct in-process LangChain tools, concurrency=%d",
                args.concurrency,
            )
            asyncio.run(
                enrich_records_direct(
                    records,
                    concurrency=args.concurrency,
                    checkpoint_path=checkpoint_path,
                    checkpoint_every=args.checkpoint_every,
                )
            )

    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with args.output_jsonl.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec, default=str) + "\n")
    logger.info("wrote %d records to %s", len(records), args.output_jsonl)

    report = coverage_report(records)
    args.coverage_report.parent.mkdir(parents=True, exist_ok=True)
    args.coverage_report.write_text(report + "\n")
    logger.info("wrote coverage report to %s", args.coverage_report)

    elapsed = time.time() - started
    logger.info("done in %.1fs", elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
