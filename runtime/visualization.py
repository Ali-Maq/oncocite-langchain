"""
Graph Visualization and State History Analytics
================================================

Provides utilities for:
- Generating Mermaid diagrams of LangGraph graphs
- Saving visualizations to files
- Accessing and analyzing state history
- Exporting analytics for debugging and audit

Usage:
    from runtime.visualization import (
        save_graph_visualization,
        get_state_history,
        get_execution_analytics,
    )

    # Save graph diagram
    save_graph_visualization(graph, "extraction_graph.md")

    # Get state history for a thread
    history = get_state_history(graph, thread_id="paper_123")

    # Get execution analytics
    analytics = get_execution_analytics(history)
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Iterator, Union
from dataclasses import dataclass, field

from langgraph.graph import StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger("civic.visualization")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _parse_timestamp(ts: Union[str, datetime, None]) -> Optional[datetime]:
    """
    Parse a timestamp that may be a string, datetime, or None.

    Args:
        ts: Timestamp as string (ISO format), datetime object, or None

    Returns:
        datetime object or None
    """
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            # Try ISO format first
            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except ValueError:
            try:
                # Try common formats
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                    try:
                        return datetime.strptime(ts, fmt)
                    except ValueError:
                        continue
            except Exception:
                pass
    logger.warning(f"Could not parse timestamp: {ts}")
    return None


# =============================================================================
# GRAPH VISUALIZATION
# =============================================================================

def get_mermaid_diagram(graph: StateGraph) -> str:
    """
    Generate a Mermaid diagram string from a LangGraph graph.

    Args:
        graph: Compiled LangGraph StateGraph

    Returns:
        Mermaid diagram string

    Example:
        >>> diagram = get_mermaid_diagram(extraction_graph)
        >>> print(diagram)
        graph TD
            __start__ --> orchestrator
            orchestrator --> planner
            ...
    """
    try:
        return graph.get_graph().draw_mermaid()
    except Exception as e:
        logger.error(f"Failed to generate Mermaid diagram: {e}")
        return f"# Error generating diagram: {e}"


def save_graph_visualization(
    graph: StateGraph,
    output_path: str | Path,
    include_header: bool = True,
    title: Optional[str] = None,
) -> Path:
    """
    Save a LangGraph graph visualization as a Mermaid markdown file.

    Args:
        graph: Compiled LangGraph StateGraph
        output_path: Path for output file (.md extension recommended)
        include_header: Whether to include markdown header and code fences
        title: Optional title for the diagram

    Returns:
        Path to saved file

    Example:
        >>> path = save_graph_visualization(
        ...     extraction_graph,
        ...     "outputs/extraction_graph.md",
        ...     title="CIViC Extraction Pipeline"
        ... )
        >>> print(f"Saved to: {path}")
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    mermaid = get_mermaid_diagram(graph)

    if include_header:
        title = title or "LangGraph Visualization"
        content = f"""# {title}

Generated: {datetime.now().isoformat()}

```mermaid
{mermaid}
```

## Notes

- Nodes represent processing stages (agents)
- Edges show state transitions
- Conditional edges may not show all branches
"""
    else:
        content = mermaid

    output_path.write_text(content)
    logger.info(f"Graph visualization saved to: {output_path}")

    return output_path


def save_all_graph_visualizations(
    output_dir: str | Path = "outputs/graphs",
) -> Dict[str, Path]:
    """
    Save visualizations for all pipeline graphs.

    Args:
        output_dir: Directory for output files

    Returns:
        Dict mapping graph names to file paths
    """
    from graphs.reader_graph import build_reader_graph
    from graphs.extraction_graph import build_extraction_graph

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved = {}

    # Reader graph
    try:
        reader = build_reader_graph()
        saved["reader"] = save_graph_visualization(
            reader,
            output_dir / "reader_graph.md",
            title="Reader Graph - PDF to Structured Content"
        )
    except Exception as e:
        logger.error(f"Failed to save reader graph: {e}")

    # Extraction graph
    try:
        extraction = build_extraction_graph()
        saved["extraction"] = save_graph_visualization(
            extraction,
            output_dir / "extraction_graph.md",
            title="Extraction Graph - Evidence Extraction Pipeline"
        )
    except Exception as e:
        logger.error(f"Failed to save extraction graph: {e}")

    return saved


