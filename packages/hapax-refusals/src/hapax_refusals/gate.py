"""R-Tuning post-emission refusal gate (Zhang et al., NAACL 2024).

The gate scans an LLM emission for declarative assertions, matches
each candidate against a registered set of :class:`ClaimSpec`
posteriors, and rejects the emission when:

  1. An asserted proposition matches a registered claim whose
     posterior is below the per-surface floor; OR
  2. An asserted proposition's underlying claim is not registered
     at all (the model hallucinated a fact not backed by any
     sensor signal).

On rejection, the gate returns a :class:`RefusalResult` carrying a
re-roll prompt addendum that names each rejected proposition and
asks the model to render the corresponding claim as ``[UNKNOWN]``
instead. The convenience wrapper :func:`refuse_and_reroll` runs the
whole gate-then-re-roll loop around any callable LLM call.

This module is the CORE of ``hapax-refusals``: a re-roll-on-refuse
pattern that wraps any LLM call. Surface floors 0.60-0.90 per the
surface taxonomy (see :mod:`hapax_refusals.surface`).

R-Tuning is Zhang et al. (NAACL 2024, arXiv 2311.09677): teach the
model to refuse rather than over-commit. We implement the post-hoc
verifier branch — the model emits, we check, we reject + re-roll if
needed.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from hapax_refusals.registry import RefusalEvent, RefusalRegistry
from hapax_refusals.surface import SURFACE_FLOORS, NarrationSurface, floor_for

if TYPE_CHECKING:
    from datetime import datetime

    from hapax_refusals.claim import ClaimSpec

log = logging.getLogger(__name__)


# Sentence-boundary split. Simple by design — Phase 5+ refinements
# can replace with a proper sentence segmenter if false-positives
# bite. The conservative posture is that an over-eager segmenter
# false-flags more than it lets slip.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# ``[UNKNOWN]`` markers (and the ``[p=...]`` envelope tokens that an
# upstream Phase 4 prompt envelope may emit but the model might echo)
# flag a span as explicitly-not-an-assertion.
_UNKNOWN_MARKER = re.compile(r"\[UNKNOWN\]", re.IGNORECASE)
_ENVELOPE_MARKER = re.compile(r"\[p=[^\]]*\]", re.IGNORECASE)

# Verbs that count as "asserting a fact". Conservative list — adding
# more candidates trades false-positive rate for recall. Tune on a
# domain corpus; the default is calibrated for narration surfaces
# where the LLM emits English declarative sentences about live state.
_ASSERTIVE_VERB = re.compile(
    r"\b(is|are|was|were|has|have|had|will|does|did|do|am|"
    r"plays|playing|spins|spinning)\b",
    re.IGNORECASE,
)

# Verbal hedges. Phase 4 prompt envelopes teach the model to hedge
# below-floor claims (``appears to``, ``the signal suggests``). Those
# are correct outputs, not violations — the gate must NOT flag them.
_HEDGES: tuple[str, ...] = (
    "appears to",
    "the signal suggests",
    "may be",
    "might be",
    "possibly",
    "seems to",
    "i'm not sure",
    "[unknown]",
)


def parse_emitted_propositions(text: str) -> list[str]:
    """Extract declarative assertion candidates from an LLM emission.

    Skips:

    * ``[UNKNOWN] ...`` spans (explicitly non-claim).
    * Sentences ending in ``?`` (questions, not assertions).
    * Empty / whitespace-only sentences.

    Strips ``[p=X src=Y]`` envelope markers if the model echoed them.
    """
    if not text or not text.strip():
        return []
    out: list[str] = []
    for raw in _SENT_SPLIT.split(text.strip()):
        sentence = raw.strip()
        if not sentence:
            continue
        if _UNKNOWN_MARKER.search(sentence):
            continue
        if sentence.endswith("?"):
            continue
        cleaned = _ENVELOPE_MARKER.sub("", sentence).strip()
        if not cleaned:
            continue
        out.append(cleaned)
    return out


def _looks_assertive(proposition: str) -> bool:
    """Two-condition gate: no hedges AND has an assertive verb.

    Conservative-by-default: the proposition must clear BOTH bars to
    count as an assertion worth checking. This filters parenthetical
    filler and fragment text that the parser may pick up but that
    doesn't actually assert anything.
    """
    p = proposition.lower()
    if any(h in p for h in _HEDGES):
        return False
    return bool(_ASSERTIVE_VERB.search(p))


def _proposition_matches_claim(proposition: str, claim: ClaimSpec) -> bool:
    """Loose token-overlap matcher.

    The claim's name is split on underscores; tokens of length ≥ 3
    are required to all appear (lowercase substring) in the
    proposition. Conservative because the gate's failure mode is
    **let through** rather than **wrongly reject** — the wrongly-
    rejected emission is a worse outcome (consent / latency cost).
    """
    name_tokens = [t for t in claim.name.lower().split("_") if len(t) > 2]
    if not name_tokens:
        return False
    p = proposition.lower()
    return all(token in p for token in name_tokens)


class RefusalResult(BaseModel):
    """Outcome of a single emission check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: bool
    rejected_propositions: list[str] = Field(default_factory=list)
    reroll_prompt_addendum: str = ""


