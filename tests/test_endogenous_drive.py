"""Tests for shared.endogenous_drive — Bayesian drive evaluator."""

from __future__ import annotations

import time

import pytest

from shared.endogenous_drive import DriveContext, EndogenousDrive


class TestPressureAccumulation:
    def test_zero_elapsed_zero_pressure(self):
        drive = EndogenousDrive(tau=120.0)
        drive._last_emission_ts = time.time()
        assert drive.base_pressure() == pytest.approx(0.0, abs=0.01)

    def test_pressure_at_tau(self):
        drive = EndogenousDrive(tau=120.0)
        now = time.time()
        drive._last_emission_ts = now - 120.0
        # 1 - e^(-1) ≈ 0.632
        assert drive.base_pressure(now) == pytest.approx(0.632, abs=0.01)

    def test_pressure_at_2tau(self):
        drive = EndogenousDrive(tau=120.0)
        now = time.time()
        drive._last_emission_ts = now - 240.0
        # 1 - e^(-2) ≈ 0.865
        assert drive.base_pressure(now) == pytest.approx(0.865, abs=0.01)

    def test_pressure_at_3tau(self):
        drive = EndogenousDrive(tau=120.0)
        now = time.time()
        drive._last_emission_ts = now - 360.0
        # 1 - e^(-3) ≈ 0.950
        assert drive.base_pressure(now) == pytest.approx(0.950, abs=0.01)

    def test_pressure_bounded_at_one(self):
        drive = EndogenousDrive(tau=120.0)
        now = time.time()
        drive._last_emission_ts = now - 100000.0
        # At extreme elapsed times, float64 underflow makes pressure
        # exactly 1.0 — that's fine, it must never exceed 1.0.
        assert drive.base_pressure(now) <= 1.0

    def test_pressure_monotonically_increases(self):
        drive = EndogenousDrive(tau=120.0)
        now = time.time()
        drive._last_emission_ts = now - 300.0
        prev = 0.0
        for dt in range(0, 300, 10):
            p = drive.base_pressure(now - 300 + dt)
            assert p >= prev
            prev = p


class TestRefractory:
    def test_emission_resets_pressure(self):
        drive = EndogenousDrive(tau=120.0)
        now = time.time()
        drive._last_emission_ts = now - 300.0
        assert drive.base_pressure(now) > 0.9

        drive.record_emission(now)
        assert drive.base_pressure(now) == pytest.approx(0.0, abs=0.01)

    def test_pressure_rebuilds_after_emission(self):
        drive = EndogenousDrive(tau=120.0)
        now = time.time()
        drive.record_emission(now)
        # 60s later — pressure should be building
        assert drive.base_pressure(now + 60) == pytest.approx(0.393, abs=0.01)


class TestContextualModifiers:
    def test_chronicle_modifier_zero_events(self):
        drive = EndogenousDrive()
        assert drive._chronicle_modifier(0) == 1.0

    def test_chronicle_modifier_increases_with_count(self):
        drive = EndogenousDrive()
        m4 = drive._chronicle_modifier(4)
        m16 = drive._chronicle_modifier(16)
        m64 = drive._chronicle_modifier(64)
        assert 1.0 < m4 < m16 < m64

    def test_stimmung_ambient_boosts(self):
        drive = EndogenousDrive()
        assert drive._stimmung_modifier("ambient") > 1.0

    def test_stimmung_critical_suppresses(self):
        drive = EndogenousDrive()
        assert drive._stimmung_modifier("critical") < 1.0

    def test_all_stimmung_modifiers_positive(self):
        """No stimmung modifier may be zero (architectural invariant)."""
        from shared.endogenous_drive import _STIMMUNG_MODIFIERS

        for stance, mod in _STIMMUNG_MODIFIERS.items():
            assert mod > 0, f"stimmung {stance} has zero modifier"

    def test_all_role_modifiers_positive(self):
        """No role modifier may be zero (architectural invariant)."""
        from shared.endogenous_drive import _ROLE_AFFINITY

        for role, mod in _ROLE_AFFINITY.items():
            assert mod > 0, f"role {role} has zero modifier"

    def test_role_ambient_highest(self):
        drive = EndogenousDrive()
        assert drive._role_modifier("ambient") > drive._role_modifier("ritual")

    def test_presence_absent_boosts(self):
        drive = EndogenousDrive()
        assert drive._presence_modifier(0.0) > 1.0

    def test_presence_present_suppresses(self):
        drive = EndogenousDrive()
        assert drive._presence_modifier(1.0) < 1.0

    def test_presence_modifier_never_zero(self):
        drive = EndogenousDrive()
        assert drive._presence_modifier(1.0) > 0


