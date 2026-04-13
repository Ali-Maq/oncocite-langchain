"""
Reader Graph
============

LangGraph StateGraph for the Reader phase (Phase 1).
Converts PDF pages to images and extracts paper content using multimodal LLM.

CRITICAL INVARIANTS:
1. Reader MUST receive actual images, not text
2. Images are base64 JPEG at 1.5x scale (108 DPI)
3. All pages (up to 20) are sent to Reader
4. paper_content_text is the FULL text (~10-50KB, NEVER truncate)
"""

import base64
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.base import BaseCheckpointSaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from .state import ExtractionGraphState
from .prompts import READER_SYSTEM_PROMPT
from runtime.llm import get_reader_llm
from tools.tool_registry import get_reader_tools
from tools.context import set_context, get_context, ToolContext
from config.settings import (
    MAX_PAGES,
    CHUNK_SIZE,
    QWEN_IMAGE_MAX_PIXELS,
    QWEN_IMAGE_MIN_PIXELS,
    READER_RENDER_MODE,
    TILE_ROWS,
    TILE_COLS,
    TILE_OVERLAP,
    TILE_DPI,
    READER_CONCURRENCY,
    JSON_RETRY_ON_FAIL,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONTEXT TRIMMING (to prevent multimodal context bloat)
# =============================================================================

def _trim_multimodal_content(messages: List[Any]) -> List[Any]:
    """
    Remove image data from messages to reduce context size.

    After the initial extraction request, images are no longer needed.
    This function strips image_url content from HumanMessages to prevent
    context bloat during tool iteration loops.

    Args:
        messages: List of conversation messages

    Returns:
        Messages with image data stripped (text preserved)
    """
    trimmed = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = msg.content
            # If content is a list (multimodal), filter out images
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text_parts.append(part)
                        elif part.get("type") == "image_url":
                            # Replace with placeholder to maintain context
                            text_parts.append({
                                "type": "text",
                                "text": "[Image content already processed]"
                            })
                        else:
                            text_parts.append(part)
                    else:
                        text_parts.append(part)
                # Create new message with trimmed content
                trimmed.append(HumanMessage(content=text_parts))
            else:
                trimmed.append(msg)
        else:
            trimmed.append(msg)
    return trimmed


# =============================================================================
# XML TOOL CALL PARSING (for models that output tool calls in text format)
# =============================================================================

def _parse_xml_tool_calls(content: str) -> List[Dict[str, Any]]:
    """
    Parse XML-style tool calls from model output.

    Some models (GLM-4, Qwen3-VL via Fireworks) output tool calls in text format:
    <tool_call>tool_name(arg1="value1", arg2="value2")</tool_call>

    This function parses these and returns structured tool call dicts.

    Args:
        content: The LLM response content

    Returns:
        List of parsed tool calls with name, args, and generated id
    """
    if not content:
        return []

    tool_calls = []

    # Pattern 1: <tool_call>tool_name</tool_call> or <tool_call>tool_name(args)</tool_call>
    pattern1 = re.compile(r'<tool_call>\s*(\w+)(?:\((.*?)\))?\s*</tool_call>', re.DOTALL)
    for match in pattern1.finditer(content):
        tool_name = match.group(1)
        args_str = match.group(2) or ""

        # Parse arguments
        args = {}
        if args_str:
            # Try to parse as key=value pairs
            arg_pattern = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\{.*?\})|(\[.*?\])|([^,\)]+))')
            for arg_match in arg_pattern.finditer(args_str):
                key = arg_match.group(1)
                value = arg_match.group(2) or arg_match.group(3) or arg_match.group(4) or arg_match.group(5) or arg_match.group(6)
                if value:
                    value = value.strip()
                    if value.startswith('{') or value.startswith('['):
                        try:
                            value = json.loads(value)
                        except:
                            pass
                    args[key] = value

        tool_calls.append({
            "name": tool_name,
            "args": args,
            "id": f"call_{uuid.uuid4().hex[:8]}"
        })

    # Pattern 2: <tool_call>{"name": "...", "arguments": {...}}</tool_call>
    pattern2 = re.compile(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', re.DOTALL)
    for match in pattern2.finditer(content):
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and "name" in data:
                tool_calls.append({
                    "name": data["name"],
                    "args": data.get("arguments", data.get("args", {})),
                    "id": f"call_{uuid.uuid4().hex[:8]}"
                })
        except json.JSONDecodeError:
            pass

    # Pattern 3: Function call notation like save_paper_content(title="...", ...)
    # Look for calls to known tools
    known_tools = ["save_paper_content", "get_paper_info", "read_paper_page"]
    for tool_name in known_tools:
        pattern3 = re.compile(rf'{tool_name}\s*\(\s*(.*?)\s*\)', re.DOTALL)
        for match in pattern3.finditer(content):
            args_str = match.group(1) or ""
            args = {}

            if args_str:
                # Try to parse as key=value pairs
                arg_pattern = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\{.*?\})|(\[.*?\])|([^,]+))')
                for arg_match in arg_pattern.finditer(args_str):
                    key = arg_match.group(1)
                    value = arg_match.group(2) or arg_match.group(3) or arg_match.group(4) or arg_match.group(5) or arg_match.group(6)
                    if value:
                        value = value.strip()
                        if value.startswith('{') or value.startswith('['):
                            try:
                                value = json.loads(value)
                            except:
                                pass
                        args[key] = value

            # Only add if we haven't already found this tool call
            if not any(tc["name"] == tool_name for tc in tool_calls):
                tool_calls.append({
                    "name": tool_name,
                    "args": args,
                    "id": f"call_{uuid.uuid4().hex[:8]}"
                })

    return tool_calls


