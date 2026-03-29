"""Tests for agents/hapax_daimonion/env_context.py — environment TOON serialization."""

from __future__ import annotations

from dataclasses import dataclass, field

from agents.hapax_daimonion.env_context import serialize_environment


@dataclass(frozen=True)
class _FakeEnv:
    timestamp: float = 0.0
    operator_present: bool = True
    face_count: int = 1
    activity_mode: str = "coding"
    active_window: object = None
    speech_detected: bool = False
    vad_confidence: float = 0.0
    presence_score: str = "likely_present"
    workspace_context: str = ""
    window_count: int = 0
    active_workspace_id: int = 0
    in_voice_session: bool = False
    interruptibility_score: float = 1.0
    consent_phase: str = "no_guest"
    directive: str = "process"


@dataclass
class _FakeAnalysis:
    app: str = "chrome"
    context: str = "github PR review"
    summary: str = "reviewing code"
    gear_state: list = field(default_factory=list)


@dataclass
class _FakeAmbient:
    interruptible: bool = True
    reason: str = ""
    top_labels: list = field(default_factory=lambda: [("music", 0.85)])


class TestSerializeEnvironment:
    def setup_method(self):
        # Reset change detection between tests
        import agents.hapax_daimonion.env_context as mod

        mod._last_hash = 0

    def test_basic_serialization(self):
        env = _FakeEnv()
        result = serialize_environment(env, None, None)
        assert "op: present" in result
        assert "faces: 1" in result
        assert "mode: coding" in result

    def test_with_workspace_analysis(self):
        env = _FakeEnv()
        analysis = _FakeAnalysis()
        result = serialize_environment(env, analysis, None)
        assert "app: chrome" in result
        assert "ctx: github PR review" in result

    def test_with_ambient_audio(self):
        env = _FakeEnv()
        ambient = _FakeAmbient()
        result = serialize_environment(env, None, ambient)
        assert "audio: music" in result

    def test_absent_operator(self):
        env = _FakeEnv(operator_present=False, face_count=0)
        result = serialize_environment(env, None, None)
        assert "op: absent" in result
        assert "faces: 0" in result

    def test_change_detection_returns_empty_on_repeat(self):
        env = _FakeEnv()
        result1 = serialize_environment(env, None, None)
        assert result1  # first call returns content
        result2 = serialize_environment(env, None, None)
        assert result2 == ""  # same state = empty

    def test_change_detection_returns_content_on_change(self):
        env1 = _FakeEnv(face_count=1)
        result1 = serialize_environment(env1, None, None)
        assert result1

        env2 = _FakeEnv(face_count=2)
        result2 = serialize_environment(env2, None, None)
        assert result2  # different state = new content

    def test_unknown_mode_excluded(self):
        env = _FakeEnv(activity_mode="unknown")
        result = serialize_environment(env, None, None)
        assert "mode" not in result

    def test_low_confidence_audio_excluded(self):
        env = _FakeEnv()
        ambient = _FakeAmbient()
        ambient.top_labels = [("speech", 0.05)]
        result = serialize_environment(env, None, ambient)
        assert "audio" not in result
