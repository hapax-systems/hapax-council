"""Tests for the director's audio reactivity prompt block (ARI L1/L22).

Acceptance criteria:
- Director reads audio state from unified-reactivity SHM snapshot.
- Silent, low, moderate, high energy labels are correctly assigned.
- Spectrum is classified as bass-heavy, balanced, or bright.
- Voice activity detection based on per-source RMS threshold.
- Missing or stale snapshot returns None (section omitted).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture()
def shm_path(tmp_path: Path) -> Path:
    return tmp_path / "unified-reactivity.json"


def _write_snapshot(
    path: Path,
    *,
    rms: float = 0.0,
    bass: float = 0.0,
    mid: float = 0.0,
    treble: float = 0.0,
    onset: float = 0.0,
    bpm: float = 0.0,
    published_at: float | None = None,
) -> None:
    import time

    data = {
        "blended": {
            "rms": rms,
            "onset": onset,
            "centroid": 0.5,
            "zcr": 0.01,
            "bpm_estimate": bpm,
            "energy_delta": 0.0,
            "bass_band": bass,
            "mid_band": mid,
            "treble_band": treble,
        },
        "per_source": {
            "mixer": {
                "rms": rms,
                "onset": onset,
                "centroid": 0.5,
                "zcr": 0.01,
                "bpm_estimate": bpm,
                "energy_delta": 0.0,
                "bass_band": bass,
                "mid_band": mid,
                "treble_band": treble,
            },
        },
        "active_sources": ["mixer"] if rms > 0.01 else [],
        "published_at": published_at or time.time(),
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_director_loop():
    from unittest.mock import MagicMock

    from agents.studio_compositor.director_loop import DirectorLoop

    mock_slot = MagicMock()
    mock_slot.slot_id = 0
    mock_slot._title = "test"
    mock_slot._channel = "test"
    mock_reactor = MagicMock()
    loop = DirectorLoop([mock_slot], mock_reactor)
    return loop


class TestAudioReactivityBlock:
    def test_silent_energy_label(self, shm_path: Path) -> None:
        _write_snapshot(shm_path, rms=0.001)
        loop = _make_director_loop()
        with patch("shared.audio_reactivity.SHM_PATH", shm_path):
            block = loop._render_audio_reactivity_block()
        assert block is not None
        joined = " ".join(block)
        assert "silent" in joined.lower()

    def test_moderate_energy_label(self, shm_path: Path) -> None:
        _write_snapshot(shm_path, rms=0.25)
        loop = _make_director_loop()
        with patch("shared.audio_reactivity.SHM_PATH", shm_path):
            block = loop._render_audio_reactivity_block()
        assert block is not None
        joined = " ".join(block)
        assert "moderate" in joined.lower()

    def test_high_energy_label(self, shm_path: Path) -> None:
        _write_snapshot(shm_path, rms=0.6)
        loop = _make_director_loop()
        with patch("shared.audio_reactivity.SHM_PATH", shm_path):
            block = loop._render_audio_reactivity_block()
        assert block is not None
        joined = " ".join(block)
        assert "high" in joined.lower()

    def test_bass_heavy_spectrum(self, shm_path: Path) -> None:
        _write_snapshot(shm_path, rms=0.3, bass=0.5, mid=0.1, treble=0.05)
        loop = _make_director_loop()
        with patch("shared.audio_reactivity.SHM_PATH", shm_path):
            block = loop._render_audio_reactivity_block()
        assert block is not None
        joined = " ".join(block)
        assert "bass-heavy" in joined.lower()

    def test_bright_spectrum(self, shm_path: Path) -> None:
        _write_snapshot(shm_path, rms=0.3, bass=0.05, mid=0.1, treble=0.4)
        loop = _make_director_loop()
        with patch("shared.audio_reactivity.SHM_PATH", shm_path):
            block = loop._render_audio_reactivity_block()
        assert block is not None
        joined = " ".join(block)
        assert "bright" in joined.lower()

    def test_voice_active_detection(self, shm_path: Path) -> None:
        _write_snapshot(shm_path, rms=0.2)
        loop = _make_director_loop()
        with patch("shared.audio_reactivity.SHM_PATH", shm_path):
            block = loop._render_audio_reactivity_block()
        assert block is not None
        joined = " ".join(block)
        assert "active" in joined.lower()

    def test_stale_snapshot_returns_none(self, shm_path: Path) -> None:
        import time

        _write_snapshot(shm_path, rms=0.3, published_at=time.time() - 30)
        loop = _make_director_loop()
        with patch("shared.audio_reactivity.SHM_PATH", shm_path):
            block = loop._render_audio_reactivity_block()
        assert block is None

    def test_missing_snapshot_returns_none(self) -> None:
        loop = _make_director_loop()
        with patch(
            "shared.audio_reactivity.SHM_PATH",
            Path("/nonexistent/path/unified-reactivity.json"),
        ):
            block = loop._render_audio_reactivity_block()
        assert block is None

    def test_bpm_included_when_present(self, shm_path: Path) -> None:
        _write_snapshot(shm_path, rms=0.3, bpm=120.0)
        loop = _make_director_loop()
        with patch("shared.audio_reactivity.SHM_PATH", shm_path):
            block = loop._render_audio_reactivity_block()
        assert block is not None
        joined = " ".join(block)
        assert "120" in joined

    def test_beat_detection(self, shm_path: Path) -> None:
        _write_snapshot(shm_path, rms=0.3, onset=0.8)
        loop = _make_director_loop()
        with patch("shared.audio_reactivity.SHM_PATH", shm_path):
            block = loop._render_audio_reactivity_block()
        assert block is not None
        joined = " ".join(block)
        assert "Beat: yes" in joined
