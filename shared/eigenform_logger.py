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
    consistency_radius: float = 0.0,
    path: Path = EIGENFORM_LOG,
) -> None:
    """Append state vector to JSONL log for eigenform analysis."""
    entry = {
        "t": time.time(),
        "presence": presence,
        "flow_score": flow_score,
        "audio_energy": audio_energy,
        "stimmung_stance": stimmung_stance,
        "imagination_salience": imagination_salience,
        "visual_brightness": visual_brightness,
        "heart_rate": heart_rate,
        "operator_stress": operator_stress,
        "activity": activity,
        "e_mesh": e_mesh,
        "consistency_radius": consistency_radius,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
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
