"""Tests for audio-pathways Phase 3 — voice-embedding ducking gate.

Spec: docs/superpowers/specs/2026-04-18-audio-pathways-audit-design.md §3.2.
Plan: docs/superpowers/plans/2026-04-20-audio-pathways-audit-plan.md §lines 140-164.

Verifies:
  - VAD inactive → no duck regardless of embedding match
  - VAD + embedding >= 0.75 → duck with reason vad_and_embedding
  - VAD + 0.4 <= embedding < 0.75 → duck with reason vad_only_fallback
  - VAD + embedding < 0.4 → no duck, reason no_duck_phantom
  - Boundary values exactly at thresholds behave deterministically
  - Custom thresholds honoured (env-override path)
  - evaluate_and_emit fires the emit callback for non-silent decisions
  - emit callback exception does NOT propagate
"""

from __future__ import annotations

import pytest  # noqa: TC002

from agents.hapax_daimonion.voice_gate import (
    HIGH_CONFIDENCE_THRESHOLD,
    PHANTOM_THRESHOLD,
    DuckDecision,
    evaluate_and_emit,
    should_duck,
)

# ── Threshold defaults ─────────────────────────────────────────────────


class TestThresholds:
    def test_high_threshold_default_is_0_75(self) -> None:
        assert pytest.approx(0.75) == HIGH_CONFIDENCE_THRESHOLD

    def test_phantom_threshold_default_is_0_4(self) -> None:
        assert pytest.approx(0.4) == PHANTOM_THRESHOLD


# ── Core decision matrix (spec §3.2) ───────────────────────────────────


class TestDecisionMatrix:
    def test_vad_inactive_never_ducks(self) -> None:
        decision = should_duck(vad_active=False, embedding_match=0.95)
        assert decision.duck is False
        assert decision.reason == "no_duck_silent"

    def test_vad_active_with_high_embedding_ducks(self) -> None:
        decision = should_duck(vad_active=True, embedding_match=0.9)
        assert decision.duck is True
        assert decision.reason == "vad_and_embedding"

    def test_vad_active_with_mid_embedding_ducks_with_caveat(self) -> None:
        decision = should_duck(vad_active=True, embedding_match=0.55)
        assert decision.duck is True
        assert decision.reason == "vad_only_fallback"

    def test_vad_active_with_low_embedding_does_not_duck(self) -> None:
        decision = should_duck(vad_active=True, embedding_match=0.3)
        assert decision.duck is False
        assert decision.reason == "no_duck_phantom"


# ── Boundary values ────────────────────────────────────────────────────


class TestBoundaryValues:
    def test_exactly_high_threshold_ducks_high_confidence(self) -> None:
        """0.75 exactly → vad_and_embedding (>= comparison)."""
        decision = should_duck(vad_active=True, embedding_match=0.75)
        assert decision.duck is True
        assert decision.reason == "vad_and_embedding"

    def test_exactly_phantom_threshold_ducks_low_confidence(self) -> None:
        """0.4 exactly → vad_only_fallback (>= comparison)."""
        decision = should_duck(vad_active=True, embedding_match=0.4)
        assert decision.duck is True
        assert decision.reason == "vad_only_fallback"

    def test_just_below_phantom_threshold_no_duck(self) -> None:
        decision = should_duck(vad_active=True, embedding_match=0.39)
        assert decision.duck is False
        assert decision.reason == "no_duck_phantom"

    def test_negative_embedding_treated_as_phantom(self) -> None:
        """A negative cosine (anticorrelated voices) is unambiguously
        not the operator → no duck.
        """
        decision = should_duck(vad_active=True, embedding_match=-0.2)
        assert decision.duck is False
        assert decision.reason == "no_duck_phantom"


# ── Custom thresholds ──────────────────────────────────────────────────


class TestCustomThresholds:
    def test_lower_high_threshold_promotes_decision(self) -> None:
        """Tighter (lower) high threshold → mid-range decision becomes
        high-confidence."""
        decision = should_duck(
            vad_active=True,
            embedding_match=0.55,
            high_threshold=0.5,
            phantom_threshold=0.2,
        )
        assert decision.duck is True
        assert decision.reason == "vad_and_embedding"

    def test_higher_phantom_threshold_blocks_more(self) -> None:
        """Looser (higher) phantom threshold → mid-range decision becomes
        no-duck."""
        decision = should_duck(
            vad_active=True,
            embedding_match=0.55,
            high_threshold=0.9,
            phantom_threshold=0.6,
        )
        assert decision.duck is False
        assert decision.reason == "no_duck_phantom"


# ── DuckDecision shape ────────────────────────────────────────────────


class TestDuckDecisionShape:
    def test_decision_carries_embedding_match(self) -> None:
        decision = should_duck(vad_active=True, embedding_match=0.812)
        assert decision.embedding_match == pytest.approx(0.812)

    def test_decision_is_frozen_dataclass(self) -> None:
        decision = should_duck(vad_active=False, embedding_match=0.0)
        with pytest.raises((AttributeError, Exception)):
            decision.duck = True  # type: ignore[misc]


# ── evaluate_and_emit observability hook ──────────────────────────────


class TestEvaluateAndEmit:
    def test_emit_fires_for_high_confidence_duck(self) -> None:
        captured: list[str] = []
        decision = evaluate_and_emit(vad_active=True, embedding_match=0.9, emit=captured.append)
        assert decision.duck is True
        assert captured == ["vad_and_embedding"]

    def test_emit_fires_for_phantom_no_duck(self) -> None:
        captured: list[str] = []
        decision = evaluate_and_emit(vad_active=True, embedding_match=0.2, emit=captured.append)
        assert decision.duck is False
        assert captured == ["no_duck_phantom"]

    def test_emit_skipped_for_silent_decision(self) -> None:
        """When VAD is inactive (silence), the emit hook does not fire —
        no metric pollution from steady-state silence.
        """
        captured: list[str] = []
        evaluate_and_emit(vad_active=False, embedding_match=0.9, emit=captured.append)
        assert captured == []

    def test_emit_exception_does_not_propagate(self) -> None:
        """A broken emit callback must not break the pipeline."""

        def boom(reason: str) -> None:
            raise RuntimeError("emit broken")

        decision = evaluate_and_emit(vad_active=True, embedding_match=0.9, emit=boom)
        # Decision still returned despite emit failure
        assert decision.duck is True
        assert decision.reason == "vad_and_embedding"

    def test_no_emit_callback_works(self) -> None:
        """Calling without an emit callback returns the decision cleanly."""
        decision = evaluate_and_emit(vad_active=True, embedding_match=0.5)
        assert isinstance(decision, DuckDecision)
        assert decision.duck is True
