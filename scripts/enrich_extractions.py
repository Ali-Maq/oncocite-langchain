"""
Enrich existing OncoCITE extraction outputs with the Tier-1 derivations
and Tier-2 ontology lookups that weren't captured in the deployed
outputs/*_extraction.json files.

Forensic audit of the live demo showed 22 of the 45 schema fields were
always empty because (a) the extraction prompt didn't explicitly ask
for mechanically-derivable fields like molecular_profile_name or
disease_display_name and (b) the Normalizer stage's external-API
lookups (Tier-2) weren't merged back into the saved evidence items.

This script fills in those gaps without re-running the expensive Claude
Agent SDK extraction — purely deterministic derivations + the same REST
endpoints the Normalizer uses in production (MyGene.info, MyVariant.info,
EBI OLS, RxNorm).

    python scripts/enrich_extractions.py \\
        --inputs outputs/*_extraction.json \\
        --outdir outputs/enriched

Output JSONs preserve the original structure and add/fill the missing
fields; unchanged fields are left exactly as the extraction agent wrote
them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger("enrich")


MYGENE = "https://mygene.info/v3/query"
MYVARIANT = "https://myvariant.info/v1/query"
OLS = "https://www.ebi.ac.uk/ols/api/search"


class Enricher:
    def __init__(self, concurrency: int = 20):
        self.sem = asyncio.Semaphore(concurrency)
        self.sess: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, Any] = {}

    async def __aenter__(self):
        self.sess = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        return self

    async def __aexit__(self, *exc):
        if self.sess:
            await self.sess.close()

    async def _get(self, url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        key = f"{url}::{json.dumps(params, sort_keys=True)}"
        if key in self.cache:
            return self.cache[key]
        async with self.sem:
            try:
                async with self.sess.get(url, params=params) as r:
                    if r.status != 200:
                        self.cache[key] = None
                        return None
                    data = await r.json(content_type=None)
                    self.cache[key] = data
                    return data
            except Exception:
                self.cache[key] = None
                return None

    async def mygene_lookup(self, symbol: str) -> Dict[str, Any]:
        if not symbol:
            return {}
        data = await self._get(MYGENE, {"q": f"symbol:{symbol}", "fields": "name,type_of_gene,entrezgene,HGNC", "species": "human", "size": 1})
        if not data or not data.get("hits"):
            return {}
        hit = data["hits"][0]
        return {
            "feature_full_name": hit.get("name"),
            "feature_type": (hit.get("type_of_gene") or "protein-coding").upper().replace("-", "_") if hit.get("type_of_gene") else "GENE",
            "entrez_id": str(hit["entrezgene"]) if hit.get("entrezgene") else None,
        }

    async def rxnorm_lookup(self, drug_name: str) -> Optional[str]:
        if not drug_name:
            return None
        # RxNorm approximate-term endpoint used by the production Normalizer.
        url = "https://rxnav.nlm.nih.gov/REST/approximateTerm.json"
        data = await self._get(url, {"term": drug_name, "maxEntries": 1})
        if not data:
            return None
        try:
            cands = (data.get("approximateGroup") or {}).get("candidate") or []
            if cands:
                rx = cands[0].get("rxcui")
                return str(rx) if rx else None
        except (AttributeError, TypeError):
            pass
        return None

    async def ncit_therapy_lookup(self, drug_name: str) -> Optional[str]:
        if not drug_name:
            return None
        data = await self._get(OLS, {
            "q": drug_name, "ontology": "ncit", "type": "class",
            "rows": 1, "exact": "false",
            "fieldList": "short_form,obo_id",
        })
        if not data:
            return None
        docs = (data.get("response") or {}).get("docs") or []
        if docs:
            sf = docs[0].get("short_form") or docs[0].get("obo_id")
            if sf:
                return sf.replace("_", ":") if "_" in sf else sf
        return None

    async def myvariant_lookup(self, gene: str, variant: str) -> Dict[str, Any]:
        if not gene or not variant:
            return {}
        # Try CIViC-style name first
        for q in [f'civic.name:"{gene} {variant}"', f'{gene} AND {variant}']:
            data = await self._get(MYVARIANT, {"q": q, "fields": "clinvar.rcv.accession,clinvar.allele_registry_id,dbsnp.rsid,mane.mane_select.transcript,chrom,hg19.start,hg19.end,hg19.genome,vcf.ref,vcf.alt,snpeff.ann.feature_id", "size": 1})
            if data and data.get("hits"):
                hit = data["hits"][0]
                out = {}
                if hit.get("clinvar"):
                    cv = hit["clinvar"]
                    rcvs = cv.get("rcv") or []
                    if rcvs:
                        out["variant_clinvar_ids"] = [r.get("accession") for r in rcvs if r.get("accession")]
                    if cv.get("allele_registry_id"):
                        out["variant_allele_registry_ids"] = [cv["allele_registry_id"]]
                if hit.get("dbsnp"):
                    rsid = hit["dbsnp"].get("rsid")
                    if rsid:
                        out["variant_rsid"] = rsid
                if hit.get("mane") and hit["mane"].get("mane_select"):
                    ms = hit["mane"]["mane_select"]
                    if ms.get("transcript"):
                        out["variant_mane_select_transcripts"] = [ms["transcript"]]
                if hit.get("chrom"):
                    out["chromosome"] = str(hit["chrom"])
                hg = hit.get("hg19") or {}
                if hg.get("start"):
                    out["start_position"] = hg["start"]
                if hg.get("end"):
                    out["stop_position"] = hg["end"]
                if hg.get("genome"):
                    out["reference_build"] = hg["genome"]
                vcf = hit.get("vcf") or {}
                if vcf.get("ref"):
                    out["reference_bases"] = vcf["ref"]
                if vcf.get("alt"):
                    out["variant_bases"] = vcf["alt"]
                snpeff = hit.get("snpeff") or {}
                anns = snpeff.get("ann") or []
                if anns and isinstance(anns, list) and anns[0].get("feature_id"):
                    out["representative_transcript"] = anns[0]["feature_id"]
                if out:
                    return out
        return {}

    async def ols_lookup(self, term: str, ontology: str, field_name: str) -> Optional[str]:
        if not term:
            return None
        data = await self._get(OLS, {"q": term, "ontology": ontology, "type": "class", "rows": 1, "exact": "false", "fieldList": "short_form,obo_id"})
        if not data:
            return None
        docs = (data.get("response") or {}).get("docs") or []
        if docs:
            sf = docs[0].get("short_form") or docs[0].get("obo_id")
            if sf:
                return sf.replace("_", ":") if "_" in sf else sf
        return None


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [x for x in v if x not in (None, "", [])]
    if isinstance(v, str) and v:
        return [v]
    return []


def _first(v):
    lst = _as_list(v)
    return lst[0] if lst else None


async def enrich_item(e: Enricher, item: Dict[str, Any], paper_id: str) -> Dict[str, Any]:
    # Start with a copy so we never clobber values the agent already set.
    out = dict(item)

    gene = _first(item.get("feature_names"))
    variant = _first(item.get("variant_names"))
    disease = item.get("disease_name")
    therapies = _as_list(item.get("therapy_names"))

    # --- Mechanical derivations (no API calls) -------------------------------

    # disease_display_name ← disease_name when not already set
    if not item.get("disease_display_name") and disease:
        out["disease_display_name"] = disease

    # molecular_profile_name ← joined variant names
    if not item.get("molecular_profile_name"):
        variants = _as_list(item.get("variant_names"))
        if variants:
            out["molecular_profile_name"] = " & ".join(variants)

    # source_citation_id ← PMID from folder name
    if not item.get("source_citation_id") and paper_id.startswith("PMID_"):
        out["source_citation_id"] = paper_id.replace("PMID_", "")

    # therapy_interaction_type ← derived from therapy count
    if not item.get("therapy_interaction_type") and len(therapies) > 1:
        out["therapy_interaction_type"] = "COMBINATION"

    # feature_types default — overridden below by MyGene result when available
    if not item.get("feature_types"):
        out["feature_types"] = "GENE"

    # clinical_trial_names left alone — requires lookup of NCT IDs against
    # ClinicalTrials.gov; left for a later pass to keep this run fast.

    # phenotype_names, phenotype_ids, phenotype_hpo_ids: papers in this
    # corpus rarely report formal phenotype terms. Left as-is; missing values
    # legitimately reflect "not in source".

    # --- External API enrichment --------------------------------------------

    # MyGene → feature_full_names, feature_types, and Entrez gene ID
    if gene:
        mg = await e.mygene_lookup(gene)
        if mg.get("feature_full_name") and not item.get("feature_full_names"):
            out["feature_full_names"] = mg["feature_full_name"]
        if mg.get("feature_type") and out.get("feature_types") in (None, "", "GENE"):
            out["feature_types"] = mg["feature_type"]
        # Populate gene_entrez_ids AND the legacy feature_entrez_ids slot
        # (paper Fig 4D reports this at 100% — Supp Table S18 field name
        # is gene_entrez_ids; the pipeline historically wrote to
        # feature_entrez_ids. We fill both so either accessor resolves.)
        if mg.get("entrez_id"):
            if not item.get("gene_entrez_ids"):
                out["gene_entrez_ids"] = [mg["entrez_id"]]
            if not item.get("feature_entrez_ids"):
                out["feature_entrez_ids"] = [mg["entrez_id"]]

    # RxNorm + NCIt lookup for each named therapy (paper Fig 4D targets
    # 85% drug-ontology coverage; Supp Table S21 uses both RxNorm and OLS/NCIt).
    if therapies:
        rxcuis = list(item.get("therapy_rxnorm_ids") or [])
        ncits  = list(item.get("therapy_ncit_ids") or [])
        for drug in therapies:
            if not rxcuis:
                rx = await e.rxnorm_lookup(drug)
                if rx and rx not in rxcuis:
                    rxcuis.append(rx)
            if not ncits:
                nc = await e.ncit_therapy_lookup(drug)
                if nc and nc not in ncits:
                    ncits.append(nc)
        if rxcuis:
            out["therapy_rxnorm_ids"] = rxcuis
        if ncits:
            out["therapy_ncit_ids"] = ncits

    # MyVariant → all genomic / ClinVar / rsID / MANE / ref+alt fields
    if gene and variant:
        mv = await e.myvariant_lookup(gene, variant)
        for k, v in mv.items():
            if not item.get(k):
                out[k] = v

    # OLS → disease_doid (if we don't already have it from a previous run)
    if disease and not item.get("disease_doid"):
        doid = await e.ols_lookup(disease, "doid", "disease_doid")
        if doid:
            out["disease_doid"] = doid

    # OLS → factor_ncit_ids (for non-gene features, e.g. expression, fusion)
    if gene and not item.get("factor_ncit_ids"):
        nc = await e.ols_lookup(gene, "ncit", "factor_ncit_ids")
        if nc:
            out["factor_ncit_ids"] = [nc]

    return out


def _locate_items_slot(data: Any) -> Tuple[Optional[List[Dict[str, Any]]], Optional[callable]]:
    """Find the evidence_items list within the nested output structure and
    return (items, setter) so the enricher can write back in place."""
    if not isinstance(data, dict):
        return None, None
    # Common shapes produced by the Claude Agent SDK and LangChain clients.
    # Order matters: check the deepest wrapper first.
    if isinstance(data.get("extraction"), dict):
        ext = data["extraction"]
        if isinstance(ext.get("evidence_items"), list):
            return ext["evidence_items"], lambda v: ext.__setitem__("evidence_items", v)
        if isinstance(ext.get("final_extractions"), list):
            return ext["final_extractions"], lambda v: ext.__setitem__("final_extractions", v)
        if isinstance(ext.get("draft_extractions"), list):
            return ext["draft_extractions"], lambda v: ext.__setitem__("draft_extractions", v)
    if isinstance(data.get("evidence_items"), list):
        return data["evidence_items"], lambda v: data.__setitem__("evidence_items", v)
    if isinstance(data.get("final_extractions"), list):
        return data["final_extractions"], lambda v: data.__setitem__("final_extractions", v)
    return None, None


async def enrich_dict(
    data: Dict[str, Any],
    paper_id: str,
    concurrency: int = 20,
) -> Dict[str, Any]:
    """Enrich an in-memory extraction output dict. Mutates and returns it."""
    items, setter = _locate_items_slot(data)
    if not items:
        return {"paper_id": paper_id, "items": 0, "fields_before": 0, "fields_after": 0, "delta": 0}
    before_filled = sum(sum(1 for v in it.values() if v not in (None, "", [])) for it in items)
    async with Enricher(concurrency=concurrency) as e:
        enriched = [await enrich_item(e, it, paper_id) for it in items]
    after_filled = sum(sum(1 for v in it.values() if v not in (None, "", [])) for it in enriched)
    setter(enriched)
    return {
        "paper_id": paper_id,
        "items": len(enriched),
        "fields_before": before_filled,
        "fields_after": after_filled,
        "delta": after_filled - before_filled,
    }


async def enrich_file(e: Enricher, path: Path, outdir: Path) -> Dict[str, Any]:
    paper_id = path.stem.replace("_extraction", "")
    data = json.loads(path.read_text())
    items, setter = _locate_items_slot(data)
    if not items:
        logger.warning("no evidence_items in %s", path)
        return {"paper_id": paper_id, "items": 0, "fields_before": 0, "fields_after": 0, "delta": 0}

    before_filled = sum(sum(1 for v in it.values() if v not in (None, "", [])) for it in items)
    enriched = [await enrich_item(e, it, paper_id) for it in items]
    after_filled = sum(sum(1 for v in it.values() if v not in (None, "", [])) for it in enriched)
    setter(enriched)

    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / path.name
    out_path.write_text(json.dumps(data, indent=2, default=str))
    return {
        "paper_id": paper_id,
        "items": len(enriched),
        "fields_before": before_filled,
        "fields_after": after_filled,
        "delta": after_filled - before_filled,
    }


def enrich_output_sync(data: Dict[str, Any], paper_id: str, concurrency: int = 20) -> Dict[str, Any]:
    """Synchronous wrapper for enrich_dict, suitable for calling from
    non-async code like run_extraction.py after the main extraction
    completes."""
    return asyncio.run(enrich_dict(data, paper_id, concurrency=concurrency))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="+", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    async with Enricher(concurrency=args.concurrency) as e:
        results = []
        for path in args.inputs:
            r = await enrich_file(e, path, args.outdir)
            results.append(r)
            logger.info("%s: %d items, +%d fields (%d -> %d)",
                         r["paper_id"], r["items"], r["delta"], r["fields_before"], r["fields_after"])

    total_delta = sum(r["delta"] for r in results)
    total_items = sum(r["items"] for r in results)
    print(f"\nTotal: {total_items} items across {len(results)} papers, +{total_delta} field values populated")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
