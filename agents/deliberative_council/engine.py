from __future__ import annotations

import asyncio
import hashlib
import json
import logging

from pydantic_ai import Agent  # noqa: TC002 — used at runtime in _call_member

from .aggregation import aggregate_scores, should_shortcircuit
from .members import MODEL_FAMILIES, build_member
from .models import (
    AdversarialExchange,
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    CouncilVerdict,
    EvidenceMatrix,
    EvidenceMatrixAxis,
    PhaseOneResult,
)
from .prompts import phase1_prompt, phase3_adversarial_prompt, phase4_revision_prompt
from .rubrics import Rubric

_log = logging.getLogger(__name__)


async def _call_member(member: Agent[None, str], prompt: str) -> str:
    result = await member.run(prompt)
    return result.output


def _parse_phase1_output(model_alias: str, raw: str) -> PhaseOneResult:
    try:
        text = raw.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()
        data = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        _log.warning("Model %s returned non-JSON, using empty scores", model_alias)
        data = {"scores": {}, "rationale": {}, "research_findings": []}
    return PhaseOneResult(
        model_alias=model_alias,
        scores={k: int(v) for k, v in data.get("scores", {}).items()},
        rationale=data.get("rationale", {}),
        research_findings=data.get("research_findings", []),
    )


async def run_phase1(
    inp: CouncilInput,
    rubric: Rubric,
    config: CouncilConfig,
) -> list[PhaseOneResult]:
    async def _run_one(alias: str, seed: int) -> PhaseOneResult | None:
        try:
            member = build_member(alias)
            prompt = phase1_prompt(rubric, inp.text, inp.source_ref, seed=seed)
            raw = await _call_member(member, prompt)
            return _parse_phase1_output(alias, raw)
        except Exception as e:
            _log.error("Phase 1 failure for %s: %s", alias, e)
            return None

    results_or_none = await asyncio.gather(
        *(_run_one(alias, i) for i, alias in enumerate(config.model_aliases))
    )
    return [r for r in results_or_none if r is not None]


async def deliberate(
    inp: CouncilInput,
    mode: CouncilMode,
    rubric: Rubric,
    config: CouncilConfig | None = None,
) -> CouncilVerdict:
    if config is None:
        config = CouncilConfig()

    input_hash = hashlib.sha256(
        json.dumps({"text": inp.text, "source_ref": inp.source_ref}, sort_keys=True).encode()
    ).hexdigest()

    phase1_results = await run_phase1(inp, rubric, config)

    if not phase1_results:
        return CouncilVerdict(
            scores={},
            confidence_bands={},
            convergence_status=ConvergenceStatus.HUNG,
            disagreement_log=["All models failed in Phase 1"],
            research_findings=[],
            evidence_matrix=None,
            receipt={"input_hash": input_hash, "error": "all_models_failed"},
        )

    if should_shortcircuit(phase1_results, config.shortcircuit_iqr_threshold):
        agg = aggregate_scores(
            phase1_results,
            config.contested_iqr_threshold,
            families=MODEL_FAMILIES,
            family_penalty_threshold=config.family_correlation_penalty_threshold,
        )
        return CouncilVerdict(
            scores={k: v.score for k, v in agg.items()},
            confidence_bands={k: v.confidence_band for k, v in agg.items()},
            convergence_status=ConvergenceStatus.CONVERGED,
            disagreement_log=[],
            research_findings=[f for r in phase1_results for f in r.research_findings],
            evidence_matrix=None,
            receipt={
                "input_hash": input_hash,
                "shortcircuited": True,
                "models_used": [r.model_alias for r in phase1_results],
                "phases_completed": [1],
            },
        )

    # Phase 2: Evidence matrix — Opus builds ACH classification
    evidence_matrix = await _run_phase2(phase1_results, rubric, config)

    # Phase 3: Adversarial challenge — highest vs lowest on contested axes
    adversarial_exchanges = await _run_phase3(phase1_results, evidence_matrix, rubric, config)

    # Phase 4: Revised private judgment
    phase4_results = await _run_phase4(
        phase1_results, evidence_matrix, adversarial_exchanges, rubric, config
    )

    # Phase 5: Final convergence on revised scores
    final_results = phase4_results if phase4_results else phase1_results
    agg = aggregate_scores(final_results, config.contested_iqr_threshold)
    statuses = [v.status for v in agg.values()]
    if ConvergenceStatus.HUNG in statuses:
        overall = ConvergenceStatus.HUNG
    elif ConvergenceStatus.CONTESTED in statuses:
        overall = ConvergenceStatus.CONTESTED
    else:
        overall = ConvergenceStatus.CONVERGED

    return CouncilVerdict(
        scores={k: v.score for k, v in agg.items()},
        confidence_bands={k: v.confidence_band for k, v in agg.items()},
        convergence_status=overall,
        disagreement_log=[
            f"{a}: IQR={v.iqr:.1f} values={v.values}" for a, v in agg.items() if v.iqr > 1.0
        ],
        research_findings=[f for r in phase1_results for f in r.research_findings],
        evidence_matrix=evidence_matrix,
        adversarial_exchanges=tuple(adversarial_exchanges),
        receipt={
            "input_hash": input_hash,
            "shortcircuited": False,
            "models_used": [r.model_alias for r in phase1_results],
            "phases_completed": [1, 2, 3, 4, 5],
        },
    )


