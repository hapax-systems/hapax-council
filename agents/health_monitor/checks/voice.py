"""Voice daemon health checks."""

from __future__ import annotations

import os
import time
from pathlib import Path

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


def _voice_socket_path() -> str:
    """Return expected path for the hapax-daimonion hotkey socket."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return f"{runtime_dir}/hapax-daimonion.sock"


@check_group("voice")
async def check_voice_services() -> list[CheckResult]:
    """Check voice daemon is running and PipeWire is active."""
    results: list[CheckResult] = []
    t = time.monotonic()

    voice_active = False

    try:
        import httpx

        resp = httpx.get("http://localhost:9080/processes", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            for _key, procs in data.items():
                for p in procs:
                    if p.get("name") == "voice" and p.get("status") == "Running":
                        voice_active = True
                        break
    except Exception:
        pass

    if not voice_active:
        rc, out, _err = await _u.run_cmd(
            ["systemctl", "--user", "is-active", "hapax-daimonion.service"]
        )
        voice_active = out.strip() == "active"

    results.append(
        CheckResult(
            name="voice.daemon",
            group="voice",
            status=Status.HEALTHY if voice_active else Status.FAILED,
            message="running" if voice_active else "not running",
            remediation="process-compose process restart voice --port 9080"
            if not voice_active
            else None,
            duration_ms=_u._timed(t),
        )
    )

    t = time.monotonic()
    rc, out, _err = await _u.run_cmd(["systemctl", "--user", "is-active", "pipewire.service"])
    pw_active = out.strip() == "active"
    results.append(
        CheckResult(
            name="voice.pipewire",
            group="voice",
            status=Status.HEALTHY if pw_active else Status.FAILED,
            message="active" if pw_active else (out.strip() or "inactive"),
            remediation="systemctl --user restart pipewire" if not pw_active else None,
            duration_ms=_u._timed(t),
        )
    )

    return results


@check_group("voice")
async def check_voice_socket() -> list[CheckResult]:
    """Check the hotkey Unix socket exists."""
    t = time.monotonic()
    sock_path = _voice_socket_path()

    if Path(sock_path).exists():
        return [
            CheckResult(
                name="voice.hotkey_socket",
                group="voice",
                status=Status.HEALTHY,
                message=f"socket exists at {sock_path}",
                duration_ms=_u._timed(t),
            )
        ]
    return [
        CheckResult(
            name="voice.hotkey_socket",
            group="voice",
            status=Status.DEGRADED,
            message=f"socket not found at {sock_path}",
            detail="Hotkey commands will not work until daemon creates the socket",
            remediation="systemctl --user restart hapax-daimonion",
            duration_ms=_u._timed(t),
        )
    ]


@check_group("voice")
async def check_voice_vram_lock() -> list[CheckResult]:
    """Check VRAM lockfile isn't stale."""
    t = time.monotonic()

    if not _c.VOICE_VRAM_LOCK.exists():
        return [
            CheckResult(
                name="voice.vram_lock",
                group="voice",
                status=Status.HEALTHY,
                message="no lock held",
                duration_ms=_u._timed(t),
            )
        ]

    try:
        pid = int(_c.VOICE_VRAM_LOCK.read_text().strip())
        os.kill(pid, 0)
        return [
            CheckResult(
                name="voice.vram_lock",
                group="voice",
                status=Status.HEALTHY,
                message=f"lock held by PID {pid} (alive)",
                duration_ms=_u._timed(t),
            )
        ]
    except PermissionError:
        return [
            CheckResult(
                name="voice.vram_lock",
                group="voice",
                status=Status.HEALTHY,
                message=f"lock held by PID {pid} (alive, different user)",
                duration_ms=_u._timed(t),
            )
        ]
    except (ValueError, ProcessLookupError, OSError):
        return [
            CheckResult(
                name="voice.vram_lock",
                group="voice",
                status=Status.DEGRADED,
                message="stale VRAM lockfile (holder process dead)",
                detail=f"Lock at {_c.VOICE_VRAM_LOCK}",
                remediation=f"rm {_c.VOICE_VRAM_LOCK}",
                duration_ms=_u._timed(t),
            )
        ]
