"""
Paper Reading Tools
===================

Tools for reading paper pages and metadata.
Migrated from Claude Agent SDK to LangChain format.
"""

import base64
import json
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool

from .context import get_context


def render_pdf_page_to_image(pdf_path: str, page_num: int, dpi: int = 150) -> bytes:
    """
    Render a PDF page to a JPEG image.

    Args:
        pdf_path: Path to PDF file
        page_num: 1-indexed page number
        dpi: Resolution for rendering (default 150 for good quality/size balance)

    Returns:
        JPEG image bytes
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        if page_num < 1 or page_num > len(doc):
            doc.close()
            raise ValueError(f"Page {page_num} out of range (1-{len(doc)})")

        page = doc[page_num - 1]  # 0-indexed in PyMuPDF

        # Render at specified DPI
        zoom = dpi / 72  # 72 is default PDF DPI
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)

        # Convert to JPEG
        img_bytes = pix.tobytes("jpeg")

        doc.close()
        return img_bytes

    except ImportError:
        raise ImportError(
            "PyMuPDF (fitz) is required for PDF reading. "
            "Install with: pip install PyMuPDF"
        )


@tool
def read_paper_page(page_num: int, include_image: bool = True) -> str:
    """
    Read a specific page from the current paper.

    Returns page image data as base64 for visual analysis.
    Supports PDF files (renders page to image) and pre-rendered page images.

    Args:
        page_num: Page number to read (1-indexed)
        include_image: Whether to include the page image (default True)

    Returns:
        JSON string with page info and optional base64 image
    """
    ctx = get_context()

    if not ctx.paper_id:
        return json.dumps({"error": "No paper loaded"})

    if page_num < 1 or page_num > ctx.num_pages:
        return json.dumps({
            "error": f"Invalid page {page_num}. Paper has {ctx.num_pages} pages."
        })

    result = {
        "page_num": page_num,
        "total_pages": ctx.num_pages,
        "paper_id": ctx.paper_id,
    }

    # Get image if requested
    if include_image:
        image_bytes = None
        image_source = None

        # Try PDF first (preferred)
        if ctx.pdf_path:
            pdf_path = Path(ctx.pdf_path)
            if pdf_path.exists():
                try:
                    image_bytes = render_pdf_page_to_image(str(pdf_path), page_num)
                    image_source = "pdf"
                except Exception as e:
                    result["warning"] = f"Could not render PDF page: {e}"

        # Fallback to pre-rendered images
        if image_bytes is None and ctx.page_images:
            if page_num <= len(ctx.page_images):
                page_image_path = Path(ctx.page_images[page_num - 1])
                if page_image_path.exists():
                    with open(page_image_path, "rb") as f:
                        image_bytes = f.read()
                    image_source = "pre-rendered"

        # Add image to result
        if image_bytes:
            result["image"] = {
                "data": base64.b64encode(image_bytes).decode("utf-8"),
                "media_type": "image/jpeg",
                "source": image_source,
            }
        else:
            result["warning"] = f"Could not load image for page {page_num}"

    return json.dumps(result)


@tool
def get_paper_info() -> str:
    """
    Get metadata about the current paper being processed.

    Returns information including paper ID, author, year, page count,
    paper type, expected item count, and current iteration status.

    Returns:
        JSON string with paper metadata
    """
    ctx = get_context()

    if not ctx.paper_id:
        return json.dumps({"error": "No paper loaded"})

    info = {
        "paper_id": ctx.paper_id,
        "author": ctx.author,
        "year": ctx.year,
        "num_pages": ctx.num_pages,
        "paper_type": ctx.paper_type or "Not yet determined",
        "current_iteration": ctx.iteration_count,
        "max_iterations": ctx.max_iterations,
        "source": "PDF" if ctx.pdf_path else "Images",
        "is_complete": ctx.is_complete,
    }

    return json.dumps(info, indent=2)
