"""Tests for ``scripts/audit-preset-affordances.py`` — preset-variety Phase 5.

Phase 5 of preset-variety-plan (task #166). Pins the audit math against
synthesized inputs so future drift between FAMILY_PRESETS and Qdrant can
be detected without hitting a live Qdrant.

Loaded via runpy because the script is a uv-script with no installable
package layer.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit-preset-affordances.py"


def _load_script_module():
    """Load the script as a module without executing ``main``."""
    spec = importlib.util.spec_from_file_location("_audit_preset_affordances", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_compute_findings_no_gaps() -> None:
    audit = _load_script_module()
    family_presets = {
        "audio-reactive": ("a", "b", "c", "d"),
        "calm-textural": ("e", "f", "g"),
    }
    disk_presets = {"a", "b", "c", "d", "e", "f", "g"}
    qdrant = {"fx.family.audio-reactive", "fx.family.calm-textural"}
    findings = audit.compute_findings(family_presets, disk_presets, qdrant, None)
    assert findings["A_thin_families"] == {}
    assert findings["B_family_entries_missing_on_disk"] == []
    assert findings["C_disk_presets_orphaned"] == []
    drift = findings["D_qdrant_drift"]
    assert drift["status"] == "ok"
    assert drift["in_qdrant_not_in_family_map"] == []
    assert drift["in_family_map_not_in_qdrant"] == []


def test_compute_findings_thin_family_flagged() -> None:
    audit = _load_script_module()
    family_presets = {"thin": ("a", "b"), "ok": ("c", "d", "e")}
    disk_presets = {"a", "b", "c", "d", "e"}
    findings = audit.compute_findings(family_presets, disk_presets, set(), None)
    assert "thin" in findings["A_thin_families"]
    assert "ok" not in findings["A_thin_families"]


def test_compute_findings_missing_on_disk_flagged() -> None:
    audit = _load_script_module()
    family_presets = {"f": ("a", "b", "c", "missing")}
    disk_presets = {"a", "b", "c"}
    findings = audit.compute_findings(family_presets, disk_presets, set(), None)
    assert "missing" in findings["B_family_entries_missing_on_disk"]


def test_compute_findings_orphaned_disk_flagged() -> None:
    audit = _load_script_module()
    family_presets = {"f": ("a", "b", "c")}
    disk_presets = {"a", "b", "c", "experiment_only"}
    findings = audit.compute_findings(family_presets, disk_presets, set(), None)
    assert findings["C_disk_presets_orphaned"] == ["experiment_only"]


def test_compute_findings_qdrant_drift_in_qdrant_only() -> None:
    audit = _load_script_module()
    family_presets = {"f": ("a", "b", "c")}
    qdrant = {"fx.family.f", "fx.family.legacy-only"}
    findings = audit.compute_findings(family_presets, set(), qdrant, None)
    drift = findings["D_qdrant_drift"]
    assert drift["in_qdrant_not_in_family_map"] == ["fx.family.legacy-only"]
    assert drift["in_family_map_not_in_qdrant"] == []


def test_compute_findings_qdrant_drift_missing_in_qdrant() -> None:
    audit = _load_script_module()
    family_presets = {"f": ("a",), "g": ("b",)}
    qdrant = {"fx.family.f"}
    findings = audit.compute_findings(family_presets, set(), qdrant, None)
    drift = findings["D_qdrant_drift"]
    assert drift["in_family_map_not_in_qdrant"] == ["fx.family.g"]


def test_compute_findings_qdrant_skipped() -> None:
    audit = _load_script_module()
    findings = audit.compute_findings({}, set(), None, "qdrant unreachable")
    drift = findings["D_qdrant_drift"]
    assert drift["status"] == "skipped"
    assert drift["reason"] == "qdrant unreachable"


def test_render_markdown_handles_empty_findings() -> None:
    audit = _load_script_module()
    findings = audit.compute_findings({}, set(), set(), None)
    md = audit.render_markdown(findings)
    assert "Preset affordance audit" in md
    assert "(none" in md  # at least one "none" placeholder fires


def test_render_markdown_includes_thin_family_listing() -> None:
    audit = _load_script_module()
    findings = audit.compute_findings({"thin": ("a", "b")}, {"a", "b"}, set(), None)
    md = audit.render_markdown(findings)
    assert "`thin` (2)" in md
    assert "a, b" in md


def test_disk_preset_names_excludes_underscore_prefix(tmp_path: Path) -> None:
    audit = _load_script_module()
    # Replace PRESETS_DIR with a temp dir for this test
    real_presets_dir = audit.PRESETS_DIR
    try:
        audit.PRESETS_DIR = tmp_path
        (tmp_path / "valid.json").write_text("{}")
        (tmp_path / "_metadata.json").write_text("{}")
        result = audit.disk_preset_names()
        assert result == {"valid"}
    finally:
        audit.PRESETS_DIR = real_presets_dir
