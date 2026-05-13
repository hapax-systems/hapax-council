"""Shared appsrc queue bounds for live compositor producer paths."""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_LIVE_APPSRC_MAX_BUFFERS = 2
DEFAULT_LIVE_APPSRC_MAX_BYTES = 0
DEFAULT_LIVE_APPSRC_MAX_TIME = 0


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("Invalid %s=%r; using %d", name, raw, default)
        return default
    return max(0, value)


def _downstream_leaky_value() -> Any:
    try:
        import gi

        gi.require_version("GstApp", "1.0")
        from gi.repository import GstApp  # type: ignore[import-not-found]

        return GstApp.AppLeakyType.DOWNSTREAM
    except Exception:
        return 2


def _set_optional_property(element: Any, name: str, value: Any) -> bool:
    try:
        element.set_property(name, value)
    except Exception:
        log.debug("appsrc property not supported: %s", name, exc_info=True)
        return False
    return True


def configure_live_appsrc_queue(element: Any) -> None:
    """Bound appsrc's internal queue without making producer threads block.

    Live compositor appsrc producers should drop stale frames rather than
    retain an unbounded backlog. ``max-buffers`` is the primary bound;
    ``leaky-type=downstream`` keeps the newest frame when downstream is slow.
    Unsupported properties are ignored because distro GStreamer versions vary.
    """

    max_buffers = _env_int("HAPAX_LIVE_APPSRC_MAX_BUFFERS", DEFAULT_LIVE_APPSRC_MAX_BUFFERS)
    max_bytes = _env_int("HAPAX_LIVE_APPSRC_MAX_BYTES", DEFAULT_LIVE_APPSRC_MAX_BYTES)
    max_time = _env_int("HAPAX_LIVE_APPSRC_MAX_TIME", DEFAULT_LIVE_APPSRC_MAX_TIME)

    _set_optional_property(element, "block", False)
    _set_optional_property(element, "max-buffers", max_buffers)
    _set_optional_property(element, "max-bytes", max_bytes)
    _set_optional_property(element, "max-time", max_time)
    _set_optional_property(element, "leaky-type", _downstream_leaky_value())
