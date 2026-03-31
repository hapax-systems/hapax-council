"""Tests for the Reverie mixer — visual expression orchestrator."""

import json
import tempfile
from pathlib import Path

from agents.reverie.mixer import ReverieMixer


def test_mixer_initializes():
    mixer = ReverieMixer()
    assert mixer is not None


def test_mixer_reads_acoustic_impulse():
    mixer = ReverieMixer()
    with tempfile.TemporaryDirectory() as tmpdir:
        impulse_path = Path(tmpdir) / "acoustic-impulse.json"
        impulse_path.write_text(
            json.dumps(
                {
                    "source": "daimonion",
                    "timestamp": 1711907400.0,
                    "signals": {"energy": 0.7, "onset": True, "pitch_hz": 185.0},
                }
            )
        )
        result = mixer._read_acoustic_impulse(impulse_path)
        assert result is not None
        assert result["signals"]["energy"] == 0.7


def test_mixer_reads_missing_acoustic_impulse():
    mixer = ReverieMixer()
    result = mixer._read_acoustic_impulse(Path("/nonexistent/path"))
    assert result is None


def test_mixer_writes_visual_salience():
    mixer = ReverieMixer()
    with tempfile.TemporaryDirectory() as tmpdir:
        salience_path = Path(tmpdir) / "visual-salience.json"
        mixer._write_visual_salience(salience_path, salience=0.6, content_density=2)
        data = json.loads(salience_path.read_text())
        assert data["source"] == "reverie"
        assert data["signals"]["salience"] == 0.6
        assert data["signals"]["content_density"] == 2


def test_mixer_has_same_interface_as_actuation_loop():
    mixer = ReverieMixer()
    assert hasattr(mixer, "pipeline")
    assert hasattr(mixer, "shader_capability")
    assert hasattr(mixer, "visual_chain")
    assert hasattr(mixer, "tick")
    assert callable(mixer.tick)
