"""
Validation Tools
================

Tools for validating evidence items against CIViC rules.
Migrated from Claude Agent SDK to LangChain format.
"""

import json
from typing import Any, Dict, List
from langchain_core.tools import tool

from .schemas import (
    REQUIRED_FIELDS,
    TIER_1_FIELDS,
    VALID_EVIDENCE_TYPES,
    VALID_EVIDENCE_LEVELS,
    VALID_EVIDENCE_DIRECTIONS,
    VALID_VARIANT_ORIGINS,
    VALID_FEATURE_TYPES,
    EVIDENCE_SIGNIFICANCE_MAP,
)
from .context import get_context
import re


@tool
def validate_evidence_item(item: Dict[str, Any]) -> str:
    """
    Validate an evidence item against CIViC field requirements.

    Checks:
    - All 8 required fields present
    - Field values match controlled vocabularies
    - Evidence significance matches evidence type
    - PREDICTIVE evidence has therapy_names
    - Tier 1 field coverage percentage

    Args:
        item: Evidence item dictionary to validate

    Returns:
        JSON string with validation result including errors, warnings, and coverage stats
    """
    errors = []
    warnings = []
    field_status = {}

    # ==========================================================================
    # Check required fields (8)
    # ==========================================================================
    for field in REQUIRED_FIELDS:
        value = item.get(field)
        if value is None or value == "":
            errors.append(f"Missing required field: {field}")
            field_status[field] = "MISSING"
        else:
            field_status[field] = "PRESENT"

    # ==========================================================================
    # Validate evidence_type
    # ==========================================================================
    etype = item.get("evidence_type")
    if etype:
        etype_upper = etype.upper() if isinstance(etype, str) else str(etype)
        if etype_upper not in VALID_EVIDENCE_TYPES:
            errors.append(
                f"Invalid evidence_type: '{etype}'. "
                f"Must be one of: {', '.join(VALID_EVIDENCE_TYPES)}"
            )

    # ==========================================================================
    # Validate evidence_level
    # ==========================================================================
    level = item.get("evidence_level")
    if level and level not in VALID_EVIDENCE_LEVELS:
        errors.append(
            f"Invalid evidence_level: '{level}'. "
            f"Must be one of: {', '.join(VALID_EVIDENCE_LEVELS)}"
        )

    # ==========================================================================
    # Validate evidence_direction
    # ==========================================================================
    direction = item.get("evidence_direction")
    if direction:
        dir_normalized = direction.upper().replace(" ", "_") if isinstance(direction, str) else str(direction)
        if dir_normalized not in VALID_EVIDENCE_DIRECTIONS:
            errors.append(
                f"Invalid evidence_direction: '{direction}'. "
                f"Must be SUPPORTS or DOES_NOT_SUPPORT"
            )

    # ==========================================================================
    # Validate evidence_significance matches evidence_type
    # ==========================================================================
    significance = item.get("evidence_significance")
    if etype and significance:
        etype_upper = etype.upper() if isinstance(etype, str) else str(etype)
        valid_sigs = EVIDENCE_SIGNIFICANCE_MAP.get(etype_upper, [])
        sig_upper = significance.upper().replace(" ", "_") if isinstance(significance, str) else str(significance)

        if valid_sigs and sig_upper not in valid_sigs:
            errors.append(
                f"evidence_significance '{significance}' is invalid for "
                f"evidence_type '{etype}'. Valid options: {', '.join(valid_sigs)}"
            )

    # ==========================================================================
    # Validate variant_origin if present
    # ==========================================================================
    variant_origin = item.get("variant_origin")
    if variant_origin:
        origin_upper = variant_origin.upper() if isinstance(variant_origin, str) else str(variant_origin)
        if origin_upper not in VALID_VARIANT_ORIGINS:
            warnings.append(
                f"Unusual variant_origin: '{variant_origin}'. "
                f"Expected: {', '.join(VALID_VARIANT_ORIGINS)}"
            )

    # ==========================================================================
    # Validate feature_types if present
    # ==========================================================================
    feature_type = item.get("feature_types")
    if feature_type:
        if feature_type not in VALID_FEATURE_TYPES:
            warnings.append(
                f"Invalid feature_types: '{feature_type}'. "
                f"Must be GENE or FACTOR"
            )

    # ==========================================================================
    # Validate therapy_interaction_type if present
    # ==========================================================================
    interaction = item.get("therapy_interaction_type")
    if interaction:
        if interaction not in ["COMBINATION", "SEQUENTIAL", "SUBSTITUTES"]:
            warnings.append(
                f"Invalid therapy_interaction_type: '{interaction}'. "
                f"Must be COMBINATION, SEQUENTIAL, or SUBSTITUTES"
            )

    # ==========================================================================
    # PREDICTIVE evidence must have therapy_names
    # ==========================================================================
    if etype and etype.upper() == "PREDICTIVE":
        therapy = item.get("therapy_names")
        if not therapy:
            errors.append(
                "PREDICTIVE evidence REQUIRES therapy_names field. "
                "If no specific drug is mentioned, this may be PROGNOSTIC instead."
            )

    # ==========================================================================
    # Check therapy specificity (warn about drug classes)
    # ==========================================================================
    therapy = item.get("therapy_names")
    if therapy:
        # Handle both string and list cases
        if isinstance(therapy, list):
            therapy_str = ", ".join(str(t) for t in therapy)
        else:
            therapy_str = str(therapy)
        therapy_lower = therapy_str.lower()
        class_indicators = [
            ("tki", "TKI is a drug class - use specific drug name like Erlotinib, Gefitinib"),
            ("egfr inhibitor", "EGFR inhibitor is a drug class - use Erlotinib, Gefitinib, Osimertinib, etc."),
            ("braf inhibitor", "BRAF inhibitor is a drug class - use Vemurafenib or Dabrafenib"),
            ("mek inhibitor", "MEK inhibitor is a drug class - use Trametinib, Cobimetinib, etc."),
            ("immunotherapy", "Immunotherapy is a drug class - use Pembrolizumab, Nivolumab, etc."),
            ("targeted therapy", "Targeted therapy is too generic - use specific drug name"),
            ("chemotherapy", "Chemotherapy is too generic - use specific agent like Carboplatin, Paclitaxel"),
        ]
        for indicator, message in class_indicators:
            if indicator in therapy_lower and len(therapy_lower) < 20:
                warnings.append(f"Therapy '{therapy_str}': {message}")
                break

    # ==========================================================================
    # Check evidence description quality
    # ==========================================================================
    desc = item.get("evidence_description", "")
    if desc:
        if len(desc) < 50:
            warnings.append(
                f"evidence_description is only {len(desc)} chars. "
                "Should be 1-3 sentences with statistics (HR, p-value, n)."
            )
        elif len(desc) > 1000:
            warnings.append(
                f"evidence_description is {len(desc)} chars. "
                "Should be 1-3 concise sentences, not a full paragraph."
            )

        has_stats = any(c.isdigit() for c in desc)
        if not has_stats:
            warnings.append(
                "evidence_description has no statistics. "
                "Consider adding HR, p-value, response rate, or patient numbers."
            )

    # ==========================================================================
    # Check molecular_profile_name consistency
    # ==========================================================================
    mp_name = item.get("molecular_profile_name")
    gene = item.get("feature_names", "")
    variant = item.get("variant_names", "")

    if gene and variant and not mp_name:
        warnings.append(
            f"molecular_profile_name not set. Should be '{gene} {variant}'"
        )

    # ==========================================================================
    # Check fusion fields consistency
    # ==========================================================================
    variant_type = item.get("variant_type_names", "")
    # Handle both string and list cases for variant_type
    if isinstance(variant_type, list):
        variant_type_str = ", ".join(str(v) for v in variant_type) if variant_type else ""
    else:
        variant_type_str = str(variant_type) if variant_type else ""
    if variant_type_str and "fusion" in variant_type_str.lower():
        if not item.get("fusion_five_prime_gene_names"):
            warnings.append("Fusion variant should have fusion_five_prime_gene_names")
        if not item.get("fusion_three_prime_gene_names"):
            warnings.append("Fusion variant should have fusion_three_prime_gene_names")

    if item.get("fusion_five_prime_gene_names") or item.get("fusion_three_prime_gene_names"):
        if variant_type_str and "fusion" not in variant_type_str.lower():
            warnings.append(
                f"Fusion gene fields are set but variant_type_names is '{variant_type_str}'. "
                "Should be 'Fusion' or similar."
            )

    # ==========================================================================
    # Grounding strictness: verbatim_quote must appear in paper content,
    # and key tokens from evidence_description must appear in verbatim_quote.
    # ==========================================================================
    try:
        ctx = get_context()
        content_text = ctx.paper_content_text or ""
    except Exception:
        content_text = ""

    quote = item.get("verbatim_quote", "") or ""
    if quote:
        if content_text and quote not in content_text:
            errors.append("verbatim_quote is not an exact substring of paper content text")
        # Ensure key tokens from description are present in quote
        desc = item.get("evidence_description", "") or ""
        # Extract simple numeric/stat tokens (percentages, decimals, integers)
        num_tokens: List[str] = re.findall(r"\b\d+(?:\.\d+)?%?\b", desc)
        for tok in set(num_tokens):
            if tok and tok not in quote:
                errors.append(f"statistic '{tok}' from evidence_description not found in verbatim_quote")
        # Ensure entities appear in quote (case-insensitive contains)
        def in_quote(val: Any) -> bool:
            if not val:
                return True
            qlow = quote.lower()
            if isinstance(val, list):
                return all(str(v).lower() in qlow for v in val if str(v).strip())
            return str(val).lower() in qlow

        if not in_quote(item.get("disease_name")):
            errors.append("disease_name not found in verbatim_quote")
        if not in_quote(item.get("feature_names")):
            errors.append("feature_names not found in verbatim_quote")
        if not in_quote(item.get("variant_names")):
            errors.append("variant_names not found in verbatim_quote")
        if item.get("evidence_type", "").upper() == "PREDICTIVE":
            if not in_quote(item.get("therapy_names")):
                errors.append("therapy_names not found in verbatim_quote for PREDICTIVE evidence")
    else:
        errors.append("Missing required grounded field: verbatim_quote")

    # ==========================================================================
    # Additional clinical logic checks
    # ==========================================================================
    # Antigen loss / escape should not be labeled as sensitivity
    desc_lower = (item.get("evidence_description") or "").lower()
    cs_lower = (item.get("clinical_significance") or "").lower()
    if any(tok in desc_lower for tok in ["antigen escape", "antigen-negative", "antigen negative", "loss of", "lost expression"]):
        if "sensit" in cs_lower or "response" in cs_lower or "benefit" in cs_lower:
            errors.append("Antigen loss/escape implies resistance; clinical_significance should not be sensitivity/response")

    # ==========================================================================
    # Calculate Tier 1 field coverage
    # ==========================================================================
    tier1_present = []
    tier1_missing = []

    for field in TIER_1_FIELDS:
        value = item.get(field)
        if value is not None and value != "":
            tier1_present.append(field)
        else:
            tier1_missing.append(field)

    coverage_pct = round(len(tier1_present) / len(TIER_1_FIELDS) * 100, 1)

    if coverage_pct < 40:
        warnings.append(
            f"Tier 1 coverage is only {coverage_pct}%. "
            f"Consider extracting: {', '.join(tier1_missing[:5])}"
        )

    # ==========================================================================
    # Build result
    # ==========================================================================
    is_valid = len(errors) == 0

    result = {
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "tier1_coverage": {
            "fields_present": len(tier1_present),
            "fields_missing": len(tier1_missing),
            "total_fields": len(TIER_1_FIELDS),
            "coverage_percent": coverage_pct,
            "present_fields": tier1_present,
            "missing_fields": tier1_missing[:10],
        },
        "recommendation": "VALID - Ready to save" if is_valid else "FIX ERRORS before saving"
    }

    return json.dumps(result, indent=2)


