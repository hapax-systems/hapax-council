from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "screwm-speech-wave-producer.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("screwm_speech_wave_producer", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_missing_speech_ring_renders_idle_midline(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "DEFAULT_RING", tmp_path / "missing-speech-wave.bin")
    monkeypatch.setattr(module, "DEFAULT_OUTPUT", tmp_path / "quake-live-speech-wave.bgra")

    frame, meta = module._render((0.27, 0.91, 1.0), now=1000.0)

    assert len(frame) == module.FRAME_SIZE
    assert any(frame)
    assert meta["state"] == "missing-ring-idle-midline"
    assert meta["ring_present"] is False
    assert meta["frame_size_bytes"] == module.FRAME_SIZE
