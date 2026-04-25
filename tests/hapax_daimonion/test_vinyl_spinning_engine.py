"""Tests for ``agents.hapax_daimonion.vinyl_spinning_engine``."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agents.hapax_daimonion.vinyl_spinning_engine import (
    DEFAULT_PRIOR,
    VinylSpinningEngine,
)


def _write_album_state(path: Path, *, confidence: float, age_s: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"confidence": confidence}))
    if age_s:
        ts = time.time() - age_s
        import os

        os.utime(path, (ts, ts))


def _write_perception_state(
    path: Path, *, hand_zone: str = "", hand_activity: str = "", age_s: float = 0.0
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ir_hand_zone": hand_zone, "ir_hand_activity": hand_activity}))
    if age_s:
        ts = time.time() - age_s
        import os

        os.utime(path, (ts, ts))


def _make_engine(tmp_path: Path) -> VinylSpinningEngine:
    return VinylSpinningEngine(
        album_state_file=tmp_path / "album-state.json",
        perception_state_file=tmp_path / "perception-state.json",
        operator_override_flag=tmp_path / "vinyl-operator-active.flag",
    )


# ── Initial state ────────────────────────────────────────────────────


class TestInitialState:
    def test_starts_at_prior_uncertain(self, tmp_path):
        engine = _make_engine(tmp_path)
        assert engine.posterior == pytest.approx(DEFAULT_PRIOR, abs=1e-9)
        assert engine.state == "UNCERTAIN"
        assert engine.is_spinning is False

    def test_no_signal_files_keeps_prior(self, tmp_path):
        engine = _make_engine(tmp_path)
        engine.tick()
        # No observations contributed → posterior stays at prior.
        assert engine.posterior == pytest.approx(DEFAULT_PRIOR, abs=1e-9)
        assert engine.is_spinning is False


# ── Signal: operator override ────────────────────────────────────────


class TestOperatorOverride:
    def test_override_flag_drives_posterior_high(self, tmp_path):
        engine = _make_engine(tmp_path)
        (tmp_path / "vinyl-operator-active.flag").touch()
        engine.tick()
        # Operator-override LR ~99/0.01 → single tick lands ~0.92.
        assert engine.posterior > 0.85

    def test_override_alone_reaches_asserted_after_k_enter(self, tmp_path):
        engine = _make_engine(tmp_path)
        (tmp_path / "vinyl-operator-active.flag").touch()
        # Operator-override hits LR ~99/0.01 — single tick crosses
        # enter_threshold. ASSERT requires sustaining for k_enter ticks.
        for _ in range(8):
            engine.tick()
        assert engine.state == "ASSERTED"
        assert engine.is_spinning is True


# ── Signal: album cover fresh ────────────────────────────────────────


class TestAlbumCoverFresh:
    def test_cover_alone_does_not_lift_posterior(self, tmp_path):
        """Cover-fresh WITHOUT hand-on-turntable contributes nothing.

        Load-bearing test for the operator's reported bug: the album-
        identifier writes ALBUM_STATE_FILE while the cover sits in the
        IR field even when the platter is silent. Cover-alone must NOT
        be evidence of spinning.
        """
        engine = _make_engine(tmp_path)
        _write_album_state(tmp_path / "album-state.json", confidence=0.9)
        for _ in range(15):
            engine.tick()
        assert engine.posterior == pytest.approx(DEFAULT_PRIOR, abs=1e-9)
        assert engine.is_spinning is False

    def test_low_confidence_treated_as_no_evidence(self, tmp_path):
        engine = _make_engine(tmp_path)
        _write_album_state(tmp_path / "album-state.json", confidence=0.2)
        engine.tick()
        # Confidence below threshold → contributes None (no evidence).
        assert engine.posterior == pytest.approx(DEFAULT_PRIOR, abs=1e-9)

    def test_stale_album_state_treated_as_no_evidence(self, tmp_path):
        engine = _make_engine(tmp_path)
        _write_album_state(
            tmp_path / "album-state.json",
            confidence=0.9,
            age_s=600,  # > 300s stale cutoff
        )
        engine.tick()
        assert engine.posterior == pytest.approx(DEFAULT_PRIOR, abs=1e-9)


# ── Signal: hand on turntable ────────────────────────────────────────


class TestHandOnTurntable:
    def test_hand_alone_does_not_lift_posterior(self, tmp_path):
        """Hand-on-turntable WITHOUT cover-fresh contributes nothing.

        Operator may handle the deck without playing (queueing the
        next album, cleaning the stylus, swapping covers). Hand-alone
        is not evidence of spinning.
        """
        engine = _make_engine(tmp_path)
        _write_perception_state(tmp_path / "perception-state.json", hand_zone="turntable")
        for _ in range(15):
            engine.tick()
        assert engine.posterior == pytest.approx(DEFAULT_PRIOR, abs=1e-9)
        assert engine.is_spinning is False

    def test_stale_perception_state_treated_as_no_evidence(self, tmp_path):
        # With cover present (would otherwise conjunct), stale hand
        # state still contributes None → no posterior lift.
        engine = _make_engine(tmp_path)
        _write_album_state(tmp_path / "album-state.json", confidence=0.9)
        _write_perception_state(
            tmp_path / "perception-state.json",
            hand_zone="turntable",
            age_s=200,  # > 120s stale cutoff
        )
        engine.tick()
        assert engine.posterior == pytest.approx(DEFAULT_PRIOR, abs=1e-9)


# ── Asymmetric temporal profile (slow-enter / fast-exit) ────────────


class TestAsymmetricProfile:
    def test_single_signal_does_not_immediately_assert(self, tmp_path):
        """Cover-only (no hand) must NOT reach ASSERTED.

        Load-bearing for the operator's reported bug: the conjunction
        is required — cover alone is upstream-zeroed to None before
        reaching the engine.
        """
        engine = _make_engine(tmp_path)
        _write_album_state(tmp_path / "album-state.json", confidence=0.9)
        for _ in range(15):
            engine.tick()
        assert engine.state in {"UNCERTAIN", "RETRACTED"}, (
            f"single weak signal asserted vinyl spinning (posterior={engine.posterior})"
        )
        assert engine.is_spinning is False

    def test_two_signals_assert_after_k_enter(self, tmp_path):
        """Cover + hand-on-turntable together should ASSERT (slow-enter)."""
        engine = _make_engine(tmp_path)
        _write_album_state(tmp_path / "album-state.json", confidence=0.9)
        _write_perception_state(tmp_path / "perception-state.json", hand_zone="turntable")
        for _ in range(10):
            engine.tick()
        assert engine.state == "ASSERTED"
        assert engine.is_spinning is True

    def test_fast_retraction_when_signals_drop(self, tmp_path):
        """Once asserted, removing signals retracts within k_exit ticks."""
        engine = _make_engine(tmp_path)
        _write_album_state(tmp_path / "album-state.json", confidence=0.9)
        _write_perception_state(tmp_path / "perception-state.json", hand_zone="turntable")
        for _ in range(10):
            engine.tick()
        assert engine.state == "ASSERTED"

        # Drop signals (simulate operator removing album / leaving deck).
        (tmp_path / "album-state.json").unlink()
        (tmp_path / "perception-state.json").unlink()
        # k_exit=2 + dwell — give ample ticks; should retract quickly.
        for _ in range(8):
            engine.tick()
        assert engine.state in {"UNCERTAIN", "RETRACTED"}
        assert engine.is_spinning is False


# ── Bypass ───────────────────────────────────────────────────────────


class TestBypass:
    def test_bypass_pins_posterior_to_prior(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HAPAX_BAYESIAN_BYPASS", "1")
        engine = _make_engine(tmp_path)
        # Strongest possible signal — operator override.
        (tmp_path / "vinyl-operator-active.flag").touch()
        engine.tick()
        # Bypass active → update is no-op, posterior pinned to prior.
        assert engine.posterior == pytest.approx(DEFAULT_PRIOR, abs=1e-9)
        assert engine.state == "UNCERTAIN"
        assert engine.is_spinning is False
