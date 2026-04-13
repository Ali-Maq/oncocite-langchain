"""
LangGraph-compatible tools for CIViC extraction pipeline.

This package contains tools migrated from Claude Agent SDK to LangChain format.
All tools use the @tool decorator from langchain_core.tools.

Tool Categories:
- paper_tools: Paper reading and metadata
- paper_content_tools: Reader output storage/retrieval
- extraction_tools: Extraction plan and evidence items
- validation_tools: Evidence validation and actionability
- normalization_tools: Entity ID lookups and normalization
"""

from .paper_tools import get_paper_info, read_paper_page
from .paper_content_tools import save_paper_content, get_paper_content
from .extraction_tools import (
    save_extraction_plan,
    get_extraction_plan,
    save_evidence_items,
    get_draft_extractions,
    save_critique,
    increment_iteration,
)
from .validation_tools import validate_evidence_item, check_actionability
from .normalization_tools import (
    finalize_extraction,
    get_tier2_coverage,
    lookup_rxnorm,
    lookup_efo,
    lookup_safety_profile,
    lookup_gene_entrez,
    lookup_variant_info,
    lookup_therapy_ncit,
    lookup_disease_doid,
    lookup_clinical_trial,
    lookup_hpo,
    lookup_pmcid,
)
from .tool_registry import (
    get_reader_tools,
    get_planner_tools,
    get_extractor_tools,
    get_critic_tools,
    get_normalizer_tools,
)

__all__ = [
    # Paper tools
    "get_paper_info",
    "read_paper_page",
    # Paper content tools
    "save_paper_content",
    "get_paper_content",
    # Extraction tools
    "save_extraction_plan",
    "get_extraction_plan",
    "save_evidence_items",
    "get_draft_extractions",
    "save_critique",
    "increment_iteration",
    # Validation tools
    "validate_evidence_item",
    "check_actionability",
    # Normalization tools
    "finalize_extraction",
    "get_tier2_coverage",
    "lookup_rxnorm",
    "lookup_efo",
    "lookup_safety_profile",
    "lookup_gene_entrez",
    "lookup_variant_info",
    "lookup_therapy_ncit",
    "lookup_disease_doid",
    "lookup_clinical_trial",
    "lookup_hpo",
    "lookup_pmcid",
    # Registry
    "get_reader_tools",
    "get_planner_tools",
    "get_extractor_tools",
    "get_critic_tools",
    "get_normalizer_tools",
]
