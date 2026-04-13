"""
Tool Context Management
=======================

Provides state access for tools in the LangGraph pipeline.

In LangGraph, tools can access state through:
1. Tool arguments (explicit state passing)
2. RunnableConfig (via InjectedState)
3. Global context (thread-safe singleton)

This module provides a simple global context approach that mirrors
the original Claude Agent SDK pattern while being LangGraph-compatible.
"""

from typing import Optional, Any
from threading import local
from dataclasses import dataclass, field

# Thread-local storage for context
_thread_local = local()


@dataclass
class ToolContext:
    """
    Context object providing state access to tools.

    This mirrors the original CIViCContext but is simplified for tools.
    The full state is managed by LangGraph; this provides a view for tools.
    """
    # Paper info
    paper_id: str = ""
    paper_folder: str = ""
    pdf_path: str = ""
    num_pages: int = 0
    author: str = ""
    year: str = ""
    paper_type: str = ""
    page_images: list[str] = field(default_factory=list)

    # Reader output
    paper_content: dict[str, Any] = field(default_factory=dict)
    paper_content_text: str = ""

    # Extraction state
    extraction_plan: dict[str, Any] = field(default_factory=dict)
    draft_extractions: list[dict[str, Any]] = field(default_factory=list)
    critique: dict[str, Any] = field(default_factory=dict)
    final_extractions: list[dict[str, Any]] = field(default_factory=list)

    # Iteration control
    iteration_count: int = 0
    max_iterations: int = 3

    # Status
    is_complete: bool = False
    final_status: str = ""


def get_context() -> ToolContext:
    """
    Get the current tool context.

    Returns:
        ToolContext for the current thread

    Raises:
        RuntimeError if no context is set
    """
    ctx = getattr(_thread_local, 'context', None)
    if ctx is None:
        raise RuntimeError(
            "No tool context set. Call set_context() before using tools, "
            "or ensure tools are called within a LangGraph node."
        )
    return ctx


def set_context(ctx: ToolContext) -> None:
    """
    Set the tool context for the current thread.

    Args:
        ctx: ToolContext to set
    """
    _thread_local.context = ctx


def clear_context() -> None:
    """Clear the tool context for the current thread."""
    _thread_local.context = None


def context_from_state(state: dict[str, Any]) -> ToolContext:
    """
    Create a ToolContext from a LangGraph state dict.

    This bridges between LangGraph's state and the tool context.

    Args:
        state: ExtractionGraphState dict

    Returns:
        ToolContext populated from state
    """
    paper_info = state.get("paper_info", {})

    return ToolContext(
        # Paper info
        paper_id=state.get("paper_id", ""),
        paper_folder=paper_info.get("paper_folder", ""),
        pdf_path=paper_info.get("pdf_path", ""),
        num_pages=paper_info.get("num_pages", 0),
        author=paper_info.get("author", ""),
        year=paper_info.get("year", ""),
        paper_type=paper_info.get("paper_type", ""),
        page_images=paper_info.get("page_images", []),

        # Reader output
        paper_content=state.get("paper_content", {}),
        paper_content_text=state.get("paper_content_text", ""),

        # Extraction state
        extraction_plan=state.get("extraction_plan", {}),
        draft_extractions=state.get("draft_extractions", []),
        critique=state.get("critique", {}),
        final_extractions=state.get("final_extractions", []),

        # Iteration control
        iteration_count=state.get("iteration_count", 0),
        max_iterations=state.get("max_iterations", 3),

        # Status
        is_complete=state.get("is_complete", False),
        final_status=state.get("final_status", ""),
    )


def state_from_context(ctx: ToolContext) -> dict[str, Any]:
    """
    Convert a ToolContext back to state dict updates.

    This extracts the mutable fields that tools may have changed.

    Args:
        ctx: ToolContext with potentially modified fields

    Returns:
        Dict of state updates
    """
    return {
        "paper_content": ctx.paper_content,
        "paper_content_text": ctx.paper_content_text,
        "extraction_plan": ctx.extraction_plan,
        "draft_extractions": ctx.draft_extractions,
        "critique": ctx.critique,
        "final_extractions": ctx.final_extractions,
        "iteration_count": ctx.iteration_count,
        "is_complete": ctx.is_complete,
        "final_status": ctx.final_status,
    }


class ContextManager:
    """
    Context manager for setting up tool context within a LangGraph node.

    Usage:
        def my_node(state: ExtractionGraphState) -> dict:
            with ContextManager(state) as ctx:
                # Tools can now access context via get_context()
                result = my_tool.invoke({"arg": "value"})

            # Get state updates from context
            return state_from_context(ctx)
    """

    def __init__(self, state: dict[str, Any]):
        self.state = state
        self.ctx: Optional[ToolContext] = None

    def __enter__(self) -> ToolContext:
        self.ctx = context_from_state(self.state)
        set_context(self.ctx)
        return self.ctx

    def __exit__(self, exc_type, exc_val, exc_tb):
        clear_context()
        return False
