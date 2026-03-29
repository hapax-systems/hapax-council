"""Tests for StudioIngestionBackend — CLAP-based audio classification.

All tests mock CLAP and audio capture — no GPU or audio hardware needed.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from agents.hapax_daimonion.backends.studio_ingestion import (
    _ACTIVITY_MAP,
    StudioIngestionBackend,
    _compute_rms,
    _estimate_flow_score,
    _InferenceCache,
)
from agents.hapax_daimonion.primitives import Behavior


class TestInferenceCache:
    def test_initial_values(self):
        cache = _InferenceCache()
        data = cache.read()
        assert data["production_activity"] == "idle"
        assert data["music_genre"] == "unknown"
        assert data["flow_state_score"] == 0.0
        assert data["audio_energy_rms"] == 0.0

    def test_update_and_read(self):
        cache = _InferenceCache()
        cache.update(
            production_activity="production",
            music_genre="hip hop beat",
            flow_state_score=0.7,
            audio_energy_rms=0.05,
        )
        data = cache.read()
        assert data["production_activity"] == "production"
        assert data["music_genre"] == "hip hop beat"
        assert data["flow_state_score"] == 0.7
        assert data["audio_energy_rms"] == 0.05
        assert data["updated_at"] > 0

    def test_thread_safety(self):
        """Cache reads and writes don't raise under concurrent access."""
        import threading

        cache = _InferenceCache()
        errors = []

        def writer():
            try:
                for _ in range(100):
                    cache.update(
                        production_activity="production",
                        music_genre="jazz",
                        flow_state_score=0.5,
                        audio_energy_rms=0.03,
                    )
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    cache.read()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


class TestComputeRms:
    def test_silence(self):
        assert _compute_rms(np.zeros(1000, dtype=np.float32)) == 0.0

    def test_empty(self):
        assert _compute_rms(np.array([], dtype=np.float32)) == 0.0

    def test_nonzero(self):
        signal = np.ones(1000, dtype=np.float32) * 0.5
        assert _compute_rms(signal) == pytest.approx(0.5)

    def test_sine_wave(self):
        t = np.linspace(0, 1, 48000, dtype=np.float32)
        signal = np.sin(2 * np.pi * 440 * t)
        rms = _compute_rms(signal)
        assert 0.7 < rms < 0.72  # RMS of sine = 1/√2 ≈ 0.707


class TestEstimateFlowScore:
    def test_idle_silence(self):
        score = _estimate_flow_score("idle", 0.0, 0.0)
        assert score == 0.0

    def test_production_with_energy(self):
        score = _estimate_flow_score("production", 0.05, 0.5)
        assert score > 0.7  # 0.5 + 0.3(capped) + 0.2 = 1.0

    def test_conversation(self):
        score = _estimate_flow_score("conversation", 0.02, 0.1)
        assert 0.1 < score < 0.5

    def test_clamped_to_one(self):
        score = _estimate_flow_score("production", 1.0, 1.0)
        assert score == 1.0


class TestActivityMap:
    def test_production_activities(self):
        assert _ACTIVITY_MAP["music production session"] == "production"
        assert _ACTIVITY_MAP["beat making"] == "production"
        assert _ACTIVITY_MAP["mixing and mastering"] == "production"

    def test_conversation(self):
        assert _ACTIVITY_MAP["casual conversation"] == "conversation"

    def test_idle(self):
        assert _ACTIVITY_MAP["silence or ambient noise"] == "idle"


class TestStudioIngestionBackend:
    def test_name(self):
        backend = StudioIngestionBackend()
        assert backend.name == "studio_ingestion"

    def test_provides(self):
        backend = StudioIngestionBackend()
        expected = {
            "production_activity",
            "music_genre",
            "flow_state_score",
            "emotion_valence",
            "emotion_arousal",
            "audio_energy_rms",
        }
        assert backend.provides == frozenset(expected)

    def test_tier_is_slow(self):
        from agents.hapax_daimonion.perception import PerceptionTier

        backend = StudioIngestionBackend()
        assert backend.tier == PerceptionTier.SLOW

    def test_available_when_clap_importable(self):
        with patch.dict("sys.modules", {"shared.clap": MagicMock()}):
            backend = StudioIngestionBackend()
            assert backend.available() is True

    def test_contribute_reads_cache(self):
        backend = StudioIngestionBackend()
        backend._cache.update(
            production_activity="production",
            music_genre="trap beat",
            flow_state_score=0.8,
            audio_energy_rms=0.04,
        )

        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)

        assert behaviors["production_activity"].value == "production"
        assert behaviors["music_genre"].value == "trap beat"
        assert behaviors["flow_state_score"].value == pytest.approx(0.8)
        assert behaviors["audio_energy_rms"].value == pytest.approx(0.04)
        assert behaviors["emotion_valence"].value == 0.0  # Placeholder
        assert behaviors["emotion_arousal"].value == 0.0  # Placeholder

    def test_contribute_never_blocks(self):
        """contribute() should complete in <10ms even with empty cache."""
        backend = StudioIngestionBackend()
        behaviors: dict[str, Behavior] = {}

        start = time.monotonic()
        backend.contribute(behaviors)
        elapsed = time.monotonic() - start

        assert elapsed < 0.01  # 10ms max

    def test_start_stop_lifecycle(self):
        """Start creates thread, stop joins it."""
        backend = StudioIngestionBackend(poll_interval=0.1)

        with patch(
            "agents.hapax_daimonion.backends.studio_ingestion._capture_audio",
            return_value=None,
        ):
            backend.start()
            assert backend._thread is not None
            assert backend._thread.is_alive()

            backend.stop()
            assert backend._thread is None

    def test_inference_step_with_silence(self):
        """Near-silence audio results in idle state."""
        backend = StudioIngestionBackend()
        silence = np.zeros(48000 * 10, dtype=np.float32)

        with patch(
            "agents.hapax_daimonion.backends.studio_ingestion._capture_audio",
            return_value=silence,
        ):
            backend._run_inference_step()

        data = backend._cache.read()
        assert data["production_activity"] == "idle"
        assert data["music_genre"] == "unknown"

    def test_inference_step_with_audio(self):
        """Audio above noise floor triggers CLAP classification."""
        backend = StudioIngestionBackend()
        audio = np.random.randn(48000 * 10).astype(np.float32) * 0.1

        mock_classify = MagicMock(
            side_effect=[
                # Activity scores
                {
                    "music production session": 0.4,
                    "beat making": 0.2,
                    "silence or ambient noise": 0.05,
                    "casual conversation": 0.05,
                    "sample digging and listening": 0.1,
                    "recording vocals": 0.1,
                    "mixing and mastering": 0.1,
                },
                # Genre scores
                {
                    "hip hop beat": 0.35,
                    "trap beat": 0.25,
                    "jazz": 0.1,
                    "soul music": 0.05,
                    "funk music": 0.05,
                    "boom bap beat": 0.05,
                    "lo-fi hip hop": 0.05,
                    "r&b": 0.03,
                    "electronic music": 0.02,
                    "ambient music": 0.02,
                    "rock music": 0.02,
                    "pop music": 0.01,
                },
            ]
        )

        with (
            patch(
                "agents.hapax_daimonion.backends.studio_ingestion._capture_audio",
                return_value=audio,
            ),
            patch(
                "shared.clap.classify_zero_shot",
                mock_classify,
            ),
        ):
            backend._run_inference_step()

        data = backend._cache.read()
        assert data["production_activity"] == "production"
        assert data["music_genre"] == "hip hop beat"
        assert data["flow_state_score"] > 0.5
        assert data["audio_energy_rms"] > 0.0
