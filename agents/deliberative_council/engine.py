from __future__ import annotations

import asyncio
import hashlib
import json
import logging

from pydantic_ai import Agent  # noqa: TC002 — used at runtime in _call_member

from .aggregation import aggregate_scores, should_shortcircuit
from .members import build_member
from .models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    CouncilVerdict,
    PhaseOneResult,
)
from .prompts import phase1_prompt
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

    # Full deliberation path (Phases 2-5 — to be completed in Task 7)
    agg = aggregate_scores(phase1_results, config.contested_iqr_threshold)
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
        evidence_matrix=None,
        receipt={
            "input_hash": input_hash,
            "shortcircuited": False,
            "models_used": [r.model_alias for r in phase1_results],
            "phases_completed": [1],
        },
    )
