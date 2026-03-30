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
            from shared.stimmung import SystemStimmung

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


def read_apperception_block() -> str:
    """Read self-band state from /dev/shm and format for prompt injection."""
    apperception_path = Path("/dev/shm/hapax-apperception/self-band.json")
    try:
        import time

        raw = json.loads(apperception_path.read_text(encoding="utf-8"))
        ts = raw.get("timestamp", 0)
        if ts > 0 and (time.time() - ts) > 30:
            return ""

        model = raw.get("self_model", {})
        dimensions = model.get("dimensions", {})
        observations = model.get("recent_observations", [])
        reflections = model.get("recent_reflections", [])
        coherence = model.get("coherence", 0.7)
        pending_actions = raw.get("pending_actions", [])

        if not dimensions and not observations:
            return ""

        lines: list[str] = [
            "Self-awareness (apperceptive self-observations -- "
            "what I notice about my own processing):"
        ]

        if coherence < 0.4:
            lines.append(
                f"  Self-coherence low ({coherence:.2f}) -- "
                "rebuilding self-model, expect uncertainty"
            )

        if dimensions:
            lines.append("  Self-dimensions:")
            for name, dim in sorted(dimensions.items()):
                conf = dim.get("confidence", 0.5)
                assessment = dim.get("current_assessment", "")
                affirm = dim.get("affirming_count", 0)
                prob = dim.get("problematizing_count", 0)
                desc = f"    {name}: confidence={conf:.2f} (+{affirm}/-{prob})"
                if assessment:
                    desc += f" -- {assessment}"
                lines.append(desc)

        if observations:
            recent = observations[-5:]
            lines.append("  Recent self-observations:")
            for obs in recent:
                lines.append(f"    - {obs}")

        if reflections:
            recent_ref = reflections[-3:]
            lines.append("  Reflections:")
            for ref in recent_ref:
                lines.append(f"    - {ref}")

        if pending_actions:
            lines.append("  Pending self-actions:")
            for action in pending_actions[:3]:
                lines.append(f"    - {action}")

        return "\n".join(lines)
    except Exception:
        return ""
