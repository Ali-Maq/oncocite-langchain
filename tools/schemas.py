"""
CIViC Schema Constants
======================

Controlled vocabularies and field requirements for CIViC evidence items.
These match the official CIViC database schema.
"""

# =============================================================================
# REQUIRED FIELDS (Must be present for valid evidence item)
# =============================================================================

REQUIRED_FIELDS = [
    "feature_names",           # Gene symbol(s)
    "variant_names",           # Variant name(s)
    "disease_name",            # Disease/condition
    "evidence_type",           # PREDICTIVE, DIAGNOSTIC, etc.
    "evidence_direction",      # SUPPORTS or DOES_NOT_SUPPORT
    "evidence_level",          # A, B, C, D, E
    "clinical_significance",   # Sensitivity/Resistance, etc.
    "evidence_description",    # Full description with statistics
]

# =============================================================================
# TIER 1 FIELDS (Important for completeness, but not strictly required)
# =============================================================================

TIER_1_FIELDS = [
    # Core identifiers
    "feature_names",
    "variant_names",
    "disease_name",
    "therapy_names",

    # Evidence classification
    "evidence_type",
    "evidence_level",
    "evidence_direction",
    "clinical_significance",

    # Source information
    "source_title",
    "source_journal",
    "source_publication_year",
    "source_pmid",

    # Molecular details
    "molecular_profile_name",
    "variant_origin",
    "variant_type_names",

    # Clinical trial
    "clinical_trial_nct_ids",

    # Description
    "evidence_description",

    # Normalized IDs
    "gene_entrez_ids",
    "disease_doid",
    "therapy_ncit_ids",
]

# =============================================================================
# TIER 2 FIELDS (Optional, for enhanced records)
# =============================================================================

TIER_2_FIELDS = [
    # Additional IDs
    "therapy_rxnorm_ids",
    "disease_efo_id",
    "source_pmcid",

    # Fusion details
    "fusion_five_prime_gene_names",
    "fusion_three_prime_gene_names",

    # Additional context
    "feature_types",
    "therapy_interaction_type",
    "phenotypes_hpo_ids",

    # Clinical trial details
    "clinical_trial_details",

    # Safety data
    "safety_profile",
]

# =============================================================================
# VALID ENUM VALUES
# =============================================================================

VALID_EVIDENCE_TYPES = [
    "PREDICTIVE",      # Response to therapy
    "DIAGNOSTIC",      # Diagnostic marker
    "PROGNOSTIC",      # Outcome prediction
    "PREDISPOSING",    # Cancer risk
    "ONCOGENIC",       # Oncogenic function
    "FUNCTIONAL",      # Functional effect
]

VALID_EVIDENCE_LEVELS = [
    "A",  # Validated/guideline
    "B",  # Clinical (trial/cohort)
    "C",  # Case report
    "D",  # Preclinical
    "E",  # Inferential
]

VALID_EVIDENCE_DIRECTIONS = [
    "SUPPORTS",
    "DOES_NOT_SUPPORT",
]

VALID_VARIANT_ORIGINS = [
    "SOMATIC",
    "GERMLINE",
    "COMBINED",
    "UNKNOWN",
    "N/A",
]

VALID_FEATURE_TYPES = [
    "GENE",
    "FACTOR",
]

VALID_THERAPY_INTERACTION_TYPES = [
    "COMBINATION",
    "SEQUENTIAL",
    "SUBSTITUTES",
]

# =============================================================================
# EVIDENCE TYPE → SIGNIFICANCE MAPPINGS
# =============================================================================

EVIDENCE_SIGNIFICANCE_MAP = {
    "PREDICTIVE": [
        "SENSITIVITYRESPONSE",
        "SENSITIVITY/RESPONSE",
        "RESISTANCE",
        "ADVERSE_RESPONSE",
        "ADVERSE RESPONSE",
        "REDUCED_SENSITIVITY",
        "REDUCED SENSITIVITY",
        "N/A",
        "NA",
    ],
    "DIAGNOSTIC": [
        "POSITIVE",
        "NEGATIVE",
        "N/A",
        "NA",
    ],
    "PROGNOSTIC": [
        "BETTER_OUTCOME",
        "BETTER OUTCOME",
        "POOR_OUTCOME",
        "POOR OUTCOME",
        "N/A",
        "NA",
    ],
    "PREDISPOSING": [
        "PREDISPOSITION",
        "PROTECTIVENESS",
        "N/A",
        "NA",
    ],
    "ONCOGENIC": [
        "ONCOGENICITY",
        "PROTECTIVENESS",
        "N/A",
        "NA",
    ],
    "FUNCTIONAL": [
        "GAIN_OF_FUNCTION",
        "GAIN OF FUNCTION",
        "LOSS_OF_FUNCTION",
        "LOSS OF FUNCTION",
        "UNALTERED_FUNCTION",
        "UNALTERED FUNCTION",
        "NEOMORPHIC",
        "DOMINANT_NEGATIVE",
        "DOMINANT NEGATIVE",
        "UNKNOWN",
        "N/A",
        "NA",
    ],
}