# =============================================================================
# STATE HISTORY ACCESS
# =============================================================================

@dataclass
class StateSnapshot:
    """Snapshot of graph state at a point in time."""
    step: int
    node_name: str
    timestamp: Optional[datetime]
    state: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


def get_state_history(
    graph: StateGraph,
    thread_id: str,
    limit: Optional[int] = None,
) -> List[StateSnapshot]:
    """
    Get the state history for a specific thread/execution.

    Args:
        graph: Compiled LangGraph StateGraph with checkpointer
        thread_id: Thread ID to get history for
        limit: Maximum number of snapshots to return (most recent first)

    Returns:
        List of StateSnapshot objects, ordered from oldest to newest

    Example:
        >>> history = get_state_history(graph, "paper_123")
        >>> for snapshot in history:
        ...     print(f"Step {snapshot.step}: {snapshot.node_name}")
    """
    config = {"configurable": {"thread_id": thread_id}}

    snapshots = []

    try:
        # LangGraph's get_state_history returns an iterator
        history_iter = graph.get_state_history(config)

        step = 0
        for state in history_iter:
            # Parse timestamp - may be string or datetime depending on LangGraph version
            raw_timestamp = state.created_at if hasattr(state, "created_at") else None
            parsed_timestamp = _parse_timestamp(raw_timestamp)

            snapshot = StateSnapshot(
                step=step,
                node_name=state.metadata.get("langgraph_node", "unknown") if state.metadata else "unknown",
                timestamp=parsed_timestamp,
                state=dict(state.values) if state.values else {},
                metadata=dict(state.metadata) if state.metadata else {},
            )
            snapshots.append(snapshot)
            step += 1

            if limit and step >= limit:
                break

        # Reverse to get oldest first
        snapshots.reverse()

    except Exception as e:
        logger.error(f"Failed to get state history for thread {thread_id}: {e}")

    return snapshots


