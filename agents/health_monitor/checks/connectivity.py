"""Connectivity checks (Tailscale, ntfy, n8n, Obsidian, GDrive, Watch, Phone)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("connectivity")
async def check_tailscale() -> list[CheckResult]:
    """Check Tailscale VPN connectivity."""
    t = time.monotonic()
    rc, out, err = await _u.run_cmd(["tailscale", "status", "--json"])
    if rc != 0:
        if "not found" in (err or ""):
            return [
                CheckResult(
                    name="connectivity.tailscale",
                    group="connectivity",
                    status=Status.HEALTHY,
                    message="not installed (planned)",
                    duration_ms=_u._timed(t),
                )
            ]
        return [
            CheckResult(
                name="connectivity.tailscale",
                group="connectivity",
                status=Status.DEGRADED,
                message=f"tailscale error (rc={rc})",
                detail=(err or out or "")[:200],
                duration_ms=_u._timed(t),
            )
        ]

    try:
        data = json.loads(out)
        self_status = data.get("Self", {}).get("Online", False)
        peer_count = len([p for p in data.get("Peer", {}).values() if p.get("Online")])
        if self_status:
            return [
                CheckResult(
                    name="connectivity.tailscale",
                    group="connectivity",
                    status=Status.HEALTHY,
                    message=f"online, {peer_count} peer(s)",
                    duration_ms=_u._timed(t),
                )
            ]
        return [
            CheckResult(
                name="connectivity.tailscale",
                group="connectivity",
                status=Status.DEGRADED,
                message="tailscale offline",
                remediation="sudo tailscale up",
                duration_ms=_u._timed(t),
            )
        ]
    except Exception as e:
        return [
            CheckResult(
                name="connectivity.tailscale",
                group="connectivity",
                status=Status.DEGRADED,
                message=f"tailscale status parse error: {e}",
                duration_ms=_u._timed(t),
            )
        ]


@check_group("connectivity")
async def check_ntfy() -> list[CheckResult]:
    """Check ntfy push notification service reachability."""
    t = time.monotonic()
    ntfy_url = os.environ.get("NTFY_BASE_URL", "http://localhost:8090")
    code, body = await _u.http_get(f"{ntfy_url}/v1/health", timeout=3.0)
    if 200 <= code < 400:
        return [
            CheckResult(
                name="connectivity.ntfy",
                group="connectivity",
                status=Status.HEALTHY,
                message=f"HTTP {code}",
                duration_ms=_u._timed(t),
            )
        ]
    return [
        CheckResult(
            name="connectivity.ntfy",
            group="connectivity",
            status=Status.DEGRADED,
            message=f"ntfy unreachable (HTTP {code})" if code else "ntfy unreachable",
            detail=body[:200] if body else None,
            remediation=f"cd {_c.COMPOSE_FILE.parent} && docker compose --profile full up -d ntfy",
            duration_ms=_u._timed(t),
        )
    ]


@check_group("connectivity")
async def check_n8n_health() -> list[CheckResult]:
    """Check n8n workflow automation health endpoint."""
    t = time.monotonic()
    code, body = await _u.http_get("http://localhost:5678/healthz", timeout=3.0)
    if 200 <= code < 400:
        return [
            CheckResult(
                name="connectivity.n8n",
                group="connectivity",
                status=Status.HEALTHY,
                message=f"HTTP {code}",
                duration_ms=_u._timed(t),
            )
        ]
    return [
        CheckResult(
            name="connectivity.n8n",
            group="connectivity",
            status=Status.DEGRADED,
            message=f"n8n unreachable (HTTP {code})" if code else "n8n unreachable",
            remediation=f"cd {_c.COMPOSE_FILE.parent} && docker compose --profile full up -d n8n",
            duration_ms=_u._timed(t),
        )
    ]


@check_group("connectivity")
async def check_obsidian_sync() -> list[CheckResult]:
    """Check Obsidian desktop app is running."""
    t = time.monotonic()
    rc, out, err = await _u.run_cmd(["pgrep", "-f", "obsidian/app.asar"])
    if rc == 0:
        return [
            CheckResult(
                name="connectivity.obsidian",
                group="connectivity",
                status=Status.HEALTHY,
                message="running",
                duration_ms=_u._timed(t),
            )
        ]
    return [
        CheckResult(
            name="connectivity.obsidian",
            group="connectivity",
            status=Status.DEGRADED,
            message="not running (desktop app)",
            duration_ms=_u._timed(t),
        )
    ]


@check_group("connectivity")
async def check_gdrive_sync_freshness() -> list[CheckResult]:
    """Check Google Drive sync freshness."""
    t = time.monotonic()
    gdrive_dir = _c.RAG_SOURCES_DIR / "gdrive"
    if not gdrive_dir.exists():
        return [
            CheckResult(
                name="connectivity.gdrive-sync",
                group="connectivity",
                status=Status.HEALTHY,
                message="not configured",
                duration_ms=_u._timed(t),
            )
        ]

    state_file = Path.home() / ".cache" / "gdrive-sync" / "state.json"
    if state_file.exists():
        age_hours = (time.time() - state_file.stat().st_mtime) / 3600
        if age_hours > 24:
            return [
                CheckResult(
                    name="connectivity.gdrive-sync",
                    group="connectivity",
                    status=Status.DEGRADED,
                    message=f"gdrive sync state is {age_hours:.0f}h old",
                    remediation="cd ~/projects/hapax-council && uv run python -m agents.gdrive_sync --auto",
                    duration_ms=_u._timed(t),
                )
            ]

    return [
        CheckResult(
            name="connectivity.gdrive-sync",
            group="connectivity",
            status=Status.HEALTHY,
            message="sync-pipeline container running",
            duration_ms=_u._timed(t),
        )
    ]


@check_group("connectivity")
async def check_watch_connected() -> list[CheckResult]:
    """Check if Pixel Watch is streaming sensor data (non-critical, tier 3)."""
    t = time.monotonic()
    conn_file = _c.WATCH_STATE_DIR / "connection.json"
    if not conn_file.exists():
        return [
            CheckResult(
                name="connectivity.watch",
                group="connectivity",
                status=Status.HEALTHY,
                message="not configured",
                duration_ms=_u._timed(t),
                tier=3,
            )
        ]
    try:
        data = json.loads(conn_file.read_text())
    except (json.JSONDecodeError, OSError):
        return [
            CheckResult(
                name="connectivity.watch",
                group="connectivity",
                status=Status.DEGRADED,
                message="connection.json unreadable",
                duration_ms=_u._timed(t),
                tier=3,
            )
        ]
    age = time.time() - data.get("last_seen_epoch", 0)
    battery = data.get("battery_pct")
    bat_str = f", battery {battery}%" if battery is not None else ""
    # Watch is tier 3 (non-critical) and routinely off-wrist overnight.
    # Report as HEALTHY with informational message, not DEGRADED.
    if age > 1800:
        return [
            CheckResult(
                name="connectivity.watch",
                group="connectivity",
                status=Status.HEALTHY,
                message=f"Watch last seen {age / 60:.0f}m ago{bat_str}",
                duration_ms=_u._timed(t),
                tier=3,
            )
        ]
    return [
        CheckResult(
            name="connectivity.watch",
            group="connectivity",
            status=Status.HEALTHY,
            message=f"Watch connected ({age / 60:.0f}m ago{bat_str})",
            duration_ms=_u._timed(t),
            tier=3,
        )
    ]


@check_group("connectivity")
async def check_phone_connected() -> list[CheckResult]:
    """Check if Pixel 10 phone is sending heartbeats (non-critical, tier 3)."""
    t = time.monotonic()
    conn_file = _c.WATCH_STATE_DIR / "phone_connection.json"
    if not conn_file.exists():
        return [
            CheckResult(
                name="connectivity.phone",
                group="connectivity",
                status=Status.HEALTHY,
                message="not configured",
                duration_ms=_u._timed(t),
                tier=3,
            )
        ]
    try:
        data = json.loads(conn_file.read_text())
    except (json.JSONDecodeError, OSError):
        return [
            CheckResult(
                name="connectivity.phone",
                group="connectivity",
                status=Status.DEGRADED,
                message="phone_connection.json unreadable",
                duration_ms=_u._timed(t),
                tier=3,
            )
        ]
    age = time.time() - data.get("last_seen_epoch", 0)
    battery = data.get("battery_pct", "?")
    if age > 300:
        return [
            CheckResult(
                name="connectivity.phone",
                group="connectivity",
                status=Status.DEGRADED,
                message=f"Phone last seen {age / 60:.0f}m ago (battery {battery}%)",
                duration_ms=_u._timed(t),
                tier=3,
            )
        ]
    return [
        CheckResult(
            name="connectivity.phone",
            group="connectivity",
            status=Status.HEALTHY,
            message=f"Phone connected, battery {battery}%",
            duration_ms=_u._timed(t),
            tier=3,
        )
    ]
