"""
LLM Client Factory
==================

Provides factory functions for creating LLM clients that connect to
GLM-4.7 via Fireworks AI (OpenAI-compatible API).

This module abstracts the LLM provider so the rest of the codebase
doesn't need to know about Fireworks-specific details.

Features:
- Configurable retry policies with exponential backoff
- Circuit breaker pattern for resilience
- Per-agent LLM configurations optimized for each role
"""

from typing import Optional, Any, Union
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel

from config.settings import (
    FIREWORKS_API_KEY,
    FIREWORKS_BASE_URL,
    FIREWORKS_MODEL_NAME,
    FIREWORKS_VISION_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    VERBOSE,
)

from runtime.retry import RetryableLLM, RETRY_POLICIES, RetryConfig


# =============================================================================
# RETRY CONFIGURATION
# =============================================================================

# Default: Enable retry for production resilience
DEFAULT_ENABLE_RETRY = True

# Circuit breaker names for each agent type
CIRCUIT_BREAKER_NAMES = {
    "reader": "cb_reader",
    "planner": "cb_planner",
    "extractor": "cb_extractor",
    "critic": "cb_critic",
    "normalizer": "cb_normalizer",
    "default": "cb_default",
}


def get_llm(
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    enable_retry: bool = DEFAULT_ENABLE_RETRY,
    retry_policy: Optional[str] = "llm",
    circuit_breaker_name: Optional[str] = None,
    **kwargs: Any,
) -> Union[BaseChatModel, RetryableLLM]:
    """
    Create a LangChain ChatOpenAI instance configured for Fireworks AI.

    This is the primary LLM factory for the CIViC extraction pipeline.
    All agents should use this function to get their LLM instance.

    GLM-4.7 and Kimi-K2 THINKING MODE:
    - Both models have built-in thinking/reasoning (no special params needed)
    - Thinking output appears in `reasoning_content` field
    - Recommended params: temperature=0.6, top_p=0.95
    - 200K context window can handle full paper content

    RETRY BEHAVIOR:
    - By default, all LLMs are wrapped with RetryableLLM for resilience
    - Retries on: TimeoutError, ConnectionError, 429/502/503/504 HTTP errors
    - Uses exponential backoff with jitter
    - Circuit breaker prevents cascade failures

    Args:
        model: Model name (default: FIREWORKS_MODEL_NAME from settings)
        max_tokens: Maximum tokens in response (default: DEFAULT_MAX_TOKENS)
        temperature: Sampling temperature (default: 0.6 for thinking mode)
        enable_retry: Whether to wrap with retry logic (default: True)
        retry_policy: Name of retry policy ("llm", "vision", "normalization")
        circuit_breaker_name: Name for circuit breaker (default: auto-generated)
        **kwargs: Additional arguments passed to ChatOpenAI

    Returns:
        ChatOpenAI instance (or RetryableLLM wrapper if retry enabled)

    Example:
        >>> llm = get_llm()
        >>> response = llm.invoke([HumanMessage(content="Hello")])

        >>> # With custom settings
        >>> llm = get_llm(max_tokens=1000, temperature=0.2)

        >>> # Without retry (for testing)
        >>> llm = get_llm(enable_retry=False)

        >>> # With tools bound
        >>> llm_with_tools = get_llm().bind_tools([my_tool])
    """
    # FIX: Preserve reasoning_content across tool turns for multi-step agents
    # This tells Fireworks to maintain reasoning context during tool call iterations
    # Note: model_kwargs don't work for custom params; using extra_body instead
    # However, ChatOpenAI doesn't support extra_body directly, so we skip this
    # for now until LangChain adds support or we use a custom client
    # TODO: Implement custom Fireworks client wrapper for reasoning_history support

    base_llm = ChatOpenAI(
        api_key=FIREWORKS_API_KEY,
        base_url=FIREWORKS_BASE_URL,
        model=model or FIREWORKS_MODEL_NAME,
        max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
        temperature=temperature if temperature is not None else 0.6,  # Optimal for thinking
        top_p=0.95,  # Optimal for thinking mode
        **kwargs,
    )

    if enable_retry:
        cb_name = circuit_breaker_name or CIRCUIT_BREAKER_NAMES.get("default", "cb_default")
        return RetryableLLM(
            llm=base_llm,
            policy=retry_policy or "llm",
            circuit_breaker_name=cb_name,
        )

    return base_llm


