"""Read apperception state from /dev/shm for prompt injection.

Zero external dependencies — stdlib only (json, time, pathlib).
Safe to import from any module (shared/, agents/, logos/) without
config coupling. This is the canonical implementation; do not duplicate.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

APPERCEPTION_SHM_PATH = Path("/dev/shm/hapax-apperception/self-band.json")
_STALENESS_THRESHOLD = 30  # seconds


def read_apperception_block(path: Path = APPERCEPTION_SHM_PATH) -> str:
    """Read self-band state from /dev/shm and format for prompt injection.

    Returns formatted text block for LLM system prompts. Returns empty
    string if data is missing, stale (>30s), or has no meaningful content.

    Args:
        path: Override for testing. Defaults to /dev/shm path.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        ts = raw.get("timestamp", 0)
        if ts > 0 and (time.time() - ts) > _STALENESS_THRESHOLD:
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
            "Self-awareness (apperceptive self-observations \u2014 "
            "what I notice about my own processing):"
        ]

        if coherence < 0.4:
            lines.append(
                f"  \u26a0 Self-coherence low ({coherence:.2f}) \u2014 "
                "rebuilding self-model, expect uncertainty"
            )

        if dimensions:
            lines.append("  Self-dimensions:")
            for name, dim in sorted(dimensions.items()):
                conf = dim.get("confidence", 0.5)
                affirm = dim.get("affirming_count", 0)
                prob = dim.get("problematizing_count", 0)
                desc = f"    {name}: confidence={conf:.2f} (+{affirm}/-{prob})"
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