@tool
def check_actionability(claim: str) -> str:
    """
    Test if a clinical claim meets CIViC's actionability criteria.

    A claim is actionable if knowing it would change clinical care.

    Actionable examples:
    - "EGFR L858R predicts response to erlotinib" (treatment decision)
    - "BRCA1 mutation increases breast cancer risk" (screening decision)

    NOT actionable:
    - "EGFR mutations occur in 30% of NSCLC" (just prevalence)
    - "V600E activates MAPK pathway" (just mechanism)

    Args:
        claim: The clinical claim text to analyze

    Returns:
        JSON string with actionability assessment and analysis details
    """
    claim_lower = claim.lower()

    analysis = {
        "has_molecular_alteration": False,
        "has_clinical_outcome": False,
        "is_prevalence_only": False,
        "is_mechanism_only": False,
    }

    feedback = []

    # ==========================================================================
    # Check for molecular alteration mention
    # ==========================================================================
    alteration_indicators = [
        "mutation", "variant", "deletion", "insertion", "amplification",
        "fusion", "rearrangement", "expression", "loss", "gain", "alteration",
        "v600", "l858", "t790", "g12", "exon", "p.", "c.", "wild-type", "wildtype"
    ]
    if any(ind in claim_lower for ind in alteration_indicators):
        analysis["has_molecular_alteration"] = True
    else:
        feedback.append("No specific molecular alteration detected")

    # ==========================================================================
    # Check for clinical outcome
    # ==========================================================================
    outcome_indicators = [
        "response", "sensitivity", "resistance", "efficacy", "benefit",
        "responded", "effective", "refractory",
        "survival", "prognosis", "outcome", "mortality", "death",
        "progression", "recurrence", "relapse",
        "hazard ratio", "hr ", "odds ratio", "or ", "risk ratio",
        "overall survival", "progression-free", "pfs", "os ",
        "median survival", "response rate", "orr", "dcr",
        "predicts", "predictive", "associated with", "correlates",
        "improved", "decreased", "increased", "worse", "better"
    ]
    if any(ind in claim_lower for ind in outcome_indicators):
        analysis["has_clinical_outcome"] = True
    else:
        feedback.append("No clinical outcome detected")

    # ==========================================================================
    # Check for prevalence-only claims (NOT actionable)
    # ==========================================================================
    prevalence_phrases = [
        "% of patients", "percent of patients", "frequency of",
        "prevalence of", "incidence of", "common in", "rare in",
        "found in", "detected in", "occurs in", "present in",
        "identified in", "observed in"
    ]

    if any(phrase in claim_lower for phrase in prevalence_phrases):
        if not analysis["has_clinical_outcome"]:
            analysis["is_prevalence_only"] = True
            feedback.append(
                "Appears to be a prevalence/frequency statistic without clinical outcome. "
                "Prevalence alone is NOT actionable."
            )

    # ==========================================================================
    # Check for mechanism-only claims (NOT actionable)
    # ==========================================================================
    mechanism_phrases = [
        "activates", "inhibits", "phosphorylates", "binds to",
        "downstream of", "upstream of", "pathway", "signaling",
        "kinase activity", "transcription", "expression of",
        "in vitro", "cell line", "biochemical"
    ]

    if any(phrase in claim_lower for phrase in mechanism_phrases):
        if not analysis["has_clinical_outcome"]:
            analysis["is_mechanism_only"] = True
            feedback.append(
                "Appears to describe molecular mechanism without clinical outcome. "
                "Mechanism alone is NOT actionable."
            )

    # ==========================================================================
    # Determine actionability
    # ==========================================================================
    is_actionable = (
        analysis["has_molecular_alteration"] and
        analysis["has_clinical_outcome"] and
        not analysis["is_prevalence_only"] and
        not analysis["is_mechanism_only"]
    )

    if is_actionable:
        recommendation = "ACTIONABLE - Include as evidence item"
    elif analysis["is_prevalence_only"]:
        recommendation = "NOT ACTIONABLE - Prevalence statistic only"
    elif analysis["is_mechanism_only"]:
        recommendation = "NOT ACTIONABLE - Mechanism description only"
    elif not analysis["has_molecular_alteration"]:
        recommendation = "NOT ACTIONABLE - No specific molecular alteration"
    elif not analysis["has_clinical_outcome"]:
        recommendation = "NOT ACTIONABLE - No clinical outcome described"
    else:
        recommendation = "UNCLEAR - Review manually"

    result = {
        "is_actionable": is_actionable,
        "analysis": analysis,
        "feedback": feedback,
        "recommendation": recommendation,
        "claim_analyzed": claim[:200] + "..." if len(claim) > 200 else claim
    }

    return json.dumps(result, indent=2)
