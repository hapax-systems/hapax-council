"""Task-bound maintenance locks for automated remediation.

Runtime maintenance windows can intentionally stop services that health checks
normally auto-repair. Lock files under ``~/.cache/hapax/maintenance-locks`` let
governed tasks suppress targeted remediation until an explicit expiry.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_LOCK_DIR = Path("~/.cache/hapax/maintenance-locks")
MAX_LOCK_FILES = 64
MAX_LOCK_BYTES = 64 * 1024


@dataclass(frozen=True)
class MaintenanceLock:
    """An active maintenance lock parsed from a runtime lock file."""

    path: Path
    expires_at: datetime
    task_id: str | None = None
    reason: str | None = None
    containers: frozenset[str] = frozenset()
    services: frozenset[str] = frozenset()
    targets: frozenset[str] = frozenset()

    def matches(self, target: str, *, target_type: str = "docker") -> bool:
        """Return whether this lock covers a Docker container/service target."""
        target = target.strip()
        if not target:
            return False
        candidates = set(self.targets)
        if target_type in {"container", "docker"}:
            candidates.update(self.containers)
        if target_type in {"service", "compose", "docker"}:
            candidates.update(self.services)
            # Compose service names and container names are often identical in
            # the local stack, so let service checks honor both explicit fields.
            candidates.update(self.containers)
        return target in candidates

    def has_docker_targets(self) -> bool:
        """Return whether this lock covers at least one Docker remediation target."""
        return bool(self.containers or self.services or self.targets)


def default_lock_dir() -> Path:
    """Return the configured lock directory."""
    configured = os.environ.get("HAPAX_MAINTENANCE_LOCK_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_LOCK_DIR.expanduser()


def active_maintenance_locks(
    *,
    lock_dir: Path | None = None,
    now: datetime | None = None,
) -> list[MaintenanceLock]:
    """Read active lock files, ignoring missing, expired, and malformed entries."""
    root = (lock_dir or default_lock_dir()).expanduser()
    if now is None:
        now = datetime.now(UTC)
    if not root.is_dir():
        return []

    locks: list[MaintenanceLock] = []
    for path in sorted(root.glob("*.json"))[:MAX_LOCK_FILES]:
        lock = _read_lock(path, now=now)
        if lock is not None:
            locks.append(lock)
    return locks


def maintenance_lock_for_target(
    target: str,
    *,
    target_type: str = "docker",
    lock_dir: Path | None = None,
    now: datetime | None = None,
) -> MaintenanceLock | None:
    """Return the first active lock covering ``target``, if any."""
    for lock in active_maintenance_locks(lock_dir=lock_dir, now=now):
        if lock.matches(target, target_type=target_type):
            return lock
    return None


def first_docker_maintenance_lock(
    *,
    lock_dir: Path | None = None,
    now: datetime | None = None,
) -> MaintenanceLock | None:
    """Return any active Docker-targeted lock.

    This is used for targetless ``docker compose up -d`` commands, which would
    otherwise start every stopped compose service.
    """
    for lock in active_maintenance_locks(lock_dir=lock_dir, now=now):
        if lock.has_docker_targets():
            return lock
    return None


def maintenance_lock_message(action: str, target: str, lock: MaintenanceLock) -> str:
    """Build a concise suppression message for logs and test assertions."""
    owner = f" for task {lock.task_id}" if lock.task_id else ""
    reason = f": {lock.reason}" if lock.reason else ""
    return (
        f"Suppressed {action} for {target} by active maintenance lock{owner} "
        f"until {lock.expires_at.isoformat().replace('+00:00', 'Z')}{reason}"
    )


def _read_lock(path: Path, *, now: datetime) -> MaintenanceLock | None:
    try:
        if path.stat().st_size > MAX_LOCK_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    expires_at = _parse_datetime(data.get("expires_at"))
    if expires_at is None or expires_at <= now:
        return None

    containers = _string_set(_chain_values(data.get("containers"), data.get("docker_containers")))
    services = _string_set(_chain_values(data.get("services"), data.get("compose_services")))
    targets = _string_set(data.get("targets"))
    if not (containers or services or targets):
        return None

    task_id = data.get("task_id")
    reason = data.get("reason")
    return MaintenanceLock(
        path=path,
        expires_at=expires_at,
        task_id=task_id.strip() if isinstance(task_id, str) and task_id.strip() else None,
        reason=reason.strip() if isinstance(reason, str) and reason.strip() else None,
        containers=frozenset(containers),
        services=frozenset(services),
        targets=frozenset(targets),
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if isinstance(value, list | tuple | set):
        return {item.strip() for item in value if isinstance(item, str) and item.strip()}
    return set()


def _chain_values(*values: Any) -> list[Any]:
    chained: list[Any] = []
    for value in values:
        if isinstance(value, list):
            chained.extend(value)
        elif value is not None:
            chained.append(value)
    return chained
