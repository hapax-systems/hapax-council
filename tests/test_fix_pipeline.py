"""Tests for shared.fix_capabilities.pipeline."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from agents.health_monitor import CheckResult, GroupResult, HealthReport, Status, worst_status
from shared.fix_capabilities.background_admission import BackgroundCapabilityAdmission
from shared.fix_capabilities.base import (
    Action,
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)
from shared.fix_capabilities.pipeline import FixOutcome, PipelineResult, run_fix_pipeline

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_report(*checks: CheckResult) -> HealthReport:
    """Build a minimal HealthReport from CheckResult objects."""
    groups: dict[str, list[CheckResult]] = {}
    for c in checks:
        groups.setdefault(c.group, []).append(c)

    group_results = []
    for group_name, group_checks in groups.items():
        statuses = [c.status for c in group_checks]
        group_results.append(
            GroupResult(
                group=group_name,
                status=worst_status(*statuses),
                checks=group_checks,
                healthy_count=sum(1 for s in statuses if s == Status.HEALTHY),
                degraded_count=sum(1 for s in statuses if s == Status.DEGRADED),
                failed_count=sum(1 for s in statuses if s == Status.FAILED),
            )
        )

    all_statuses = [c.status for c in checks] or [Status.HEALTHY]
    return HealthReport(
        timestamp="2026-01-01T00:00:00",
        hostname="test",
        overall_status=worst_status(*all_statuses),
        groups=group_results,
        total_checks=len(checks),
        healthy_count=sum(1 for c in checks if c.status == Status.HEALTHY),
        degraded_count=sum(1 for c in checks if c.status == Status.DEGRADED),
        failed_count=sum(1 for c in checks if c.status == Status.FAILED),
    )


class _MockCap(Capability):
    """Mock capability for testing."""

    name = "mock-cap"
    check_groups = {"test-group"}

    def __init__(
        self,
        *,
        validate_result: bool = True,
        exec_result: ExecutionResult | None = None,
    ):
        self._validate_result = validate_result
        self._exec_result = exec_result or ExecutionResult(success=True, message="fixed")
        self._probe = ProbeResult(capability="mock-cap", raw={"key": "val"})

    async def gather_context(self, check):
        return self._probe

    def available_actions(self) -> list[Action]:
        return [Action(name="restart", safety=Safety.SAFE)]

    def validate(self, proposal: FixProposal) -> bool:
        return self._validate_result

    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        return self._exec_result


_FAILING_CHECK = CheckResult(
    name="test-check",
    group="test-group",
    status=Status.FAILED,
    message="something broke",
)

_HEALTHY_CHECK = CheckResult(
    name="ok-check",
    group="test-group",
    status=Status.HEALTHY,
    message="all good",
)

_SAFE_PROPOSAL = FixProposal(
    capability="mock-cap",
    action_name="restart",
    params={},
    rationale="needs restart",
    safety=Safety.SAFE,
)

_DESTRUCTIVE_PROPOSAL = FixProposal(
    capability="mock-cap",
    action_name="purge",
    params={},
    rationale="needs purge",
    safety=Safety.DESTRUCTIVE,
)

_PATCH_BASE = "shared.fix_capabilities.pipeline"


def _admission(*, admitted: bool = True) -> BackgroundCapabilityAdmission:
    return BackgroundCapabilityAdmission(
        capability_name="health_monitor.fix.mock.restart",
        route_id="local_tool.local.worker",
        admitted=admitted,
        denied_reason=None if admitted else "route_policy_denied",
        reason_codes=("policy_launch",) if admitted else ("runtime_actuation_receipt_absent",),
        task_id="task-x",
        authority_case="CASE-CAPACITY-ROUTING-001",
        mutation_surface="runtime",
        quality_floor="deterministic_ok",
        route_decision_id="rd-test",
        model_descriptor={
            "execution_descriptor": {"model_id": "command-r-08-2024"},
        },
    )


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_failures_returns_empty():
    """Healthy report produces total=0 and no outcomes."""
    report = _make_report(_HEALTHY_CHECK)
    result = await run_fix_pipeline(report)
    assert result.total == 0
    assert result.outcomes == []


@pytest.mark.asyncio
async def test_no_capability_skips_check():
    """Unknown group with no registered capability is skipped."""
    check = CheckResult(
        name="unknown-check",
        group="unknown-group",
        status=Status.FAILED,
        message="broken",
    )
    report = _make_report(check)
    with patch(f"{_PATCH_BASE}.get_capability_for_group", return_value=None):
        result = await run_fix_pipeline(report)
    assert result.total == 0
    assert result.outcomes == []


@pytest.mark.asyncio
async def test_safe_proposal_executes():
    """Safe FixProposal is executed with success."""
    cap = _MockCap()
    report = _make_report(_FAILING_CHECK)
    with (
        patch(f"{_PATCH_BASE}.get_capability_for_group", return_value=cap),
        patch(f"{_PATCH_BASE}.evaluate_check", new_callable=AsyncMock, return_value=_SAFE_PROPOSAL),
        patch(f"{_PATCH_BASE}._admit_runtime_fix_execution", return_value=_admission()),
        patch(f"{_PATCH_BASE}.send_notification"),
    ):
        result = await run_fix_pipeline(report)

    assert result.total == 1
    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.executed is True
    assert outcome.execution_result is not None
    assert outcome.execution_result.success is True
    assert outcome.notified is False
    assert outcome.admission is not None
    assert outcome.admission["route_id"] == "local_tool.local.worker"


@pytest.mark.asyncio
async def test_safe_proposal_refuses_without_runtime_admission():
    """Safe proposals do not execute unless the spine admits runtime actuation."""
    cap = _MockCap()
    report = _make_report(_FAILING_CHECK)
    with (
        patch(f"{_PATCH_BASE}.get_capability_for_group", return_value=cap),
        patch(f"{_PATCH_BASE}.evaluate_check", new_callable=AsyncMock, return_value=_SAFE_PROPOSAL),
        patch(
            f"{_PATCH_BASE}._admit_runtime_fix_execution", return_value=_admission(admitted=False)
        ),
        patch(f"{_PATCH_BASE}.send_notification"),
    ):
        result = await run_fix_pipeline(report)

    assert result.total == 1
    outcome = result.outcomes[0]
    assert outcome.executed is False
    assert outcome.rejected_reason is not None
    assert "runtime_actuation_receipt_absent" in outcome.rejected_reason


@pytest.mark.asyncio
async def test_destructive_proposal_notifies_not_executes():
    """Destructive proposal triggers notification but no execution."""
    cap = _MockCap()
    report = _make_report(_FAILING_CHECK)
    with (
        patch(f"{_PATCH_BASE}.get_capability_for_group", return_value=cap),
        patch(
            f"{_PATCH_BASE}.evaluate_check",
            new_callable=AsyncMock,
            return_value=_DESTRUCTIVE_PROPOSAL,
        ),
        patch(f"{_PATCH_BASE}.send_notification") as mock_notify,
    ):
        result = await run_fix_pipeline(report)

    assert result.total == 1
    outcome = result.outcomes[0]
    assert outcome.executed is False
    assert outcome.notified is True
    mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_dry_run_does_not_execute():
    """mode='dry_run' skips execution even for safe proposals."""
    cap = _MockCap()
    report = _make_report(_FAILING_CHECK)
    with (
        patch(f"{_PATCH_BASE}.get_capability_for_group", return_value=cap),
        patch(f"{_PATCH_BASE}.evaluate_check", new_callable=AsyncMock, return_value=_SAFE_PROPOSAL),
        patch(f"{_PATCH_BASE}.send_notification"),
    ):
        result = await run_fix_pipeline(report, mode="dry_run")

    assert result.total == 1
    outcome = result.outcomes[0]
    assert outcome.executed is False
    assert outcome.proposal == _SAFE_PROPOSAL


@pytest.mark.asyncio
async def test_validation_failure_skips():
    """Invalid proposal gets rejected_reason set."""
    cap = _MockCap(validate_result=False)
    report = _make_report(_FAILING_CHECK)
    with (
        patch(f"{_PATCH_BASE}.get_capability_for_group", return_value=cap),
        patch(f"{_PATCH_BASE}.evaluate_check", new_callable=AsyncMock, return_value=_SAFE_PROPOSAL),
        patch(f"{_PATCH_BASE}.send_notification"),
    ):
        result = await run_fix_pipeline(report)

    assert result.total == 1
    outcome = result.outcomes[0]
    assert outcome.rejected_reason is not None
    assert outcome.executed is False


@pytest.mark.asyncio
async def test_evaluator_returns_none_skips():
    """evaluate_check returning None means total stays 0."""
    cap = _MockCap()
    report = _make_report(_FAILING_CHECK)
    with (
        patch(f"{_PATCH_BASE}.get_capability_for_group", return_value=cap),
        patch(f"{_PATCH_BASE}.evaluate_check", new_callable=AsyncMock, return_value=None),
        patch(f"{_PATCH_BASE}.send_notification"),
    ):
        result = await run_fix_pipeline(report)

    assert result.total == 0
    assert result.outcomes == []


@pytest.mark.asyncio
async def test_deterministic_docker_compose_up_suppressed_by_maintenance_lock(
    tmp_path, monkeypatch
):
    """Fallback compose-up remediation does not run while target is locked."""
    monkeypatch.setenv("HAPAX_MAINTENANCE_LOCK_DIR", str(tmp_path))
    (tmp_path / "minio.json").write_text(
        json.dumps(
            {
                "task_id": "minio-cutover",
                "expires_at": "2999-01-01T00:00:00Z",
                "services": ["minio"],
            }
        ),
        encoding="utf-8",
    )
    check = CheckResult(
        name="docker.minio",
        group="unknown-group",
        status=Status.FAILED,
        message="stopped",
        remediation="cd ~/llm-stack && docker compose up -d minio",
    )
    report = _make_report(check)
    with (
        patch(f"{_PATCH_BASE}.get_capability_for_group", return_value=None),
        patch(f"{_PATCH_BASE}._admit_runtime_fix_execution", return_value=_admission()),
        patch(f"{_PATCH_BASE}.run_cmd", new_callable=AsyncMock) as mock_cmd,
    ):
        result = await run_fix_pipeline(report)

    assert result.total == 1
    outcome = result.outcomes[0]
    assert outcome.executed is False
    assert outcome.rejected_reason is not None
    assert "Suppressed docker compose up for minio" in outcome.rejected_reason
    assert "minio-cutover" in outcome.rejected_reason
    mock_cmd.assert_not_called()


@pytest.mark.asyncio
async def test_deterministic_targetless_compose_up_suppressed_when_any_docker_lock(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HAPAX_MAINTENANCE_LOCK_DIR", str(tmp_path))
    (tmp_path / "active.json").write_text(
        json.dumps(
            {
                "task_id": "maintenance",
                "expires_at": "2999-01-01T00:00:00Z",
                "containers": ["minio"],
            }
        ),
        encoding="utf-8",
    )
    check = CheckResult(
        name="docker.containers",
        group="unknown-group",
        status=Status.FAILED,
        message="none",
        remediation="cd ~/llm-stack && docker compose up -d",
    )
    report = _make_report(check)
    with (
        patch(f"{_PATCH_BASE}.get_capability_for_group", return_value=None),
        patch(f"{_PATCH_BASE}._admit_runtime_fix_execution", return_value=_admission()),
        patch(f"{_PATCH_BASE}.run_cmd", new_callable=AsyncMock) as mock_cmd,
    ):
        result = await run_fix_pipeline(report)

    assert result.total == 1
    assert result.outcomes[0].rejected_reason is not None
    assert "<all compose services>" in result.outcomes[0].rejected_reason
    mock_cmd.assert_not_called()


@pytest.mark.asyncio
async def test_deterministic_docker_compose_up_runs_when_lock_expired(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPAX_MAINTENANCE_LOCK_DIR", str(tmp_path))
    (tmp_path / "expired.json").write_text(
        json.dumps(
            {
                "task_id": "old-maintenance",
                "expires_at": "2000-01-01T00:00:00Z",
                "services": ["minio"],
            }
        ),
        encoding="utf-8",
    )
    check = CheckResult(
        name="docker.minio",
        group="unknown-group",
        status=Status.FAILED,
        message="stopped",
        remediation="cd ~/llm-stack && docker compose up -d minio",
    )
    report = _make_report(check)
    with (
        patch(f"{_PATCH_BASE}.get_capability_for_group", return_value=None),
        patch(f"{_PATCH_BASE}._admit_runtime_fix_execution", return_value=_admission()),
        patch(
            f"{_PATCH_BASE}.run_cmd",
            new_callable=AsyncMock,
            return_value=(0, "ok", ""),
        ) as mock_cmd,
    ):
        result = await run_fix_pipeline(report)

    assert result.total == 1
    assert result.outcomes[0].executed is True
    assert result.outcomes[0].execution_result is not None
    assert result.outcomes[0].execution_result.success is True
    mock_cmd.assert_called_once_with(
        ["docker", "compose", "up", "-d", "minio"],
        timeout=30.0,
        cwd=os.path.expanduser("~/llm-stack"),
    )


@pytest.mark.asyncio
async def test_gather_context_exception_skips():
    """Exception in gather_context skips the check."""
    cap = _MockCap()

    # Monkey-patch the instance method to raise
    async def _raise(check):
        raise RuntimeError("probe failed")

    cap.gather_context = _raise
    report = _make_report(_FAILING_CHECK)
    with (
        patch(f"{_PATCH_BASE}.get_capability_for_group", return_value=cap),
        patch(f"{_PATCH_BASE}.evaluate_check", new_callable=AsyncMock) as mock_eval,
        patch(f"{_PATCH_BASE}.send_notification"),
    ):
        result = await run_fix_pipeline(report)

    assert result.total == 0
    mock_eval.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_result_computed_properties():
    """executed_count and notified_count compute from outcomes."""
    pr = PipelineResult(
        total=3,
        outcomes=[
            FixOutcome(check_name="a", executed=True),
            FixOutcome(check_name="b", executed=True, notified=True),
            FixOutcome(check_name="c", notified=True),
        ],
    )
    assert pr.executed_count == 2
    assert pr.notified_count == 2
