"""Ghost-release detector: live processes bound to deleted source-activation releases.

The release-GC ghost (audit 2026-06-11, F1): logos-api kept executing from a
release dir under .../source-activation/releases/ for ~2.5 days after the dir
was deleted on disk, 500ing every lazy import unalerted. This probe scans
/proc for processes whose cwd or exe resolve into a release dir and fails when
the referenced path no longer exists (the /proc "(deleted)" marker or a
dangling target). Same-user processes only — readlink on other users' proc
entries fails silently — which covers the systemd --user estate.
"""

from __future__ import annotations

import os
import time

from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group

RELEASES_MARKER = "/source-activation/releases/"
_DELETED_SUFFIX = " (deleted)"


class ProcScanError(RuntimeError):
    """The proc root could not be scanned — the probe must report UNKNOWN,
    never healthy (dossier finding 2026-06-12: fail-open probe)."""


def _release_refs(proc_root: str) -> tuple[int, list[str]]:
    """Return (live release reference count, ghost reference descriptors)."""
    live = 0
    ghosts: list[str] = []
    try:
        entries = os.listdir(proc_root)
    except OSError as exc:
        raise ProcScanError(f"proc root unreadable: {exc}") from exc
    for pid in entries:
        if not pid.isdigit():
            continue
        for kind in ("cwd", "exe"):
            try:
                target = os.readlink(os.path.join(proc_root, pid, kind))
            except OSError:
                continue
            deleted = target.endswith(_DELETED_SUFFIX)
            path = target.removesuffix(_DELETED_SUFFIX)
            if RELEASES_MARKER not in path:
                continue
            live += 1
            if deleted or not os.path.exists(path):
                ghosts.append(f"pid {pid} {kind} -> {target}")
    return live, ghosts


@check_group("release")
async def check_release_ghost(proc_root: str = "/proc") -> list[CheckResult]:
    t = time.monotonic()
    try:
        live, ghosts = _release_refs(proc_root)
    except ProcScanError as exc:
        # Fail CLOSED: an unscannable proc root is a FAILED probe, never a
        # green one (dossier finding 2026-06-12).
        return [
            CheckResult(
                name="release.ghost",
                group="release",
                status=Status.FAILED,
                message=f"release-ghost probe could not scan processes: {exc}",
                remediation=(
                    "fix /proc readability for the health monitor (mount/perms); "
                    "do NOT trust release GC until the probe scans again"
                ),
                duration_ms=_u._timed(t),
            )
        ]

    if ghosts:
        return [
            CheckResult(
                name="release.ghost",
                group="release",
                status=Status.FAILED,
                message=f"ghost release: {len(ghosts)} live process reference(s) into deleted release dirs",
                detail="\n".join(sorted(ghosts)),
                remediation=(
                    "restart the affected --user service onto the current release "
                    "(systemctl --user restart <unit>); never GC a release dir with live PIDs"
                ),
                duration_ms=_u._timed(t),
            )
        ]

    return [
        CheckResult(
            name="release.ghost",
            group="release",
            status=Status.HEALTHY,
            message=f"{live} live release reference(s), none deleted",
            duration_ms=_u._timed(t),
        )
    ]
