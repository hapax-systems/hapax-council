"""Tests for ``scripts/compare-preset-variety.py`` — preset-variety Phase 9.

Pins the comparator math against synthesized baseline + post-deploy
JSONs so future drift in threshold semantics is caught at PR time.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "compare-preset-variety.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("_compare_preset_variety", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_compute_findings_all_pass() -> None:
    cmp_mod = _load_script_module()
    baseline = {
        "preset_family_entropy_bits": 0.0,
        "colorgrade_halftone_ratio": 30.0,
        "recent_10_cosine_min_distance_mean": 0.20,
    }
    post = {
        "preset_family_entropy_bits": 1.6,
        "colorgrade_halftone_ratio": 8.0,
        "recent_10_cosine_min_distance_mean": 0.45,
    }
    findings = cmp_mod.compute_findings(baseline, post)
    assert findings["summary"]["passing"] == 3
    assert findings["summary"]["failing"] == 0
    assert findings["summary"]["no_data"] == 0


def test_compute_findings_partial_fail() -> None:
    cmp_mod = _load_script_module()
    baseline = {
        "preset_family_entropy_bits": 0.0,
        "colorgrade_halftone_ratio": 30.0,
        "recent_10_cosine_min_distance_mean": 0.20,
    }
    post = {
        "preset_family_entropy_bits": 0.5,  # below 1.5 → FAIL
        "colorgrade_halftone_ratio": 5.0,
        "recent_10_cosine_min_distance_mean": 0.45,
    }
    findings = cmp_mod.compute_findings(baseline, post)
    assert findings["summary"]["passing"] == 2
    assert findings["summary"]["failing"] == 1


def test_compute_findings_na_yields_no_data() -> None:
    cmp_mod = _load_script_module()
    baseline = {
        "preset_family_entropy_bits": 0.0,
        "colorgrade_halftone_ratio": "NA",
        "recent_10_cosine_min_distance_mean": "NA",
    }
    post = {
        "preset_family_entropy_bits": 1.6,
        "colorgrade_halftone_ratio": "NA",
        "recent_10_cosine_min_distance_mean": "NA",
    }
    findings = cmp_mod.compute_findings(baseline, post)
    assert findings["summary"]["passing"] == 1
    assert findings["summary"]["no_data"] == 2


def test_direction_down_metric_inverted() -> None:
    """`colorgrade_halftone_ratio` is a 'down' metric — lower wins."""
    cmp_mod = _load_script_module()
    baseline = {"colorgrade_halftone_ratio": 30.0}
    post = {"colorgrade_halftone_ratio": 5.0}
    findings = cmp_mod.compute_findings(baseline, post)
    halftone_row = next(r for r in findings["rows"] if r["metric"] == "colorgrade_halftone_ratio")
    assert halftone_row["verdict"] == "PASS"
    baseline2 = {"recent_10_cosine_min_distance_mean": 0.20}
    post2 = {"recent_10_cosine_min_distance_mean": 0.10}
    findings2 = cmp_mod.compute_findings(baseline2, post2)
    rec_row = next(
        r for r in findings2["rows"] if r["metric"] == "recent_10_cosine_min_distance_mean"
    )
    assert rec_row["verdict"] == "FAIL"


def test_delta_renders_with_sign() -> None:
    cmp_mod = _load_script_module()
    findings = cmp_mod.compute_findings(
        {"preset_family_entropy_bits": 0.5}, {"preset_family_entropy_bits": 1.7}
    )
    row = findings["rows"][0]
    assert row["delta"].startswith("+")


def test_delta_dash_when_either_value_non_numeric() -> None:
    cmp_mod = _load_script_module()
    findings = cmp_mod.compute_findings(
        {"preset_family_entropy_bits": "NA"}, {"preset_family_entropy_bits": 1.0}
    )
    row = findings["rows"][0]
    assert row["delta"] == "-"


def test_render_table_has_header_and_summary() -> None:
    cmp_mod = _load_script_module()
    findings = cmp_mod.compute_findings({}, {})
    table = cmp_mod.render_table(findings)
    assert "metric" in table
    assert "verdict" in table
    assert "summary:" in table
    assert "0 pass" in table
