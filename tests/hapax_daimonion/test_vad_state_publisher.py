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


# ── audio-pathways Phase 3 (#134, B1) — voice_gate wire ───────────────


class TestVoiceGateWire:
    """Phantom-VAD remediation: when an embedding_match_provider is
    wired, the gate suppresses publishes for low-similarity triggers
    (YouTube crossfeed, ambient room voice).
    """

    def _make_publisher(self, monkeypatch, *, provider):
        from agents.hapax_daimonion import vad_state_publisher as vsp

        monkeypatch.setattr(vsp, "UserStartedSpeakingFrame", _FakeStartFrame)
        monkeypatch.setattr(vsp, "UserStoppedSpeakingFrame", _FakeStopFrame)
        p = vsp.VadStatePublisher(embedding_match_provider=provider)
        p.push_frame = AsyncMock()
        return p

    @pytest.mark.asyncio
    async def test_high_match_publishes_true(self, monkeypatch, voice_state_file):
        """Embedding match >= 0.75 → vad_and_embedding → publish."""
        p = self._make_publisher(monkeypatch, provider=lambda: 0.85)
        await p.process_frame(_FakeStartFrame(), "downstream")
        state = json.loads(voice_state_file.read_text())
        assert state["operator_speech_active"] is True

    @pytest.mark.asyncio
    async def test_phantom_match_suppresses_publish(self, monkeypatch, voice_state_file):
        """Embedding match < 0.4 → no_duck_phantom → suppress publish.

        This is the phantom-VAD fix: YouTube voice triggers VAD with a
        very low embedding match, so the gate prevents the duck from
        firing on its own crossfeed (which would create the duck
        feedback loop the operator flagged).
        """
        p = self._make_publisher(monkeypatch, provider=lambda: 0.1)
        await p.process_frame(_FakeStartFrame(), "downstream")
        # File must NOT be written — the gate suppressed the publish.
        assert not voice_state_file.exists()
        # Frame still propagates downstream so STT still receives it.
        p.push_frame.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fallback_match_still_publishes(self, monkeypatch, voice_state_file):
        """0.4 <= match < 0.75 → vad_only_fallback → still publish.

        Low confidence but the gate still ducks — the operator's voice
        with poor enrollment match shouldn't get blocked. Only outright
        phantom triggers (match < 0.4) suppress.
        """
        p = self._make_publisher(monkeypatch, provider=lambda: 0.5)
        await p.process_frame(_FakeStartFrame(), "downstream")
        state = json.loads(voice_state_file.read_text())
        assert state["operator_speech_active"] is True

    @pytest.mark.asyncio
    async def test_provider_failure_falls_open(self, monkeypatch, voice_state_file):
        """A provider that raises must NOT block the pipeline — fall open
        to publish=True so a sensor failure doesn't silently break ducking.
        """

        def _broken() -> float:
            raise RuntimeError("speaker model down")

        p = self._make_publisher(monkeypatch, provider=_broken)
        await p.process_frame(_FakeStartFrame(), "downstream")
        # Fall-open: publish still fires.
        state = json.loads(voice_state_file.read_text())
        assert state["operator_speech_active"] is True

    @pytest.mark.asyncio
    async def test_stop_publish_never_gated(self, monkeypatch, voice_state_file):
        """The duck-release path must never be gated — even with a
        provider that would suppress Started, Stopped always publishes
        False so a stuck duck cannot persist after the operator quiets.
        """
        # Force the gate into "suppress publish" mode for Started.
        p = self._make_publisher(monkeypatch, provider=lambda: 0.05)
        await p.process_frame(_FakeStopFrame(), "downstream")
        state = json.loads(voice_state_file.read_text())
        assert state["operator_speech_active"] is False
