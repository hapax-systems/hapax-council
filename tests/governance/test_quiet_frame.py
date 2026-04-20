"""Tests for shared.governance.quiet_frame — demonet Phase 11."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.governance.monetization_safety import GATE
from shared.governance.quiet_frame import (
    QUIET_FRAME_DEFAULT_DURATION_S,
    QUIET_FRAME_PROGRAMME_ID,
    QUIET_FRAME_TIER_BAND,
    activate_quiet_frame,
    build_quiet_frame_programme,
    deactivate_quiet_frame,
)
from shared.programme import Programme, ProgrammeRole, ProgrammeStatus
from shared.programme_store import ProgrammePlanStore


@pytest.fixture
def store(tmp_path: Path) -> ProgrammePlanStore:
    return ProgrammePlanStore(path=tmp_path / "programmes.jsonl")


class _Candidate:
    def __init__(self, name: str, risk: str, reason: str = "") -> None:
        self.capability_name = name
        self.payload = {"monetization_risk": risk}
        if reason:
            self.payload["risk_reason"] = reason


class TestBuildQuietFrameProgramme:
    def test_shape(self) -> None:
        p = build_quiet_frame_programme()
        assert p.programme_id == QUIET_FRAME_PROGRAMME_ID
        assert p.role == ProgrammeRole.AMBIENT
        assert p.status == ProgrammeStatus.PENDING
        assert p.planned_duration_s == QUIET_FRAME_DEFAULT_DURATION_S
        assert p.constraints.monetization_opt_ins == set()
        assert p.constraints.voice_tier_band_prior == QUIET_FRAME_TIER_BAND

    def test_custom_duration(self) -> None:
        p = build_quiet_frame_programme(duration_s=3600.0)
        assert p.planned_duration_s == 3600.0

    def test_reason_in_notes(self) -> None:
        p = build_quiet_frame_programme(reason="Content ID hit cooldown")
        assert "Content ID hit cooldown" in p.notes


class TestActivate:
    def test_adds_and_activates(self, store: ProgrammePlanStore) -> None:
        result = activate_quiet_frame(store, now=1000.0)
        assert result.status == ProgrammeStatus.ACTIVE
        assert result.actual_started_at == 1000.0
        # Persisted.
        assert store.get(QUIET_FRAME_PROGRAMME_ID).status == ProgrammeStatus.ACTIVE

    def test_deactivates_prior_active(self, store: ProgrammePlanStore) -> None:
        """Activating quiet frame terminates any prior ACTIVE programme."""
        prior = Programme(
            programme_id="some-showcase",
            role=ProgrammeRole.SHOWCASE,
            status=ProgrammeStatus.ACTIVE,
            planned_duration_s=60.0,
            parent_show_id="test",
            actual_started_at=500.0,
        )
        store.add(prior)
        activate_quiet_frame(store, now=1000.0)
        # Prior became COMPLETED.
        assert store.get("some-showcase").status == ProgrammeStatus.COMPLETED
        # Only the quiet frame is ACTIVE.
        assert store.active_programme().programme_id == QUIET_FRAME_PROGRAMME_ID

    def test_idempotent_reactivation(self, store: ProgrammePlanStore) -> None:
        """Calling activate twice is safe — second call refreshes started_at."""
        activate_quiet_frame(store, now=1000.0)
        activate_quiet_frame(store, duration_s=3600.0, now=2000.0)
        p = store.get(QUIET_FRAME_PROGRAMME_ID)
        assert p.actual_started_at == 2000.0
        assert p.planned_duration_s == 3600.0


class TestDeactivate:
    def test_completes_active_quiet_frame(self, store: ProgrammePlanStore) -> None:
        activate_quiet_frame(store, now=1000.0)
        result = deactivate_quiet_frame(store, now=1500.0)
        assert result is not None
        assert result.status == ProgrammeStatus.COMPLETED
        assert result.actual_ended_at == 1500.0

    def test_noop_when_absent(self, store: ProgrammePlanStore) -> None:
        """No quiet frame in store → None, no exception."""
        assert deactivate_quiet_frame(store) is None

    def test_noop_when_already_completed(self, store: ProgrammePlanStore) -> None:
        activate_quiet_frame(store, now=1000.0)
        deactivate_quiet_frame(store, now=1500.0)
        # Second deactivate is a no-op.
        assert deactivate_quiet_frame(store, now=2000.0) is None


class TestGateIntegration:
    def test_medium_risk_blocked_under_quiet_frame(self, store: ProgrammePlanStore) -> None:
        """With quiet frame active, no medium-risk capability admits."""
        result = activate_quiet_frame(store, now=1000.0)
        cand = _Candidate("knowledge.web_search", "medium")
        assessment = GATE.assess(cand, result)
        assert assessment.allowed is False
        assert "opt-in" in assessment.reason

    def test_low_risk_passes_under_quiet_frame(self, store: ProgrammePlanStore) -> None:
        """Low-risk capabilities pass even under quiet frame."""
        result = activate_quiet_frame(store, now=1000.0)
        cand = _Candidate("knowledge.wikipedia", "low")
        assessment = GATE.assess(cand, result)
        assert assessment.allowed is True

    def test_none_risk_passes_under_quiet_frame(self, store: ProgrammePlanStore) -> None:
        result = activate_quiet_frame(store, now=1000.0)
        cand = _Candidate("env.weather", "none")
        assessment = GATE.assess(cand, result)
        assert assessment.allowed is True


class TestTierBand:
    def test_band_excludes_granular_tiers(self) -> None:
        """Band (0, 2) — UNADORNED..BROADCAST_GHOST — keeps engine idle."""
        low, high = QUIET_FRAME_TIER_BAND
        # VoiceTier.GRANULAR_WASH = 5, OBLITERATED = 6 both excluded.
        assert low == 0
        assert high == 2
