#!/usr/bin/env python
"""
Expert adjudication workflow — paper Section 4.5, "Domain Expert Adjudication".

The three-way analysis agent (scripts/run_three_way_analysis.py) surfaces
candidate discrepancies between CIViC ground truth and OncoCITE
extraction. Paper Sec 4.5 requires a domain expert (S.T., Multiple
Myeloma) to review each candidate and render a judgment:

    CONFIRMED   — the flagged discrepancy is genuine
    REJECTED    — reflects acceptable curatorial interpretation
    UNCERTAIN   — ambiguous case

Only CONFIRMED discrepancies are reported as ground-truth errors; the
others are retained in the ground truth for metric calculations
(paper Sec 4.5).

This tool does NOT replace the human. It operationalizes the workflow by:

  1. `--emit-packet`   extracts candidates from analysis.regenerated.json
                       into a flat CSV/Markdown review packet that an
                       expert can mark up.
  2. `--ingest`        reads the marked-up decisions back in and merges
                       them onto the raw analysis to produce the
                       post-adjudication `analysis.json`.

Two metric numbers therefore flow from the pipeline:

    pre-adjudication  — raw analysis agent output (what the LLM flagged)
    post-adjudication — after S.T. confirmed/rejected each flag (what
                        the manuscript reports)

The committed `test_paper/triplet/*/analysis.json` files reflect the
post-adjudication state that went into the manuscript.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("expert_adjudication")


# ---------------------------------------------------------------------------
# Packet generation — list every candidate discrepancy in a reviewable form
# ---------------------------------------------------------------------------


def _candidates_from(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten the analysis JSON into one row per discrepancy candidate."""
    rows: List[Dict[str, Any]] = []
    pid = doc.get("paper_id") or ""

    for entry in doc.get("missing_from_ai") or []:
        rows.append(
            {
                "paper_id": pid,
                "candidate_kind": "missing_from_ai",
                "tuple_id": entry.get("tuple_id", ""),
                "gt_index": entry.get("gt_index", ""),
                "ai_index": "",
                "reason": entry.get("reason_missing", ""),
                "expert_judgment": "",
                "expert_rationale": "",
            }
        )
    for entry in doc.get("ai_hallucinated_items") or []:
        rows.append(
            {
                "paper_id": pid,
                "candidate_kind": "ai_hallucinated",
                "tuple_id": entry.get("tuple_id", ""),
                "gt_index": "",
                "ai_index": entry.get("ai_index", ""),
                "reason": entry.get("paper_contradicts_with", ""),
                "expert_judgment": "",
                "expert_rationale": "",
            }
        )
    for entry in doc.get("ai_improvements_over_gt") or []:
        rows.append(
            {
                "paper_id": pid,
                "candidate_kind": "ai_improvement",
                "tuple_id": entry.get("tuple_id", ""),
                "gt_index": "",
                "ai_index": entry.get("ai_index", ""),
                "reason": entry.get("paper_support", ""),
                "expert_judgment": "",
                "expert_rationale": "",
            }
        )

    # Per-tuple field statuses that aren't "EXACT_MATCH_WITH_PAPER" are
    # also candidates for expert review.
    for tup in doc.get("alignment") or []:
        tid = tup.get("tuple_id", "")
        fs = tup.get("field_status") or {}
        for field, status in fs.items():
            if status and status != "EXACT_MATCH_WITH_PAPER":
                rows.append(
                    {
                        "paper_id": pid,
                        "candidate_kind": f"field:{status}",
                        "tuple_id": tid,
                        "gt_index": "",
                        "ai_index": "",
                        "reason": f"{field} flagged as {status}",
                        "expert_judgment": "",
                        "expert_rationale": "",
                    }
                )
    return rows


def emit_packet(analysis_paths: List[Path], out_csv: Path, out_md: Path) -> None:
    all_rows: List[Dict[str, Any]] = []
    for p in analysis_paths:
        try:
            doc = json.loads(p.read_text())
        except json.JSONDecodeError:
            logger.warning("skip %s (JSON error)", p)
            continue
        all_rows.extend(_candidates_from(doc))

    fieldnames = [
        "paper_id",
        "candidate_kind",
        "tuple_id",
        "gt_index",
        "ai_index",
        "reason",
        "expert_judgment",
        "expert_rationale",
    ]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_rows)
    logger.info("wrote %d candidates to %s", len(all_rows), out_csv)

    # Markdown review packet
    lines: List[str] = []
    lines.append("# Expert adjudication packet — OncoCITE three-way validation")
    lines.append("")
    lines.append(
        "Following paper Section 4.5, each candidate below requires an "
        "independent domain-expert judgment: **CONFIRMED** (genuine "
        "discrepancy), **REJECTED** (acceptable curatorial interpretation), "
        "or **UNCERTAIN** (ambiguous). Only CONFIRMED items are reported "
        "as ground-truth errors in the manuscript."
    )
    lines.append("")
    by_paper: Dict[str, List[Dict[str, Any]]] = {}
    for r in all_rows:
        by_paper.setdefault(r["paper_id"], []).append(r)
    for pid in sorted(by_paper):
        lines.append(f"## {pid}")
        lines.append("")
        lines.append("| # | kind | tuple | reason | judgment | rationale |")
        lines.append("|---|---|---|---|---|---|")
        for i, r in enumerate(by_paper[pid], 1):
            lines.append(
                f"| {i} | `{r['candidate_kind']}` | `{r['tuple_id']}` | {r['reason'][:140]} | ___ | ___ |"
            )
        lines.append("")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines) + "\n")
    logger.info("wrote packet to %s", out_md)


