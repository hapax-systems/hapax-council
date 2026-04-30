"""Wake greeting playback must pass the private-or-drop voice gate."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agents.hapax_daimonion.cpal.destination_channel import DestinationChannel
from agents.hapax_daimonion.pipeline_start import _play_wake_greeting


class _ImmediateThread:
    def __init__(self, target, daemon=True):
        self._target = target
        self.daemon = daemon

    def start(self):
        self._target()


def _daemon_stub():
    pipeline = MagicMock()
    pipeline._session_id = "test-session"
    pipeline._audio_output = MagicMock()
    pipeline._echo_canceller = None
    daemon = SimpleNamespace(
        _conversation_pipeline=pipeline,
        _conversation_buffer=MagicMock(),
        _bridge_engine=MagicMock(),
    )
    daemon._bridge_engine.select.return_value = ("hello", b"\x00\x01")
    return daemon


def test_wake_greeting_records_decision_before_routed_write():
    daemon = _daemon_stub()
    decision = SimpleNamespace(
        allowed=True,
        destination=DestinationChannel.PRIVATE,
        reason_code="private_assistant_monitor_bound",
        safety_gate={"context_default": "private_or_drop"},
        target="hapax-private",
        media_role="Assistant",
    )

    with (
        patch(
            "agents.hapax_daimonion.cpal.destination_channel.resolve_playback_decision",
            return_value=decision,
        ),
        patch("agents.hapax_daimonion.voice_output_witness.record_destination_decision"),
        patch("threading.Thread", _ImmediateThread),
    ):
        _play_wake_greeting(daemon)

    daemon._conversation_pipeline._write_audio.assert_called_once_with(
        daemon._conversation_pipeline._audio_output,
        None,
        b"\x00\x01",
        "hapax-private",
        "Assistant",
    )


def test_wake_greeting_drops_when_default_route_blocked():
    daemon = _daemon_stub()
    blocked = SimpleNamespace(
        allowed=False,
        destination=DestinationChannel.PRIVATE,
        reason_code="private_monitor_status_missing",
        safety_gate={"context_default": "private_or_drop"},
        target=None,
        media_role=None,
    )

    with (
        patch(
            "agents.hapax_daimonion.cpal.destination_channel.resolve_playback_decision",
            return_value=blocked,
        ),
        patch("agents.hapax_daimonion.voice_output_witness.record_destination_decision"),
        patch("agents.hapax_daimonion.voice_output_witness.record_drop") as record_drop,
        patch("threading.Thread", _ImmediateThread),
    ):
        _play_wake_greeting(daemon)

    daemon._conversation_pipeline._write_audio.assert_not_called()
    assert record_drop.call_args.kwargs["source"] == "pipeline_start_wake_greeting"
