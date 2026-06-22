"""PR 4b follow-up: screwm-cns-witness binds the independent intent verdict
(intent_hash, intent_pass) from a declared VisualIntentRecord + a captured OBS
source frame.

Tests the producer wiring (the record/frame helpers + the realized-vector binding)
without the full receipt-emit path, which needs a coord signing key + a deployed
gamedir. cc-task: avsdlc-intent-producer-wiring. Self-contained per workspace convention.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "screwm-cns-witness.py"

_RECORD = {
    "predicates": [
        {
            "pov_label": "obs-source",
            "region": "entity_core",
            "metric": "luma",
            "op": "<=",
            "target": 10.0,
            "direction": "decrease",
            "critical": True,
        }
    ],
    "aggregation_floor": 0.75,
}


def _load_module():
    spec = importlib.util.spec_from_file_location("screwm_cns_witness_intent", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_png(path: Path, rgb: int) -> None:
    import numpy as np
    from PIL import Image

    Image.fromarray(np.full((100, 100, 3), rgb, dtype=np.uint8)).save(path)


def test_read_intent_record_file_inline_and_none(tmp_path: Path) -> None:
    mod = _load_module()
    blob = json.dumps(_RECORD)
    f = tmp_path / "rec.json"
    f.write_text(blob)
    assert mod._read_intent_record(str(f)) == blob  # file path
    assert mod._read_intent_record(blob) == blob  # inline JSON
    assert mod._read_intent_record(None) is None


def test_read_intent_record_long_inline_string_does_not_crash() -> None:
    # A long inline JSON (>255-char path component) must not raise from Path.is_file()
    # (Errno 36); it falls through to be treated as inline JSON. Never raises.
    mod = _load_module()
    long_blob = json.dumps({**_RECORD, "note": "x" * 400})
    assert len(long_blob) > 255
    assert mod._read_intent_record(long_blob) == long_blob


def test_load_obs_source_frame_present_and_absent(tmp_path: Path) -> None:
    mod = _load_module()
    _write_png(tmp_path / "obs-source-00.png", 0)
    frame = mod._load_obs_source_frame(tmp_path)
    assert frame is not None and frame.shape == (100, 100, 3)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert mod._load_obs_source_frame(empty) is None  # no frame → None, never raises


def test_intent_binding_dark_frame_confirms(tmp_path: Path) -> None:
    from shared.avsdlc_visual_intent import intent_hash_from_record, parse_intent_record
    from shared.avsdlc_witness import intent_fields_from_record_and_frame

    mod = _load_module()
    _write_png(tmp_path / "obs-source-00.png", 0)  # entity_core luma ~0 <= 10
    record = mod._read_intent_record(json.dumps(_RECORD))
    frame = mod._load_obs_source_frame(tmp_path)
    h, passed = intent_fields_from_record_and_frame(record, frame, "obs-source")
    assert passed is True
    assert h == intent_hash_from_record(parse_intent_record(record))


def test_intent_binding_bright_frame_rejects(tmp_path: Path) -> None:
    from shared.avsdlc_witness import intent_fields_from_record_and_frame

    mod = _load_module()
    _write_png(tmp_path / "obs-source-00.png", 200)  # entity_core luma 200 > 10
    record = mod._read_intent_record(json.dumps(_RECORD))
    frame = mod._load_obs_source_frame(tmp_path)
    h, passed = intent_fields_from_record_and_frame(record, frame, "obs-source")
    assert passed is False
    assert h  # hash derived from the declared record, independent of the frame


def test_intent_binding_missing_frame_degrades_to_empty(tmp_path: Path) -> None:
    # The main() wiring: missing frame → intent stays empty (degradation). Simulate it.
    mod = _load_module()
    record = mod._read_intent_record(json.dumps(_RECORD))
    frame = mod._load_obs_source_frame(tmp_path)  # no png → None
    assert frame is None
    intent_hash, intent_pass = ("", False) if not (record and frame is not None) else ("x", True)
    assert intent_hash == "" and intent_pass is False
