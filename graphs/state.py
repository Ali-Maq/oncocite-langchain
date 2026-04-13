"""
LangGraph State Definitions
===========================

Defines the state TypedDict for the CIViC extraction pipeline.
This mirrors the original ExtractionState but in LangGraph-compatible format.

ARCHITECTURE:
    Reader → Planner → Extractor → Critic → Normalizer

The Reader extracts paper content ONCE, then all downstream agents
use the same text-based context (no more redundant image reading).
"""

from typing import TypedDict, Annotated, Any, Optional
from langgraph.graph.message import add_messages
from datetime import datetime


class PaperInfo(TypedDict, total=False):
    """Basic paper metadata (from folder structure)."""
    paper_id: str
    author: str
    year: str
    num_pages: int
    paper_type: str
    pdf_path: str
    paper_folder: str
    page_images: list[str]  # Base64 encoded images for Reader
    expected_item_count: int


class ExtractionPlan(TypedDict, total=False):
    """Plan created by the Planner agent."""
    paper_type: str
    expected_items: int
    key_variants: list[str]
    key_therapies: list[str]
    key_diseases: list[str]
    focus_sections: list[str]
    extraction_notes: str
    # Optional structured plan details to aid the Extractor
    extraction_queue: list[dict]
    stat_critical: list[dict]


class CritiqueResult(TypedDict, total=False):
    """Feedback from the Critic agent."""
    overall_assessment: str  # "APPROVE", "NEEDS_REVISION", "REJECT"
    item_feedback: list[dict]
    missing_items: str
    extra_items: str
    summary: str
    iteration: int


class EvidenceProvenance(TypedDict, total=False):
    """
    Provenance and confidence metadata for an evidence item.

    This provides traceability and confidence information for each extraction,
    enabling reviewers to verify claims and assess extraction quality.
    """
    # ==========================================================================
    # Source Location
    # ==========================================================================

    # Page number(s) where the evidence was found (1-indexed)
    source_pages: list[int]

    # Specific section of the paper (e.g., "Results", "Table 2", "Figure 3A")
    source_section: str

    # Figure or table reference if applicable (e.g., "Figure 3A", "Table 2")
    figure_table_ref: str

    # ==========================================================================
    # Verbatim Quote
    # ==========================================================================

    # Exact quote from the paper supporting this extraction
    # Should be the actual text, not paraphrased
    verbatim_quote: str

    # Context around the quote (sentence before/after if helpful)
    quote_context: str

    # ==========================================================================
    # Reasoning
    # ==========================================================================

    # Why this extraction is clinically significant
    clinical_significance: str

    # Reasoning for why this evidence is important for CIViC
    extraction_reasoning: str

    # Any assumptions or interpretations made
    assumptions: list[str]

    # ==========================================================================
    # Confidence Assessment
    # ==========================================================================

    # Confidence score (0.0 to 1.0)
    # 0.0-0.3: Low confidence - uncertain extraction, may need verification
    # 0.3-0.6: Medium confidence - reasonable extraction, some ambiguity
    # 0.6-0.9: High confidence - strong supporting evidence
    # 0.9-1.0: Very high confidence - clear, unambiguous evidence
    confidence_score: float

    # Confidence level as category: "low", "medium", "high", "very_high"
    confidence_level: str

    # Factors that increase confidence
    confidence_factors_positive: list[str]

    # Factors that decrease confidence
    confidence_factors_negative: list[str]

    # Specific concerns or caveats about this extraction
    caveats: list[str]

    # ==========================================================================
    # Data Quality Indicators
    # ==========================================================================

    # Whether statistics are included (p-values, odds ratios, etc.)
    has_statistics: bool

    # Whether the claim is directly stated vs. inferred
    is_direct_statement: bool

    # Sample size if available
    sample_size: str

    # Study type (e.g., "clinical trial", "case study", "meta-analysis")
    study_type: str


def create_default_provenance() -> EvidenceProvenance:
    """Create a default provenance object with sensible defaults."""
    return EvidenceProvenance(
        source_pages=[],
        source_section="",
        figure_table_ref="",
        verbatim_quote="",
        quote_context="",
        clinical_significance="",
        extraction_reasoning="",
        assumptions=[],
        confidence_score=0.5,
        confidence_level="medium",
        confidence_factors_positive=[],
        confidence_factors_negative=[],
        caveats=[],
        has_statistics=False,
        is_direct_statement=True,
        sample_size="",
        study_type="",
    )


