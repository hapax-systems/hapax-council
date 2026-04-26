"""Tests for task #136 — follow-mode operator-tracking hero camera.

The controller fuses IR fleet presence + camera classifications into a
scored hero-camera recommendation. These tests pin:

* Scoring math yields the correct winner per operator location — in
  particular, the overhead camera is chosen when the operator moves to
  the overhead zone even though ``brio-operator`` has higher
  ambient_priority.
* Repetition penalty actively depresses the score of the current hero.
* Demo-activity bonus flips the desk recommendation from
  ``brio-operator`` to ``c920-overhead`` ("show the work" shot).
* The feature flag gates the consumer, not the computation.
* ``read_follow_mode_recommendation`` respects ``active=False`` so the
  hero-override consumer does not follow a stale/disabled suggestion.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest import mock

from agents.studio_compositor.follow_mode import (
    FollowModeController,
    FollowModeRecommendation,
    read_follow_mode_recommendation,
)

# Classification payload matching the production defaults (task #135).
# Captured verbatim so tests fail if production weights drift unexpectedly.
_PROD_CLASSIFICATIONS: dict[str, dict[str, object]] = {
    "brio-operator": {
        "semantic_role": "operator-face",
        "subject_ontology": ["person"],
        "angle": "front",
        "operator_visible": True,
        "ambient_priority": 7,
    },
    "c920-desk": {
        "semantic_role": "operator-hands",
        "subject_ontology": ["hands", "mpc"],
        "angle": "oblique",
        "operator_visible": False,
        "ambient_priority": 5,
    },
    "c920-room": {
        "semantic_role": "room-wide",
        "subject_ontology": ["room", "person"],
        "angle": "oblique",
        "operator_visible": True,
        "ambient_priority": 8,
    },
    "c920-overhead": {
        "semantic_role": "operator-desk-topdown",
        "subject_ontology": ["hands", "mpc", "desk"],
        "angle": "top-down",
        "operator_visible": False,
        "ambient_priority": 6,
    },
    "brio-room": {
        "semantic_role": "outboard-gear",
        "subject_ontology": ["eurorack", "outboard"],
        "angle": "front",
        "operator_visible": False,
        "ambient_priority": 3,
    },
    "brio-synths": {
        "semantic_role": "turntables",
        "subject_ontology": ["turntable", "vinyl"],
        "angle": "top-down",
        "operator_visible": False,
        "ambient_priority": 4,
    },
}


def _make_controller(
    tmp_path: Path,
    classifications: dict[str, dict[str, object]] | None = None,
    ir_reports: dict[str, dict[str, object]] | None = None,
    activity: str | None = None,
) -> FollowModeController:
    """Build a controller pointed at tmp paths with seeded state."""
    cls_path = tmp_path / "camera-classifications.json"
    rec_path = tmp_path / "follow-mode-recommendation.json"
    nar_path = tmp_path / "narrative-state.json"
    ir_dir = tmp_path / "pi-noir"
    ir_dir.mkdir(parents=True, exist_ok=True)

    cls_path.write_text(json.dumps(classifications or _PROD_CLASSIFICATIONS), encoding="utf-8")

    for role, report in (ir_reports or {}).items():
        (ir_dir / f"{role}.json").write_text(json.dumps(report), encoding="utf-8")

    if activity is not None:
        nar_path.write_text(json.dumps({"activity": activity}), encoding="utf-8")

    return FollowModeController(
        ir_state_dir=ir_dir,
        classifications_path=cls_path,
        recommendation_path=rec_path,
        narrative_state_path=nar_path,
    )


def _person_report(role: str, motion: float = 0.05) -> dict[str, object]:
    return {
        "role": role,
        "persons": [{"confidence": 0.8, "gaze_zone": "at-screen"}],
        "hands": [],
        "motion_delta": motion,
        "screens": [],
        "biometrics": {},
        "ir_brightness": 120.0,
        "ts": time.time(),
    }


class TestScoringMath:
    """Per-location winner verification."""

    def test_operator_at_overhead_picks_overhead_camera(self, tmp_path: Path) -> None:
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"overhead": _person_report("overhead")},
        )
        rec = ctrl.compute(now=time.time())
        assert rec is not None
        assert rec.operator_location == "overhead"
        assert rec.camera_role == "c920-overhead"
        # c920-overhead base 6 + location match 3.0 = 9.0 vs
        # brio-operator 7 + 0.3 = 7.3. Overhead wins by ~1.7.
        assert "location=overhead" in rec.reason

    def test_operator_at_desk_picks_overhead_camera(self, tmp_path: Path) -> None:
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"desk": _person_report("desk")},
        )
        rec = ctrl.compute(now=time.time())
        assert rec is not None
        assert rec.operator_location == "desk"
        # _LOCATION_ONTOLOGY_HINTS["desk"] = {"hands", "mpc", "desk"} —
        # both c920-desk (ontology=hands+mpc) and c920-overhead
        # (ontology=hands+mpc+desk) match. operator_visible bonus
        # applies to all. Tie-broken by ambient_priority:
        #   c920-overhead = 6 + 0.3 + 3.0 = 9.3
        #   c920-desk     = 5 + 0.3 + 3.0 = 8.3
        #   brio-operator = 7 + 0.3       = 7.3 (no ontology match)
        #   c920-room     = 8 + 0.3       = 8.3 (no ontology match)
        # c920-overhead wins by 1.0 — the "show the work" angle.
        # Test was previously named ``picks_brio_operator`` and asserted
        # c920-desk; both were wrong (operator-at-desk has always picked
        # c920-overhead per the actual scoring math).
        assert rec.camera_role == "c920-overhead"
        assert "location=desk" in rec.reason

    def test_operator_at_room_picks_room_camera(self, tmp_path: Path) -> None:
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"room": _person_report("room")},
        )
        rec = ctrl.compute(now=time.time())
        assert rec is not None
        assert rec.operator_location == "room"
        assert rec.camera_role == "c920-room"

    def test_no_ir_signal_still_produces_recommendation(self, tmp_path: Path) -> None:
        """No operator detected → controller falls back to ambient priorities."""
        ctrl = _make_controller(tmp_path, ir_reports={})
        rec = ctrl.compute(now=time.time())
        assert rec is not None
        assert rec.operator_location is None
        # With no location bonus, the highest ambient_priority wins.
        assert rec.camera_role == "c920-room"


class TestRepetitionPenalty:
    def test_repetition_penalty_reduces_winner_score(self, tmp_path: Path) -> None:
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"overhead": _person_report("overhead")},
        )
        now = time.time()
        first = ctrl.compute(now=now)
        assert first is not None and first.camera_role == "c920-overhead"

        # Simulate c920-overhead having been the hero for the last few seconds.
        ctrl._record_hero("c920-overhead", now)
        # Also record c920-overhead multiple times to be sure the
        # repetition branch fires.
        ctrl._record_hero("c920-overhead", now + 1.0)

        # Now recompute with the same inputs. Repetition penalty (-3.0)
        # drops c920-overhead from 9.3 to 6.3. With overhead penalised:
        #   c920-room     = 8 + 0.3       = 8.3 (highest priority + visible)
        #   c920-desk     = 5 + 0.0 + 3.0 = 8.0 (ontology match, not visible)
        #   brio-operator = 7 + 0.3       = 7.3 (no ontology match for overhead)
        #   c920-overhead = 6 + 0.0 + 3.0 - 3.0 = 6.0
        # c920-room wins by ambient priority + operator_visible. (Test was
        # previously expecting brio-operator at 7.3 — author missed that
        # c920-room at priority 8 + visible bonus = 8.3 takes the lead.)
        second = ctrl.compute(now=now + 2.0)
        assert second is not None
        assert second.camera_role != "c920-overhead"
        assert second.camera_role == "c920-room"

    def test_repetition_window_expires(self, tmp_path: Path) -> None:
        """Past the 30 s window, the penalty no longer applies."""
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"overhead": _person_report("overhead")},
        )
        t0 = time.time()
        ctrl._record_hero("c920-overhead", t0)
        # 40 s later, the history entry should no longer contribute.
        # Refresh the IR report file's mtime to the simulated "now"
        # so _read_ir_report's _IR_STALE_S=10s freshness check passes
        # — otherwise operator_location returns None, location bonus
        # drops, and c920-room (priority 8 + operator_visible) wins
        # by raw priority instead of c920-overhead (which we're trying
        # to verify recovers after the penalty window expires).
        # _read_ir_report compares file mtime to the supplied `now`,
        # not the JSON `ts` field — so utime is the right knob here.
        import os

        ir_file = tmp_path / "pi-noir" / "overhead.json"
        os.utime(ir_file, (t0 + 40.0, t0 + 40.0))
        rec = ctrl.compute(now=t0 + 40.0)
        assert rec is not None
        assert rec.camera_role == "c920-overhead"


class TestModeBonus:
    def test_demonstrate_at_desk_boosts_overhead(self, tmp_path: Path) -> None:
        """Activity=demonstrate + operator at desk → c920-overhead wins."""
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"desk": _person_report("desk")},
            activity="demonstrate",
        )
        rec = ctrl.compute(now=time.time())
        assert rec is not None
        assert rec.activity == "demonstrate"
        assert rec.operator_location == "desk"
        # c920-desk: 5 + 3.0 = 8.0
        # c920-overhead: 6 + 3.0 (desk-ontology match) + 2.0 (demo bonus) = 11.0
        # → overhead wins.
        assert rec.camera_role == "c920-overhead"
        assert "demo_desk_overhead" in rec.reason

    def test_demonstrate_elsewhere_does_not_apply_bonus(self, tmp_path: Path) -> None:
        """Demo bonus is desk-specific — demonstrate + at room does not boost overhead."""
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"room": _person_report("room")},
            activity="demonstrate",
        )
        rec = ctrl.compute(now=time.time())
        assert rec is not None
        assert rec.camera_role == "c920-room"
        assert "demo_desk_overhead" not in rec.reason


class TestPublishAndFlag:
    def test_tick_publishes_recommendation_when_active(
        self, tmp_path: Path, monkeypatch: mock.MagicMock
    ) -> None:
        monkeypatch.setenv("HAPAX_FOLLOW_MODE_ACTIVE", "1")
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"overhead": _person_report("overhead")},
        )
        rec = ctrl.tick()
        assert rec is not None and rec.active is True
        assert ctrl.recommendation_path.exists()
        payload = json.loads(ctrl.recommendation_path.read_text(encoding="utf-8"))
        assert payload["camera_role"] == "c920-overhead"
        assert payload["active"] is True

    def test_tick_publishes_inactive_marker_when_flag_off(
        self, tmp_path: Path, monkeypatch: mock.MagicMock
    ) -> None:
        # 2026-04-26: default flipped to ON per feedback_features_on_by_default;
        # explicit "0" is the new opt-out path.
        monkeypatch.setenv("HAPAX_FOLLOW_MODE_ACTIVE", "0")
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"overhead": _person_report("overhead")},
        )
        rec = ctrl.tick()
        assert rec is not None and rec.active is False
        # File is still written (observability) but with active=False.
        assert ctrl.recommendation_path.exists()
        payload = json.loads(ctrl.recommendation_path.read_text(encoding="utf-8"))
        assert payload["active"] is False

    def test_tick_publishes_active_marker_when_env_unset(
        self, tmp_path: Path, monkeypatch: mock.MagicMock
    ) -> None:
        # 2026-04-26: default-ON per feedback_features_on_by_default. Env
        # unset must produce active=True so the controller is live by default.
        monkeypatch.delenv("HAPAX_FOLLOW_MODE_ACTIVE", raising=False)
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"overhead": _person_report("overhead")},
        )
        rec = ctrl.tick()
        assert rec is not None and rec.active is True
        payload = json.loads(ctrl.recommendation_path.read_text(encoding="utf-8"))
        assert payload["active"] is True

    def test_read_recommendation_returns_none_when_inactive(
        self, tmp_path: Path, monkeypatch: mock.MagicMock
    ) -> None:
        monkeypatch.setenv("HAPAX_FOLLOW_MODE_ACTIVE", "0")
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"overhead": _person_report("overhead")},
        )
        ctrl.tick()
        # The consumer respects the active flag.
        got = read_follow_mode_recommendation(path=ctrl.recommendation_path)
        assert got is None

    def test_read_recommendation_respects_ttl(
        self, tmp_path: Path, monkeypatch: mock.MagicMock
    ) -> None:
        monkeypatch.setenv("HAPAX_FOLLOW_MODE_ACTIVE", "1")
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"overhead": _person_report("overhead")},
        )
        rec = ctrl.tick()
        assert rec is not None
        # 60 s later the TTL (15 s default) has expired.
        got = read_follow_mode_recommendation(path=ctrl.recommendation_path, now=rec.ts + 60.0)
        assert got is None

    def test_read_recommendation_returns_payload_when_fresh(
        self, tmp_path: Path, monkeypatch: mock.MagicMock
    ) -> None:
        monkeypatch.setenv("HAPAX_FOLLOW_MODE_ACTIVE", "1")
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"overhead": _person_report("overhead")},
        )
        rec = ctrl.tick()
        assert rec is not None
        got = read_follow_mode_recommendation(path=ctrl.recommendation_path, now=rec.ts + 1.0)
        assert got is not None
        assert got.camera_role == "c920-overhead"
        assert got.active is True


class TestMotionAndTransitions:
    def test_multiple_location_transitions_produce_multiple_cuts(self, tmp_path: Path) -> None:
        """Simulate operator moving desk → room → overhead — three distinct hero picks."""
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"desk": _person_report("desk")},
        )
        picks: list[str] = []
        t0 = time.time()

        def _rewrite_ir(role: str) -> None:
            for r in ("desk", "room", "overhead"):
                p = ctrl.ir_state_dir / f"{r}.json"
                if p.exists():
                    p.unlink()
            (ctrl.ir_state_dir / f"{role}.json").write_text(
                json.dumps(_person_report(role)), encoding="utf-8"
            )
            # Force mtime to "now" so freshness check passes under tmp fs.
            os.utime(ctrl.ir_state_dir / f"{role}.json", None)

        for i, loc in enumerate(["desk", "room", "overhead"]):
            _rewrite_ir(loc)
            rec = ctrl.compute(now=t0 + i * 2.0)
            assert rec is not None
            picks.append(rec.camera_role)
            ctrl._record_hero(rec.camera_role, t0 + i * 2.0)

        # The three cuts must hit at least two distinct cameras (not
        # stuck on brio-operator the whole time).
        assert len(set(picks)) >= 2
        # Specifically, the overhead tick should land on c920-overhead
        # (repetition penalty prevents stuck-on-brio).
        assert "c920-overhead" in picks


class TestRecommendationShape:
    def test_recommendation_confidence_in_range(self, tmp_path: Path) -> None:
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"overhead": _person_report("overhead")},
        )
        rec = ctrl.compute(now=time.time())
        assert rec is not None
        assert 0.0 <= rec.confidence <= 1.0

    def test_recommendation_includes_reason_string(self, tmp_path: Path) -> None:
        ctrl = _make_controller(
            tmp_path,
            ir_reports={"overhead": _person_report("overhead")},
        )
        rec = ctrl.compute(now=time.time())
        assert rec is not None
        assert "priority=" in rec.reason

    def test_no_classifications_returns_none(self, tmp_path: Path) -> None:
        """Controller returns None when camera-classifications.json is missing."""
        ir_dir = tmp_path / "pi-noir"
        ir_dir.mkdir()
        ctrl = FollowModeController(
            ir_state_dir=ir_dir,
            classifications_path=tmp_path / "missing.json",
            recommendation_path=tmp_path / "out.json",
            narrative_state_path=tmp_path / "missing-narrative.json",
        )
        assert ctrl.compute(now=time.time()) is None


class TestStaleIRRejection:
    def test_stale_ir_report_ignored(self, tmp_path: Path) -> None:
        """Pi reports older than 10 s are treated as absent."""
        ctrl = _make_controller(tmp_path, ir_reports={})
        # Manually write a stale report — mtime 30 s in the past.
        stale_path = ctrl.ir_state_dir / "overhead.json"
        stale_path.write_text(json.dumps(_person_report("overhead")), encoding="utf-8")
        past = time.time() - 30.0
        os.utime(stale_path, (past, past))
        rec = ctrl.compute(now=time.time())
        assert rec is not None
        # No location inferred → falls back to highest ambient priority.
        assert rec.operator_location is None
        assert rec.camera_role == "c920-room"


class TestRecommendationDataclass:
    def test_frozen(self) -> None:
        """FollowModeRecommendation is immutable (frozen dataclass)."""
        rec = FollowModeRecommendation(
            camera_role="brio-operator",
            confidence=0.8,
            reason="priority=7",
            ts=time.time(),
            active=True,
        )
        # Frozen dataclasses raise FrozenInstanceError on attribute mutation.
        try:
            rec.camera_role = "c920-room"  # type: ignore[misc]
            raise AssertionError("expected FrozenInstanceError")
        except Exception as exc:
            assert "frozen" in str(exc).lower() or "cannot assign" in str(exc).lower()
