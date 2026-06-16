"""Claim-cache lease helpers shared by hygiene checks/actions."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_CLAIM_CACHE_DIR = Path.home() / ".cache" / "hapax"
DEFAULT_CLAIM_LEASE_TTL_SECS = 21600
_NULLISH_ROLES = frozenset({"", "null", "none", "~", "unassigned", "[]"})


def _claim_cache_dir() -> Path:
    return Path(os.environ.get("HAPAX_CLAIM_CACHE_DIR", str(DEFAULT_CLAIM_CACHE_DIR)))


def claim_lease_ttl_seconds() -> int:
    raw = os.environ.get("HAPAX_CLAIM_LEASE_TTL_SECS")
    if raw is None:
        return DEFAULT_CLAIM_LEASE_TTL_SECS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_CLAIM_LEASE_TTL_SECS


def _now_epoch(now: datetime | None) -> float:
    if now is None:
        return datetime.now(UTC).timestamp()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).timestamp()


def _claim_task(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").splitlines()[0].strip()
    except (IndexError, OSError):
        return ""


def fresh_matching_claim_lease(
    role: str | None,
    task_id: str | None = None,
    *,
    cache_dir: Path | None = None,
    now: datetime | None = None,
    ttl_seconds: int | None = None,
) -> Path | None:
    """Return a fresh claim lease for ``role`` and optional ``task_id``.

    Accepts both legacy ``cc-active-task-<role>`` and session-keyed
    ``cc-active-task-<role>-<session>`` leases.
    """
    normalized_role = str(role or "").strip()
    if normalized_role.lower() in _NULLISH_ROLES:
        return None
    normalized_task = str(task_id).strip() if task_id is not None else None
    cache = cache_dir or _claim_cache_dir()
    ttl = claim_lease_ttl_seconds() if ttl_seconds is None else max(0, ttl_seconds)
    now_ts = _now_epoch(now)

    candidates = [cache / f"cc-active-task-{normalized_role}"]
    candidates.extend(sorted(cache.glob(f"cc-active-task-{normalized_role}-*")))
    for path in candidates:
        if not path.is_file():
            continue
        claim_task = _claim_task(path)
        if not claim_task:
            continue
        if normalized_task is not None and claim_task != normalized_task:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if now_ts - mtime > ttl:
            continue
        return path
    return None


__all__ = ["DEFAULT_CLAIM_LEASE_TTL_SECS", "fresh_matching_claim_lease"]
