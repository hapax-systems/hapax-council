"""LiteLLM custom callbacks for Langfuse scoring.

Scores Anthropic generations with rate_limited: BOOLEAN so dashboards
can track rate-limit pressure over time.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class RateLimitScoreCallback:
    """LiteLLM callback that scores generations for rate limiting."""

    def async_log_success_event(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        self._score(kwargs, rate_limited=False)

    def async_log_failure_event(
        self, kwargs: dict[str, Any], response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        exception = kwargs.get("exception")
        if exception is None:
            return

        exc_str = str(exception).lower()
        is_rate_limit = "rate_limit" in exc_str or "429" in exc_str
        if is_rate_limit:
            self._score(kwargs, rate_limited=True)

    @staticmethod
    def _score(kwargs: dict[str, Any], *, rate_limited: bool) -> None:
        """Attach rate_limited boolean score to the current Langfuse observation."""
        model = kwargs.get("model", "")
        if "anthropic" not in model and "claude" not in model:
            return  # only score Anthropic calls

        try:
            from langfuse import get_client

            get_client().score_current_trace(
                name="rate_limited",
                value=int(rate_limited),
                data_type="BOOLEAN",
            )
        except Exception:
            log.debug("Rate limit scoring failed", exc_info=True)
