#!/usr/bin/env python
"""
Regenerate Supplementary Figure S1 panels (A–G) from the CIViC evidence
corpus — the "Extended CIViC Database Analysis" figure in the OncoCITE
manuscript (Section 2.1, Section 4.3, Supp Fig S1).

Panels reproduced:
  A  Long-tail source distribution (evidence items per source, log scale)
  B  Temporal evidence production (items + unique sources per year)
  C  Evidence level × evidence type heatmap
  D  Trust rating violin plots across evidence levels
  E  Clinical significance profile by evidence type
  F  Variant origin × evidence type (categorical heatmap)
  G  Top diseases by evidence volume / type

Usage:
  python scripts/generate_eda_figures.py \\
      --input-csv /path/to/civic_evidence_denormalized.csv \\
      --outdir data/figures

Matches the plotting recipe described in Section 4.3: matplotlib 3.7,
seaborn 0.12, 300 DPI, Python 3.11 / pandas 2.0. No LLM / API required;
pure data analysis.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    import seaborn as sns
except ImportError:
    sns = None

logger = logging.getLogger("eda")


def _load(csv_path: Path) -> pd.DataFrame:
    logger.info("loading %s", csv_path)
    df = pd.read_csv(csv_path, low_memory=False)
    df = df.drop_duplicates(subset="evidence_id", keep="first")
    logger.info("unique evidence items: %d", len(df))
    return df


def panel_a(df: pd.DataFrame, out: Path) -> None:
    """Long-tail source distribution — evidence items per unique source."""
    per_src = df.groupby("source_citation_id").size().sort_values(ascending=False)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(per_src.values, bins=np.logspace(0, np.log10(per_src.max() + 1), 30), color="#4c72b0")
    ax.set_xscale("log")
    ax.set_xlabel("Evidence items per source (log scale)")
    ax.set_ylabel("Number of sources")
    ax.set_title(f"S1A  Long-tail source distribution (n={len(per_src):,} unique sources)")
    fig.tight_layout()
    fig.savefig(out, dpi=300)
    plt.close(fig)
    logger.info("wrote %s", out)


def panel_b(df: pd.DataFrame, out: Path) -> None:
    """Temporal evidence production by publication year."""
    d = df.copy()
    d["year"] = pd.to_numeric(d["source_publication_year"], errors="coerce")
    d = d.dropna(subset=["year"])
    d = d[(d["year"] >= 1985) & (d["year"] <= 2025)]
    per_year = d.groupby(d["year"].astype(int)).agg(
        items=("evidence_id", "count"),
        sources=("source_citation_id", "nunique"),
    )
    fig, ax1 = plt.subplots(figsize=(7, 4))
    ax1.plot(per_year.index, per_year["items"], color="#4c72b0", label="Evidence items", linewidth=2)
    ax1.set_xlabel("Publication year")
    ax1.set_ylabel("Evidence items", color="#4c72b0")
    ax1.tick_params(axis="y", labelcolor="#4c72b0")
    ax2 = ax1.twinx()
    ax2.bar(per_year.index, per_year["sources"], color="#dd8452", alpha=0.4, label="Unique sources")
    ax2.set_ylabel("Unique sources", color="#dd8452")
    ax2.tick_params(axis="y", labelcolor="#dd8452")
    ax1.set_title("S1B  Evidence production by publication year")
    fig.tight_layout()
    fig.savefig(out, dpi=300)
    plt.close(fig)
    logger.info("wrote %s", out)


def panel_c(df: pd.DataFrame, out: Path) -> None:
    """Evidence type × evidence level heatmap (% within evidence type)."""
    ct = pd.crosstab(df["evidence_type"], df["evidence_level"], normalize="index") * 100
    fig, ax = plt.subplots(figsize=(6, 4))
    if sns is not None:
        sns.heatmap(ct, annot=True, fmt=".1f", cmap="viridis", ax=ax, cbar_kws={"label": "% within evidence type"})
    else:
        im = ax.imshow(ct.values, aspect="auto", cmap="viridis")
        ax.set_xticks(range(len(ct.columns))); ax.set_xticklabels(ct.columns)
        ax.set_yticks(range(len(ct.index))); ax.set_yticklabels(ct.index)
        fig.colorbar(im, ax=ax, label="% within evidence type")
    ax.set_title("S1C  Evidence level distribution by evidence type")
    ax.set_xlabel("Evidence level")
    ax.set_ylabel("Evidence type")
    fig.tight_layout()
    fig.savefig(out, dpi=300)
    plt.close(fig)
    logger.info("wrote %s", out)


def panel_d(df: pd.DataFrame, out: Path) -> None:
    """Trust (evidence rating) distribution across evidence levels."""
    d = df[["evidence_level", "evidence_rating"]].dropna().copy()
    d["evidence_rating"] = pd.to_numeric(d["evidence_rating"], errors="coerce")
    d = d.dropna()
    fig, ax = plt.subplots(figsize=(6, 4))
    if sns is not None:
        sns.violinplot(data=d, x="evidence_level", y="evidence_rating", order=list("ABCDE"), ax=ax, inner="quartile")
    else:
        levels = list("ABCDE")
        ax.violinplot([d.loc[d.evidence_level == lv, "evidence_rating"].values for lv in levels])
        ax.set_xticks(range(1, 6)); ax.set_xticklabels(levels)
    ax.set_title("S1D  Evidence quality (trust rating) across evidence levels")
    ax.set_xlabel("Evidence level")
    ax.set_ylabel("Trust rating (1–5 stars)")
    fig.tight_layout()
    fig.savefig(out, dpi=300)
    plt.close(fig)
    logger.info("wrote %s", out)


def panel_e(df: pd.DataFrame, out: Path) -> None:
    """Clinical significance profile by evidence type."""
    ct = pd.crosstab(df["evidence_type"], df["evidence_significance"], normalize="index") * 100
    top = ct.sum().sort_values(ascending=False).head(12).index
    ct = ct[top]
    fig, ax = plt.subplots(figsize=(10, 5))
    if sns is not None:
        sns.heatmap(ct, cmap="mako", annot=False, ax=ax, cbar_kws={"label": "% within evidence type"})
    else:
        im = ax.imshow(ct.values, aspect="auto", cmap="mako")
        ax.set_xticks(range(len(ct.columns))); ax.set_xticklabels(ct.columns, rotation=45, ha="right")
        ax.set_yticks(range(len(ct.index))); ax.set_yticklabels(ct.index)
        fig.colorbar(im, ax=ax, label="% within evidence type")
    ax.set_title("S1E  Clinical significance profile by evidence type")
    fig.tight_layout()
    fig.savefig(out, dpi=300)
    plt.close(fig)
    logger.info("wrote %s", out)


def panel_f(df: pd.DataFrame, out: Path) -> None:
    """Variant origin × evidence type."""
    ct = pd.crosstab(df["variant_origin"].fillna("UNKNOWN"), df["evidence_type"])
    fig, ax = plt.subplots(figsize=(7, 4))
    if sns is not None:
        sns.heatmap(ct, annot=True, fmt="d", cmap="Greens", ax=ax, cbar_kws={"label": "Count"})
    else:
        im = ax.imshow(ct.values, aspect="auto", cmap="Greens")
        ax.set_xticks(range(len(ct.columns))); ax.set_xticklabels(ct.columns, rotation=45, ha="right")
        ax.set_yticks(range(len(ct.index))); ax.set_yticklabels(ct.index)
        fig.colorbar(im, ax=ax, label="Count")
    ax.set_title("S1F  Variant origin × evidence type")
    fig.tight_layout()
    fig.savefig(out, dpi=300)
    plt.close(fig)
    logger.info("wrote %s", out)


def panel_g(df: pd.DataFrame, out: Path) -> None:
    """Top diseases by evidence volume, stacked by evidence type."""
    top_diseases = df["disease_display_name"].value_counts().head(15).index
    d = df[df["disease_display_name"].isin(top_diseases)]
    ct = pd.crosstab(d["disease_display_name"], d["evidence_type"]).loc[top_diseases]
    fig, ax = plt.subplots(figsize=(8, 6))
    ct.plot(kind="barh", stacked=True, ax=ax, colormap="tab10")
    ax.invert_yaxis()
    ax.set_xlabel("Number of evidence items")
    ax.set_title("S1G  Top diseases by evidence volume (stacked by evidence type)")
    fig.tight_layout()
    fig.savefig(out, dpi=300)
    plt.close(fig)
    logger.info("wrote %s", out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--outdir", type=Path, default=Path("data/figures"))
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )
    args.outdir.mkdir(parents=True, exist_ok=True)

    df = _load(args.input_csv)
    panel_a(df, args.outdir / "SuppFigS1A_source_longtail.png")
    panel_b(df, args.outdir / "SuppFigS1B_temporal.png")
    panel_c(df, args.outdir / "SuppFigS1C_level_by_type.png")
    panel_d(df, args.outdir / "SuppFigS1D_trust_by_level.png")
    panel_e(df, args.outdir / "SuppFigS1E_significance_by_type.png")
    panel_f(df, args.outdir / "SuppFigS1F_variant_origin.png")
    panel_g(df, args.outdir / "SuppFigS1G_top_diseases.png")
    logger.info("done — %d panels written to %s", 7, args.outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
