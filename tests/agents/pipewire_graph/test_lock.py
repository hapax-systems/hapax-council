from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agents.pipewire_graph.lock import (
    acquire_session_lock,
    lock_allows_owner,
    read_lock_status,
    release_session_lock,
)

NOW = datetime(2026, 5, 7, 3, 10, tzinfo=UTC)


def test_acquire_session_lock_writes_active_lease(tmp_path: Path) -> None:
    status = acquire_session_lock(
        owner="cx-cyan",
        ttl_s=300,
        lock_root=tmp_path,
        now_utc=NOW,
    )

    assert status.active is True
    assert status.owner == "cx-cyan"
    assert status.expires_at == "2026-05-07T03:15:00Z"
    assert lock_allows_owner("cx-cyan", lock_root=tmp_path, now_utc=NOW) is True
    assert lock_allows_owner("cx-blue", lock_root=tmp_path, now_utc=NOW) is False


def test_acquire_session_lock_refuses_other_active_owner(tmp_path: Path) -> None:
    acquire_session_lock(owner="cx-cyan", ttl_s=300, lock_root=tmp_path, now_utc=NOW)

    with pytest.raises(RuntimeError, match="held by 'cx-cyan'"):
        acquire_session_lock(owner="cx-blue", ttl_s=300, lock_root=tmp_path, now_utc=NOW)


def test_expired_lock_is_not_active_and_can_be_replaced(tmp_path: Path) -> None:
    acquire_session_lock(owner="cx-cyan", ttl_s=1, lock_root=tmp_path, now_utc=NOW)
    later = datetime(2026, 5, 7, 3, 10, 2, tzinfo=UTC)

    expired = read_lock_status(lock_root=tmp_path, now_utc=later)
    assert expired.active is False
    assert expired.expired is True

    refreshed = acquire_session_lock(owner="cx-blue", ttl_s=60, lock_root=tmp_path, now_utc=later)
    assert refreshed.active is True
    assert refreshed.owner == "cx-blue"


def test_release_session_lock_requires_owner_unless_forced(tmp_path: Path) -> None:
    acquire_session_lock(owner="cx-cyan", ttl_s=300, lock_root=tmp_path, now_utc=NOW)

    with pytest.raises(RuntimeError, match="refusing unlock"):
        release_session_lock(owner="cx-blue", lock_root=tmp_path, now_utc=NOW)

    forced = release_session_lock(owner="cx-blue", lock_root=tmp_path, force=True, now_utc=NOW)
    assert forced.active is False
    assert forced.reason == "missing"
