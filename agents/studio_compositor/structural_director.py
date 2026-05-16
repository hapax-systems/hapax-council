"""StructuralDirector — slow-cadence LLM for long-horizon moves.

Phase 5c of the volitional-director epic (PR #1018; spec §3.4).

Cadence: 150 s. Emits StructuralIntent that the narrative director reads
as a context enrichment on its next tick — "Current structural direction:
<long_horizon_direction>". This keeps structural moves slow and coherent
across multiple narrative ticks without forcing the narrative director
to carry long-horizon state itself.

Output lands at /dev/shm/hapax-structural/intent.json (atomic replace).
The narrative director reads it alongside the PerceptualField block.

Under the grounding-exhaustive axiom, structural moves are grounding
moves of the slowest frequency — scene shifts, preset-family
transitions, YouTube direction. They use the grounded model (Command R
via LiteLLM) just like the narrative director, but with a smaller prompt
(no compositional-impingement demand; just scene_mode + family_hint +
long_horizon_direction free text).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agents.studio_compositor.action_receipts import emit_action_receipt
from shared.action_receipt import ActionReceiptStatus

log = logging.getLogger(__name__)

_STRUCTURAL_INTENT_PATH = Path("/dev/shm/hapax-structural/intent.json")
_STRUCTURAL_INTENT_JSONL = Path(
    os.path.expanduser("~/hapax-state/stream-experiment/structural-intent.jsonl")
)
_ACTION_RECEIPTS_JSONL = Path("/dev/shm/hapax-compositor/action-receipts.jsonl")

SceneMode = Literal[
    "desk-work",
    "hardware-play",
    "conversation",
    "idle-ambient",
    "mixed",
    "research-primary",
]

PresetFamilyHint = Literal[
    "audio-reactive",
    "audio-reactive-extended",
    "calm-textural",
    "glitch-dense",
    "neutral-ambient",
    "warm-minimal",
]

# HOMAGE Phase 8 (task #114): rotation strategy the structural director
# emits to drive the HOMAGE choreographer's ward-rotation behaviour.
#
# Values:
#   * ``sequential``           — default; choreographer applies transitions
#                                in pending-queue order (pre-Phase 8).
#   * ``random``               — transitions remain eligible but are not
#                                pre-sorted (choreographer leaves ordering
#                                to its concurrency-limit slice).
#   * ``weighted_by_salience`` — sort pending entry/exit transitions by
#                                ``salience`` descending before the
#                                concurrency-limit slice so the
#                                most-salient wards win under contention.
#   * ``paused``               — choreographer drops all transitions this
#                                tick (substrate broadcast + coupling
#                                payload still publish; only the FSM
#                                advance stops).
#
# Spec §4.13 lists a complementary cadence family (steady/deliberate/
# rapid/burst); those compose with the strategy modes here once the
# cadence multiplier lands.
HomageRotationMode = Literal[
    "sequential",
    "random",
    "weighted_by_salience",
    "paused",
]


class StructuralIntent(BaseModel):
    scene_mode: SceneMode
    preset_family_hint: PresetFamilyHint
    long_horizon_direction: str = Field(
        ...,
        description=(
            "1-2 sentence direction the narrative director reads as "
            "context on its next tick. Stays in effect for ~150s until "
            "superseded."
        ),
    )
    homage_rotation_mode: HomageRotationMode = Field(
        default="sequential",
        description=(
            "HOMAGE Phase 8 (task #114). Drives the choreographer's "
            "ward-rotation strategy: sequential (default), random, "
            "weighted_by_salience, or paused. Default is sequential so "
            "pre-existing structural intents deserialize without change."
        ),
    )
    emitted_at: float = Field(default_factory=time.time)
    condition_id: str = "none"

    # Programme-layer Phase 5: stamp the active programme on every emitted
    # intent so Phase 9 observability can group structural moves by the
    # programme they served. None when no programme is active.
    programme_id: str | None = Field(
        default=None,
        description=(
            "ID of the active Programme at emission time; None when no "
            "programme is active. Stamped by StructuralDirector.tick_once "
            "(Phase 5 of the programme-layer plan)."
        ),
    )


_RESEARCH_MARKER_PATH = Path("/dev/shm/hapax-compositor/research-marker.json")


def _read_condition_id() -> str:
    try:
        if _RESEARCH_MARKER_PATH.exists():
            data = json.loads(_RESEARCH_MARKER_PATH.read_text(encoding="utf-8"))
            return data.get("condition_id") or "none"
    except Exception:
        pass
    return "none"


def _publish(intent: StructuralIntent) -> None:
    """Atomic publish to /dev/shm + append to JSONL for research observability."""
    applied_refs: list[str] = []
    error_refs: list[str] = []
    try:
        _STRUCTURAL_INTENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STRUCTURAL_INTENT_PATH.with_suffix(".json.tmp")
        tmp.write_text(intent.model_dump_json(), encoding="utf-8")
        tmp.replace(_STRUCTURAL_INTENT_PATH)
        applied_refs.append("shm:hapax-structural/intent.json")
    except Exception:
        log.warning("structural-intent publish failed", exc_info=True)
        error_refs.append("structural_intent_publish_failed")
    try:
        _STRUCTURAL_INTENT_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with _STRUCTURAL_INTENT_JSONL.open("a", encoding="utf-8") as fh:
            fh.write(intent.model_dump_json() + "\n")
        applied_refs.append("jsonl:stream-experiment/structural-intent.jsonl")
    except Exception:
        log.warning("structural-intent jsonl write failed", exc_info=True)
        error_refs.append("structural_intent_jsonl_write_failed")
    try:
        from shared.director_observability import emit_structural_intent

        emit_structural_intent(
            scene_mode=intent.scene_mode,
            preset_family_hint=intent.preset_family_hint,
            condition_id=intent.condition_id,
        )
    except Exception:
        log.debug("prometheus emit_structural_intent failed", exc_info=True)
    receipt_request_id = (
        intent.condition_id
        if intent.condition_id and intent.condition_id != "none"
        else f"structural-director:{time.time_ns()}"
    )
    emit_action_receipt(
        request_id=receipt_request_id,
        capability_name="structural.director.intent",
        requested_action=intent.long_horizon_direction,
        status=ActionReceiptStatus.ERROR if error_refs else ActionReceiptStatus.APPLIED,
        family="structural.director",
        command_ref="structural-director:publish",
        applied_refs=applied_refs if not error_refs else [],
        error_refs=error_refs,
        structural_reflex=True,
        path=_ACTION_RECEIPTS_JSONL,
    )


def parse_structural_intent(raw: str) -> StructuralIntent | None:
    """Best-effort parse of an LLM response into a StructuralIntent.

    Returns None on any failure — the caller can fall back to a stale
    intent or a default.
    """
    text = raw.strip()
    if not text or not text.startswith("{"):
        return None
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    try:
        return StructuralIntent.model_validate(obj)
    except Exception:
        return None


class StructuralDirector:
    """Slow 150-second LLM loop publishing long-horizon directives."""

    # Epic 2 Phase E (2026-04-17) tightened 150.0 → 90.0 so long-horizon
    # moves hit more frequently during the livestream. Override via
    # HAPAX_STRUCTURAL_CADENCE_S for debugging.
    DEFAULT_CADENCE_S = float(os.environ.get("HAPAX_STRUCTURAL_CADENCE_S", "90.0"))
    STARTUP_OFFSET_S = 10.0  # delay so structural doesn't collide with narrative tick edge

    def __init__(
        self,
        *,
        cadence_s: float = DEFAULT_CADENCE_S,
        sleep_fn=time.sleep,
        llm_fn=None,
        programme_provider=None,
    ):
        """llm_fn: callable(prompt: str) -> str. Defaults to the same
        LiteLLM route used by the narrative director. Tests inject a
        deterministic stub.

        programme_provider: callable() -> Programme | None. When provided,
        the director consults the active programme on every tick to
        enrich the prompt with the programme's role + beat + soft priors,
        stamp ``programme_id`` on emitted intents, and honour the
        programme's ``structural_cadence_prior_s`` override between
        ticks. ``None`` short-circuits to legacy behaviour.
        """
        self._cadence_s = cadence_s
        self._sleep = sleep_fn
        self._llm_fn = llm_fn or _default_llm_fn
        self._programme_provider = programme_provider
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="structural-director", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        # Startup offset so structural ticks don't coincide with narrative tick edges
        self._sleep(self.STARTUP_OFFSET_S)
        while self._running:
            try:
                self.tick_once()
            except Exception:  # pragma: no cover
                log.warning("structural tick crashed", exc_info=True)
            self._sleep(self._next_cadence_s())

    def _active_programme(self):
        """Resolve the active Programme (or None). Robust to provider failure."""
        if self._programme_provider is None:
            return None
        try:
            return self._programme_provider()
        except Exception:
            log.debug("structural: programme lookup failed", exc_info=True)
            return None

    def _next_cadence_s(self) -> float:
        """Return the cadence to use for the upcoming sleep.

        A programme's ``structural_cadence_prior_s`` overrides the
        director's default for the next sleep when set. The validator
        in ``ProgrammeConstraintEnvelope`` already enforces ``> 0``.
        """
        prog = self._active_programme()
        if prog is None:
            return self._cadence_s
        prior = prog.constraints.structural_cadence_prior_s
        return float(prior) if prior else self._cadence_s

    def tick_once(self) -> StructuralIntent | None:
        programme = self._active_programme()
        prompt = self._build_prompt(programme=programme)
        try:
            raw = self._llm_fn(prompt)
        except Exception:
            log.warning("structural LLM call failed", exc_info=True)
            return None
        intent = parse_structural_intent(raw or "")
        if intent is None:
            log.debug("structural LLM response unparseable; keeping prior intent")
            return None
        intent = intent.model_copy(
            update={
                "emitted_at": time.time(),
                "condition_id": _read_condition_id(),
                "programme_id": programme.programme_id if programme is not None else None,
            }
        )
        _publish(intent)
        return intent

    def _build_prompt(self, programme=None) -> str:
        """Minimal structural prompt. No images, no per-tick compositional demand.

        Reads the same PerceptualField the narrative director sees plus a
        short objectives summary. Shorter than narrative to keep the 150s
        cadence latency-cheap.

        When a programme is active its role + narrative beat + soft priors
        are appended as a "Programme context" section so the LLM knows
        which long-horizon direction it's serving. The priors are framed
        as PREFERENCES (soft bias), never as REQUIREMENTS (hard gate) —
        the regression pin
        ``test_structural_director_programme.py::TestSoftPriorFraming``
        enforces this wording at module-test time.
        """
        parts: list[str] = []
        parts.append("<structural_context>")
        try:
            from shared.perceptual_field import build_perceptual_field

            field = build_perceptual_field()
            parts.append("## Perceptual Field")
            parts.append(field.model_dump_json(indent=2, exclude_none=True))
        except Exception:
            log.debug("structural: perceptual_field read failed", exc_info=True)
        parts.append("")
        if programme is not None:
            parts.extend(_render_programme_context(programme))
            parts.append("")
        parts.append("## Your Role")
        parts.append(
            "You are Hapax's slow (2-3 min) structural director. Your job "
            "is the long-horizon shape of the livestream: what scene mode "
            "we're in, which effect-preset family feels right, and a "
            "one-or-two-sentence direction the narrative director reads "
            "as its next tick's context."
        )
        parts.append("")
        parts.append("## Response Format")
        parts.append(
            "{\n"
            '  "scene_mode": "<desk-work|hardware-play|conversation|idle-ambient|mixed|research-primary>",\n'
            '  "preset_family_hint": "<audio-reactive|audio-reactive-extended|calm-textural|glitch-dense|neutral-ambient|warm-minimal>",\n'
            '  "long_horizon_direction": "<1-2 sentences>",\n'
            '  "homage_rotation_mode": "<sequential|random|weighted_by_salience|paused>"\n'
            "}"
        )
        parts.append(
            "``homage_rotation_mode`` is optional (defaults to "
            "``sequential``). Use ``paused`` to quiet ward rotation "
            "during delicate operator work; ``weighted_by_salience`` to "
            "let the highest-salience ward win under contention; "
            "``random`` when you want the choreographer's concurrency "
            "slice to pick freely."
        )
        parts.append(
            "Ground your scene_mode in what the PerceptualField actually "
            "shows. Ground your family hint in the music/energy profile. "
            "The long_horizon_direction is prose guidance the narrative "
            "director consumes; stay concrete, avoid rhetorical flourish "
            "(axiom ex-prose-001)."
        )
        parts.append("</structural_context>")
        return "\n".join(parts)


def _render_programme_context(programme) -> list[str]:
    """Render the active Programme as a soft-prior context block.

    Phase 5 of the programme-layer plan. Soft priors only — every prior
    is framed as a preference the LLM may override when impingement
    pressure justifies it. The grounding-expansion regression pin
    inspects this section's wording (must NOT contain 'must' / 'required'
    / 'only' / 'never' / 'forbidden'; MUST frame priors with 'prefers' /
    'soft prior' / 'bias toward' so the LLM knows it has slack).
    """
    role = programme.role.value if hasattr(programme.role, "value") else str(programme.role)
    lines: list[str] = ["## Programme context"]
    lines.append(
        f"An active programme of role `{role}` is in flight. "
        "Treat the items below as SOFT PRIORS — preferences that bias "
        "your choices, not gates that constrain them. When impingement "
        "pressure or the perceptual field calls for a different move, "
        "emit it; the programme's purpose is to expand grounding "
        "opportunities, not to replace grounding."
    )
    beat = (programme.content.narrative_beat or "").strip()
    if beat:
        lines.append(f"- programme direction: {beat}")
    constraints = programme.constraints
    if constraints.preset_family_priors:
        priors = ", ".join(constraints.preset_family_priors)
        lines.append(f"- prefers preset families: {priors} (soft prior)")
    if constraints.homage_rotation_modes:
        modes = ", ".join(constraints.homage_rotation_modes)
        lines.append(f"- bias toward homage rotation modes: {modes} (soft prior)")
    return lines


def _default_llm_fn(prompt: str) -> str:
    """Fallback LLM call — reuses the narrative director's LiteLLM route.

    Best-effort: imports are lazy so tests can stub this without pulling
    in the heavy director_loop module.
    """
    import subprocess
    import urllib.request

    litellm_url = "http://localhost:4000/v1/chat/completions"
    # Reuse the same key fetch as director_loop._get_litellm_key
    try:
        result = subprocess.run(
            ["pass", "show", "litellm/master-key"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        key = result.stdout.strip()
    except Exception:
        key = ""
    body = json.dumps(
        {
            "model": os.environ.get("HAPAX_STRUCTURAL_MODEL", "local-fast"),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 320,
            "temperature": 0.7,
        }
    ).encode()
    req = urllib.request.Request(
        litellm_url,
        body,
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    started = time.time()
    # Publish LLM-in-flight marker so the ThinkingIndicator Cairo source
    # pulses while the structural tier is mid-call.
    from agents.studio_compositor.director_loop import _LLMInFlight

    with _LLMInFlight(
        tier="structural", model=os.environ.get("HAPAX_STRUCTURAL_MODEL", "local-fast")
    ):
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
    elapsed = time.time() - started
    try:
        from shared.director_observability import observe_llm_latency

        observe_llm_latency(elapsed, tier="structural", condition_id=_read_condition_id())
    except Exception:
        pass
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


__all__ = [
    "HomageRotationMode",
    "StructuralDirector",
    "StructuralIntent",
    "parse_structural_intent",
]
