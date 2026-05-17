from __future__ import annotations

import asyncio
import hashlib
import json
import logging

from pydantic_ai import Agent  # noqa: TC002 — used at runtime in _call_member

from .aggregation import aggregate_scores, should_shortcircuit
from .members import build_member
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
from .prompts import (
    phase1_prompt,
    phase2_alternative_framing_prompt,
    phase3_adversarial_prompt,
    phase3_audience_simulation_prompt,
    phase4_revision_prompt,
)
from .rubrics import Rubric

_log = logging.getLogger(__name__)


async def _call_member(member: Agent[None, str], prompt: str) -> tuple[str, list[str]]:
    result = await member.run(prompt)
    tool_calls: list[str] = []
    try:
        for msg in result.all_messages():
            parts = getattr(msg, "parts", [])
            for part in parts:
                kind = getattr(part, "part_kind", "")
                if kind == "tool-call":
                    name = getattr(part, "tool_name", "?")
                    args = str(getattr(part, "args", ""))[:200]
                    tool_calls.append(f"{name}({args})")
                elif kind == "tool-return":
                    name = getattr(part, "tool_name", "?")
                    content = str(getattr(part, "content", ""))[:200]
                    tool_calls.append(f"{name} → {content}")
    except Exception:
        pass
    return result.output, tool_calls


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

            source_ctx_block = ""
            if inp.source_context:
                source_ctx_block = (
                    f"\n\n## Source Context\n```\n{inp.source_context}\n```\n"
                )

            investigate_prompt = (
                "You are a council member. FIRST, investigate the source material "
                "using your research tools. Do NOT score yet — only gather evidence.\n\n"
                f"**Source ref:** {inp.source_ref}\n\n**Text:**\n{inp.text}"
                f"{source_ctx_block}\n\n"
                "Use tools to verify claims, check sources, and gather evidence. "
                "Report your findings as a JSON list:\n"
                '{"research_findings": ["finding 1", "finding 2", ...]}'
            )
            investigate_raw, tool_calls = await _call_member(member, investigate_prompt)

            findings_text = investigate_raw[:2000]

            score_prompt = phase1_prompt(rubric, inp.text, inp.source_ref, seed=seed)
            score_prompt += (
                f"\n\n## Your Prior Research Findings\n{findings_text}\n\n"
                "Score based on your research above. Do NOT re-investigate."
            )
            score_raw, score_tools = await _call_member(member, score_prompt)
            all_tools = tool_calls + score_tools

            result = _parse_phase1_output(alias, score_raw)
            return PhaseOneResult(
                model_alias=result.model_alias,
                scores=result.scores,
                rationale=result.rationale,
                research_findings=result.research_findings,
                tool_calls_log=all_tools,
            )
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

    if not inp.source_context:
        from agents.deliberative_council.source_context import populate_source_context

        ctx = populate_source_context(inp.text, inp.source_ref, inp.metadata)
        if ctx:
            inp = inp.model_copy(update={"source_context": ctx})

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
        agg = aggregate_scores(phase1_results, config.contested_iqr_threshold)
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

    # Phase 2: Evidence matrix (epistemic) or Alternative Framing Matrix (narrative)
    evidence_matrix = await _run_phase2(phase1_results, rubric, config, mode=mode, text=inp.text)

    # Phase 3: Adversarial challenge (epistemic) or Audience Simulation (narrative)
    adversarial_exchanges = await _run_phase3(
        phase1_results, evidence_matrix, rubric, config, mode=mode, text=inp.text
    )

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
    *,
    mode: CouncilMode = CouncilMode.DISCONFIRMATION,
    text: str = "",
) -> EvidenceMatrix | None:
    """Phase 2: Build ACH evidence matrix (epistemic) or Alternative Framing Matrix (narrative)."""
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

    if mode == CouncilMode.NARRATIVE and text:
        phase1_scores = {r.model_alias: r.scores for r in phase1_results}
        prompt = phase2_alternative_framing_prompt(text, phase1_scores)
    else:
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
        raw, _ = await _call_member(member, prompt)
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
    *,
    mode: CouncilMode = CouncilMode.DISCONFIRMATION,
    text: str = "",
) -> list[AdversarialExchange]:
    """Phase 3: Adversarial challenge (epistemic) or Audience Simulation (narrative)."""
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

        if mode == CouncilMode.NARRATIVE and text:
            prompt = phase3_audience_simulation_prompt(
                text=text,
                axis=axis,
                your_score=high_score,
                your_rationale=high_result.rationale.get(axis, ""),
                opponent_score=low_score,
                opponent_rationale=low_result.rationale.get(axis, ""),
            )
        else:
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
            raw, _ = await _call_member(member, prompt)
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
            raw, _ = await _call_member(member, prompt)
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