def get_latest_state(
    graph: StateGraph,
    thread_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Get the latest state for a thread.

    Args:
        graph: Compiled LangGraph StateGraph with checkpointer
        thread_id: Thread ID

    Returns:
        Latest state dict or None if not found
    """
    config = {"configurable": {"thread_id": thread_id}}

    try:
        state = graph.get_state(config)
        if state and state.values:
            return dict(state.values)
    except Exception as e:
        logger.error(f"Failed to get latest state for thread {thread_id}: {e}")

    return None


# =============================================================================
# EXECUTION ANALYTICS
# =============================================================================

@dataclass
class ExecutionAnalytics:
    """Analytics about a graph execution."""
    thread_id: str
    total_steps: int
    nodes_visited: List[str]
    node_visit_counts: Dict[str, int]
    iterations_used: int
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    duration_seconds: Optional[float]
    final_status: str
    errors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "thread_id": self.thread_id,
            "total_steps": self.total_steps,
            "nodes_visited": self.nodes_visited,
            "node_visit_counts": self.node_visit_counts,
            "iterations_used": self.iterations_used,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "final_status": self.final_status,
            "errors": self.errors,
        }


def get_execution_analytics(
    history: List[StateSnapshot],
    thread_id: str = "",
) -> ExecutionAnalytics:
    """
    Generate analytics from state history.

    Args:
        history: List of StateSnapshots from get_state_history
        thread_id: Thread ID for the execution

    Returns:
        ExecutionAnalytics object with computed metrics

    Example:
        >>> history = get_state_history(graph, "paper_123")
        >>> analytics = get_execution_analytics(history, "paper_123")
        >>> print(f"Total steps: {analytics.total_steps}")
        >>> print(f"Iterations: {analytics.iterations_used}")
    """
    if not history:
        return ExecutionAnalytics(
            thread_id=thread_id,
            total_steps=0,
            nodes_visited=[],
            node_visit_counts={},
            iterations_used=0,
            start_time=None,
            end_time=None,
            duration_seconds=None,
            final_status="no_history",
            errors=[],
        )

    # Compute metrics
    nodes_visited = [s.node_name for s in history]
    node_counts: Dict[str, int] = {}
    for node in nodes_visited:
        node_counts[node] = node_counts.get(node, 0) + 1

    # Get times (parse timestamps if they're strings)
    start_time = _parse_timestamp(history[0].timestamp) if history else None
    end_time = _parse_timestamp(history[-1].timestamp) if history else None
    duration = None
    if start_time and end_time:
        try:
            duration = (end_time - start_time).total_seconds()
        except (TypeError, AttributeError) as e:
            logger.warning(f"Could not compute duration: {e}")

    # Get final state info
    final_state = history[-1].state if history else {}
    iterations = final_state.get("iteration_count", 0)
    is_complete = final_state.get("is_complete", False)
    errors = final_state.get("errors", [])

    final_status = "completed" if is_complete else "incomplete"
    if errors:
        final_status = "error"

    return ExecutionAnalytics(
        thread_id=thread_id,
        total_steps=len(history),
        nodes_visited=nodes_visited,
        node_visit_counts=node_counts,
        iterations_used=iterations,
        start_time=start_time,
        end_time=end_time,
        duration_seconds=duration,
        final_status=final_status,
        errors=errors if isinstance(errors, list) else [str(errors)],
    )


def save_execution_report(
    graph: StateGraph,
    thread_id: str,
    output_path: str | Path,
) -> Path:
    """
    Generate and save a complete execution report.

    Args:
        graph: Compiled graph with checkpointer
        thread_id: Thread ID
        output_path: Path for output file

    Returns:
        Path to saved report
    """
    import json

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Get history and analytics
    history = get_state_history(graph, thread_id)
    analytics = get_execution_analytics(history, thread_id)

    # Build report
    report = {
        "report_generated": datetime.now().isoformat(),
        "analytics": analytics.to_dict(),
        "state_history": [
            {
                "step": s.step,
                "node": s.node_name,
                "timestamp": s.timestamp.isoformat() if s.timestamp else None,
                "state_keys": list(s.state.keys()),
                # Don't include full state to keep report size manageable
            }
            for s in history
        ],
    }

    output_path.write_text(json.dumps(report, indent=2))
    logger.info(f"Execution report saved to: {output_path}")

    return output_path


# =============================================================================
# CONVENIENCE FUNCTIONS FOR PIPELINE
# =============================================================================

def visualize_pipeline(output_dir: str | Path = "outputs") -> Dict[str, Any]:
    """
    Generate all visualizations for the CIViC extraction pipeline.

    Args:
        output_dir: Directory for outputs

    Returns:
        Dict with paths to generated files and any errors
    """
    output_dir = Path(output_dir)
    results = {
        "generated_at": datetime.now().isoformat(),
        "files": {},
        "errors": [],
    }

    # Save graph visualizations
    try:
        graphs_dir = output_dir / "graphs"
        saved = save_all_graph_visualizations(graphs_dir)
        results["files"]["graphs"] = {k: str(v) for k, v in saved.items()}
    except Exception as e:
        results["errors"].append(f"Graph visualization error: {e}")

    return results


if __name__ == "__main__":
    # Quick test when run directly
    print("Generating pipeline visualizations...")
    results = visualize_pipeline()
    print(f"Generated at: {results['generated_at']}")
    print(f"Files: {results['files']}")
    if results['errors']:
        print(f"Errors: {results['errors']}")
