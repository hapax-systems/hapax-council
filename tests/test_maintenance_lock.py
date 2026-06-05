"""Tests for shared.maintenance_lock."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from shared.maintenance_lock import (
    active_maintenance_locks,
    first_docker_maintenance_lock,
    maintenance_lock_for_target,
)


def _write_lock(path, **fields) -> None:
    path.write_text(json.dumps(fields), encoding="utf-8")


def test_active_lock_matches_containers_services_and_targets(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_MAINTENANCE_LOCK_DIR", str(tmp_path))
    _write_lock(
        tmp_path / "minio.json",
        task_id="task-1",
        reason="cutover",
        expires_at="2026-06-05T08:00:00Z",
        containers=["minio"],
        services=["langfuse"],
        targets=["langfuse-worker"],
    )
    now = datetime(2026, 6, 5, 7, 0, tzinfo=UTC)

    assert maintenance_lock_for_target("minio", target_type="container", now=now)
    assert maintenance_lock_for_target("langfuse", target_type="service", now=now)
    assert maintenance_lock_for_target("langfuse-worker", target_type="service", now=now)
    assert maintenance_lock_for_target("qdrant", target_type="service", now=now) is None


def test_expired_lock_is_ignored(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_MAINTENANCE_LOCK_DIR", str(tmp_path))
    _write_lock(
        tmp_path / "expired.json",
        expires_at="2026-06-05T06:59:59Z",
        containers=["minio"],
    )
    now = datetime(2026, 6, 5, 7, 0, tzinfo=UTC)

    assert active_maintenance_locks(now=now) == []
    assert maintenance_lock_for_target("minio", target_type="container", now=now) is None


def test_malformed_lock_is_ignored(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_MAINTENANCE_LOCK_DIR", str(tmp_path))
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    _write_lock(tmp_path / "missing-expiry.json", containers=["minio"])

    assert active_maintenance_locks(now=datetime(2026, 6, 5, 7, 0, tzinfo=UTC)) == []


def test_targetless_docker_lock_detector_requires_docker_targets(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_MAINTENANCE_LOCK_DIR", str(tmp_path))
    _write_lock(
        tmp_path / "active.json",
        expires_at="2026-06-05T08:00:00Z",
        services=["minio"],
    )

    assert first_docker_maintenance_lock(now=datetime(2026, 6, 5, 7, 0, tzinfo=UTC))