class ExtractionGraphState(TypedDict, total=False):
    """
    Central state object shared across all agents in LangGraph.

    This is the LangGraph-compatible version of ExtractionState.
    All fields are optional (total=False) to allow incremental updates.

    CRITICAL INVARIANTS:
    - paper_content_text is the FULL extracted text (~10-50KB)
    - NEVER truncate or summarize paper_content_text
    - All subagents receive the complete paper_content_text
    """

    # ==========================================================================
    # LangGraph Control Fields
    # ==========================================================================

    # Thread ID for checkpointing (typically = paper_id)
    thread_id: str

    # Messages for agent communication (using add_messages reducer)
    messages: Annotated[list, add_messages]

    # Current phase: "reader" | "planner" | "extractor" | "critic" | "normalizer" | "complete"
    current_phase: str

    # ==========================================================================
    # Paper Identification
    # ==========================================================================

    paper_id: str
    paper_info: PaperInfo

    # ==========================================================================
    # Reader Input (Page Images)
    # ==========================================================================

    # Base64 encoded page images for Reader (list of image content dicts)
    page_images: list[dict[str, Any]]

    # ==========================================================================
    # Reader Output (CRITICAL - Full Content)
    # ==========================================================================

    # Structured paper content from Reader (dict with sections, tables, etc.)
    paper_content: dict[str, Any]

    # Text version of paper content for agent prompts
    # INVARIANT: This is the FULL text (~10-50KB), NEVER truncated
    paper_content_text: str

    # Optional: Per-page JSON extractions for audit/debug
    page_extractions: list[dict[str, Any]]

    # ==========================================================================
    # Planner Output
    # ==========================================================================

    extraction_plan: ExtractionPlan

    # ==========================================================================
    # Extractor Output
    # ==========================================================================

    # Evidence items before normalization
    draft_extractions: list[dict[str, Any]]

    # ==========================================================================
    # Critic Output
    # ==========================================================================

    critique: CritiqueResult

    # ==========================================================================
    # Normalizer Output
    # ==========================================================================

    # Evidence items with normalized IDs (gene_entrez_ids, disease_doid, etc.)
    final_extractions: list[dict[str, Any]]

    # ==========================================================================
    # Iteration Control
    # ==========================================================================

    # Current iteration (0-based, max 3)
    iteration_count: int

    # Maximum allowed iterations
    max_iterations: int

    # ==========================================================================
    # Completion Status
    # ==========================================================================

    # True after finalize_extraction is called
    is_complete: bool

    # Final status: "APPROVED", "MAX_ITERATIONS", "ERROR"
    final_status: str

    # ==========================================================================
    # Timing
    # ==========================================================================

    start_time: str  # ISO format datetime string
    end_time: str    # ISO format datetime string

    # ==========================================================================
    # Error Tracking
    # ==========================================================================

    errors: list[str]


def create_initial_state(
    paper_id: str,
    paper_info: Optional[PaperInfo] = None,
    max_iterations: int = 3,
) -> ExtractionGraphState:
    """
    Create initial state for a new extraction.

    Args:
        paper_id: Unique identifier for the paper
        paper_info: Optional paper metadata
        max_iterations: Maximum Extractor-Critic iterations (default 3)

    Returns:
        Initial ExtractionGraphState with sensible defaults
    """
    return ExtractionGraphState(
        # LangGraph control
        thread_id=paper_id,
        messages=[],
        current_phase="reader",

        # Paper identification
        paper_id=paper_id,
        paper_info=paper_info or PaperInfo(paper_id=paper_id),

        # Reader input (page images, filled before Reader runs)
        page_images=[],

        # Reader output (empty until Reader runs)
        paper_content={},
        paper_content_text="",

        # Planner output (empty until Planner runs)
        extraction_plan=ExtractionPlan(),

        # Extractor output (empty until Extractor runs)
        draft_extractions=[],

        # Critic output (empty until Critic runs)
        critique=CritiqueResult(),

        # Normalizer output (empty until Normalizer runs)
        final_extractions=[],

        # Iteration control
        iteration_count=0,
        max_iterations=max_iterations,

        # Completion status
        is_complete=False,
        final_status="",

        # Timing
        start_time=datetime.now().isoformat(),
        end_time="",

        # Errors
        errors=[],
    )


def should_continue_iteration(state: ExtractionGraphState) -> bool:
    """
    Check if the extraction loop should continue.

    Returns False if:
    - is_complete is True
    - iteration_count >= max_iterations
    - critique assessment is "APPROVE"
    """
    if state.get("is_complete", False):
        return False

    if state.get("iteration_count", 0) >= state.get("max_iterations", 3):
        return False

    critique = state.get("critique")
    if critique and critique.get("overall_assessment") == "APPROVE":
        return False

    return True


def get_next_phase(state: ExtractionGraphState) -> str:
    """
    Determine the next phase based on current state.

    Flow:
        reader → planner → extractor → critic

        If critic says NEEDS_REVISION and iterations < max:
            → extractor

        If critic says APPROVE or iterations >= max:
            → normalizer → complete
    """
    current = state.get("current_phase", "reader")

    # Reader → Planner
    if current == "reader":
        if state.get("paper_content_text"):
            return "planner"
        return "reader"

    # Planner → Extractor
    if current == "planner":
        if state.get("extraction_plan"):
            return "extractor"
        return "planner"

    # Extractor → Critic
    if current == "extractor":
        if state.get("draft_extractions"):
            return "critic"
        return "extractor"

    # Critic → Extractor (revision) or Normalizer (approved/max iterations)
    if current == "critic":
        critique = state.get("critique")
        if critique:
            assessment = critique.get("overall_assessment", "")

            # Approved → Normalizer
            if assessment == "APPROVE":
                return "normalizer"

            # Needs revision and under max iterations → Extractor
            if assessment == "NEEDS_REVISION":
                if state.get("iteration_count", 0) < state.get("max_iterations", 3):
                    return "extractor"
                else:
                    return "normalizer"  # Max iterations reached

            # Reject → Normalizer (with whatever we have)
            if assessment == "REJECT":
                return "normalizer"

        return "critic"

    # Normalizer → Complete
    if current == "normalizer":
        if state.get("is_complete"):
            return "complete"
        return "normalizer"

    return "complete"
