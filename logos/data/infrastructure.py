"""Infrastructure data collectors for the logos.

Reads from profiles/infra-snapshot.json written by the host-side health
monitor, which has access to Docker, systemd, and GPU. The logos-api
runs inside Docker where these commands are unavailable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from logos._config import PROFILES_DIR
from shared.working_mode import get_working_mode

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


@dataclass
class TimerStatus:
    unit: str
    next_fire: str
    last_fired: str
    activates: str


def _load_snapshot() -> dict:
    """Load the infra snapshot written by health monitor."""
    try:
        return json.loads(INFRA_SNAPSHOT.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


async def collect_docker() -> list[ContainerStatus]:
    """Read Docker container status from infra snapshot."""
    snapshot = _load_snapshot()
    return [
        ContainerStatus(
            name=c.get("name", ""),
            service=c.get("service", ""),
            state=c.get("state", "unknown"),
            health=c.get("health", ""),
        )
        for c in snapshot.get("containers", [])
    ]


async def collect_timers() -> list[TimerStatus]:
    """Read systemd timers from snapshot, compute container cron from working mode."""
    snapshot = _load_snapshot()

    # Systemd timers from snapshot (written by health monitor on host)
    timers = [
        TimerStatus(
            unit=t.get("unit", ""),
            next_fire=t.get("next_fire", "-"),
            last_fired=t.get("last_fired", "-"),
            activates=t.get("activates", t.get("unit", "")),
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
            )
        )

    return timers
