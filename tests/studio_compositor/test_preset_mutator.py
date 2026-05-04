"""Tests for preset_mutator — Phase 1 of the preset variety expansion epic.

Spec: ``docs/superpowers/specs/2026-04-18-preset-variety-expansion-design.md``.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from random import Random
from unittest import mock

import pytest

from agents.studio_compositor import preset_family_selector as pfs
from agents.studio_compositor.preset_mutator import (
    DEFAULT_VARIANCE,
    FEATURE_FLAG_ENV,
    mutate_preset,
    variety_enabled,
)

PRESET_DIR = Path(__file__).parent.parent.parent / "presets"


def _sample_preset() -> dict:
    """Load feedback_preset.json — a representative multi-node graph."""
    return json.loads((PRESET_DIR / "feedback_preset.json").read_text())


class TestStructuralPreservation:
    def test_node_count_unchanged(self):
        preset = _sample_preset()
        mutated = mutate_preset(preset, seed=42)
        assert set(mutated["nodes"].keys()) == set(preset["nodes"].keys())

    def test_edge_count_and_order_unchanged(self):
        preset = _sample_preset()
        mutated = mutate_preset(preset, seed=42)
        assert mutated["edges"] == preset["edges"]

    def test_node_types_unchanged(self):
        preset = _sample_preset()
        mutated = mutate_preset(preset, seed=42)
        for name, node in preset["nodes"].items():
            assert mutated["nodes"][name]["type"] == node["type"]

    def test_returns_new_object_not_in_place(self):
        preset = _sample_preset()
        baseline = copy.deepcopy(preset)
        mutated = mutate_preset(preset, seed=1)
        assert preset == baseline
        assert mutated is not preset

    def test_top_level_keys_preserved(self):
        preset = _sample_preset()
        mutated = mutate_preset(preset, seed=1)
        assert set(mutated.keys()) == set(preset.keys())
        assert mutated["name"] == preset["name"]
        assert mutated["description"] == preset["description"]

    def test_modulations_preserved(self):
        preset = _sample_preset()
        mutated = mutate_preset(preset, seed=1)
        assert mutated["modulations"] == preset["modulations"]


class TestNumericJitterBounds:
    def test_floats_within_variance(self):
        preset = _sample_preset()
        variance = 0.15
        mutated = mutate_preset(preset, seed=123, variance=variance)
        for name, node in preset["nodes"].items():
            for param, val in node["params"].items():
                if not isinstance(val, (int, float)) or isinstance(val, bool):
                    continue
                if val == 0:
                    continue
                new_val = mutated["nodes"][name]["params"][param]
                lo = val * (1.0 - variance) - 1.0
                hi = val * (1.0 + variance) + 1.0
                assert lo <= new_val <= hi, (
                    f"{name}.{param}: {val} -> {new_val} outside [{lo}, {hi}]"
                )

    def test_15_percent_variance_bounds_across_many_seeds(self):
        preset = _sample_preset()
        for seed in range(200):
            mutated = mutate_preset(preset, seed=seed, variance=0.15)
            for name, node in preset["nodes"].items():
                for param, val in node["params"].items():
                    if not isinstance(val, (int, float)) or isinstance(val, bool):
                        continue
                    if val == 0:
                        continue
                    new_val = mutated["nodes"][name]["params"][param]
                    if isinstance(val, int):
                        slack = 1.0
                    else:
                        slack = 1e-9
                    assert abs(new_val - val) <= abs(val) * 0.15 + slack

    def test_zero_values_unchanged(self):
        preset = {"nodes": {"n": {"type": "x", "params": {"z": 0, "zf": 0.0}}}, "edges": []}
        mutated = mutate_preset(preset, seed=7, variance=0.5)
        assert mutated["nodes"]["n"]["params"]["z"] == 0
        assert mutated["nodes"]["n"]["params"]["zf"] == 0.0

    def test_integer_stays_integer(self):
        preset = {
            "nodes": {"bloom": {"type": "bloom", "params": {"radius": 20}}},
            "edges": [],
        }
        mutated = mutate_preset(preset, seed=1)
        assert isinstance(mutated["nodes"]["bloom"]["params"]["radius"], int)

    def test_float_stays_float(self):
        preset = {
            "nodes": {"bloom": {"type": "bloom", "params": {"alpha": 0.7}}},
            "edges": [],
        }
        mutated = mutate_preset(preset, seed=1)
        assert isinstance(mutated["nodes"]["bloom"]["params"]["alpha"], float)


class TestNonNumericPassthrough:
    def test_string_params_unchanged(self):
        preset = _sample_preset()
        mutated = mutate_preset(preset, seed=9)
        assert (
            mutated["nodes"]["trail"]["params"]["blend_mode"]
            == preset["nodes"]["trail"]["params"]["blend_mode"]
        )

    def test_bool_params_unchanged(self):
        preset = {
            "nodes": {
                "n": {
                    "type": "x",
                    "params": {"enabled": True, "hidden": False, "mix": 0.5},
                }
            },
            "edges": [],
        }
        mutated = mutate_preset(preset, seed=1)
        assert mutated["nodes"]["n"]["params"]["enabled"] is True
        assert mutated["nodes"]["n"]["params"]["hidden"] is False
        assert mutated["nodes"]["n"]["params"]["mix"] != 0.5

    def test_nested_dict_params_recurse(self):
        preset = {
            "nodes": {
                "n": {
                    "type": "x",
                    "params": {
                        "wrapped": {"sub_numeric": 2.0, "sub_label": "mode-a"},
                    },
                }
            },
            "edges": [],
        }
        mutated = mutate_preset(preset, seed=1, variance=0.15)
        nested = mutated["nodes"]["n"]["params"]["wrapped"]
        assert nested["sub_label"] == "mode-a"
        assert nested["sub_numeric"] != 2.0
        assert 1.7 <= nested["sub_numeric"] <= 2.3

    def test_list_params_deep_copied_unchanged(self):
        preset = {
            "nodes": {"n": {"type": "x", "params": {"palette": [0.1, 0.2, 0.3]}}},
            "edges": [],
        }
        mutated = mutate_preset(preset, seed=1)
        assert mutated["nodes"]["n"]["params"]["palette"] == [0.1, 0.2, 0.3]
        preset["nodes"]["n"]["params"]["palette"].append(0.4)
        assert mutated["nodes"]["n"]["params"]["palette"] == [0.1, 0.2, 0.3]


class TestDeterminism:
    def test_same_seed_produces_identical_output(self):
        preset = _sample_preset()
        a = mutate_preset(preset, seed=42)
        b = mutate_preset(preset, seed=42)
        assert a == b

    def test_different_seeds_produce_different_output(self):
        preset = _sample_preset()
        a = mutate_preset(preset, seed=1)
        b = mutate_preset(preset, seed=2)
        assert a != b

    def test_explicit_rng_overrides_seed_kwarg(self):
        preset = _sample_preset()
        rng = Random(99)
        a = mutate_preset(preset, rng=rng)
        b = mutate_preset(preset, seed=99)
        assert a == b

    def test_zero_variance_returns_deep_copy_equal_to_input(self):
        preset = _sample_preset()
        mutated = mutate_preset(preset, seed=1, variance=0.0)
        assert mutated == preset
        assert mutated is not preset


class TestFeatureFlag:
    def test_default_enabled(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(FEATURE_FLAG_ENV, None)
            assert variety_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "False", "no", "off", "  OFF  "])
    def test_disabled_values(self, val):
        with mock.patch.dict(os.environ, {FEATURE_FLAG_ENV: val}):
            assert variety_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "on", "yes", ""])
    def test_enabled_values(self, val):
        with mock.patch.dict(os.environ, {FEATURE_FLAG_ENV: val}):
            assert variety_enabled() is True


class TestPickAndLoadMutated:
    def setup_method(self):
        pfs.reset_memory()

    def teardown_method(self):
        pfs.reset_memory()

    def test_returns_name_and_graph_dict(self):
        hit = pfs.pick_and_load_mutated("audio-reactive", seed=5)
        assert hit is not None
        name, graph = hit
        assert name in pfs.presets_for_family("audio-reactive")
        assert isinstance(graph, dict)
        # Two preset shapes are supported by mutate_preset (see
        # agents/studio_compositor/preset_mutator.py:116-118): legacy
        # ``{nodes: dict, edges: [...]}`` and modern audit-pool
        # ``{nodes: dict, lineage: ...}`` (no edges, audit pools
        # 2026-05-03). Accept either; the mutator iterates nodes either
        # way.
        assert "nodes" in graph

    def test_returns_none_on_unknown_family(self):
        assert pfs.pick_and_load_mutated("nonexistent-family") is None

    def test_mutate_false_preserves_raw_preset(self):
        hit = pfs.pick_and_load_mutated(
            "audio-reactive",
            available=["feedback_preset"],
            seed=5,
            mutate=False,
        )
        assert hit is not None
        _, graph = hit
        raw = json.loads((PRESET_DIR / "feedback_preset.json").read_text())
        assert graph == raw

    def test_mutate_true_diverges_from_raw(self):
        hit = pfs.pick_and_load_mutated(
            "audio-reactive",
            available=["feedback_preset"],
            seed=5,
            mutate=True,
        )
        assert hit is not None
        _, graph = hit
        raw = json.loads((PRESET_DIR / "feedback_preset.json").read_text())
        assert graph != raw

    def test_feature_flag_disables_mutation(self):
        with mock.patch.dict(os.environ, {FEATURE_FLAG_ENV: "0"}):
            hit = pfs.pick_and_load_mutated(
                "audio-reactive",
                available=["feedback_preset"],
                seed=5,
            )
        assert hit is not None
        _, graph = hit
        raw = json.loads((PRESET_DIR / "feedback_preset.json").read_text())
        assert graph == raw

    def test_same_seed_same_family_same_available_deterministic(self):
        pfs.reset_memory()
        hit_a = pfs.pick_and_load_mutated(
            "audio-reactive",
            available=["feedback_preset"],
            seed=7,
        )
        pfs.reset_memory()
        hit_b = pfs.pick_and_load_mutated(
            "audio-reactive",
            available=["feedback_preset"],
            seed=7,
        )
        assert hit_a == hit_b


def test_default_variance_is_30_percent():
    # Widened from 0.15 → 0.30 on 2026-05-03 (visual-monoculture
    # rebalance). Pairs with the family-weight rebalance in
    # `shared/visual_mode_bias.py` to break up monoculture without
    # preset-corpus changes.
    assert DEFAULT_VARIANCE == 0.30
