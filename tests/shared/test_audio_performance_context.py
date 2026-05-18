"""Tests for shared.audio_performance_context."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from shared.audio_performance_context import (
    AudioContextSignal,
    build_performance_context,
    classify_vinyl_performance_intent,
    read_audio_context_signal,
    read_audio_performance_mode,
)


def _write_impingements(path: Path, *impingements: dict[str, object]) -> None:
    path.write_text(
        "".join(f"{json.dumps(impingement)}\n" for impingement in impingements),
        encoding="utf-8",
    )


def _audio_impingement(
    source: str,
    state: str,
    *,
    timestamp: float | None = None,
) -> dict[str, object]:
    return {
        "id": f"test-{source}-{state}",
        "timestamp": time.time() if timestamp is None else timestamp,
        "source": source,
        "content": {"to_state": state},
    }


def test_idle_when_no_impingements(tmp_path: Path) -> None:
    with (
        patch("shared.audio_performance_context.IMPINGEMENTS_PATH", tmp_path / "missing.jsonl"),
        patch("shared.audio_performance_context.PERCEPTION_STATE_PATH", tmp_path / "missing.json"),
        patch("shared.audio_performance_context._read_voice_active", return_value=False),
    ):
        assert read_audio_performance_mode() == "idle"


def test_active_performance_on_vinyl(tmp_path: Path) -> None:
    imp_file = tmp_path / "impingements.jsonl"
    _write_impingements(imp_file, _audio_impingement("audio.vinyl_spinning", "ASSERTED"))
    with (
        patch("shared.audio_performance_context.IMPINGEMENTS_PATH", imp_file),
        patch("shared.audio_performance_context.PERCEPTION_STATE_PATH", tmp_path / "missing.json"),
        patch("shared.audio_performance_context._read_voice_active", return_value=False),
    ):
        assert read_audio_performance_mode() == "active_performance"


def test_passive_music_on_yamnet(tmp_path: Path) -> None:
    imp_file = tmp_path / "impingements.jsonl"
    _write_impingements(imp_file, _audio_impingement("audio.music_playing", "ASSERTED"))
    with (
        patch("shared.audio_performance_context.IMPINGEMENTS_PATH", imp_file),
        patch("shared.audio_performance_context.PERCEPTION_STATE_PATH", tmp_path / "missing.json"),
        patch("shared.audio_performance_context._read_voice_active", return_value=False),
    ):
        assert read_audio_performance_mode() == "passive_music"


def test_speaking_overrides_performance(tmp_path: Path) -> None:
    imp_file = tmp_path / "impingements.jsonl"
    _write_impingements(imp_file, _audio_impingement("audio.vinyl_spinning", "ASSERTED"))
    with (
        patch("shared.audio_performance_context.IMPINGEMENTS_PATH", imp_file),
        patch("shared.audio_performance_context.PERCEPTION_STATE_PATH", tmp_path / "missing.json"),
        patch("shared.audio_performance_context._read_voice_active", return_value=True),
    ):
        assert read_audio_performance_mode() == "speaking"


def test_build_performance_context_returns_dict() -> None:
    signal = AudioContextSignal(
        performance_mode="idle",
        vinyl_performance_intent="background_playback",
    )
    with patch("shared.audio_performance_context.read_audio_context_signal", return_value=signal):
        ctx = build_performance_context()
        assert ctx == {
            "audio_performance_mode": "idle",
            "vinyl_performance_intent": "background_playback",
        }


def test_vinyl_intent_idle_without_signal() -> None:
    intent, evidence = classify_vinyl_performance_intent(
        vinyl_spinning=False,
        perception={},
    )

    assert intent == "idle"
    assert evidence == ()


def test_vinyl_intent_background_when_spinning_without_scratch_cues() -> None:
    intent, evidence = classify_vinyl_performance_intent(
        vinyl_spinning=True,
        perception={},
    )

    assert intent == "background_playback"
    assert evidence == ("audio.vinyl_spinning=ASSERTED",)


def test_vinyl_intent_scratching_from_cross_modal_turntable_cues() -> None:
    intent, evidence = classify_vinyl_performance_intent(
        vinyl_spinning=True,
        perception={
            "ir_hand_zone": "turntable",
            "ir_hand_activity": "sliding",
            "desk_energy": 0.2,
            "desk_onset_rate": 2.0,
            "desk_spectral_centroid": 500.0,
            "desk_autocorr_peak": 0.1,
        },
    )

    assert intent == "scratching"
    assert "vision.turntable_hand_activity=sliding" in evidence
    assert "contact_mic_ir.classifier=scratching" in evidence


def test_audio_context_signal_includes_scratching_intent(tmp_path: Path) -> None:
    imp_file = tmp_path / "impingements.jsonl"
    perception_file = tmp_path / "perception-state.json"
    _write_impingements(imp_file, _audio_impingement("audio.vinyl_spinning", "ASSERTED"))
    perception_file.write_text(
        json.dumps(
            {
                "ir_hand_zone": "turntable",
                "ir_hand_activity": "sliding",
                "desk_energy": 0.2,
                "desk_onset_rate": 2.0,
                "desk_spectral_centroid": 500.0,
                "desk_autocorr_peak": 0.1,
            }
        ),
        encoding="utf-8",
    )

    with (
        patch("shared.audio_performance_context.IMPINGEMENTS_PATH", imp_file),
        patch("shared.audio_performance_context.PERCEPTION_STATE_PATH", perception_file),
        patch("shared.audio_performance_context._read_voice_active", return_value=False),
    ):
        signal = read_audio_context_signal()

    assert signal.performance_mode == "active_performance"
    assert signal.vinyl_performance_intent == "scratching"
    assert "audio.vinyl_spinning=ASSERTED" in signal.evidence
    assert "contact_mic_ir.classifier=scratching" in signal.evidence


def test_audio_context_signal_distinguishes_background_vinyl(tmp_path: Path) -> None:
    imp_file = tmp_path / "impingements.jsonl"
    _write_impingements(imp_file, _audio_impingement("audio.vinyl_spinning", "ASSERTED"))

    with (
        patch("shared.audio_performance_context.IMPINGEMENTS_PATH", imp_file),
        patch("shared.audio_performance_context.PERCEPTION_STATE_PATH", tmp_path / "missing.json"),
        patch("shared.audio_performance_context._read_voice_active", return_value=False),
    ):
        signal = read_audio_context_signal()

    assert signal.performance_mode == "active_performance"
    assert signal.vinyl_performance_intent == "background_playback"
    assert signal.evidence.count("audio.vinyl_spinning=ASSERTED") == 1


def test_audio_context_signal_treats_scratch_cues_as_active_performance(
    tmp_path: Path,
) -> None:
    imp_file = tmp_path / "impingements.jsonl"
    perception_file = tmp_path / "perception-state.json"
    _write_impingements(imp_file)
    perception_file.write_text(
        json.dumps(
            {
                "overhead_hand_zones": "turntable,mixer",
                "desk_activity": "tapping",
            }
        ),
        encoding="utf-8",
    )

    with (
        patch("shared.audio_performance_context.IMPINGEMENTS_PATH", imp_file),
        patch("shared.audio_performance_context.PERCEPTION_STATE_PATH", perception_file),
        patch("shared.audio_performance_context._read_voice_active", return_value=False),
    ):
        signal = read_audio_context_signal()

    assert signal.performance_mode == "active_performance"
    assert signal.vinyl_performance_intent == "scratching"
    assert "contact_mic_ir.turntable_non_idle" in signal.evidence


def test_audio_context_signal_uses_latest_vinyl_state(tmp_path: Path) -> None:
    imp_file = tmp_path / "impingements.jsonl"
    now = time.time()
    _write_impingements(
        imp_file,
        _audio_impingement("audio.vinyl_spinning", "ASSERTED", timestamp=now - 10),
        _audio_impingement("audio.vinyl_spinning", "RETRACTED", timestamp=now),
    )

    with (
        patch("shared.audio_performance_context.IMPINGEMENTS_PATH", imp_file),
        patch("shared.audio_performance_context.PERCEPTION_STATE_PATH", tmp_path / "missing.json"),
        patch("shared.audio_performance_context._read_voice_active", return_value=False),
    ):
        signal = read_audio_context_signal()

    assert signal.performance_mode == "idle"
    assert signal.vinyl_performance_intent == "idle"
