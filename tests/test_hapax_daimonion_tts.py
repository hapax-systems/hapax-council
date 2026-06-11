"""Tests for hapax_daimonion TTS — backend selector, synthesis, witness backend.

The pre-2026-06 version of this file tested a Kokoro-only TTSManager API
(``_pipeline``/``_get_pipeline``) that no longer exists; it is rewritten
against the real module, including the ``HAPAX_TTS_BACKEND`` selector shipped
under CASE-VOICE-FOUNDATION-20260610.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import numpy as np

from agents.hapax_daimonion.tts import (
    TTS_BACKEND_ENV,
    TTS_TRANSPORT_ENV,
    VALID_TTS_BACKENDS,
    VALID_TTS_TRANSPORTS,
    TTSManager,
    priority_class_for_use_case,
    resolve_backend_from_env,
    resolve_transport_from_env,
    select_tier,
)

# ---------------------------------------------------------------------------
# select_tier
# ---------------------------------------------------------------------------


def test_select_tier_known_use_cases_map_to_chatterbox() -> None:
    for use_case in ("conversation", "notification", "briefing", "proactive"):
        assert select_tier(use_case) == "chatterbox"


def test_select_tier_unknown_defaults_to_chatterbox() -> None:
    assert select_tier("unknown_thing") == "chatterbox"


# ---------------------------------------------------------------------------
# Backend selector — HAPAX_TTS_BACKEND is honored by code, not theater
# ---------------------------------------------------------------------------


def test_backend_env_unset_defaults_to_chatterbox() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop(TTS_BACKEND_ENV, None)
        assert resolve_backend_from_env() == "chatterbox"


def test_backend_env_kokoro_selected() -> None:
    with patch.dict(os.environ, {TTS_BACKEND_ENV: "kokoro"}):
        assert resolve_backend_from_env() == "kokoro"
        assert TTSManager().backend == "kokoro"


def test_backend_env_tolerates_case_and_whitespace() -> None:
    with patch.dict(os.environ, {TTS_BACKEND_ENV: "  Kokoro "}):
        assert resolve_backend_from_env() == "kokoro"


def test_backend_env_invalid_warns_and_defaults(caplog) -> None:
    with patch.dict(os.environ, {TTS_BACKEND_ENV: "espeak"}):
        with caplog.at_level("WARNING", logger="agents.hapax_daimonion.tts"):
            assert resolve_backend_from_env() == "chatterbox"
    assert any(TTS_BACKEND_ENV in rec.message for rec in caplog.records)


def test_valid_backends_pin() -> None:
    assert VALID_TTS_BACKENDS == ("chatterbox", "kokoro")


def test_transport_env_unset_defaults_to_local() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop(TTS_TRANSPORT_ENV, None)
        assert resolve_transport_from_env() == "local"


def test_transport_env_server_selected() -> None:
    with patch.dict(os.environ, {TTS_TRANSPORT_ENV: "server"}):
        assert resolve_transport_from_env() == "server"
        assert TTSManager().transport == "server"


def test_valid_transports_pin() -> None:
    assert VALID_TTS_TRANSPORTS == ("local", "server")


def test_priority_class_maps_interactive_bridge_hosting() -> None:
    assert priority_class_for_use_case("conversation") == "interactive"
    assert priority_class_for_use_case("bridge") == "bridge"
    assert priority_class_for_use_case("proactive") == "hosting"


def test_server_transport_preload_does_not_load_models(tmp_path) -> None:
    mgr = TTSManager(
        transport="server",
        server_socket_path=tmp_path / "missing.sock",
        request_deadline_s=0.001,
    )
    with (
        patch.object(mgr, "_get_kokoro") as mock_kokoro,
        patch.object(mgr, "_get_chatterbox") as mock_chatterbox,
    ):
        mgr.preload()
    mock_kokoro.assert_not_called()
    mock_chatterbox.assert_not_called()
    assert mgr.last_server_liveness is not None
    assert mgr.last_server_liveness["status"] == "unreachable"


def test_server_transport_error_clears_stale_synthesis_backend(tmp_path) -> None:
    mgr = TTSManager(
        transport="server",
        server_socket_path=tmp_path / "missing.sock",
        request_deadline_s=0.001,
    )
    mgr._last_synthesis_backend = "kokoro"

    # Server error clears the stale backend AND (2026-06-11 review fix)
    # falls back to in-process synthesis rather than silencing the voice.
    with patch.object(mgr, "_synthesize_kokoro", return_value=b"\x05\x06") as local:
        result = mgr.synthesize("hello", "conversation")

    assert local.called, "in-process fallback must engage on server error"
    assert result == b"\x05\x06"
    assert mgr.last_server_liveness is not None
    assert mgr.last_server_liveness["status"] == "error"


def test_preload_kokoro_backend_never_touches_chatterbox() -> None:
    with patch.dict(os.environ, {TTS_BACKEND_ENV: "kokoro"}):
        mgr = TTSManager()
    with (
        patch.object(mgr, "_get_kokoro") as mock_kokoro,
        patch.object(mgr, "_get_chatterbox") as mock_chatterbox,
    ):
        mgr.preload()
    mock_kokoro.assert_called_once()
    mock_chatterbox.assert_not_called()
    assert mgr.backend == "kokoro"


def test_preload_chatterbox_failure_demotes_to_kokoro() -> None:
    with patch.dict(os.environ, {TTS_BACKEND_ENV: "chatterbox"}):
        mgr = TTSManager()
    with (
        patch.object(mgr, "_get_chatterbox", side_effect=RuntimeError("no kernel image")),
        patch.object(mgr, "_get_kokoro"),
    ):
        mgr.preload()
    assert mgr.backend == "kokoro"


# ---------------------------------------------------------------------------
# Kokoro synthesis (mocked pipeline)
# ---------------------------------------------------------------------------


def _kokoro_manager(audio_samples: np.ndarray | object | None) -> TTSManager:
    """TTSManager pinned to kokoro with a mock pipeline yielding one chunk."""
    mgr = TTSManager()
    mgr._backend = "kokoro"
    pipeline = MagicMock()
    pipeline.return_value = iter([("hello", "h_lo", audio_samples)])
    mgr._kokoro_pipeline = pipeline
    return mgr


def test_kokoro_synthesis_returns_pcm() -> None:
    samples = np.array([0.0, 0.5, -0.5, 1.0], dtype=np.float32)
    mgr = _kokoro_manager(samples)
    result = mgr.synthesize("hello")
    assert isinstance(result, bytes)
    assert len(result) == len(samples) * 2  # int16 = 2 bytes per sample


def test_empty_text_returns_empty_without_synthesis() -> None:
    mgr = _kokoro_manager(None)
    assert mgr.synthesize("") == b""
    assert mgr.synthesize("   ") == b""
    assert mgr.last_synthesis_backend is None


def test_kokoro_no_audio_output_returns_empty() -> None:
    mgr = _kokoro_manager(None)
    assert mgr.synthesize("hello") == b""


def test_kokoro_torch_tensor_converted() -> None:
    raw = np.array([0.5, -0.5], dtype=np.float32)
    tensor = MagicMock()
    tensor.numpy.return_value = raw
    mgr = _kokoro_manager(tensor)
    result = mgr.synthesize("hi")
    tensor.numpy.assert_called_once()
    assert len(result) == 4  # 2 samples * 2 bytes


# ---------------------------------------------------------------------------
# last_synthesis_backend — the witness truth
# ---------------------------------------------------------------------------


def test_kokoro_synthesis_records_backend() -> None:
    samples = np.array([0.1], dtype=np.float32)
    mgr = _kokoro_manager(samples)
    mgr.synthesize("hello")
    assert mgr.last_synthesis_backend == "kokoro"


def test_chatterbox_per_call_failure_falls_back_and_records_kokoro() -> None:
    mgr = TTSManager()
    mgr._backend = "chatterbox"
    samples = np.array([0.1, 0.2], dtype=np.float32)
    pipeline = MagicMock()
    pipeline.return_value = iter([("hello", "h_lo", samples)])
    mgr._kokoro_pipeline = pipeline
    with patch.object(mgr, "_get_chatterbox", side_effect=RuntimeError("cuda error")):
        result = mgr.synthesize("hello")
    assert len(result) == 4
    assert mgr.last_synthesis_backend == "kokoro"


# ---------------------------------------------------------------------------
# voice-output witness carries the synthesizing backend
# ---------------------------------------------------------------------------


def test_record_tts_synthesis_includes_backend(tmp_path) -> None:
    from agents.hapax_daimonion.voice_output_witness import record_tts_synthesis

    path = tmp_path / "voice-output-witness.json"
    witness = record_tts_synthesis(
        status="completed",
        text="hello there",
        pcm=b"\x00\x00" * 240,
        backend="kokoro",
        path=path,
    )
    assert witness.last_tts_synthesis is not None
    assert witness.last_tts_synthesis["backend"] == "kokoro"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["last_tts_synthesis"]["backend"] == "kokoro"


def test_record_tts_synthesis_includes_server_liveness(tmp_path) -> None:
    from agents.hapax_daimonion.voice_output_witness import record_tts_synthesis

    path = tmp_path / "voice-output-witness.json"
    witness = record_tts_synthesis(
        status="completed",
        text="hello there",
        pcm=b"\x00\x00" * 240,
        backend="kokoro",
        server_liveness={"mode": "server", "status": "ok", "queue_wait_ms": 3},
        path=path,
    )
    assert witness.last_tts_synthesis is not None
    assert witness.last_tts_synthesis["server_liveness"]["status"] == "ok"


def test_record_tts_synthesis_backend_defaults_to_none(tmp_path) -> None:
    from agents.hapax_daimonion.voice_output_witness import record_tts_synthesis

    path = tmp_path / "voice-output-witness.json"
    witness = record_tts_synthesis(status="empty", text="", pcm=b"", path=path)
    assert witness.last_tts_synthesis is not None
    assert witness.last_tts_synthesis["backend"] is None


def test_server_down_falls_back_to_in_process(monkeypatch, tmp_path):
    """Review finding 2026-06-11: ConnectionRefused/server-down must not
    silence the voice — synthesize() falls through to the local path."""
    from agents.hapax_daimonion import tts as tts_mod

    mgr = tts_mod.TTSManager.__new__(tts_mod.TTSManager)
    mgr._transport = "server"
    mgr._backend = "kokoro"
    mgr._last_synthesis_backend = None
    calls = {}
    monkeypatch.setattr(mgr, "_synthesize_via_server", lambda *a, **k: b"", raising=False)
    monkeypatch.setattr(
        mgr,
        "_synthesize_kokoro",
        lambda text, **k: (calls.setdefault("local", True), b"\x01\x02")[1],
        raising=False,
    )
    out = mgr.synthesize("hello world")
    assert calls.get("local"), "in-process fallback was not invoked"
    assert out == b"\x01\x02"
