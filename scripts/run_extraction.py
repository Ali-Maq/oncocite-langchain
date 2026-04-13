#!/usr/bin/env python
"""
CIViC Evidence Extraction Script (LangGraph Version)
=====================================================

Command-line interface for running CIViC evidence extraction on scientific papers.

OUTPUT STRUCTURE:
    outputs/
    └── {paper_id}/
        └── {YYYYMMDD_HHMMSS}/          # Timestamped run folder
            ├── 00_summary.json          # Extraction summary
            ├── 01_paper_content.json    # Reader output (structured)
            ├── 02_paper_content.txt     # Reader output (text)
            ├── 03_extraction_plan.json  # Planner output
            ├── 04_draft_extractions.json# Extractor output
            ├── 05_critique.json         # Critic output
            ├── 06_final_extractions.json# Normalizer output
            ├── 07_tool_usage_log.json   # Tool call history
            ├── 08_retry_stats.json      # LLM retry statistics
            ├── extraction_graph.md      # Pipeline visualization
            └── run.log                  # Detailed log file

Usage:
    uv run python scripts/run_extraction.py <paper_id>
    uv run python scripts/run_extraction.py <paper_id> --papers-dir ./papers
    uv run python scripts/run_extraction.py PMID_12345 --max-iterations 5

Examples:
    uv run python scripts/run_extraction.py longhurst_2014
    uv run python scripts/run_extraction.py PMID_11050000 --verbose
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from client import CivicExtractionClient
from config.settings import PAPERS_DIR, OUTPUTS_DIR
from hooks.logging_callbacks import get_tool_usage_log, start_new_log_session
from runtime.llm import get_llm_retry_stats

logger = logging.getLogger(__name__)


def find_pdf_path(paper_id: str, papers_dir: Path) -> Path:
    """
    Find the PDF file for a paper ID.

    Searches for:
    - {papers_dir}/{paper_id}/{paper_id}.pdf
    - {papers_dir}/{paper_id}/paper.pdf
    - {papers_dir}/{paper_id}.pdf

    Args:
        paper_id: Paper identifier
        papers_dir: Directory containing papers

    Returns:
        Path to PDF file

    Raises:
        FileNotFoundError: If PDF not found
    """
    # Try folder with paper ID
    paper_folder = papers_dir / paper_id
    if paper_folder.is_dir():
        # Try {paper_id}.pdf
        pdf_path = paper_folder / f"{paper_id}.pdf"
        if pdf_path.exists():
            return pdf_path

        # Try paper.pdf
        pdf_path = paper_folder / "paper.pdf"
        if pdf_path.exists():
            return pdf_path

        # Try any .pdf file in folder
        pdfs = list(paper_folder.glob("*.pdf"))
        if pdfs:
            return pdfs[0]

    # Try direct path
    pdf_path = papers_dir / f"{paper_id}.pdf"
    if pdf_path.exists():
        return pdf_path

    raise FileNotFoundError(
        f"Could not find PDF for paper '{paper_id}' in {papers_dir}. "
        f"Tried: {paper_folder}/{paper_id}.pdf, {paper_folder}/paper.pdf, {pdf_path}"
    )


def create_run_directory(paper_id: str, output_dir: Path) -> Path:
    """
    Create a timestamped run directory for a paper.

    Structure: {output_dir}/{paper_id}/{YYYYMMDD_HHMMSS}/

    Args:
        paper_id: Paper identifier
        output_dir: Base output directory

    Returns:
        Path to run directory
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / paper_id / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def save_artifact(run_dir: Path, filename: str, data: any, as_text: bool = False) -> Path:
    """
    Save an artifact to the run directory.

    Args:
        run_dir: Run directory path
        filename: Filename (with extension)
        data: Data to save (dict for JSON, str for text)
        as_text: If True, save as plain text

    Returns:
        Path to saved file
    """
    filepath = run_dir / filename

    if as_text:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(str(data))
    else:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str, ensure_ascii=False)

    return filepath


