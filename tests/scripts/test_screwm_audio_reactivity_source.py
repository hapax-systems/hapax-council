from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "screwm-audio-reactivity-source.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("screwm_audio_reactivity_source", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_audio_reactivity_stays_active_on_onset_without_rms() -> None:
    module = _load_module()
    source = module.MixerMasterSource(capture=object())
    source._snap = {"mixer_energy": 0.0, "beat_pulse": 0.2}

    assert source.is_active() is True


def test_audio_reactivity_stays_active_on_band_energy_without_rms() -> None:
    module = _load_module()
    source = module.MixerMasterSource(capture=object())
    source._snap = {"mixer_energy": 0.0, "mixer_bass": 0.1}

    assert source.is_active() is True
