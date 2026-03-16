"""shared/llm_health.py — LiteLLM proxy health check with circuit breaker.

Provides a cached, non-blocking health check for the LiteLLM proxy.
Used by agents that need to know if LLM calls will succeed before
attempting them (fail-fast rather than timeout).

Usage:
    from shared.llm_health import is_litellm_healthy

    if is_litellm_healthy():
        result = await agent.run(prompt)
    else:
        log.warning("LiteLLM unavailable, skipping LLM call")
"""

from __future__ import annotations

import logging
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

from shared.config import LITELLM_BASE

log = logging.getLogger(__name__)

# Circuit breaker state
_lock = threading.Lock()
_last_check_time: float = 0.0
_last_check_result: bool = False
_consecutive_failures: int = 0

# Configuration
_CACHE_TTL_S: float = 30.0
_TIMEOUT_S: float = 2.0
_CIRCUIT_OPEN_THRESHOLD: int = 3
_CIRCUIT_OPEN_COOLDOWN_S: float = 60.0


def is_litellm_healthy() -> bool:
    """Check if LiteLLM proxy is reachable and responding.

    Results are cached for 30s. After 3 consecutive failures, the circuit
    opens and checks are skipped for 60s (returns False immediately).

    Returns:
        True if the proxy responded to GET /health within 2s.
    """
    global _last_check_time, _last_check_result, _consecutive_failures

    with _lock:
        now = time.monotonic()
        elapsed = now - _last_check_time

        # Circuit breaker: if open, skip check and return False
        if _consecutive_failures >= _CIRCUIT_OPEN_THRESHOLD:
            if elapsed < _CIRCUIT_OPEN_COOLDOWN_S:
                return False
            # Cooldown expired, allow a probe
            log.debug("circuit breaker: cooldown expired, probing LiteLLM")

        # Cache: return last result if fresh
        if elapsed < _CACHE_TTL_S:
            return _last_check_result

        # Perform health check
        _last_check_time = now

    # Do the actual HTTP check outside the lock to avoid blocking
    try:
        url = f"{LITELLM_BASE.rstrip('/')}/health"
        with urlopen(url, timeout=_TIMEOUT_S) as resp:
            healthy = resp.status == 200
    except (URLError, OSError, TimeoutError):
        healthy = False

    with _lock:
        _last_check_result = healthy

        if healthy:
            _consecutive_failures = 0
        else:
            _consecutive_failures += 1
            if _consecutive_failures == _CIRCUIT_OPEN_THRESHOLD:
                log.warning(
                    "LiteLLM circuit breaker OPEN after %d failures, skipping checks for %ds",
                    _consecutive_failures,
                    int(_CIRCUIT_OPEN_COOLDOWN_S),
                )

    return healthy


def reset_circuit_breaker() -> None:
    """Reset circuit breaker state (for testing)."""
    global _last_check_time, _last_check_result, _consecutive_failures
    with _lock:
        _last_check_time = 0.0
        _last_check_result = False
        _consecutive_failures = 0
