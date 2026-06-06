"""Infrastructure data collectors for the logos.

Reads from profiles/infra-snapshot.json written by the host-side health
monitor, which has access to Docker, systemd, and GPU. The logos-api
runs inside Docker where these commands are unavailable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from logos._config import PROFILES_DIR
from logos._working_mode import get_working_mode

INFRA_SNAPSHOT = PROFILES_DIR / "infra-snapshot.json"

# Container cron schedules by working mode — kept in sync with
# sync-pipeline/crontab.rnd and sync-pipeline/crontab.research
_CONTAINER_CRON: dict[str, dict[str, str]] = {
    "rnd": {
        "gdrive_sync": "15 */2 * * *",
        "gcalendar_sync": "*/30 * * * *",
        "gmail_sync": "5 * * * *",
        "youtube_sync": "30 */6 * * *",
        "claude_code_sync": "15 */2 * * *",
        "obsidian_sync": "10,40 * * * *",
        "chrome_sync": "20 * * * *",
    },
    "research": {
        "gdrive_sync": "15 */4 * * *",
        "gcalendar_sync": "0 */2 * * *",
        "gmail_sync": "5 */4 * * *",
        "youtube_sync": "30 */12 * * *",
        "claude_code_sync": "15 */4 * * *",
        "obsidian_sync": "0 */2 * * *",
        "chrome_sync": "20 */4 * * *",
    },
}


@dataclass
class ContainerStatus:
    name: str
    service: str
    state: str
    health: str
    image: str = ""
    ports: list[str] = field(default_factory=list)
    evidence_host: str | None = None
    evidence_machine_id: str | None = None
    evidence_class: str = "unknown"
    observed_at: str | None = None
    actual_host_witness: dict | None = None


@dataclass
class TimerStatus:
    unit: str
    next_fire: str
    last_fired: str
    activates: str
    evidence_host: str | None = None
    evidence_machine_id: str | None = None
    evidence_class: str = "unknown"
    observed_at: str | None = None
    actual_host_witness: dict | None = None


def _load_snapshot() -> dict:
    """Load the infra snapshot written by health monitor."""
    try:
        return json.loads(INFRA_SNAPSHOT.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _snapshot_observed_at(snapshot: dict) -> str | None:
    value = snapshot.get("observed_at") or snapshot.get("timestamp") or snapshot.get("updated_at")
    if isinstance(value, str) and value:
        return value
    try:
        return datetime.fromtimestamp(INFRA_SNAPSHOT.stat().st_mtime, tz=UTC).isoformat()
    except OSError:
        return None


def _snapshot_host(snapshot: dict) -> str | None:
    value = snapshot.get("evidence_host") or snapshot.get("hostname") or snapshot.get("host")
    return str(value) if value else None


def _snapshot_machine_id(snapshot: dict) -> str | None:
    value = snapshot.get("evidence_machine_id") or snapshot.get("machine_id")
    return str(value) if value else None


def _age_s(observed_at: str | None) -> int | None:
    if not observed_at:
        return None
    try:
        normalized = observed_at.replace("Z", "+00:00")
        observed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - observed).total_seconds()))


def _snapshot_witness(snapshot: dict) -> dict:
    observed_at = _snapshot_observed_at(snapshot)
    return {
        "source": "logos_infra",
        "evidence_host": _snapshot_host(snapshot),
        "evidence_machine_id": _snapshot_machine_id(snapshot),
        "observed_at": observed_at,
        "witness_age_s": _age_s(observed_at),
        "max_witness_age_s": 300,
    }


async def collect_docker() -> list[ContainerStatus]:
    """Read Docker container status from infra snapshot."""
    snapshot = _load_snapshot()
    witness = _snapshot_witness(snapshot)
    return [
        ContainerStatus(
            name=c.get("name", ""),
            service=c.get("service", ""),
            state=c.get("state", "unknown"),
            health=c.get("health", ""),
            image=c.get("image", ""),
            ports=c.get("ports", []),
            evidence_host=witness["evidence_host"],
            evidence_machine_id=witness["evidence_machine_id"],
            evidence_class="live" if witness["evidence_host"] else "unknown",
            observed_at=witness["observed_at"],
            actual_host_witness=witness,
        )
        for c in snapshot.get("containers", [])
    ]


async def collect_timers() -> list[TimerStatus]:
    """Read systemd timers from snapshot, compute container cron from working mode."""
    snapshot = _load_snapshot()
    witness = _snapshot_witness(snapshot)

    # Systemd timers from snapshot (written by health monitor on host)
    timers = [
        TimerStatus(
            unit=t.get("unit", ""),
            next_fire=t.get("next_fire", "-"),
            last_fired=t.get("last_fired", "-"),
            activates=t.get("activates", t.get("unit", "")),
            evidence_host=witness["evidence_host"],
            evidence_machine_id=witness["evidence_machine_id"],
            evidence_class="live" if witness["evidence_host"] else "unknown",
            observed_at=witness["observed_at"],
            actual_host_witness=witness,
        )
        for t in snapshot.get("timers", [])
        if t.get("type") != "container-cron"
    ]

    # Container cron jobs — computed live from current working mode
    mode = get_working_mode()
    cron_schedules = _CONTAINER_CRON.get(mode, _CONTAINER_CRON["rnd"])
    for agent, schedule in cron_schedules.items():
        timers.append(
            TimerStatus(
                unit=agent,
                next_fire=schedule,
                last_fired="-",
                activates=agent,
                evidence_host=witness["evidence_host"],
                evidence_machine_id=witness["evidence_machine_id"],
                evidence_class="derived" if witness["evidence_host"] else "unknown",
                observed_at=witness["observed_at"],
                actual_host_witness=witness,
            )
        )

    return timers
