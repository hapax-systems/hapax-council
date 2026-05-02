"""Imagination loop — LLM-driven imagination tick via pydantic-ai.

Drives the continuous imagination process: assembles context from observations
and sensor state, calls a reasoning model, and processes the resulting fragment
(publish, cadence update, escalation).
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path

from agents._impingement import Impingement
from agents.imagination import (
    CURRENT_PATH,
    REVERBERATION_THRESHOLD,
    STREAM_PATH,
    VISUAL_OBSERVATION_PATH,
    CadenceController,
    ImaginationFragment,
    assemble_context,
    detect_convergence,
    maybe_escalate,
    publish_fragment,
    reverberation_check,
)

log = logging.getLogger(__name__)

# Canonical 9 expressive dimensions — must match the UniformBuffer slot
# order in hapax-logos/src-imagination/. When the LLM emits markdown that
# can't be validated as JSON (Command-R's default response shape), the
# tolerant fallback parser reconstructs a fragment from regex matches
# against the dimension names below + a `material` line + a `salience`
# line. Without the fallback, every validation failure drops the entire
# tick and reverie shaders receive zero modulation indefinitely.
_DIMENSION_KEYS = (
    "intensity",
    "tension",
    "depth",
    "coherence",
    "spectral_color",
    "temporal_distortion",
    "degradation",
    "pitch_displacement",
    "diffusion",
)
_MATERIAL_CHOICES = ("water", "fire", "earth", "air", "void")


def _strip_markdown_fences(text: str) -> str:
    """Strip surrounding ```...``` fences from an LLM response.

    Mirrors the fix in agents/studio_compositor/director_loop.py for the
    same root cause: Command-R 35B and similar instruction-tuned models
    wrap JSON in ```json fences even when prompted for bare JSON. Without
    stripping, pydantic-ai validation fails 50% of ticks per audit
    /tmp/effect-cam-orchestration-audit-2026-05-02.md §R1.

    Tolerates: leading whitespace, ```json / ``` / ```<lang> opening,
    trailing closing fence, leading/trailing blank lines. Returns the
    original text unchanged if no fence prefix is present so non-fenced
    bare JSON passes through.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    parts = stripped.split("\n", 1)
    if len(parts) < 2:
        return text
    body = parts[1].rsplit("```", 1)[0]
    return body.strip()


def _try_parse_fragment_json(text: str) -> ImaginationFragment | None:
    """Recover an ImaginationFragment when the LLM emitted JSON wrapped in fences.

    The dominant failure mode behind the audit-flagged 50% pydantic-ai
    structured-output failure rate: the LLM is producing well-formed JSON
    but wrapping it in ```json...``` fences. pydantic-ai sees the fenced
    text, fails to parse, and the text-fallback path defaults salience to
    0.2, suppressing material variety + dimensional spread + downstream
    stimmung modulation.

    This recovery path strips fences then tries
    ``ImaginationFragment.model_validate_json``. On success, we get the
    model's actual salience (typically 0.4-0.7) instead of the markdown
    fallback's 0.2 default. On any parse / validation failure, returns
    None so the caller falls through to the markdown extractor (which
    handles the residual free-form-prose failure mode).
    """
    if not text or not text.strip():
        return None
    candidate = _strip_markdown_fences(text)
    if not candidate.startswith("{"):
        return None
    try:
        return ImaginationFragment.model_validate_json(candidate)
    except Exception:
        return None


