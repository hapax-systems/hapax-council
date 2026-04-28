"""Tests for restic backup health checks."""

from __future__ import annotations

import pytest

from agents.health_monitor import Status
from agents.health_monitor.checks import backup as backup_checks
from agents.health_monitor.constants import RESTIC_REPO
from shared import sufficiency_probes


def test_restic_repo_matches_live_local_backup_target():
    assert str(RESTIC_REPO) == "/store/hapax-backups/restic"
    assert str(sufficiency_probes.RUNTIME_RESTIC_REPO) == str(RESTIC_REPO)


@pytest.mark.asyncio
async def test_backup_freshness_uses_repo_activity(monkeypatch, tmp_path):
    repo = tmp_path / "restic"
    snapshots = repo / "snapshots"
    snapshots.mkdir(parents=True)
    monkeypatch.setattr(backup_checks._c, "RESTIC_REPO", repo)

    results = await backup_checks.check_backup_freshness()

    assert results[0].status == Status.HEALTHY
    assert str(snapshots) in results[0].detail
    assert results[0].remediation is None


def test_sufficiency_backup_probe_uses_live_repo_path(monkeypatch, tmp_path):
    repo = tmp_path / "restic"
    (repo / "locks").mkdir(parents=True)
    monkeypatch.setattr(sufficiency_probes, "RUNTIME_RESTIC_REPO", repo)

    ok, evidence = sufficiency_probes._check_backup_fresh()

    assert ok
    assert "backup" in evidence
