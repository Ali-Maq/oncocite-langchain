"""
LangGraph graph definitions for CIViC extraction pipeline.

This package contains:
- state.py: LangGraph state TypedDict
- prompts.py: Agent prompts (copied from original client.py)
- reader_graph.py: Reader phase StateGraph
- extraction_graph.py: Orchestrator + subagents StateGraph
"""

from .state import ExtractionGraphState, create_initial_state
from .prompts import (
    READER_SYSTEM_PROMPT,
    ORCHESTRATOR_SYSTEM_PROMPT,
    PLANNER_PROMPT,
    EXTRACTOR_PROMPT,
    CRITIC_PROMPT,
    NORMALIZER_PROMPT,
    AGENT_DESCRIPTIONS,
)
from .reader_graph import (
    build_reader_graph,
    run_reader_phase,
    load_images_from_pdf,
    load_images_from_paths,
)
from .extraction_graph import (
    build_extraction_graph,
    run_extraction_phase,
    run_full_pipeline,
)

__all__ = [
    # State
    "ExtractionGraphState",
    "create_initial_state",
    # Prompts
    "READER_SYSTEM_PROMPT",
    "ORCHESTRATOR_SYSTEM_PROMPT",
    "PLANNER_PROMPT",
    "EXTRACTOR_PROMPT",
    "CRITIC_PROMPT",
    "NORMALIZER_PROMPT",
    "AGENT_DESCRIPTIONS",
    # Reader graph
    "build_reader_graph",
    "run_reader_phase",
    "load_images_from_pdf",
    "load_images_from_paths",
    # Extraction graph
    "build_extraction_graph",
    "run_extraction_phase",
    "run_full_pipeline",
]
