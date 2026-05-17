"""Flow journal — persist flow state transitions to RAG for behavioral profiling.

Reads the live perception state file and writes daily flow transition
summaries to rag-sources/flow/. Each run appends new transitions since
the last sync. Designed to run on a 15-minute timer.

Flow state data feeds the energy_and_attention and creative_process
profile dimensions. Without this agent, flow state is ephemeral —
lost on daemon restart.

Run: uv run python -m agents.flow_journal
Timer: every 15 minutes via systemd
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

RAG_DIR = Path.home() / "documents" / "rag-sources" / "flow"
CACHE_DIR = Path.home() / ".cache" / "flow-journal"
STATE_FILE = CACHE_DIR / "state.json"
PERCEPTION_STATE = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
STIMMUNG_STATE = Path("/dev/shm/hapax-stimmung/state.json")

_FLOW_STATES = frozenset({"idle", "warming", "active", "deep", "flow", "blocked", "unknown"})
_ACTIVITY_MODES = frozenset(
    {"unknown", "idle", "coding", "research", "production", "meeting", "conversation", "away"}
)
_STIMMUNG_STANCES = frozenset({"unknown", "nominal", "seeking", "cautious", "degraded", "critical"})


def _allowed_label(value: object, *, allowed: frozenset[str], default: str) -> str:
    if not isinstance(value, str):
        return default
    label = value.strip().lower()
    return label if label in allowed else "other"


def _flow_state_label(value: object) -> str:
    return _allowed_label(value, allowed=_FLOW_STATES, default="idle")


def _activity_mode_label(value: object) -> str:
    return _allowed_label(value, allowed=_ACTIVITY_MODES, default="unknown")


def _stimmung_label(value: object) -> str:
    return _allowed_label(value, allowed=_STIMMUNG_STANCES, default="unknown")


def _score_band(value: object) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if score < 0.3:
        return "low"
    if score < 0.6:
        return "medium"
    if score < 0.8:
        return "high"
    return "very_high"


def _heart_rate_band(value: object) -> str:
    try:
        bpm = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if bpm <= 0:
        return "unknown"
    if bpm < 60:
        return "low"
    if bpm < 90:
        return "nominal"
    if bpm < 110:
        return "elevated"
    return "critical"


def _read_perception() -> dict | None:
    """Read current perception state (flow_state, activity_mode, etc.)."""
    try:
        data = json.loads(PERCEPTION_STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.warning("Cannot read perception state: %s", e)
        return None
    if not isinstance(data, dict):
        return None
    return data


def _read_stimmung() -> str:
    """Read current stimmung stance."""
    try:
        data = json.loads(STIMMUNG_STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    return data.get("overall_stance", "unknown")


def _default_state() -> dict:
    return {"last_flow_state": "idle", "last_activity_mode": "unknown", "transitions": []}


def _load_state() -> dict:
    """Load journal state (last known flow state, today's transitions)."""
    try:
        data = json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(data, dict):
        return _default_state()
    return data


def _save_state(state: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _today_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def sync() -> bool:
    """Check for flow state changes and record transitions."""
    perc = _read_perception()
    if perc is None:
        return False

    state = _load_state()
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    today = _today_str()

    # Detect flow state transition
    current_flow = _flow_state_label(perc.get("flow_state", "idle"))
    current_activity = _activity_mode_label(perc.get("activity_mode", "unknown"))
    last_flow = _flow_state_label(state.get("last_flow_state", "idle"))

    changed = False

    if current_flow != last_flow:
        transition = {
            "timestamp": now_iso,
            "from_state": last_flow,
            "to_state": current_flow,
            "flow_score_band": _score_band(perc.get("flow_score", 0.0)),
            "activity_mode": current_activity,
            "heart_rate_band": _heart_rate_band(perc.get("heart_rate_bpm", 0)),
            "stimmung_stance": _stimmung_label(_read_stimmung()),
        }
        state.setdefault("transitions", []).append(transition)
        state["last_flow_state"] = current_flow
        state["last_activity_mode"] = current_activity
        changed = True
        log.info("Flow transition recorded")

    # Write daily summary if we have transitions
    day_transitions = [t for t in state.get("transitions", []) if t["timestamp"].startswith(today)]
    if day_transitions:
        _write_daily_doc(today, day_transitions, current_flow, perc)

    if changed:
        _save_state(state)

    # Prune old transitions (keep last 7 days)
    from datetime import timedelta

    cutoff_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    state["transitions"] = [
        t for t in state.get("transitions", []) if t["timestamp"][:10] >= cutoff_date
    ]
    _save_state(state)

    return True


def _write_daily_doc(
    date_str: str, transitions: list[dict], current_state: str, perc: dict
) -> None:
    """Write or update the daily flow journal document."""
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    path = RAG_DIR / f"flow-{date_str}.md"
    current_state = _flow_state_label(current_state)

    # Compute time-in-state summary
    state_durations: dict[str, float] = {}
    for i, t in enumerate(transitions):
        if i + 1 < len(transitions):
            from datetime import datetime as dt

            start = dt.fromisoformat(t["timestamp"])
            end = dt.fromisoformat(transitions[i + 1]["timestamp"])
            dur_min = (end - start).total_seconds() / 60.0
            state_name = _flow_state_label(t.get("to_state"))
            state_durations[state_name] = state_durations.get(state_name, 0.0) + dur_min

    frontmatter = {
        "source_service": "flow_journal",
        "content_type": "flow_transitions",
        "timestamp": transitions[-1]["timestamp"],
        "modality_tags": ["behavioral", "temporal"],
        "date": date_str,
        "transition_count": len(transitions),
        "current_state": current_state,
    }

    lines = [
        f"---\n{yaml.dump(frontmatter, default_flow_style=False).strip()}\n---",
        f"# Flow Journal — {date_str}\n",
        f"**Current state:** {current_state}",
        f"**Transitions today:** {len(transitions)}\n",
    ]

    if state_durations:
        lines.append("## Time in State\n")
        for state_name, minutes in sorted(state_durations.items(), key=lambda x: -x[1]):
            lines.append(f"- **{state_name}:** {minutes:.0f} min")
        lines.append("")

    lines.append("## Transitions\n")
    for t in transitions:
        ts = t["timestamp"][11:16]  # HH:MM
        from_state = _flow_state_label(t.get("from_state"))
        to_state = _flow_state_label(t.get("to_state"))
        score_band = t.get("flow_score_band") or _score_band(t.get("flow_score", 0.0))
        activity_mode = _activity_mode_label(t.get("activity_mode"))
        heart_rate_band = t.get("heart_rate_band") or _heart_rate_band(t.get("heart_rate_bpm", 0))
        lines.append(
            f"- **{ts}** {from_state} -> {to_state} "
            f"(score_band={score_band}, "
            f"activity={activity_mode}, "
            f"hr_band={heart_rate_band})"
        )

    path.write_text("\n".join(lines) + "\n")
    log.info("Wrote flow journal: %s (%d transitions)", path.name, len(transitions))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sync():
        print("Flow journal synced.")
    else:
        print("Flow journal sync failed (no perception state).")
