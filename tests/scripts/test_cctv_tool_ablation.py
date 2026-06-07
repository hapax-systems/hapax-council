from __future__ import annotations

import json

import pytest

from agents.deliberative_council.members import ToolLevel
from agents.deliberative_council.models import PhaseOneResult
from scripts.cctv_tool_ablation import (
    HOME_PATH,
    AblationProbe,
    _budgeted_investigation_prompt,
    _redact_home_paths,
    load_self_test_probes,
    run_ablation,
)


def _write_self_test_jsonl(path, *, count: int = 13) -> None:
    rows = []
    for index in range(1, count + 1):
        rows.append(
            {
                "claim_id": f"CLAIM-{index}",
                "claim_text": f"Claim text {index}",
                "source_ref": None if index == 1 else f"source-{index}.md",
                "domain": "test-domain",
            }
        )
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_load_self_test_probes_requires_13_claims(tmp_path) -> None:
    path = tmp_path / "self-test.jsonl"
    _write_self_test_jsonl(path)

    probes = load_self_test_probes(path)

    assert len(probes) == 13
    assert probes[0].probe_id == "CLAIM-1"
    assert probes[0].source_ref == str(path)
    assert probes[1].source_ref == "source-2.md"
    assert "domain=test-domain" in probes[0].notes


def test_load_self_test_probes_rejects_partial_corpus(tmp_path) -> None:
    path = tmp_path / "self-test.jsonl"
    _write_self_test_jsonl(path, count=12)

    with pytest.raises(ValueError, match="expected 13 self-test probes"):
        load_self_test_probes(path)


@pytest.mark.asyncio
async def test_dry_run_plans_13_by_3_conditions(tmp_path) -> None:
    path = tmp_path / "self-test.jsonl"
    out = tmp_path / "ablation.json"
    _write_self_test_jsonl(path)

    summary = await run_ablation(dry_run=True, input_path=path, output_path=out, tool_budget=4)

    assert summary["probes_run"] == 13
    assert summary["tool_budget"] == 4
    assert summary["condition_runs_planned"] == 39
    assert summary["condition_runs_recorded"] == 39
    assert summary["condition_runs_completed"] == 0
    assert summary["condition_runs_partial"] == 0
    assert summary["condition_runs_usable"] == 0
    assert summary["delta_pairs_usable"] == 0
    assert summary["decision"] == "insufficient_data"
    assert out.is_file()


@pytest.mark.asyncio
async def test_records_distributions_and_material_decision(tmp_path) -> None:
    probes = [AblationProbe("P1", "A test claim", "source.md")]
    out = tmp_path / "ablation.json"

    async def runner(inp, rubric, config, condition):
        score = {"full": 4, "restricted": 3, "none": 2}[condition.value]
        return [
            PhaseOneResult(
                model_alias=alias,
                scores={axis.name: score for axis in rubric.axes},
                rationale={},
                research_findings=[],
                tool_calls_log=[f"{condition.value}:{alias}:tool"],
            )
            for alias in config.model_aliases
        ]

    summary = await run_ablation(probes=probes, output_path=out, runner=runner)

    assert summary["mean_delta"] == 2.0
    assert summary["decision"] == "tools_material_keep_full_tooling"
    full = summary["results"][0]["conditions"]["full"]
    assert full["axis_scores"]["evidence_adequacy"] == [4, 4, 4]
    assert full["mean_scores"]["evidence_adequacy"] == 4.0
    assert full["models_responded"] == 3
    assert full["tool_calls_total"] == 3


@pytest.mark.asyncio
async def test_resume_skips_completed_conditions(tmp_path) -> None:
    probes = [AblationProbe("P1", "A test claim", "source.md")]
    out = tmp_path / "ablation.json"
    calls: list[str] = []

    async def runner(inp, rubric, config, condition):
        calls.append(condition.value)
        return [
            PhaseOneResult(
                model_alias="opus",
                scores={axis.name: 4 if condition is ToolLevel.FULL else 2 for axis in rubric.axes},
                rationale={},
                research_findings=[],
            )
        ]

    await run_ablation(
        probes=probes,
        output_path=out,
        conditions=(ToolLevel.FULL,),
        model_aliases=("opus",),
        runner=runner,
    )
    await run_ablation(
        probes=probes,
        output_path=out,
        conditions=(ToolLevel.FULL, ToolLevel.NONE),
        model_aliases=("opus",),
        runner=runner,
    )

    assert calls == ["full", "none"]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data["results"][0]["conditions"]) == {"full", "none"}


@pytest.mark.asyncio
async def test_failed_condition_is_recorded_but_retryable(tmp_path) -> None:
    probes = [AblationProbe("P1", "A test claim", "source.md")]
    out = tmp_path / "ablation.json"
    calls: list[str] = []

    async def failing_runner(inp, rubric, config, condition):
        calls.append(condition.value)
        return []

    await run_ablation(
        probes=probes,
        output_path=out,
        conditions=(ToolLevel.FULL,),
        model_aliases=("opus",),
        runner=failing_runner,
    )
    await run_ablation(
        probes=probes,
        output_path=out,
        conditions=(ToolLevel.FULL,),
        model_aliases=("opus",),
        runner=failing_runner,
    )

    assert calls == ["full", "full"]
    data = json.loads(out.read_text(encoding="utf-8"))
    full = data["results"][0]["conditions"]["full"]
    assert full["status"] == "failed"
    assert full["error"] == "no_models_responded"
    assert data["condition_runs_recorded"] == 1
    assert data["condition_runs_completed"] == 0
    assert data["condition_runs_partial"] == 0
    assert data["condition_runs_usable"] == 0


