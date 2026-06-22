"""AVSDLC visual-eval — realized per-region perceptual vector (PR 4a).

Computes the REALIZED {luma, edge_energy} vector per AESTHETIC region from a
captured frame — the input shape ``shared.avsdlc_visual_intent.intent_pass``
consumes — so the independent witness can confirm a pre-authored intent against
what actually rendered. Pure + numpy; the witness wiring and the gate conjunct
are later slices. Self-contained per convention.

cc-task: avsdlc-visual-eval-realized-vector (CASE-AVSDLC-REALIZED-VECTOR-20260622).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from shared.avsdlc_realized_vector import (
    PHASE1_REGION_ROIS,
    realized_vector_from_frame,
)
from shared.avsdlc_visual_intent import intent_pass, parse_intent_record


def _roi_pixels(frame_hw, region):
    """Return the (y0,y1,x0,x1) integer slice for a region in an (H,W) frame."""
    h, w = frame_hw
    x0, y0, x1, y1 = PHASE1_REGION_ROIS[region]
    return (round(y0 * h), round(y1 * h), round(x0 * w), round(x1 * w))


class TestRealizedVector:
    def test_uniform_white_frame_high_luma_low_edge(self) -> None:
        frame = np.full((120, 200), 255, dtype=np.uint8)
        vec = realized_vector_from_frame(frame, "cam0")["cam0"]
        for region in PHASE1_REGION_ROIS:
            assert vec[region]["luma"] == 255.0
            assert vec[region]["edge_energy"] == 0.0

    def test_uniform_black_frame_low_luma(self) -> None:
        frame = np.zeros((120, 200), dtype=np.uint8)
        vec = realized_vector_from_frame(frame, "cam0")["cam0"]
        assert vec["entity_core"]["luma"] == 0.0

    def test_region_isolation(self) -> None:
        frame = np.zeros((120, 200), dtype=np.uint8)
        y0, y1, x0, x1 = _roi_pixels((120, 200), "entity_core")
        frame[y0:y1, x0:x1] = 255  # light ONLY the entity_core ROI
        vec = realized_vector_from_frame(frame, "cam0")["cam0"]
        assert vec["entity_core"]["luma"] > 250.0
        assert vec["negative_space"]["luma"] == 0.0

    def test_edges_raise_edge_energy(self) -> None:
        flat = np.full((120, 200), 128, dtype=np.uint8)
        striped = np.zeros((120, 200), dtype=np.uint8)
        striped[:, ::2] = 255  # vertical stripes -> strong horizontal gradient
        flat_e = realized_vector_from_frame(flat, "cam0")["cam0"]["entity_core"]["edge_energy"]
        striped_e = realized_vector_from_frame(striped, "cam0")["cam0"]["entity_core"][
            "edge_energy"
        ]
        assert flat_e == 0.0
        assert striped_e > flat_e

    def test_rgb_frame_luma_rec601(self) -> None:
        frame = np.zeros((120, 200, 3), dtype=np.uint8)
        frame[..., 0] = 255  # pure red
        luma = realized_vector_from_frame(frame, "cam0")["cam0"]["entity_core"]["luma"]
        assert abs(luma - 0.299 * 255) < 0.5

    def test_output_shape_and_metrics_present(self) -> None:
        vec = realized_vector_from_frame(np.zeros((60, 80), dtype=np.uint8), "pov-x")
        assert set(vec.keys()) == {"pov-x"}
        assert set(vec["pov-x"].keys()) == set(PHASE1_REGION_ROIS)
        assert set(vec["pov-x"]["floor"].keys()) == {"luma", "edge_energy"}


class TestEndToEndIntent:
    def test_white_blob_drives_intent_pass_false(self) -> None:
        # The motivating loop: the agent predicted entity_core would go near-black
        # (luma <= 10, critical); the realized frame still shows a bright blob there
        # -> the realized vector drives intent_pass False. Predict-then-confirm.
        frame = np.zeros((120, 200), dtype=np.uint8)
        y0, y1, x0, x1 = _roi_pixels((120, 200), "entity_core")
        frame[y0:y1, x0:x1] = 200  # the white blob survived
        realized = realized_vector_from_frame(frame, "cam0")
        record = parse_intent_record(
            {
                "predicates": [
                    {
                        "pov_label": "cam0",
                        "region": "entity_core",
                        "metric": "luma",
                        "op": "<=",
                        "target": 10.0,
                        "direction": "decrease",
                        "critical": True,
                    }
                ]
            }
        )
        assert intent_pass(record, realized) is False

    def test_dark_entity_core_passes_intent(self) -> None:
        frame = np.zeros((120, 200), dtype=np.uint8)  # entity_core near-black
        realized = realized_vector_from_frame(frame, "cam0")
        record = parse_intent_record(
            {
                "predicates": [
                    {
                        "pov_label": "cam0",
                        "region": "entity_core",
                        "metric": "luma",
                        "op": "<=",
                        "target": 10.0,
                        "direction": "decrease",
                        "critical": True,
                    }
                ]
            }
        )
        assert intent_pass(record, realized) is True


def test_phase1_region_rois_match_witness() -> None:
    # Drift pin: vendored ROIs must equal the witness AESTHETIC_REGIONS (names + coords).
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "screwm-effect-drift-matrix-witness.py"
    )
    text = script.read_text(encoding="utf-8")
    block = text.split("AESTHETIC_REGIONS", 1)[1].split("}", 1)[0]
    witness = {
        m.group(1): tuple(float(x) for x in m.group(2).split(","))
        for m in re.finditer(r'"([a-z_]+)":\s*\(([^)]+)\)', block)
    }
    assert witness == PHASE1_REGION_ROIS
