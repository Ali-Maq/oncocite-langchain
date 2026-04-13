"""
Extraction State Tools
======================

Tools for managing extraction state (plans, items, critiques).
Migrated from Claude Agent SDK to LangChain format.
"""

import json
import re
from typing import Any, List, Dict, Optional, Union
from langchain_core.tools import tool

from .context import get_context

# Required fields for evidence items (imported from original schemas)
REQUIRED_FIELDS = [
    "feature_names",
    "variant_names",
    "disease_name",
    "evidence_type",
    "evidence_direction",
    "evidence_level",
    "clinical_significance",
    "evidence_description",
]

def _norm_list_str(v: Any) -> List[str]:
    if not v:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    return [s] if s else []

def _norm_key(item: Dict[str, Any]) -> tuple:
    feats = tuple(sorted(x.lower() for x in _norm_list_str(item.get("feature_names"))))
    dis = (item.get("disease_name") or "").strip().lower()
    thers = tuple(sorted(x.lower() for x in _norm_list_str(item.get("therapy_names"))))
    etype = (item.get("evidence_type") or "").strip().upper()
    # Normalize clinical_significance to sensitivity/resistance/other token if present
    cs = (item.get("clinical_significance") or "").strip().lower()
    if "resist" in cs:
        csn = "resistance"
    elif "sensit" in cs or "response" in cs or "benefit" in cs:
        csn = "sensitivity"
    else:
        csn = cs
    return (feats, dis, thers, etype, csn)

def _score_item(item: Dict[str, Any]) -> int:
    desc = (item.get("evidence_description") or "").strip()
    quote = (item.get("verbatim_quote") or "").strip()
    # Prefer items with longer description + quote length
    return len(desc) + len(quote)