# =============================================================================
# JSON EXTRACTION HELPERS
# =============================================================================

def _strip_code_fences(text: str) -> str:
    """Remove common markdown fences from model output."""
    if not text:
        return text
    lines = text.strip().splitlines()
    # Remove ```json or ``` fences if present
    if lines and lines[0].strip().startswith("```"):
        # Drop first line
        lines = lines[1:]
        # Drop last fence if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort extract a JSON object from text content."""
    if not text:
        return None
    raw = _strip_code_fences(text)
    # Find outermost braces
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = raw[start:end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        # Try a second pass removing stray trailing commas
        try:
            fixed = snippet.replace(",}\n", "}\n").replace(",]", "]")
            return json.loads(fixed)
        except Exception:
            return None


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen = set()
    out = []
    for v in values:
        key = v.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(v.strip())
    return out


def _ensure_list_str(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    return [str(value)] if str(value).strip() else []


def _coerce_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        s = str(value).strip()
        return int(s) if s.isdigit() else None
    except Exception:
        return None


def _merge_page_into_aggregate(aggregate: Dict[str, Any], page: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a single page JSON into the overall paper_content aggregate."""
    page_num = page.get("page_number")

    # 1) Page metadata (first non-empty wins)
    meta = page.get("page_metadata") or {}
    if not aggregate.get("title") and meta.get("title"):
        aggregate["title"] = str(meta.get("title")).strip()
    if not aggregate.get("authors") and meta.get("authors"):
        aggregate["authors"] = _ensure_list_str(meta.get("authors"))
    if not aggregate.get("journal") and meta.get("journal"):
        aggregate["journal"] = str(meta.get("journal")).strip()
    if aggregate.get("year") in (None, "") and meta.get("year") is not None:
        year_int = _coerce_int(meta.get("year"))
        if year_int is not None:
            aggregate["year"] = year_int

    # 2) Sections: convert to expected schema
    for sec in page.get("sections", []) or []:
        heading = str(sec.get("heading", "Section")).strip() or "Section"
        text = str(sec.get("text", "")).strip()
        if not text:
            continue
        # Detect Abstract section
        if not aggregate.get("abstract") and heading.lower() == "abstract":
            aggregate["abstract"] = text
        aggregate["sections"].append({
            "name": heading,
            "page_numbers": [page_num] if page_num else [],
            "content": text,
        })

    # 3) Tables
    for tbl in page.get("tables", []) or []:
        table_obj = {
            "table_id": tbl.get("table_id", "Table"),
            "caption": tbl.get("caption", ""),
            "headers": tbl.get("headers") or [],
            "rows": tbl.get("rows") or [],
            "footnotes": tbl.get("footnotes") or "",
            "page_number": page_num,
        }
        # Attach verbatim snippets if provided
        if tbl.get("verbatim_snippets"):
            table_obj["verbatim_snippets"] = tbl.get("verbatim_snippets")
        aggregate["tables"].append(table_obj)

    # 4) Figures
    for fig in page.get("figures", []) or []:
        fig_obj = {
            "figure_id": fig.get("figure_id", "Figure"),
            "caption": fig.get("caption", ""),
            "description": fig.get("observations", ""),
            "page_number": page_num,
        }
        if fig.get("statistics"):
            fig_obj["statistics"] = fig.get("statistics")
        aggregate["figures"].append(fig_obj)

    # 5) Statistics (normalize into our flat list expected by _generate_paper_context_text)
    for stat in page.get("statistics", []) or []:
        value_str = str(stat.get("value", "")).strip()
        metric = str(stat.get("metric_type", "")).strip()
        unit = str(stat.get("unit", "")).strip()
        combined_value = f"{metric}: {value_str}{(' ' + unit) if unit else ''}" if metric else value_str
        aggregate["statistics"].append({
            "value": combined_value,
            "confidence_interval": "",
            "p_value": "",
            "sample_size": "",
            "context": stat.get("verbatim_text", ""),
            "page_number": page_num,
            "source_location": stat.get("location", ""),
        })

    # 6) Entities
    ents = page.get("entities") or {}
    def collect(name: str, dest_key: str):
        items = ents.get(name) or []
        for it in items:
            text = str(it.get("text", "")).strip()
            if text:
                aggregate[dest_key].append(text)

    collect("genes", "genes")
    collect("variants", "variants")
    collect("diseases", "diseases")
    collect("therapies", "therapies")

    # Trials (NCT IDs)
    for it in ents.get("trials", []) or []:
        nct = str(it.get("nct_id", "")).strip()
        if nct:
            aggregate["clinical_trials"].append({"nct_id": nct})

    # 7) Track uncertainty flag
    if page.get("needs_higher_resolution"):
        aggregate["_needs_higher_resolution_count"] = aggregate.get("_needs_higher_resolution_count", 0) + 1

    # 8) Uncertainties (optional)
    for u in page.get("uncertainties", []) or []:
        aggregate.setdefault("_uncertainties", []).append(str(u))

    return aggregate
# PDF TO IMAGE CONVERSION
# =============================================================================

def _img_content_from_pixmap(pix, quality: int = 90) -> Dict[str, Any]:
    data = base64.b64encode(pix.tobytes("jpeg", jpg_quality=quality)).decode("utf-8")
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/jpeg;base64,{data}",
            "detail": "high",
        },
    }


def load_images_from_pdf(pdf_path: str, max_pages: int = None) -> List[Any]:
    """
    Render PDF pages to base64 JPEG images.

    Args:
        pdf_path: Path to the PDF file
        max_pages: Maximum number of pages to process (None = all pages)

    Returns:
        List of image content dicts for LangChain message format
    """
    import fitz  # PyMuPDF

    # Use MAX_PAGES from settings if not specified
    if max_pages is None:
        max_pages = MAX_PAGES

    images_content: List[Any] = []
    try:
        doc = fitz.open(pdf_path)
        # If max_pages is None, process ALL pages
        num_pages = len(doc) if max_pages is None else min(len(doc), max_pages)

        logger.info(f"Rendering {num_pages} pages from PDF for Reader context...")

        for i in range(num_pages):
            page = doc[i]
            rect = page.rect

            def render_moderate() -> Dict[str, Any]:
                base_scale = 1.5
                est_w = rect.width * base_scale
                est_h = rect.height * base_scale
                est_pixels = est_w * est_h
                scale = base_scale
                if est_pixels > QWEN_IMAGE_MAX_PIXELS and est_pixels > 0:
                    scale = (QWEN_IMAGE_MAX_PIXELS / est_pixels) ** 0.5 * base_scale
                elif est_pixels < QWEN_IMAGE_MIN_PIXELS and est_pixels > 0:
                    desired = (QWEN_IMAGE_MIN_PIXELS / est_pixels) ** 0.5 * base_scale
                    scale = min(base_scale, desired)
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
                return _img_content_from_pixmap(pix, quality=90)

            def render_max_dpi(dpi: int) -> Dict[str, Any]:
                scale = dpi / 72.0
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
                return _img_content_from_pixmap(pix, quality=95)

            if READER_RENDER_MODE == "tiled":
                # Full page at moderate scale
                page_images: List[Dict[str, Any]] = [render_moderate()]
                # Tiles at high DPI
                rows, cols = TILE_ROWS, TILE_COLS
                dx = rect.width / cols
                dy = rect.height / rows
                ox = dx * TILE_OVERLAP
                oy = dy * TILE_OVERLAP
                tscale = TILE_DPI / 72.0
                for r in range(rows):
                    for c in range(cols):
                        x0 = max(rect.x0, rect.x0 + c * dx - (ox if c > 0 else 0))
                        y0 = max(rect.y0, rect.y0 + r * dy - (oy if r > 0 else 0))
                        x1 = min(rect.x1, rect.x0 + (c + 1) * dx + (ox if c < cols - 1 else 0))
                        y1 = min(rect.y1, rect.y0 + (r + 1) * dy + (oy if r < rows - 1 else 0))
                        clip = fitz.Rect(x0, y0, x1, y1)
                        pix = page.get_pixmap(matrix=fitz.Matrix(tscale, tscale), clip=clip)
                        page_images.append(_img_content_from_pixmap(pix, quality=95))
                images_content.append(page_images)
            elif READER_RENDER_MODE == "max_dpi":
                images_content.append(render_max_dpi(TILE_DPI))
            else:  # moderate
                images_content.append(render_moderate())
        doc.close()
        logger.info(f"Successfully rendered {len(images_content)} page images")

    except Exception as e:
        logger.error(f"Failed to render PDF images: {e}")
        raise

    return images_content


def load_images_from_paths(image_paths: List[str]) -> List[Dict[str, Any]]:
    """
    Load images from file paths and convert to base64.

    Args:
        image_paths: List of paths to image files

    Returns:
        List of image content dicts for LangChain message format
    """
    images_content = []

    for img_path in image_paths:
        try:
            with open(img_path, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")

            # Determine media type from extension
            ext = img_path.lower().split(".")[-1]
            media_type = "image/jpeg" if ext in ["jpg", "jpeg"] else f"image/{ext}"

            images_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{media_type};base64,{data}",
                    "detail": "high"
                }
            })
        except Exception as e:
            logger.error(f"Failed to load image {img_path}: {e}")

    return images_content


# =============================================================================
# READER NODE
# =============================================================================

async def reader_node(state: ExtractionGraphState) -> Dict[str, Any]:
    """
    Reader agent node that extracts paper content from images.

    This node implements PAGE CHUNKING protocol (matching original Claude SDK):
    1. Sends pages in chunks of 2 (CHUNK_SIZE)
    2. For non-last chunks: LLM acknowledges but does NOT extract yet
    3. For last chunk: LLM extracts ALL and calls save_paper_content
    4. This ensures LLM sees ALL pages before extracting
    """
    logger.info("=== READER NODE START ===")

    # Set up tool context
    ctx = ToolContext()
    ctx.paper_id = state.get("paper_id", "")
    set_context(ctx)

    # Get LLM and tools
    llm = get_reader_llm()
    tools = get_reader_tools()
    # For page JSON extraction, do NOT bind tools (JSON-only output)

    # Get page images from state
    page_images = state.get("page_images", [])
    if not page_images:
        logger.error("No page images in state")
        return {
            "errors": state.get("errors", []) + ["No page images provided to Reader"]
        }

    total_pages = len(page_images)
    logger.info(f"Reader processing {total_pages} page images - JSON per page, then aggregate")

    page_jsons: List[Dict[str, Any]] = []

    # Process each page individually
    async def extract_one(idx: int):
        page_image = page_images[idx]
        page_instr = (
            f"You are extracting ONLY page {idx + 1} of {total_pages}.\n"
            "Follow the system instructions and return VALID JSON only."
        )
        content: List[Dict[str, Any]] = [{"type": "text", "text": page_instr}]
        if isinstance(page_image, list):
            content.extend(page_image)
        else:
            content.append(page_image)

        messages = [SystemMessage(content=READER_SYSTEM_PROMPT), HumanMessage(content=content)]

        async def call_once(msgs):
            try:
                resp = await llm.ainvoke(msgs)
                obj = _extract_json_obj(resp.content or "")
                return obj, resp.content
            except Exception as e:
                return None, f"ERROR: {e}"

        logger.info(f"Extracting page {idx + 1}/{total_pages}")
        obj, raw = await call_once(messages)
        if not obj and JSON_RETRY_ON_FAIL:
            # Retry with explicit fix-JSON instruction
            fix_text = (
                "Your previous output was not valid JSON. "
                "Return VALID JSON only that strictly matches the schema. No prose."
            )
            messages_retry = [
                SystemMessage(content=READER_SYSTEM_PROMPT),
                HumanMessage(content=[{"type": "text", "text": fix_text}] + content[1:]),
            ]
            obj, raw = await call_once(messages_retry)

        if obj:
            obj.setdefault("page_number", idx + 1)
            logger.info(f"Page {idx + 1} JSON extracted")
        else:
            logger.warning(f"Page {idx + 1}: JSON parse failed. Response preview: {(raw or '')[:400]}")
        return obj

    import asyncio
    sem = asyncio.Semaphore(max(1, READER_CONCURRENCY))

    async def worker(i):
        async with sem:
            return await extract_one(i)

    async def run_all():
        tasks = [asyncio.create_task(worker(i)) for i in range(total_pages)]
        return await asyncio.gather(*tasks)

    # Execute with concurrency
    page_results = await run_all()
    for obj in page_results:
        if obj:
            page_jsons.append(obj)

    # Aggregate programmatically with light grounding (require verbatim text when present)
    logger.info(f"Aggregating {len(page_jsons)} page JSONs")
    aggregate: Dict[str, Any] = {
        "title": "",
        "authors": [],
        "journal": "",
        "year": None,
        "paper_type": "",
        "abstract": "",
        "sections": [],
        "tables": [],
        "figures": [],
        "statistics": [],
        "genes": [],
        "variants": [],
        "diseases": [],
        "therapies": [],
        "clinical_trials": [],
    }

    for page_obj in page_jsons:
        # Drop stats without verbatim_text (grounding requirement)
        stats = []
        for s in (page_obj.get("statistics") or []):
            if s and str(s.get("verbatim_text", "")).strip():
                stats.append(s)
        if stats:
            page_obj = dict(page_obj)
            page_obj["statistics"] = stats

        _merge_page_into_aggregate(aggregate, page_obj)

    # Deduplicate entity lists
    aggregate["genes"] = _dedupe_preserve_order(aggregate["genes"])  # type: ignore
    aggregate["variants"] = _dedupe_preserve_order(aggregate["variants"])  # type: ignore
    aggregate["diseases"] = _dedupe_preserve_order(aggregate["diseases"])  # type: ignore
    aggregate["therapies"] = _dedupe_preserve_order(aggregate["therapies"])  # type: ignore

    # Provide defaults for required save_paper_content args
    title = aggregate["title"] or state.get("paper_id", "Unknown Title")
    authors = aggregate["authors"] or []
    journal = aggregate["journal"] or "Unknown"
    year = aggregate["year"] if isinstance(aggregate["year"], int) else None
    paper_type = aggregate["paper_type"] or "UNKNOWN"
    abstract = aggregate["abstract"] or ""

    # Invoke save_paper_content directly (no LLM involvement)
    tool = next((t for t in tools if t.name == "save_paper_content"), None)
    if not tool:
        logger.error("save_paper_content tool not found")
        return {
            "errors": state.get("errors", []) + ["save_paper_content tool not available"],
            "current_phase": "reader_error",
        }

    payload = {
        "title": title,
        "authors": authors,
        "journal": journal,
        "year": year or 0,
        "paper_type": paper_type,
        "abstract": abstract,
        "sections": aggregate["sections"],
        "tables": aggregate["tables"],
        "figures": aggregate["figures"],
        "statistics": aggregate["statistics"],
        "genes": aggregate["genes"],
        "variants": aggregate["variants"],
        "diseases": aggregate["diseases"],
        "therapies": aggregate["therapies"],
        "clinical_trials": aggregate["clinical_trials"],
    }

    logger.info("Invoking save_paper_content with aggregated JSON")
    tool_result = tool.invoke(payload)
    messages = [
        SystemMessage(content="Reader aggregation complete; tool invoked programmatically."),
        ToolMessage(content=tool_result, tool_call_id="save_paper_content_direct"),
    ]

    # Get results from context
    ctx = get_context()

    logger.info(f"Reader extracted content: {bool(ctx.paper_content)}")
    logger.info(f"Paper content text length: {len(ctx.paper_content_text)}")

    return {
        "paper_content": ctx.paper_content,
        "paper_content_text": ctx.paper_content_text,
        "paper_type": ctx.paper_type,
        "author": ctx.author,
        "year": ctx.year,
        "current_phase": "reader_complete",
        "messages": messages,
        "page_extractions": page_jsons,
    }


# =============================================================================
# GRAPH CONSTRUCTION
# =============================================================================

def build_reader_graph(checkpointer: Optional[BaseCheckpointSaver] = None) -> StateGraph:
    """
    Build the Reader phase StateGraph.

    Graph structure:
        START -> reader_node -> END

    Args:
        checkpointer: Optional LangGraph checkpointer for persistence/resume.
                     Required for thread_id-based state management per LangGraph v0.2+.

    Returns:
        Compiled StateGraph for Reader phase
    """
    # Create graph with state schema
    graph = StateGraph(ExtractionGraphState)

    # Add reader node
    graph.add_node("reader", reader_node)

    # Add edges
    graph.add_edge(START, "reader")
    graph.add_edge("reader", END)

    # Compile with checkpointer for persistence (LangGraph v0.2+ pattern)
    # This enables: thread_id-based state management, resume capability, state history
    return graph.compile(checkpointer=checkpointer)


def run_reader_phase(
    pdf_path: Optional[str] = None,
    image_paths: Optional[List[str]] = None,
    paper_id: str = "unknown",
) -> ExtractionGraphState:
    """
    Convenience function to run the Reader phase.

    Args:
        pdf_path: Path to PDF file (preferred)
        image_paths: List of image file paths (alternative)
        paper_id: Identifier for the paper

    Returns:
        State with paper_content extracted
    """
    # Load images
    if pdf_path:
        page_images = load_images_from_pdf(pdf_path)
    elif image_paths:
        page_images = load_images_from_paths(image_paths)
    else:
        raise ValueError("Must provide either pdf_path or image_paths")

    # Build initial state
    initial_state: ExtractionGraphState = {
        "paper_id": paper_id,
        "thread_id": paper_id,
        "page_images": page_images,
        "current_phase": "reader",
        "iteration_count": 0,
        "max_iterations": 3,
        "is_complete": False,
        "errors": [],
        "messages": [],
    }

    # Build and run graph
    graph = build_reader_graph()
    result = graph.invoke(initial_state)

    return result
