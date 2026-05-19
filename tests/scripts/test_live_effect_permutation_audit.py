from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    script = Path(__file__).resolve().parents[2] / "scripts/live-effect-permutation-audit.py"
    spec = importlib.util.spec_from_file_location("live_effect_permutation_audit", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_canonical_effect_node_id_strips_slotdrift_prefix_without_losing_underscores():
    module = _load_module()

    assert module.canonical_effect_node_id("slot0_2_chromatic_aberration") == "chromatic_aberration"
    assert module.canonical_effect_node_id("slot14_3_noise_overlay") == "noise_overlay"
    assert module.canonical_effect_node_id("color_map") == "color_map"
    assert module.canonical_effect_node_id("fb") == "fb"


def test_observed_nodes_are_canonical_but_lineage_preserves_generated_ids(tmp_path):
    module = _load_module()
    state_path = tmp_path / "effect-drift-state.json"
    state_path.write_text(
        json.dumps(
            {
                "passes": [
                    {"node_id": "slot0_0_chromatic_aberration"},
                    {"node_id": "slot0_1_noise_overlay"},
                    {"node_id": "slot1_0_noise_overlay"},
                    {"node_id": "fb"},
                    {"node_id": "post"},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert module.observed_nodes_from_effect_state_file(state_path) == {
        "chromatic_aberration",
        "noise_overlay",
    }
    assert module.observed_node_lineage_from_effect_state_file(state_path) == {
        "chromatic_aberration": {"slot0_0_chromatic_aberration"},
        "noise_overlay": {"slot0_1_noise_overlay", "slot1_0_noise_overlay"},
    }


def test_canonical_effect_node_ids_still_expose_missing_requested_shader():
    module = _load_module()
    allowed = {"chromatic_aberration", "color_map", "fb", "post"}
    raw_plan_nodes = [
        "slot0_0_chromatic_aberration",
        "slot0_1_threshold",
        "post",
    ]

    canonical = {module.canonical_effect_node_id(node_id) for node_id in raw_plan_nodes}

    assert "chromatic_aberration" in canonical
    assert "threshold" in canonical
    assert not canonical.issubset(allowed)


def test_plan_constraint_uses_slot_anchor_not_every_generated_support_node():
    module = _load_module()
    passes = [
        {
            "node_id": "slot0_0_halftone",
            "graph_motif": "halftone",
            "slot_index": 0,
        },
        {
            "node_id": "slot0_1_palette",
            "graph_motif": "halftone",
            "slot_index": 0,
        },
        {
            "node_id": "slot1_0_color_map",
            "graph_motif": "color_map",
            "slot_index": 1,
        },
        {"node_id": "fb"},
        {"node_id": "post"},
    ]

    anchors = module.plan_anchor_ids_from_passes(passes)

    assert anchors == {"halftone", "color_map"}
    assert anchors.issubset({"halftone", "color_map"})