class TestThompson:
    def test_initial_prior_biased_toward_success(self):
        drive = EndogenousDrive()
        # Beta(2, 1) mean = 2/3 ≈ 0.667
        assert drive._ts_alpha == 2.0
        assert drive._ts_beta == 1.0

    def test_record_success_increases_alpha(self):
        drive = EndogenousDrive()
        drive.record_outcome(success=True)
        assert drive._ts_alpha == 3.0
        assert drive._ts_beta == 1.0

    def test_record_failure_increases_beta(self):
        drive = EndogenousDrive()
        drive.record_outcome(success=False)
        assert drive._ts_alpha == 2.0
        assert drive._ts_beta == 2.0


class TestEvaluate:
    def test_evaluate_returns_positive(self):
        drive = EndogenousDrive(tau=120.0)
        drive._last_emission_ts = time.time() - 200.0
        ctx = DriveContext(chronicle_event_count=5, stimmung_stance="ambient")
        posterior = drive.evaluate(ctx)
        assert posterior > 0

    def test_high_pressure_high_chronicle_high_posterior(self, monkeypatch: pytest.MonkeyPatch):
        drive = EndogenousDrive(tau=120.0)
        monkeypatch.setattr(drive, "_thompson_sample", lambda: 0.8)
        now = time.time()
        drive._last_emission_ts = now - 600.0  # 5*tau
        ctx = DriveContext(
            chronicle_event_count=20,
            stimmung_stance="ambient",
            operator_presence_score=0.0,
            programme_role="ambient",
            now=now,
        )
        posterior = drive.evaluate(ctx)
        # Very high pressure, lots of events, ambient role, no operator
        assert posterior > 0.3

    def test_low_pressure_ritual_low_posterior(self):
        drive = EndogenousDrive(tau=120.0)
        now = time.time()
        drive._last_emission_ts = now - 30.0  # early accumulation
        ctx = DriveContext(
            chronicle_event_count=0,
            stimmung_stance="critical",
            operator_presence_score=0.9,
            programme_role="ritual",
            now=now,
        )
        posterior = drive.evaluate(ctx)
        # Low pressure, no events, critical stimmung, present operator, ritual
        assert posterior < 0.05


class TestExtremityOverride:
    def test_extreme_accumulation_breaks_through_ritual(self, monkeypatch: pytest.MonkeyPatch):
        """45 minutes of unnarrated rich chronicle during ritual should
        produce a non-trivial posterior despite role suppression.

        Pin the Thompson sample to its prior mean (Beta(2,1) → 0.67) so
        the assertion is deterministic. Without pinning, the random
        Beta(2,1) draw can fall low enough (~1% of runs) for the product
        ``1.0 * 2.2 * 1.2 * 0.35 * 1.3 * sample`` to dip below the 0.12
        threshold and flake CI.
        """
        drive = EndogenousDrive(tau=120.0)
        # Pin Thompson sample to Beta(2,1) prior mean — same idiom used
        # by ``test_high_pressure_high_chronicle_high_posterior``.
        monkeypatch.setattr(drive, "_thompson_sample", lambda: 0.67)
        now = time.time()
        drive._last_emission_ts = now - 2700.0  # 45 minutes
        ctx = DriveContext(
            chronicle_event_count=20,
            stimmung_stance="ambient",
            operator_presence_score=0.0,
            programme_role="ritual",
            now=now,
        )
        # With 45min accumulation, pressure ≈ 1.0
        # chronicle_mod ≈ 2.2 (20 events)
        # stimmung_mod = 1.2
        # role_mod = 0.35 (ritual)
        # presence_mod = 1.3 (absent)
        # thompson = 0.67 (pinned)
        # product = 1.0 * 2.2 * 1.2 * 0.35 * 1.3 * 0.67 ≈ 0.80
        posterior = drive.evaluate(ctx)
        assert posterior > drive.threshold


class TestBuildNarrative:
    def test_narrative_mentions_narration(self):
        drive = EndogenousDrive()
        drive._last_emission_ts = time.time() - 200.0
        ctx = DriveContext(chronicle_event_count=5, stimmung_stance="ambient")
        narrative = drive.build_narrative(ctx)
        assert "narrat" in narrative.lower()

    def test_narrative_mentions_events_when_present(self):
        drive = EndogenousDrive()
        drive._last_emission_ts = time.time() - 200.0
        ctx = DriveContext(chronicle_event_count=12)
        narrative = drive.build_narrative(ctx)
        assert "12" in narrative

    def test_narrative_mentions_role(self):
        drive = EndogenousDrive()
        ctx = DriveContext(programme_role="listening")
        narrative = drive.build_narrative(ctx)
        assert "listening" in narrative
