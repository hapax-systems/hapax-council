"""Infrastructure snapshot writer for logos-api."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime

from .constants import AI_AGENTS_DIR, PROFILES_DIR
from .models import HealthReport, Status

log = logging.getLogger("agents.health_monitor")

INFRA_SNAPSHOT_FILE = PROFILES_DIR / "infra-snapshot.json"

_SYSTEM_TIMERS = {"pop-upgrade-notify", "launchpadlib-cache-clean"}


def _collect_all_timers() -> list[dict]:
    """Query systemd for all hapax user timers with schedule data."""
    timers: list[dict] = []
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-timers", "--all", "--no-pager", "--output=json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            for entry in json.loads(result.stdout):
                unit = entry.get("unit", "")
                bare_name = unit.removesuffix(".timer")
                if bare_name in _SYSTEM_TIMERS:
                    continue
                activates = entry.get("activates", "")
                next_us = entry.get("next", 0)
                last_us = entry.get("last", 0)
                next_fire = (
                    datetime.fromtimestamp(next_us / 1_000_000, tz=UTC).isoformat()
                    if next_us
                    else "-"
                )
                last_fired = (
                    datetime.fromtimestamp(last_us / 1_000_000, tz=UTC).isoformat()
                    if last_us
                    else "-"
                )
                timers.append(
                    {
                        "unit": unit.removesuffix(".timer"),
                        "type": "systemd",
                        "activates": activates,
                        "status": "active" if next_us else "inactive",
                        "next_fire": next_fire,
                        "last_fired": last_fired,
                    }
                )
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        log.debug("Timer collection failed, falling back to unit files: %s", e)

    if not timers:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "list-timers", "--all", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines()[1:]:
                    if not line.strip() or line.startswith(" ") and "timers listed" in line:
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        unit = next((p for p in parts if p.endswith(".timer")), None)
                        if unit and unit.removesuffix(".timer") not in _SYSTEM_TIMERS:
                            next_str = " ".join(parts[:3]) if parts[0] != "-" else "-"
                            timers.append(
                                {
                                    "unit": unit.removesuffix(".timer"),
                                    "type": "systemd",
                                    "status": "active" if parts[0] != "-" else "inactive",
                                    "next_fire": next_str,
                                    "last_fired": "-",
                                }
                            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return timers


def write_infra_snapshot(report: HealthReport) -> None:
    """Write infrastructure snapshot for logos-api container to read."""
    containers: list[dict] = []
    gpu: dict | None = None

    for group in report.groups:
        for check in group.checks:
            name = check.name

            if name.startswith("docker.") and name not in (
                "docker.daemon",
                "docker.compose_file",
                "docker.containers",
                "docker.agents_compose",
                "docker.agents_containers",
            ):
                service = name.split(".", 1)[1]
                raw_health = check.message.lower()
                if "healthy" in raw_health:
                    health = "healthy"
                elif "unhealthy" in raw_health:
                    health = "unhealthy"
                elif "starting" in raw_health:
                    health = "starting"
                else:
                    health = check.message
                containers.append(
                    {
                        "service": service,
                        "name": service,
                        "state": "running" if check.status == Status.HEALTHY else "not running",
                        "health": health,
                    }
                )

            elif name == "gpu.vram":
                msg = check.message
                loaded_models: list[str] = []
                if check.detail and "Loaded Ollama models:" in check.detail:
                    loaded_models = [m.strip() for m in check.detail.split(":", 1)[1].split(",")]
                try:
                    nums = re.findall(r"(\d+)\s*MiB", msg)
                    used = int(nums[0])
                    total = int(nums[1])
                    gpu = {
                        "used_mb": used,
                        "total_mb": total,
                        "free_mb": total - used,
                        "loaded_models": loaded_models,
                        "message": msg,
                    }
                except (ValueError, IndexError):
                    gpu = {"message": msg, "loaded_models": loaded_models}

    timers = _collect_all_timers()

    from agents._working_mode import get_working_mode

    wmode = get_working_mode()
    crontab = AI_AGENTS_DIR / "sync-pipeline" / f"crontab.{wmode}"
    if not crontab.exists():
        crontab = AI_AGENTS_DIR / "sync-pipeline" / "crontab.rnd"
    if crontab.exists():
        for line in crontab.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 6:
                schedule = " ".join(parts[:5])
                agent = parts[-1].rsplit("/", 1)[-1] if "/" in parts[-1] else parts[-1]
                timers.append(
                    {
                        "unit": agent,
                        "type": "container-cron",
                        "schedule": schedule,
                        "status": "active",
                        "next_fire": schedule,
                        "last_fired": "-",
                    }
                )

    snapshot = {
        "timestamp": report.timestamp,
        "working_mode": wmode,
        "containers": containers,
        "timers": timers,
        "gpu": gpu,
    }

    try:
        fd, tmp = tempfile.mkstemp(dir=PROFILES_DIR, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(snapshot, f)
        os.replace(tmp, INFRA_SNAPSHOT_FILE)
    except Exception as e:
        log.warning("Failed to write infra snapshot: %s", e)
