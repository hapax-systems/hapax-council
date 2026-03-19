"""Circulatory system telemetry — domain-aware Langfuse instrumentation.

Maps the five Hapax circulatory systems into Langfuse traces/spans/events
so Langfuse becomes a navigable live map of system phenomenology.

Five circulations:
  1. Perception (2.5s heartbeat) — sensory data flow
  2. Stimmung (15s/5s adaptive) — system self-state
  3. Visual (0.5-5s adaptive) — ambient field rendering
  4. Experiential (episode-bounded) — learning & correction
  5. Prediction (3s) — anticipation & pre-computation

Cross-system interactions are logged as events with source/target tags,
making the flow interactions visible in Langfuse's trace timeline.

Usage:
    from shared.telemetry import hapax_span, hapax_event, hapax_score

    with hapax_span("perception", "tick", metadata={...}) as span:
        # perception tick work
        hapax_score(span, "confidence", 0.85)

    hapax_event("stimmung", "stance_change", metadata={"from": "nominal", "to": "cautious"})
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any

log = logging.getLogger("hapax.telemetry")

# ── Langfuse client (lazy init) ──────────────────────────────────────────────

_langfuse = None
_available: bool | None = None


def _get_langfuse():
    """Get Langfuse client singleton. Returns None if unavailable."""
    global _langfuse, _available  # noqa: PLW0603
    if _available is False:
        return None
    if _langfuse is not None:
        return _langfuse
    try:
        from langfuse import get_client

        _langfuse = get_client()
        _available = True
        return _langfuse
    except Exception:
        _available = False
        log.debug("Langfuse client not available", exc_info=True)
        return None


# ── System Tags ──────────────────────────────────────────────────────────────

SYSTEMS = frozenset(
    {
        "perception",
        "stimmung",
        "visual",
        "experiential",
        "prediction",
        "voice",
        "engine",
        "interaction",
    }
)


def _system_tags(system: str, extra_tags: list[str] | None = None) -> list[str]:
    """Build tag list: system name + optional extras."""
    tags = [f"system:{system}"]
    if extra_tags:
        tags.extend(extra_tags)
    return tags


# ── Core Instrumentation ─────────────────────────────────────────────────────


@contextmanager
def hapax_span(
    system: str,
    name: str,
    *,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    session_id: str | None = None,
    input_data: Any = None,
):
    """Create a Langfuse span for a circulatory system tick.

    Yields the span object (or None if Langfuse unavailable).
    All operations are best-effort — failures never block the caller.

    Args:
        system: One of: perception, stimmung, visual, experiential, prediction
        name: Operation name (e.g., "tick", "update", "consolidation")
        metadata: Domain-specific key-value pairs
        tags: Additional tags beyond the auto-generated system tag
        session_id: Episode/session grouping key
        input_data: Structured input for the span
    """
    client = _get_langfuse()
    if client is None:
        yield None
        return

    full_name = f"{system}.{name}"
    all_tags = _system_tags(system, tags)

    try:
        from langfuse import propagate_attributes

        with propagate_attributes(
            tags=all_tags,
            session_id=session_id,
            metadata=metadata or {},
        ):
            with client.start_as_current_observation(
                as_type="span",
                name=full_name,
                input=input_data,
                metadata=metadata or {},
            ) as span:
                yield span
    except Exception:
        log.debug("Langfuse span failed: %s", full_name, exc_info=True)
        yield None


def hapax_event(
    system: str,
    name: str,
    *,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    level: str = "DEFAULT",
) -> None:
    """Log a point-in-time event in a circulatory system.

    Use for: state transitions, boundary crossings, interactions.
    """
    client = _get_langfuse()
    if client is None:
        return

    full_name = f"{system}.{name}"
    try:
        with client.start_as_current_observation(
            as_type="event",
            name=full_name,
            metadata=metadata or {},
            level=level,
        ):
            pass
    except Exception:
        log.debug("Langfuse event failed: %s", full_name, exc_info=True)


def hapax_score(
    span: Any,
    name: str,
    value: float,
    *,
    comment: str = "",
) -> None:
    """Attach a numeric score to a span.

    Use for: confidence, hit rate, surprise, coherence.
    """
    if span is None:
        return
    try:
        span.score(name=name, value=round(value, 4), data_type="NUMERIC", comment=comment)
    except Exception:
        log.debug("Langfuse score failed: %s", name, exc_info=True)


@contextmanager
def hapax_trace(
    system: str,
    name: str,
    *,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    session_id: str | None = None,
    input_data: Any = None,
):
    """Create a top-level Langfuse chain span for a system operation.

    Unlike hapax_span (which creates child observations), this creates a root-level
    "chain" span that groups an entire operation. Child hapax_span() calls within
    the context will nest automatically.

    Use for: utterance lifecycles, reactive engine events, sync runs.
    """
    client = _get_langfuse()
    if client is None:
        yield None
        return

    full_name = f"{system}.{name}"
    all_tags = _system_tags(system, tags)

    try:
        from langfuse import propagate_attributes

        with propagate_attributes(
            tags=all_tags,
            session_id=session_id,
            metadata=metadata or {},
        ):
            with client.start_as_current_observation(
                as_type="chain",
                name=full_name,
                input=input_data,
                metadata=metadata or {},
            ) as trace:
                yield trace
    except Exception:
        log.debug("Langfuse trace failed: %s", full_name, exc_info=True)
        yield None


def hapax_bool_score(
    span: Any,
    name: str,
    value: bool,
    *,
    comment: str = "",
) -> None:
    """Attach a boolean score to a span.

    Use for: consent_latency_ok, rate_limited, threshold checks.
    """
    if span is None:
        return
    try:
        span.score(name=name, value=int(value), data_type="BOOLEAN", comment=comment)
    except Exception:
        log.debug("Langfuse bool score failed: %s", name, exc_info=True)


def hapax_interaction(
    source: str,
    target: str,
    interaction: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Log a cross-system interaction.

    Use for: stimmung modulating engine, surprise contradicting cache,
    correction influencing prediction.
    """
    hapax_event(
        "interaction",
        f"{source}_to_{target}.{interaction}",
        metadata={
            "source_system": source,
            "target_system": target,
            "interaction_type": interaction,
            **(metadata or {}),
        },
        tags=[f"system:{source}", f"system:{target}", "cross-system"],
    )


