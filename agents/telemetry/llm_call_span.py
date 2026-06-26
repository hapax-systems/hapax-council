"""LLM-call span helper (LRR Phase 10 §3.1 call-site wiring).

Wraps a block of LLM-call code with start/finish telemetry: Prometheus
(per-condition), langfuse tags (if available), and an exception-safe
outcome label. Designed so callers migrate in one line:

    from agents.telemetry.llm_call_span import llm_call_span

    with llm_call_span(model="qwen3.5-9b", route="local-fast") as span:
        result = await agent.run(prompt)

The context manager:

- increments ``hapax_llm_calls_total{condition, model, route}`` on enter
- observes ``hapax_llm_call_latency_seconds{condition, model, route}`` on exit
- increments ``hapax_llm_call_outcomes_total{condition, model, route, outcome}``
  on exit with outcome in {"success", "error", "timeout"}
- optionally records true time-to-first-token via ``span.set_ttft_seconds(...)``
  for local-capacity pressure; total span latency is not a TTFT substitute
- propagates caller exceptions; does not swallow or catch

Callers override the outcome label explicitly via ``span.set_outcome("refused")``
when the LLM response itself is a refusal or other non-error non-success.

This is the single recommended entry point for LLM-call observability
post LRR Phase 10 §3.1. Direct use of ``record_llm_call_start`` /
``record_llm_call_finish`` remains available for callers that can't
use a context manager (e.g., background streaming handlers).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass

from agents.telemetry.condition_metrics import (
    record_llm_call_cost,
    record_llm_call_finish,
    record_llm_call_start,
    record_llm_call_tokens,
)


@dataclass
class LlmCallSpan:
    """Mutable span handle yielded by ``llm_call_span``."""

    model: str
    route: str
    outcome: str = "success"
    cost_dollars: float | None = None
    ttft_seconds: float | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def set_outcome(self, outcome: str) -> None:
        """Override the default "success" outcome label before span exit.

        Common values: "success", "error", "timeout", "refused", "partial".
        """
        self.outcome = outcome

    def set_cost(self, cost_dollars: float | None) -> None:
        """Record per-call cost in USD; emitted to the cost counter on exit.

        cc-task vision-cost-guard-prometheus-emitter. Callers that have
        access to LiteLLM's `_hidden_params._response_cost` (or any other
        per-call cost source) call this during the span block. None /
        zero / negative values are no-ops at emission time (graceful for
        proxies that don't return cost).
        """
        self.cost_dollars = cost_dollars

    def set_ttft_seconds(self, ttft_seconds: float | None) -> None:
        """Record true time-to-first-token for local-capacity pressure.

        Call this when a streaming caller observes the first content/tool
        delta. Do not pass total completion latency here; when TTFT is
        unavailable the local-capacity exporter intentionally emits a
        neutral TTFT ratio and relies on inflight pressure.
        """
        self.ttft_seconds = ttft_seconds

    def set_tokens(self, *, prompt_tokens: int, completion_tokens: int) -> None:
        """Record per-call token VOLUME (e.g. from a local TabbyAPI ``usage`` block).

        Emitted to ``hapax_llm_tokens_total`` on exit. Volume only — NOT dollars;
        local inference uses this instead of ``set_cost`` (no marginal $).
        """
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


@contextmanager
def llm_call_span(*, model: str, route: str):
    """Context-managed per-LLM-call telemetry span.

    Yields a ``LlmCallSpan`` so the caller can override the outcome label
    + record cost before exit. If the block raises, outcome defaults to
    "error".
    """
    span = LlmCallSpan(model=model, route=route)
    record_llm_call_start(model=model, route=route)
    t0 = time.monotonic()
    try:
        yield span
    except TimeoutError:
        span.outcome = "timeout"
        raise
    except Exception:
        span.outcome = "error"
        raise
    finally:
        latency = time.monotonic() - t0
        record_llm_call_finish(
            model=model,
            route=route,
            outcome=span.outcome,
            latency_seconds=latency,
            ttft_seconds=span.ttft_seconds,
        )
        if span.cost_dollars is not None:
            record_llm_call_cost(
                model=model,
                route=route,
                cost_dollars=span.cost_dollars,
            )
        if span.prompt_tokens or span.completion_tokens:
            record_llm_call_tokens(
                model=model,
                route=route,
                prompt_tokens=span.prompt_tokens,
                completion_tokens=span.completion_tokens,
            )
