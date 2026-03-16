"""Tests for the vocal effects processor."""

from __future__ import annotations

import numpy as np

from agents.hapax_voice.vocal_fx import (
    _DEFAULT_PRESETS,
    VocalFXProcessor,
    VocalPreset,
)

SR = 24000


def _make_pcm(duration_s: float = 1.0, freq_hz: float = 440.0) -> bytes:
    """Generate a sine wave as PCM int16 bytes."""
    t = np.linspace(0, duration_s, int(SR * duration_s), endpoint=False)
    audio = (np.sin(2 * np.pi * freq_hz * t) * 16000).astype(np.int16)
    return audio.tobytes()


class TestPresets:
    def test_default_presets_exist(self):
        proc = VocalFXProcessor()
        assert "warm_conversation" in proc.available_presets
        assert "clear_notification" in proc.available_presets
        assert "broadcast_briefing" in proc.available_presets
        assert "bypass" in proc.available_presets

    def test_switch_preset(self):
        proc = VocalFXProcessor()
        assert proc.active_preset == "warm_conversation"
        assert proc.switch_preset("bypass")
        assert proc.active_preset == "bypass"

    def test_switch_unknown_preset_fails(self):
        proc = VocalFXProcessor()
        assert not proc.switch_preset("nonexistent")
        assert proc.active_preset == "warm_conversation"

    def test_preset_from_dict(self):
        data = _DEFAULT_PRESETS["warm_conversation"]
        preset = VocalPreset.from_dict(data)
        assert preset.name == "warm_conversation"
        assert len(preset.effects) > 0

    def test_use_case_routing(self):
        proc = VocalFXProcessor()
        assert proc.preset_for_use_case("conversation") == "warm_conversation"
        assert proc.preset_for_use_case("notification") == "clear_notification"
        assert proc.preset_for_use_case("briefing") == "broadcast_briefing"
        assert proc.preset_for_use_case("unknown") == proc.active_preset


class TestProcessing:
    def test_process_produces_same_length(self):
        proc = VocalFXProcessor()
        pcm = _make_pcm(1.0)
        processed = proc.process(pcm, use_case="conversation")
        assert len(processed) == len(pcm)

    def test_process_modifies_audio(self):
        proc = VocalFXProcessor()
        pcm = _make_pcm(1.0)
        processed = proc.process(pcm, use_case="conversation")
        assert processed != pcm, "Effects should modify the audio"

    def test_bypass_returns_unchanged(self):
        proc = VocalFXProcessor()
        proc.switch_preset("bypass")
        pcm = _make_pcm(1.0)
        processed = proc.process(pcm)
        assert processed == pcm

    def test_empty_input_returns_empty(self):
        proc = VocalFXProcessor()
        assert proc.process(b"") == b""

    def test_process_fail_open(self):
        """If the chain somehow fails, return unprocessed audio."""
        proc = VocalFXProcessor()
        pcm = _make_pcm(0.5)
        # Corrupt the chain to force an error
        proc._chains["warm_conversation"] = "not a pedalboard"
        result = proc.process(pcm, use_case="conversation")
        assert len(result) == len(pcm)

    def test_all_presets_process_without_error(self):
        proc = VocalFXProcessor()
        pcm = _make_pcm(0.5)
        for preset_name in proc.available_presets:
            proc.switch_preset(preset_name)
            result = proc.process(pcm)
            assert len(result) == len(pcm), f"Preset {preset_name} changed audio length"

    def test_output_not_clipped_to_silence(self):
        proc = VocalFXProcessor()
        pcm = _make_pcm(1.0, freq_hz=1000)
        processed = proc.process(pcm, use_case="conversation")
        audio = np.frombuffer(processed, dtype=np.int16)
        assert np.max(np.abs(audio)) > 100, "Output should not be silent"

    def test_limiter_prevents_clipping(self):
        """Loud input should be limited, not clipped hard."""
        proc = VocalFXProcessor()
        # Generate very loud signal
        t = np.linspace(0, 0.5, int(SR * 0.5), endpoint=False)
        loud = (np.sin(2 * np.pi * 1000 * t) * 32000).astype(np.int16)
        pcm = loud.tobytes()
        processed = proc.process(pcm, use_case="conversation")
        audio = np.frombuffer(processed, dtype=np.int16).astype(np.float32)
        # Peak should be below max int16 (limiter at -1dB)
        assert np.max(np.abs(audio)) < 32767


class TestLatency:
    def test_processing_under_10ms(self):
        """Vocal FX chain must not add perceptible latency."""
        import time

        proc = VocalFXProcessor()
        pcm = _make_pcm(3.0)  # 3 seconds of audio
        # Warmup
        proc.process(pcm, use_case="conversation")

        times = []
        for _ in range(10):
            t0 = time.monotonic()
            proc.process(pcm, use_case="conversation")
            times.append((time.monotonic() - t0) * 1000)

        mean_ms = np.mean(times)
        assert mean_ms < 10, f"Mean processing time {mean_ms:.1f}ms exceeds 10ms budget"
