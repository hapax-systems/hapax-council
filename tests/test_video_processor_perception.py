"""Tests for perception-informed video segment classification."""

from __future__ import annotations

import json
from pathlib import Path

from agents.video_processor import (
    _aggregate_perception_minutes,
    _classify_from_perception,
    _parse_segment_timestamp,
)


class TestParseSegmentTimestamp:
    def test_standard_format(self):
        ts = _parse_segment_timestamp("brio-operator_20260324-154619_0233.mkv")
        assert ts is not None
        assert isinstance(ts, float)
        assert ts > 0

    def test_invalid_format(self):
        assert _parse_segment_timestamp("bad-filename.mkv") is None

    def test_missing_timestamp(self):
        assert _parse_segment_timestamp("noparts.mkv") is None


def _minute(
    *,
    activity: str = "coding",
    flow_mean: float = 0.5,
    operator_present: bool = True,
    person_count_max: int = 1,
    consent_phase: str = "no_guest",
    voice_active: bool = False,
    audio_mean: float = 0.01,
    stress_elevated: bool = False,
    hr_mean: float = 70.0,
) -> dict:
    return {
        "timestamp": 1711303560.0,
        "activity": activity,
        "flow_mean": flow_mean,
        "operator_present": operator_present,
        "person_count_max": person_count_max,
        "consent_phase": consent_phase,
        "voice_active": voice_active,
        "audio_mean": audio_mean,
        "stress_elevated": stress_elevated,
        "hr_mean": hr_mean,
    }


class TestAggregatePerceptionMinutes:
    def test_single_minute(self):
        agg = _aggregate_perception_minutes([_minute()])
        assert agg["operator_present"] is True
        assert agg["person_count_max"] == 1
        assert agg["activity_mode"] == "coding"

    def test_mixed_presence(self):
        minutes = [
            _minute(operator_present=True),
            _minute(operator_present=False),
            _minute(operator_present=True),
        ]
        agg = _aggregate_perception_minutes(minutes)
        assert agg["operator_present"] is True
        assert abs(agg["operator_present_ratio"] - 2 / 3) < 0.01

    def test_activity_changed(self):
        minutes = [
            _minute(activity="coding"),
            _minute(activity="producing"),
        ]
        agg = _aggregate_perception_minutes(minutes)
        assert agg["activity_changed"] is True

    def test_no_activity_change(self):
        minutes = [_minute(activity="coding")] * 3
        agg = _aggregate_perception_minutes(minutes)
        assert agg["activity_changed"] is False


