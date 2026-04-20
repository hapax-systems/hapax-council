"""Tests for D-18: CPAL music_policy proof-of-wiring.

Per delta-to-alpha-d17-d18-wiring relay drop, the CPAL wire is
"proof-of-wiring" only — actual production-mute behavior is deferred
to D-18b once a real (non-Null) music detector ships. These tests
verify the wire (per-tick evaluate() call + transition logging) without
asserting any behavior change against the default NullMusicDetector.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.hapax_daimonion.cpal.runner import CpalRunner
from shared.governance.music_policy import (
    MusicDetectionResult as _Result,
)
from shared.governance.music_policy import (
    MusicPath,
    MusicPolicy,
    MusicPolicyDecision,
    NullMusicDetector,
)


def _make_runner(music_policy=None):
    buffer = MagicMock()
    buffer.speech_active = False
    buffer.speech_duration_s = 0.0
    buffer.is_speaking = False
    buffer.get_utterance.return_value = None
    buffer.speech_frames_snapshot = []
    stt = MagicMock()
    router = MagicMock()
    return CpalRunner(buffer=buffer, stt=stt, salience_router=router, music_policy=music_policy)


class TestMusicPolicyWired:
    def test_default_runner_has_music_policy_with_null_detector(self) -> None:
        runner = _make_runner()
        assert runner._music_policy is not None
        assert isinstance(runner._music_policy.detector, NullMusicDetector)

    def test_explicit_music_policy_passed_through(self) -> None:
        custom_policy = MusicPolicy(path=MusicPath.PATH_A, detector=NullMusicDetector())
        runner = _make_runner(music_policy=custom_policy)
        assert runner._music_policy is custom_policy

    def test_evaluate_called_per_tick(self) -> None:
        # MagicMock(wraps=) on a MusicPolicy dataclass loses dataclass-method
        # binding in some contexts; use a plain MagicMock spy that returns a
        # deterministic decision and just counts calls.
        spy = MagicMock()
        spy.evaluate.return_value = MusicPolicyDecision(
            should_mute=False,
            surface_transcript=False,
            reason="no music",
            path=MusicPath.PATH_A,
            detection=_Result(detected=False),
        )
        runner = _make_runner(music_policy=spy)
        runner._evaluate_music_policy(b"\x00" * 1024)
        spy.evaluate.assert_called_once()

    def test_no_log_when_decision_does_not_change(self, caplog) -> None:
        spy = MagicMock()
        spy.evaluate.return_value = MusicPolicyDecision(
            should_mute=False,
            surface_transcript=False,
            reason="no music",
            path=MusicPath.PATH_A,
            detection=_Result(detected=False),
        )
        runner = _make_runner(music_policy=spy)
        with caplog.at_level("INFO"):
            runner._evaluate_music_policy(b"")
            runner._evaluate_music_policy(b"")
            runner._evaluate_music_policy(b"")
        # No transitions → no MUTE/ALLOWED log lines.
        assert not any("music policy" in r.message for r in caplog.records)

    def test_transition_to_mute_logged(self, caplog) -> None:
        spy = MagicMock()
        spy.evaluate.return_value = MusicPolicyDecision(
            should_mute=True,
            surface_transcript=True,
            reason="music detected (conf=0.95): Path A mute+transcript",
            path=MusicPath.PATH_A,
            detection=_Result(detected=True, confidence=0.95),
        )
        runner = _make_runner(music_policy=spy)
        with caplog.at_level("INFO"):
            runner._evaluate_music_policy(b"")
        assert runner._music_mute_active is True
        assert any(
            "music policy → MUTE" in r.message and "music detected" in r.message
            for r in caplog.records
        )

    def test_transition_to_mute_logged_only_once(self, caplog) -> None:
        spy = MagicMock()
        spy.evaluate.return_value = MusicPolicyDecision(
            should_mute=True,
            surface_transcript=True,
            reason="ongoing music",
            path=MusicPath.PATH_A,
            detection=_Result(detected=True, confidence=0.9),
        )
        runner = _make_runner(music_policy=spy)
        with caplog.at_level("INFO"):
            runner._evaluate_music_policy(b"")
            runner._evaluate_music_policy(b"")
            runner._evaluate_music_policy(b"")
        mute_logs = [r for r in caplog.records if "music policy → MUTE" in r.message]
        assert len(mute_logs) == 1

    def test_transition_back_to_allowed_logged(self, caplog) -> None:
        spy = MagicMock()
        # Sequence: mute → mute → allowed
        spy.evaluate.side_effect = [
            MusicPolicyDecision(
                should_mute=True,
                surface_transcript=True,
                reason="music detected",
                path=MusicPath.PATH_A,
                detection=_Result(detected=True, confidence=0.9),
            ),
            MusicPolicyDecision(
                should_mute=True,
                surface_transcript=True,
                reason="ongoing music",
                path=MusicPath.PATH_A,
                detection=_Result(detected=True, confidence=0.9),
            ),
            MusicPolicyDecision(
                should_mute=False,
                surface_transcript=False,
                reason="music ended",
                path=MusicPath.PATH_A,
                detection=_Result(detected=False),
            ),
        ]
        runner = _make_runner(music_policy=spy)
        with caplog.at_level("INFO"):
            runner._evaluate_music_policy(b"")
            runner._evaluate_music_policy(b"")
            runner._evaluate_music_policy(b"")
        assert runner._music_mute_active is False
        allowed_logs = [r for r in caplog.records if "music policy → ALLOWED" in r.message]
        assert len(allowed_logs) == 1

    def test_evaluate_failure_does_not_crash_tick(self, caplog) -> None:
        spy = MagicMock()
        spy.evaluate.side_effect = RuntimeError("simulated detector failure")
        runner = _make_runner(music_policy=spy)
        with caplog.at_level("WARNING"):
            # Must not raise.
            runner._evaluate_music_policy(b"")
        assert any("music_policy.evaluate raised" in r.message for r in caplog.records)
        # State unchanged on failure (no transition logged).
        assert runner._music_mute_active is False

    def test_default_null_detector_never_triggers_mute(self) -> None:
        """Behavior invariant: with the default NullMusicDetector, the wire
        is exercised but no mute decision is ever made. This is the
        contract that lets D-18 ship without behavioral risk."""
        runner = _make_runner()  # default policy uses NullMusicDetector
        for _ in range(10):
            runner._evaluate_music_policy(b"\x00" * 1024)
        assert runner._music_mute_active is False
