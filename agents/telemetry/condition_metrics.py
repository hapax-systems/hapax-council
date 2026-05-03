"""Per-condition Prometheus slicing for LLM-call metrics (LRR Phase 10 §3.1).

Wraps the existing prometheus_client primitives with a helper that reads the
current research condition and passes it as a label to every observation.
This enables slicing dashboards / alerts / correlation reports by Condition A
(e.g., Qwen3.5-9B) vs Condition A' (e.g., OLMo-3-7B) once both are live in
the append-only research registry.

Design:
- Reads condition from ``shared.research_condition.get_current_condition``.
- Never raises on a condition read failure — falls through to the "unknown"
  label rather than dropping the metric (time series continuity over
  attribution accuracy under transient registry drift).
- Metric objects are module-level singletons so registration happens once at
  import time; safe to call from multiple callers.
- Callers supply model, route, and outcome labels; condition is added here.

Usage:

    from agents.telemetry.condition_metrics import (
        record_llm_call_start,
        record_llm_call_finish,
    )

    record_llm_call_start(model="qwen3.5-9b", route="local-fast")
    # ... LLM call ...
    record_llm_call_finish(
        model="qwen3.5-9b",
        route="local-fast",
        outcome="success",
        latency_seconds=0.742,
    )
"""

from __future__ import annotations

try:
    from prometheus_client import REGISTRY, Counter, Histogram

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False
    REGISTRY = None  # type: ignore[misc,assignment]
    Counter = None  # type: ignore[misc,assignment]
    Histogram = None  # type: ignore[misc,assignment]


_LLM_CALLS_TOTAL = None
_LLM_CALL_LATENCY_SECONDS = None
_LLM_CALL_OUTCOMES_TOTAL = None
_LLM_CALL_COST_DOLLARS_TOTAL = None

_LLM_LATENCY_BUCKETS = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    4.0,
    8.0,
    15.0,
    30.0,
    60.0,
    float("inf"),
)


def _ensure_metrics(registry=None) -> None:
    """Lazy-register metrics. Tests may pass a fresh CollectorRegistry."""
    global _LLM_CALLS_TOTAL, _LLM_CALL_LATENCY_SECONDS, _LLM_CALL_OUTCOMES_TOTAL
    global _LLM_CALL_COST_DOLLARS_TOTAL

    if not _PROMETHEUS_AVAILABLE:
        return

    effective_registry = registry if registry is not None else REGISTRY

    if _LLM_CALLS_TOTAL is None:
        _LLM_CALLS_TOTAL = Counter(
            "hapax_llm_calls_total",
            "Total LLM calls, labeled by research condition, model, and route.",
            ["condition", "model", "route"],
            registry=effective_registry,
        )
    if _LLM_CALL_LATENCY_SECONDS is None:
        _LLM_CALL_LATENCY_SECONDS = Histogram(
            "hapax_llm_call_latency_seconds",
            "End-to-end LLM call latency (seconds).",
            ["condition", "model", "route"],
            buckets=_LLM_LATENCY_BUCKETS,
            registry=effective_registry,
        )
    if _LLM_CALL_OUTCOMES_TOTAL is None:
        _LLM_CALL_OUTCOMES_TOTAL = Counter(
            "hapax_llm_call_outcomes_total",
            "Terminal LLM call outcomes (success|error|timeout|refused).",
            ["condition", "model", "route", "outcome"],
            registry=effective_registry,
        )
    # cc-task vision-cost-guard-prometheus-emitter — per-call cost tracking.
    # LiteLLM Proxy returns response cost via the `_hidden_params._response_cost`
    # path on the OpenAI client response object. Callers (currently DMN
    # multimodal) pass this into `set_cost` on the LlmCallSpan; the span emits
    # to this counter on exit. PromQL `rate(...total[1h]) * 3600` derives
    # `hapax_vision_cost_per_hour_dollars` for alerting (Grafana alert rule
    # is a separate downstream cc-task).
    if _LLM_CALL_COST_DOLLARS_TOTAL is None:
        _LLM_CALL_COST_DOLLARS_TOTAL = Counter(
            "hapax_llm_call_cost_dollars_total",
            "Per-call LLM cost in USD, sourced from LiteLLM response.",
            ["condition", "model", "route"],
            registry=effective_registry,
        )


def reset_for_testing() -> None:
    """Reset module-level singletons so tests can re-register with a fresh registry."""
    global _LLM_CALLS_TOTAL, _LLM_CALL_LATENCY_SECONDS, _LLM_CALL_OUTCOMES_TOTAL
    global _LLM_CALL_COST_DOLLARS_TOTAL
    _LLM_CALLS_TOTAL = None
    _LLM_CALL_LATENCY_SECONDS = None
    _LLM_CALL_OUTCOMES_TOTAL = None
    _LLM_CALL_COST_DOLLARS_TOTAL = None


def _condition() -> str:
    from shared.research_condition import get_current_condition

    try:
        return get_current_condition()
    except Exception:  # noqa: BLE001 — metrics must never raise
        return "unknown"


def record_llm_call_start(*, model: str, route: str) -> None:
    """Record that a call has begun. Increments the call counter."""
    _ensure_metrics()
    if _LLM_CALLS_TOTAL is None:
        return
    _LLM_CALLS_TOTAL.labels(condition=_condition(), model=model, route=route).inc()


def record_llm_call_finish(
    *,
    model: str,
    route: str,
    outcome: str,
    latency_seconds: float,
) -> None:
    """Record terminal state for a call: observe latency + outcome."""
    _ensure_metrics()
    cond = _condition()
    if _LLM_CALL_LATENCY_SECONDS is not None:
        _LLM_CALL_LATENCY_SECONDS.labels(condition=cond, model=model, route=route).observe(
            latency_seconds
        )
    if _LLM_CALL_OUTCOMES_TOTAL is not None:
        _LLM_CALL_OUTCOMES_TOTAL.labels(
            condition=cond, model=model, route=route, outcome=outcome
        ).inc()


def record_llm_call_cost(*, model: str, route: str, cost_dollars: float) -> None:
    """Record per-call LLM cost in USD.

    Increments `hapax_llm_call_cost_dollars_total{condition, model, route}`
    by `cost_dollars`. Zero / negative / NaN costs are no-ops (graceful for
    proxies that don't emit cost). PromQL `rate(...total[1h]) * 3600`
    derives the per-hour cost for alerting.

    cc-task: vision-cost-guard-prometheus-emitter.
    """
    if cost_dollars is None or cost_dollars <= 0:
        return
    # Guard against NaN.
    try:
        if cost_dollars != cost_dollars:  # NaN test
            return
    except TypeError:
        return
    _ensure_metrics()
    if _LLM_CALL_COST_DOLLARS_TOTAL is None:
        return
    _LLM_CALL_COST_DOLLARS_TOTAL.labels(condition=_condition(), model=model, route=route).inc(
        cost_dollars
    )
