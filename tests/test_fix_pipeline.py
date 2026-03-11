"""Tests for shared.fix_capabilities.pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.health_monitor import CheckResult, GroupResult, HealthReport, Status, worst_status
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