# ---------------------------------------------------------------------------
# Ingest decisions and build post-adjudication analysis.json
# ---------------------------------------------------------------------------


def _key(row: Dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("paper_id", "")),
            str(row.get("candidate_kind", "")),
            str(row.get("tuple_id", "")),
            str(row.get("gt_index", "")),
            str(row.get("ai_index", "")),
        ]
    )


def ingest_decisions(
    analysis_in: Path, decisions_csv: Path, analysis_out: Path
) -> Dict[str, int]:
    doc = json.loads(analysis_in.read_text())
    decisions: Dict[str, Dict[str, str]] = {}
    with decisions_csv.open() as fh:
        for row in csv.DictReader(fh):
            if row.get("paper_id") != doc.get("paper_id"):
                continue
            decisions[_key(row)] = {
                "judgment": (row.get("expert_judgment") or "").strip().upper(),
                "rationale": (row.get("expert_rationale") or "").strip(),
            }

    counts = {"CONFIRMED": 0, "REJECTED": 0, "UNCERTAIN": 0, "unadjudicated": 0}

    def _annotate(entries: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
        kept: List[Dict[str, Any]] = []
        for e in entries:
            k = "|".join(
                [
                    doc.get("paper_id", ""),
                    kind,
                    str(e.get("tuple_id", "")),
                    str(e.get("gt_index", "")) if "gt_index" in e else "",
                    str(e.get("ai_index", "")) if "ai_index" in e else "",
                ]
            )
            dec = decisions.get(k)
            if not dec or not dec["judgment"]:
                counts["unadjudicated"] += 1
                e["expert_judgment"] = "UNADJUDICATED"
                kept.append(e)
                continue
            j = dec["judgment"]
            if j not in counts:
                counts[j] = 0
            counts[j] += 1
            e["expert_judgment"] = j
            e["expert_rationale"] = dec["rationale"]
            if j == "CONFIRMED":
                kept.append(e)  # retained as genuine GT error
            # REJECTED / UNCERTAIN → still kept in the document, but flagged
            elif j in ("REJECTED", "UNCERTAIN"):
                kept.append(e)
        return kept

    doc["missing_from_ai"] = _annotate(doc.get("missing_from_ai") or [], "missing_from_ai")
    doc["ai_hallucinated_items"] = _annotate(
        doc.get("ai_hallucinated_items") or [], "ai_hallucinated"
    )
    doc["ai_improvements_over_gt"] = _annotate(
        doc.get("ai_improvements_over_gt") or [], "ai_improvement"
    )

    doc.setdefault("_adjudication", {})
    doc["_adjudication"].update(
        {
            "method": "Paper Sec 4.5 — domain expert review (S.T., Multiple Myeloma)",
            "decisions_source": str(decisions_csv),
            "counts": counts,
        }
    )

    analysis_out.parent.mkdir(parents=True, exist_ok=True)
    analysis_out.write_text(json.dumps(doc, indent=2))
    logger.info(
        "ingested: CONFIRMED=%d REJECTED=%d UNCERTAIN=%d unadjudicated=%d",
        counts.get("CONFIRMED", 0),
        counts.get("REJECTED", 0),
        counts.get("UNCERTAIN", 0),
        counts["unadjudicated"],
    )
    return counts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    emit = sub.add_parser("emit-packet", help="Extract candidates into a review packet.")
    emit.add_argument(
        "--analysis",
        nargs="+",
        type=Path,
        required=True,
        help="One or more analysis.regenerated.json files.",
    )
    emit.add_argument("--out-csv", type=Path, default=Path("data/adjudication/packet.csv"))
    emit.add_argument("--out-md", type=Path, default=Path("data/adjudication/packet.md"))

    ingest = sub.add_parser("ingest", help="Merge expert decisions into a final analysis.json.")
    ingest.add_argument("--analysis", type=Path, required=True)
    ingest.add_argument("--decisions-csv", type=Path, required=True)
    ingest.add_argument("--out", type=Path, required=True)

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )

    if args.cmd == "emit-packet":
        emit_packet(args.analysis, args.out_csv, args.out_md)
    else:
        ingest_decisions(args.analysis, args.decisions_csv, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
