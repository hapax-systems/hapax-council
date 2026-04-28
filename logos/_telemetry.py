"""Vendored telemetry for the logos package.

Domain-aware Langfuse instrumentation for circulatory system traces/spans/events.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

log = logging.getLogger("hapax.telemetry")

try:
    from shared.langfuse_logging import install_langfuse_exporter_noise_filter

    install_langfuse_exporter_noise_filter()
except Exception:
    pass

_langfuse = None
_available: bool | None = None
_LANGFUSE_ENV_FILE = Path.home() / ".cache" / "hapax" / "langfuse-env"


def _apply_langfuse_environment() -> None:
    if "LANGFUSE_TRACING_ENVIRONMENT" in os.environ:
        return
    try:
        env = _LANGFUSE_ENV_FILE.read_text().strip()
        if env:
            os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = env
    except FileNotFoundError:
        pass


def _get_langfuse():
    global _langfuse, _available  # noqa: PLW0603
    if _available is False:
        return None
    if _langfuse is not None:
        return _langfuse
    try:
        _apply_langfuse_environment()
        from langfuse import get_client

        _langfuse = get_client()
        _available = True
        return _langfuse
    except Exception:
        _available = False
        log.debug("Langfuse client not available", exc_info=True)
        return None


def _system_tags(system: str, extra_tags: list[str] | None = None) -> list[str]:
    tags = [f"system:{system}"]
    if extra_tags:
        tags.extend(extra_tags)
    return tags


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
    client = _get_langfuse()
    if client is None:
        return

    full_name = f"{system}.{name}"
    event_metadata = {
        "event_kind": "hapax_event",
        "event_system": system,
        "event_name": name,
        **(metadata or {}),
    }
    try:
        from langfuse import propagate_attributes

        with propagate_attributes(tags=_system_tags(system, tags), metadata=event_metadata):
            # Langfuse 3.x no longer accepts as_type="event" here. Represent
            # point-in-time events as short spans to avoid SDK fallback warnings.
            with client.start_as_current_observation(
                as_type="span",
                name=full_name,
                metadata=event_metadata,
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


def trace_compositor_effect(
    preset: str,
    prev_preset: str = "",
) -> None:
    hapax_event(
        "visual",
        "effect_switch",
        metadata={"preset": preset, "prev_preset": prev_preset},
        tags=[f"effect:{preset}"],
    )
