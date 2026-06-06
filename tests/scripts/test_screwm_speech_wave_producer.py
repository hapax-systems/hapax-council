from __future__ import annotations

import importlib.util
import os
import struct
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


def _write_ring(path: Path, *, frame_id: int, samples: bytes, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_count = min(len(samples), 480)
    payload = struct.pack("<QBBH", frame_id, 0, 0, sample_count) + samples[:sample_count]
    payload += bytes([128] * (480 - sample_count))
    path.write_bytes(payload)
    os.utime(path, (mtime, mtime))


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


def test_changed_ring_frame_is_fresh_when_mtime_is_stale(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    ring_path = tmp_path / "speech-wave.bin"
    monkeypatch.setattr(module, "DEFAULT_RING", ring_path)
    monkeypatch.setattr(module, "DEFAULT_OUTPUT", tmp_path / "quake-live-speech-wave.bgra")
    stale_mtime = 900.0

    _write_ring(ring_path, frame_id=1, samples=bytes([128] * 480), mtime=stale_mtime)
    _frame, stale_meta = module._render((0.27, 0.91, 1.0), now=1000.0)

    samples = bytes([127, 129] * 240)
    _write_ring(ring_path, frame_id=2, samples=samples, mtime=stale_mtime)
    frame, meta = module._render((0.27, 0.91, 1.0), now=1000.1)

    assert stale_meta["state"] == "stale-idle-midline"
    assert len(frame) == module.FRAME_SIZE
    assert meta["state"] == "active-waveform"
    assert meta["ring_frame_id"] == 2
    assert meta["ring_age_s"] == 0.0
    assert meta["amplitude"] > 0.0
