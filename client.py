"""
CIViC Extraction Client (LangGraph Version)
============================================

Wrapper for the LangGraph-based CIViC extraction pipeline.
Provides the same API as the original Claude Agent SDK client.

This is the main entry point for running extractions.
"""

import base64
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from graphs.reader_graph import build_reader_graph, load_images_from_pdf, load_images_from_paths
from graphs.extraction_graph import build_extraction_graph
from graphs.state import ExtractionGraphState, create_initial_state
from runtime.checkpointing import get_checkpointer
from tools.context import set_context, get_context, ToolContext
from hooks.logging_callbacks import get_logging_callbacks, start_new_log_session

logger = logging.getLogger(__name__)


class CivicExtractionClient:
    """
    LangGraph-based client for CIViC evidence extraction.

    Implements the same interface as the original Claude Agent SDK client
    for backwards compatibility.

    Usage:
        client = CivicExtractionClient()
        result = await client.run_extraction(pdf_path="paper.pdf", paper_id="paper123")
    """

    def __init__(
        self,
        verbose: bool = True,
        use_checkpointing: bool = True,
        use_callbacks: bool = True,
    ):
        """
        Initialize the extraction client.

        Args:
            verbose: Enable verbose logging
            use_checkpointing: Enable LangGraph checkpointing for resume capability
            use_callbacks: Enable LangChain callbacks for observability
        """
        self.verbose = verbose
        self.use_checkpointing = use_checkpointing
        self.use_callbacks = use_callbacks

        # Set up checkpointer FIRST if enabled (required before building graphs)
        # Per LangGraph v0.2+, checkpointer must be passed to graph.compile()
        self.checkpointer = get_checkpointer() if use_checkpointing else None

        # Build graphs WITH checkpointer for proper state persistence
        # This enables: thread_id-based state management, resume capability, state history
        self.reader_graph = build_reader_graph(checkpointer=self.checkpointer)
        self.extraction_graph = build_extraction_graph(checkpointer=self.checkpointer)

        # Set up callbacks if enabled (using LangChain's built-in callback system)
        self.callbacks = get_logging_callbacks() if use_callbacks else []

        if verbose:
            logging.basicConfig(level=logging.INFO)
            logger.info("CivicExtractionClient initialized with LangGraph backend")

    def _load_images_from_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        """
        Render PDF pages to images for direct injection.

        This method preserves the original interface while using the
        new implementation from reader_graph.py.
        """
        return load_images_from_pdf(pdf_path)

    async def run_reader_phase(
        self,
        pdf_path: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        paper_id: str = "unknown",
        force_rerun: bool = False,
        max_pages: Optional[int] = None,
    ) -> ExtractionGraphState:
        """
        Phase 1: Run Reader Agent with page images.

        Implements checkpoint-based resumption:
        - If Reader already completed (paper_content exists), skip and return cached state
        - If Reader started but not complete, resume from checkpoint
        - If no checkpoint, start fresh

        Args:
            pdf_path: Path to PDF file (preferred)
            image_paths: List of image file paths (alternative)
            paper_id: Identifier for the paper
            force_rerun: If True, ignore existing checkpoints and run fresh

        Returns:
            State with paper_content extracted
        """
        logger.info("=== PHASE 1: READER ===")

        # Build config for checkpointing
        config = {}
        if self.checkpointer:
            config["configurable"] = {"thread_id": f"{paper_id}_reader"}
        if self.callbacks:
            config["callbacks"] = self.callbacks

        # Check for existing checkpoint (resume capability)
        if self.checkpointer and not force_rerun:
            try:
                existing_state = self.reader_graph.get_state(config)
                if existing_state and existing_state.values:
                    paper_content = existing_state.values.get("paper_content")
                    paper_content_text = existing_state.values.get("paper_content_text", "")

                    # Reader already completed - return cached state
                    if paper_content and len(paper_content_text) > 0:
                        logger.info(f"✓ Reader already completed (checkpoint found). "
                                   f"Skipping - cached content: {len(paper_content_text)} chars")
                        return existing_state.values
                    else:
                        logger.info("Found incomplete Reader checkpoint - will resume...")
            except Exception as e:
                logger.debug(f"No existing checkpoint found: {e}")

        # Load images (only if we need to run)
        if pdf_path:
            page_images = load_images_from_pdf(pdf_path, max_pages=max_pages)
            logger.info(f"Loaded {len(page_images)} pages from PDF: {pdf_path}")
        elif image_paths:
            page_images = load_images_from_paths(image_paths)
            logger.info(f"Loaded {len(page_images)} images from paths")
        else:
            raise ValueError("Must provide either pdf_path or image_paths")

        # Build initial state
        initial_state = create_initial_state(paper_id=paper_id)
        initial_state["page_images"] = page_images
        initial_state["current_phase"] = "reader"

        if self.verbose:
            logger.info(f"Running Reader graph with {len(page_images)} images...")

        result = await self.reader_graph.ainvoke(initial_state, config)

        if self.verbose:
            content_size = len(result.get("paper_content_text", ""))
            logger.info(f"Reader complete. Content size: {content_size} chars")

        return result

    async def run_orchestrator_phase(
        self,
        paper_content: Dict[str, Any],
        paper_content_text: str,
        paper_id: str = "unknown",
        max_iterations: int = 3,
        force_rerun: bool = False,
    ) -> ExtractionGraphState:
        """
        Phase 2: Run Orchestrator with Planner, Extractor, Critic, Normalizer.

        Implements checkpoint-based resumption:
        - If extraction already completed (is_complete=True), skip and return cached state
        - If extraction started but not complete, resume from last checkpoint
        - If no checkpoint, start fresh

        Args:
            paper_content: Structured paper content from Reader
            paper_content_text: Full text representation of paper
            paper_id: Identifier for the paper
            max_iterations: Maximum Critic→Extractor iterations
            force_rerun: If True, ignore existing checkpoints and run fresh

        Returns:
            State with final_extractions
        """
        logger.info("=== PHASE 2: ORCHESTRATOR ===")

        # Build config for checkpointing
        config = {}
        if self.checkpointer:
            config["configurable"] = {"thread_id": f"{paper_id}_extraction"}
        if self.callbacks:
            config["callbacks"] = self.callbacks
        # Allow deeper Extractor↔Critic loops before stopping
        config["recursion_limit"] = 60

        # Check for existing checkpoint (resume capability)
        if self.checkpointer and not force_rerun:
            try:
                existing_state = self.extraction_graph.get_state(config)
                if existing_state and existing_state.values:
                    is_complete = existing_state.values.get("is_complete", False)
                    final_extractions = existing_state.values.get("final_extractions", [])
                    current_phase = existing_state.values.get("current_phase", "")

                    # Extraction already completed - return cached state
                    if is_complete and final_extractions:
                        logger.info(f"✓ Extraction already completed (checkpoint found). "
                                   f"Skipping - {len(final_extractions)} items cached")
                        return existing_state.values

                    # Extraction started but not complete - resume from checkpoint
                    if current_phase and current_phase not in ["", "extraction_start"]:
                        logger.info(f"Resuming from checkpoint at phase: {current_phase}")
                        # Pass None to resume from last checkpoint state
                        result = self.extraction_graph.invoke(None, config)

                        if self.verbose:
                            items_count = len(result.get("final_extractions", []))
                            iterations = result.get("iteration_count", 0)
                            logger.info(f"Extraction resumed and complete. Items: {items_count}, Iterations: {iterations}")

                        return result
            except Exception as e:
                logger.debug(f"No existing checkpoint found: {e}")

        # Build initial state (fresh start)
        initial_state = create_initial_state(paper_id=paper_id)
        initial_state["paper_content"] = paper_content
        initial_state["paper_content_text"] = paper_content_text
        initial_state["max_iterations"] = max_iterations
        initial_state["current_phase"] = "extraction_start"
        # Pass through page_extractions for artifact saving later
        # (not used by extraction graph nodes but useful for outputs/pages)
        if "page_extractions" in paper_content:
            # Just in case someone mistakenly nested it; otherwise ignore
            pass
        # If the reader phase returned page_extractions in the cached result
        # (common case), carry it along in initial state so the final result
        # can include it for saving.
        # Note: caller is passing paper_content and paper_content_text; we don't
        # have the full reader_result here, so run_extraction passes page_extractions separately.

        if self.verbose:
            logger.info("Running Extraction graph (Planner → Extractor → Critic → Normalizer)...")

        result = self.extraction_graph.invoke(initial_state, config)

        if self.verbose:
            items_count = len(result.get("final_extractions", []))
            iterations = result.get("iteration_count", 0)
            logger.info(f"Extraction complete. Items: {items_count}, Iterations: {iterations}")

        return result

    async def run_extraction(
        self,
        pdf_path: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        paper_id: str = "unknown",
        max_iterations: int = 3,
        max_pages: Optional[int] = None,
    ) -> ExtractionGraphState:
        """
        Run the complete extraction pipeline (Reader + Orchestrator).

        This is the main entry point for extraction.

        Args:
            pdf_path: Path to PDF file (preferred)
            image_paths: List of image file paths (alternative)
            paper_id: Identifier for the paper
            max_iterations: Maximum Critic→Extractor iterations

        Returns:
            Final state with all extractions
        """
        logger.info(f"=== STARTING EXTRACTION: {paper_id} ===")

        # Phase 1: Reader
        reader_result = await self.run_reader_phase(
            pdf_path=pdf_path,
            image_paths=image_paths,
            paper_id=paper_id,
            max_pages=max_pages,
        )

        # Check Reader success
        if not reader_result.get("paper_content"):
            logger.error("Reader phase failed to extract content")
            return reader_result

        # Phase 2: Orchestrator
        extraction_result = await self.run_orchestrator_phase(
            paper_content=reader_result["paper_content"],
            paper_content_text=reader_result["paper_content_text"],
            paper_id=paper_id,
            max_iterations=max_iterations,
        )

        # Attach page_extractions to final result so artifact saver can write pages/*.json
        if reader_result.get("page_extractions") and not extraction_result.get("page_extractions"):
            extraction_result["page_extractions"] = reader_result["page_extractions"]

        logger.info(f"=== EXTRACTION COMPLETE: {paper_id} ===")
        return extraction_result

    def run_extraction_sync(
        self,
        pdf_path: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        paper_id: str = "unknown",
        max_iterations: int = 3,
    ) -> ExtractionGraphState:
        """
        Synchronous version of run_extraction.

        Convenience method for non-async contexts.
        """
        import asyncio
        return asyncio.run(self.run_extraction(
            pdf_path=pdf_path,
            image_paths=image_paths,
            paper_id=paper_id,
            max_iterations=max_iterations,
        ))

    def get_extraction_summary(self, result: ExtractionGraphState) -> Dict[str, Any]:
        """
        Generate a summary of extraction results.

        Args:
            result: Final extraction state

        Returns:
            Summary dictionary with key statistics
        """
        final_extractions = result.get("final_extractions", [])
        draft_extractions = result.get("draft_extractions", [])

        # Count by evidence type
        type_counts = {}
        for item in final_extractions:
            etype = item.get("evidence_type", "UNKNOWN")
            type_counts[etype] = type_counts.get(etype, 0) + 1

        # Calculate field coverage
        from tools.schemas import TIER_1_FIELDS
        tier1_coverages = []
        for item in final_extractions:
            present = sum(1 for f in TIER_1_FIELDS if item.get(f) is not None)
            tier1_coverages.append(present / len(TIER_1_FIELDS) * 100)

        avg_coverage = round(sum(tier1_coverages) / len(tier1_coverages), 1) if tier1_coverages else 0

        return {
            "paper_id": result.get("paper_id", "unknown"),
            "paper_type": result.get("paper_type", "unknown"),
            "is_complete": result.get("is_complete", False),
            "iterations_used": result.get("iteration_count", 0),
            "max_iterations": result.get("max_iterations", 3),
            "total_items": len(final_extractions),
            "draft_items": len(draft_extractions),
            "items_by_type": type_counts,
            "average_tier1_coverage": avg_coverage,
            "critique_assessment": result.get("critique", {}).get("overall_assessment", "N/A"),
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def extract_from_pdf(
    pdf_path: str,
    paper_id: Optional[str] = None,
    verbose: bool = True,
    max_iterations: int = 3,
) -> Dict[str, Any]:
    """
    Convenience function to extract evidence from a PDF.

    Args:
        pdf_path: Path to PDF file
        paper_id: Optional paper identifier (defaults to filename)
        verbose: Enable verbose logging
        max_iterations: Maximum Critic→Extractor iterations

    Returns:
        Dictionary with extraction results
    """
    if paper_id is None:
        paper_id = Path(pdf_path).stem

    client = CivicExtractionClient(verbose=verbose)
    result = client.run_extraction_sync(
        pdf_path=pdf_path,
        paper_id=paper_id,
        max_iterations=max_iterations,
    )

    return {
        "paper_id": paper_id,
        "evidence_items": result.get("final_extractions", []),
        "summary": client.get_extraction_summary(result),
        "paper_content": result.get("paper_content", {}),
        "extraction_plan": result.get("extraction_plan", {}),
        "critique": result.get("critique", {}),
    }


if __name__ == "__main__":
    # Simple test
    import sys

    if len(sys.argv) < 2:
        print("Usage: python client.py <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    result = extract_from_pdf(pdf_path)

    print(f"\nExtraction Summary:")
    print(f"  Paper ID: {result['summary']['paper_id']}")
    print(f"  Total Items: {result['summary']['total_items']}")
    print(f"  Items by Type: {result['summary']['items_by_type']}")
    print(f"  Avg Coverage: {result['summary']['average_tier1_coverage']}%")
