"""CCTV tool-level ablation: compare FULL vs RESTRICTED vs NONE.

Runs the same CCTV self-test claims under three tool conditions to measure the
evidence delta that tools provide. The default corpus is the durable 13-claim
V1 self-test JSONL in hapax-research.

Usage:
    uv run python scripts/cctv_tool_ablation.py [--dry-run] [--probes N]

Output: benchmarks/cctv-rubric-v2/ablation-<timestamp>.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from agents.deliberative_council.engine import run_phase1
from agents.deliberative_council.members import ToolLevel
from agents.deliberative_council.models import CouncilConfig, CouncilInput, PhaseOneResult
from agents.deliberative_council.rubrics import DisconfirmationRubric

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "cctv-rubric-v2"
DEFAULT_SELF_TEST_VERDICTS = (
    Path.home() / "projects/hapax-research/datasets/epistemic-quality/cctv-self-test-verdicts.jsonl"
)
DEFAULT_MODELS = ("opus", "balanced", "gemini-3-pro")
DEFAULT_CONDITIONS = (ToolLevel.FULL, ToolLevel.RESTRICTED, ToolLevel.NONE)
MATERIAL_DELTA_THRESHOLD = 0.5
DEFAULT_TOOL_BUDGET = 6
HOME_PATH = str(Path.home())


@dataclass(frozen=True)
class AblationProbe:
    probe_id: str
    text: str
    source_ref: str
    notes: str = ""


Phase1Runner = Callable[
    [CouncilInput, DisconfirmationRubric, CouncilConfig, ToolLevel],
    Awaitable[list[PhaseOneResult]],
]


LEGACY_PROBES = (
    AblationProbe(
        probe_id="private_claim_fabricated_path",
        text=(
            "The governance system validates all agent outputs through "
            "shared/governance/output_validator.py which enforces axiom "
            "compliance before any external emission."
        ),
        source_ref="shared/governance/output_validator.py",
        notes="File does not exist. Tools should discover this.",
    ),
    AblationProbe(
        probe_id="private_claim_real_file",
        text=(
            "The evil pet state module at shared/evil_pet_state.py implements "
            "a 15-second heartbeat timeout for crash recovery, using atomic "
            "tmp+rename writes on tmpfs."
        ),
        source_ref="shared/evil_pet_state.py",
        notes="File exists, claims are verifiable. Tools should confirm.",
    ),
    AblationProbe(
        probe_id="private_claim_partial_truth",
        text=(
            "The affordance pipeline indexes all capabilities in Qdrant and "
            "uses Thompson sampling with Beta(2,1) priors clamped to [1,10] "
            "for selection. The pipeline achieves 100% recall on indexed "
            "affordances."
        ),
        source_ref="shared/affordance_pipeline.py",
        notes="Implementation details verifiable; 100% recall claim is not.",
    ),
    AblationProbe(
        probe_id="external_claim_unverifiable",
        text=(
            "According to the Loewenstein (1994) information gap theory, "
            "curiosity arises from a perceived gap between what one knows "
            "and what one wants to know. This system exploits that mechanism."
        ),
        source_ref="docs/research/narrative-theory.md",
        notes="External citation. Tools may not help without web access.",
    ),
    AblationProbe(
        probe_id="mixed_verifiable_unverifiable",
        text=(
            "The vocal chain maps 9 semantic dimensions to MIDI CCs "
            "(agents/hapax_daimonion/vocal_chain.py). Each dimension's CC "
            "range was validated through A/B listening tests with 12 "
            "participants showing 94% intelligibility at max activation."
        ),
        source_ref="agents/hapax_daimonion/vocal_chain.py",
        notes="First sentence verifiable (code exists). A/B test claim is fabricated.",
    ),
)


def _default_self_test_path() -> Path:
    override = os.environ.get("HAPAX_CCTV_SELF_TEST_VERDICTS")
    return Path(override).expanduser() if override else DEFAULT_SELF_TEST_VERDICTS


def _display_path(path: Path) -> str:
    raw = str(path)
    return raw.replace(HOME_PATH, "~", 1) if raw.startswith(HOME_PATH) else raw


def load_self_test_probes(path: Path | None = None) -> list[AblationProbe]:
    source = path or _default_self_test_path()
    probes: list[AblationProbe] = []
    with source.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            record = json.loads(raw)
            claim_id = str(record.get("claim_id") or f"line-{line_number}")
            text = str(record.get("claim_text") or record.get("text") or "").strip()
            if not text:
                raise ValueError(f"{source}:{line_number} missing claim_text")
            source_ref = str(record.get("source_ref") or _display_path(source))
            domain = record.get("domain")
            notes = "V1 CCTV self-test claim"
            if domain:
                notes = f"{notes}; domain={domain}"
            probes.append(
                AblationProbe(
                    probe_id=claim_id,
                    text=text,
                    source_ref=source_ref,
                    notes=notes,
                )
            )
    if len(probes) != 13:
        raise ValueError(f"expected 13 self-test probes in {source}, found {len(probes)}")
    return probes


def select_probes(*, corpus: str, input_path: Path | None = None) -> list[AblationProbe]:
    if corpus == "legacy":
        return list(LEGACY_PROBES)
    if corpus == "self-test":
        return load_self_test_probes(input_path)
    raise ValueError(f"unknown corpus {corpus!r}")


def _parse_conditions(raw: str) -> tuple[ToolLevel, ...]:
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if not names:
        raise ValueError("at least one condition is required")
    return tuple(ToolLevel(name) for name in names)


def _parse_models(raw: str) -> tuple[str, ...]:
    models = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not models:
        raise ValueError("at least one model alias is required")
    return models


def _member_timeout_override_s() -> float | None:
    raw = os.environ.get("HAPAX_CCTV_MEMBER_TIMEOUT_S")
    if raw is None or not raw.strip():
        return None
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise ValueError("HAPAX_CCTV_MEMBER_TIMEOUT_S must be numeric") from exc
    if timeout <= 0:
        raise ValueError("HAPAX_CCTV_MEMBER_TIMEOUT_S must be positive")
    return timeout


def _tool_budget_override() -> int | None:
    raw = os.environ.get("HAPAX_CCTV_TOOL_BUDGET")
    if raw is None or not raw.strip():
        return None
    try:
        budget = int(raw)
    except ValueError as exc:
        raise ValueError("HAPAX_CCTV_TOOL_BUDGET must be an integer") from exc
    if budget <= 0:
        raise ValueError("HAPAX_CCTV_TOOL_BUDGET must be positive")
    return budget


def _budgeted_investigation_prompt(prompt: object, *, tool_budget: int | None) -> object:
    if tool_budget is None or not isinstance(prompt, str):
        return prompt
    if "FIRST, investigate the source material" not in prompt:
        return prompt
    return (
        prompt
        + "\n\n## Ablation Evidence Budget\n"
        + f"Use at most {tool_budget} total tool calls for this investigation. "
        + "If tools are available, start with `read_source` on the given source_ref. "
        + "Prefer the source_ref and adjacent dataset or repo files; avoid broad workspace, "
        + "home-directory, or root searches. Stop once you have enough evidence to score, "
        + "and report remaining uncertainty instead of continuing to search."
    )


def _existing_summary(output_path: Path | None, *, resume: bool) -> dict:
    if not resume or output_path is None or not output_path.is_file():
        return {}
    try:
        return dict(json.loads(output_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return {}


def _existing_results(existing_summary: dict) -> list[dict]:
    results = existing_summary.get("results")
    return list(results) if isinstance(results, list) else []


def _existing_elapsed_s(existing_summary: dict) -> float:
    try:
        return float(existing_summary.get("elapsed_s") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _condition_done(
    results: list[dict],
    probe_id: str,
    condition: ToolLevel,
    *,
    expected_models: int,
    accept_partial: bool,
) -> bool:
    for result in results:
        if result.get("probe_id") != probe_id:
            continue
        conditions = result.get("conditions")
        if not isinstance(conditions, dict):
            return False
        entry = conditions.get(condition.value)
        if not isinstance(entry, dict):
            return False
        if entry.get("status") == "failed":
            return False
        if entry.get("status") == "partial":
            return accept_partial and int(entry.get("models_responded") or 0) > 0
        if entry.get("dry_run"):
            return True
        return int(entry.get("models_responded") or 0) >= expected_models
    return False


def _is_completed_entry(entry: object, *, expected_models: int) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("status") not in {"completed", None}:
        return False
    return int(entry.get("models_responded") or 0) >= expected_models


def _is_usable_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("status") not in {"completed", "partial", None}:
        return False
    return int(entry.get("models_responded") or 0) > 0


def _result_for_probe(results: list[dict], probe: AblationProbe) -> dict:
    for result in results:
        if result.get("probe_id") == probe.probe_id:
            return result
    result = {
        "probe_id": probe.probe_id,
        "source_ref": probe.source_ref,
        "notes": probe.notes,
        "conditions": {},
    }
    results.append(result)
    return result


def _axis_distributions(
    phase1: Sequence[PhaseOneResult],
    rubric: DisconfirmationRubric,
) -> tuple[dict[str, list[int]], dict[str, float]]:
    axis_scores: dict[str, list[int]] = {}
    axis_means: dict[str, float] = {}
    for axis in rubric.axes:
        scores = [r.scores[axis.name] for r in phase1 if axis.name in r.scores]
        if scores:
            axis_scores[axis.name] = scores
            axis_means[axis.name] = round(sum(scores) / len(scores), 2)
    return axis_scores, axis_means


def _summary(
    *,
    rubric: DisconfirmationRubric,
    probes: Sequence[AblationProbe],
    conditions: Sequence[ToolLevel],
    model_aliases: Sequence[str],
    results: list[dict],
    elapsed_s: float,
    corpus: str,
    input_path: Path | None,
    tool_budget: int | None,
) -> dict:
    deltas: list[dict] = []
    expected_models = len(model_aliases)
    for result in results:
        conds = result.get("conditions", {})
        full_entry = conds.get("full", {})
        none_entry = conds.get("none", {})
        full = full_entry.get("overall_mean", 0)
        none = none_entry.get("overall_mean", 0)
        if _is_usable_entry(full_entry) and _is_usable_entry(none_entry):
            deltas.append(
                {
                    "probe_id": result["probe_id"],
                    "full_minus_none": round(full - none, 2),
                }
            )

    mean_delta = (
        round(sum(delta["full_minus_none"] for delta in deltas) / len(deltas), 2)
        if deltas
        else None
    )
    if mean_delta is None:
        decision = "insufficient_data"
    elif abs(mean_delta) >= MATERIAL_DELTA_THRESHOLD:
        decision = "tools_material_keep_full_tooling"
    else:
        decision = "tools_not_material_simplification_candidate"

    recorded = sum(
        1
        for result in results
        for condition in conditions
        if condition.value in result.get("conditions", {})
    )
    completed = sum(
        1
        for result in results
        for condition in conditions
        if _is_completed_entry(
            result.get("conditions", {}).get(condition.value),
            expected_models=expected_models,
        )
    )
    partial = sum(
        1
        for result in results
        for condition in conditions
        if result.get("conditions", {}).get(condition.value, {}).get("status") == "partial"
    )
    usable = sum(
        1
        for result in results
        for condition in conditions
        if _is_usable_entry(result.get("conditions", {}).get(condition.value))
    )
    return {
        "rubric": rubric.name,
        "rubric_version": rubric.version,
        "corpus": corpus,
        "input_path": str(input_path or _default_self_test_path() if corpus == "self-test" else ""),
        "conditions": [condition.value for condition in conditions],
        "model_aliases": list(model_aliases),
        "tool_budget": tool_budget,
        "probes_run": len(probes),
        "condition_runs_planned": len(probes) * len(conditions),
        "condition_runs_recorded": recorded,
        "condition_runs_completed": completed,
        "condition_runs_partial": partial,
        "condition_runs_usable": usable,
        "delta_pairs_usable": len(deltas),
        "elapsed_s": round(elapsed_s, 1),
        "deltas": deltas,
        "mean_delta": mean_delta,
        "material_delta_threshold": MATERIAL_DELTA_THRESHOLD,
        "decision": decision,
        "results": results,
    }


def _write_summary(output_path: Path, summary: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_redact_home_paths(summary), indent=2) + "\n", encoding="utf-8"
    )


def _redact_home_paths(value: object) -> object:
    if isinstance(value, str):
        return value.replace(HOME_PATH, "~")
    if isinstance(value, list):
        return [_redact_home_paths(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_home_paths(item) for key, item in value.items()}
    return value


async def default_phase1_runner(
    inp: CouncilInput,
    rubric: DisconfirmationRubric,
    config: CouncilConfig,
    condition: ToolLevel,
) -> list[PhaseOneResult]:
    from unittest.mock import patch

    from agents.deliberative_council import engine as council_engine
    from agents.deliberative_council.members import build_member

    def _build_with_level(alias: str, tool_level: ToolLevel | None = None) -> object:
        return build_member(alias, tool_level=condition)

    tool_budget = _tool_budget_override()
    timeout_s = _member_timeout_override_s()
    original_call_member = council_engine._call_member

    async def _call_member_with_budget(member: object, prompt: object) -> tuple[str, list[str]]:
        budgeted_prompt = _budgeted_investigation_prompt(prompt, tool_budget=tool_budget)
        return await original_call_member(member, budgeted_prompt)  # type: ignore[arg-type]

    with ExitStack() as stack:
        stack.enter_context(
            patch("agents.deliberative_council.engine.build_member", _build_with_level)
        )
        if tool_budget is not None:
            stack.enter_context(
                patch("agents.deliberative_council.engine._call_member", _call_member_with_budget)
            )
        if timeout_s is not None:
            stack.enter_context(
                patch("agents.deliberative_council.engine._MEMBER_TIMEOUT_S", timeout_s)
            )
        return await run_phase1(inp, rubric, config)


async def run_ablation(
    *,
    dry_run: bool = False,
    max_probes: int | None = None,
    probes: Sequence[AblationProbe] | None = None,
    corpus: str = "self-test",
    input_path: Path | None = None,
    output_path: Path | None = None,
    conditions: Sequence[ToolLevel] = DEFAULT_CONDITIONS,
    model_aliases: Sequence[str] = DEFAULT_MODELS,
    resume: bool = True,
    tool_budget: int | None = None,
    accept_partial: bool = False,
    runner: Phase1Runner = default_phase1_runner,
) -> dict:
    rubric = DisconfirmationRubric()
    selected = (
        list(probes) if probes is not None else select_probes(corpus=corpus, input_path=input_path)
    )
    selected = selected[:max_probes] if max_probes else selected
    if output_path is None:
        ts = time.strftime("%Y%m%dT%H%M%S")
        output_path = RESULTS_DIR / f"ablation-{ts}.json"

    existing_summary = _existing_summary(output_path, resume=resume)
    results = _existing_results(existing_summary)
    previous_elapsed_s = _existing_elapsed_s(existing_summary)
    start = time.time()

    for probe in selected:
        probe_result = _result_for_probe(results, probe)

        for condition in conditions:
            if _condition_done(
                results,
                probe.probe_id,
                condition,
                expected_models=len(model_aliases),
                accept_partial=accept_partial,
            ):
                log.info(
                    "Probe %s | condition=%s already complete; skipping",
                    probe.probe_id,
                    condition.value,
                )
                continue
            log.info("Probe %s | condition=%s", probe.probe_id, condition.value)

            if dry_run:
                probe_result["conditions"][condition.value] = {
                    "status": "dry_run",
                    "dry_run": True,
                }
                summary = _summary(
                    rubric=rubric,
                    probes=selected,
                    conditions=conditions,
                    model_aliases=model_aliases,
                    results=results,
                    elapsed_s=previous_elapsed_s + time.time() - start,
                    corpus=corpus,
                    input_path=input_path,
                    tool_budget=tool_budget,
                )
                _write_summary(output_path, summary)
                continue

            config = CouncilConfig(
                phases=(1,),
                model_aliases=tuple(model_aliases),
                shortcircuit_iqr_threshold=99.0,
            )
            inp = CouncilInput(
                text=probe.text,
                source_ref=probe.source_ref,
                metadata={"probe_id": probe.probe_id, "ablation_condition": condition.value},
            )

            phase1 = await runner(inp, rubric, config, condition)
            axis_scores, axis_means = _axis_distributions(phase1, rubric)

            tool_calls_total = sum(len(r.tool_calls_log) for r in phase1)
            if not phase1:
                probe_result["conditions"][condition.value] = {
                    "status": "failed",
                    "error": "no_models_responded",
                    "axis_scores": {},
                    "mean_scores": {},
                    "overall_mean": 0.0,
                    "tool_calls_total": tool_calls_total,
                    "models_expected": len(model_aliases),
                    "models_responded": 0,
                    "model_scores": [],
                }
                summary = _summary(
                    rubric=rubric,
                    probes=selected,
                    conditions=conditions,
                    model_aliases=model_aliases,
                    results=results,
                    elapsed_s=previous_elapsed_s + time.time() - start,
                    corpus=corpus,
                    input_path=input_path,
                    tool_budget=tool_budget,
                )
                _write_summary(output_path, summary)
                continue

            responded_aliases = [result.model_alias for result in phase1]
            missing_aliases = [alias for alias in model_aliases if alias not in responded_aliases]
            probe_result["conditions"][condition.value] = {
                "status": "completed" if not missing_aliases else "partial",
                "axis_scores": axis_scores,
                "mean_scores": axis_means,
                "overall_mean": round(
                    sum(axis_means.values()) / len(axis_means) if axis_means else 0.0, 2
                ),
                "tool_calls_total": tool_calls_total,
                "models_expected": len(model_aliases),
                "models_responded": len(phase1),
                "models_missing": missing_aliases,
                "model_scores": [
                    {"model": r.model_alias, "scores": r.scores, "tool_calls": r.tool_calls_log}
                    for r in phase1
                ],
            }

            summary = _summary(
                rubric=rubric,
                probes=selected,
                conditions=conditions,
                model_aliases=model_aliases,
                results=results,
                elapsed_s=previous_elapsed_s + time.time() - start,
                corpus=corpus,
                input_path=input_path,
                tool_budget=tool_budget,
            )
            _write_summary(output_path, summary)

    elapsed = previous_elapsed_s + time.time() - start
    summary = _summary(
        rubric=rubric,
        probes=selected,
        conditions=conditions,
        model_aliases=model_aliases,
        results=results,
        elapsed_s=elapsed,
        corpus=corpus,
        input_path=input_path,
        tool_budget=tool_budget,
    )
    _write_summary(output_path, summary)
    log.info(
        "Ablation complete: %d probes x %d conditions -> %s",
        len(selected),
        len(conditions),
        output_path,
    )
    if summary["mean_delta"] is not None:
        log.info("Mean FULL-NONE delta: %.2f points", summary["mean_delta"])
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--probes", type=int, default=None)
    parser.add_argument("--corpus", choices=("self-test", "legacy"), default="self-test")
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--conditions", default="full,restricted,none")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--member-timeout-s", type=float, default=None)
    parser.add_argument("--tool-budget", type=int, default=DEFAULT_TOOL_BUDGET)
    parser.add_argument("--accept-partial", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args(sys.argv[1:])
    if args.member_timeout_s is not None:
        os.environ["HAPAX_CCTV_MEMBER_TIMEOUT_S"] = str(args.member_timeout_s)
    if args.tool_budget is not None:
        os.environ["HAPAX_CCTV_TOOL_BUDGET"] = str(args.tool_budget)

    asyncio.run(
        run_ablation(
            dry_run=args.dry_run,
            max_probes=args.probes,
            corpus=args.corpus,
            input_path=args.input,
            output_path=args.output,
            conditions=_parse_conditions(args.conditions),
            model_aliases=_parse_models(args.models),
            resume=not args.no_resume,
            tool_budget=args.tool_budget,
            accept_partial=args.accept_partial,
        )
    )


if __name__ == "__main__":
    main()
