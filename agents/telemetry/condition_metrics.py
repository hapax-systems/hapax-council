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

import json
import logging
import os
import threading
import time
from pathlib import Path

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
# Local-inference VOLUME (NOT dollars). Local models on owned hardware have ~$0
# marginal cost; tracking token/call volume makes local inference visible so the
# cost/capacity signal stops treating it as free (over-route -> fleet saturation).
_LLM_TOKENS_TOTAL = None
_EMBED_CALLS_TOTAL = None
_EMBED_INPUT_CHARS_TOTAL = None
LOCAL_CAPACITY_FILE = Path(
    os.environ.get("HAPAX_LOCAL_CAPACITY_FILE", "/dev/shm/hapax-local-capacity.json")
)
LOCAL_CAPACITY_LEASE_DIR = Path(
    os.environ.get(
        "HAPAX_LOCAL_CAPACITY_LEASE_DIR",
        str(LOCAL_CAPACITY_FILE.with_suffix(f"{LOCAL_CAPACITY_FILE.suffix}.d")),
    )
)
LOCAL_CAPACITY_CEILING = float(os.environ.get("HAPAX_LOCAL_CAPACITY_CEILING", "1"))
LOCAL_CAPACITY_BASELINE_S = float(os.environ.get("HAPAX_LOCAL_CAPACITY_BASELINE_S", "1.0"))
LOCAL_CAPACITY_LEASE_TTL_S = float(os.environ.get("HAPAX_LOCAL_CAPACITY_LEASE_TTL_S", "300"))
_LOCAL_CAPACITY_ALPHA = float(os.environ.get("HAPAX_LOCAL_CAPACITY_EWMA_ALPHA", "0.2"))
_LOCAL_CAPACITY_LOCK = threading.Lock()
_LOCAL_CAPACITY_INFLIGHT = 0
_LOCAL_CAPACITY_TTFT_EWMA_S: float | None = None
_DEFAULT_LOCAL_CAPACITY_FILE = Path("/dev/shm/hapax-local-capacity.json")
_LOG = logging.getLogger(__name__)

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
    global _LLM_TOKENS_TOTAL, _EMBED_CALLS_TOTAL, _EMBED_INPUT_CHARS_TOTAL

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
    # Local-inference volume — makes Ollama embed + TabbyAPI/Command-R visible.
    # These are VOLUME (tokens/calls/chars), never dollars; they must NOT be summed
    # into the cost path. nomic embed has no usage field, so embeds track call+char
    # volume only (no fabricated tokens).
    if _LLM_TOKENS_TOTAL is None:
        _LLM_TOKENS_TOTAL = Counter(
            "hapax_llm_tokens_total",
            "Local/remote LLM token volume by direction (prompt|completion).",
            ["condition", "model", "route", "direction"],
            registry=effective_registry,
        )
    if _EMBED_CALLS_TOTAL is None:
        _EMBED_CALLS_TOTAL = Counter(
            "hapax_embed_calls_total",
            "Embedding calls (Ollama, local). nomic returns no usage; volume proxy.",
            ["condition", "model", "kind"],
            registry=effective_registry,
        )
    if _EMBED_INPUT_CHARS_TOTAL is None:
        _EMBED_INPUT_CHARS_TOTAL = Counter(
            "hapax_embed_input_chars_total",
            "Embedding input characters (volume proxy; nomic has no token usage).",
            ["condition", "model", "kind"],
            registry=effective_registry,
        )


def reset_for_testing() -> None:
    """Reset module-level singletons so tests can re-register with a fresh registry."""
    global _LLM_CALLS_TOTAL, _LLM_CALL_LATENCY_SECONDS, _LLM_CALL_OUTCOMES_TOTAL
    global _LLM_CALL_COST_DOLLARS_TOTAL
    global _LLM_TOKENS_TOTAL, _EMBED_CALLS_TOTAL, _EMBED_INPUT_CHARS_TOTAL
    global _LOCAL_CAPACITY_INFLIGHT, _LOCAL_CAPACITY_TTFT_EWMA_S
    _LLM_CALLS_TOTAL = None
    _LLM_CALL_LATENCY_SECONDS = None
    _LLM_CALL_OUTCOMES_TOTAL = None
    _LLM_CALL_COST_DOLLARS_TOTAL = None
    _LLM_TOKENS_TOTAL = None
    _EMBED_CALLS_TOTAL = None
    _EMBED_INPUT_CHARS_TOTAL = None
    with _LOCAL_CAPACITY_LOCK:
        _LOCAL_CAPACITY_INFLIGHT = 0
        _LOCAL_CAPACITY_TTFT_EWMA_S = None
        try:
            _local_capacity_lease_file().unlink(missing_ok=True)
        except Exception:
            _LOG.debug("local capacity lease reset failed", exc_info=True)