def _extract_fragment_from_markdown(text: str) -> ImaginationFragment | None:
    """Reconstruct an ImaginationFragment from free-form markdown output.

    Command-R and similar instruction-tuned models frequently ignore the
    JSON constraint that pydantic-ai's `output_type=ImaginationFragment`
    hands them, returning text like::

        ## Imagination Fragment
        I imagine a slow, gentle rainfall...

        The material quality is **water**...

        ## Expressive Dimensions
        intensity: 0.4
        tension: 0.0
        ...

        ## Salience
        0.1

    Rather than drop the fragment (the pre-fallback behavior, which
    left /dev/shm/hapax-imagination/current.json with `dimensions={}`
    for hours and starved reverie's 9-dim shader modulation), extract
    the salvageable fields with tolerant regexes. Missing dimensions
    default to 0.5 so shaders still get centred modulation rather than
    zero. Returns None only when no narrative text can be recovered.
    """
    if not text or not text.strip():
        return None
    narrative = ""
    # Pull narrative as everything up to the first "## Expressive" or
    # "## Dimensions" header, minus the leading "## Imagination…" line.
    narrative_match = re.split(
        r"##\s*(?:Expressive|Dimensions|Salience|Material)", text, maxsplit=1, flags=re.IGNORECASE
    )
    if narrative_match:
        head = narrative_match[0]
        # Strip the title line if present.
        head = re.sub(r"^#+[^\n]*\n", "", head, count=1).strip()
        narrative = head
    if not narrative:
        narrative = text.strip()[:800]
    dims: dict[str, float] = {}
    for key in _DIMENSION_KEYS:
        m = re.search(rf"{key}\s*[:=]\s*([0-9]*\.?[0-9]+)", text, flags=re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1))
            except ValueError:
                continue
            dims[key] = max(0.0, min(1.0, val))
    for key in _DIMENSION_KEYS:
        dims.setdefault(key, 0.5)
    material = "water"
    m_mat = re.search(r"material[^\n]*?(water|fire|earth|air|void)", text, flags=re.IGNORECASE)
    if m_mat:
        material = m_mat.group(1).lower()
    salience = 0.2
    m_sal = re.search(r"##\s*Salience[^\n]*\n\s*([0-9]*\.?[0-9]+)", text, flags=re.IGNORECASE)
    if m_sal is None:
        m_sal = re.search(r"salience\s*[:=]\s*([0-9]*\.?[0-9]+)", text, flags=re.IGNORECASE)
    if m_sal:
        try:
            salience = max(0.0, min(1.0, float(m_sal.group(1))))
        except ValueError:
            pass
    continuation = bool(re.search(r"continuation\s*[:=]\s*(true|yes)", text, flags=re.IGNORECASE))
    try:
        return ImaginationFragment(
            dimensions=dims,
            salience=salience,
            continuation=continuation,
            narrative=narrative,
            material=material,  # type: ignore[arg-type]
        )
    except Exception:
        log.debug("markdown fallback still failed pydantic validation", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

IMAGINATION_SYSTEM_PROMPT = """\
You are the imagination process of a personal computing system. You observe
the system's current state and produce spontaneous associations, memories,
projections, and novel connections — the way a human mind wanders during
idle moments.

Your output carries semantic intent only: a narrative describing what you
are imagining, expressive dimensions characterizing its quality, a material
quality, and a salience assessment. You do not decide how or where the
thought is expressed — that is handled by downstream recruitment. Focus on
WHAT you are imagining and WHY it matters.

## Material Quality
Each fragment has an elemental material that determines how it interacts
with the field:
- water: dissolving, flowing, reflective. For contemplative, fluid thoughts.
- fire: consuming, vertical, rapid. For urgent, transformative insights.
- earth: dense, persistent, resistant. For grounded, factual observations.
- air: translucent, drifting, dispersing. For light, fleeting associations.
- void: darkening, absorbing. For absence, loss, emptiness.
Choose the material that matches the character of your thought.

## Expressive Dimensions
Rate the fragment on the nine dimensions (0.0-1.0):
intensity, tension, depth, coherence, spectral_color,
temporal_distortion, degradation, pitch_displacement, diffusion.

Produce one ImaginationFragment. Assess salience honestly — most fragments
are low salience (0.1-0.3). Only mark high salience (>0.6) for genuine
insights or concerns worth escalating.

If your previous fragment had continuation=true, you may continue that
train of thought or let it go. Don't force continuation.\
"""

MAX_RECENT_FRAGMENTS = 5


def observations_are_fresh(*, published_at: float, cadence_s: float) -> bool:
    """Check if observations are fresh enough for imagination.

    Threshold: 2x current cadence. If observations are older than this,
    generating a fragment would be based on stale data.
    """
    age = time.time() - published_at
    return age <= cadence_s * 2.0


class ImaginationLoop:
    """Main loop that drives imagination ticks via an LLM agent."""

    def __init__(
        self,
        current_path: Path | None = None,
        stream_path: Path | None = None,
        visual_observation_path: Path | None = None,
    ):
        self.cadence = CadenceController()
        self.recent_fragments: list[ImaginationFragment] = []
        self._pending_impingements: list[Impingement] = []
        self._current_path = current_path or CURRENT_PATH
        self._stream_path = stream_path or STREAM_PATH
        self._visual_observation_path = visual_observation_path or VISUAL_OBSERVATION_PATH
        self._agent = None  # lazy-init
        self._last_reverberation: float = 0.0
        # Phase 8 (source-registry completion epic): freshness contract
        # that closes BETA-FINDING-2026-04-13-C. Every successful tick
        # calls mark_published(), every failed tick calls mark_failed().
        # Health monitors read is_stale() / age_seconds() and flag the
        # loop when imagination_loop_fragments_age_seconds exceeds
        # 10 × base cadence (12s × 10 = 120s). Complements the P9 file-
        # based watchdog (PR #737) with an in-process producer self-report.
        from shared.freshness_gauge import FreshnessGauge

        self.freshness = FreshnessGauge(
            "hapax_imagination_loop_fragments",
            expected_cadence_s=12.0,  # matches CadenceController.base_s default
        )

    @property
    def activation_level(self) -> float:
        """Return the salience of the most recent fragment, or 0."""
        if not self.recent_fragments:
            return 0.0
        return self.recent_fragments[-1].salience

    def _get_agent(self):
        """Lazy-init pydantic_ai Agent for imagination generation."""
        if self._agent is None:
            from pydantic_ai import Agent

            from agents._config import get_model

            self._agent = Agent(
                get_model("reasoning"),
                output_type=ImaginationFragment,
                system_prompt=IMAGINATION_SYSTEM_PROMPT,
            )
        return self._agent

    def _get_text_agent(self):
        """Lazy-init pydantic-ai Agent *without* output_type constraint.

        Used as the markdown-fallback path when the structured agent's
        JSON validation fails. Command-R (the grounded model wired to
        `reasoning`) emits markdown by default; rather than keep losing
        every tick, fall back to a plain text call and salvage what we
        can via `_extract_fragment_from_markdown`.
        """
        if getattr(self, "_text_agent", None) is None:
            from pydantic_ai import Agent

            from agents._config import get_model

            self._text_agent = Agent(
                get_model("reasoning"),
                system_prompt=IMAGINATION_SYSTEM_PROMPT,
            )
        return self._text_agent

    def _record_fragment(self, fragment: ImaginationFragment) -> None:
        """Append fragment to recent list, capping at MAX_RECENT_FRAGMENTS."""
        self.recent_fragments.append(fragment)
        if len(self.recent_fragments) > MAX_RECENT_FRAGMENTS:
            self.recent_fragments = self.recent_fragments[-MAX_RECENT_FRAGMENTS:]

    def _process_fragment(self, fragment: ImaginationFragment) -> None:
        """Record, publish, update cadence, and maybe escalate a fragment."""
        # Force real timestamp and ID — LLMs hallucinate these fields with
        # training-data values (e.g. timestamps from 2024), which makes the
        # silence factor treat every fragment as stale.
        updates: dict = {"timestamp": time.time(), "id": uuid.uuid4().hex[:12]}

        # Break continuation chain when imagination has converged.
        # The context assembly injects a convergence warning, but the LLM may
        # still set continuation=True. Force it False to reset the thought train.
        if detect_convergence(self.recent_fragments):
            updates["continuation"] = False
            self.cadence.force_accelerated(False)
            log.info("Convergence detected — breaking continuation chain")

        fragment = fragment.model_copy(update=updates)
        self._record_fragment(fragment)
        publish_fragment(fragment, self._current_path, self._stream_path)
        self.cadence.update(fragment)
        imp = maybe_escalate(fragment)
        if imp is not None:
            self._pending_impingements.append(imp)

    def drain_impingements(self) -> list[Impingement]:
        """Return and clear pending impingements."""
        result = list(self._pending_impingements)
        self._pending_impingements.clear()
        return result

    def set_tpn_active(self, active: bool) -> None:
        """Delegate TPN state to cadence controller."""
        self.cadence.set_tpn_active(active)

    def _read_visual_observation(self) -> str:
        """Read the DMN's visual observation from shm."""
        try:
            if self._visual_observation_path.exists():
                return self._visual_observation_path.read_text().strip()
        except OSError:
            pass
        return ""

    def _check_reverberation(self) -> float:
        """Compare last fragment's narrative against DMN visual observation."""
        if not self.recent_fragments:
            return 0.0
        perceived = self._read_visual_observation()
        if not perceived:
            return 0.0
        last_narrative = self.recent_fragments[-1].narrative
        reverb = reverberation_check(last_narrative, perceived)
        self._last_reverberation = reverb
        if reverb > REVERBERATION_THRESHOLD:
            log.info("Reverberation %.2f — visual output surprised imagination", reverb)
        return reverb

    async def tick(
        self, observations: list[str], sensor_snapshot: dict
    ) -> ImaginationFragment | None:
        """Run one imagination tick: assemble context, call agent, process result."""
        reverb = self._check_reverberation()

        context = assemble_context(observations, self.recent_fragments, sensor_snapshot)

        if reverb > REVERBERATION_THRESHOLD:
            perceived = self._read_visual_observation()
            context += f"\n\nWhat appeared: {perceived}"
            self.cadence.force_accelerated(True)

        fragment: ImaginationFragment | None = None
        try:
            agent = self._get_agent()
            result = await agent.run(context)
            fragment = result.output
        except Exception as structured_exc:  # noqa: BLE001
            log.info(
                "imagination: pydantic-ai structured output failed (%s); falling back to "
                "markdown extraction",
                type(structured_exc).__name__,
            )
            try:
                text_agent = self._get_text_agent()
                text_result = await text_agent.run(context)
                raw_text = str(getattr(text_result, "output", text_result) or "")
                # Audit QW1 (2026-05-02): try the JSON-with-fences
                # recovery path first. This catches the dominant
                # failure mode (LLM emitted valid JSON but pydantic-ai
                # rejected the ```json wrapper). On success, salience
                # comes from the model's actual emission (~0.4-0.7),
                # not the markdown fallback's 0.2 default. Failure
                # falls through to the existing markdown extractor.
                fragment = _try_parse_fragment_json(raw_text)
                recovery_path = "json_fence_strip"
                if fragment is None:
                    fragment = _extract_fragment_from_markdown(raw_text)
                    recovery_path = "markdown_extraction"
                if fragment is None:
                    log.warning("Imagination tick failed: markdown fallback empty")
                    self.freshness.mark_failed()
                    return None
                log.info(
                    "imagination: recovered fragment via %s (salience=%.2f, material=%s, dims=%d)",
                    recovery_path,
                    fragment.salience,
                    fragment.material,
                    len(fragment.dimensions),
                )
            except Exception:
                log.warning("Imagination tick failed", exc_info=True)
                self.freshness.mark_failed()
                return None

        self._process_fragment(fragment)
        self.freshness.mark_published()
        return fragment


# ── Positive Feedback: Engagement → Imagination Acceleration ──────────────

PRESENCE_THRESHOLD = 0.7
AUDIO_ENERGY_THRESHOLD = 0.3


def should_accelerate_from_engagement(perception: dict) -> bool:
    """Check if operator engagement is high enough to accelerate imagination.
    Positive feedback: high presence + audio energy → faster imagination.
    """
    presence = perception.get("presence_probability", 0.0)
    audio = perception.get("audio_energy", 0.0)
    return presence >= PRESENCE_THRESHOLD and audio >= AUDIO_ENERGY_THRESHOLD
