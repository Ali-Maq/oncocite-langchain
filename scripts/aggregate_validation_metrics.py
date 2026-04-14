#!/usr/bin/env python
"""
Aggregate validation metrics across the 10 retrospective Multiple Myeloma
papers → produces the summary numbers shown in Table S3 of the OncoCITE
manuscript (Ground Truth Recovery, Novel Discovery Precision, Critical
Error Rate, GT Curation Errors Detected), with Wilson 95% CIs.

Uses the analysis.regenerated.json files produced by
scripts/run_three_way_analysis.py (or the committed analysis.json files
if `--use-committed` is passed).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import List, Tuple


def wilson_ci(k: int, n: int, z: float = 1.96) -> Tuple[float, float, float]:
    """Wilson score confidence interval for a proportion."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    halfwidth = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (phat, max(0.0, center - halfwidth), min(1.0, center + halfwidth))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=Path("test_paper/triplet"),
        help="Directory of PMID_* folders.",
    )
    parser.add_argument(
        "--use-committed",
        action="store_true",
        help="Use analysis.json (committed) instead of analysis.regenerated.json.",
    )
    parser.add_argument("--output", type=Path, default=Path("-"))
    args = parser.parse_args()

    aligned_total = 0
    gt_total = 0
    ai_total = 0
    missing_total = 0
    hallucinated_total = 0
    improvements_total = 0
    rows: List[dict] = []

    for folder in sorted(args.corpus_dir.iterdir()):
        if not folder.is_dir() or not folder.name.startswith("PMID_"):
            continue
        fname = "analysis.json" if args.use_committed else "analysis.regenerated.json"
        fpath = folder / fname
        if not fpath.exists() or fpath.stat().st_size == 0:
            continue
        try:
            data = json.loads(fpath.read_text())
        except json.JSONDecodeError:
            continue
        align = data.get("alignment") or []
        missing = data.get("missing_from_ai") or []
        halluc = data.get("ai_hallucinated_items") or []
        improvements = data.get("ai_improvements_over_gt") or []
        gt_n = int(data.get("gt_evidence_item_count") or 0)
        ai_n = int(data.get("ai_evidence_item_count") or 0)

        aligned_total += len(align)
        gt_total += gt_n
        ai_total += ai_n
        missing_total += len(missing)
        hallucinated_total += len(halluc)
        improvements_total += len(improvements)

        rows.append(
            {
                "paper_id": data.get("paper_id") or folder.name,
                "gt_items": gt_n,
                "ai_items": ai_n,
                "aligned": len(align),
                "missing_from_ai": len(missing),
                "hallucinated": len(halluc),
                "improvements": len(improvements),
            }
        )

    # Recovery = aligned_tuples / gt_items (approximates paper's definition)
    recovery_p, recovery_lo, recovery_hi = wilson_ci(aligned_total, max(gt_total, 1))

    # Novel precision = improvements / (improvements + hallucinated)
    novel_denom = improvements_total + hallucinated_total
    novel_p, novel_lo, novel_hi = wilson_ci(improvements_total, max(novel_denom, 1))

    # Critical error rate = hallucinated / total AI items
    crit_p, crit_lo, crit_hi = wilson_ci(hallucinated_total, max(ai_total, 1))

    # GT discrepancies = papers where missing_from_ai indicates GT issue
    gt_err_papers = sum(1 for r in rows if r["missing_from_ai"] > 0 or r["hallucinated"] > 0)

    out = {
        "source": str(fname),
        "corpus_size": len(rows),
        "totals": {
            "gt_items": gt_total,
            "ai_items": ai_total,
            "aligned_tuples": aligned_total,
            "missing_from_ai": missing_total,
            "ai_hallucinated_items": hallucinated_total,
            "ai_improvements_over_gt": improvements_total,
        },
        "primary_metrics": {
            "ground_truth_recovery": {
                "value": recovery_p,
                "ci_95_lo": recovery_lo,
                "ci_95_hi": recovery_hi,
                "paper_reported": 0.840,
            },
            "novel_discovery_precision": {
                "value": novel_p,
                "ci_95_lo": novel_lo,
                "ci_95_hi": novel_hi,
                "paper_reported": 0.978,
            },
            "critical_error_rate": {
                "value": crit_p,
                "ci_95_lo": crit_lo,
                "ci_95_hi": crit_hi,
                "paper_reported": 0.000,
            },
        },
        "per_paper": rows,
    }

    text = json.dumps(out, indent=2)
    if args.output == Path("-"):
        print(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
        print(f"wrote {args.output}")

    # Also emit a human-readable summary
    print()
    print("Summary (Table S3-equivalent):")
    print(
        f"  Ground truth recovery:     {recovery_p:.3f}  "
        f"(95% CI {recovery_lo:.3f}-{recovery_hi:.3f})   [paper: 0.840]"
    )
    print(
        f"  Novel discovery precision: {novel_p:.3f}  "
        f"(95% CI {novel_lo:.3f}-{novel_hi:.3f})   [paper: 0.978]"
    )
    print(
        f"  Critical error rate:       {crit_p:.3f}  "
        f"(95% CI {crit_lo:.3f}-{crit_hi:.3f})   [paper: 0.000]"
    )
    print(f"  Corpus size: {len(rows)} papers, {gt_total} GT items, {ai_total} AI items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
