"""
Tool Registry
=============

Provides scoped tool lists for each agent type.
Each agent has access ONLY to its designated tools per the CIViC architecture.

Agent Tool Assignments (from original client.py):
- Reader: save_paper_content, get_paper_info, read_paper_page
- Planner: get_paper_info, get_paper_content, save_extraction_plan
- Extractor: get_paper_info, get_paper_content, get_extraction_plan,
             get_draft_extractions, check_actionability,
             validate_evidence_item, save_evidence_items
- Critic: get_paper_info, get_paper_content, get_extraction_plan,
          get_draft_extractions, check_actionability,
          validate_evidence_item, save_critique, increment_iteration
- Normalizer: get_draft_extractions, save_evidence_items, finalize_extraction,
              lookup_rxnorm, lookup_efo, lookup_safety_profile,
              lookup_gene_entrez, lookup_variant_info, lookup_therapy_ncit,
              lookup_disease_doid, lookup_clinical_trial, lookup_hpo, lookup_pmcid
"""

from typing import List
from langchain_core.tools import BaseTool

# Import all tools
from .paper_tools import get_paper_info, read_paper_page
from .paper_content_tools import save_paper_content, get_paper_content, get_paper_content_json
from .extraction_tools import (
    save_extraction_plan,
    get_extraction_plan,
    save_evidence_items,
    consolidate_evidence_items,
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


def get_reader_tools() -> List[BaseTool]:
    """
    Get tools available to the Reader agent.

    Reader's role: Extract content from PDF images into structured text.

    Tools:
    - save_paper_content: Save extracted paper content
    - get_paper_info: Get paper metadata
    - read_paper_page: Read specific page (legacy)
    """
    return [save_paper_content, get_paper_info, read_paper_page]


def get_planner_tools() -> List[BaseTool]:
    """
    Get tools available to the Planner agent.

    Planner's role: Analyze paper content and create extraction strategy.

    Tools:
    - get_paper_info: Get paper metadata
    - get_paper_content: Get FULL paper content text
    - save_extraction_plan: Save the extraction strategy
    """
    return [get_paper_info, get_paper_content, get_paper_content_json, save_extraction_plan]


def get_extractor_tools() -> List[BaseTool]:
    """
    Get tools available to the Extractor agent.

    Extractor's role: Extract evidence items following the plan.

    Tools:
    - get_paper_info: Get paper metadata
    - get_paper_content: Get FULL paper content text
    - get_extraction_plan: Get the extraction strategy
    - get_draft_extractions: Get current draft items (for iteration)
    - check_actionability: Check if a claim is actionable
    - validate_evidence_item: Validate item against CIViC rules
    - save_evidence_items: Save extracted evidence items
    """
    return [
        get_paper_info,
        get_paper_content,
        get_paper_content_json,
        get_extraction_plan,
        get_draft_extractions,
        check_actionability,
        validate_evidence_item,
        consolidate_evidence_items,
        save_evidence_items,
    ]


def get_critic_tools() -> List[BaseTool]:
    """
    Get tools available to the Critic agent.

    Critic's role: Review and validate extracted evidence items.

    Tools:
    - get_paper_info: Get paper metadata
    - get_paper_content: Get FULL paper content text
    - get_extraction_plan: Get the extraction strategy
    - get_draft_extractions: Get items to review
    - check_actionability: Verify claims are actionable
    - validate_evidence_item: Validate items against CIViC rules
    - save_critique: Save review assessment
    - increment_iteration: Increment counter before re-extraction
    """
    return [
        get_paper_info,
        get_paper_content,
        get_paper_content_json,
        get_extraction_plan,
        get_draft_extractions,
        check_actionability,
        validate_evidence_item,
        consolidate_evidence_items,
        save_evidence_items,
        save_critique,
        increment_iteration,
    ]


def get_normalizer_tools() -> List[BaseTool]:
    """
    Get tools available to the Normalizer agent.

    Normalizer's role: Add normalized IDs to evidence items.

    Tools:
    - get_draft_extractions: Get items to normalize
    - save_evidence_items: Save items with normalized IDs
    - finalize_extraction: Mark extraction as complete
    - lookup_rxnorm: RxNorm drug lookup
    - lookup_efo: EFO disease ontology lookup
    - lookup_safety_profile: FDA FAERS safety lookup
    - lookup_gene_entrez: NCBI gene ID lookup
    - lookup_variant_info: Variant annotation lookup
    - lookup_therapy_ncit: NCIt therapy lookup
    - lookup_disease_doid: DOID disease lookup
    - lookup_clinical_trial: ClinicalTrials.gov lookup
    - lookup_hpo: HPO phenotype lookup
    - lookup_pmcid: PMID to PMCID lookup
    """
    return [
        get_draft_extractions,
        save_evidence_items,
        finalize_extraction,
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
    ]


def get_all_tools() -> List[BaseTool]:
    """
    Get all available tools (for debugging/testing only).

    WARNING: Do not use this for agent binding. Each agent should
    only have access to its designated tools.
    """
    return [
        # Paper tools
        get_paper_info,
        read_paper_page,
        # Paper content tools
        save_paper_content,
        get_paper_content,
        # Extraction tools
        save_extraction_plan,
        get_extraction_plan,
        save_evidence_items,
        get_draft_extractions,
        save_critique,
        increment_iteration,
        # Validation tools
        validate_evidence_item,
        check_actionability,
        # Normalization tools
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
    ]
