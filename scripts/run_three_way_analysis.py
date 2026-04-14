#!/usr/bin/env python
"""
Three-way validation agent — reproduces the analysis pipeline described in
Section 2.7 / 4.5 / Supplementary Figure S6 of the OncoCITE manuscript.

For each paper in the retrospective Multiple Myeloma corpus we have three
views of the evidence: (1) the source publication itself, (2) the
CIViC-curated ground truth, (3) the OncoCITE system extraction. The paper
text is treated as the sole ground truth; CIViC and OncoCITE are both
evaluated against it.

This script spawns an independent analysis agent in a fresh Claude 3.5
Sonnet session (`claude-3-5-sonnet-20241022`, temperature 0.0) that:

  * reads all three inputs,
  * performs tuple-by-tuple alignment on
    Gene - Variant - Disease - Therapy keys, applying the paper's
    aliasing rules (NY-ESO-1 / CTAG1B, PKC412 / Midostaurin, ...) and
    the L1 (Exact) / L2 (Core) / L3 (Subsumption, e.g. CODON 12
    MUTATION -> G12A/C/D/S) matching hierarchy,
  * emits an `analysis.json` matching the schema already present for
    the 10 retrospective papers under test_paper/triplet/.

Session isolation: each paper is processed in its own single-shot
Bedrock call so there is no cross-paper state — the "separate session"
requirement in Sec 4.5.

Usage:
    python scripts/run_three_way_analysis.py \\
        --pdf test_paper/triplet/PMID_12483530/PMID_12483530.pdf \\
        --ground-truth test_paper/triplet/PMID_12483530/PMID_12483530_ground_truth.json \\
        --extraction test_paper/triplet/PMID_12483530/PMID_12483530_extraction.json \\
        --output test_paper/triplet/PMID_12483530/analysis.regenerated.json

Credentials: by default uses the `mssm-bedrock` AWS profile in
`ap-south-1` (Mumbai inference profile for Claude 3.5 Sonnet). The
validation corpus is entirely public published literature, so
residency is not a concern; do NOT send PHI through this pipeline.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from anthropic import AnthropicBedrock

logger = logging.getLogger("three_way_analysis")

# ---------------------------------------------------------------------------
# Paper Sec 4.5: hierarchical matching + aliasing
# ---------------------------------------------------------------------------

# Standard gene aliases explicitly called out in Sec 4.5.
GENE_ALIASES: Dict[str, str] = {
    "NY-ESO-1": "CTAG1B",
    "CTAG1B": "CTAG1B",
    "LAGE-1": "CTAG2",
    "CTAG2": "CTAG2",
}

# Drug name equivalences explicitly called out in Sec 4.5.
DRUG_ALIASES: Dict[str, str] = {
    "PKC412": "Midostaurin",
    "MIDOSTAURIN": "Midostaurin",
    "PLX4032": "Vemurafenib",
    "VEMURAFENIB": "Vemurafenib",
}

CODON_RE = re.compile(r"CODON\s+(\d+)\s+MUTATION", re.IGNORECASE)
POINTMUT_RE = re.compile(r"([A-Z])(\d+)([A-Z*])")  # e.g. G12A, V600E


def _norm(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return re.sub(r"\s+", " ", str(value)).strip()


def canonical_gene(name: str) -> str:
    u = _norm(name).upper()
    return GENE_ALIASES.get(u, u)


def canonical_drug(name: str) -> str:
    u = _norm(name).upper()
    return DRUG_ALIASES.get(u, _norm(name).title())


def tuple_key(item: Dict[str, Any]) -> str:
    """Paper Sec 4.5 tuple key — Gene|Variant|Disease|Therapy."""
    gene = canonical_gene(item.get("feature_names") or item.get("gene_name") or "")
    variant = _norm(item.get("variant_names") or item.get("variant_name") or "")
    disease = _norm(item.get("disease_name") or item.get("disease_display_name") or "")
    therapy_raw = item.get("therapy_names") or item.get("drugs") or ""
    therapy = canonical_drug(therapy_raw if not isinstance(therapy_raw, list) else (therapy_raw[0] if therapy_raw else ""))
    return f"{gene}|{variant}|{disease}|{therapy}"


def match_level(gt: Dict[str, Any], ai: Dict[str, Any]) -> str:
    """Paper Sec 4.5 L1/L2/L3/NONE matching hierarchy."""
    g_key = tuple_key(gt)
    a_key = tuple_key(ai)
    if g_key == a_key:
        return "L1"  # Exact: all core fields match

    # Disease names can contain '|' in some CIViC entries — only split into 4.
    g_parts = g_key.split("|", 3)
    a_parts = a_key.split("|", 3)
    if len(g_parts) < 4 or len(a_parts) < 4:
        return "NONE"
    gg, gv, gd, gt_th = g_parts
    ag, av, ad, at_th = a_parts

    # L2 Core: gene + disease + evidence direction
    if (gg == ag and gd == ad and _norm(gt.get("evidence_direction")).upper()
            == _norm(ai.get("evidence_direction")).upper()):
        return "L2"

    # L3 Subsumption: codon -> specific amino acid change
    if gg == ag and gd == ad:
        codon_match = CODON_RE.search(gv or "")
        point_match = POINTMUT_RE.match(av or "")
        if codon_match and point_match and codon_match.group(1) == point_match.group(2):
            return "L3"

    return "NONE"


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def extract_pdf_text(pdf_path: Path, max_chars_per_page: int = 4000) -> str:
    doc = fitz.open(pdf_path)
    pages: List[str] = []
    for i in range(doc.page_count):
        text = doc[i].get_text("text") or ""
        if len(text) > max_chars_per_page:
            text = text[:max_chars_per_page] + "\n[... page truncated ...]"
        pages.append(f"\n=== PAGE {i + 1} ===\n{text.strip()}")
    doc.close()
    return "\n".join(pages)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an INDEPENDENT analysis agent performing three-way validation of clinical oncology evidence extraction, as described in the OncoCITE manuscript (Research Square preprint 10.21203/rs.3.rs-9160944/v1), Section 4.5 "Three-Way Validation Framework".

METHOD:
- The ORIGINAL SCIENTIFIC PUBLICATION is the sole source of truth.
- Neither CIViC curation NOR OncoCITE extraction is authoritative; BOTH are evaluated against the paper text.
- For each {Gene, Variant, Disease, Therapy} tuple present in CIViC and/or OncoCITE, assess whether the paper supports it.
- Apply paper-prescribed matching hierarchy: L1 Exact (all core fields), L2 Core (gene + disease + evidence direction), L3 Subsumption (codon-level variants match specific AA changes, e.g. CODON 12 MUTATION matches G12A/G12C/G12D/G12S).
- Apply paper-prescribed aliases: NY-ESO-1 == CTAG1B, LAGE-1 == CTAG2, PKC412 == Midostaurin, PLX4032 == Vemurafenib.

For each field in each evidence item, assign one of these status codes per Sec 4.5:
- EXACT_MATCH_WITH_PAPER
- PARTIAL_MATCH_OR_UNDER_SPECIFIED
- CORRECT_BUT_MISSING_IN_GROUND_TRUTH
- OVER_SPECIFIED_BEYOND_PAPER
- CONTRADICTS_PAPER

OUTPUT:
Respond with a SINGLE valid JSON object matching the schema described below. No prose outside the JSON. No markdown code fences. Start the response with `{` and end with `}`.
"""

