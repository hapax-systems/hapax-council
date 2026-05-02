"""M8 firmware/hardware ingest from m8c-hapax SHM sidecar.

Reads `/dev/shm/hapax-sources/m8-info.json` (written by the m8c-hapax
carry-fork on each system_info packet) and surfaces M8 hardware id +
installed firmware version as a health row. When a staged firmware
update record exists at `relay/coordination/*-m8-firmware-update-staged.md`
and its version differs from the installed version, the row goes
DEGRADED so the operator notices the unblocker.

cc-task: m8-system-info-firmware-ingest
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group

_INFO_PATH = Path("/dev/shm/hapax-sources/m8-info.json")
_RELAY_DIR = Path.home() / ".cache" / "hapax" / "relay" / "coordination"
_STAGED_RE = re.compile(r"m8-firmware-update-staged.*\.(?:md|yaml)$")
_FW_RE = re.compile(r"\b(\d+)\.(\d+)\.(\d+)\b")


def _read_installed_firmware() -> dict | None:
    if not _INFO_PATH.exists():
        return None
    try:
        return json.loads(_INFO_PATH.read_text())
    except (OSError, ValueError):
        return None


def _read_staged_firmware() -> str | None:
    """Scan relay coordination dir for a staged-firmware record.

    Returns the X.Y.Z firmware string from the most recent staged
    record, or None if nothing is staged.
    """
    if not _RELAY_DIR.is_dir():
        return None
    candidates = sorted(
        (p for p in _RELAY_DIR.iterdir() if _STAGED_RE.search(p.name)),
        reverse=True,
    )
    for path in candidates:
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        match = _FW_RE.search(text)
        if match:
            return ".".join(match.groups())
    return None


@check_group("m8")
async def check_m8_firmware() -> list[CheckResult]:
    """Surface M8 firmware version + staged-vs-installed drift."""
    t = time.monotonic()
    info = _read_installed_firmware()
    if info is None:
        return [
            CheckResult(
                name="m8.firmware",
                group="m8",
                status=Status.HEALTHY,
                message="no M8 connected (sidecar absent)",
                duration_ms=_u._timed(t),
            )
        ]

    installed = info.get("firmware") or "unknown"
    hardware_name = info.get("hardware_name") or "Unknown"
    staged = _read_staged_firmware()

    if staged and staged != installed:
        return [
            CheckResult(
                name="m8.firmware",
                group="m8",
                status=Status.DEGRADED,
                message=(
                    f"{hardware_name} installed={installed} "
                    f"staged={staged} (operator-physical update pending)"
                ),
                duration_ms=_u._timed(t),
            )
        ]

    return [
        CheckResult(
            name="m8.firmware",
            group="m8",
            status=Status.HEALTHY,
            message=f"{hardware_name} firmware {installed}",
            duration_ms=_u._timed(t),
        )
    ]
