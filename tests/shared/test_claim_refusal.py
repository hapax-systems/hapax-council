"""Tests for ``shared.claim_refusal`` — Bayesian Phase 5 R-Tuning refusal gate.

Spec: ``docs/research/2026-04-24-universal-bayesian-claim-confidence.md`` §8.
Workstream: ``docs/operations/2026-04-24-workstream-realignment-v3.md`` §3.2 Phase 5.

Refusal-gate contract:
- Per-surface floors: director 0.60 / spontaneous 0.70 / autonomous 0.75 /
  persona 0.80 / grounding-act 0.90.
- LLM-emitted text scanned for assertions; if an assertion matches a known
  claim whose posterior is below the surface floor, OR asserts a proposition
  whose claim_name is absent from the registry — gate rejects + emits a
  stricter re-roll prompt addendum.
- Langfuse score ``claim_discipline`` records pass/reject per emission.
"""

from __future__ import annotations

from shared.claim import (
    Claim,
    EvidenceRef,
    TemporalProfile,
)
from shared.claim_refusal import (
    SURFACE_FLOORS,
    NarrationSurface,
    RefusalGate,
    RefusalResult,
    claim_discipline_score,
    parse_emitted_propositions,
)


def _claim(
    name: str = "vinyl_is_playing",
    posterior: float = 0.75,
    proposition: str = "Vinyl is currently playing.",
    domain: str = "audio",
) -> Claim:
    return Claim(
        name=name,
        domain=domain,
        proposition=proposition,
        posterior=posterior,
        prior_source="reference",
        prior_provenance_ref="prior_provenance.yaml#vinyl_is_playing",
        evidence_sources=[
            EvidenceRef(
                signal_name="ir_hand_zone",
                value="turntable",
                timestamp=0.0,
                frame_source="raw_sensor",
            )
        ],
        last_update_t=0.0,
        temporal_profile=TemporalProfile(
            enter_threshold=0.7, exit_threshold=0.3, k_enter=2, k_exit=2
        ),
        composition=None,
        narration_floor=0.6,
        staleness_cutoff_s=60.0,
    )


class TestSurfaceFloors:
    def test_director_floor_is_060(self) -> None:
        assert SURFACE_FLOORS["director"] == 0.60

    def test_spontaneous_floor_is_070(self) -> None:
        assert SURFACE_FLOORS["spontaneous"] == 0.70

    def test_autonomous_floor_is_075(self) -> None:
        assert SURFACE_FLOORS["autonomous"] == 0.75

    def test_persona_floor_is_080(self) -> None:
        assert SURFACE_FLOORS["persona"] == 0.80

    def test_grounding_act_floor_is_090(self) -> None:
        assert SURFACE_FLOORS["grounding-act"] == 0.90

    def test_floors_are_strictly_increasing(self) -> None:
        from itertools import pairwise

        ordered = ["director", "spontaneous", "autonomous", "persona", "grounding-act"]
        for a, b in pairwise(ordered):
            assert SURFACE_FLOORS[a] < SURFACE_FLOORS[b]


class TestParseEmittedPropositions:
    """The output parser locates declarative assertions in LLM emissions."""

    def test_simple_assertion(self) -> None:
        out = parse_emitted_propositions("Vinyl is currently playing on the turntable.")
        assert any("vinyl" in p.lower() for p in out)

    def test_multiple_sentences(self) -> None:
        text = "Vinyl is playing. The operator is working. The album is queued."
        out = parse_emitted_propositions(text)
        assert len(out) >= 2

    def test_skips_unknown_markers(self) -> None:
        """``[UNKNOWN]`` propositions are explicitly non-claims; not parsed."""
        text = "[UNKNOWN] Authoritative now-playing track. Vinyl is spinning."
        out = parse_emitted_propositions(text)
        assert not any("authoritative now-playing" in p.lower() for p in out)
        assert any("vinyl" in p.lower() for p in out)

    def test_skips_questions(self) -> None:
        out = parse_emitted_propositions("Is the vinyl playing?")
        assert out == []

    def test_returns_empty_on_empty_input(self) -> None:
        assert parse_emitted_propositions("") == []


class TestRefusalGateAccept:
    def test_accepts_when_no_claims_in_emission(self) -> None:
        gate = RefusalGate(surface="director")
        result = gate.check("(no claim assertions here)", available_claims=[])
        assert result.accepted is True
        assert result.rejected_propositions == []

    def test_accepts_above_floor_claim(self) -> None:
        """Vinyl at 0.75 posterior, director floor 0.60 → accept."""
        gate = RefusalGate(surface="director")
        claims = [_claim(posterior=0.75)]
        result = gate.check("Vinyl is currently playing.", available_claims=claims)
        assert result.accepted is True


class TestRefusalGateReject:
    def test_rejects_below_floor_claim(self) -> None:
        """Vinyl at 0.45 posterior, director floor 0.60 → reject."""
        gate = RefusalGate(surface="director")
        claims = [_claim(posterior=0.45)]
        result = gate.check("Vinyl is currently playing.", available_claims=claims)
        assert result.accepted is False
        assert any("vinyl" in p.lower() for p in result.rejected_propositions)

    def test_rejects_unknown_claim_assertion(self) -> None:
        """Asserting a proposition whose claim_name isn't in the registry → reject."""
        gate = RefusalGate(surface="director")
        result = gate.check(
            "The operator is hallucinating about chess positions.",
            available_claims=[_claim()],  # registry has only vinyl_is_playing
        )
        # The "chess positions" claim is not registered — should be flagged.
        assert result.accepted is False

    def test_higher_floor_rejects_what_lower_accepts(self) -> None:
        """Same posterior — director (0.60) accepts, persona (0.80) rejects."""
        claim = _claim(posterior=0.65)
        director_result = RefusalGate(surface="director").check(
            "Vinyl is currently playing.", available_claims=[claim]
        )
        persona_result = RefusalGate(surface="persona").check(
            "Vinyl is currently playing.", available_claims=[claim]
        )
        assert director_result.accepted is True
        assert persona_result.accepted is False


class TestRerollAddendum:
    def test_addendum_mentions_below_floor_claim(self) -> None:
        gate = RefusalGate(surface="director")
        result = gate.check(
            "Vinyl is currently playing.",
            available_claims=[_claim(posterior=0.45)],
        )
        assert "vinyl" in result.reroll_prompt_addendum.lower()
        assert "[unknown]" in result.reroll_prompt_addendum.lower()

    def test_addendum_empty_when_accepted(self) -> None:
        gate = RefusalGate(surface="director")
        result = gate.check("benign text", available_claims=[])
        assert result.reroll_prompt_addendum == ""


class TestClaimDisciplineScore:
    """Langfuse score for per-surface rejection rate observability."""

    def test_score_1_on_accept(self) -> None:
        result = RefusalResult(accepted=True, rejected_propositions=[], reroll_prompt_addendum="")
        assert claim_discipline_score(result) == 1.0

    def test_score_0_on_reject(self) -> None:
        result = RefusalResult(
            accepted=False,
            rejected_propositions=["foo"],
            reroll_prompt_addendum="re-roll",
        )
        assert claim_discipline_score(result) == 0.0


class TestNarrationSurfaceLiteral:
    def test_known_surface_strings(self) -> None:
        # Compile-time + runtime check that Literal type lists the 5 surfaces.
        surfaces: list[NarrationSurface] = [
            "director",
            "spontaneous",
            "autonomous",
            "persona",
            "grounding-act",
        ]
        for s in surfaces:
            assert s in SURFACE_FLOORS