JSON_SCHEMA_HINT = """
SCHEMA (match exactly; use null for unknown scalar fields, [] for unknown lists):
{
  "paper_id": "<string, matches the --paper-id the caller provided>",
  "total_true_items_in_paper_estimate": <int, your best count of distinct evidence tuples genuinely supported by the paper>,
  "ai_evidence_item_count": <int, count of distinct items in the OncoCITE extraction input>,
  "gt_evidence_item_count": <int, count of distinct items in the CIViC ground-truth input>,
  "alignment": [
    {
      "tuple_id": "<GENE|VARIANT|DISEASE|THERAPY>",
      "paper_evidence": {
        "summary": "<what the paper says about this tuple>",
        "location": "<section / figure / page references>",
        "quantitative_data": "<numeric support from the paper, or '' if none>",
        "evidence_type": "<PREDICTIVE|DIAGNOSTIC|PROGNOSTIC|PREDISPOSING|ONCOGENIC|FUNCTIONAL>",
        "evidence_level": "<A|B|C|D|E>",
        "evidence_direction": "<SUPPORTS|DOES_NOT_SUPPORT>",
        "evidence_significance": "<paper-implied significance enum, e.g. RESISTANCE>"
      },
      "ai_items": [ { "ai_index": <int>, "fields": { <the OncoCITE item fields verbatim> } } ],
      "gt_items": [ { <the CIViC ground-truth item fields verbatim> } ],
      "field_status": {
        "<field_name>": "<one of EXACT_MATCH_WITH_PAPER | PARTIAL_MATCH_OR_UNDER_SPECIFIED | CORRECT_BUT_MISSING_IN_GROUND_TRUTH | OVER_SPECIFIED_BEYOND_PAPER | CONTRADICTS_PAPER>"
      },
      "match_level_gt_to_paper": "<L1|L2|L3|NONE>",
      "match_level_ai_to_paper": "<L1|L2|L3|NONE>",
      "notes": "<one or two sentences flagging any discrepancy for expert adjudication>"
    }
  ],
  "missing_from_ai": [
    { "gt_index": <int>, "tuple_id": "<...>", "reason_missing": "<paper-backed explanation>" }
  ],
  "ai_hallucinated_items": [
    { "ai_index": <int>, "tuple_id": "<...>", "paper_contradicts_with": "<quote or location>" }
  ],
  "ai_improvements_over_gt": [
    { "ai_index": <int>, "tuple_id": "<...>", "improvement_type": "CORRECT_BUT_MISSING_IN_GROUND_TRUTH|OVER_SPECIFIED_BEYOND_PAPER|OTHER", "paper_support": "<quote or location>" }
  ],
  "overall_judgement": {
    "summary": "<2-4 sentences on overall extraction quality for this paper>",
    "strengths": [ "<string>", ... ],
    "weaknesses": [ "<string>", ... ]
  }
}
"""


