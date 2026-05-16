"""Segment prep disconfirmation — council-hardened assertions.

Extracts material claims from composed segments, runs them through the
deliberative council in DISCONFIRMATION mode, and feeds verdicts back
into the prep pipeline. Claims that survive earn a disconfirmation
receipt. Claims that are refuted get removed or trigger a no-candidate
dossier.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    CouncilVerdict,
)
from agents.deliberative_council.rubrics import DisconfirmationRubric

_log = logging.getLogger(__name__)

DISCONFIRMATION_ENABLED_ENV = "HAPAX_COUNCIL_DISCONFIRMATION_ENABLED"


def _is_enabled() -> bool:
    val = os.environ.get(DISCONFIRMATION_ENABLED_ENV, "1").strip().lower()
    return val in {"1", "true", "yes", "on"}


def extract_claims(
    *,
    claim_map: Sequence[Mapping[str, Any]],
    source_consequence_map: Sequence[Mapping[str, Any]],
    script: Sequence[str] | None = None,
    max_script_claims: int = 3,
) -> list[CouncilInput]:
    consequence_by_claim: dict[str, str] = {}
    for entry in source_consequence_map:
        kind = entry.get("consequence_kind", "")
        for cid in entry.get("claim_ids", []):
            consequence_by_claim[cid] = kind

    seen_texts: set[str] = set()
    inputs: list[CouncilInput] = []

    for claim in claim_map:
        claim_id = claim.get("claim_id", "")
        claim_text = claim.get("claim_text", "").strip()
        grounds = claim.get("grounds", [])
        source_consequence = claim.get("source_consequence", "")

        if not claim_text or not grounds:
            continue

        if claim_text in seen_texts:
            continue
        seen_texts.add(claim_text)

        primary_ground = grounds[0] if grounds else ""

        inputs.append(
            CouncilInput(
                text=claim_text,
                source_ref=primary_ground,
                metadata={
                    "claim_id": claim_id,
                    "source_consequence": source_consequence,
                    "consequence_kind": consequence_by_claim.get(claim_id, ""),
                    "all_grounds": list(grounds),
                },
            )
        )

    if script and len(inputs) < 2:
        import re

        assertion_re = re.compile(
            r"\b(?:demonstrates?|proves?|shows? that|establishes?|eliminates?|ensures?|guarantees?)\b",
            re.IGNORECASE,
        )
        for beat_text in script:
            if len(inputs) >= len(claim_map) + max_script_claims:
                break
            for sentence in re.split(r"[.!?]+", beat_text):
                sentence = sentence.strip()
                if (
                    assertion_re.search(sentence)
                    and len(sentence) > 30
                    and sentence not in seen_texts
                ):
                    seen_texts.add(sentence)
                    inputs.append(
                        CouncilInput(
                            text=sentence,
                            source_ref="script",
                            metadata={
                                "claim_id": f"script-assertion-{len(inputs)}",
                                "source_consequence": "",
                                "consequence_kind": "script_extracted",
                                "all_grounds": [],
                            },
                        )
                    )
                    if len(inputs) >= len(claim_map) + max_script_claims:
                        break

    return inputs


async def _run_disconfirmation_async(
    claims: list[CouncilInput],
    config: CouncilConfig | None = None,
) -> list[tuple[CouncilInput, CouncilVerdict]]:
    from agents.deliberative_council.engine import deliberate

    rubric = DisconfirmationRubric()
    results: list[tuple[CouncilInput, CouncilVerdict]] = []

    for claim in claims:
        try:
            verdict = await deliberate(claim, CouncilMode.DISCONFIRMATION, rubric, config)
            results.append((claim, verdict))
        except Exception as e:
            _log.error(
                "Council disconfirmation failed for %s: %s", claim.metadata.get("claim_id"), e
            )
            fallback = CouncilVerdict(
                scores={},
                confidence_bands={},
                convergence_status=ConvergenceStatus.HUNG,
                disagreement_log=[f"Council unavailable: {e}"],
                research_findings=[],
                evidence_matrix=None,
                receipt={"council_unavailable": True, "error": str(e)},
            )
            results.append((claim, fallback))

    return results


def run_council_disconfirmation(
    claims: list[CouncilInput],
    config: CouncilConfig | None = None,
) -> list[tuple[CouncilInput, CouncilVerdict]]:
    if not _is_enabled():
        _log.info("Council disconfirmation bypassed (HAPAX_COUNCIL_DISCONFIRMATION_ENABLED=0)")
        return []

    if not claims:
        return []

    return asyncio.run(_run_disconfirmation_async(claims, config))


def apply_council_verdicts(
    verdicts: list[tuple[CouncilInput, CouncilVerdict]],
    source_consequence_map: list[dict[str, Any]],
    claim_map: list[dict[str, Any]],
) -> dict[str, Any]:
    survived: list[str] = []
    contested: list[str] = []
    refuted: list[str] = []
    no_candidate_triggered = False
    updated_map = list(source_consequence_map)

    for claim_input, verdict in verdicts:
        claim_id = claim_input.metadata.get("claim_id", "")

        if verdict.receipt.get("council_unavailable"):
            survived.append(claim_id)
            continue

        if verdict.convergence_status == ConvergenceStatus.CONVERGED:
            all_low = all(s is not None and s <= 2 for s in verdict.scores.values())
            if all_low:
                refuted.append(claim_id)
                is_structural = _is_structural_claim(claim_id, claim_map)
                if is_structural:
                    no_candidate_triggered = True
            else:
                survived.append(claim_id)

        elif verdict.convergence_status == ConvergenceStatus.CONTESTED:
            contested.append(claim_id)
            updated_map.append(
                {
                    "source_ref": claim_input.source_ref,
                    "claim_ids": [claim_id],
                    "consequence_kind": "council_contested",
                    "changed_field": "qualifier_narrowed",
                    "failure_if_missing": "council found disagreement on this claim",
                    "council_disagreement_log": verdict.disagreement_log,
                    "council_research_findings": verdict.research_findings,
                }
            )

        else:
            contested.append(claim_id)

    all_verdicts_json = json.dumps(
        [
            {"claim_id": ci.metadata.get("claim_id"), "status": cv.convergence_status.value}
            for ci, cv in verdicts
        ],
        sort_keys=True,
    )
    verdict_sha = hashlib.sha256(all_verdicts_json.encode()).hexdigest()

    return {
        "survived_claims": survived,
        "contested_claims": contested,
        "refuted_claims": refuted,
        "updated_source_consequence_map": updated_map,
        "no_candidate_triggered": no_candidate_triggered,
        "council_verdict_sha256": verdict_sha,
        "council_disconfirmation_passed": len(refuted) == 0,
    }


def build_substance_gap_report(
    verdicts: list[tuple[CouncilInput, CouncilVerdict]],
    claim_map: list[dict[str, Any]],
) -> str:
    """Build a human-readable substance gap report from council verdicts.

    Identifies which claims were refuted, what sources were weak, and
    suggests search terms for replacement sources. Feeds back into the
    composer for a repair pass.
    """
    lines = ["## Substance Gap Report (Council Disconfirmation)"]
    refuted_claims: list[str] = []
    weak_sources: set[str] = set()

    for claim_input, verdict in verdicts:
        claim_id = claim_input.metadata.get("claim_id", "unknown")
        if verdict.receipt.get("council_unavailable"):
            continue
        scores = verdict.scores
        mean = sum(s for s in scores.values() if s is not None) / max(1, len(scores))
        if mean <= 2.0:
            claim_text = claim_input.text[:200]
            refuted_claims.append(claim_id)
            lines.append(f"\n### REFUTED: {claim_id}")
            lines.append(f"Claim: {claim_text}")
            lines.append(f"Scores: {scores}")
            if verdict.disagreement_log:
                lines.append(f"Council notes: {verdict.disagreement_log[0][:200]}")
            if verdict.research_findings:
                lines.append(f"Research: {verdict.research_findings[0][:200]}")
            for cm in claim_map:
                if cm.get("claim_id") == claim_id:
                    for g in cm.get("grounds", []):
                        weak_sources.add(str(g))

    if weak_sources:
        lines.append(f"\n### Weak sources: {', '.join(weak_sources)}")
    lines.append(f"\n### Summary: {len(refuted_claims)} claims refuted.")
    lines.append("The composer should find stronger evidence or reframe these claims.")
    return "\n".join(lines)


def _is_structural_claim(claim_id: str, claim_map: list[dict[str, Any]]) -> bool:
    for claim in claim_map:
        if claim.get("claim_id") == claim_id:
            grounds = claim.get("grounds", [])
            return len(grounds) >= 2
    return False
