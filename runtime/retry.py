"""
Retry Policies and Circuit Breaker
===================================

Provides retry functionality with exponential backoff and circuit breaker
pattern for resilient API calls.

Features:
- Exponential backoff with jitter
- Circuit breaker to prevent cascade failures
- Configurable retry conditions
- Comprehensive logging
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional, Set, Type, TypeVar, Union

logger = logging.getLogger("civic.retry")

T = TypeVar("T")


# =============================================================================
# RETRY CONFIGURATION
# =============================================================================

@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    initial_delay: float = 1.0  # seconds
    backoff_multiplier: float = 2.0
    max_delay: float = 60.0  # seconds
    jitter: float = 0.1  # random variation (0-1)
    retry_on: Set[Type[Exception]] = field(default_factory=lambda: {
        TimeoutError,
        ConnectionError,
        ConnectionResetError,
    })

    def should_retry(self, error: Exception) -> bool:
        """Check if error is retryable."""
        # Check exact type match
        if type(error) in self.retry_on:
            return True
        # Check inheritance
        for error_type in self.retry_on:
            if isinstance(error, error_type):
                return True
        # Check for common HTTP errors in error message
        error_str = str(error).lower()
        if any(code in error_str for code in ["504", "502", "503", "429", "timeout", "rate limit"]):
            return True
        return False

    def get_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and jitter."""
        delay = min(
            self.initial_delay * (self.backoff_multiplier ** attempt),
            self.max_delay
        )
        # Add jitter
        jitter_amount = delay * self.jitter * random.random()
        return delay + jitter_amount


# Pre-configured retry policies for different use cases
RETRY_POLICIES = {
    "vision": RetryConfig(
        max_attempts=3,
        initial_delay=5.0,      # Vision calls are slow, longer initial delay
        backoff_multiplier=2.0,  # 5s -> 10s -> 20s
        max_delay=60.0,
    ),
    "llm": RetryConfig(
        max_attempts=3,
        initial_delay=2.0,
        backoff_multiplier=2.0,  # 2s -> 4s -> 8s
        max_delay=30.0,
    ),
    "normalization": RetryConfig(
        max_attempts=2,
        initial_delay=1.0,
        backoff_multiplier=2.0,  # 1s -> 2s
        max_delay=10.0,
    ),
}


# =============================================================================
# CIRCUIT BREAKER
# =============================================================================

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Blocking all calls
    HALF_OPEN = "half_open" # Testing if service recovered


@dataclass
class CircuitBreaker:
    """
    Circuit breaker to prevent cascade failures.

    When too many failures occur, the circuit "opens" and blocks
    further calls for a cooldown period. After cooldown, it enters
    "half-open" state to test if the service has recovered.

    Usage:
        breaker = CircuitBreaker(name="external_api")

        if breaker.can_execute():
            try:
                result = call_api()
                breaker.record_success()
            except Exception as e:
                breaker.record_failure()
                raise
        else:
            raise CircuitOpenError("Circuit is open")
    """
    name: str
    failure_threshold: int = 5        # Failures before opening
    recovery_timeout: float = 30.0    # Seconds before trying again
    half_open_max_calls: int = 1      # Calls to allow in half-open state

    # Internal state
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: Optional[datetime] = field(default=None, init=False)
    _half_open_calls: int = field(default=0, init=False)

    @property
    def state(self) -> CircuitState:
        """Get current state, checking for recovery."""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time:
                time_since_failure = (datetime.now() - self._last_failure_time).total_seconds()
                if time_since_failure >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info(f"[CircuitBreaker:{self.name}] Entering half-open state")
        return self._state

    def can_execute(self) -> bool:
        """Check if a call can be made."""
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        elif state == CircuitState.HALF_OPEN:
            return self._half_open_calls < self.half_open_max_calls
        else:  # OPEN
            return False

    def record_success(self) -> None:
        """Record a successful call."""
        if self._state == CircuitState.HALF_OPEN:
            logger.info(f"[CircuitBreaker:{self.name}] Recovery confirmed, closing circuit")
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = datetime.now()

        if self._state == CircuitState.HALF_OPEN:
            logger.warning(f"[CircuitBreaker:{self.name}] Failed in half-open state, reopening")
            self._state = CircuitState.OPEN
        elif self._failure_count >= self.failure_threshold:
            logger.warning(f"[CircuitBreaker:{self.name}] Threshold reached ({self._failure_count}), opening circuit")
            self._state = CircuitState.OPEN

        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