def _merge_items(primary: Dict[str, Any], other: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(primary)
    # Union list fields where it’s safe
    for field in [
        "therapy_names",
        "clinical_trial_nct_ids",
        "gene_entrez_ids",
        "therapy_ncit_ids",
    ]:
        p = _norm_list_str(merged.get(field))
        o = _norm_list_str(other.get(field))
        if o:
            merged[field] = sorted(list({*p, *o}))
    # Keep the longer description and quote
    if len((other.get("evidence_description") or "")) > len((merged.get("evidence_description") or "")):
        merged["evidence_description"] = other.get("evidence_description")
    if len((other.get("verbatim_quote") or "")) > len((merged.get("verbatim_quote") or "")):
        merged["verbatim_quote"] = other.get("verbatim_quote")
    return merged

@tool
def consolidate_evidence_items(items: List[Dict[str, Any]]) -> str:
    """
    Consolidate redundant evidence items.

    Heuristics:
    - Group by (feature_names set, disease_name, therapy_names set, evidence_type, clinical_significance token)
    - Within each group, keep the most informative item (longer description/quote)
    - Merge safe list fields and prefer longer fields

    Returns:
        JSON string with {"consolidated": [...], "dropped": N}
    """
    if not isinstance(items, list):
        return json.dumps({"error": "items must be a list"})
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for it in items:
        key = _norm_key(it)
        groups.setdefault(key, []).append(it)
    consolidated: List[Dict[str, Any]] = []
    dropped = 0
    for key, group in groups.items():
        if len(group) == 1:
            consolidated.append(group[0])
            continue
        # Pick best primary
        group_sorted = sorted(group, key=_score_item, reverse=True)
        primary = group_sorted[0]
        for other in group_sorted[1:]:
            primary = _merge_items(primary, other)
        dropped += len(group_sorted) - 1
        consolidated.append(primary)
    return json.dumps({"consolidated": consolidated, "dropped": dropped}, indent=2)


def _normalize_disease_terms(name: Optional[str]) -> list:
    """Return a list of lowercased disease strings for substring matching.

    We preserve both the full string and simple splits on common separators so
    trials with slightly different phrasing can still match.
    """
    if not name:
        return []
    lowered = name.lower()
    cleaned = re.sub(r"[^a-z0-9\s/-]", " ", lowered)
    segments = [seg.strip() for seg in re.split(r"[,/;]+", cleaned) if seg.strip()]
    if cleaned.strip() and cleaned.strip() not in segments:
        segments.append(cleaned.strip())
    return segments


def _parse_trial_entries(meta_trials: Optional[Union[str, list]], candidate_diseases: set) -> tuple[list, list]:
    """Parse trial metadata into structured entries.

    Each entry includes the NCT IDs, the lowercased source text, and any disease
    tokens found in that text that overlap with known evidence diseases.
    """
    lines: list[str] = []
    if isinstance(meta_trials, str):
        lines = [line.strip() for line in meta_trials.splitlines() if line.strip()]
    elif isinstance(meta_trials, list):
        lines = [str(line).strip() for line in meta_trials if str(line).strip()]

    trial_entries = []
    for line in lines:
        ncts = re.findall(r"NCT\d+", line)
        if not ncts:
            continue
        lower_line = line.lower()
        diseases_in_line = [d for d in candidate_diseases if d in lower_line]
        seen = set()
        deduped_ncts = [n for n in ncts if not (n in seen or seen.add(n))]
        trial_entries.append({
            "ncts": deduped_ncts,
            "text": lower_line,
            "diseases": diseases_in_line,
        })

    flat_ncts_seen = set()
    flat_ncts = []
    for entry in trial_entries:
        for nct in entry["ncts"]:
            if nct not in flat_ncts_seen:
                flat_ncts.append(nct)
                flat_ncts_seen.add(nct)

    return trial_entries, flat_ncts


@tool
def save_extraction_plan(
    paper_type: str,
    expected_items: int,
    key_variants: List[str],
    key_therapies: List[str],
    key_diseases: List[str],
    focus_sections: List[str],
    extraction_notes: str,
    extraction_queue: Optional[List[Dict[str, Any]]] = None,
    stat_critical: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Save the extraction strategy created by the Planner agent.

    Must be called before extraction. This establishes what the extractor
    should look for in the paper.

    Args:
        paper_type: Paper classification (PRIMARY, REVIEW, META_ANALYSIS, CASE_REPORT, GUIDELINE)
        expected_items: Estimated number of evidence items to extract
        key_variants: List of key genetic variants identified in paper
        key_therapies: List of key therapies/drugs mentioned
        key_diseases: List of key diseases/conditions
        focus_sections: Paper sections most likely to contain evidence
        extraction_notes: Additional notes for the extractor

    Returns:
        JSON string with save status and summary
    """
    ctx = get_context()

    # Validate paper_type
    valid_types = ["REVIEW", "PRIMARY", "CASE_REPORT", "GUIDELINE", "META_ANALYSIS", "UNKNOWN"]
    if paper_type not in valid_types:
        return json.dumps({
            "error": f"Invalid paper_type '{paper_type}'. Must be one of {valid_types}"
        })

    plan = {
        "paper_type": paper_type,
        "expected_items": expected_items,
        "key_variants": key_variants or [],
        "key_therapies": key_therapies or [],
        "key_diseases": key_diseases or [],
        "focus_sections": focus_sections or [],
        "extraction_notes": extraction_notes or "",
    }

    # Optional structured plan enrichments
    if extraction_queue is not None:
        plan["extraction_queue"] = extraction_queue
    if stat_critical is not None:
        plan["stat_critical"] = stat_critical if isinstance(stat_critical, list) else []

    # Save to context
    ctx.extraction_plan = plan
    ctx.paper_type = paper_type

    summary = f"Plan saved: {paper_type}, expecting {expected_items} items"

    if paper_type == "REVIEW":
        summary += "\nWARNING: Review papers typically yield 0-2 evidence items. Be very conservative."

    return json.dumps({"status": "saved", "summary": summary, "plan": plan}, indent=2)


@tool
def get_extraction_plan() -> str:
    """
    Get the current extraction plan.

    Use this to understand what to extract. Returns the plan created by
    the Planner agent, including any previous critique feedback if iterating.

    Returns:
        JSON string with extraction plan and optional previous critique
    """
    ctx = get_context()

    if not ctx.extraction_plan:
        return json.dumps({
            "error": "No extraction plan yet. The Planner agent should run first."
        })

    result = dict(ctx.extraction_plan)

    # Include critique feedback if available (for iterations)
    if ctx.critique:
        result["previous_critique"] = {
            "assessment": ctx.critique.get("overall_assessment"),
            "feedback": ctx.critique.get("item_feedback", []),
            "missing_items": ctx.critique.get("missing_items", []),
            "summary": ctx.critique.get("summary", "")
        }
        result["iteration"] = ctx.iteration_count

    return json.dumps(result, indent=2)


@tool
def save_evidence_items(items: List[Dict[str, Any]]) -> str:
    """
    Save extracted evidence items for Critic review.

    Each item must have the 8 required fields:
    - feature_names: Gene symbol(s)
    - variant_names: Variant name(s)
    - disease_name: Disease/condition
    - evidence_type: PREDICTIVE, DIAGNOSTIC, PROGNOSTIC, PREDISPOSING, ONCOGENIC, FUNCTIONAL
    - evidence_direction: SUPPORTS, DOES_NOT_SUPPORT
    - evidence_level: A, B, C, D, E
    - clinical_significance: Drug sensitivity/resistance, positive/negative outcome, etc.
    - evidence_description: Full description with statistics

    Args:
        items: List of evidence item dictionaries

    Returns:
        JSON string with save status and validation summary
    """
    ctx = get_context()

    if not isinstance(items, list):
        return json.dumps({
            "error": f"items must be a list, received {type(items).__name__}"
        })

    # Guard against accidental wipe-outs (e.g., Normalizer calling with empty list).
    if not items:
        if ctx.draft_extractions:
            return json.dumps({
                "warning": "Empty items ignored to avoid overwriting existing extractions.",
                "kept_items": len(ctx.draft_extractions)
            })
        ctx.draft_extractions = []
        return json.dumps({"warning": "No items provided. Saved empty list."})

    # Get metadata for backfill
    ctx_meta = ctx.paper_content or {}
    meta_title = ctx_meta.get("title", "")
    meta_journal = ctx_meta.get("journal")
    meta_year = ctx_meta.get("year")
    meta_trials = ctx_meta.get("clinical_trials") or ctx_meta.get("clinical_trial_nct_ids")

    # Build disease-aware trial entries
    candidate_diseases = set()
    for item in items:
        if isinstance(item, dict):
            candidate_diseases.update(_normalize_disease_terms(item.get("disease_name")))
    trial_entries, trials_list = _parse_trial_entries(meta_trials, candidate_diseases)

    # Determine diseases that belong to the primary paper context
    primary_diseases = {d for d in candidate_diseases if d and d in meta_title.lower()}

    # Backfill per item before validation
    for item in items:
        if isinstance(item, dict):
            if meta_title and not item.get("source_title"):
                item["source_title"] = meta_title
            if meta_journal and not item.get("source_journal"):
                item["source_journal"] = meta_journal
            if meta_year and not item.get("source_publication_year"):
                item["source_publication_year"] = str(meta_year)

            # Disease-aware clinical trial assignment
            if trials_list:
                disease_terms = _normalize_disease_terms(item.get("disease_name"))
                existing_trials = item.get("clinical_trial_nct_ids")
                if isinstance(existing_trials, str):
                    existing_trials = [existing_trials]
                elif existing_trials is None:
                    existing_trials = []

                matched_trials = []
                for entry in trial_entries:
                    if entry["diseases"]:
                        if any(term in entry["diseases"] for term in disease_terms):
                            matched_trials.extend(entry["ncts"])
                    elif primary_diseases and any(term in primary_diseases for term in disease_terms):
                        matched_trials.extend(entry["ncts"])

                # dedupe preserving order
                seen_trials = set()
                matched_trials = [t for t in matched_trials if not (t in seen_trials or seen_trials.add(t))]

                if matched_trials:
                    item["clinical_trial_nct_ids"] = matched_trials
                elif existing_trials:
                    item["clinical_trial_nct_ids"] = existing_trials

            # Default variant_origin to SOMATIC unless predisposition
            if not item.get("variant_origin") and item.get("evidence_type") != "PREDISPOSING":
                item["variant_origin"] = "SOMATIC"

    # Validate each item
    validation_summary = []
    for i, item in enumerate(items):
        missing = [f for f in REQUIRED_FIELDS if not item.get(f)]
        validation_summary.append({
            "index": i,
            "valid": len(missing) == 0,
            "missing_required": missing,
            "gene": item.get("feature_names", "?"),
            "variant": item.get("variant_names", "?"),
            "type": item.get("evidence_type", "?"),
        })

    # Save to context
    ctx.draft_extractions = items

    # Calculate stats
    valid_count = sum(1 for v in validation_summary if v["valid"])
    invalid_count = len(items) - valid_count

    result = {
        "saved": len(items),
        "valid": valid_count,
        "invalid": invalid_count,
        "items_summary": validation_summary
    }

    if invalid_count > 0:
        result["warning"] = f"{invalid_count} items have missing required fields. Please fix before submitting."

    return json.dumps(result, indent=2)


@tool
def get_draft_extractions() -> str:
    """
    Get the current draft extractions and any previous critique for review or iteration.

    Used by Critic to review items, and by Normalizer to get items for ID lookup.

    Returns:
        JSON string with items, count, iteration info, and optional critique
    """
    ctx = get_context()

    result = {
        "count": len(ctx.draft_extractions),
        "items": ctx.draft_extractions,
        "iteration": ctx.iteration_count,
        "max_iterations": ctx.max_iterations,
    }

    # Include plan context
    if ctx.extraction_plan:
        result["plan"] = {
            "paper_type": ctx.extraction_plan.get("paper_type"),
            "expected_items": ctx.extraction_plan.get("expected_items"),
        }

    # Include previous critique if any
    if ctx.critique:
        result["previous_critique"] = ctx.critique

    return json.dumps(result, indent=2)


@tool
def save_critique(
    overall_assessment: str,
    item_feedback: List[Dict[str, Any]],
    missing_items: List[str],
    extra_items: List[str],
    summary: str,
) -> str:
    """
    Save the Critic's assessment of draft extractions.

    Args:
        overall_assessment: APPROVE, NEEDS_REVISION, or REJECT
        item_feedback: List of feedback for each item (corrections needed)
        missing_items: List of evidence items that should have been extracted
        extra_items: List of items that shouldn't have been extracted
        summary: Overall summary of the critique

    Returns:
        JSON string with assessment status and recommendation
    """
    ctx = get_context()

    assessment = overall_assessment.upper()
    valid_assessments = ["APPROVE", "NEEDS_REVISION", "REJECT"]

    if assessment not in valid_assessments:
        return json.dumps({
            "error": f"Invalid assessment '{assessment}'. Must be one of {valid_assessments}"
        })

    critique = {
        "overall_assessment": assessment,
        "item_feedback": item_feedback or [],
        "missing_items": missing_items or [],
        "extra_items": extra_items or [],
        "summary": summary or "",
        "iteration": ctx.iteration_count,
    }

    # Save to context
    ctx.critique = critique

    # Determine recommendation
    needs_revision = assessment == "NEEDS_REVISION"
    can_iterate = ctx.iteration_count < ctx.max_iterations

    if assessment == "APPROVE":
        recommendation = "FINALIZE"
        message = "Extraction approved. Ready to normalize and finalize."
    elif assessment == "REJECT":
        recommendation = "FINALIZE"
        message = "Extraction rejected. Will finalize with current items (or empty)."
    elif needs_revision and can_iterate:
        recommendation = "ITERATE"
        message = f"Revision needed. Iteration {ctx.iteration_count + 1} of {ctx.max_iterations} available."
    else:
        recommendation = "FINALIZE"
        message = f"Max iterations ({ctx.max_iterations}) reached. Will finalize with current items."

    result = {
        "assessment": assessment,
        "needs_revision": needs_revision,
        "can_iterate": can_iterate,
        "recommendation": recommendation,
        "message": message
    }

    return json.dumps(result, indent=2)


@tool
def increment_iteration() -> str:
    """
    Increment the iteration counter before re-extraction.

    Call this before going back to extractor for another attempt.
    Will fail if already at max iterations.

    Returns:
        JSON string with new iteration count or error
    """
    ctx = get_context()

    if ctx.iteration_count >= ctx.max_iterations:
        return json.dumps({
            "error": f"Already at max iterations ({ctx.max_iterations}). Cannot iterate further."
        })

    ctx.iteration_count += 1

    return json.dumps({
        "status": "incremented",
        "iteration": ctx.iteration_count,
        "max_iterations": ctx.max_iterations,
        "message": f"Iteration {ctx.iteration_count} of {ctx.max_iterations}. Ready for re-extraction."
    })
