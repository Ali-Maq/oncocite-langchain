"""
Checkpointing Factory
=====================

Provides factory functions for creating LangGraph checkpointers.

Checkpointers enable:
- Resumable workflows (stop and continue later)
- State persistence across restarts
- Thread-based state isolation (each paper_id gets its own thread)

Supported backends:
- memory: In-memory storage (development, testing)
- sqlite: SQLite database (production, persistence)
"""

from typing import Optional, Union
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.base import BaseCheckpointSaver

from config.settings import (
    LANGGRAPH_CHECKPOINT_BACKEND,
    LANGGRAPH_CHECKPOINT_PATH,
    VERBOSE,
)


# Global checkpointer instance (singleton pattern)
_checkpointer: Optional[BaseCheckpointSaver] = None


def get_checkpointer(
    backend: Optional[str] = None,
    reset: bool = False,
) -> BaseCheckpointSaver:
    """
    Get or create a LangGraph checkpointer.

    Uses singleton pattern - returns same instance on subsequent calls
    unless reset=True is specified.

    Args:
        backend: Override backend type ("memory" or "sqlite")
                 Default: from LANGGRAPH_CHECKPOINT_BACKEND setting
        reset: If True, create a new checkpointer even if one exists

    Returns:
        BaseCheckpointSaver instance (MemorySaver or SqliteSaver)

    Example:
        >>> checkpointer = get_checkpointer()
        >>> graph = builder.compile(checkpointer=checkpointer)

        >>> # Use with thread_id = paper_id
        >>> config = {"configurable": {"thread_id": paper_id}}
        >>> result = graph.invoke(state, config)

        >>> # Resume later with same thread_id
        >>> state = graph.get_state(config)
    """
    global _checkpointer

    if _checkpointer is not None and not reset:
        return _checkpointer

    backend = backend or LANGGRAPH_CHECKPOINT_BACKEND

    if backend == "memory":
        _checkpointer = _create_memory_checkpointer()
    elif backend == "sqlite":
        try:
            _checkpointer = _create_sqlite_checkpointer()
        except ImportError as e:
            # Fallback to memory if sqlite extras are not installed
            print("[Checkpointer] SQLite extras not available; falling back to memory.\n"
                  "Install with: pip install 'langgraph[sqlite]' to enable persistence.")
            _checkpointer = _create_memory_checkpointer()
    else:
        raise ValueError(f"Unknown checkpoint backend: {backend}. Use 'memory' or 'sqlite'.")

    if VERBOSE:
        print(f"[Checkpointer] Created {backend} checkpointer")

    return _checkpointer


def _create_memory_checkpointer() -> MemorySaver:
    """
    Create an in-memory checkpointer.

    Good for:
    - Development and testing
    - Short-lived processes
    - When persistence isn't needed

    Note: State is lost when process exits.
    """
    return MemorySaver()


def _create_sqlite_checkpointer() -> BaseCheckpointSaver:
    """
    Create a SQLite-based checkpointer.

    Good for:
    - Production use
    - Long-running processes
    - When persistence is needed

    The checkpoint database is stored at LANGGRAPH_CHECKPOINT_PATH.
    """
    # Prefer async saver to support ainvoke across the pipeline
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        import asyncio
        import aiosqlite
        # Ensure parent directory exists
        LANGGRAPH_CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Create connection in a private event loop (since we are in sync context)
        loop = asyncio.new_event_loop()
        try:
            conn = loop.run_until_complete(aiosqlite.connect(str(LANGGRAPH_CHECKPOINT_PATH)))
        finally:
            loop.close()
        return AsyncSqliteSaver(conn)
    except Exception:
        # Fallback to sync saver if async not available
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            import sqlite3
            LANGGRAPH_CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(LANGGRAPH_CHECKPOINT_PATH), check_same_thread=False)
            return SqliteSaver(conn)
        except Exception as e:
            raise ImportError(
                "SqliteSaver/AsyncSqliteSaver requires additional dependencies. "
                "Install with: pip install langgraph-checkpoint-sqlite aiosqlite"
            )


def clear_checkpoints(thread_id: Optional[str] = None) -> None:
    """
    Clear checkpoint data.

    Args:
        thread_id: If specified, only clear checkpoints for this thread.
                   If None, clear all checkpoints.

    Note: This only works for MemorySaver. SqliteSaver requires
          direct database manipulation.
    """
    global _checkpointer

    if _checkpointer is None:
        return

    if isinstance(_checkpointer, MemorySaver):
        if thread_id:
            # MemorySaver stores data in .storage dict keyed by thread_id
            if hasattr(_checkpointer, 'storage'):
                _checkpointer.storage.pop(thread_id, None)
        else:
            # Clear all
            if hasattr(_checkpointer, 'storage'):
                _checkpointer.storage.clear()

        if VERBOSE:
            scope = f"thread {thread_id}" if thread_id else "all threads"
            print(f"[Checkpointer] Cleared checkpoints for {scope}")


def get_thread_config(paper_id: str) -> dict:
    """
    Create a config dict for LangGraph with the paper_id as thread_id.

    This is the standard way to pass thread_id to LangGraph operations.

    Args:
        paper_id: The paper identifier (becomes thread_id)

    Returns:
        Config dict: {"configurable": {"thread_id": paper_id}}

    Example:
        >>> config = get_thread_config("pmid_12345678")
        >>> result = graph.invoke(state, config)
        >>> state = graph.get_state(config)
    """
    return {"configurable": {"thread_id": paper_id}}


def test_checkpointing() -> dict:
    """
    Test checkpointing functionality.

    Returns:
        Dict with test results
    """
    from langgraph.graph import StateGraph, START, END
    from typing import TypedDict

    class TestState(TypedDict):
        value: int

    def increment(state: TestState) -> TestState:
        return {"value": state["value"] + 1}

    # Build simple graph
    builder = StateGraph(TestState)
    builder.add_node("increment", increment)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)

    # Compile with checkpointer
    checkpointer = get_checkpointer(reset=True)
    graph = builder.compile(checkpointer=checkpointer)

    # Run with thread_id
    config = get_thread_config("test-thread")
    result = graph.invoke({"value": 0}, config)

    # Get state from checkpoint
    state = graph.get_state(config)

    return {
        "status": "ok",
        "backend": LANGGRAPH_CHECKPOINT_BACKEND,
        "initial_value": 0,
        "final_value": result["value"],
        "checkpoint_exists": state is not None,
        "checkpoint_value": state.values.get("value") if state else None,
    }


if __name__ == "__main__":
    # Quick test when run directly
    print("Testing checkpointing...")
    result = test_checkpointing()
    print(f"Status: {result['status']}")
    print(f"Backend: {result['backend']}")
    print(f"Initial: {result['initial_value']} → Final: {result['final_value']}")
    print(f"Checkpoint exists: {result['checkpoint_exists']}")
    print(f"Checkpoint value: {result['checkpoint_value']}")
