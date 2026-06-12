"""State vector logger for eigenform convergence analysis.

Logs the coupled operator-system state vector to a JSONL file at each
observation point, enabling offline analysis of T(x) convergence,
orbit detection, and divergence identification.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

EIGENFORM_LOG = Path("/dev/shm/hapax-eigenform/state-log.jsonl")
MAX_ENTRIES = 500  # ring buffer in JSONL
SENSITIVE_NUMERIC_FIELDS = ("heart_rate", "operator_stress")

_STIMMUNG_STANCES = frozenset({"nominal", "seeking", "cautious", "degraded", "critical"})
_ACTIVITIES = frozenset(
    {"idle", "unknown", "coding", "research", "production", "meeting", "conversation", "speaking"}
)


def _safe_label(value: str, *, allowed: frozenset[str], default: str) -> str:
    label = value.strip().lower()
    return label if label in allowed else default


PERSISTENT_LOG = Path.home() / "hapax-state/research/eigenform-log.jsonl"
MAX_PERSISTENT_ENTRIES = 50_000


def _append_and_trim(
    entry: dict, path: Path = PERSISTENT_LOG, max_entries: int = MAX_PERSISTENT_ENTRIES
) -> None:
    """Append *entry* to a persistent JSONL ring buffer on disk."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # jsonl-rotation: exempt(inline ring buffer; max_entries rewrite caps retained rows)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        if len(lines) > max_entries * 2:
            path.write_text("\n".join(lines[-max_entries:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def log_state_vector(
    *,
    presence: float = 0.0,
    flow_score: float = 0.0,
    audio_energy: float = 0.0,
    stimmung_stance: str = "nominal",
    imagination_salience: float = 0.0,
    visual_brightness: float = 0.0,
    heart_rate: float = 0.0,
    operator_stress: float = 0.0,
    activity: str = "idle",
    e_mesh: float = 1.0,
    restriction_residual_rms: float = 0.0,
    path: Path = EIGENFORM_LOG,
) -> None:
    """Append state vector to JSONL log for eigenform analysis."""
    entry = {
        "t": time.time(),
        "presence": presence,
        "flow_score": flow_score,
        "audio_energy": audio_energy,
        "stimmung_stance": _safe_label(
            stimmung_stance,
            allowed=_STIMMUNG_STANCES,
            default="nominal",
        ),
        "imagination_salience": imagination_salience,
        "visual_brightness": visual_brightness,
        "heart_rate": 0.0,
        "operator_stress": 0.0,
        "activity": _safe_label(activity, allowed=_ACTIVITIES, default="unknown"),
        "e_mesh": e_mesh,
        "restriction_residual_rms": restriction_residual_rms,
        "sensitive_fields_redacted": list(SENSITIVE_NUMERIC_FIELDS),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # jsonl-rotation: exempt(inline ring buffer; MAX_ENTRIES rewrite caps tmpfs file)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    # Trim to MAX_ENTRIES (read all, keep last N, rewrite)
    try:
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        if len(lines) > MAX_ENTRIES * 2:  # only trim when 2x over
            trimmed = lines[-MAX_ENTRIES:]
            path.write_text("\n".join(trimmed) + "\n", encoding="utf-8")
    except OSError:
        pass

    # Persistent disk log (50K ring buffer for long-term convergence analysis)
    _append_and_trim(entry)
