"""Session-scoped applier lock for the PipeWire graph.

Phase 3 of the audio graph SSOT does not apply live graph changes yet.
It adds the coordination primitive that prevents direct edits to the
graph-owned PipeWire/WirePlumber files unless a session explicitly holds
the applier lock.

The lock is represented as a short-lived JSON lease at
``~/.cache/hapax/pipewire-graph/applier.lock``. The lease shape is easy
for shell hooks to inspect while the Python CLI serializes updates with
``flock`` so two sessions cannot refresh it concurrently.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_LOCK_ROOT = Path("~/.cache/hapax/pipewire-graph").expanduser()
DEFAULT_LOCK_FILENAME = "applier.lock"
DEFAULT_LOCK_TTL_S = 300


@dataclass(frozen=True)
class ApplierLockStatus:
    """Readable lock state for hooks, CLI, and tests."""

    path: Path
    active: bool
    owner: str | None = None
    acquired_at: str | None = None
    expires_at: str | None = None
    ttl_s: int | None = None
    pid: int | None = None
    host: str | None = None
    expired: bool = False
    malformed: bool = False
    reason: str = "missing"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "active": self.active,
            "owner": self.owner,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "ttl_s": self.ttl_s,
            "pid": self.pid,
            "host": self.host,
            "expired": self.expired,
            "malformed": self.malformed,
            "reason": self.reason,
        }


def lock_path(lock_root: Path | None = None) -> Path:
    """Return the applier lock path, creating no files."""

    return (lock_root or DEFAULT_LOCK_ROOT) / DEFAULT_LOCK_FILENAME


def owner_from_env(default: str = "unknown") -> str:
    """Resolve the current Hapax session identity from common agent env vars."""

    for key in (
        "HAPAX_AGENT_ROLE",
        "HAPAX_AGENT_NAME",
        "CODEX_ROLE",
        "CODEX_THREAD_NAME",
        "CLAUDE_ROLE",
        "USER",
    ):
        raw = os.environ.get(key)
        if raw and raw.strip():
            return _normalize_owner(raw)
    return _normalize_owner(default)


def read_lock_status(
    *,
    lock_root: Path | None = None,
    now_utc: datetime | None = None,
) -> ApplierLockStatus:
    """Read and classify the current applier lock lease."""

    path = lock_path(lock_root)
    now = now_utc or datetime.now(UTC)
    if not path.exists():
        return ApplierLockStatus(path=path, active=False, reason="missing")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ApplierLockStatus(path=path, active=False, malformed=True, reason="malformed")
    if not isinstance(raw, dict):
        return ApplierLockStatus(path=path, active=False, malformed=True, reason="malformed")
    owner = _optional_str(raw.get("owner"))
    expires_at = _optional_str(raw.get("expires_at"))
    expires_dt = _parse_utc(expires_at)
    if owner is None or expires_dt is None:
        return ApplierLockStatus(
            path=path,
            active=False,
            owner=owner,
            acquired_at=_optional_str(raw.get("acquired_at")),
            expires_at=expires_at,
            malformed=True,
            reason="malformed",
        )
    expired = expires_dt <= now
    return ApplierLockStatus(
        path=path,
        active=not expired,
        owner=owner,
        acquired_at=_optional_str(raw.get("acquired_at")),
        expires_at=expires_at,
        ttl_s=_optional_int(raw.get("ttl_s")),
        pid=_optional_int(raw.get("pid")),
        host=_optional_str(raw.get("host")),
        expired=expired,
        reason="active" if not expired else "expired",
    )


def acquire_session_lock(
    *,
    owner: str,
    ttl_s: int = DEFAULT_LOCK_TTL_S,
    lock_root: Path | None = None,
    force: bool = False,
    now_utc: datetime | None = None,
) -> ApplierLockStatus:
    """Acquire or refresh the session edit lease.

    This does not mutate PipeWire. It only writes the lock metadata that
    the PreToolUse gate checks before allowing graph-file edits.
    """

    owner = _normalize_owner(owner)
    if ttl_s <= 0:
        raise ValueError("ttl_s must be positive")
    now = now_utc or datetime.now(UTC)
    path = lock_path(lock_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            status = read_lock_status(lock_root=path.parent, now_utc=now)
            if status.active and status.owner != owner and not force:
                raise RuntimeError(
                    f"applier lock is held by {status.owner!r} until {status.expires_at}"
                )
            expires = now + timedelta(seconds=ttl_s)
            payload = {
                "schema_version": 1,
                "owner": owner,
                "acquired_at": _format_utc(now),
                "expires_at": _format_utc(expires),
                "ttl_s": ttl_s,
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "mode": "session_edit",
                "live_pipewire_mutation": False,
            }
            handle.seek(0)
            handle.truncate(0)
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return read_lock_status(lock_root=path.parent, now_utc=now)


def release_session_lock(
    *,
    owner: str | None = None,
    lock_root: Path | None = None,
    force: bool = False,
    now_utc: datetime | None = None,
) -> ApplierLockStatus:
    """Release the session edit lease when owned, forced, or expired."""

    path = lock_path(lock_root)
    if not path.exists():
        return read_lock_status(lock_root=path.parent, now_utc=now_utc)
    expected_owner = _normalize_owner(owner) if owner else None
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            status = read_lock_status(lock_root=path.parent, now_utc=now_utc)
            if (
                status.active
                and not force
                and expected_owner is not None
                and status.owner != expected_owner
            ):
                raise RuntimeError(
                    f"applier lock is held by {status.owner!r}; refusing unlock by "
                    f"{expected_owner!r}"
                )
            if force or status.expired or expected_owner is None or status.owner == expected_owner:
                handle.seek(0)
                handle.truncate(0)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    if path.exists() and path.stat().st_size == 0:
        path.unlink()
    return read_lock_status(lock_root=path.parent, now_utc=now_utc)


def lock_allows_owner(
    owner: str,
    *,
    lock_root: Path | None = None,
    now_utc: datetime | None = None,
) -> bool:
    """Return True when ``owner`` currently holds the active edit lease."""

    status = read_lock_status(lock_root=lock_root, now_utc=now_utc)
    return status.active and status.owner == _normalize_owner(owner)


def _normalize_owner(raw: str) -> str:
    owner = re.sub(r"[^A-Za-z0-9_.@:-]+", "-", raw.strip()).strip("-")
    return owner or "unknown"


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _parse_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "DEFAULT_LOCK_FILENAME",
    "DEFAULT_LOCK_ROOT",
    "DEFAULT_LOCK_TTL_S",
    "ApplierLockStatus",
    "acquire_session_lock",
    "lock_allows_owner",
    "lock_path",
    "owner_from_env",
    "read_lock_status",
    "release_session_lock",
]