# ── Convenience: Perception Telemetry ────────────────────────────────────────


def trace_perception_tick(
    flow_score: float,
    activity: str,
    audio_energy: float,
    confidence: float,
    backends_active: int = 0,
    session_id: str | None = None,
) -> None:
    """Lightweight perception tick trace (no context manager needed)."""
    client = _get_langfuse()
    if client is None:
        return
    try:
        with client.start_as_current_observation(
            as_type="span",
            name="perception.tick",
            metadata={
                "flow_score": round(flow_score, 3),
                "activity": activity,
                "audio_energy": round(audio_energy, 4),
                "confidence": round(confidence, 3),
                "backends_active": backends_active,
            },
        ) as span:
            span.score(
                name="perception_confidence", value=round(confidence, 4), data_type="NUMERIC"
            )
    except Exception:
        pass  # never block perception


def trace_stimmung_update(
    stance: str,
    health: float,
    resource_pressure: float,
    error_rate: float,
    throughput: float,
    perception_confidence: float,
    llm_cost: float,
    prev_stance: str = "",
) -> None:
    """Trace a stimmung collection cycle."""
    client = _get_langfuse()
    if client is None:
        return
    try:
        meta = {
            "stance": stance,
            "health": round(health, 3),
            "resource_pressure": round(resource_pressure, 3),
            "error_rate": round(error_rate, 3),
            "processing_throughput": round(throughput, 3),
            "perception_confidence": round(perception_confidence, 3),
            "llm_cost_pressure": round(llm_cost, 3),
        }
        with client.start_as_current_observation(
            as_type="span",
            name="stimmung.update",
            metadata=meta,
        ) as span:
            # Score the overall system health (inverted: 1.0 = healthy)
            worst = max(
                health, resource_pressure, error_rate, throughput, perception_confidence, llm_cost
            )
            span.score(name="system_health", value=round(1.0 - worst, 4), data_type="NUMERIC")

        # Log stance transition as a separate event
        if prev_stance and prev_stance != stance:
            hapax_event(
                "stimmung",
                "stance_change",
                metadata={"from": prev_stance, "to": stance},
                level="WARNING" if stance in ("degraded", "critical") else "DEFAULT",
            )
    except Exception:
        pass


