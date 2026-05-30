from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "screwm-imagination-source-publisher.py"


def _load_publisher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("screwm_imagination_source_publisher", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_downsample_converts_bgra_to_rgba() -> None:
    publisher = _load_publisher()
    bgra = bytes(
        [
            10,
            20,
            30,
            255,
            40,
            50,
            60,
            255,
            70,
            80,
            90,
            255,
            100,
            110,
            120,
            255,
        ]
    )

    assert publisher._downsample_bgra_to_rgba(bgra, 2, 2, 1, 1) == bytes([30, 20, 10, 255])


def test_publish_once_writes_imagination_source_protocol(tmp_path: Path) -> None:
    publisher = _load_publisher()
    input_dir = tmp_path / "compositor"
    output_dir = tmp_path / "sources"
    input_dir.mkdir()
    role = "brio-operator"
    frame = bytes([10, 20, 30, 255] * 16)
    (input_dir / f"quake-live-cam-{role}.bgra").write_bytes(frame)
    (input_dir / f"quake-live-cam-{role}.json").write_text(
        json.dumps({"width": 4, "height": 4, "fps": 5}),
        encoding="utf-8",
    )

    published = publisher.publish_once(
        input_dir=input_dir,
        output_dir=output_dir,
        roles=(role,),
        width=2,
        height=2,
        sequence=7,
    )

    assert published == 1
    source_dir = output_dir / "screwm-quake-camera-brio-operator"
    assert (source_dir / "frame.rgba").read_bytes() == bytes([30, 20, 10, 255] * 4)
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_id"] == "screwm-quake-camera-brio-operator"
    assert manifest["content_type"] == "rgba"
    assert manifest["width"] == 2
    assert manifest["height"] == 2
    assert manifest["ttl_ms"] == 3000
    assert manifest["frame_sequence"] == 7
    assert "source-presence" in manifest["tags"]
    assert "camera-snapshot" in manifest["tags"]
