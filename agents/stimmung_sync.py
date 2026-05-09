"""Stimmung sync — persist system self-state history to RAG.

Reads /dev/shm/hapax-stimmung/state.json and writes daily summaries
of stance transitions and dimension readings to rag-sources/stimmung/.
Without this agent, stimmung state is ephemeral.

Enables queries like "How was system health this week?" and feeds
the energy_and_attention profile dimension via infrastructure context.

Run: uv run python -m agents.stimmung_sync
Timer: every 15 minutes via systemd
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

RAG_DIR = Path.home() / "documents" / "rag-sources" / "stimmung"
CACHE_DIR = Path.home() / ".cache" / "stimmung-sync"
STATE_FILE = CACHE_DIR / "state.json"
STIMMUNG_STATE = Path("/dev/shm/hapax-stimmung/state.json")

DIMENSION_NAMES = [
    "health",
    "resource_pressure",
    "error_rate",
    "processing_throughput",
    "perception_confidence",
    "llm_cost_pressure",
    "grounding_quality",
    "exploration_deficit",
    "audience_engagement",
    "operator_stress",
    "operator_energy",
    "physiological_coherence",
    "audio_signal_presence",
    "audio_spectral_centroid",
    "audio_spectral_balance",
    "audio_content_mix",
]


def _read_stimmung() -> dict | None:
    """Read current stimmung state.

    Validates the JSON root is a mapping. Downstream consumers in the
    sync loop call ``.get(...)`` on the returned value — a writer
    producing valid JSON whose root is null, a list, a string, or a
    number previously raised AttributeError out of the stimmung sync
    daemon. Same shape as the other recent SHM-read fixes.
    """
    try:
        data = json.loads(STIMMUNG_STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.warning("Cannot read stimmung state: %s", e)
        return None
    return data if isinstance(data, dict) else None


def _load_state() -> dict:
    """Load sync-state file as dict, or canonical default on failure.

    Same isinstance contract as :func:`_read_stimmung`. The default
    state object is the canonical schema the sync loop writes back,
    so a corrupt persist file gets overwritten on the next save.
    """
    default = {"last_stance": "unknown", "readings": []}
    try:
        data = json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default
    return data if isinstance(data, dict) else default


def _save_state(state: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _today_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def sync() -> bool:
    """Sample stimmung state and record stance transitions."""
    stimmung = _read_stimmung()
    if stimmung is None:
        return False

    state = _load_state()
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    today = _today_str()

    current_stance = stimmung.get("overall_stance", "unknown")
    last_stance = state.get("last_stance", "unknown")

    # Record a reading every sync (dimensions snapshot)
    reading = {
        "timestamp": now_iso,
        "stance": current_stance,
    }
    for dim in DIMENSION_NAMES:
        dim_data = stimmung.get(dim, {})
        if isinstance(dim_data, dict):
            reading[dim] = dim_data.get("value", 0.0)

    state.setdefault("readings", []).append(reading)

    if current_stance != last_stance:
        state.setdefault("transitions", []).append(
            {
                "timestamp": now_iso,
                "from_stance": last_stance,
                "to_stance": current_stance,
            }
        )
        state["last_stance"] = current_stance
        log.info("Stimmung transition: %s → %s", last_stance, current_stance)

    # Write atomic state to /dev/shm for DMN consumption
    from agents._sensor_protocol import emit_sensor_impingement, write_sensor_state

    write_sensor_state("stimmung", reading)

    # Emit impingement on stance transition OR significant dimension change
    last_reading = state["readings"][-2] if len(state["readings"]) >= 2 else {}
    significant = [
        dim
        for dim in reading
        if dim in DIMENSION_NAMES and abs(reading.get(dim, 0.0) - last_reading.get(dim, 0.0)) > 0.15
    ]
    if significant or current_stance != last_stance:
        changed = (["overall_stance"] if current_stance != last_stance else []) + significant
        emit_sensor_impingement("stimmung", "energy_and_attention", changed)

    # Write daily summary
    day_readings = [r for r in state["readings"] if r["timestamp"].startswith(today)]
    day_transitions = [t for t in state.get("transitions", []) if t["timestamp"].startswith(today)]
    if day_readings:
        _write_daily_doc(today, day_readings, day_transitions, current_stance)

    # Prune readings older than 7 days
    from datetime import timedelta

    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    state["readings"] = [r for r in state["readings"] if r["timestamp"][:10] >= cutoff]
    state["transitions"] = [
        t for t in state.get("transitions", []) if t["timestamp"][:10] >= cutoff
    ]

    _save_state(state)
    return True


def _write_daily_doc(
    date_str: str,
    readings: list[dict],
    transitions: list[dict],
    current_stance: str,
) -> None:
    """Write daily stimmung summary."""
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    path = RAG_DIR / f"stimmung-{date_str}.md"

    # Compute stance time distribution
    stance_counts: dict[str, int] = {}
    for r in readings:
        stance_counts[r["stance"]] = stance_counts.get(r["stance"], 0) + 1
    total = len(readings)

    # Compute dimension averages
    dim_avgs: dict[str, float] = {}
    for dim in DIMENSION_NAMES:
        values = [r.get(dim, 0.0) for r in readings if isinstance(r.get(dim), (int, float))]
        if values:
            dim_avgs[dim] = sum(values) / len(values)

    # Find worst dimension
    worst_dim = max(dim_avgs, key=dim_avgs.get) if dim_avgs else "none"

    frontmatter = {
        "source_service": "stimmung_sync",
        "content_type": "stimmung_daily",
        "timestamp": readings[-1]["timestamp"],
        "modality_tags": ["infrastructure", "temporal"],
        "date": date_str,
        "reading_count": total,
        "transition_count": len(transitions),
        "current_stance": current_stance,
        "worst_dimension": worst_dim,
    }

    lines = [
        f"---\n{yaml.dump(frontmatter, default_flow_style=False).strip()}\n---",
        f"# System Stimmung — {date_str}\n",
        f"**Current stance:** {current_stance}",
        f"**Readings today:** {total}",
        f"**Stance transitions:** {len(transitions)}",
        f"**Worst dimension:** {worst_dim} ({dim_avgs.get(worst_dim, 0):.3f} avg)\n",
    ]

    lines.append("## Stance Distribution\n")
    for stance, count in sorted(stance_counts.items(), key=lambda x: -x[1]):
        pct = (count / total) * 100
        lines.append(f"- **{stance}:** {pct:.0f}% ({count} readings)")

    lines.append("\n## Dimension Averages\n")
    for dim in DIMENSION_NAMES:
        avg = dim_avgs.get(dim, 0.0)
        bar = "█" * int(avg * 10) + "░" * (10 - int(avg * 10))
        lines.append(f"- **{dim}:** {avg:.3f} {bar}")

    if transitions:
        lines.append("\n## Transitions\n")
        for t in transitions:
            ts = t["timestamp"][11:16]
            lines.append(f"- **{ts}** {t['from_stance']} → {t['to_stance']}")

    path.write_text("\n".join(lines) + "\n")
    log.info("Wrote stimmung summary: %s (%d readings)", path.name, total)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sync():
        print("Stimmung synced.")
    else:
        print("Stimmung sync failed (no stimmung state).")
