"""Tests for hapax_daimonion TTS tier abstraction and Voxtral synthesis backend."""

from __future__ import annotations

import base64
import struct
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from agents.hapax_daimonion.tts import (
    TTSManager,
    _audio_to_pcm_int16,
    _decode_pcm_f32_b64,
    select_tier,
)

# ---------------------------------------------------------------------------
# select_tier
# ---------------------------------------------------------------------------


def test_select_tier_conversation_is_voxtral() -> None:
    assert select_tier("conversation") == "voxtral"


def test_select_tier_notification_is_voxtral() -> None:
    assert select_tier("notification") == "voxtral"


def test_select_tier_briefing_is_voxtral() -> None:
    assert select_tier("briefing") == "voxtral"


def test_select_tier_unknown_defaults_to_voxtral() -> None:
    assert select_tier("unknown_thing") == "voxtral"


# ---------------------------------------------------------------------------
# _audio_to_pcm_int16
# ---------------------------------------------------------------------------


def test_pcm_silence() -> None:
    silence = np.zeros(100, dtype=np.float32)
    pcm = _audio_to_pcm_int16(silence)
    assert len(pcm) == 200  # 100 samples * 2 bytes each
    assert pcm == b"\x00" * 200


def test_pcm_full_scale() -> None:
    full = np.ones(1, dtype=np.float32)
    pcm = _audio_to_pcm_int16(full)
    value = struct.unpack("<h", pcm)[0]
    # 1.0 * 32768 overflows int16 to -32768 (standard PCM convention)
    assert value == -32768


def test_pcm_clipping() -> None:
    over = np.array([2.0], dtype=np.float32)
    pcm = _audio_to_pcm_int16(over)
    value = struct.unpack("<h", pcm)[0]
    # Clipped to 1.0, then * 32768 overflows to -32768
    assert value == -32768


def test_pcm_negative() -> None:
    neg = np.array([-1.0], dtype=np.float32)
    pcm = _audio_to_pcm_int16(neg)
    value = struct.unpack("<h", pcm)[0]
    # -1.0 * 32768 = -32768, fits int16 exactly
    assert value == -32768


# ---------------------------------------------------------------------------
# _decode_pcm_f32_b64
# ---------------------------------------------------------------------------


def test_decode_pcm_f32_b64_roundtrip() -> None:
    """Encode float32 samples to base64, decode back, verify equality."""
    samples = [0.0, 0.5, -0.5, 1.0, -1.0]
    raw = struct.pack(f"<{len(samples)}f", *samples)
    b64 = base64.b64encode(raw).decode()
    result = _decode_pcm_f32_b64(b64)
    np.testing.assert_array_almost_equal(result, samples)


# ---------------------------------------------------------------------------
# TTSManager — init
# ---------------------------------------------------------------------------


def test_tts_manager_init_sets_voice() -> None:
    with patch.dict("os.environ", {"MISTRAL_API_KEY": "test-key"}):
        mgr = TTSManager(voice_id="bf_emma")
    assert mgr.voice_id == "bf_emma"


def test_tts_manager_default_voice() -> None:
    """Default voice_id is 'jessica'."""
    with patch.dict("os.environ", {"MISTRAL_API_KEY": "test-key"}):
        mgr = TTSManager()
    assert mgr.voice_id == "gb_jane_neutral"


def test_tts_manager_ref_audio(tmp_path) -> None:
    """ref_audio_path loads and base64-encodes the file."""
    audio_file = tmp_path / "ref.wav"
    audio_file.write_bytes(b"\x00\x01\x02\x03")

    mgr = TTSManager(ref_audio_path=str(audio_file))
    expected_b64 = base64.b64encode(b"\x00\x01\x02\x03").decode("ascii")
    assert mgr._ref_audio_b64 == expected_b64


# ---------------------------------------------------------------------------
# Voxtral synthesis (mocked Mistral client)
# ---------------------------------------------------------------------------


def _make_stream_events(pcm_f32_samples: list[float]) -> list:
    """Create mock streaming events from float32 samples."""
    raw = struct.pack(f"<{len(pcm_f32_samples)}f", *pcm_f32_samples)
    b64 = base64.b64encode(raw).decode()
    delta = MagicMock()
    delta.event = "speech.audio.delta"
    delta.data.audio_data = b64
    done = MagicMock()
    done.event = "speech.audio.done"
    return [delta, done]


