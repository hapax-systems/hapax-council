"""Tests for scripts/measure-preset-variety-baseline.py — preset-variety Phase 1.

Verifies:
  - shannon_entropy correctness on uniform / monoculture / mixed distributions
  - load_jsonl_window respects the time cutoff
  - load_jsonl_window handles missing file / malformed lines / non-dict records
  - family_histogram counts preset_family_hint per record
  - preset_bias_impingement_count counts only intent_family="preset.bias" entries
  - material_histogram counts material from preset.bias impingements only
  - build_baseline emits the documented JSON shape
  - build_baseline marks per-preset/cosine fields as NA when recruitment log absent
  - write_baseline produces atomic .json file (tmp+rename)
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "measure-preset-variety-baseline.py"
spec = importlib.util.spec_from_file_location("measure_preset_variety_baseline", SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules["measure_preset_variety_baseline"] = mod
spec.loader.exec_module(mod)


# ── shannon_entropy ───────────────────────────────────────────────────


class TestShannonEntropy:
    def test_empty_distribution_zero(self) -> None:
        assert mod.shannon_entropy(Counter()) == 0.0

    def test_monoculture_zero(self) -> None:
        """One non-zero value → entropy 0 (perfect predictability)."""
        assert mod.shannon_entropy(Counter({"calm-textural": 100})) == 0.0

    def test_uniform_two_classes_one_bit(self) -> None:
        result = mod.shannon_entropy(Counter({"a": 50, "b": 50}))
        assert math.isclose(result, 1.0, abs_tol=1e-9)

    def test_uniform_four_classes_two_bits(self) -> None:
        result = mod.shannon_entropy(Counter({"a": 25, "b": 25, "c": 25, "d": 25}))
        assert math.isclose(result, 2.0, abs_tol=1e-9)

    def test_skewed_distribution(self) -> None:
        result = mod.shannon_entropy(Counter({"a": 90, "b": 10}))
        # H = -(0.9 log2 0.9 + 0.1 log2 0.1) ≈ 0.469
        assert 0.4 < result < 0.5


# ── load_jsonl_window ────────────────────────────────────────────────


class TestLoadJsonlWindow:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = mod.load_jsonl_window(tmp_path / "nope.jsonl", now=1000.0, window_s=60.0)
        assert result == []

    def test_filters_by_timestamp(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        records = [
            {"emitted_at": 100.0, "v": "old"},
            {"emitted_at": 950.0, "v": "in-window"},
            {"emitted_at": 999.0, "v": "fresh"},
        ]
        path.write_text("\n".join(json.dumps(r) for r in records))
        result = mod.load_jsonl_window(path, now=1000.0, window_s=100.0)
        assert [r["v"] for r in result] == ["in-window", "fresh"]

    def test_records_without_timestamp_included(self, tmp_path: Path) -> None:
        """A record missing every recognised timestamp field is kept —
        non-timestamped logs aren't excluded."""
        path = tmp_path / "log.jsonl"
        path.write_text(json.dumps({"v": "no-ts"}))
        result = mod.load_jsonl_window(path, now=1000.0, window_s=10.0)
        assert len(result) == 1

    def test_malformed_line_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        path.write_text(
            json.dumps({"v": "good"}) + "\n{not valid json\n" + json.dumps({"v": "also good"})
        )
        result = mod.load_jsonl_window(path, now=1000.0, window_s=10.0)
        assert [r["v"] for r in result] == ["good", "also good"]

    def test_non_dict_record_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        path.write_text("[1, 2, 3]\n" + json.dumps({"v": "ok"}))
        result = mod.load_jsonl_window(path, now=1000.0, window_s=10.0)
        assert result == [{"v": "ok"}]


# ── family_histogram ─────────────────────────────────────────────────


class TestFamilyHistogram:
    def test_counts_preset_family_hint(self) -> None:
        records = [
            {"preset_family_hint": "calm-textural"},
            {"preset_family_hint": "calm-textural"},
            {"preset_family_hint": "glitch-dense"},
        ]
        hist = mod.family_histogram(records)
        assert hist == Counter({"calm-textural": 2, "glitch-dense": 1})

    def test_missing_or_invalid_family_skipped(self) -> None:
        records = [
            {"preset_family_hint": "audio-reactive"},
            {"preset_family_hint": ""},
            {"preset_family_hint": None},
            {},
        ]
        hist = mod.family_histogram(records)
        assert hist == Counter({"audio-reactive": 1})


# ── preset.bias impingement counts ───────────────────────────────────


class TestPresetBiasCount:
    def test_counts_preset_bias_only(self) -> None:
        records = [
            {
                "compositional_impingements": [
                    {"intent_family": "preset.bias"},
                    {"intent_family": "overlay.emphasis"},
                    {"intent_family": "preset.bias"},
                ]
            },
            {"compositional_impingements": [{"intent_family": "ward.size"}]},
            {},  # no compositional_impingements
        ]
        assert mod.preset_bias_impingement_count(records) == 2

    def test_handles_non_list_field(self) -> None:
        records = [{"compositional_impingements": "not a list"}]
        assert mod.preset_bias_impingement_count(records) == 0


class TestMaterialHistogram:
    def test_counts_material_from_preset_bias_only(self) -> None:
        records = [
            {
                "compositional_impingements": [
                    {"intent_family": "preset.bias", "material": "water"},
                    {"intent_family": "overlay.emphasis", "material": "fire"},
                    {"intent_family": "preset.bias", "material": "void"},
                    {"intent_family": "preset.bias", "material": "water"},
                ]
            }
        ]
        assert mod.material_histogram(records) == Counter({"water": 2, "void": 1})


