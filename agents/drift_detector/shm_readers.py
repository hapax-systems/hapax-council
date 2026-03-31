"""Shared-memory state readers for stimmung, temporal, and apperception."""

from __future__ import annotations

import json
from pathlib import Path


def read_stimmung_block() -> str:
    """Read current system Stimmung from /dev/shm and format for prompt injection."""
    stimmung_path = Path("/dev/shm/hapax-stimmung/state.json")
    try:
        import time

        raw = json.loads(stimmung_path.read_text(encoding="utf-8"))
        ts = raw.get("timestamp", 0)
        if ts > 0 and (time.monotonic() - ts) > 300:
            return ""
        stance = raw.get("overall_stance", "nominal")
        if stance == "nominal":
            return ""

        try:
            from agents._stimmung import SystemStimmung

            stimmung = SystemStimmung.model_validate(raw)
            return (
                "System self-state (adjust behavior accordingly):\n" + stimmung.format_for_prompt()
            )
        except ImportError:
            return f"System self-state: stance={stance} (non-nominal)"
    except Exception:
        return ""


def read_temporal_block() -> str:
    """Read temporal bands from /dev/shm and format for prompt injection."""
    temporal_path = Path("/dev/shm/hapax-temporal/bands.json")
    try:
        import time

        raw = json.loads(temporal_path.read_text(encoding="utf-8"))
        ts = raw.get("timestamp", 0)
        if ts > 0 and (time.time() - ts) > 30:
            return ""

        xml = raw.get("xml", "")
        if not xml or xml == "<temporal_context>\n</temporal_context>":
            return ""

        max_surprise = raw.get("max_surprise", 0.0)
        preamble = (
            "Temporal context (retention = fading past, impression = vivid present, "
            "protention = anticipated near-future"
        )
        if max_surprise > 0.3:
            preamble += f", SURPRISE detected: {max_surprise:.2f}"
        preamble += "):"

        return preamble + "\n" + xml
    except Exception:
        return ""


from agents._apperception_shm import read_apperception_block  # noqa: F401
