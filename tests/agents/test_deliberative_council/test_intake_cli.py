from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from agents.deliberative_council import __main__ as council_cli
from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilMode,
    CouncilVerdict,
)
from agents.deliberative_council.modes.intake import (
    AXIS_WEIGHTS,
    AxisResult,
    IntakeReceipt,
    IntakeRecommendation,
    IntakeVerdict,
    run_intake,
)
from agents.deliberative_council.rubrics import IntakeHardeningRubric
from shared.frontmatter import parse_frontmatter


def _write_request(path: Path, *, status: str = "captured") -> str:
    frontmatter = {
        "type": "hapax-request",
        "request_id": "REQ-INTAKE-CLI",
        "title": "Intake CLI target",
        "status": status,
    }
    body = "# Request\n\nBuild a concrete intake artifact with a pytest check.\n"
    text = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\n{body}"
    path.write_text(text, encoding="utf-8")
    return text


def _scores(value: int) -> dict[str, int | None]:
    return {axis: value for axis in AXIS_WEIGHTS}


def _axis_results(value: int) -> tuple[AxisResult, ...]:
    return tuple(AxisResult(name=axis, score=value) for axis in AXIS_WEIGHTS)


def _council_verdict(
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


@pytest.mark.asyncio
async def test_run_intake_returns_receipt_and_ready_advances_status(tmp_path: Path) -> None:
    request = tmp_path / "REQ-INTAKE-CLI.md"
    _write_request(request)

    with patch(
        "agents.deliberative_council.engine.deliberate",
        new=AsyncMock(return_value=_council_verdict(_scores(4))),
    ) as deliberate_mock:
        receipt = await run_intake(request)

    assert isinstance(receipt, IntakeReceipt)
    assert receipt.verdict == IntakeVerdict.READY_TO_PLAN
    assert receipt.request_path == str(request)
    assert receipt.composite_score == pytest.approx(4.0)

    inp, mode, rubric, config = deliberate_mock.await_args.args
    assert inp.text == "# Request\n\nBuild a concrete intake artifact with a pytest check.\n"
    assert inp.source_ref == str(request)
    assert mode == CouncilMode.INTAKE
    assert isinstance(rubric, IntakeHardeningRubric)
    assert isinstance(config, CouncilConfig)

    frontmatter, body = parse_frontmatter(request)
    assert frontmatter["status"] == "accepted_for_planning"
    assert frontmatter["cctv_intake_verdict"] == "ready_to_plan"
    assert frontmatter["recommendation"] == "advance"
    assert set(frontmatter["axes"]) == set(AXIS_WEIGHTS)
    assert all(isinstance(axis["score"], int) for axis in frontmatter["axes"].values())
    assert frontmatter["axes"]["outcome_concreteness"]["score"] == 4
    assert body == "# Request\n\nBuild a concrete intake artifact with a pytest check.\n"


@pytest.mark.asyncio
async def test_run_intake_non_ready_keeps_captured_and_records_axes(tmp_path: Path) -> None:
    request = tmp_path / "REQ-INTAKE-CLI.md"
    _write_request(request)
    scores = _scores(4)
    scores["scope_boundedness"] = 2

    with patch(
        "agents.deliberative_council.engine.deliberate",
        new=AsyncMock(return_value=_council_verdict(scores)),
    ):
        receipt = await run_intake(request)

    assert receipt.verdict == IntakeVerdict.NEEDS_HARDENING
    frontmatter, _body = parse_frontmatter(request)
    assert frontmatter["status"] == "captured"
    assert frontmatter["cctv_intake_verdict"] == "needs_hardening"
    assert frontmatter["recommendation"] == "harden"
    assert frontmatter["axes"]["scope_boundedness"] == {
        "score": 2,
        "label": "explicit in/out boundaries",
        "below_threshold": True,
    }
    assert frontmatter["failing_axes"] == [
        "scope_boundedness=2 (needs: explicit in/out boundaries)"
    ]


@pytest.mark.asyncio
async def test_run_intake_write_back_false_leaves_file_unchanged(tmp_path: Path) -> None:
    request = tmp_path / "REQ-INTAKE-CLI.md"
    original = _write_request(request)

    with patch(
        "agents.deliberative_council.engine.deliberate",
        new=AsyncMock(return_value=_council_verdict(_scores(4))),
    ):
        receipt = await run_intake(request, write_back=False)

    assert receipt.verdict == IntakeVerdict.READY_TO_PLAN
    assert request.read_text(encoding="utf-8") == original


def test_cli_dry_run_prints_all_axes_and_does_not_mutate_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = tmp_path / "REQ-INTAKE-CLI.md"
    original = _write_request(request)

    async def fake_run_intake(
        request_path: str | Path,
        *,
        config: CouncilConfig | None = None,
        write_back: bool = True,
    ) -> IntakeReceipt:
        assert request_path == request
        assert isinstance(config, CouncilConfig)
        assert write_back is False
        return IntakeReceipt(
            request_id="REQ-INTAKE-CLI",
            request_path=str(request_path),
            verdict=IntakeVerdict.READY_TO_PLAN,
            recommendation=IntakeRecommendation.ADVANCE,
            axis_results=_axis_results(4),
            composite_score=4.0,
            convergence_status=ConvergenceStatus.CONVERGED,
        )

    monkeypatch.setattr(
        sys,
        "argv",
        ["council", "--mode", "intake", "--input", str(request), "--dry-run"],
    )
    with patch("agents.deliberative_council.modes.intake.run_intake", side_effect=fake_run_intake):
        council_cli.main()

    captured = capsys.readouterr()
    assert "verdict=ready_to_plan" in captured.out
    assert "recommendation=advance" in captured.out
    assert "convergence=converged" in captured.out
    for axis in AXIS_WEIGHTS:
        assert f"{axis}=4" in captured.out
    assert request.read_text(encoding="utf-8") == original


def test_cli_models_single_member_forwarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = tmp_path / "REQ-INTAKE-CLI.md"
    _write_request(request)
    seen_configs: list[CouncilConfig] = []

    async def fake_run_intake(
        request_path: str | Path,
        *,
        config: CouncilConfig | None = None,
        write_back: bool = True,
    ) -> IntakeReceipt:
        assert request_path == request
        assert write_back is True
        assert config is not None
        seen_configs.append(config)
        return IntakeReceipt(
            request_id="REQ-INTAKE-CLI",
            request_path=str(request_path),
            verdict=IntakeVerdict.READY_TO_PLAN,
            recommendation=IntakeRecommendation.ADVANCE,
            axis_results=_axis_results(4),
            composite_score=4.0,
            convergence_status=ConvergenceStatus.CONVERGED,
        )

    monkeypatch.setattr(
        sys,
        "argv",
        ["council", "--mode", "intake", "--input", str(request), "--models", "opus"],
    )
    with patch("agents.deliberative_council.modes.intake.run_intake", side_effect=fake_run_intake):
        council_cli.main()

    assert len(seen_configs) == 1
    assert seen_configs[0].model_aliases == ("opus",)
    assert seen_configs[0].min_valid_members == 1
    assert seen_configs[0].min_valid_families == 1
    assert seen_configs[0].min_axis_values == 1


def test_cli_default_uses_quorum_preserving_council_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = tmp_path / "REQ-INTAKE-CLI.md"
    _write_request(request)
    seen_configs: list[CouncilConfig] = []

    async def fake_run_intake(
        request_path: str | Path,
        *,
        config: CouncilConfig | None = None,
        write_back: bool = True,
    ) -> IntakeReceipt:
        assert request_path == request
        assert config is not None
        seen_configs.append(config)
        return IntakeReceipt(
            request_id="REQ-INTAKE-CLI",
            request_path=str(request_path),
            verdict=IntakeVerdict.READY_TO_PLAN,
            recommendation=IntakeRecommendation.ADVANCE,
            axis_results=_axis_results(4),
            composite_score=4.0,
            convergence_status=ConvergenceStatus.CONVERGED,
        )

    monkeypatch.setattr(sys, "argv", ["council", "--mode", "intake", "--input", str(request)])
    with patch("agents.deliberative_council.modes.intake.run_intake", side_effect=fake_run_intake):
        council_cli.main()

    assert len(seen_configs) == 1
    assert seen_configs[0].model_aliases == CouncilConfig().model_aliases
    assert seen_configs[0].min_valid_members >= 4
    assert seen_configs[0].min_valid_families >= 4


def test_captured_request_paths_filters_directly_on_type_and_status(tmp_path: Path) -> None:
    request = tmp_path / "REQ-INTAKE-CLI.md"
    _write_request(request)
    unrelated = tmp_path / "note.md"
    unrelated.write_text("---\ntype: note\nstatus: captured\n---\n\n# Note\n", encoding="utf-8")
    draft_request = tmp_path / "REQ-DRAFT.md"
    _write_request(draft_request, status="accepted_for_planning")

    assert council_cli._captured_request_paths(tmp_path) == [request]


def test_cli_scan_only_collects_hapax_request_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = tmp_path / "REQ-INTAKE-CLI.md"
    _write_request(request)
    unrelated = tmp_path / "note.md"
    unrelated.write_text("---\ntype: note\nstatus: captured\n---\n\n# Note\n", encoding="utf-8")
    seen_paths: list[Path] = []

    async def fake_run_intake(
        request_path: str | Path,
        *,
        config: CouncilConfig | None = None,
        write_back: bool = True,
    ) -> IntakeReceipt:
        seen_paths.append(Path(request_path))
        return IntakeReceipt(
            request_id="REQ-INTAKE-CLI",
            request_path=str(request_path),
            verdict=IntakeVerdict.READY_TO_PLAN,
            recommendation=IntakeRecommendation.ADVANCE,
            axis_results=_axis_results(4),
            composite_score=4.0,
            convergence_status=ConvergenceStatus.CONVERGED,
        )

    monkeypatch.setenv("HAPAX_REQUESTS_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["council", "--mode", "intake", "--scan"])
    with patch("agents.deliberative_council.modes.intake.run_intake", side_effect=fake_run_intake):
        council_cli.main()

    assert seen_paths == [request]


def test_cli_member_timeout_surfaces_stderr_and_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = tmp_path / "REQ-INTAKE-CLI.md"
    original = _write_request(request)

    async def fake_run_intake(
        request_path: str | Path,
        *,
        config: CouncilConfig | None = None,
        write_back: bool = True,
    ) -> IntakeReceipt:
        raise RuntimeError(f"intake council member timeout for {Path(request_path).stem}: opus")

    monkeypatch.setattr(sys, "argv", ["council", "--mode", "intake", "--input", str(request)])
    with (
        patch("agents.deliberative_council.modes.intake.run_intake", side_effect=fake_run_intake),
        pytest.raises(SystemExit) as exc_info,
    ):
        council_cli.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "opus" in captured.err
    assert "timeout" in captured.err
    assert request.read_text(encoding="utf-8") == original


def test_cli_refused_all_models_failed_is_nonzero_and_does_not_write_null_axes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = tmp_path / "REQ-INTAKE-CLI.md"
    original = _write_request(request)
    refused = _council_verdict(
        {axis: None for axis in AXIS_WEIGHTS},
        convergence=ConvergenceStatus.REFUSED,
        receipt={"refusal_reason": "all_models_failed"},
    )

    monkeypatch.setattr(sys, "argv", ["council", "--mode", "intake", "--input", str(request)])
    with (
        patch("agents.deliberative_council.engine.deliberate", new=AsyncMock(return_value=refused)),
        pytest.raises(SystemExit) as exc_info,
    ):
        council_cli.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "COUNCIL_REFUSED all_models_failed" in captured.err
    assert request.read_text(encoding="utf-8") == original
    frontmatter, _body = parse_frontmatter(request)
    assert "cctv_intake_verdict" not in frontmatter
    assert "axes" not in frontmatter


def test_existing_labeling_ratify_and_audit_modes_still_invoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("[]", encoding="utf-8")
    output = tmp_path / "labels.json"
    review_queue = tmp_path / "review.json"
    ratification = tmp_path / "ratification.json"

    monkeypatch.setattr(
        sys,
        "argv",
        ["council", "--mode", "labeling", "--input", str(manifest), "--output", str(output)],
    )
    with patch(
        "agents.deliberative_council.modes.labeling.run_labeling",
        new=AsyncMock(return_value=([], [])),
    ) as labeling:
        council_cli.main()
    labeling.assert_awaited_once()
    assert "Labeled: 0 ratified" in capsys.readouterr().out

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "council",
            "--mode",
            "ratify",
            "--review-queue",
            str(review_queue),
            "--ratification",
            str(ratification),
            "--manifest",
            str(manifest),
            "--output",
            str(output),
        ],
    )
    with patch(
        "agents.deliberative_council.modes.labeling.run_ratification", return_value=[]
    ) as ratify:
        council_cli.main()
    ratify.assert_called_once()
    assert "Ratified: 0 records written" in capsys.readouterr().out

    monkeypatch.setattr(
        sys, "argv", ["council", "--mode", "audit", "--scope", str(tmp_path), "--dry-run"]
    )
    council_cli.main()
    assert "Audit dry-run:" in capsys.readouterr().out