def get_reader_llm(
    max_tokens: Optional[int] = None,
    enable_retry: bool = DEFAULT_ENABLE_RETRY,
    **kwargs: Any,
) -> Union[BaseChatModel, RetryableLLM]:
    """
    Create LLM for the Reader agent.

    The Reader needs to process multimodal input (images of PDF pages)
    and extract structured content. Uses a VISION-CAPABLE model (Qwen3-VL)
    that supports image input.

    THINKING MODE: The Qwen3-VL-thinking model has reasoning enabled by default.
    We use Temperature=0.6, TopP=0.95 as recommended for thinking mode.
    The model will output <think>...</think> blocks for reasoning.

    REASONING PRESERVATION: For multi-step agents with tool calling, we use
    reasoning_history="preserved" to maintain reasoning context across tool turns.
    This prevents reasoning from being lost between tool call iterations.

    RETRY POLICY: Uses "vision" policy with longer delays (5s -> 10s -> 20s)
    since vision calls are slower and more resource-intensive.

    Args:
        max_tokens: Maximum tokens (default: 16384 for detailed extraction)
        enable_retry: Whether to wrap with retry logic (default: True)
        **kwargs: Additional arguments

    Returns:
        ChatOpenAI configured for Reader agent with vision model
    """
    # Note: reasoning_history parameter not supported via LangChain ChatOpenAI
    # The Fireworks API supports it but the OpenAI SDK validates against it
    # TODO: Implement custom client wrapper for full reasoning_history support

    base_llm = ChatOpenAI(
        api_key=FIREWORKS_API_KEY,
        base_url=FIREWORKS_BASE_URL,
        model=FIREWORKS_VISION_MODEL,  # Use vision model with thinking enabled
        max_tokens=max_tokens or 16384,  # Higher for detailed extraction
        temperature=0.6,  # Recommended for thinking mode
        top_p=0.95,  # Recommended for thinking mode
        **kwargs,
    )

    if enable_retry:
        return RetryableLLM(
            llm=base_llm,
            policy="vision",  # Longer delays for vision calls
            circuit_breaker_name=CIRCUIT_BREAKER_NAMES["reader"],
        )

    return base_llm


def get_planner_llm(
    max_tokens: Optional[int] = None,
    enable_retry: bool = DEFAULT_ENABLE_RETRY,
    **kwargs: Any,
) -> Union[BaseChatModel, RetryableLLM]:
    """
    Create LLM for the Planner agent.

    The Planner analyzes paper content and creates extraction strategy.
    GLM-4.7 has built-in thinking for deep analysis.

    Args:
        max_tokens: Maximum tokens (default: 8192 for detailed planning)
        enable_retry: Whether to wrap with retry logic (default: True)
        **kwargs: Additional arguments

    Returns:
        ChatOpenAI configured for Planner agent
    """
    return get_llm(
        max_tokens=max_tokens or 16384,  # Increased for larger structured plans
        temperature=0.6,  # Optimal for thinking mode
        enable_retry=enable_retry,
        retry_policy="llm",
        circuit_breaker_name=CIRCUIT_BREAKER_NAMES["planner"],
        **kwargs,
    )


def get_extractor_llm(
    max_tokens: Optional[int] = None,
    enable_retry: bool = DEFAULT_ENABLE_RETRY,
    **kwargs: Any,
) -> Union[BaseChatModel, RetryableLLM]:
    """
    Create LLM for the Extractor agent.

    The Extractor creates evidence items from paper content.
    GLM-4.7 has built-in thinking for thorough extraction.

    Args:
        max_tokens: Maximum tokens (default: 16384 for multiple evidence items + thinking)
        enable_retry: Whether to wrap with retry logic (default: True)
        **kwargs: Additional arguments

    Returns:
        ChatOpenAI configured for Extractor agent
    """
    return get_llm(
        max_tokens=max_tokens or 16384,  # Higher for thinking + multiple items
        temperature=0.6,  # Optimal for thinking mode
        enable_retry=enable_retry,
        retry_policy="llm",
        circuit_breaker_name=CIRCUIT_BREAKER_NAMES["extractor"],
        **kwargs,
    )


