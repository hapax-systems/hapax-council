"""Tests for ``agents.hapax_daimonion.music_playing_engine``."""

from __future__ import annotations

import pytest

from agents.hapax_daimonion.music_playing_engine import (
    DEFAULT_PRIOR,
    MUSIC_POSTERIOR_THRESHOLD,
    MusicPlayingEngine,
)


def _make_engine(
    *,
    capture_returns,  # type: ignore[no-untyped-def]
    classify_returns: float | None = None,
    music_threshold: float = MUSIC_POSTERIOR_THRESHOLD,
) -> MusicPlayingEngine:
    """Build an engine with deterministic capture + classify behavior."""
    return MusicPlayingEngine(
        capture_fn=lambda: capture_returns,
        classify_fn=lambda _audio: classify_returns,
        music_threshold=music_threshold,
    )


# ── Initial state ────────────────────────────────────────────────────


class TestInitialState:
    def test_starts_at_prior_uncertain(self):
        engine = _make_engine(capture_returns=None)
        assert engine.posterior == pytest.approx(DEFAULT_PRIOR, abs=1e-9)
        assert engine.state == "UNCERTAIN"
        assert engine.is_playing is False


# ── Capture failure ──────────────────────────────────────────────────


class TestCaptureFailure:
    def test_capture_returns_none_keeps_prior(self):
        engine = _make_engine(capture_returns=None)
        engine.tick()
        # No audio captured → no observation → posterior at prior.
        assert engine.posterior == pytest.approx(DEFAULT_PRIOR, abs=1e-9)


# ── Classification result drives signal ──────────────────────────────


class TestMusicScore:
    def test_music_score_above_threshold_lifts_posterior(self):
        engine = _make_engine(capture_returns=[0.0] * 96000, classify_returns=0.85)
        engine.tick()
        assert engine.posterior > DEFAULT_PRIOR

    def test_music_score_below_threshold_lowers_posterior(self):
        engine = _make_engine(capture_returns=[0.0] * 96000, classify_returns=0.10)
        engine.tick()
        # Bidirectional signal: low score = direct evidence of NO music.
        assert engine.posterior < DEFAULT_PRIOR

    def test_classify_returns_none_keeps_prior(self):
        engine = _make_engine(capture_returns=[0.0] * 96000, classify_returns=None)
        engine.tick()
        assert engine.posterior == pytest.approx(DEFAULT_PRIOR, abs=1e-9)

    def test_threshold_boundary_inclusive(self):
        """Score exactly at threshold counts as music present."""
        engine = _make_engine(
            capture_returns=[0.0] * 96000,
            classify_returns=MUSIC_POSTERIOR_THRESHOLD,
        )
        engine.tick()
        # >=threshold → True → posterior lifts.
        assert engine.posterior > DEFAULT_PRIOR


# ── Asymmetric temporal profile ─────────────────────────────────────


class TestAsymmetricProfile:
    def test_sustained_music_reaches_asserted(self):
        """Sustained high-music signal asserts after k_enter ticks."""
        engine = _make_engine(capture_returns=[0.0] * 96000, classify_returns=0.85)
        for _ in range(8):
            engine.tick()
        assert engine.state == "ASSERTED"
        assert engine.is_playing is True

    def test_sustained_silence_drives_to_retracted(self):
        """Sustained low-music signal retracts."""
        engine = _make_engine(capture_returns=[0.0] * 96000, classify_returns=0.05)
        for _ in range(15):
            engine.tick()
        assert engine.state in {"UNCERTAIN", "RETRACTED"}
        assert engine.is_playing is False

    def test_fast_retraction_when_music_drops(self):
        """Once asserted, a sustained low-music signal retracts quickly."""
        # Phase 1: assert with high-music signal.
        capture_returns = [0.0] * 96000
        classify_value = [0.85]
        engine = MusicPlayingEngine(
            capture_fn=lambda: capture_returns,
            classify_fn=lambda _a: classify_value[0],
        )
        for _ in range(8):
            engine.tick()
        assert engine.state == "ASSERTED"

        # Phase 2: switch classifier output to low-music.
        classify_value[0] = 0.05
        for _ in range(8):
            engine.tick()
        assert engine.state in {"UNCERTAIN", "RETRACTED"}
        assert engine.is_playing is False


# ── Bypass ───────────────────────────────────────────────────────────


class TestBypass:
    def test_bypass_pins_posterior_to_prior(self, monkeypatch):
        monkeypatch.setenv("HAPAX_BAYESIAN_BYPASS", "1")
        engine = _make_engine(capture_returns=[0.0] * 96000, classify_returns=0.99)
        engine.tick()
        assert engine.posterior == pytest.approx(DEFAULT_PRIOR, abs=1e-9)
        assert engine.state == "UNCERTAIN"
        assert engine.is_playing is False