class TestClassifyFromPerception:
    def test_production_session(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(activity="producing", flow_mean=0.7, operator_present=True),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.category == "production_session"
        assert result.value_score == 1.0

    def test_conversation_requires_consent(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(person_count_max=3, consent_phase="consent_granted"),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.category == "conversation"
        assert result.value_score == 0.8

    def test_multiple_people_without_consent_not_conversation(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(person_count_max=3, consent_phase="no_guest"),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        # Should NOT be conversation without consent
        assert result.category != "conversation"

    def test_active_work(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(activity="coding", flow_mean=0.5, operator_present=True),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.category == "active_work"
        assert result.value_score == 0.6

    def test_idle_occupied(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(activity="idle", flow_mean=0.1, operator_present=True),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.category == "idle_occupied"
        assert result.value_score == 0.3

    def test_empty_room(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(operator_present=False, activity=""),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.category == "empty_room"
        assert result.value_score == 0.0

    def test_voice_active_bonus(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(activity="coding", flow_mean=0.5, voice_active=True),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.value_score == 0.7  # 0.6 base + 0.1 voice bonus

    def test_activity_transition_bonus(self):
        minutes = [
            _minute(activity="coding", flow_mean=0.5),
            _minute(activity="coding", flow_mean=0.5),
            _minute(activity="producing", flow_mean=0.5),
            _minute(activity="coding", flow_mean=0.5),
            _minute(activity="coding", flow_mean=0.5),
        ]
        agg = _aggregate_perception_minutes(minutes)
        result = _classify_from_perception(agg)
        assert result.value_score == 0.7  # 0.6 base + 0.1 transition bonus

    def test_production_session_beats_conversation(self):
        """Production with a consented guest should be production_session, not conversation."""
        agg = _aggregate_perception_minutes(
            [
                _minute(
                    activity="producing",
                    flow_mean=0.7,
                    operator_present=True,
                    person_count_max=2,
                    consent_phase="consent_granted",
                ),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.category == "production_session"
        assert result.value_score == 1.0

    def test_ssim_clamped_to_valid_range(self):
        """ssim must stay in [0.0, 1.0] even with high audio energy."""
        agg = _aggregate_perception_minutes(
            [_minute(audio_mean=1.5, activity="producing", flow_mean=0.7)] * 5
        )
        result = _classify_from_perception(agg)
        assert 0.0 <= result.ssim <= 1.0
        assert 0.0 <= result.motion_score <= 1.0


class TestAggregateEmpty:
    def test_empty_list_no_division_error(self):
        agg = _aggregate_perception_minutes([])
        assert agg["operator_present"] is False
        assert agg["flow_score_mean"] == 0.0
        assert agg["activity_mode"] == ""


class TestGuestPresenceNeverPersistsOnConsentFailure:
    """Guest-derived segment metadata persists only on an affirmative guest
    video consent. A failed, missing, unreadable or malformed consent check
    withholds it — and withheld is recorded as withheld, never as an
    observed claim that only the operator was present.

    Guest-derived persisted fields (determined from _process_segment and
    _write_sidecar): ``people_count`` and ``max_people`` in the sidecar;
    ``category`` when it is "conversation" (only reachable with >1 person)
    in the sidecar, the state record, the change log and the notification;
    ``people_count`` in the state record, the change log and the log line;
    ``value_score`` everywhere it persists, because the multi-person score
    (0.8, or 0.9 with the scene-change bonus) itself infers a second person.
    """

    SEGMENT = "brio-operator_20260324-154619_0233.mkv"
    SYNTHETIC_SUBJECT = "synthetic-subject-b"

    def _classification(self, *, people_count: int, max_people: int, category: str):
        from agents.video_processor import SegmentClassification

        return SegmentClassification(
            category=category,
            value_score=0.8 if category == "conversation" else 0.3,
            people_count=people_count,
            max_people=max_people,
            motion_score=0.01,
        )

    def _patch_registry(self, monkeypatch, *, load_exc=None, check=None, fail_closed=False):
        import shared.governance.consent as consent_mod

        calls = {"load": 0, "check": 0}

        class _Registry:
            def __init__(self, *_a, **_k):
                pass

            def load(self, *_a, **_k):
                calls["load"] += 1
                if load_exc is not None:
                    raise load_exc
                return 0 if fail_closed else 1

            @property
            def fail_closed(self):
                return fail_closed

            def contract_check(self, person_id, data_category):
                calls["check"] += 1
                if isinstance(check, BaseException):
                    raise check
                return check if check is not None else (not fail_closed and False)

        monkeypatch.setattr(consent_mod, "ConsentRegistry", _Registry)
        return calls

    def _run(self, tmp_path, monkeypatch, classification):
        import agents.refusal_brief as refusal_pkg
        import agents.video_processor as vp

        role_dir = tmp_path / "brio-operator"
        role_dir.mkdir()
        segment = role_dir / self.SEGMENT
        segment.write_bytes(b"")
        changes: list = []
        refusals: list = []
        monkeypatch.setattr(vp, "_classify_segment_dispatch", lambda _p: classification)
        monkeypatch.setattr(vp, "_upload_to_gdrive", lambda *_a, **_k: True)
        monkeypatch.setattr(vp, "_log_change", lambda *a, **_k: changes.append(a))
        monkeypatch.setattr(refusal_pkg, "append", lambda ev, **_: refusals.append(ev) or True)
        info = vp._process_segment(segment, vp.VideoProcessorState())
        sidecars = list(role_dir.glob(self.SEGMENT + ".*"))
        assert len(sidecars) == 1
        sidecar = json.loads(sidecars[0].read_text())
        return info, sidecar, changes, refusals

    def _assert_withheld(self, info, sidecar, changes):
        assert "max_people" not in sidecar
        assert "people_count" not in sidecar
        assert sidecar["category"] != "conversation"
        assert sidecar.get("guest_presence") == "withheld"
        assert sidecar.get("guest_presence_cause")
        assert info.people_count is None
        assert info.category != "conversation"
        assert info.guest_presence == "withheld"
        extra = changes[-1][2]
        assert "people_count" not in extra
        assert extra["category"] != "conversation"
        assert extra["guest_presence"] == "withheld"
        assert "value_score" not in sidecar
        assert info.value_score is None
        assert "value_score" not in extra

    def test_registry_load_failure_withholds(self, tmp_path, monkeypatch):
        self._patch_registry(monkeypatch, load_exc=RuntimeError("contracts unreadable"))
        cls = self._classification(people_count=2, max_people=2, category="conversation")
        info, sidecar, changes, _ = self._run(tmp_path, monkeypatch, cls)
        self._assert_withheld(info, sidecar, changes)

    def test_failed_current_check_withholds(self, tmp_path, monkeypatch):
        # The custody-failure shape: the check itself raises.
        self._patch_registry(monkeypatch, check=RuntimeError("custody unavailable"))
        cls = self._classification(people_count=2, max_people=2, category="conversation")
        info, sidecar, changes, _ = self._run(tmp_path, monkeypatch, cls)
        self._assert_withheld(info, sidecar, changes)

    def test_fail_closed_registry_withholds(self, tmp_path, monkeypatch):
        self._patch_registry(monkeypatch, fail_closed=True)
        cls = self._classification(people_count=2, max_people=2, category="conversation")
        info, sidecar, changes, _ = self._run(tmp_path, monkeypatch, cls)
        self._assert_withheld(info, sidecar, changes)
        assert sidecar["guest_presence_cause"] == "consent_registry_unavailable"

    def test_no_guest_contract_withholds_and_is_not_an_operator_only_claim(
        self, tmp_path, monkeypatch
    ):
        self._patch_registry(monkeypatch, check=False)
        cls = self._classification(people_count=2, max_people=2, category="conversation")
        info, sidecar, changes, _ = self._run(tmp_path, monkeypatch, cls)
        self._assert_withheld(info, sidecar, changes)
        assert sidecar["guest_presence_cause"] == "no_guest_video_consent"

    def test_average_one_max_two_edge_is_gated(self, tmp_path, monkeypatch):
        # Haar path: frames [1, 2, 1] round to an average of 1 while max is 2.
        calls = self._patch_registry(monkeypatch, check=False)
        cls = self._classification(people_count=1, max_people=2, category="conversation")
        info, sidecar, changes, _ = self._run(tmp_path, monkeypatch, cls)
        assert calls["check"] == 1
        self._assert_withheld(info, sidecar, changes)

    def test_non_boolean_answer_withholds(self, tmp_path, monkeypatch):
        self._patch_registry(monkeypatch, check="yes")
        cls = self._classification(people_count=2, max_people=2, category="conversation")
        info, sidecar, changes, _ = self._run(tmp_path, monkeypatch, cls)
        self._assert_withheld(info, sidecar, changes)

    def test_withholding_is_audited_sanitized_with_remedy(self, tmp_path, monkeypatch):
        self._patch_registry(monkeypatch, check=RuntimeError(f"custody {self.SYNTHETIC_SUBJECT}"))
        cls = self._classification(people_count=2, max_people=2, category="conversation")
        _, sidecar, _, refusals = self._run(tmp_path, monkeypatch, cls)
        assert len(refusals) == 1
        reason = refusals[0].reason
        assert refusals[0].axiom == "interpersonal_transparency"
        assert "RuntimeError" in reason
        assert "remedy" in reason
        assert self.SYNTHETIC_SUBJECT not in reason
        assert self.SYNTHETIC_SUBJECT not in json.dumps(sidecar)

    def test_positive_control_guest_consent_persists_counts(self, tmp_path, monkeypatch):
        self._patch_registry(monkeypatch, check=True)
        cls = self._classification(people_count=2, max_people=2, category="conversation")
        info, sidecar, changes, refusals = self._run(tmp_path, monkeypatch, cls)
        assert sidecar["people_count"] == 2
        assert sidecar["max_people"] == 2
        assert sidecar["category"] == "conversation"
        assert "guest_presence" not in sidecar
        assert info.people_count == 2
        assert changes[-1][2]["people_count"] == 2
        assert sidecar["value_score"] == 0.8
        assert info.value_score == 0.8
        assert changes[-1][2]["value_score"] == 0.8
        assert refusals == []

    def test_single_person_is_observed_without_consulting_consent(self, tmp_path, monkeypatch):
        calls = self._patch_registry(monkeypatch, load_exc=RuntimeError("must not be read"))
        cls = self._classification(people_count=1, max_people=1, category="idle_occupied")
        info, sidecar, changes, refusals = self._run(tmp_path, monkeypatch, cls)
        assert calls["load"] == 0
        assert sidecar["people_count"] == 1
        assert sidecar["max_people"] == 1
        assert "guest_presence" not in sidecar
        assert info.people_count == 1
        assert refusals == []

    def test_withheld_log_lines_carry_no_count_score_or_category(
        self, tmp_path, monkeypatch, caplog
    ):
        import logging

        self._patch_registry(monkeypatch, check=False)
        cls = self._classification(people_count=2, max_people=2, category="conversation")
        with caplog.at_level(logging.DEBUG, logger="agents.video_processor"):
            self._run(tmp_path, monkeypatch, cls)
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "Classified" in text
        assert "conversation" not in text
        assert "people=2" not in text
        assert "0.80" not in text

    def test_perception_classified_log_line_carries_no_guest_derived_fields(
        self, monkeypatch, caplog
    ):
        # This line is written before any consent decision exists, so it
        # must not carry the guest-derived count, score or category.
        import logging

        import agents.video_processor as vp

        minutes = [
            {"operator_present": True, "person_count_max": 2, "consent_phase": "consent_granted"}
        ]
        monkeypatch.setattr(vp, "_read_perception_minutes", lambda *_a: minutes)
        with caplog.at_level(logging.DEBUG, logger="agents.video_processor"):
            cls = vp._classify_segment_dispatch(Path(self.SEGMENT))
        assert cls.category == "conversation"
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "Perception-classified" in text
        assert "conversation" not in text
        assert "people=2" not in text
        assert "score=" not in text

    def test_run_notification_withholds_guest_category(self, tmp_path, monkeypatch):
        import agents._notify as notify_mod
        import agents.refusal_brief as refusal_pkg
        import agents.video_processor as vp

        self._patch_registry(monkeypatch, check=False)
        role_dir = tmp_path / "brio-operator"
        role_dir.mkdir()
        segment = role_dir / self.SEGMENT
        segment.write_bytes(b"")
        cls = self._classification(people_count=2, max_people=2, category="conversation")
        sent: list = []
        monkeypatch.setattr(vp, "_find_unprocessed_segments", lambda _s: [segment])
        monkeypatch.setattr(vp, "_classify_segment_dispatch", lambda _p: cls)
        monkeypatch.setattr(vp, "_upload_to_gdrive", lambda *_a, **_k: True)
        monkeypatch.setattr(vp, "_log_change", lambda *_a, **_k: None)
        monkeypatch.setattr(vp, "_save_state", lambda _s: None)
        monkeypatch.setattr(refusal_pkg, "append", lambda ev, **_: True)
        monkeypatch.setattr(notify_mod, "send_notification", lambda *a, **_k: sent.append(a))
        vp._process_new_segments(vp.VideoProcessorState())
        assert len(sent) == 1
        message = sent[0][1]
        assert "conversation" not in message
        assert "withheld: 1" in message