async def _run_phase2(
    phase1_results: list[PhaseOneResult],
    rubric: Rubric,
    config: CouncilConfig,
) -> EvidenceMatrix | None:
    """Phase 2: Build ACH evidence matrix from Phase 1 findings."""
    from .aggregation import compute_iqr

    contested_axes: list[str] = []
    all_axes: set[str] = set()
    for r in phase1_results:
        all_axes.update(r.scores.keys())
    for axis in all_axes:
        values = [r.scores[axis] for r in phase1_results if axis in r.scores]
        if compute_iqr(values) > config.shortcircuit_iqr_threshold:
            contested_axes.append(axis)

    if not contested_axes:
        return None

    all_findings = []
    for r in phase1_results:
        for f in r.research_findings:
            all_findings.append(f"{r.model_alias}: {f}")

    findings_block = "\n".join(all_findings) if all_findings else "No research findings."
    scores_block = "\n".join(f"  {r.model_alias}: {r.scores}" for r in phase1_results)

    prompt = (
        "You are building an Analysis of Competing Hypotheses (ACH) evidence matrix.\n\n"
        f"## Contested axes: {contested_axes}\n\n"
        f"## Phase 1 scores:\n{scores_block}\n\n"
        f"## Research findings:\n{findings_block}\n\n"
        "For each contested axis, classify each research finding as:\n"
        "- consistent: supports this score level\n"
        "- inconsistent: contradicts this score level\n"
        "- irrelevant: neither supports nor contradicts\n\n"
        "Identify the LEAST INCONSISTENT score level per axis (ACH logic).\n\n"
        "Respond in JSON:\n"
        '{"axes": {"axis_name": {"least_inconsistent_score": int, '
        '"summary": "..."}, ...}}'
    )

    try:
        member = build_member(config.model_aliases[0])
        raw = await _call_member(member, prompt)
        text = raw.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()
        data = json.loads(text)

        matrix_axes = {}
        for axis, info in data.get("axes", {}).items():
            matrix_axes[axis] = EvidenceMatrixAxis(
                axis=axis,
                least_inconsistent_score=info.get("least_inconsistent_score"),
            )
        return EvidenceMatrix(axes=matrix_axes, built_by=config.model_aliases[0])
    except Exception as e:
        _log.warning("Phase 2 failed: %s", e)
        return None