def save_all_artifacts(
    run_dir: Path,
    result: dict,
    summary: dict,
    paper_id: str,
    pdf_path: str,
    start_time: datetime,
    duration: float,
) -> dict:
    """
    Save all extraction artifacts to the run directory.

    Args:
        run_dir: Run directory path
        result: Full extraction result
        summary: Extraction summary
        paper_id: Paper identifier
        pdf_path: Path to source PDF
        start_time: Extraction start time
        duration: Total duration in seconds

    Returns:
        Dict mapping artifact names to file paths
    """
    saved_files = {}

    # 00: Summary
    summary_data = {
        "paper_id": paper_id,
        "pdf_path": str(pdf_path),
        "run_timestamp": start_time.isoformat(),
        "duration_seconds": round(duration, 2),
        "summary": summary,
        "is_complete": result.get("is_complete", False),
        "iterations_used": result.get("iteration_count", 0),
        "max_iterations": result.get("max_iterations", 3),
    }
    saved_files["summary"] = str(save_artifact(run_dir, "00_summary.json", summary_data))

    # 01: Paper content (structured)
    paper_content = result.get("paper_content", {})
    if paper_content:
        saved_files["paper_content"] = str(save_artifact(run_dir, "01_paper_content.json", paper_content))

    # 02: Paper content (text)
    paper_content_text = result.get("paper_content_text", "")
    if paper_content_text:
        saved_files["paper_content_text"] = str(save_artifact(run_dir, "02_paper_content.txt", paper_content_text, as_text=True))

    # 02b: Per-page JSON extractions (if available)
    page_extractions = result.get("page_extractions", [])
    if page_extractions:
        pages_dir = run_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        for p in page_extractions:
            pn = p.get("page_number", "unknown")
            try:
                pn_int = int(pn)
            except Exception:
                pn_int = 0
            (pages_dir / f"page_{pn_int:03d}.json").write_text(json.dumps(p, indent=2))
        saved_files["page_extractions_dir"] = str(pages_dir)

    # 03: Extraction plan
    extraction_plan = result.get("extraction_plan", {})
    if extraction_plan:
        saved_files["extraction_plan"] = str(save_artifact(run_dir, "03_extraction_plan.json", extraction_plan))

    # 04: Draft extractions
    draft_extractions = result.get("draft_extractions", [])
    if draft_extractions:
        saved_files["draft_extractions"] = str(save_artifact(run_dir, "04_draft_extractions.json", draft_extractions))

    # 05: Critique
    critique = result.get("critique", {})
    if critique:
        saved_files["critique"] = str(save_artifact(run_dir, "05_critique.json", critique))

    # 06: Final extractions (the main output)
    final_extractions = result.get("final_extractions", [])
    saved_files["final_extractions"] = str(save_artifact(run_dir, "06_final_extractions.json", final_extractions))

    # 07: Tool usage log
    tool_log = get_tool_usage_log()
    if tool_log:
        saved_files["tool_usage_log"] = str(save_artifact(run_dir, "07_tool_usage_log.json", tool_log))

    # 08: Retry statistics
    retry_stats = get_llm_retry_stats()
    if retry_stats:
        saved_files["retry_stats"] = str(save_artifact(run_dir, "08_retry_stats.json", retry_stats))

    # Graph visualization
    try:
        from runtime.visualization import save_graph_visualization
        from graphs.extraction_graph import build_extraction_graph

        graph = build_extraction_graph()
        viz_path = save_graph_visualization(
            graph,
            run_dir / "extraction_graph.md",
            title=f"CIViC Pipeline - {paper_id}"
        )
        saved_files["graph_visualization"] = str(viz_path)
    except Exception as e:
        logger.warning(f"Could not save graph visualization: {e}")

    return saved_files


