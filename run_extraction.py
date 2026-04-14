#!/usr/bin/env python
"""
OncoCITE extraction — paper-spec CLI entry point.

Matches the install-and-run commands documented in the OncoCITE manuscript
(Supplementary Note S2.3):

    pip install -r requirements.txt
    python run_extraction.py --input paper.pdf --output results/

This is a thin wrapper around `scripts/run_extraction.py` that accepts a
direct PDF path instead of a paper_id lookup against a papers directory.
For the full-featured CLI (paper_id mode, batch runs, checkpoint resume)
see `scripts/run_extraction.py`.
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from client import CivicExtractionClient
from hooks.logging_callbacks import get_tool_usage_log, start_new_log_session
from runtime.llm import get_llm_retry_stats

# The Normalizer stage (paper Sec 2.2 / 2.4) — runs as a deterministic
# post-processor after the Extractor-Critic loop completes. Queries the
# same MyGene / MyVariant / OLS / RxNorm endpoints documented in
# Supplementary Table S21 and writes the Tier-2 identifiers back into
# each evidence item.
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
try:
    from enrich_extractions import enrich_output_sync
    _ENRICHMENT_AVAILABLE = True
except Exception:  # pragma: no cover
    _ENRICHMENT_AVAILABLE = False


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_extraction.py",
        description=(
            "Run the OncoCITE multi-agent extraction pipeline on a scientific "
            "paper PDF and emit a structured evidence-items JSON."
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to the source PDF file.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output directory (will be created if it does not exist).",
    )
    parser.add_argument(
        "--paper-id",
        default=None,
        help="Optional paper identifier; defaults to the PDF filename stem.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum Critic-Extractor refinement iterations (default: 3).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limit Reader to the first N pages (default: all pages).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable verbose logging.",
    )
    args = parser.parse_args()

    pdf_path: Path = args.input.expanduser().resolve()
    output_dir: Path = args.output.expanduser().resolve()

    if not pdf_path.is_file():
        print(f"ERROR: input PDF not found: {pdf_path}", file=sys.stderr)
        return 2

    paper_id = args.paper_id or pdf_path.stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / paper_id / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    verbose = not args.quiet
    log_level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(run_dir / "run.log"),
        ],
    )
    start_new_log_session()

    print("=" * 70)
    print("OncoCITE — CIViC evidence extraction")
    print("=" * 70)
    print(f"Input PDF:    {pdf_path}")
    print(f"Paper ID:     {paper_id}")
    print(f"Run dir:      {run_dir}")
    print(f"Iterations:   {args.max_iterations}")
    if args.max_pages:
        print(f"Max pages:    {args.max_pages}")
    print("=" * 70)

    client = CivicExtractionClient(verbose=verbose)

    started = datetime.now()
    result = asyncio.run(
        client.run_extraction(
            pdf_path=str(pdf_path),
            paper_id=paper_id,
            max_iterations=args.max_iterations,
            max_pages=args.max_pages,
        )
    )
    duration = (datetime.now() - started).total_seconds()

    final_path = run_dir / f"{paper_id}_extraction.json"
    payload = {
        "paper_id": paper_id,
        "pdf_path": str(pdf_path),
        "timestamp": timestamp,
        "duration_seconds": duration,
        "extraction": result,
        "tool_usage": get_tool_usage_log(),
        "retry_stats": get_llm_retry_stats(),
    }

    # Normalizer stage — fill Tier-2 ontology identifiers and the
    # mechanically-derivable Tier-1 fields (molecular_profile_name,
    # disease_display_name, feature_types, therapy_interaction_type,
    # source_citation_id) that the Extractor / Critic loop doesn't emit
    # natively. Runs only after extraction succeeds.
    if _ENRICHMENT_AVAILABLE:
        try:
            stats = enrich_output_sync(payload, paper_id)
            payload["_normalizer_stats"] = stats
            if verbose:
                print(
                    f"[Normalizer] enriched {stats.get('items', 0)} items, "
                    f"+{stats.get('delta', 0)} field values populated via "
                    f"external ontology APIs (MyGene / MyVariant / OLS / RxNorm)"
                )
        except Exception as exc:
            if verbose:
                print(f"[Normalizer] enrichment skipped ({exc})")

    final_path.write_text(json.dumps(payload, indent=2, default=str))

    items = result.get("final_extractions") or result.get("evidence_items") or []
    print()
    print(f"Done in {duration:.1f}s — {len(items)} evidence items → {final_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
