"""
Logging Callbacks for LangGraph Pipeline.

Uses LangChain's built-in BaseCallbackHandler for observability.
This replaces Claude Agent SDK hooks with the standard LangChain pattern.
"""

import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.agents import AgentAction, AgentFinish

# Configure logger
logger = logging.getLogger("civic.callbacks")

# Session tracking
_current_session_id: Optional[str] = None
_tool_usage_log: List[Dict[str, Any]] = []


def start_new_log_session(paper_id: str = "") -> str:
    """Start a new logging session."""
    global _current_session_id, _tool_usage_log
    _current_session_id = f"{paper_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    _tool_usage_log = []
    logger.info(f"Started new log session: {_current_session_id}")
    return _current_session_id


def clear_tool_usage_log() -> None:
    """Clear the tool usage log."""
    global _tool_usage_log
    _tool_usage_log = []


def get_tool_usage_log() -> List[Dict[str, Any]]:
    """Get the current tool usage log."""
    return _tool_usage_log.copy()


class CivicLoggingHandler(BaseCallbackHandler):
    """
    LangChain callback handler for CIViC extraction pipeline logging.

    Uses LangChain's built-in callback interface:
    - on_tool_start: Called when a tool starts
    - on_tool_end: Called when a tool completes
    - on_chain_start: Called when a chain/node starts
    - on_chain_end: Called when a chain/node completes
    - on_llm_start: Called when LLM invocation starts
    - on_llm_end: Called when LLM invocation completes
    """

    def __init__(
        self,
        log_level: int = logging.INFO,
        log_to_file: bool = False,
        log_dir: Optional[Path] = None,
    ):
        """
        Initialize the logging handler.

        Args:
            log_level: Logging level (default INFO)
            log_to_file: Whether to also log to file
            log_dir: Directory for log files
        """
        super().__init__()
        self.log_level = log_level
        self.log_to_file = log_to_file
        self.log_dir = log_dir or Path("logs")
        self._chain_stack: List[str] = []

    @property
    def always_verbose(self) -> bool:
        """Always return True to receive all callbacks."""
        return True

    # =========================================================================
    # Tool callbacks
    # =========================================================================

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        inputs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Called when a tool starts running."""
        # Handle None serialized (can happen in LangGraph)
        tool_name = serialized.get("name", "unknown_tool") if serialized else "unknown_tool"

        # Log the tool start
        logger.log(
            self.log_level,
            f"[TOOL START] {tool_name}",
        )

        # Record in tool usage log
        _tool_usage_log.append({
            "timestamp": datetime.now().isoformat(),
            "event": "tool_start",
            "tool_name": tool_name,
            "run_id": str(run_id),
            "input_preview": input_str[:200] if input_str else "",
        })

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when a tool finishes running."""
        output_preview = str(output)[:200] if output else ""

        logger.log(
            self.log_level,
            f"[TOOL END] run_id={run_id}",
        )

        _tool_usage_log.append({
            "timestamp": datetime.now().isoformat(),
            "event": "tool_end",
            "run_id": str(run_id),
            "output_preview": output_preview,
        })

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when a tool errors."""
        logger.error(f"[TOOL ERROR] run_id={run_id}: {error}")

        _tool_usage_log.append({
            "timestamp": datetime.now().isoformat(),
            "event": "tool_error",
            "run_id": str(run_id),
            "error": str(error),
        })

    # =========================================================================
    # Chain/Node callbacks
    # =========================================================================

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Called when a chain/node starts."""
        # Handle None serialized (can happen in LangGraph)
        if serialized is None:
            chain_name = "unknown"
        else:
            id_value = serialized.get("id", ["unknown"])
            id_name = id_value[-1] if isinstance(id_value, list) and id_value else "unknown"
            chain_name = serialized.get("name", id_name)
        self._chain_stack.append(chain_name)

        logger.log(
            self.log_level,
            f"[CHAIN START] {chain_name} (depth={len(self._chain_stack)})",
        )

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when a chain/node finishes."""
        chain_name = self._chain_stack.pop() if self._chain_stack else "unknown"

        logger.log(
            self.log_level,
            f"[CHAIN END] {chain_name}",
        )

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when a chain/node errors."""
        chain_name = self._chain_stack.pop() if self._chain_stack else "unknown"
        logger.error(f"[CHAIN ERROR] {chain_name}: {error}")

    # =========================================================================
    # LLM callbacks
    # =========================================================================

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM starts."""
        # Handle None serialized (can happen in LangGraph)
        if serialized is None:
            model = "unknown"
        else:
            model = serialized.get("kwargs", {}).get("model", "unknown")
        logger.debug(f"[LLM START] model={model}, prompts={len(prompts)}")

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM finishes."""
        generations = len(response.generations) if response.generations else 0
        logger.debug(f"[LLM END] generations={generations}")

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM errors."""
        logger.error(f"[LLM ERROR] {error}")


def get_logging_callbacks(
    log_level: int = logging.INFO,
    log_to_file: bool = False,
) -> List[BaseCallbackHandler]:
    """
    Get the list of callback handlers for the pipeline.

    Usage:
        callbacks = get_logging_callbacks()
        graph.invoke(state, config={"callbacks": callbacks})

    Args:
        log_level: Logging level
        log_to_file: Whether to log to file

    Returns:
        List of callback handlers
    """
    return [CivicLoggingHandler(log_level=log_level, log_to_file=log_to_file)]
