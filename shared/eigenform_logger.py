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
PERSISTENT_LOG = Path.home() / "hapax-state/research/eigenform-log.jsonl"
MAX_ENTRIES = 500  # ring buffer for SHM
PERSISTENT_MAX_ENTRIES = 50_000  # ~4 months at 3s tick rate


def _append_and_trim(line: str, path: Path, max_entries: int) -> None:
    """Append a JSONL line and trim if over 2x max_entries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
    try:
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        if len(lines) > max_entries * 2:
            trimmed = lines[-max_entries:]
            path.write_text("\n".join(trimmed) + "\n", encoding="utf-8")
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
    persistent_path: Path | None = PERSISTENT_LOG,
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
        "restriction_residual_rms": restriction_residual_rms,
    }
    line = json.dumps(entry) + "\n"
    _append_and_trim(line, path, MAX_ENTRIES)
    if persistent_path is not None:
        try:
            _append_and_trim(line, persistent_path, PERSISTENT_MAX_ENTRIES)
        except OSError:
            pass
