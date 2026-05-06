"""GEM LLM-driven authoring — pydantic-ai Agent emits multi-keyframe sequences.

Phase 3 follow-on per ``docs/superpowers/plans/2026-04-21-gem-ward-activation-plan.md``.

The template-driven authoring path in ``gem_producer.render_emphasis_template``
+ ``render_composition_template`` produces serviceable but rigid output:
overlapping graffiti layers for emphasis/composition. Hapax
should be able to author richer mural sequences — abstract glyph
animation, frame-by-frame box-draw narrative, BitchX-grammar emphasis
— without operator authoring each frame by hand.

This module ships an authoring ``Agent`` that takes an impingement's
narrative + intent_family and returns a list of ``GemFrame`` validated
through the same AntiPatternKind gate the renderer enforces.

Activation:

* **Default ON** per directive ``feedback_features_on_by_default``
  (2026-04-25T20:55Z). Operator opts out via ``HAPAX_GEM_LLM_AUTHORING=0``;
  setting to ``0`` / ``false`` / ``no`` / ``off`` exclusively uses the
  template path.
* When the LLM call fails / times out / returns invalid output, the
  producer falls back to the template path (no broadcast outage).
  Existing fallback wiring at ``gem_producer.py:271`` is unchanged.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from agents.studio_compositor.gem_source import contains_emoji

if TYPE_CHECKING:
    from shared.impingement import Impingement

log = logging.getLogger(__name__)

GEM_LLM_AUTHORING_ENV = "HAPAX_GEM_LLM_AUTHORING"

# Hard caps so a runaway LLM can't flood the renderer.
MAX_FRAMES = 5
MIN_HOLD_MS = 200
MAX_HOLD_MS = 3000
MAX_FRAME_TEXT_CHARS = 80


class GemFramePayload(BaseModel):
    """Wire-format frame the LLM emits.

    Strict validators enforce CP437-only / no-emoji / sane hold timing.
    Failed validation propagates as a Pydantic ValidationError; caller
    treats this as a parse failure and falls back to template.
    """

    text: str = Field(
        description=(
            "Frame text — CP437 + box-draw + BitchX punctuation only. "
            "No emoji, no emoji presentation selectors. "
            f"Max {MAX_FRAME_TEXT_CHARS} chars."
        )
    )
    hold_ms: int = Field(
        default=1500,
        ge=MIN_HOLD_MS,
        le=MAX_HOLD_MS,
        description=f"Frame hold duration in ms ({MIN_HOLD_MS}-{MAX_HOLD_MS}).",
    )

    @field_validator("text")
    @classmethod
    def _no_emoji_no_overlong(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("frame text must be non-empty")
        if contains_emoji(value):
            raise ValueError("frame text contains emoji codepoints (AntiPatternKind)")
        if len(value) > MAX_FRAME_TEXT_CHARS:
            raise ValueError(f"frame text {len(value)} chars exceeds {MAX_FRAME_TEXT_CHARS}")
        return value


class GemSequence(BaseModel):
    """LLM authoring output — N frames forming a mural sequence."""

    frames: list[GemFramePayload] = Field(
        min_length=1,
        max_length=MAX_FRAMES,
        description=f"1-{MAX_FRAMES} frames; renderer plays them in order.",
    )


GEM_SYSTEM_PROMPT = """\
You are HAPAX authoring a single GEM (Graffiti Emphasis Mural) sequence
for the lower-band raster surface (1840x240, BitchX CP437 grammar).

Constraints (non-negotiable):
* Only CP437 / Px437 IBM VGA glyphs — box-draw (┌─┐│└─┘╔═╗║╚═╝),
  block (▓▒░), arrows (»«→←↑↓), Braille (⠀-⣿), basic Latin.
* No emoji, no anti-aliased proportional fonts, no emoji-presentation
  selectors (U+FE0F).
* No humanoid figures. No faces. No eyes/mouths/expressions. The frame
  is a flat glyph mural, never a character.
