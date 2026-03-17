"""Correction synthesis — extract profile facts from accumulated corrections.

WS3: Reviews accumulated operator corrections to identify stable behavioral
patterns and preferences, then merges them into the operator profile.

Example: 10 corrections of "coding" → "writing in Obsidian" after 6pm becomes:
  ProfileFact(dimension="work_patterns", key="evening_obsidian_writing",
              value="Frequently writes in Obsidian in the evening (often misclassified as coding)",
              confidence=0.85, source="correction:synthesis")

Runs as a reactive engine rule (daily) or on-demand.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger("correction_synthesis")

# Minimum corrections before synthesis is worthwhile
MIN_CORRECTIONS = 3


class SynthesizedFact(BaseModel):
    """A profile fact derived from correction patterns."""

    dimension: str
    key: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    correction_count: int = 0
    reasoning: str = ""


class SynthesisResult(BaseModel):
    """Output of the correction synthesis agent."""

    facts: list[SynthesizedFact] = Field(default_factory=list)
    summary: str = ""
    corrections_analyzed: int = 0


_SYNTHESIS_PROMPT = """\
You are analyzing accumulated operator corrections to extract stable profile facts.

Corrections are instances where the operator corrected Hapax's perception of what
they were doing. Your job is to find PATTERNS across corrections — not to repeat
individual corrections, but to identify behavioral facts about the operator.

## Input

You will receive a list of corrections, each with:
- dimension: what was corrected (activity, flow, presence, etc.)
- original_value: what the system thought
- corrected_value: what the operator said it actually was
- context: any detail the operator provided
- hour: time of day
- flow_score: flow state when correction happened

## Output

Extract profile facts that explain WHY the system keeps making these mistakes.
Each fact should be a stable behavioral observation.

Map to these profile dimensions:
- work_patterns: time allocation, task switching, focus sessions
- energy_and_attention: focus duration, circadian rhythm, productive windows
- tool_usage: tool preferences, workflow toolchain
- creative_process: production sessions, creative flow triggers
- information_seeking: research patterns, content consumption

Guidelines:
- Only create facts supported by 2+ corrections (not one-off mistakes)
- Set confidence based on how many corrections support the pattern (3→0.6, 5→0.75, 10+→0.9)
- Use snake_case keys that describe the behavioral pattern
- The value should explain the pattern AND why the system was wrong
- If corrections cluster around a time of day, note the circadian pattern
- If corrections show tool confusion (e.g. "coding" vs "writing"), note the tool usage
"""


async def synthesize_corrections(
    corrections: list[dict[str, Any]],
) -> SynthesisResult:
    """Analyze accumulated corrections and extract profile facts.

    Args:
        corrections: Correction dicts from CorrectionStore.get_all().

    Returns:
        SynthesisResult with extracted facts and summary.
    """
    if len(corrections) < MIN_CORRECTIONS:
        return SynthesisResult(
            summary=f"Too few corrections ({len(corrections)}) — need at least {MIN_CORRECTIONS}.",
            corrections_analyzed=len(corrections),
        )

    from pydantic_ai import Agent

    from shared.config import get_model
    from shared.operator import get_system_prompt_fragment

    system_prompt = get_system_prompt_fragment("correction-synthesis") + "\n\n" + _SYNTHESIS_PROMPT

    agent = Agent(
        get_model("fast"),
        system_prompt=system_prompt,
        output_type=SynthesisResult,
    )

    # Format corrections for the LLM
    lines: list[str] = []
    for c in corrections:
        line = (
            f"- [{c.get('dimension', '?')}] "
            f'system said "{c.get("original_value", "?")}" → '
            f'operator said "{c.get("corrected_value", "?")}"'
        )
        if c.get("context"):
            line += f" (detail: {c['context']})"
        if c.get("hour"):
            line += f" [hour={c['hour']}]"
        if c.get("flow_score"):
            line += f" [flow={c['flow_score']:.2f}]"
        lines.append(line)

    user_msg = (
        f"Here are {len(corrections)} accumulated corrections:\n\n"
        + "\n".join(lines)
        + "\n\nExtract stable behavioral profile facts from these patterns."
    )

    result = await agent.run(user_msg)
    output = result.output
    output.corrections_analyzed = len(corrections)
    return output


async def run_correction_synthesis() -> str:
    """Full pipeline: read corrections → synthesize → apply to profile.

    Returns a summary string for logging.
    """
    from agents.profiler import apply_corrections
    from shared.correction_memory import CorrectionStore

    store = CorrectionStore()
    try:
        store.ensure_collection()
    except Exception:
        return "Qdrant unavailable — skipping correction synthesis."

    corrections = store.get_all(limit=200)
    if not corrections:
        return "No corrections found."

    correction_dicts = [c.model_dump() for c in corrections]
    result = await synthesize_corrections(correction_dicts)

    if not result.facts:
        return f"Analyzed {result.corrections_analyzed} corrections — no stable patterns found."

    # Convert synthesized facts to the format apply_corrections expects
    profile_corrections = [
        {
            "dimension": fact.dimension,
            "key": fact.key,
            "value": fact.value,
        }
        for fact in result.facts
    ]

    apply_result = apply_corrections(profile_corrections)

    log.info(
        "Correction synthesis: %d facts from %d corrections. %s",
        len(result.facts),
        result.corrections_analyzed,
        apply_result,
    )

    return (
        f"Synthesized {len(result.facts)} profile facts from "
        f"{result.corrections_analyzed} corrections. {apply_result}"
    )
