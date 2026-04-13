#!/usr/bin/env python
"""
Resume extraction from saved Reader output (without re-running Reader).

Usage:
  uv run python scripts/resume_from_reader.py --paper-id PMID_26193344 \
      --reader-json ../outputs/checkpoints/PMID_26193344/01_reader_output.json

This loads paper_content from the JSON, regenerates paper_content_text, and runs
the orchestrator (Planner→Extractor→Critic→Normalizer). Artifacts are saved under
outputs/{paper_id}/{timestamp}/.
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from client import CivicExtractionClient
from tools.paper_content_tools import _generate_paper_context_text  # type: ignore


async def run_resume(paper_id: str, reader_json: Path, max_iterations: int = 3, verbose: bool = True):
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING)

    data = json.loads(reader_json.read_text())
    paper_content = data.get("paper_content", {})
    if not paper_content:
        raise RuntimeError("reader_json missing 'paper_content'")

    paper_content_text = _generate_paper_context_text(paper_content)

    client = CivicExtractionClient(verbose=verbose)
    # Directly run orchestrator phase
    result = await client.run_orchestrator_phase(
        paper_content=paper_content,
        paper_content_text=paper_content_text,
        paper_id=paper_id,
        max_iterations=max_iterations,
    )

    # Use existing artifact saver
    from scripts.run_extraction import create_run_directory, save_all_artifacts
    from datetime import datetime
    from config.settings import OUTPUTS_DIR

    run_dir = create_run_directory(paper_id, OUTPUTS_DIR)
    # Generate summary
    summary = client.get_extraction_summary(result)
    saved = save_all_artifacts(
        run_dir=run_dir,
        result=result,
        summary=summary,
        paper_id=paper_id,
        pdf_path=f"RESUMED_FROM:{reader_json}",
        start_time=datetime.now(),
        duration=0.0,
    )
    print("Run directory:", run_dir)
    print("Saved:", json.dumps(saved, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper-id", required=True)
    ap.add_argument("--reader-json", required=True, type=Path)
    ap.add_argument("--max-iterations", type=int, default=3)
    ap.add_argument("--verbose", action="store_true", default=True)
    args = ap.parse_args()

    asyncio.run(run_resume(
        paper_id=args.paper_id,
        reader_json=args.reader_json,
        max_iterations=args.max_iterations,
        verbose=args.verbose,
    ))


if __name__ == "__main__":
    main()

