from __future__ import annotations

import random

from .rubrics import Rubric


def phase1_prompt(rubric: Rubric, text: str, source_ref: str, seed: int | None = None) -> str:
    axes = list(rubric.axes)
    if seed is not None:
        rng = random.Random(seed)
        rng.shuffle(axes)

    axis_block = "\n".join(
        f"- **{a.name}** ({a.min_score}-{a.max_score}): {a.description}\n"
        f"  Strong example: {a.strong_example}\n"
        f"  Weak example: {a.weak_example}"
        for a in axes
    )

    return (
        "You are a member of a deliberative council evaluating text.\n\n"
        f"{rubric.instructions}\n\n"
        f"## Rubric Axes\n\n{axis_block}\n\n"
        f"## Input\n\n**Source ref:** {source_ref}\n\n**Text:**\n{text}\n\n"
        "## Instructions\n\n"
        "1. Use your research tools to investigate the source_ref before scoring.\n"
        f"2. Score each axis {axes[0].min_score}-{axes[0].max_score}.\n"
        "3. For each score, provide a 1-2 sentence rationale.\n"
        "4. List any research findings (files checked, evidence found or not found).\n\n"
        "Respond in JSON:\n"
        '{"scores": {"axis_name": int, ...}, '
        '"rationale": {"axis_name": "...", ...}, '
        '"research_findings": ["..."]}'
    )


def phase3_adversarial_prompt(
    axis: str,
    your_score: int,
    your_rationale: str,
    opponent_score: int,
    opponent_rationale: str,
    opponent_findings: list[str],
    evidence_matrix_summary: str,
) -> str:
    findings_text = ", ".join(opponent_findings) if opponent_findings else "none"
    return (
        f"You scored '{axis}' as {your_score}. Another council member scored it {opponent_score}.\n\n"
        f"**Their rationale:** {opponent_rationale}\n\n"
        f"**Their research findings:** {findings_text}\n\n"
        f"**Evidence matrix summary:** {evidence_matrix_summary}\n\n"
        "This is an adversarial challenge. Respond to the strongest points in their argument. Either:\n"
        "- Defend your score with specific counter-evidence\n"
        "- Revise your score with explicit reasoning\n\n"
        "Respond in JSON:\n"
        '{"revised_score": int, "response": "..."}'
    )


def phase4_revision_prompt(
    rubric: Rubric,
    original_scores: dict[str, int],
    evidence_matrix_summary: str,
    adversarial_exchanges: str,
) -> str:
    return (
        "You are revising your scores after seeing evidence and adversarial challenges.\n\n"
        f"## Your original scores\n{original_scores}\n\n"
        f"## Evidence matrix\n{evidence_matrix_summary}\n\n"
        f"## Adversarial exchanges\n{adversarial_exchanges}\n\n"
        "Revise your scores. This is private — no one sees your revision until aggregation.\n\n"
        "Respond in JSON:\n"
        '{"revised_scores": {"axis_name": int, ...}, '
        '"revision_rationale": {"axis_name": "...", ...}, '
        '"changed_axes": ["..."]}'
    )


def phase2_alternative_framing_prompt(
    text: str,
    phase1_scores: dict[str, dict[str, int]],
) -> str:
    score_summary = "\n".join(f"  {model}: {scores}" for model, scores in phase1_scores.items())
    return (
        "You are analyzing a livestream segment's STRUCTURE to identify "
        "alternative framings that might work better.\n\n"
        f"## Segment Text\n{text[:4000]}\n\n"
        f"## Phase 1 Scores\n{score_summary}\n\n"
        "## Task\n\n"
        "For each structural weakness identified in Phase 1 scores:\n"
        "1. Name the weakness (e.g., 'flat opening', 'parallel beats', 'citation theater')\n"
        "2. Propose an ALTERNATIVE FRAMING — how could the same material be "
        "structured differently to score higher on that axis?\n"
        "3. Assess: is the alternative demonstrably better, or just different?\n\n"
        "The narrator is a non-anthropomorphic system with authentic perspective. "
        "Alternatives must preserve external focalization — no performing humanness.\n\n"
        "Respond in JSON:\n"
        '{"alternative_framings": [{"weakness": "...", "alternative": "...", '
        '"improvement_confidence": "high|medium|low"}, ...]}'
    )


def phase3_audience_simulation_prompt(
    text: str,
    axis: str,
    your_score: int,
    your_rationale: str,
    opponent_score: int,
    opponent_rationale: str,
) -> str:
    return (
        f"You scored '{axis}' as {your_score}. Another member scored it {opponent_score}.\n\n"
        f"**Their rationale:** {opponent_rationale}\n\n"
        "## Audience Simulation Challenge\n\n"
        "Model a naive listener encountering this segment linearly at speech pace. "
        "Report:\n"
        "1. At what point (beat/sentence) does comprehension first break?\n"
        "2. Where does tension dissipate — where would a listener zone out?\n"
        "3. Where do callbacks to earlier material land vs miss?\n"
        "4. Does the closing feel like resolution or just stopping?\n\n"
        "This is diagnostic, not adversarial. The 'opponent' is attention "
        "attrition, not intellectual disagreement.\n\n"
        f"## Segment Excerpt\n{text[:3000]}\n\n"
        "Respond in JSON:\n"
        '{"comprehension_breaks": [{"beat": int, "reason": "..."}], '
        '"tension_drops": [{"beat": int, "reason": "..."}], '
        '"callback_assessment": "...", '
        '"closure_assessment": "...", '
        '"revised_score": int, "response": "..."}'
    )
