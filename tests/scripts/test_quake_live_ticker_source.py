from __future__ import annotations

import json
import runpy
from argparse import Namespace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module() -> dict:
    return runpy.run_path(
        str(REPO_ROOT / "scripts" / "quake-live-ticker-source.py"), run_name="__test__"
    )


def _pixel_bgra(frame: bytes, width: int, x: int, y: int) -> tuple[int, int, int, int]:
    offset = (y * width + x) * 4
    return tuple(frame[offset : offset + 4])


def test_grounding_rows_filters_synthetic_markers() -> None:
    module = _load_module()

    rows = module["_grounding_rows"](
        {
            "grounding_provenance": [
                "fallback.parser_json_decode, visual.scene_type",
                "audio.album.current_track",
                ".internal.marker",
            ]
        }
    )

    assert rows == ["visual.scene_type", "audio.album.current_track"]


def test_ticker_rows_are_role_specific() -> None:
    module = _load_module()
    intent = {
        "activity": "react",
        "stance": "seeking",
        "grounding_provenance": ["context.active_objective_ids"],
        "structural_intent": {
            "homage_rotation_mode": "weighted_by_salience",
            "ward_emphasis": ["activity_header", "grounding_provenance_ticker"],
            "ward_dispatch": ["precedent_ticker"],
        },
        "compositional_impingements": [
            {"intent_family": "transition.cut", "material": "fire", "salience": 0.8}
        ],
        "narrative_text": "Hold the source material while the operator inspects the room.",
    }

    assert module["_ticker_rows"](intent, "grounding") == ["context.active_objective_ids"]
    assert module["_ticker_rows"](intent, "precedent") == [
        "ward emphasis: activity_header / grounding_provenance_ticker",
        "homage rotation: weighted_by_salience",
        "dispatch: precedent_ticker",
    ]
    assert module["_ticker_rows"](intent, "chronicle") == [
        "activity: react / stance: seeking",
        "fire: transition.cut salience 0.80",
        "Hold the source material while the operator inspects the room.",
    ]


def test_cairo_pango_ticker_frame_is_bgra_texture_sized() -> None:
    module = _load_module()

    frame = module["render_ticker_frame"](
        width=1344,
        height=176,
        role="grounding",
        rows=["visual.scene_type", "audio.album.current_track"],
        now=1000.0,
    )

    assert len(frame) == 1344 * 176 * 4
    assert len(set(frame)) > 8
    assert _pixel_bgra(frame, 1344, 2, 2) == (12, 6, 4, 255)
    assert _pixel_bgra(frame, 1344, 1341, 2) == (12, 6, 4, 255)


def test_ticker_preflip_y_reverses_bgra_rows() -> None:
    module = _load_module()
    row0 = bytes([1, 2, 3, 4]) * 2
    row1 = bytes([5, 6, 7, 8]) * 2

    assert module["_flip_bgra_y"](row0 + row1, 2, 2) == row1 + row0


def test_ticker_metadata_records_renderer(tmp_path: Path) -> None:
    module = _load_module()
    args = Namespace(
        ticker_role="grounding",
        intent_path=tmp_path / "intent.jsonl",
        output=tmp_path / "ticker.bgra",
        width=1344,
        height=176,
        fps=8,
        preflip_y="1",
    )
    meta = tmp_path / "meta.json"

    module["_write_meta"](meta, args, 3, 2)
    payload = json.loads(meta.read_text(encoding="utf-8"))

    assert payload["renderer"] == "cairo-pango"
    assert payload["pixel_format"] == "BGRA8888"
    assert payload["preflip_y"] is True
    assert payload["width"] == 1344
    assert payload["height"] == 176


def test_ticker_gpu_drift_writes_raw_handoff_without_final_output(tmp_path: Path) -> None:
    module = _load_module()
    intent = tmp_path / "intent.jsonl"
    intent.write_text(
        json.dumps({"grounding_provenance": ["visual.scene_type"]}) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "quake-live-ticker-grounding.bgra"
    meta = tmp_path / "quake-live-ticker-grounding.json"

    assert (
        module["main"](
            [
                "--ticker-role",
                "grounding",
                "--intent-path",
                str(intent),
                "--output",
                str(output),
                "--meta",
                str(meta),
                "--width",
                "96",
                "--height",
                "32",
                "--fps",
                "4",
                "--preflip-y",
                "1",
                "--gpu-drift",
                "--once",
            ]
        )
        == 0
    )

    raw_output, raw_meta = module["_gpu_drift_paths"](output)
    payload = json.loads(raw_meta.read_text(encoding="utf-8"))

    assert raw_output.read_bytes()
    assert raw_output.stat().st_size == 96 * 32 * 4
    assert not output.exists()
    assert not meta.exists()
    assert payload["gpu_drift"] is True
    assert payload["gpu_drift_raw_output"] == str(raw_output)
    assert payload["gpu_drift_final_output"] == str(output)
    assert payload["gpu_drift_output_owner"] == "screwm_media_drift"
    assert payload["drift_enabled"] is False
    assert payload["drift_receiver"] == "ticker:grounding"
    assert payload["drift_input_hash"]
    assert payload["drift_output_hash"] == ""
    assert payload["preflip_y"] is True