@pytest.mark.asyncio
async def test_partial_condition_is_retryable_and_usable_for_decision(tmp_path) -> None:
    probes = [AblationProbe("P1", "A test claim", "source.md")]
    out = tmp_path / "ablation.json"
    calls: list[str] = []

    async def partial_runner(inp, rubric, config, condition):
        calls.append(condition.value)
        return [
            PhaseOneResult(
                model_alias="opus",
                scores={axis.name: 4 for axis in rubric.axes},
                rationale={},
                research_findings=[],
            )
        ]

    await run_ablation(
        probes=probes,
        output_path=out,
        conditions=(ToolLevel.FULL, ToolLevel.NONE),
        model_aliases=("opus", "balanced"),
        runner=partial_runner,
    )
    summary = await run_ablation(
        probes=probes,
        output_path=out,
        conditions=(ToolLevel.FULL, ToolLevel.NONE),
        model_aliases=("opus", "balanced"),
        runner=partial_runner,
    )

    assert calls == ["full", "none", "full", "none"]
    assert summary["condition_runs_completed"] == 0
    assert summary["condition_runs_partial"] == 2
    assert summary["condition_runs_usable"] == 2
    assert summary["delta_pairs_usable"] == 1
    assert summary["mean_delta"] == 0.0
    assert summary["decision"] == "tools_not_material_simplification_candidate"
    full = summary["results"][0]["conditions"]["full"]
    assert full["status"] == "partial"
    assert full["models_expected"] == 2
    assert full["models_responded"] == 1
    assert full["models_missing"] == ["balanced"]


@pytest.mark.asyncio
async def test_accept_partial_skips_retryable_partials(tmp_path) -> None:
    probes = [AblationProbe("P1", "A test claim", "source.md")]
    out = tmp_path / "ablation.json"
    calls: list[str] = []

    async def partial_runner(inp, rubric, config, condition):
        calls.append(condition.value)
        return [
            PhaseOneResult(
                model_alias="opus",
                scores={axis.name: 3 for axis in rubric.axes},
                rationale={},
                research_findings=[],
            )
        ]

    await run_ablation(
        probes=probes,
        output_path=out,
        conditions=(ToolLevel.NONE,),
        model_aliases=("opus", "balanced"),
        runner=partial_runner,
    )
    await run_ablation(
        probes=probes,
        output_path=out,
        conditions=(ToolLevel.NONE,),
        model_aliases=("opus", "balanced"),
        accept_partial=True,
        runner=partial_runner,
    )

    assert calls == ["none"]


@pytest.mark.asyncio
async def test_resume_preserves_existing_elapsed_time(tmp_path) -> None:
    probes = [AblationProbe("P1", "A test claim", "source.md")]
    out = tmp_path / "ablation.json"

    async def runner(inp, rubric, config, condition):
        return [
            PhaseOneResult(
                model_alias="opus",
                scores={axis.name: 3 for axis in rubric.axes},
                rationale={},
                research_findings=[],
            )
        ]

    await run_ablation(
        probes=probes,
        output_path=out,
        conditions=(ToolLevel.NONE,),
        model_aliases=("opus",),
        runner=runner,
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    data["elapsed_s"] = 42.5
    out.write_text(json.dumps(data), encoding="utf-8")

    summary = await run_ablation(
        probes=probes,
        output_path=out,
        conditions=(ToolLevel.NONE,),
        model_aliases=("opus",),
        runner=runner,
    )

    assert summary["elapsed_s"] >= 42.5


def test_budgeted_investigation_prompt_scopes_tool_loop() -> None:
    prompt = "You are a council member. FIRST, investigate the source material using tools."

    budgeted = _budgeted_investigation_prompt(prompt, tool_budget=4)
    score_prompt = _budgeted_investigation_prompt(
        "Score based on your research above.", tool_budget=4
    )

    assert "Use at most 4 total tool calls" in str(budgeted)
    assert "start with `read_source`" in str(budgeted)
    assert "avoid broad workspace" in str(budgeted)
    assert score_prompt == "Score based on your research above."


def test_redact_home_paths_in_nested_summary() -> None:
    redacted = _redact_home_paths(
        {
            "source_ref": f"{HOME_PATH}/projects/hapax-research/file.jsonl",
            "tool_calls": [f"read_source({HOME_PATH}/projects/hapax-research/file.jsonl)"],
        }
    )

    assert redacted == {
        "source_ref": "~/projects/hapax-research/file.jsonl",
        "tool_calls": ["read_source(~/projects/hapax-research/file.jsonl)"],
    }
