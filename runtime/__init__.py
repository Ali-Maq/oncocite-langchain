"""
Runtime utilities for CIViC LangGraph pipeline.

This package contains:
- llm.py: LLM client factory for GLM-4/Qwen via Fireworks AI with retry policies
- checkpointing.py: LangGraph checkpointer factory
- retry.py: Retry policies and circuit breaker for resilient API calls
- visualization.py: Graph visualization and state history analytics
- map_reduce.py: Parallel normalization with ordering preservation

Usage:
    from runtime.llm import get_llm, get_reader_llm, get_llm_retry_stats
    from runtime.checkpointing import get_checkpointer
    from runtime.retry import RetryableLLM, CircuitBreaker
    from runtime.visualization import (
        save_graph_visualization,
        get_state_history,
        get_execution_analytics,
    )
    from runtime.map_reduce import normalize_items_parallel
"""

# LLM client exports
from runtime.llm import (
    get_llm,
    get_reader_llm,
    get_planner_llm,
    get_extractor_llm,
    get_critic_llm,
    get_normalizer_llm,
    test_connection,
    get_llm_retry_stats,
    reset_llm_circuit_breakers,
)

# Checkpointing exports
from runtime.checkpointing import (
    get_checkpointer,
)

# Retry exports
from runtime.retry import (
    RetryConfig,
    RetryableLLM,
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
    RETRY_POLICIES,
    with_retry,
    with_retry_async,
    get_retry_stats,
    reset_all_circuit_breakers,
)

# Visualization exports
from runtime.visualization import (
    get_mermaid_diagram,
    save_graph_visualization,
    save_all_graph_visualizations,
    get_state_history,
    get_latest_state,
    get_execution_analytics,
    save_execution_report,
    visualize_pipeline,
    StateSnapshot,
    ExecutionAnalytics,
)

# Map-Reduce exports
from runtime.map_reduce import (
    normalize_items_parallel,
    normalize_items_sync,
    extract_normalization_tasks,
    apply_normalization_results,
    NormalizationTask,
    NormalizationResult,
    MapReduceStats,
)

__all__ = [
    # LLM
    "get_llm",
    "get_reader_llm",
    "get_planner_llm",
    "get_extractor_llm",
    "get_critic_llm",
    "get_normalizer_llm",
    "test_connection",
    "get_llm_retry_stats",
    "reset_llm_circuit_breakers",
    # Checkpointing
    "get_checkpointer",
    # Retry
    "RetryConfig",
    "RetryableLLM",
    "CircuitBreaker",
    "CircuitState",
    "CircuitOpenError",
    "RETRY_POLICIES",
    "with_retry",
    "with_retry_async",
    "get_retry_stats",
    "reset_all_circuit_breakers",
    # Visualization
    "get_mermaid_diagram",
    "save_graph_visualization",
    "save_all_graph_visualizations",
    "get_state_history",
    "get_latest_state",
    "get_execution_analytics",
    "save_execution_report",
    "visualize_pipeline",
    "StateSnapshot",
    "ExecutionAnalytics",
    # Map-Reduce
    "normalize_items_parallel",
    "normalize_items_sync",
    "extract_normalization_tasks",
    "apply_normalization_results",
    "NormalizationTask",
    "NormalizationResult",
    "MapReduceStats",
]
