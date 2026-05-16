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