async def run_extraction(
    paper_id: str,
    papers_dir: Path,
    output_dir: Path,
    max_iterations: int = 3,
    verbose: bool = True,
    max_pages: int = 0,
) -> dict:
    """
    Run extraction pipeline on a paper.

    Creates a timestamped output folder per run with all artifacts.

    Args:
        paper_id: Paper identifier
        papers_dir: Directory containing papers
        output_dir: Base directory for output files
        max_iterations: Maximum Critic-Extractor iterations
        verbose: Enable verbose logging

    Returns:
        Extraction results dictionary with file paths
    """
    start_time = datetime.now()

    # Start a new logging session
    start_new_log_session(paper_id)

    # Find PDF
    try:
        pdf_path = find_pdf_path(paper_id, papers_dir)
        logger.info(f"Found PDF: {pdf_path}")
    except FileNotFoundError as e:
        logger.error(str(e))
        return {"error": str(e), "paper_id": paper_id}

    # Create run directory
    run_dir = create_run_directory(paper_id, output_dir)
    logger.info(f"Output directory: {run_dir}")

    # Set up file logging for this run
    file_handler = logging.FileHandler(run_dir / "run.log")
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logging.getLogger().addHandler(file_handler)

    # Initialize client
    client = CivicExtractionClient(verbose=verbose)

    # Run extraction
    try:
        result = await client.run_extraction(
            pdf_path=str(pdf_path),
            paper_id=paper_id,
            max_iterations=max_iterations,
            max_pages=(max_pages or None),
        )
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        import traceback
        traceback.print_exc()

        # Save error info
        error_data = {
            "paper_id": paper_id,
            "error": str(e),
            "timestamp": start_time.isoformat(),
        }
        save_artifact(run_dir, "00_error.json", error_data)
        return {"error": str(e), "paper_id": paper_id, "run_dir": str(run_dir)}

    # Calculate timing
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # Get summary
    summary = client.get_extraction_summary(result)

    # Save all artifacts
    saved_files = save_all_artifacts(
        run_dir=run_dir,
        result=result,
        summary=summary,
        paper_id=paper_id,
        pdf_path=str(pdf_path),
        start_time=start_time,
        duration=duration,
    )

    # Build return results
    results = {
        "paper_id": paper_id,
        "pdf_path": str(pdf_path),
        "run_dir": str(run_dir),
        "timestamp": start_time.isoformat(),
        "duration_seconds": round(duration, 2),
        "summary": summary,
        "saved_files": saved_files,
        "extraction": {
            "items_count": len(result.get("final_extractions", [])),
            "evidence_items": result.get("final_extractions", []),
        },
    }

    # Print summary
    print("\n" + "=" * 70)
    print("EXTRACTION COMPLETE")
    print("=" * 70)
    print(f"Paper ID:         {paper_id}")
    print(f"Duration:         {duration:.1f} seconds")
    print(f"Evidence Items:   {summary['total_items']}")
    print(f"Items by Type:    {summary['items_by_type']}")
    print(f"Tier 1 Coverage:  {summary['average_tier1_coverage']}%")
    print(f"Iterations:       {summary['iterations_used']}/{summary['max_iterations']}")
    print(f"Critique:         {summary['critique_assessment']}")
    print("-" * 70)
    print("OUTPUT FILES:")
    for name, path in saved_files.items():
        print(f"  {name}: {path}")
    print("=" * 70)

    # Remove file handler
    logging.getLogger().removeHandler(file_handler)

    return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Extract CIViC evidence from scientific papers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Output Structure:
    outputs/{paper_id}/{timestamp}/
        00_summary.json          - Extraction summary
        01_paper_content.json    - Structured paper content
        02_paper_content.txt     - Full text content
        03_extraction_plan.json  - Planner strategy
        04_draft_extractions.json- Initial evidence items
        05_critique.json         - Critic assessment
        06_final_extractions.json- Normalized evidence items
        07_tool_usage_log.json   - Tool call history
        08_retry_stats.json      - LLM retry statistics
        extraction_graph.md      - Pipeline visualization
        run.log                  - Detailed execution log

Examples:
    %(prog)s longhurst_2014
    %(prog)s PMID_11050000 --papers-dir ./test_paper/triplet
    %(prog)s paper123 --max-iterations 5 --verbose
        """,
    )

    parser.add_argument(
        "paper_id",
        help="Paper identifier (matches folder/filename in papers directory)",
    )
    parser.add_argument(
        "--papers-dir",
        type=Path,
        default=PAPERS_DIR,
        help=f"Directory containing papers (default: {PAPERS_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUTS_DIR,
        help=f"Base directory for outputs (default: {OUTPUTS_DIR})",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum Critic-Extractor iterations (default: 3)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Limit Reader to first N pages (0 = all)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=True,
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Disable verbose logging",
    )

    args = parser.parse_args()

    # Set up logging
    verbose = args.verbose and not args.quiet
    log_level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Print banner
    print("\n" + "=" * 70)
    print("CIViC EVIDENCE EXTRACTION PIPELINE")
    print("=" * 70)
    print(f"Paper ID:     {args.paper_id}")
    print(f"Papers Dir:   {args.papers_dir}")
    print(f"Output Dir:   {args.output_dir}")
    print(f"Max Iterations: {args.max_iterations}")
    print("=" * 70 + "\n")

    # Run extraction
    results = asyncio.run(
        run_extraction(
            paper_id=args.paper_id,
            papers_dir=args.papers_dir,
            output_dir=args.output_dir,
            max_iterations=args.max_iterations,
            max_pages=args.max_pages,
            verbose=verbose,
        )
    )

    # Exit with error code if extraction failed
    if "error" in results:
        sys.exit(1)

    # Print final location
    print(f"\nAll outputs saved to: {results.get('run_dir', 'N/A')}")


if __name__ == "__main__":
    main()