def trace_visual_tick(
    display_state: str,
    signal_count: int,
    tick_interval: float,
    stimmung_stance: str,
    cache_hit: bool = False,
    scheduler_source: str = "",
) -> None:
    """Trace a visual state computation."""
    client = _get_langfuse()
    if client is None:
        return
    try:
        with client.start_as_current_observation(
            as_type="span",
            name="visual.tick",
            metadata={
                "display_state": display_state,
                "signal_count": signal_count,
                "tick_interval_s": round(tick_interval, 2),
                "stimmung_stance": stimmung_stance,
                "cache_hit": cache_hit,
                "scheduler_source": scheduler_source,
            },
        ) as span:
            span.score(
                name="visual_density", value=min(1.0, signal_count / 5.0), data_type="NUMERIC"
            )
    except Exception:
        pass


def trace_episode_closed(
    activity: str,
    duration_s: float,
    flow_state: str,
    snapshot_count: int,
    session_id: str | None = None,
) -> None:
    """Log an episode boundary as an event."""
    hapax_event(
        "experiential",
        "episode_closed",
        metadata={
            "activity": activity,
            "duration_s": round(duration_s, 1),
            "flow_state": flow_state,
            "snapshot_count": snapshot_count,
        },
        tags=[f"activity:{activity}", f"flow:{flow_state}"],
    )


def trace_phone_signals(
    signal_count: int,
    battery_pct: int,
    connected: bool,
    signals: list[str] | None = None,
) -> None:
    """Trace phone/KDEConnect signal generation."""
    if signal_count == 0 and not connected:
        return  # Skip when no phone data at all
    client = _get_langfuse()
    if client is None:
        return
    try:
        meta: dict[str, Any] = {
            "signal_count": signal_count,
            "battery_pct": battery_pct,
            "connected": connected,
        }
        if signals:
            meta["signal_titles"] = signals[:5]
        with client.start_as_current_observation(
            as_type="span",
            name="perception.phone",
            metadata=meta,
        ) as span:
            if battery_pct > 0 and battery_pct < 15:
                span.score(name="phone_battery_critical", value=1.0, data_type="NUMERIC")
    except Exception:
        pass


def trace_compositor_effect(
    preset: str,
    prev_preset: str = "",
) -> None:
    """Trace compositor effect preset change."""
    hapax_event(
        "visual",
        "effect_switch",
        metadata={"preset": preset, "prev_preset": prev_preset},
        tags=[f"effect:{preset}"],
    )


def trace_api_poll(
    endpoint: str,
    latency_ms: float,
    success: bool,
    status_code: int = 0,
) -> None:
    """Trace a cockpit API poll cycle (only logged when slow or failed)."""
    if success and latency_ms < 500:
        return  # Only trace slow or failed polls
    client = _get_langfuse()
    if client is None:
        return
    try:
        with client.start_as_current_observation(
            as_type="span",
            name=f"api.poll.{endpoint}",
            metadata={
                "endpoint": endpoint,
                "latency_ms": round(latency_ms, 1),
                "success": success,
                "status_code": status_code,
            },
        ) as span:
            span.score(name="api_latency", value=round(latency_ms / 1000, 4), data_type="NUMERIC")
    except Exception:
        pass


def trace_prediction_tick(
    predictions: int,
    cache_hit: bool,
    cache_hit_rate: float,
    surprise_max: float = 0.0,
) -> None:
    """Trace a prediction cycle."""
    client = _get_langfuse()
    if client is None:
        return
    try:
        with client.start_as_current_observation(
            as_type="span",
            name="prediction.tick",
            metadata={
                "prediction_count": predictions,
                "cache_hit": cache_hit,
                "cache_hit_rate": round(cache_hit_rate, 3),
                "surprise_max": round(surprise_max, 3),
            },
        ) as span:
            span.score(
                name="prediction_accuracy", value=round(cache_hit_rate, 4), data_type="NUMERIC"
            )
            if surprise_max > 0.5:
                span.score(name="surprise", value=round(surprise_max, 4), data_type="NUMERIC")
    except Exception:
        pass