def claim_discipline_score(result: RefusalResult) -> float:
    """Langfuse-bound score: 1.0 accepted, 0.0 rejected.

    Aggregated per-surface, the score becomes the rejection-rate
    dashboard signal. Stable rate = calibrated. Spike = upstream
    miscalibration (LR drift, prior drift, prompt regression).
    """
    return 1.0 if result.accepted else 0.0


class RefusalGate:
    """Post-emission verifier for one narration surface.

    Construct one gate per surface. The gate is stateless across
    calls (every ``check`` re-derives propositions from the input);
    multiple threads can call ``check`` on a shared instance.

    Args:
        surface: Which narration surface this gate guards. Determines
            the posterior floor (see :mod:`hapax_refusals.surface`).
        floor: Override the surface's default floor. Use sparingly —
            the asymmetric defaults are calibrated; raise the floor
            if your domain shows higher hallucination cost, lower if
            you've got upstream calibration that justifies it.
        registry: Where to log refusal events. Pass ``None`` to
            disable logging entirely (useful in tests). Default
            constructs a :class:`RefusalRegistry` with the standard
            log path.
    """

    def __init__(
        self,
        *,
        surface: NarrationSurface,
        floor: float | None = None,
        registry: RefusalRegistry | None = None,
    ) -> None:
        if surface not in SURFACE_FLOORS:
            raise ValueError(
                f"unknown surface {surface!r}; valid surfaces: {sorted(SURFACE_FLOORS.keys())}"
            )
        self.surface: NarrationSurface = surface
        self.floor: float = floor if floor is not None else floor_for(surface)
        if not 0.0 <= self.floor <= 1.0:
            raise ValueError(f"floor must be in [0, 1]; got {self.floor}")
        self._registry = registry if registry is not None else RefusalRegistry()
        self._log_to_registry = registry is not None or registry is None
        # Re-evaluate: registry=None means *use a default registry*. To
        # opt out of logging entirely, callers pass a dedicated
        # null-sink registry or wrap their own. The dedicated opt-out
        # is the ``log_refusals=`` flag below.
        self._log_to_registry = True
        if registry is False:  # pragma: no cover — type-narrowing guard
            self._log_to_registry = False

    def check(
        self,
        emitted_text: str,
        *,
        available_claims: list[ClaimSpec],
        log_refusals: bool = True,
    ) -> RefusalResult:
        """Verify ``emitted_text`` against ``available_claims``.

        Returns :class:`RefusalResult` carrying the accept/reject
        decision, the list of below-floor or unknown propositions,
        and a stricter prompt addendum for re-roll. When
        ``log_refusals`` is ``True`` (the default), each rejection
        is appended to the registry as a :class:`RefusalEvent`.
        """
        propositions = parse_emitted_propositions(emitted_text)
        if not propositions:
            return RefusalResult(accepted=True)

        rejected: list[str] = []
        for prop in propositions:
            if not _looks_assertive(prop):
                continue
            matched: ClaimSpec | None = None
            for claim in available_claims:
                if _proposition_matches_claim(prop, claim):
                    matched = claim
                    break
            if matched is None:
                rejected.append(prop)
                continue
            if matched.posterior < self.floor:
                rejected.append(prop)

        if not rejected:
            return RefusalResult(accepted=True)

        addendum = self._build_addendum(rejected)
        if log_refusals and self._log_to_registry:
            self._emit_refusal_brief(rejected)
        return RefusalResult(
            accepted=False,
            rejected_propositions=rejected,
            reroll_prompt_addendum=addendum,
        )

    def _build_addendum(self, rejected: list[str]) -> str:
        """Produce a re-roll prompt addendum naming each rejected claim."""
        lines: list[str] = [
            "The previous emission asserted propositions whose posteriors are "
            f"below the {self.surface} floor of {self.floor:.2f}. Re-emit, "
            "rendering the affected claims as ``[UNKNOWN]`` (do not negate, "
            "do not assert):",
        ]
        for prop in rejected:
            lines.append(f"- rejected: {prop}")
        return "\n".join(lines)

    def _emit_refusal_brief(self, rejected: list[str]) -> None:
        """Append a structured refusal event to the registry.

        One append per gate firing (not per rejected proposition)
        keeps the log proportional to gate decisions rather than to
        LLM verbosity. The first rejected proposition is the reason;
        the count of others is appended in parentheses when
        len(rejected) > 1.

        Best-effort: writer failures log internally and never raise,
        so the gate decision path is unaffected.
        """
        try:
            from datetime import UTC
            from datetime import datetime as _dt

            from hapax_refusals.registry import REASON_MAX_CHARS

            head = rejected[0] if rejected else "(no detail)"
            suffix = f" (+{len(rejected) - 1} more)" if len(rejected) > 1 else ""

            budget = REASON_MAX_CHARS - len(suffix)
            reason = (head[:budget] + suffix) if len(head) > budget else (head + suffix)
            ts: datetime = _dt.now(UTC)
            self._registry.append(
                RefusalEvent(
                    timestamp=ts,
                    axiom="claim_below_floor",
                    surface=f"refusal_gate:{self.surface}",
                    reason=reason,
                )
            )
        except Exception:
            log.warning(
                "hapax-refusals: refusal brief emission failed (suppressed)",
                exc_info=True,
            )


