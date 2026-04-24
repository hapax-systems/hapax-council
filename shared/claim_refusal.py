"""R-Tuning refusal gate — Bayesian Phase 5.

Post-generation check on LLM emissions. The gate parses declarative
assertions out of emitted text, matches them against the
:class:`Claim` registry, and rejects + re-rolls when:

1. An asserted proposition matches a registered claim whose posterior
   is below the surface-specific floor; or
2. An asserted proposition's underlying claim_name is not in the
   registry at all (the LLM hallucinated a fact not backed by any
   sensor signal).

Per-surface floors (asymmetric per surface brittleness, per
``docs/research/2026-04-24-universal-bayesian-claim-confidence.md`` §8):

==============   ====   ============================================
Surface          Floor  Rationale
==============   ====   ============================================
director         0.60   Audible to viewers; retraction is costly
spontaneous      0.70   Unprompted emissions; higher self-initiated bar
autonomous       0.75   Director-over-director; compounding error cost
persona          0.80   Direct conversation; max-intimacy hallucination
grounding-act    0.90   T4 Jemeinigkeit requires conviction
==============   ====   ============================================

R-Tuning is Zhang et al., NAACL 2024 (arXiv 2311.09677): teach the
model to refuse rather than over-commit. We implement the post-hoc
verifier branch — the model emits, we check, we reject + re-roll if
needed.

Phase 4 (alpha) builds the prompt-side ``Claim`` envelope; Phase 5
(this module) is the post-emission verifier. They share the
:class:`shared.claim.Claim` model from Phase 0 STUB. Wiring Phase 5
into specific narration surfaces (director, spontaneous, autonomous,
persona) is per-surface migration work — Phase 6 lands those.

Langfuse score ``claim_discipline``: 1.0 when accepted, 0.0 when
rejected. Rejection-rate dashboard tracks per-surface drift.

Spec: ``docs/operations/2026-04-24-workstream-realignment-v3.md`` §3.2 Phase 5.
"""

from __future__ import annotations

import re
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.claim import Claim

NarrationSurface = Literal[
    "director",
    "spontaneous",
    "autonomous",
    "persona",
    "grounding-act",
]


# Per-surface refusal floors — frozen by directive (see module docstring).
SURFACE_FLOORS: Final[dict[NarrationSurface, float]] = {
    "director": 0.60,
    "spontaneous": 0.70,
    "autonomous": 0.75,
    "persona": 0.80,
    "grounding-act": 0.90,
}


# Sentence-boundary split. Keeps it simple — Phase 5+ refinements can
# replace with a proper sentence segmenter if false-positives bite.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# ``[UNKNOWN]`` markers (and the ``[p=...]`` envelope tokens that
# Phase 4 may strip but the LLM might echo) flag a span as
# explicitly-not-an-assertion.
_UNKNOWN_MARKER = re.compile(r"\[UNKNOWN\]", re.IGNORECASE)
_ENVELOPE_MARKER = re.compile(r"\[p=[^\]]*\]", re.IGNORECASE)