def get_critic_llm(
    max_tokens: Optional[int] = None,
    enable_retry: bool = DEFAULT_ENABLE_RETRY,
    **kwargs: Any,
) -> Union[BaseChatModel, RetryableLLM]:
    """
    Create LLM for the Critic agent.

    The Critic validates evidence items against the paper.
    GLM-4.7 has built-in thinking for careful validation.

    Args:
        max_tokens: Maximum tokens (default: 8192 for detailed feedback)
        enable_retry: Whether to wrap with retry logic (default: True)
        **kwargs: Additional arguments

    Returns:
        ChatOpenAI configured for Critic agent
    """
    return get_llm(
        max_tokens=max_tokens or 8192,  # Increased for thinking + feedback
        temperature=0.6,  # Optimal for thinking mode
        enable_retry=enable_retry,
        retry_policy="llm",
        circuit_breaker_name=CIRCUIT_BREAKER_NAMES["critic"],
        **kwargs,
    )


def get_normalizer_llm(
    max_tokens: Optional[int] = None,
    enable_retry: bool = DEFAULT_ENABLE_RETRY,
    **kwargs: Any,
) -> Union[BaseChatModel, RetryableLLM]:
    """
    Create LLM for the Normalizer agent.

    The Normalizer looks up external IDs for entities.
    GLM-4.7 has built-in thinking for accurate lookups.

    RETRY POLICY: Uses "normalization" policy with shorter delays (1s -> 2s)
    since normalization calls are typically faster.

    Args:
        max_tokens: Maximum tokens (default: 8192)
        enable_retry: Whether to wrap with retry logic (default: True)
        **kwargs: Additional arguments

    Returns:
        ChatOpenAI configured for Normalizer agent
    """
    return get_llm(
        max_tokens=max_tokens or 8192,
        temperature=0.6,  # Optimal for thinking mode
        enable_retry=enable_retry,
        retry_policy="normalization",  # Shorter delays for normalization
        circuit_breaker_name=CIRCUIT_BREAKER_NAMES["normalizer"],
        **kwargs,
    )


def test_connection(enable_retry: bool = False) -> dict[str, Any]:
    """
    Test the connection to Fireworks AI.

    Args:
        enable_retry: Whether to test with retry wrapper (default: False for quick test)

    Returns:
        Dict with connection status and model info

    Raises:
        Exception if connection fails
    """
    from langchain_core.messages import HumanMessage

    llm = get_llm(max_tokens=50, enable_retry=enable_retry)

    try:
        response = llm.invoke([
            HumanMessage(content="Reply with exactly: CONNECTION_OK")
        ])

        return {
            "status": "ok",
            "model": FIREWORKS_MODEL_NAME,
            "base_url": FIREWORKS_BASE_URL,
            "response": response.content,
            "response_type": type(response).__name__,
            "retry_enabled": enable_retry,
        }
    except Exception as e:
        return {
            "status": "error",
            "model": FIREWORKS_MODEL_NAME,
            "base_url": FIREWORKS_BASE_URL,
            "error": str(e),
            "retry_enabled": enable_retry,
        }


# =============================================================================
# RETRY MONITORING AND UTILITIES
# =============================================================================

def get_llm_retry_stats() -> dict[str, Any]:
    """
    Get retry and circuit breaker statistics for all LLM clients.

    Returns:
        Dict with circuit breaker states and failure counts

    Example:
        >>> stats = get_llm_retry_stats()
        >>> print(stats)
        {
            "cb_reader": {"state": "closed", "failure_count": 0, ...},
            "cb_planner": {"state": "closed", "failure_count": 0, ...},
            ...
        }
    """
    from runtime.retry import get_retry_stats
    return get_retry_stats()


def reset_llm_circuit_breakers() -> None:
    """
    Reset all LLM circuit breakers.

    Useful for testing or after resolving external service issues.
    """
    from runtime.retry import reset_all_circuit_breakers
    reset_all_circuit_breakers()


if __name__ == "__main__":
    # Quick test when run directly
    print("Testing Fireworks AI connection...")
    result = test_connection()
    print(f"Status: {result['status']}")
    print(f"Model: {result['model']}")
    if result['status'] == 'ok':
        print(f"Response: {result['response']}")
    else:
        print(f"Error: {result.get('error', 'Unknown')}")