# Type alias for the user's LLM-call callable. The argument is the
# re-roll prompt addendum (or None on the first attempt); the return
# value is the LLM's emitted text. Async callers should wrap this
# function themselves; ``hapax-refusals`` keeps the core sync.
LlmCall = Callable[[str | None], str]


def refuse_and_reroll(
    call: LlmCall,
    *,
    gate: RefusalGate,
    available_claims: list[ClaimSpec],
    max_rerolls: int = 1,
    log_refusals: bool = True,
) -> tuple[str, RefusalResult, int]:
    """Wrap any LLM call with the refuse-and-re-roll loop.

    Args:
        call: Your one-shot LLM call. Must accept a single
            ``addendum: str | None`` argument and return the emitted
            text. ``None`` is passed on the first attempt; on each
            retry the gate's prompt addendum is passed verbatim.
            Caller is responsible for splicing the addendum into
            their system prompt (or wherever they want it).
        gate: Pre-constructed :class:`RefusalGate` for the surface.
        available_claims: The claim set the gate matches against.
        max_rerolls: Hard ceiling on re-rolls per call. Default 1
            (one initial attempt + one re-roll). Setting to 0 turns
            the wrapper into a one-shot gate-and-give-up.
        log_refusals: If ``False``, suppresses logging this call's
            rejections to the registry (useful for tests / dry-runs).

    Returns:
        Three-tuple ``(final_text, final_gate_result, attempts_made)``.

        * ``final_text`` — accepted emission, OR the last attempt's
          raw text if every attempt was rejected (the caller decides
          whether to drop or fall through).
        * ``final_gate_result`` — :class:`RefusalResult` from the
          last gate run. ``accepted=True`` iff some attempt cleared
          the gate.
        * ``attempts_made`` — total LLM calls (1 initial +
          re-rolls). Useful for cost accounting.

    Example::

        def call_llm(addendum: str | None) -> str:
            sys = base_system_prompt
            if addendum:
                sys = sys + "\\n\\n" + addendum
            return litellm_chat(system=sys, user=user_msg).choices[0].message.content

        gate = RefusalGate(surface="director")
        text, result, attempts = refuse_and_reroll(
            call_llm,
            gate=gate,
            available_claims=current_claims(),
            max_rerolls=1,
        )
        if not result.accepted:
            log.warning("dropped after %d attempts: %r", attempts, result.rejected_propositions)
            text = ""  # caller decides: drop or fall-through
    """
    if max_rerolls < 0:
        raise ValueError(f"max_rerolls must be ≥ 0; got {max_rerolls}")

    addendum: str | None = None
    text = ""
    attempts = 0
    result = RefusalResult(accepted=True)

    for attempt in range(max_rerolls + 1):
        attempts = attempt + 1
        text = call(addendum)
        result = gate.check(
            text,
            available_claims=available_claims,
            log_refusals=log_refusals,
        )
        if result.accepted:
            return text, result, attempts
        addendum = result.reroll_prompt_addendum

    # All attempts rejected. Return the last-attempt text + result so
    # the caller can decide drop-vs-fallthrough.
    return text, result, attempts


__all__ = [
    "LlmCall",
    "RefusalGate",
    "RefusalResult",
    "claim_discipline_score",
    "parse_emitted_propositions",
    "refuse_and_reroll",
]