# Global circuit breakers for different services
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str, **kwargs) -> CircuitBreaker:
    """Get or create a circuit breaker by name."""
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name=name, **kwargs)
    return _circuit_breakers[name]


def reset_all_circuit_breakers() -> None:
    """Reset all circuit breakers (useful for testing)."""
    _circuit_breakers.clear()


# =============================================================================
# RETRY DECORATORS
# =============================================================================

def with_retry(
    config: Optional[RetryConfig] = None,
    policy_name: Optional[str] = None,
    circuit_breaker: Optional[str] = None,
) -> Callable:
    """
    Decorator to add retry logic to a function.

    Args:
        config: RetryConfig instance
        policy_name: Name of pre-defined policy (e.g., "llm", "vision")
        circuit_breaker: Name of circuit breaker to use

    Usage:
        @with_retry(policy_name="llm")
        def call_llm():
            ...

        @with_retry(config=RetryConfig(max_attempts=5))
        def custom_call():
            ...
    """
    if config is None:
        if policy_name and policy_name in RETRY_POLICIES:
            config = RETRY_POLICIES[policy_name]
        else:
            config = RetryConfig()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            breaker = get_circuit_breaker(circuit_breaker) if circuit_breaker else None

            for attempt in range(config.max_attempts):
                # Check circuit breaker
                if breaker and not breaker.can_execute():
                    raise CircuitOpenError(f"Circuit breaker '{circuit_breaker}' is open")

                try:
                    result = func(*args, **kwargs)
                    if breaker:
                        breaker.record_success()
                    return result

                except Exception as e:
                    if breaker:
                        breaker.record_failure()

                    is_last_attempt = attempt == config.max_attempts - 1
                    should_retry = config.should_retry(e) and not is_last_attempt

                    if should_retry:
                        delay = config.get_delay(attempt)
                        logger.warning(
                            f"[Retry] {func.__name__} failed (attempt {attempt + 1}/{config.max_attempts}): "
                            f"{type(e).__name__}: {str(e)[:100]}. Retrying in {delay:.1f}s"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"[Retry] {func.__name__} failed after {attempt + 1} attempts: "
                            f"{type(e).__name__}: {str(e)[:200]}"
                        )
                        raise

            # Should never reach here, but just in case
            raise RuntimeError(f"Retry loop completed without success for {func.__name__}")

        return wrapper
    return decorator


def with_retry_async(
    config: Optional[RetryConfig] = None,
    policy_name: Optional[str] = None,
    circuit_breaker: Optional[str] = None,
) -> Callable:
    """
    Async version of with_retry decorator.

    Usage:
        @with_retry_async(policy_name="llm")
        async def call_llm_async():
            ...
    """
    if config is None:
        if policy_name and policy_name in RETRY_POLICIES:
            config = RETRY_POLICIES[policy_name]
        else:
            config = RetryConfig()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            breaker = get_circuit_breaker(circuit_breaker) if circuit_breaker else None

            for attempt in range(config.max_attempts):
                # Check circuit breaker
                if breaker and not breaker.can_execute():
                    raise CircuitOpenError(f"Circuit breaker '{circuit_breaker}' is open")

                try:
                    result = await func(*args, **kwargs)
                    if breaker:
                        breaker.record_success()
                    return result

                except Exception as e:
                    if breaker:
                        breaker.record_failure()

                    is_last_attempt = attempt == config.max_attempts - 1
                    should_retry = config.should_retry(e) and not is_last_attempt

                    if should_retry:
                        delay = config.get_delay(attempt)
                        logger.warning(
                            f"[Retry] {func.__name__} failed (attempt {attempt + 1}/{config.max_attempts}): "
                            f"{type(e).__name__}: {str(e)[:100]}. Retrying in {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"[Retry] {func.__name__} failed after {attempt + 1} attempts: "
                            f"{type(e).__name__}: {str(e)[:200]}"
                        )
                        raise

            raise RuntimeError(f"Retry loop completed without success for {func.__name__}")

        return wrapper
    return decorator


