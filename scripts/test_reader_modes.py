#!/usr/bin/env python
"""
Ad-hoc Reader mode tester (moderate, max_dpi, tiled) without full pipeline.

Usage:
    uv run python scripts/test_reader_modes.py --pdf /path/to/paper.pdf \
        --paper-id PMID_XXXXX \
        --modes moderate,max_dpi,tiled \
        --dpi 300 --tile-rows 2 --tile-cols 3 --tile-overlap 0.08

Outputs:
    outputs/test_reader_modes/{paper_id}/{mode}/{timestamp}/
      - page_XXX.json (per-page extractions)
      - aggregate.json (save_paper_content structured dict)
      - content.txt (paper_content_text)
"""

import argparse
import base64
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import fitz  # PyMuPDF

from graphs.reader_graph import build_reader_graph
from graphs.state import create_initial_state
from tools.tool_registry import get_reader_tools

logger = logging.getLogger("test_reader_modes")


def _img_content_from_pixmap(pix: "fitz.Pixmap", quality: int = 90) -> Dict[str, Any]:
    data = base64.b64encode(pix.tobytes("jpeg", jpg_quality=quality)).decode("utf-8")
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/jpeg;base64,{data}",
            "detail": "high",
        },
    }


def render_moderate(pdf: Path) -> List[Any]:
    images: List[Any] = []
    doc = fitz.open(str(pdf))
    for i in range(len(doc)):
        page = doc[i]
        base_scale = 1.5
        rect = page.rect
        est_w = rect.width * base_scale
        est_h = rect.height * base_scale
        est_pixels = est_w * est_h
        # Clamp ~262k-1.31M pixels
        min_px = 256 * 32 * 32
        max_px = 1280 * 32 * 32
        scale = base_scale
        if est_pixels > max_px:
            scale = (max_px / est_pixels) ** 0.5 * base_scale
        elif est_pixels < min_px:
            desired = (min_px / est_pixels) ** 0.5 * base_scale
            scale = min(base_scale, desired)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        images.append(_img_content_from_pixmap(pix, quality=90))
    doc.close()
    return images


def render_max_dpi(pdf: Path, dpi: int) -> List[Any]:
    images: List[Any] = []
    doc = fitz.open(str(pdf))
    scale = dpi / 72.0
    mat = fitz.Matrix(scale, scale)
    for i in range(len(doc)):
        page = doc[i]
        pix = page.get_pixmap(matrix=mat)
        images.append(_img_content_from_pixmap(pix, quality=95))
    doc.close()
    return images


def render_tiled(pdf: Path, rows: int, cols: int, overlap: float, base_dpi: int) -> List[Any]:
    """Return list where each element is either an image or a list of images for that page."""
    all_pages: List[Any] = []
    doc = fitz.open(str(pdf))
    full_scale = 1.5
    full_mat = fitz.Matrix(full_scale, full_scale)
    tile_scale = base_dpi / 72.0
    for i in range(len(doc)):
        page = doc[i]
        # Full page context at moderate scale
        full_pix = page.get_pixmap(matrix=full_mat)
        images = [_img_content_from_pixmap(full_pix, quality=90)]

        # Tiles
        rect = page.rect
        w = rect.width
        h = rect.height
        dx = w / cols
        dy = h / rows
        # Overlap in absolute units (points)
        ox = dx * overlap
        oy = dy * overlap
        for r in range(rows):
            for c in range(cols):
                x0 = max(0, rect.x0 + c * dx - ox if c > 0 else rect.x0)
                y0 = max(0, rect.y0 + r * dy - oy if r > 0 else rect.y0)
                x1 = min(rect.x1, rect.x0 + (c + 1) * dx + (ox if c < cols - 1 else 0))
                y1 = min(rect.y1, rect.y0 + (r + 1) * dy + (oy if r < rows - 1 else 0))
                clip = fitz.Rect(x0, y0, x1, y1)
                pix = page.get_pixmap(matrix=fitz.Matrix(tile_scale, tile_scale), clip=clip)
                images.append(_img_content_from_pixmap(pix, quality=95))

        all_pages.append(images)
    doc.close()
    return all_pages


def run_reader_on_pages(page_images: List[Any], paper_id: str) -> Dict[str, Any]:
    import asyncio
    graph = build_reader_graph()
    state = create_initial_state(paper_id)
    state["page_images"] = page_images
    state["current_phase"] = "reader"
    return asyncio.run(graph.ainvoke(state))


def save_mode_outputs(outdir: Path, result: Dict[str, Any]) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    # Per-page JSONs
    pages_dir = outdir / "pages"
    pages = result.get("page_extractions", []) or []
    if pages:
        pages_dir.mkdir(parents=True, exist_ok=True)
        for p in pages:
            pn = p.get("page_number", "unknown")
            (pages_dir / f"page_{int(pn):03d}.json").write_text(json.dumps(p, indent=2))
    # Aggregate
    (outdir / "aggregate.json").write_text(json.dumps(result.get("paper_content", {}), indent=2))
    # Content text
    (outdir / "content.txt").write_text(result.get("paper_content_text", ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--paper-id", required=True)
    ap.add_argument("--modes", default="moderate,max_dpi,tiled")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--tile-rows", type=int, default=2)
    ap.add_argument("--tile-cols", type=int, default=3)
    ap.add_argument("--tile-overlap", type=float, default=0.08)
    ap.add_argument("--max-pages", type=int, default=0, help="Limit number of pages for quick tests (0=all)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_out = Path("outputs/test_reader_modes") / args.paper_id / timestamp

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    for mode in modes:
        logger.info(f"Running mode: {mode}")
        if mode == "moderate":
            pages = render_moderate(args.pdf)
        elif mode == "max_dpi":
            pages = render_max_dpi(args.pdf, dpi=args.dpi)
        elif mode == "tiled":
            pages = render_tiled(args.pdf, rows=args.tile_rows, cols=args.tile_cols, overlap=args.tile_overlap, base_dpi=args.dpi)
        else:
            logger.warning(f"Unknown mode {mode}, skipping")
            continue

        if args.max_pages and args.max_pages > 0:
            pages = pages[: args.max_pages]
        result = run_reader_on_pages(pages, args.paper_id)
        save_mode_outputs(base_out / mode, result)
        logger.info(f"Saved outputs to {base_out / mode}")


if __name__ == "__main__":
    main()