def _make_manager_with_client(
    mock_client: MagicMock,
    voice_id: str = "gb_jane_neutral",
    ref_audio_path: str | None = None,
) -> TTSManager:
    """Create a TTSManager with mock client pre-injected (bypasses lazy init)."""
    mgr = TTSManager(voice_id=voice_id, ref_audio_path=ref_audio_path)
    mgr._client = mock_client
    return mgr


def test_voxtral_synthesis_returns_pcm() -> None:
    """Mock Mistral client streaming, verify PCM output."""
    samples = [0.0, 0.5, -0.5, 1.0]
    events = _make_stream_events(samples)

    mock_client = MagicMock()
    mock_stream = MagicMock()
    mock_stream.__enter__ = MagicMock(return_value=iter(events))
    mock_stream.__exit__ = MagicMock(return_value=False)
    mock_client.audio.speech.complete.return_value = mock_stream

    mgr = _make_manager_with_client(mock_client)
    result = mgr.synthesize("hello")

    assert isinstance(result, bytes)
    assert len(result) == len(samples) * 2  # int16 = 2 bytes per sample


def test_voxtral_empty_output() -> None:
    """Only speech.audio.done event, returns b''."""
    done = MagicMock()
    done.event = "speech.audio.done"
    events = [done]

    mock_client = MagicMock()
    mock_stream = MagicMock()
    mock_stream.__enter__ = MagicMock(return_value=iter(events))
    mock_stream.__exit__ = MagicMock(return_value=False)
    mock_client.audio.speech.complete.return_value = mock_stream

    mgr = _make_manager_with_client(mock_client)
    result = mgr.synthesize("")

    assert result == b""


def test_voxtral_uses_ref_audio_when_set(tmp_path) -> None:
    """Verify ref_audio is passed instead of voice_id."""
    audio_file = tmp_path / "ref.wav"
    audio_file.write_bytes(b"\xff\xfe")

    samples = [0.0]
    events = _make_stream_events(samples)

    mock_client = MagicMock()
    mock_stream = MagicMock()
    mock_stream.__enter__ = MagicMock(return_value=iter(events))
    mock_stream.__exit__ = MagicMock(return_value=False)
    mock_client.audio.speech.complete.return_value = mock_stream

    mgr = _make_manager_with_client(mock_client, ref_audio_path=str(audio_file))
    mgr.synthesize("hello there my friend")  # >=3 words to trigger ref_audio path

    call_kwargs = mock_client.audio.speech.complete.call_args.kwargs
    assert "ref_audio" in call_kwargs
    assert "voice_id" not in call_kwargs


def test_voxtral_missing_api_key() -> None:
    """RuntimeError when MISTRAL_API_KEY not set."""
    with patch.dict("os.environ", {"MISTRAL_API_KEY": ""}):
        mgr = TTSManager(voice_id="gb_jane_neutral")
        with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
            mgr._get_client()


def test_voxtral_client_loaded_once() -> None:
    """Lazy-init singleton pattern — client created once, reused."""
    samples = [0.0]
    events1 = _make_stream_events(samples)
    events2 = _make_stream_events(samples)

    mock_client = MagicMock()

    # Need separate stream objects for each call
    mock_stream1 = MagicMock()
    mock_stream1.__enter__ = MagicMock(return_value=iter(events1))
    mock_stream1.__exit__ = MagicMock(return_value=False)

    mock_stream2 = MagicMock()
    mock_stream2.__enter__ = MagicMock(return_value=iter(events2))
    mock_stream2.__exit__ = MagicMock(return_value=False)

    mock_client.audio.speech.complete.side_effect = [mock_stream1, mock_stream2]

    mgr = _make_manager_with_client(mock_client)
    mgr.synthesize("a")
    mgr.synthesize("b")

    # Client was pre-injected; verify it wasn't replaced (still the same object)
    assert mgr._client is mock_client
    # Two synthesis calls should have made two stream calls
    assert mock_client.audio.speech.complete.call_count == 2
