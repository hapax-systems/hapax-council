"""Tests for agents.hapax_daimonion.vad_state_publisher (Phase 9 hook 4)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

# pipecat is stubbed by tests/hapax_daimonion/conftest.py for test isolation;
# we assert state transitions and side-effects via our own frame classes
# rather than relying on the stubbed type machinery.
from agents.hapax_daimonion.vad_state_publisher import VadStatePublisher
from agents.studio_compositor import vad_ducking


class _FakeStartFrame:
    """Stand-in for UserStartedSpeakingFrame (conftest stubs the real one)."""

    pass


class _FakeStopFrame:
    """Stand-in for UserStoppedSpeakingFrame."""

    pass


class _UnrelatedFrame:
    pass


@pytest.fixture
def voice_state_file(tmp_path, monkeypatch):
    target = tmp_path / "voice-state.json"
    monkeypatch.setattr(vad_ducking, "VOICE_STATE_FILE", target)
    return target


@pytest.fixture
def publisher(monkeypatch):
    # Patch the module's imported frame names so isinstance() checks route
    # against our _FakeStart / _FakeStop classes, not the stub MagicMock.
    from agents.hapax_daimonion import vad_state_publisher as vsp

    monkeypatch.setattr(vsp, "UserStartedSpeakingFrame", _FakeStartFrame)
    monkeypatch.setattr(vsp, "UserStoppedSpeakingFrame", _FakeStopFrame)

    p = VadStatePublisher()
    # push_frame on the base class can be stub-dependent — mock it so we can
    # assert downstream propagation independent of the stub shape.
    p.push_frame = AsyncMock()
    return p


class TestStateTransitions:
    @pytest.mark.asyncio
    async def test_user_started_speaking_publishes_true(self, publisher, voice_state_file):
        await publisher.process_frame(_FakeStartFrame(), "downstream")
        state = json.loads(voice_state_file.read_text())
        assert state["operator_speech_active"] is True
        publisher.push_frame.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_user_stopped_speaking_publishes_false(self, publisher, voice_state_file):
        await publisher.process_frame(_FakeStopFrame(), "downstream")
        state = json.loads(voice_state_file.read_text())
        assert state["operator_speech_active"] is False

    @pytest.mark.asyncio
    async def test_other_frames_do_not_publish(self, publisher, voice_state_file):
        await publisher.process_frame(_UnrelatedFrame(), "downstream")
        assert not voice_state_file.exists()
        publisher.push_frame.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_block_pipeline(self, publisher, voice_state_file):
        with patch(
            "agents.hapax_daimonion.vad_state_publisher.publish_vad_state",
            side_effect=OSError("disk full"),
        ):
            await publisher.process_frame(_FakeStartFrame(), "downstream")
        publisher.push_frame.assert_awaited_once()