def parse_emitted_propositions(text: str) -> list[str]:
    """Extract declarative assertions from an LLM emission.

    Skips:
      * ``[UNKNOWN] ...`` spans (explicitly non-claim)
      * sentences ending in ``?`` (questions)
      * empty / whitespace-only sentences

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
        # Strip envelope markers so they don't bleed into matching.
        cleaned = _ENVELOPE_MARKER.sub("", sentence).strip()
        if not cleaned:
            continue
        out.append(cleaned)
    return out


_ASSERTIVE_VERB = re.compile(
    r"\b(is|are|was|were|has|have|had|will|does|did|do|am|"
    r"plays|playing|spins|spinning|playing\b)\b",
    re.IGNORECASE,
)


def _looks_assertive(proposition: str) -> bool:
    """Heuristic: does the proposition assert a fact (vs. hedge or filler)?

    Two-condition gate:

    1. **No hedges.** Phase 4's prompt envelope teaches the model to
       hedge below-floor claims (``appears to``, ``the signal suggests``).
       Those are expected outputs, not violations.
    2. **Has an assertive copular/action verb.** This filters out
       parenthetical filler (``(no claim assertions here)``) and
       fragment text (``benign text``) that the parser may pick up
       but that doesn't actually assert anything. ``is``/``are``/``was``/
       ``has``/``plays``/``spinning`` are flag candidates.

    Conservative-by-default: a proposition needs BOTH no-hedges AND a
    flag-candidate verb to count as an assertion worth checking.
    """
    p = proposition.lower()
    hedges = (
        "appears to",
        "the signal suggests",
        "may be",
        "might be",
        "possibly",
        "seems to",
        "i'm not sure",
        "[unknown]",
    )
    if any(h in p for h in hedges):
        return False
    return bool(_ASSERTIVE_VERB.search(p))


def _proposition_matches_claim(proposition: str, claim: Claim) -> bool:
    """Loose token-overlap match between an emitted proposition and a registered claim.

    Phase 5 ships a conservative matcher: if the claim's name (split on
    underscores) shares its content tokens with the proposition (as
    lowercase substrings), call it a match. Phase 5+ refinements can
    swap in an embedding-similarity matcher.
    """
    name_tokens = [t for t in claim.name.lower().split("_") if len(t) > 2]
    if not name_tokens:
        return False
    p = proposition.lower()
    # Conservative: every meaningful name token must appear.
    return all(token in p for token in name_tokens)


class RefusalResult(BaseModel):
    """Outcome of a single emission check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: bool
    rejected_propositions: list[str] = Field(default_factory=list)
    reroll_prompt_addendum: str = ""


class RefusalGate:
    """R-Tuning post-emission verifier for one narration surface."""

    def __init__(self, *, surface: NarrationSurface) -> None:
        if surface not in SURFACE_FLOORS:
            raise ValueError(f"unknown surface {surface!r}")
        self.surface: NarrationSurface = surface
        self.floor: float = SURFACE_FLOORS[surface]

    def check(
        self,
        emitted_text: str,
        *,
        available_claims: list[Claim],
    ) -> RefusalResult:
        """Verify ``emitted_text`` against the available claim set.

        Returns :class:`RefusalResult` carrying the accept/reject
        decision, the list of below-floor or unknown propositions,
        and a stricter prompt addendum for re-roll.
        """
        propositions = parse_emitted_propositions(emitted_text)
        if not propositions:
            return RefusalResult(accepted=True)

        rejected: list[str] = []
        for prop in propositions:
            if not _looks_assertive(prop):
                continue
            matched: Claim | None = None
            for claim in available_claims:
                if _proposition_matches_claim(prop, claim):
                    matched = claim
                    break
            if matched is None:
                # Unmatched assertion — could be benign filler OR a
                # hallucinated claim. Conservative posture: only flag
                # propositions that look "claim-shaped" (contain a
                # subject-predicate verb pair). Phase 5 takes the
                # simpler heuristic: flag any unmatched assertive
                # proposition. Phase 5+ can refine.
                rejected.append(prop)
                continue
            if matched.posterior < self.floor:
                rejected.append(prop)

        if not rejected:
            return RefusalResult(accepted=True)

        addendum = self._build_addendum(rejected, available_claims)
        return RefusalResult(
            accepted=False,
            rejected_propositions=rejected,
            reroll_prompt_addendum=addendum,
        )

    def _build_addendum(self, rejected: list[str], claims: list[Claim]) -> str:
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


def claim_discipline_score(result: RefusalResult) -> float:
    """Langfuse-bound score: 1.0 accepted, 0.0 rejected.

    Aggregated per-surface, the score becomes the rejection-rate
    dashboard signal. Stable rate = calibrated. Spike = upstream
    miscalibration (LR drift, prior drift, prompt regression).
    """
    return 1.0 if result.accepted else 0.0


__all__ = [
    "SURFACE_FLOORS",
    "NarrationSurface",
    "RefusalGate",
    "RefusalResult",
    "claim_discipline_score",
    "parse_emitted_propositions",
]