def _condition() -> str:
    from shared.research_condition import get_current_condition

    try:
        return get_current_condition()
    except Exception:  # noqa: BLE001 — metrics must never raise
        return "unknown"


def _is_local_capacity_route(*, model: str, route: str) -> bool:
    model_l = model.lower()
    route_l = route.lower()
    if route_l.startswith("local") or route_l in {
        "dmn-sensory",
        "dmn-thinking",
        "local-judge",
        "spontaneous-speech",
    }:
        return True
    local_model_hints = (
        "local-fast",
        "command-r",
        "qwen",
        "tabby",
        "ollama",
        "nomic",
        "llama",
        "mlx",
    )
    return any(hint in model_l for hint in local_model_hints)


def _local_capacity_lease_file() -> Path:
    return LOCAL_CAPACITY_LEASE_DIR / f"{os.getpid()}.json"


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _write_local_capacity_lease_locked() -> None:
    try:
        LOCAL_CAPACITY_LEASE_DIR.mkdir(parents=True, exist_ok=True)
        lease = _local_capacity_lease_file()
        if _LOCAL_CAPACITY_INFLIGHT <= 0 and _LOCAL_CAPACITY_TTFT_EWMA_S is None:
            lease.unlink(missing_ok=True)
            return
        payload = {
            "pid": os.getpid(),
            "timestamp": time.time(),
            "inflight": _LOCAL_CAPACITY_INFLIGHT,
            "ttft_ewma_s": _LOCAL_CAPACITY_TTFT_EWMA_S,
        }
        tmp = lease.with_suffix(f"{lease.suffix}.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(lease)
    except Exception:
        _LOG.debug("local capacity lease publish failed", exc_info=True)


def _aggregate_local_capacity_leases_locked() -> tuple[int, float | None]:
    now = time.time()
    inflight = 0
    ttft_ewma_s: float | None = None
    try:
        leases = list(LOCAL_CAPACITY_LEASE_DIR.glob("*.json"))
    except Exception:
        _LOG.debug("local capacity lease scan failed", exc_info=True)
        return max(0, _LOCAL_CAPACITY_INFLIGHT), _LOCAL_CAPACITY_TTFT_EWMA_S

    for lease in leases:
        try:
            data = json.loads(lease.read_text(encoding="utf-8"))
        except Exception:
            _LOG.debug("local capacity lease read failed: %s", lease, exc_info=True)
            continue

        timestamp = _safe_float(data.get("timestamp"), default=0.0)
        if timestamp <= 0 or now - timestamp > LOCAL_CAPACITY_LEASE_TTL_S:
            try:
                lease.unlink(missing_ok=True)
            except Exception:
                _LOG.debug("stale local capacity lease cleanup failed: %s", lease, exc_info=True)
            continue

        inflight += max(0, int(_safe_float(data.get("inflight"), default=0.0)))
        lease_ttft = data.get("ttft_ewma_s")
        if lease_ttft is not None:
            lease_ttft_f = _safe_float(lease_ttft, default=0.0)
            if lease_ttft_f > 0:
                ttft_ewma_s = max(ttft_ewma_s or 0.0, lease_ttft_f)

    return inflight, ttft_ewma_s


def _publish_local_capacity_locked() -> None:
    if (
        os.environ.get("PYTEST_CURRENT_TEST")
        and LOCAL_CAPACITY_FILE == _DEFAULT_LOCAL_CAPACITY_FILE
    ):
        return
    _write_local_capacity_lease_locked()
    ceiling = max(0.0, LOCAL_CAPACITY_CEILING)
    inflight, aggregate_ttft_ewma_s = _aggregate_local_capacity_leases_locked()
    ttft_ewma_s = aggregate_ttft_ewma_s if aggregate_ttft_ewma_s is not None else 0.0
    baseline_s = LOCAL_CAPACITY_BASELINE_S if LOCAL_CAPACITY_BASELINE_S > 0 else 1.0
    payload = {
        "timestamp": time.time(),
        "inflight": inflight,
        "ceiling": ceiling,
        "ttft_ewma_s": round(ttft_ewma_s, 3),
        "ttft_baseline_s": round(baseline_s, 3),
        "ttft_ratio": round(ttft_ewma_s / baseline_s, 3) if ttft_ewma_s > 0 else 1.0,
    }
    try:
        LOCAL_CAPACITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = LOCAL_CAPACITY_FILE.with_suffix(f"{LOCAL_CAPACITY_FILE.suffix}.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(LOCAL_CAPACITY_FILE)
    except Exception:
        _LOG.debug("local capacity aggregate publish failed", exc_info=True)
        return


def _record_local_capacity_start(*, model: str, route: str) -> None:
    global _LOCAL_CAPACITY_INFLIGHT
    if not _is_local_capacity_route(model=model, route=route):
        return
    with _LOCAL_CAPACITY_LOCK:
        _LOCAL_CAPACITY_INFLIGHT += 1
        _publish_local_capacity_locked()


def _record_local_capacity_finish(*, model: str, route: str, ttft_seconds: float | None) -> None:
    global _LOCAL_CAPACITY_INFLIGHT, _LOCAL_CAPACITY_TTFT_EWMA_S
    if not _is_local_capacity_route(model=model, route=route):
        return
    with _LOCAL_CAPACITY_LOCK:
        _LOCAL_CAPACITY_INFLIGHT = max(0, _LOCAL_CAPACITY_INFLIGHT - 1)
        if ttft_seconds is not None and ttft_seconds > 0:
            if _LOCAL_CAPACITY_TTFT_EWMA_S is None:
                _LOCAL_CAPACITY_TTFT_EWMA_S = ttft_seconds
            else:
                _LOCAL_CAPACITY_TTFT_EWMA_S = (
                    _LOCAL_CAPACITY_ALPHA * ttft_seconds
                    + (1 - _LOCAL_CAPACITY_ALPHA) * _LOCAL_CAPACITY_TTFT_EWMA_S
                )
        _publish_local_capacity_locked()


def record_llm_call_start(*, model: str, route: str) -> None:
    """Record that a call has begun. Increments the call counter."""
    _record_local_capacity_start(model=model, route=route)
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
    ttft_seconds: float | None = None,
) -> None:
    """Record terminal state for a call: observe latency + outcome."""
    _record_local_capacity_finish(model=model, route=route, ttft_seconds=ttft_seconds)
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


def record_llm_call_tokens(
    *, model: str, route: str, prompt_tokens: int, completion_tokens: int
) -> None:
    """Record LLM token VOLUME (prompt + completion), labeled by direction.

    Makes local inference (e.g. TabbyAPI/Command-R, which returns `usage` but no
    LiteLLM dollar cost) visible. This is volume, NOT dollars — it never feeds the
    cost counter. Non-positive counts are no-ops.
    """
    _ensure_metrics()
    if _LLM_TOKENS_TOTAL is None:
        return
    cond = _condition()
    if prompt_tokens and prompt_tokens > 0:
        _LLM_TOKENS_TOTAL.labels(condition=cond, model=model, route=route, direction="prompt").inc(
            prompt_tokens
        )
    if completion_tokens and completion_tokens > 0:
        _LLM_TOKENS_TOTAL.labels(
            condition=cond, model=model, route=route, direction="completion"
        ).inc(completion_tokens)


def record_embed(*, model: str, kind: str, n_calls: int, input_chars: int) -> None:
    """Record embedding VOLUME (call count + input chars).

    Ollama's embed endpoint returns no token usage, so this is a deliberate
    volume proxy (calls + chars) — NOT tokens, NOT dollars. ``kind`` is
    "single"|"batch". Non-positive values are no-ops.
    """
    _ensure_metrics()
    cond = _condition()
    if _EMBED_CALLS_TOTAL is not None and n_calls and n_calls > 0:
        _EMBED_CALLS_TOTAL.labels(condition=cond, model=model, kind=kind).inc(n_calls)
    if _EMBED_INPUT_CHARS_TOTAL is not None and input_chars and input_chars > 0:
        _EMBED_INPUT_CHARS_TOTAL.labels(condition=cond, model=model, kind=kind).inc(input_chars)
