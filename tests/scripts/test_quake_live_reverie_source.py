from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "quake-live-reverie-source.py"


def _load_reverie() -> ModuleType:
    spec = importlib.util.spec_from_file_location("quake_live_reverie_source", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_drift_state(game_data: Path) -> None:
    game_data.mkdir(parents=True, exist_ok=True)
    for filename, value in {
        "effect-drift-source.txt": "slotdrift",
        "effect-drift-real-source.txt": "1.0000",
        "effect-drift-active-ratio.txt": "0.9000",
        "effect-drift-max-delta.txt": "1.0000",
        "effect-drift-region-count.txt": "1.0000",
        "effect-drift-tonal.txt": "0.8000",
        "effect-drift-atmospheric.txt": "0.5000",
        "effect-drift-temporal.txt": "0.9000",
        "effect-drift-texture.txt": "0.9500",
        "effect-drift-edge.txt": "0.9000",
        "effect-drift-compositing.txt": "1.0000",
        "visual-chain-noise.txt": "0.8000",
        "visual-chain-drift.txt": "1.0000",
        "visual-chain-color.txt": "1.0000",
        "visual-chain-feedback.txt": "0.9000",
        "visual-chain-aperture.txt": "0.4000",
        "visual-chain-param-pressure.txt": "1.0000",
    }.items():
        (game_data / filename).write_text(value + "\n", encoding="utf-8")


def test_reverie_wrapper_applies_drift_and_writes_metadata(tmp_path: Path) -> None:
    reverie = _load_reverie()
    width = 32
    height = 16
    source = tmp_path / "reverie.rgba"
    output = tmp_path / "quake-live-reverie.bgra"
    meta = tmp_path / "quake-live-reverie.json"
    game_data = tmp_path / "data"
    _write_drift_state(game_data)

    frame = bytearray(bytes((20, 40, 80, 255)) * (width * height))
    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 4
            frame[idx] = (x * 7) % 256
            frame[idx + 1] = (y * 11) % 256
            frame[idx + 2] = ((x + y) * 5) % 256
    source.write_bytes(bytes(frame))

    assert (
        reverie.main(
            [
                "--input",
                str(source),
                "--output",
                str(output),
                "--meta",
                str(meta),
                "--width",
                str(width),
                "--height",
                str(height),
                "--drift-game-data",
                str(game_data),
                "--once",
            ]
        )
        == 0
    )

    assert output.read_bytes() != bytes(frame)
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["drift_renderer"] == "quake-media-drift-v1"
    assert payload["drift_enabled"] is True
    assert payload["drift_receiver"] == "reverie:w05"
    assert payload["drift_changed"] is True
    assert payload["source_fresh"] is True
