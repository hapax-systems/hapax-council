"""Phase 4 / Phase 5 live-wire bridge smoke + status pin (AUDIT-04).

Pins the current state of Phase 4 (``shared.claim_prompt.render_envelope``)
and Phase 5 (``shared.claim_refusal.RefusalGate``) live wiring across the
five narration surfaces. The library API works for all five; only a subset
is currently wired into runtime call sites. This test pins the wiring
status so a future bridge PR that wires a remaining surface flips the
exact assertion that records its absence here.

Bridge audit: ``docs/superpowers/handoff/2026-05-01-beta-audit-04-phase-4-5-live-wire-bridge.md``.

cc-task: ``audit-04-phase-4-5-live-wire-bridge``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from shared.claim import Claim, EvidenceRef, TemporalProfile
from shared.claim_prompt import (
    CLAIMS_BLOCK_HEADER,
    SURFACE_FLOORS,
    UNCERTAINTY_CONTRACT,
    render_envelope,
)
from shared.claim_refusal import RefusalGate, RefusalResult

REPO_ROOT = Path(__file__).resolve().parent.parent

NARRATION_SURFACES: tuple[str, ...] = (
    "director",
    "spontaneous_speech",
    "autonomous_narrative",
    "voice_persona",
    "grounding_act",
)

# Source-of-truth map: which file imports / uses which side of the bridge.
# Format: surface -> (phase4_consumer_path, phase5_consumer_path | None).
# A None on the Phase 5 side means library-only — the live wire has not
# landed yet and the bridge cc-task split is the next step.
LIVE_WIRE_MAP: dict[str, tuple[str, str | None]] = {
    "director": (
        "agents/studio_compositor/director_loop.py",
        "agents/studio_compositor/director_loop.py",
    ),
    "spontaneous_speech": (
        "agents/hapax_daimonion/conversation_pipeline.py",
        None,
    ),
    "voice_persona": (
        "agents/hapax_daimonion/persona.py",
        None,
    ),
    "autonomous_narrative": (
        "agents/hapax_daimonion/autonomous_narrative/compose.py",
        None,
    ),
    "grounding_act": (
        None,
        None,
    ),
}


def _claim(name: str, posterior: float, *, floor: float = 0.60) -> Claim:
    return Claim(
        name=name,
        domain="audio",
        proposition=f"the {name.replace('_', ' ')} signal is true",
        posterior=posterior,
        prior_source="reference",
        prior_provenance_ref=f"{name}.v1",
        evidence_sources=[
            EvidenceRef(
                signal_name=name,
                value=True,
                timestamp=1714000000.0,
                frame_source="raw_sensor",
            )
        ],
        last_update_t=1714000000.0,
        temporal_profile=TemporalProfile(
            enter_threshold=0.7, exit_threshold=0.3, k_enter=2, k_exit=24
        ),
        narration_floor=floor,
        staleness_cutoff_s=60.0,
    )


# ── Phase 4 library smoke ───────────────────────────────────────────────


class TestPhase4EnvelopeLibrary:
    """Phase 4 ``render_envelope`` works for every narration surface."""

    @pytest.mark.parametrize("surface", NARRATION_SURFACES)
    def test_renders_for_every_surface(self, surface: str) -> None:
        floor = SURFACE_FLOORS[surface]
        env = render_envelope([], floor=floor)
        assert UNCERTAINTY_CONTRACT in env
        assert CLAIMS_BLOCK_HEADER.format(floor=floor) in env

    @pytest.mark.parametrize("surface", NARRATION_SURFACES)
    def test_above_floor_claim_renders_with_posterior(self, surface: str) -> None:
        floor = SURFACE_FLOORS[surface]
        # Use a posterior strictly above floor so the assertion holds at
        # every surface, including ``grounding_act`` where floor is 0.90.
        claim = _claim("operator_present", min(0.99, floor + 0.05), floor=floor)
        env = render_envelope([claim], floor=floor)
        assert "[p=" in env
        assert "operator present signal" in env

    @pytest.mark.parametrize("surface", NARRATION_SURFACES)
    def test_below_floor_claim_renders_as_unknown(self, surface: str) -> None:
        floor = SURFACE_FLOORS[surface]
        claim = _claim("operator_present", max(0.0, floor - 0.10), floor=floor)
        env = render_envelope([claim], floor=floor)
        assert "[UNKNOWN]" in env


# ── Phase 5 library smoke ───────────────────────────────────────────────


class TestPhase5RefusalGateLibrary:
    """Phase 5 ``RefusalGate`` works for every narration surface."""

    @pytest.mark.parametrize("surface", NARRATION_SURFACES)
    def test_gate_constructable_for_every_surface(self, surface: str) -> None:
        gate = RefusalGate(surface=surface)
        assert gate.surface == surface
        assert gate.floor == SURFACE_FLOORS[surface]

    @pytest.mark.parametrize("surface", NARRATION_SURFACES)
    def test_empty_emission_accepted(self, surface: str) -> None:
        gate = RefusalGate(surface=surface)
        result = gate.check("", available_claims=[])
        assert isinstance(result, RefusalResult)
        assert result.accepted

    @pytest.mark.parametrize("surface", NARRATION_SURFACES)
    def test_question_emission_accepted(self, surface: str) -> None:
        """Questions are not declarative assertions and pass any floor."""
        gate = RefusalGate(surface=surface)
        result = gate.check("Is the operator present?", available_claims=[])
        assert result.accepted

    def test_unknown_surface_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown surface"):
            RefusalGate(surface="not_a_surface")  # type: ignore[arg-type]

    def test_above_floor_emission_accepted(self) -> None:
        """Sufficiently high posterior backs an asserted proposition."""
        gate = RefusalGate(surface="director")
        claim = _claim("operator_present", 0.95, floor=SURFACE_FLOORS["director"])
        result = gate.check(
            "The operator present signal is true.",
            available_claims=[claim],
        )
        assert result.accepted

    def test_below_floor_emission_rejected_with_addendum(self) -> None:
        """Below-floor posterior triggers rejection + re-roll addendum."""
        gate = RefusalGate(surface="director")
        claim = _claim("operator_present", 0.20, floor=SURFACE_FLOORS["director"])
        result = gate.check(
            "The operator present signal is true.",
            available_claims=[claim],
        )
        assert not result.accepted
        assert result.rejected_propositions
        assert "rejected:" in result.reroll_prompt_addendum


# ── Live-wire status pin ────────────────────────────────────────────────


class TestPhase4LiveWires:
    """Pin the current set of Phase 4 ``render_envelope`` consumers."""

    @pytest.mark.parametrize(
        "surface",
        ["director", "spontaneous_speech", "voice_persona", "autonomous_narrative"],
    )
    def test_phase4_envelope_consumer_imports_render_envelope(self, surface: str) -> None:
        """Each wired narration surface imports ``render_envelope``.

        ``grounding_act`` has no Phase 4 consumer yet — see the dedicated
        gap-pin below.
        """
        consumer = LIVE_WIRE_MAP[surface][0]
        assert consumer is not None
        path = REPO_ROOT / consumer
        assert path.exists(), f"{consumer} missing"
        text = path.read_text(encoding="utf-8")
        assert "render_envelope" in text, (
            f"{consumer} does not import render_envelope; Phase 4 wiring regressed"
        )

    def test_grounding_act_phase4_remains_library_only(self) -> None:
        """No production consumer wires render_envelope for grounding_act yet.

        When the grounding-act bridge lands, flip this assertion (or
        switch to ``LIVE_WIRE_MAP["grounding_act"]``-based path scanning).
        """
        # Scan all production code paths for any caller using the
        # ``grounding_act`` surface key alongside ``render_envelope``.
        production_dirs = (REPO_ROOT / "agents", REPO_ROOT / "logos", REPO_ROOT / "shared")
        pattern = re.compile(
            r"render_envelope\s*\([^)]*SURFACE_FLOORS\[\s*[\"']grounding_act[\"']\s*\]"
        )
        offenders: list[str] = []
        for root in production_dirs:
            for py in root.rglob("*.py"):
                if py.name == "claim_prompt.py":
                    continue
                if pattern.search(py.read_text(encoding="utf-8")):
                    offenders.append(str(py.relative_to(REPO_ROOT)))
        assert offenders == [], (
            "grounding_act now has Phase 4 consumers — update LIVE_WIRE_MAP "
            f"+ retire this pin (offenders: {offenders})"
        )


class TestPhase5LiveWires:
    """Pin the current set of Phase 5 ``RefusalGate`` consumers."""

    def test_director_has_refusal_gate_wired(self) -> None:
        path = REPO_ROOT / "agents/studio_compositor/director_loop.py"
        text = path.read_text(encoding="utf-8")
        assert "RefusalGate" in text, (
            "director_loop no longer imports RefusalGate — Phase 5 wiring regressed"
        )
        assert 'surface="director"' in text or "surface='director'" in text

    @pytest.mark.parametrize(
        "surface",
        ["spontaneous_speech", "voice_persona", "autonomous_narrative", "grounding_act"],
    )
    def test_non_director_surfaces_remain_library_only(self, surface: str) -> None:
        """No production consumer constructs RefusalGate for these yet.

        The bridge cc-tasks (split per surface) wire each one. When that
        lands for any surface, update ``LIVE_WIRE_MAP`` and switch this
        case from "remains library-only" to "is wired".
        """
        production_dirs = (REPO_ROOT / "agents", REPO_ROOT / "logos", REPO_ROOT / "shared")
        # Match either double or single quoted surface keyword.
        pattern = re.compile(rf"RefusalGate\s*\(\s*surface\s*=\s*[\"']{re.escape(surface)}[\"']")
        offenders: list[str] = []
        for root in production_dirs:
            for py in root.rglob("*.py"):
                if py.name == "claim_refusal.py":
                    continue
                if pattern.search(py.read_text(encoding="utf-8")):
                    offenders.append(str(py.relative_to(REPO_ROOT)))
        assert offenders == [], (
            f"surface {surface!r} now has Phase 5 wiring — update LIVE_WIRE_MAP "
            f"+ flip this pin to assert presence (offenders: {offenders})"
        )


# ── End-to-end live-wire smoke (director surface) ───────────────────────


class TestPhase4Phase5DirectorBridgeSmoke:
    """End-to-end smoke for the only fully-bridged surface today."""

    def test_envelope_then_refusal_round_trip(self) -> None:
        """Render an envelope, ask the gate, get an accept on a high claim."""
        floor = SURFACE_FLOORS["director"]
        claim = _claim("operator_present", 0.95, floor=floor)
        env = render_envelope([claim], floor=floor)
        assert "operator present signal" in env

        gate = RefusalGate(surface="director")
        result = gate.check(
            "The operator present signal is true.",
            available_claims=[claim],
        )
        assert result.accepted

    def test_envelope_renders_low_claim_unknown_then_gate_rejects_assertion(self) -> None:
        """Below-floor claim renders [UNKNOWN]; gate rejects an asserting echo."""
        floor = SURFACE_FLOORS["director"]
        claim = _claim("operator_present", 0.20, floor=floor)
        env = render_envelope([claim], floor=floor)
        assert "[UNKNOWN]" in env
        assert "[p=" not in env

        gate = RefusalGate(surface="director")
        result = gate.check(
            "The operator present signal is true.",
            available_claims=[claim],
        )
        assert not result.accepted
