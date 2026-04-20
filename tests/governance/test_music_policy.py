"""Tests for shared.governance.music_policy — Path A + Path B decisions."""

from __future__ import annotations

from dataclasses import dataclass

from shared.governance.music_policy import (
    PATH_B_DEFAULT_WINDOW_S,
    MusicDetectionResult,
    MusicPath,
    MusicPolicy,
    NullMusicDetector,
    default_policy,
)


@dataclass
class _FakeDetector:
    """Test fixture — returns a scripted result per call."""

    result: MusicDetectionResult

    def detect(self, audio_window: object) -> MusicDetectionResult:
        return self.result


class TestNullMusicDetector:
    def test_always_returns_no_detection(self) -> None:
        det = NullMusicDetector()
        result = det.detect(None)
        assert result.detected is False
        assert result.confidence == 0.0
        assert result.source == "null"


class TestDefaultPolicy:
    def test_is_path_a(self) -> None:
        policy = default_policy()
        assert policy.path == MusicPath.PATH_A

    def test_default_detector_is_null(self) -> None:
        """Until Phase 3 Ring 2 ships, default is non-detecting."""
        policy = default_policy()
        decision = policy.evaluate(audio_window=None)
        assert decision.should_mute is False
        assert "no music" in decision.reason


class TestPathA:
    def test_detection_triggers_mute_plus_transcript(self) -> None:
        detector = _FakeDetector(
            MusicDetectionResult(detected=True, confidence=0.8, source="vinyl")
        )
        policy = MusicPolicy(path=MusicPath.PATH_A, detector=detector)
        decision = policy.evaluate(audio_window=None)
        assert decision.should_mute is True
        assert decision.surface_transcript is True
        assert decision.path == MusicPath.PATH_A
        assert "Path A" in decision.reason
        assert decision.detection.source == "vinyl"

    def test_no_detection_passes_through(self) -> None:
        detector = _FakeDetector(MusicDetectionResult(detected=False))
        policy = MusicPolicy(path=MusicPath.PATH_A, detector=detector)
        decision = policy.evaluate(audio_window=None)
        assert decision.should_mute is False
        assert decision.surface_transcript is False


class TestPathB:
    def test_window_opens_on_first_detection(self) -> None:
        """First tick with music opens the window — no mute yet."""
        detector = _FakeDetector(MusicDetectionResult(detected=True, confidence=0.9))
        policy = MusicPolicy(path=MusicPath.PATH_B, detector=detector, window_s=30.0)
        decision = policy.evaluate(audio_window=None, now=1000.0)
        assert decision.should_mute is False
        assert "window opened" in decision.reason

    def test_within_window_no_mute(self) -> None:
        detector = _FakeDetector(MusicDetectionResult(detected=True, confidence=0.9))
        policy = MusicPolicy(path=MusicPath.PATH_B, detector=detector, window_s=30.0)
        policy.evaluate(audio_window=None, now=1000.0)  # opens window
        decision = policy.evaluate(audio_window=None, now=1015.0)  # 15 s in
        assert decision.should_mute is False
        assert "window open" in decision.reason
        assert "15.0/30.0" in decision.reason

    def test_window_expires_triggers_mute(self) -> None:
        detector = _FakeDetector(MusicDetectionResult(detected=True, confidence=0.9))
        policy = MusicPolicy(path=MusicPath.PATH_B, detector=detector, window_s=30.0)
        policy.evaluate(audio_window=None, now=1000.0)  # opens
        decision = policy.evaluate(audio_window=None, now=1031.0)  # expired
        assert decision.should_mute is True
        assert decision.surface_transcript is True
        assert "expired" in decision.reason

    def test_reset_window_reopens(self) -> None:
        detector = _FakeDetector(MusicDetectionResult(detected=True, confidence=0.9))
        policy = MusicPolicy(path=MusicPath.PATH_B, detector=detector, window_s=30.0)
        policy.evaluate(audio_window=None, now=1000.0)
        policy.evaluate(audio_window=None, now=1040.0)  # muted
        policy.reset_window()
        # Next detection reopens.
        decision = policy.evaluate(audio_window=None, now=1050.0)
        assert decision.should_mute is False
        assert "window opened" in decision.reason

    def test_music_stops_closes_window(self) -> None:
        """Window closes automatically when music stops being detected."""
        detector = _FakeDetector(MusicDetectionResult(detected=True))
        policy = MusicPolicy(path=MusicPath.PATH_B, detector=detector, window_s=30.0)
        policy.evaluate(audio_window=None, now=1000.0)  # opens
        # Simulate music stopping.
        policy.detector = _FakeDetector(MusicDetectionResult(detected=False))
        policy.evaluate(audio_window=None, now=1010.0)
        # Re-simulate music — should re-open, not resume expired state.
        policy.detector = _FakeDetector(MusicDetectionResult(detected=True))
        decision = policy.evaluate(audio_window=None, now=1020.0)
        assert decision.should_mute is False
        assert "window opened" in decision.reason


class TestPathBDefaults:
    def test_window_default(self) -> None:
        assert PATH_B_DEFAULT_WINDOW_S == 30.0

    def test_policy_defaults_to_30s(self) -> None:
        policy = MusicPolicy(path=MusicPath.PATH_B, detector=NullMusicDetector())
        assert policy.window_s == 30.0


class TestDetectionPropagates:
    """Full MusicDetectionResult should pass through to consumers."""

    def test_title_guess_preserved(self) -> None:
        detector = _FakeDetector(
            MusicDetectionResult(
                detected=True,
                confidence=0.95,
                title_guess="Artist - Track",
                source="youtube",
            )
        )
        policy = MusicPolicy(path=MusicPath.PATH_A, detector=detector)
        decision = policy.evaluate(audio_window=None)
        assert decision.detection.title_guess == "Artist - Track"
        assert decision.detection.source == "youtube"
