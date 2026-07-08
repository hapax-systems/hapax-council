from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from agents.deliberative_council.models import ConvergenceStatus, CouncilMode, CouncilVerdict
from agents.deliberative_council.modes.intake import (
    AXIS_WEIGHTS,
    IntakeContractError,
    IntakeHardeningRubric,
    IntakeVerdict,
    run_intake,
)
from shared.frontmatter import parse_frontmatter


def _write_request(path: Path, *, status: str = "captured") -> str:
    frontmatter = {
        "type": "request",
        "request_id": "REQ-INTAKE",
        "title": "Intake target",
        "status": status,
    }
    body = "# Request\n\nBuild the named thing with a concrete test.\n"
    text = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\n{body}"
    path.write_text(text, encoding="utf-8")
    return text


def _verdict(
    scores: dict[str, int | None],
    *,
    convergence: ConvergenceStatus = ConvergenceStatus.CONVERGED,
    receipt: dict[str, object] | None = None,
) -> CouncilVerdict:
    return CouncilVerdict(
        scores=scores,
        confidence_bands={},
        convergence_status=convergence,
        disagreement_log=[],
        research_findings=[],
        evidence_matrix=None,
        receipt=receipt or {},
    )


ADMITTED_COUNCIL_RECEIPT = {
    "route_resource_admission": "admitted",
    "capability_receipt_refs": ["cctv-capability-admission:test-member"],
    "capability_admissions": [
        {
            "capability_id": "cctv.model.opus",
            "route_id": "claude-opus",
            "admitted": True,
            "admission_action": "admitted",
            "receipt_refs": ["cctv-capability-admission:test-member"],
        }
    ],
}


@pytest.mark.asyncio
async def test_run_intake_ready_writes_admission_frontmatter(tmp_path: Path) -> None:
    request = tmp_path / "REQ-INTAKE.md"
    _write_request(request)
    scores = {axis: 4 for axis in AXIS_WEIGHTS}

    with patch(
        "agents.deliberative_council.engine.deliberate",
        new=AsyncMock(return_value=_verdict(scores, receipt=ADMITTED_COUNCIL_RECEIPT)),
    ) as deliberate_mock:
        receipt = await run_intake(request)

    assert receipt.verdict == IntakeVerdict.READY_TO_PLAN
    assert receipt.route_resource_admission == "admitted"
    assert receipt.capability_receipt_refs == ("cctv-capability-admission:test-member",)
    assert receipt.receipt_ref.startswith("cctv-intake-receipt:REQ-INTAKE:")
    inp, mode, rubric, _config = deliberate_mock.await_args.args
    assert inp.text == "# Request\n\nBuild the named thing with a concrete test.\n"
    assert inp.source_ref == str(request)
    assert mode == CouncilMode.INTAKE
    assert isinstance(rubric, IntakeHardeningRubric)

    frontmatter, body = parse_frontmatter(request)
    assert frontmatter["status"] == "accepted_for_planning"
    assert frontmatter["cctv_intake_receipt"] == receipt.receipt_ref
    assert frontmatter["cctv_intake_verdict"] == "ready_to_plan"
    assert frontmatter["cctv_route_resource_admission"] == "admitted"
    assert frontmatter["cctv_capability_receipts"] == ["cctv-capability-admission:test-member"]
    assert frontmatter["recommendation"] == "advance"
    assert frontmatter["composite"] == pytest.approx(4.0)
    assert frontmatter["axes"]["outcome_concreteness"]["score"] == 4
    assert body == "# Request\n\nBuild the named thing with a concrete test.\n"


@pytest.mark.asyncio
async def test_run_intake_marks_missing_route_resource_admission(
    tmp_path: Path,
) -> None:
    request = tmp_path / "REQ-INTAKE.md"
    _write_request(request)
    scores = {axis: 4 for axis in AXIS_WEIGHTS}

    with patch(
        "agents.deliberative_council.engine.deliberate",
        new=AsyncMock(return_value=_verdict(scores)),
    ):
        receipt = await run_intake(request)

    assert receipt.route_resource_admission == "missing"
    frontmatter, _body = parse_frontmatter(request)
    assert frontmatter["cctv_route_resource_admission"] == "missing"
    assert frontmatter["cctv_capability_receipts"] == []


@pytest.mark.asyncio
async def test_run_intake_preserves_request_body_exactly_on_writeback(tmp_path: Path) -> None:
    request = tmp_path / "REQ-INTAKE.md"
    frontmatter = {
        "type": "request",
        "request_id": "REQ-INTAKE",
        "title": "Intake target",
        "status": "captured",
    }
    body = "# Request\n\nKeep this evidence block intact.\n\n  \n"
    assert body.rstrip() != body
    request.write_text(
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\n{body}",
        encoding="utf-8",
    )
    scores = {axis: 4 for axis in AXIS_WEIGHTS}

    with patch(
        "agents.deliberative_council.engine.deliberate",
        new=AsyncMock(return_value=_verdict(scores)),
    ):
        await run_intake(request)

    _frontmatter, updated_body = parse_frontmatter(request)
    assert updated_body == body