* No chiron, ticker-tape, caption strip, or ``>>>`` single-row status line.
  GEM must read as dense lower-band graffiti, not a scrolling information bar.
* Each frame text must be ≤ 80 characters (multiple lines OK).
* Each frame's hold_ms in 200..3000.
* Sequence is 1..5 frames total. Default to 3 frames for emphasis,
  1-2 frames for composition pulses.

Grammar moves available:
* Banner emphasis:  ┌──[ TEXT ]──┐ ... └────────────┘
* Arrow markers:    » keyword «
* Box-draw frames:  ╔══════╗ over ║ TEXT ║ over ╚══════╝
* Block density:    ▓▒░ shadow under ASCII text
* Braille fills:    ⠀⠁⠃⠇⠏⠟⠿ for sub-cell shading
* Revision marks:   asterisk-prefix `* correction:`, /me actions

Sequence patterns:
* Emphasis: empty banner setup → text inside → trace fade
* Composition: glyph state change over 2-3 frames, abstract motion
* Pulse: single frame, short hold, kinetic punctuation

Return ONLY valid JSON for the GemSequence schema.
"""


def _build_authoring_agent():
    """Late import + construction so module load doesn't hit LiteLLM gateway."""
    from pydantic_ai import Agent

    from agents._config import get_model

    return Agent(
        get_model("balanced"),
        system_prompt=GEM_SYSTEM_PROMPT,
        output_type=GemSequence,
    )


_agent_singleton = None


def get_authoring_agent():
    """Lazy-construct the agent. None when authoring not opted-in."""
    global _agent_singleton
    if not is_llm_authoring_enabled():
        return None
    if _agent_singleton is None:
        _agent_singleton = _build_authoring_agent()
    return _agent_singleton


def is_llm_authoring_enabled() -> bool:
    """Read HAPAX_GEM_LLM_AUTHORING env flag.

    Default ON per directive ``feedback_features_on_by_default``
    (2026-04-25). Operator opts out via ``0`` / ``false`` / ``no`` /
    ``off``; setting ``0`` makes the template path exclusive.
    """
    raw = os.environ.get(GEM_LLM_AUTHORING_ENV, "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _build_user_prompt(imp: Impingement, narrative: str) -> str:
    """Compose the user message from an impingement + narrative fragment."""
    intent = imp.intent_family or "gem.emphasis"
    family = "composition" if intent.startswith("gem.composition") else "emphasis"
    return (
        f"Author a {family} mural sequence for this impingement.\n\n"
        f"Narrative: {narrative}\n"
        f"Intent: {intent}\n"
        f"Salience: {imp.strength:.2f}\n\n"
        f"Return a 1-5 frame GemSequence."
    )


async def author_sequence(imp: Impingement, narrative: str) -> GemSequence | None:
    """Author a multi-keyframe GEM sequence via LLM.

    Returns the GemSequence on success, or ``None`` when:
    * LLM authoring is disabled
    * Agent construction failed (no model available)
    * The LLM call raised
    * The LLM output failed Pydantic validation

    The producer treats ``None`` as "fall back to template path."
    """
    agent = get_authoring_agent()
    if agent is None:
        return None
    try:
        result = await agent.run(_build_user_prompt(imp, narrative))
        return result.output
    except Exception:
        log.warning(
            "gem-authoring: LLM call failed for impingement %s — falling back",
            imp.id,
            exc_info=True,
        )
        return None


__all__ = [
    "GEM_LLM_AUTHORING_ENV",
    "GEM_SYSTEM_PROMPT",
    "MAX_FRAMES",
    "MAX_FRAME_TEXT_CHARS",
    "MAX_HOLD_MS",
    "MIN_HOLD_MS",
    "GemFramePayload",
    "GemSequence",
    "author_sequence",
    "get_authoring_agent",
    "is_llm_authoring_enabled",
]
