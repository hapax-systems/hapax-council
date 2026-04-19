#!/usr/bin/env python3
"""hapax-heartbeat.py — Pi edge heartbeat reporter.

Collects system vitals and service status, writes JSON to workstation
state directory via HTTP POST. Runs every 60s via systemd timer.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time


def get_cpu_temp() -> float:
    """Read CPU temperature from thermal zone."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except (FileNotFoundError, ValueError):
        return 0.0


def get_memory_mb() -> tuple[int, int]:
    """Return (total_mb, available_mb) from /proc/meminfo."""
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])
    except (FileNotFoundError, ValueError):
        pass
    total = info.get("MemTotal", 0) // 1024
    available = info.get("MemAvailable", 0) // 1024
    return total, available


def get_disk_free_gb() -> float:
    """Return free disk space on root filesystem in GB."""
    try:
        stat = os.statvfs("/")
        return (stat.f_bavail * stat.f_frsize) / (1024**3)
    except OSError:
        return 0.0


def get_uptime_s() -> float:
    """Return system uptime in seconds."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (FileNotFoundError, ValueError):
        return 0.0


def get_service_status(services: list[str]) -> dict[str, str]:
    """Check systemd service status for each named service."""
    result = {}
    for svc in services:
        try:
            out = subprocess.run(
                ["systemctl", "is-active", svc],
                capture_output=True,
                text=True,
                timeout=5,
            )
            result[svc] = out.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            result[svc] = "unknown"
    return result


def build_heartbeat(role: str, services: list[str]) -> dict:
    """Build heartbeat JSON payload."""
    mem_total, mem_available = get_memory_mb()
    return {
        "hostname": socket.gethostname(),
        "last_seen_epoch": time.time(),
        "uptime_s": get_uptime_s(),
        "mem_total_mb": mem_total,
        "mem_available_mb": mem_available,
        "cpu_temp_c": get_cpu_temp(),
        "disk_free_gb": round(get_disk_free_gb(), 1),
        "services": get_service_status(services),
        "role": role,
        "checks_failed": [],
    }


def post_heartbeat(heartbeat: dict, workstation_url: str) -> bool:
    """POST heartbeat to workstation. Falls back to rsync if HTTP fails."""
    import urllib.request

    hostname = heartbeat["hostname"]
    url = f"{workstation_url}/api/pi/{hostname}/heartbeat"

    try:
        data = json.dumps(heartbeat).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        pass

    # Fallback: write to local file, rsync picks it up
    state_file = f"/tmp/{hostname}-heartbeat.json"
    with open(state_file, "w") as f:
        json.dump(heartbeat, f)

    try:
        subprocess.run(
            [
                "rsync",
                "-q",
                state_file,
                f"hapax@hapax-podium-2.local:hapax-state/edge/{hostname}.json",
            ],
            timeout=10,
            capture_output=True,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def main() -> None:
    role = os.environ.get("HEARTBEAT_ROLE", "ir-edge")
    services_str = os.environ.get("HEARTBEAT_SERVICES", "hapax-ir-edge")
    services = [s.strip() for s in services_str.split(",") if s.strip()]
    workstation = os.environ.get("WORKSTATION_URL", "http://hapax-podium-2.local:8051")

    heartbeat = build_heartbeat(role, services)
    success = post_heartbeat(heartbeat, workstation)

    if not success:
        print(f"Failed to send heartbeat for {heartbeat['hostname']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