async def _run_phase3(
    phase1_results: list[PhaseOneResult],
    evidence_matrix: EvidenceMatrix | None,
    rubric: Rubric,
    config: CouncilConfig,
) -> list[AdversarialExchange]:
    """Phase 3: Adversarial challenge — highest vs lowest on contested axes."""
    from .aggregation import compute_iqr

    exchanges: list[AdversarialExchange] = []
    all_axes: set[str] = set()
    for r in phase1_results:
        all_axes.update(r.scores.keys())

    for axis in all_axes:
        scores_for_axis = [
            (r.model_alias, r.scores.get(axis, 0)) for r in phase1_results if axis in r.scores
        ]
        if not scores_for_axis:
            continue

        values = [s for _, s in scores_for_axis]
        if compute_iqr(values) <= config.shortcircuit_iqr_threshold:
            continue

        high_alias, high_score = max(scores_for_axis, key=lambda x: x[1])
        low_alias, low_score = min(scores_for_axis, key=lambda x: x[1])

        if high_score == low_score:
            continue

        high_result = next(r for r in phase1_results if r.model_alias == high_alias)
        low_result = next(r for r in phase1_results if r.model_alias == low_alias)

        matrix_summary = ""
        if evidence_matrix and axis in evidence_matrix.axes:
            em_axis = evidence_matrix.axes[axis]
            matrix_summary = f"Least inconsistent score: {em_axis.least_inconsistent_score}"

        prompt = phase3_adversarial_prompt(
            axis=axis,
            your_score=high_score,
            your_rationale=high_result.rationale.get(axis, ""),
            opponent_score=low_score,
            opponent_rationale=low_result.rationale.get(axis, ""),
            opponent_findings=low_result.research_findings,
            evidence_matrix_summary=matrix_summary,
        )

        try:
            member = build_member(high_alias)
            raw = await _call_member(member, prompt)
            exchanges.append(
                AdversarialExchange(
                    axis=axis,
                    high_scorer=high_alias,
                    high_score=high_score,
                    low_scorer=low_alias,
                    low_score=low_score,
                    challenge_text=f"Low scorer ({low_alias}) rationale: {low_result.rationale.get(axis, '')}",
                    response_text=raw[:2000],
                )
            )
        except Exception as e:
            _log.warning("Phase 3 adversarial exchange failed for %s: %s", axis, e)

    return exchanges


async def _run_phase4(
    phase1_results: list[PhaseOneResult],
    evidence_matrix: EvidenceMatrix | None,
    adversarial_exchanges: list[AdversarialExchange],
    rubric: Rubric,
    config: CouncilConfig,
) -> list[PhaseOneResult]:
    """Phase 4: All models re-score privately after seeing evidence + challenges."""
    if not adversarial_exchanges:
        return phase1_results

    matrix_summary = (
        "No evidence matrix."
        if not evidence_matrix
        else json.dumps(
            {
                k: {"least_inconsistent": v.least_inconsistent_score}
                for k, v in evidence_matrix.axes.items()
            }
        )
    )
    exchanges_summary = "\n".join(
        f"  {e.axis}: {e.high_scorer}({e.high_score}) vs {e.low_scorer}({e.low_score}) — response: {e.response_text[:200]}"
        for e in adversarial_exchanges
    )

    revised_results: list[PhaseOneResult] = []

    async def _revise_one(original: PhaseOneResult) -> PhaseOneResult:
        prompt = phase4_revision_prompt(
            rubric=rubric,
            original_scores=original.scores,
            evidence_matrix_summary=matrix_summary,
            adversarial_exchanges=exchanges_summary,
        )
        try:
            member = build_member(original.model_alias)
            raw = await _call_member(member, prompt)
            text = raw.strip()
            if "```json" in text:
                text = text.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in text:
                text = text.split("```", 1)[1].split("```", 1)[0].strip()
            data = json.loads(text)
            revised_scores = {k: int(v) for k, v in data.get("revised_scores", {}).items()}
            if revised_scores:
                return PhaseOneResult(
                    model_alias=original.model_alias,
                    scores=revised_scores,
                    rationale=data.get("revision_rationale", original.rationale),
                    research_findings=original.research_findings,
                )
        except Exception as e:
            _log.warning("Phase 4 revision failed for %s: %s", original.model_alias, e)
        return original

    revised_results = list(await asyncio.gather(*(_revise_one(r) for r in phase1_results)))
    return revised_results