@pytest.mark.asyncio
async def test_run_intake_non_ready_keeps_captured_and_records_failing_axes(
    tmp_path: Path,
) -> None:
    request = tmp_path / "REQ-INTAKE.md"
    _write_request(request)
    scores = {axis: 4 for axis in AXIS_WEIGHTS}
    scores["scope_boundedness"] = 2

    with patch(
        "agents.deliberative_council.engine.deliberate",
        new=AsyncMock(return_value=_verdict(scores)),
    ):
        receipt = await run_intake(request)

    assert receipt.verdict == IntakeVerdict.NEEDS_HARDENING
    frontmatter, _body = parse_frontmatter(request)
    assert frontmatter["status"] == "captured"
    assert frontmatter["cctv_intake_verdict"] == "needs_hardening"
    assert frontmatter["recommendation"] == "harden"
    assert frontmatter["axes"]["scope_boundedness"]["below_threshold"] is True
    assert frontmatter["failing_axes"] == [
        "scope_boundedness=2 (needs: explicit in/out boundaries)"
    ]


@pytest.mark.asyncio
async def test_run_intake_research_refs_route_to_research_needed(tmp_path: Path) -> None:
    request = tmp_path / "REQ-INTAKE.md"
    _write_request(request)
    frontmatter, body = parse_frontmatter(request)
    frontmatter["research_refs"] = ["docs/superpowers/research/example.md"]
    request.write_text(
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\n{body}",
        encoding="utf-8",
    )
    scores = {axis: 4 for axis in AXIS_WEIGHTS}
    scores["decomposability"] = 2

    with patch(
        "agents.deliberative_council.engine.deliberate",
        new=AsyncMock(return_value=_verdict(scores)),
    ):
        receipt = await run_intake(request)

    assert receipt.verdict == IntakeVerdict.RESEARCH_NEEDED
    updated, _body = parse_frontmatter(request)
    assert updated["status"] == "captured"
    assert updated["cctv_intake_verdict"] == "research_needed"
    assert updated["recommendation"] == "research_gate"
    assert updated["axes"]["decomposability"]["below_threshold"] is True


@pytest.mark.asyncio
async def test_run_intake_nullish_research_ref_containers_do_not_route_to_research_needed(
    tmp_path: Path,
) -> None:
    request = tmp_path / "REQ-INTAKE.md"
    _write_request(request)
    frontmatter, body = parse_frontmatter(request)
    frontmatter["research_refs"] = [None, ""]
    frontmatter["source_refs"] = {"primary": "none"}
    request.write_text(
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\n{body}",
        encoding="utf-8",
    )
    scores = {axis: 4 for axis in AXIS_WEIGHTS}
    scores["decomposability"] = 2

    with patch(
        "agents.deliberative_council.engine.deliberate",
        new=AsyncMock(return_value=_verdict(scores)),
    ):
        receipt = await run_intake(request)

    assert receipt.verdict == IntakeVerdict.NEEDS_HARDENING
    updated, _body = parse_frontmatter(request)
    assert updated["cctv_intake_verdict"] == "needs_hardening"
    assert updated["recommendation"] == "harden"


@pytest.mark.asyncio
async def test_run_intake_write_back_false_does_not_mutate_file(tmp_path: Path) -> None:
    request = tmp_path / "REQ-INTAKE.md"
    original = _write_request(request)
    scores = {axis: 4 for axis in AXIS_WEIGHTS}

    with patch(
        "agents.deliberative_council.engine.deliberate",
        new=AsyncMock(return_value=_verdict(scores)),
    ):
        receipt = await run_intake(request, write_back=False)

    assert receipt.verdict == IntakeVerdict.READY_TO_PLAN
    assert request.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_run_intake_raises_on_member_timeout_before_writeback(tmp_path: Path) -> None:
    request = tmp_path / "REQ-INTAKE.md"
    original = _write_request(request)
    scores = {axis: 4 for axis in AXIS_WEIGHTS}

    with patch(
        "agents.deliberative_council.engine.deliberate",
        new=AsyncMock(
            return_value=_verdict(
                scores,
                receipt={"failed_members": [{"model_alias": "opus", "reason": "TimeoutError"}]},
            )
        ),
    ):
        with pytest.raises(RuntimeError, match="intake council member timeout.*opus"):
            await run_intake(request)

    assert request.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_run_intake_refuses_partial_axes_before_writeback(tmp_path: Path) -> None:
    request = tmp_path / "REQ-INTAKE.md"
    original = _write_request(request)
    scores = {axis: 4 for axis in AXIS_WEIGHTS}
    scores["singularity"] = None

    with patch(
        "agents.deliberative_council.engine.deliberate",
        new=AsyncMock(return_value=_verdict(scores)),
    ):
        with pytest.raises(IntakeContractError, match="COUNCIL_REFUSED partial_axis_scores"):
            await run_intake(request)

    assert request.read_text(encoding="utf-8") == original