def build_user_prompt(
    paper_id: str,
    paper_text: str,
    ground_truth: Any,
    extraction: Any,
    precomputed_matches: List[Dict[str, Any]],
) -> str:
    gt_json = json.dumps(ground_truth, indent=2, default=str)
    ex_json = json.dumps(extraction, indent=2, default=str)
    matches_json = json.dumps(precomputed_matches, indent=2)

    return f"""PAPER_ID: {paper_id}

=========================
PAPER FULL TEXT
=========================
{paper_text}

=========================
CIViC GROUND TRUTH ITEMS
=========================
{gt_json}

=========================
ONCOCITE EXTRACTION ITEMS
=========================
{ex_json}

=========================
PRECOMPUTED DETERMINISTIC MATCHES (L1/L2/L3)
=========================
These are generated by deterministic Python logic per paper Sec 4.5 aliasing + hierarchy rules — use them as a starting point but override when the paper text reveals a better alignment.

{matches_json}

=========================
TASK
=========================
Produce the analysis.json for PAPER_ID = {paper_id} following the schema below. Return ONLY the JSON object.

{JSON_SCHEMA_HINT}
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _as_list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        for key in ("evidence_items", "items", "final_extractions", "extractions"):
            v = value.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        return [value]
    return []


def _flatten_extraction(extraction_doc: Any) -> List[Dict[str, Any]]:
    """The OncoCITE extraction JSON wraps items in an `extraction` block."""
    if isinstance(extraction_doc, dict):
        for key in (
            "final_extractions",
            "evidence_items",
            "extraction",
            "items",
        ):
            v = extraction_doc.get(key)
            if v is not None:
                if isinstance(v, dict):
                    for k2 in ("evidence_items", "final_extractions", "items"):
                        if k2 in v:
                            v = v[k2]
                            break
                flat = _as_list_of_dicts(v)
                if flat:
                    return flat
    return _as_list_of_dicts(extraction_doc)


def precompute_matches(
    gt_items: List[Dict[str, Any]], ai_items: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    rows = []
    for gi, g in enumerate(gt_items):
        for ai, a in enumerate(ai_items):
            lvl = match_level(g, a)
            if lvl != "NONE":
                rows.append(
                    {
                        "gt_index": gi,
                        "ai_index": ai,
                        "match_level": lvl,
                        "gt_tuple": tuple_key(g),
                        "ai_tuple": tuple_key(a),
                    }
                )
    return rows


def invoke_agent(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    aws_profile: str,
    aws_region: str,
) -> Tuple[str, Dict[str, int]]:
    client = AnthropicBedrock(aws_profile=aws_profile, aws_region=aws_region)
    t0 = time.time()
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    elapsed = time.time() - t0
    text = "".join(
        block.text for block in msg.content if getattr(block, "type", "") == "text"
    )
    usage = {
        "input_tokens": msg.usage.input_tokens,
        "output_tokens": msg.usage.output_tokens,
        "elapsed_sec": round(elapsed, 1),
    }
    return text, usage


def parse_json_response(text: str) -> Dict[str, Any]:
    # Trim code fences and stray prose defensively.
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    # Extract the first top-level JSON object.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object found in model response")
    return json.loads(stripped[start : end + 1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--extraction", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--paper-id", default=None)
    parser.add_argument(
        "--model",
        default="apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
        help="Bedrock inference profile ID. Default matches paper Supp S3.4 model.",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=16000)
    parser.add_argument("--aws-profile", default="mssm-bedrock")
    parser.add_argument("--aws-region", default="ap-south-1")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )

    paper_id = args.paper_id or args.pdf.stem
    logger.info("paper_id=%s", paper_id)

    logger.info("extracting PDF text from %s", args.pdf)
    paper_text = extract_pdf_text(args.pdf)
    logger.info("PDF text length: %d chars", len(paper_text))

    gt_raw = json.loads(args.ground_truth.read_text())
    ex_raw = json.loads(args.extraction.read_text())
    gt_items = _as_list_of_dicts(gt_raw)
    ai_items = _flatten_extraction(ex_raw)
    logger.info("ground truth items: %d | extraction items: %d", len(gt_items), len(ai_items))

    matches = precompute_matches(gt_items, ai_items)
    logger.info("deterministic matches: %d", len(matches))

    user_prompt = build_user_prompt(
        paper_id=paper_id,
        paper_text=paper_text,
        ground_truth=gt_items,
        extraction=ai_items,
        precomputed_matches=matches,
    )

    logger.info("invoking Bedrock (%s, region=%s)", args.model, args.aws_region)
    text, usage = invoke_agent(
        SYSTEM_PROMPT,
        user_prompt,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        aws_profile=args.aws_profile,
        aws_region=args.aws_region,
    )
    logger.info(
        "response received: %d input tokens, %d output tokens, %.1fs",
        usage["input_tokens"],
        usage["output_tokens"],
        usage["elapsed_sec"],
    )

    try:
        parsed = parse_json_response(text)
    except (ValueError, json.JSONDecodeError) as e:
        # Retry once asking the model to fix the JSON.
        logger.warning("JSON parse failed (%s); retrying with repair prompt", e)
        repair_prompt = (
            "Your previous response was not a single valid JSON object. "
            "Return the JSON object only — no prose, no fences. "
            "The failed response was:\n\n" + text[:8000]
        )
        text2, usage2 = invoke_agent(
            SYSTEM_PROMPT,
            repair_prompt,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            aws_profile=args.aws_profile,
            aws_region=args.aws_region,
        )
        parsed = parse_json_response(text2)
        usage = {
            "input_tokens": usage["input_tokens"] + usage2["input_tokens"],
            "output_tokens": usage["output_tokens"] + usage2["output_tokens"],
            "elapsed_sec": usage["elapsed_sec"] + usage2["elapsed_sec"],
        }

    # Paper Sec 4.5: per-paper summary fields should exist.
    parsed.setdefault("paper_id", paper_id)
    parsed.setdefault("gt_evidence_item_count", len(gt_items))
    parsed.setdefault("ai_evidence_item_count", len(ai_items))

    # Attach a telemetry block (not in original schema — isolated under _meta).
    parsed["_meta"] = {
        "model": args.model,
        "temperature": args.temperature,
        "aws_region": args.aws_region,
        "usage": usage,
        "method": "OncoCITE Sec 4.5 three-way validation",
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(parsed, indent=2))
    logger.info("wrote analysis to %s", args.output)

    # Quick summary to stdout
    tuples = len(parsed.get("alignment", []) or [])
    missing = len(parsed.get("missing_from_ai", []) or [])
    halluc = len(parsed.get("ai_hallucinated_items", []) or [])
    improvements = len(parsed.get("ai_improvements_over_gt", []) or [])
    print(
        f"\nanalysis: {tuples} aligned tuples | "
        f"{missing} missing_from_ai | {halluc} hallucinated | {improvements} improvements | "
        f"{usage['input_tokens']} in + {usage['output_tokens']} out tokens ({usage['elapsed_sec']}s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