# =============================================================================
# LLM-SPECIFIC RETRY WRAPPER
# =============================================================================

class RetryableLLM:
    """
    Wrapper that adds retry functionality to any LangChain LLM.

    Usage:
        from langchain_openai import ChatOpenAI

        base_llm = ChatOpenAI(...)
        llm = RetryableLLM(base_llm, policy="llm")

        # Use like normal LLM
        response = llm.invoke(messages)
    """

    def __init__(
        self,
        llm: Any,
        policy: str = "llm",
        circuit_breaker_name: Optional[str] = None,
    ):
        self._llm = llm
        self._config = RETRY_POLICIES.get(policy, RetryConfig())
        self._circuit_breaker_name = circuit_breaker_name or f"llm_{id(llm)}"
        self._breaker = get_circuit_breaker(self._circuit_breaker_name)

    def __getattr__(self, name: str) -> Any:
        """Proxy all attributes to underlying LLM."""
        return getattr(self._llm, name)

    def invoke(self, *args, **kwargs) -> Any:
        """Invoke with retry."""
        for attempt in range(self._config.max_attempts):
            if not self._breaker.can_execute():
                raise CircuitOpenError(f"Circuit breaker '{self._circuit_breaker_name}' is open")

            try:
                result = self._llm.invoke(*args, **kwargs)
                self._breaker.record_success()
                return result

            except Exception as e:
                self._breaker.record_failure()
                is_last = attempt == self._config.max_attempts - 1

                if self._config.should_retry(e) and not is_last:
                    delay = self._config.get_delay(attempt)
                    logger.warning(f"[RetryableLLM] Retry {attempt + 1}/{self._config.max_attempts}: {e}. Waiting {delay:.1f}s")
                    time.sleep(delay)
                else:
                    raise

        raise RuntimeError("Retry exhausted")

    async def ainvoke(self, *args, **kwargs) -> Any:
        """Async invoke with retry."""
        for attempt in range(self._config.max_attempts):
            if not self._breaker.can_execute():
                raise CircuitOpenError(f"Circuit breaker '{self._circuit_breaker_name}' is open")

            try:
                result = await self._llm.ainvoke(*args, **kwargs)
                self._breaker.record_success()
                return result

            except Exception as e:
                self._breaker.record_failure()
                is_last = attempt == self._config.max_attempts - 1

                if self._config.should_retry(e) and not is_last:
                    delay = self._config.get_delay(attempt)
                    logger.warning(f"[RetryableLLM] Retry {attempt + 1}/{self._config.max_attempts}: {e}. Waiting {delay:.1f}s")
                    await asyncio.sleep(delay)
                else:
                    raise

        raise RuntimeError("Retry exhausted")

    def bind_tools(self, *args, **kwargs) -> "RetryableLLM":
        """Bind tools and return wrapped version."""
        bound = self._llm.bind_tools(*args, **kwargs)
        return RetryableLLM(bound, circuit_breaker_name=self._circuit_breaker_name)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_retry_stats() -> dict[str, Any]:
    """Get statistics about circuit breakers."""
    return {
        name: {
            "state": breaker.state.value,
            "failure_count": breaker._failure_count,
            "last_failure": breaker._last_failure_time.isoformat() if breaker._last_failure_time else None,
        }
        for name, breaker in _circuit_breakers.items()
    }


if __name__ == "__main__":
    # Quick test
    import time

    # Test retry decorator
    call_count = 0

    @with_retry(config=RetryConfig(max_attempts=3, initial_delay=0.1))
    def flaky_function():
        global call_count
        call_count += 1
        if call_count < 3:
            raise TimeoutError("Simulated timeout")
        return "success"

    print("Testing retry decorator...")
    result = flaky_function()
    print(f"Result: {result}, Calls: {call_count}")

    # Test circuit breaker
    print("\nTesting circuit breaker...")
    breaker = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout=1.0)

    for i in range(5):
        if breaker.can_execute():
            breaker.record_failure()
            print(f"Call {i}: Failed, state={breaker.state.value}")
        else:
            print(f"Call {i}: Blocked (circuit open)")

    print("Waiting for recovery...")
    time.sleep(1.5)
    print(f"After recovery: state={breaker.state.value}, can_execute={breaker.can_execute()}")