# ── build_baseline ───────────────────────────────────────────────────


class TestBuildBaseline:
    def test_emits_documented_shape(self, tmp_path: Path) -> None:
        structural = tmp_path / "structural.jsonl"
        director = tmp_path / "director.jsonl"
        recruitment = tmp_path / "recruitment-not-present.jsonl"
        structural.write_text(
            json.dumps({"emitted_at": 1000.0, "preset_family_hint": "calm-textural"})
            + "\n"
            + json.dumps({"emitted_at": 1000.0, "preset_family_hint": "warm-minimal"})
        )
        director.write_text(
            json.dumps(
                {
                    "emitted_at": 1000.0,
                    "compositional_impingements": [
                        {"intent_family": "preset.bias", "material": "fire"}
                    ],
                }
            )
        )
        baseline = mod.build_baseline(
            structural_log=structural,
            director_log=director,
            recruitment_log=recruitment,
            window_s=10.0,
            now=1005.0,
        )
        assert baseline["schema_version"] == 1
        assert baseline["structural_intent_records"] == 2
        assert baseline["director_intent_records"] == 1
        assert baseline["preset_bias_impingements"] == 1
        assert baseline["preset_family_histogram"] == {"calm-textural": 1, "warm-minimal": 1}
        # Two-class uniform → 1.0 bit
        assert math.isclose(baseline["preset_family_entropy_bits"], 1.0, abs_tol=1e-9)
        assert baseline["material_histogram"] == {"fire": 1}
        assert baseline["recruitment_log_present"] is False
        assert baseline["per_preset_activation_count"] == "NA"

    def test_recruitment_log_present_emits_per_preset_count(self, tmp_path: Path) -> None:
        """When recruitment-log.jsonl exists, per_preset_activation_count
        is computed from the log records (not NA)."""
        recruitment = tmp_path / "recruitment.jsonl"
        recruitment.write_text(
            json.dumps({"timestamp": 1000.0, "capability_name": "fx.family.calm-textural"})
            + "\n"
            + json.dumps({"timestamp": 1001.0, "capability_name": "fx.family.calm-textural"})
            + "\n"
            + json.dumps({"timestamp": 1002.0, "capability_name": "node.colorgrade"})
        )
        baseline = mod.build_baseline(
            structural_log=tmp_path / "missing-s.jsonl",
            director_log=tmp_path / "missing-d.jsonl",
            recruitment_log=recruitment,
            window_s=60.0,
            now=1010.0,
        )
        assert baseline["recruitment_log_present"] is True
        assert baseline["recruitment_records"] == 3
        assert baseline["per_preset_activation_count"] == {
            "fx.family.calm-textural": 2,
            "node.colorgrade": 1,
        }


# ── per_preset_activation_count + colorgrade_halftone_ratio ──────────


class TestPerPresetActivationCount:
    def test_counts_capability_name_field(self) -> None:
        records = [
            {"capability_name": "node.colorgrade"},
            {"capability_name": "node.colorgrade"},
            {"capability_name": "fx.family.glitch-dense"},
        ]
        result = mod.per_preset_activation_count(records)
        assert result == Counter({"node.colorgrade": 2, "fx.family.glitch-dense": 1})

    def test_skips_records_without_name(self) -> None:
        records = [
            {"capability_name": "x"},
            {"timestamp": 1.0},  # no capability_name
            {"capability_name": ""},  # empty string
            {"capability_name": None},  # not a string
        ]
        result = mod.per_preset_activation_count(records)
        assert result == Counter({"x": 1})


class TestColorgradeHalftoneRatio:
    def test_ratio_when_both_present(self) -> None:
        per_preset = Counter({"node.colorgrade": 30, "node.halftone": 5})
        assert mod.colorgrade_halftone_ratio(per_preset) == 6.0

    def test_inf_string_when_halftone_zero(self) -> None:
        per_preset = Counter({"node.colorgrade": 30})
        assert mod.colorgrade_halftone_ratio(per_preset) == "INF"

    def test_na_when_neither_present(self) -> None:
        per_preset = Counter({"node.drift": 5})
        assert mod.colorgrade_halftone_ratio(per_preset) == "NA"

    def test_substring_match_picks_up_qualified_names(self) -> None:
        """`node.colorgrade.x` and `node.halftone.y` count too."""
        per_preset = Counter({"node.colorgrade.warm": 10, "node.halftone.fast": 2})
        assert mod.colorgrade_halftone_ratio(per_preset) == 5.0


# ── write_baseline ──────────────────────────────────────────────────


class TestWriteBaseline:
    def test_writes_pretty_json_with_trailing_newline(self, tmp_path: Path) -> None:
        out = tmp_path / "baseline.json"
        mod.write_baseline({"schema_version": 1, "x": 42}, out)
        text = out.read_text()
        assert text.endswith("\n")
        # Pretty-printed (sort_keys + indent=2) → "schema_version" sorts before "x"
        assert text.startswith('{\n  "schema_version"')

    def test_atomic_via_tmp_rename(self, tmp_path: Path) -> None:
        out = tmp_path / "baseline.json"
        mod.write_baseline({"schema_version": 1}, out)
        assert out.exists()
        assert not out.with_suffix(".json.tmp").exists()

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        out = tmp_path / "subdir" / "deeper" / "baseline.json"
        mod.write_baseline({"schema_version": 1}, out)
        assert out.exists()
