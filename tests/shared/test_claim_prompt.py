"""Tests for shared.claim_prompt — Phase 4 prompt-envelope renderer.

145-LOC pure renderer that turns Claim instances into the per-prompt
envelope every narration surface (director, spontaneous-speech,
autonomous-narrative, voice-persona, grounding-act) prepends to its
system prompt. Untested before this commit.

Tests construct minimal ``Claim`` instances directly (the renderer
only reads ``posterior``, ``proposition``, ``name``, and
``evidence_sources[0].signal_name``).
"""

from __future__ import annotations

from shared.claim import Claim, EvidenceRef
from shared.claim_prompt import (
    CLAIMS_BLOCK_HEADER,
    SURFACE_FLOORS,
    UNCERTAINTY_CONTRACT,
    render_claims,
    render_envelope,
)


def _claim(
    *,
    name: str = "operator-present",
    proposition: str = "the operator is at the desk",
    posterior: float = 0.9,
    signal_name: str | None = "ir-presence",
) -> Claim:
    """Construct a minimal Claim. Pydantic validators require the full
    field set, but the renderer only reads four of them — the rest
    are filled with neutral defaults."""
    evidence = (
        [
            EvidenceRef(
                signal_name=signal_name,
                value=True,
                timestamp=0.0,
                frame_source="raw_sensor",
            )
        ]
        if signal_name
        else []
    )
    return Claim(
        name=name,
        domain="activity",
        proposition=proposition,
        posterior=posterior,
        prior_source="maximum_entropy",
        prior_provenance_ref="test",
        evidence_sources=evidence,
        last_update_t=0.0,
        temporal_profile={
            "enter_threshold": 0.6,
            "exit_threshold": 0.4,
            "k_enter": 2,
            "k_exit": 4,
        },  # type: ignore[arg-type]
        narration_floor=0.6,
        staleness_cutoff_s=60.0,
    )


# ── Above/below floor rendering ────────────────────────────────────


class TestRenderClaims:
    def test_above_floor_uses_p_eq_form(self) -> None:
        claim = _claim(posterior=0.92, proposition="P", signal_name="src-x")
        result = render_claims([claim], floor=0.6)
        assert "[p=0.92 src=src-x] P" in result

    def test_below_floor_uses_unknown_form(self) -> None:
        claim = _claim(posterior=0.30, proposition="Q")
        result = render_claims([claim], floor=0.6)
        assert "[UNKNOWN] Q" in result
        assert "p=0.30" not in result

    def test_at_floor_is_above_floor(self) -> None:
        """Claims with posterior exactly equal to floor render with p=
        form (the implementation uses ``>=``)."""
        claim = _claim(posterior=0.6, proposition="R")
        result = render_claims([claim], floor=0.6)
        assert "[p=0.60 src=" in result
        assert "[UNKNOWN]" not in result

    def test_source_label_falls_back_to_name_when_no_evidence(self) -> None:
        """Claims with no evidence_sources fall back to ``claim.name`` for
        the src label (per _source_label)."""
        claim = _claim(posterior=0.9, proposition="S", signal_name=None, name="fallback-name")
        result = render_claims([claim], floor=0.6)
        assert "src=fallback-name" in result

    def test_first_evidence_source_used(self) -> None:
        """When multiple evidence_sources exist, the FIRST signal_name
        is used as the src label."""
        claim = _claim(posterior=0.9, signal_name="primary")
        # add a second evidence ref
        claim.evidence_sources.append(
            EvidenceRef(
                signal_name="secondary",
                value=True,
                timestamp=0.0,
                frame_source="raw_sensor",
            )
        )
        result = render_claims([claim], floor=0.6)
        assert "src=primary" in result
        assert "src=secondary" not in result


# ── Empty list ─────────────────────────────────────────────────────


class TestEmptyClaimsList:
    def test_empty_returns_sentinel_block(self) -> None:
        result = render_claims([], floor=0.6)
        assert "(no perceptual claims active)" in result

    def test_header_includes_floor(self) -> None:
        result = render_claims([], floor=0.85)
        assert "0.85" in result


# ── Multiple claims ────────────────────────────────────────────────


class TestMultipleClaims:
    def test_each_claim_on_its_own_line(self) -> None:
        c1 = _claim(name="c1", proposition="A", posterior=0.9, signal_name="s1")
        c2 = _claim(name="c2", proposition="B", posterior=0.3, signal_name="s2")
        result = render_claims([c1, c2], floor=0.6)
        lines = result.split("\n")
        assert any("p=0.90 src=s1] A" in line for line in lines)
        assert any("[UNKNOWN] B" in line for line in lines)

    def test_header_appears_first(self) -> None:
        c = _claim()
        result = render_claims([c], floor=0.6)
        assert result.startswith(CLAIMS_BLOCK_HEADER.format(floor=0.6))


# ── Surface floors ─────────────────────────────────────────────────


class TestSurfaceFloors:
    def test_all_documented_surfaces_present(self) -> None:
        assert SURFACE_FLOORS == {
            "director": 0.60,
            "spontaneous_speech": 0.70,
            "autonomous_narrative": 0.75,
            "voice_persona": 0.80,
            "grounding_act": 0.90,
        }

    def test_floors_strictly_increase_per_brittleness(self) -> None:
        order = [
            "director",
            "spontaneous_speech",
            "autonomous_narrative",
            "voice_persona",
            "grounding_act",
        ]
        floors = [SURFACE_FLOORS[s] for s in order]
        assert floors == sorted(floors)


# ── render_envelope ────────────────────────────────────────────────


class TestRenderEnvelope:
    def test_includes_uncertainty_contract_first(self) -> None:
        result = render_envelope([], floor=0.6)
        assert result.startswith(UNCERTAINTY_CONTRACT)

    def test_includes_claims_block_after_contract(self) -> None:
        c = _claim(posterior=0.9, proposition="X", signal_name="s")
        result = render_envelope([c], floor=0.6)
        # Contract first, blank line, then claims block (with header).
        assert UNCERTAINTY_CONTRACT in result
        assert CLAIMS_BLOCK_HEADER.format(floor=0.6) in result
        assert "p=0.90 src=s] X" in result
