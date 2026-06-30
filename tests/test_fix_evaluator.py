"""Tests for shared.fix_capabilities.evaluator — LLM evaluator agent.

No LLM calls; the pydantic-ai agent is fully mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.health_monitor import CheckResult, Status
from shared.fix_capabilities.background_admission import BackgroundCapabilityAdmission
from shared.fix_capabilities.base import Action, FixProposal, ProbeResult, Safety

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_check(
    name: str = "docker_litellm",
    group: str = "docker",
    status: Status = Status.FAILED,
    message: str = "container not running",
    detail: str | None = "litellm exited 137",
    remediation: str | None = "docker compose up -d litellm",
) -> CheckResult:
    return CheckResult(
        name=name,
        group=group,
        status=status,
        message=message,
        detail=detail,
        remediation=remediation,
    )


def _make_probe() -> ProbeResult:
    return ProbeResult(
        capability="docker",
        raw={"container": "litellm", "state": "exited"},
    )


def _make_actions() -> list[Action]:
    return [
        Action(
            name="restart_container",
            safety=Safety.SAFE,
            description="Restart a stopped Docker container",
        ),
        Action(
            name="recreate_container",
            safety=Safety.DESTRUCTIVE,
            description="Destroy and recreate a container from compose",
        ),
    ]


def _make_proposal() -> FixProposal:
    return FixProposal(
        capability="docker",
        action_name="restart_container",
        params={"container": "litellm"},
        rationale="Container exited, restart is safe",
        safety=Safety.SAFE,
    )


def _admission(*, admitted: bool = True) -> BackgroundCapabilityAdmission:
    return BackgroundCapabilityAdmission(
        capability_name="health_monitor.fix_evaluator.llm",
        route_id="api.headless.provider_gateway",
        model_alias="claude-sonnet",
        admitted=admitted,
        denied_reason=None if admitted else "route_policy_denied",
        reason_codes=("policy_launch",) if admitted else ("provider_gateway_evidence_absent",),
        task_id="task-x",
        authority_case="CASE-CAPACITY-ROUTING-001",
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        route_decision_id="rd-test",
    )


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_fix_proposal():
    """Mock agent.run returns valid FixProposal -> evaluate_check returns it."""
    from shared.fix_capabilities.evaluator import evaluate_check

    proposal = _make_proposal()
    mock_result = MagicMock()
    mock_result.output = proposal

    with patch(
        "shared.fix_capabilities.evaluator._evaluator_agent.run",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        result = await evaluate_check(
            _make_check(),
            _make_probe(),
            _make_actions(),
            admission_gate=lambda: _admission(),
        )

    assert result is not None
    assert result.action_name == "restart_container"
    assert result.capability == "docker"


@pytest.mark.asyncio
async def test_returns_none_on_llm_error():
    """Mock agent.run raises Exception -> returns None."""
    from shared.fix_capabilities.evaluator import evaluate_check

    with patch(
        "shared.fix_capabilities.evaluator._evaluator_agent.run",
        new_callable=AsyncMock,
        side_effect=Exception("LLM timeout"),
    ):
        result = await evaluate_check(
            _make_check(),
            _make_probe(),
            _make_actions(),
            admission_gate=lambda: _admission(),
        )

    assert result is None


@pytest.mark.asyncio
async def test_returns_none_for_healthy_check():
    """Healthy CheckResult -> returns None without calling LLM."""
    from shared.fix_capabilities.evaluator import evaluate_check

    healthy = _make_check(status=Status.HEALTHY, message="all good")

    with patch(
        "shared.fix_capabilities.evaluator._evaluator_agent.run",
        new_callable=AsyncMock,
    ) as mock_run:
        result = await evaluate_check(healthy, _make_probe(), _make_actions())

    assert result is None
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_returns_none_for_no_action():
    """LLM proposes 'no_action' -> returns None."""
    from shared.fix_capabilities.evaluator import evaluate_check

    no_action_proposal = FixProposal(
        capability="docker",
        action_name="no_action",
        rationale="No suitable action available",
        safety=Safety.SAFE,
    )
    mock_result = MagicMock()
    mock_result.output = no_action_proposal

    with patch(
        "shared.fix_capabilities.evaluator._evaluator_agent.run",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        result = await evaluate_check(
            _make_check(),
            _make_probe(),
            _make_actions(),
            admission_gate=lambda: _admission(),
        )

    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_no_actions():
    """Empty actions list -> returns None without calling LLM."""
    from shared.fix_capabilities.evaluator import evaluate_check

    with patch(
        "shared.fix_capabilities.evaluator._evaluator_agent.run",
        new_callable=AsyncMock,
    ) as mock_run:
        result = await evaluate_check(_make_check(), _make_probe(), [])

    assert result is None
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_prompt_includes_check_context():
    """Verify the prompt passed to agent.run contains check name and message."""
    from shared.fix_capabilities.evaluator import evaluate_check

    proposal = _make_proposal()
    mock_result = MagicMock()
    mock_result.output = proposal

    check = _make_check(name="docker_litellm", message="container not running")

    with patch(
        "shared.fix_capabilities.evaluator._evaluator_agent.run",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock_run:
        await evaluate_check(
            check,
            _make_probe(),
            _make_actions(),
            admission_gate=lambda: _admission(),
        )

    mock_run.assert_called_once()
    prompt_arg = mock_run.call_args[0][0]
    assert "docker_litellm" in prompt_arg
    assert "container not running" in prompt_arg


@pytest.mark.asyncio
async def test_default_admission_denial_skips_llm():
    """The public evaluator API fails closed by default before model use."""
    from shared.fix_capabilities.evaluator import evaluate_check

    with (
        patch(
            "shared.fix_capabilities.evaluator.admit_fix_evaluator",
            return_value=_admission(admitted=False),
        ),
        patch(
            "shared.fix_capabilities.evaluator._evaluator_agent.run",
            new_callable=AsyncMock,
        ) as mock_run,
    ):
        result = await evaluate_check(_make_check(), _make_probe(), _make_actions())

    assert result is None
    mock_run.assert_not_called()


def test_fix_evaluator_admission_uses_provider_gateway_route():
    """The evaluator gate requests admission for the route backing balanced."""
    from shared.fix_capabilities.evaluator import admit_fix_evaluator

    with patch("shared.fix_capabilities.evaluator.admit_background_capability") as mock_admit:
        mock_admit.return_value = _admission()
        admission = admit_fix_evaluator()

    assert admission.admitted is True
    kwargs = mock_admit.call_args.kwargs
    assert kwargs["route_id"] == "api.headless.provider_gateway"
    assert kwargs["model_alias"] == "claude-sonnet"
    assert kwargs["mutation_surface"] == "provider_spend"
    assert kwargs["quality_floor"] == "frontier_required"
