"""Regression pins for the HARDM retirement (GEAL Phase 0).

Spec: docs/superpowers/specs/2026-04-23-geal-spec.md §12.
Plan: docs/superpowers/plans/2026-04-23-geal-plan.md Phase 0 Task 0.1.

HARDM was retired 2026-04-23 and superseded by GEAL (the Grounding
Expression Anchoring Layer extending the Sierpinski triangle directly
rather than via a separate dot-matrix grid). These tests pin the
retirement so HARDM code cannot regress back into the active codebase.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestHardmSourceRetired:
    def test_hardm_source_file_is_moved_to_retired(self):
        active = REPO_ROOT / "agents" / "studio_compositor" / "hardm_source.py"
        retired = REPO_ROOT / "agents" / "studio_compositor" / "_retired" / "hardm_source.py"
        assert not active.exists(), "hardm_source.py still present in active compositor tree"
        assert retired.exists(), "hardm_source.py not found under _retired/"


class TestHardmNotInLayout:
    def test_hardm_ward_absent_from_default_layout(self):
        layout = json.loads(
            (REPO_ROOT / "config" / "compositor-layouts" / "default.json").read_text(
                encoding="utf-8"
            )
        )
        source_ids = {s.get("id", "") for s in layout.get("sources", [])}
        surface_ids = {s.get("id", "") for s in layout.get("surfaces", [])}
        assignments = layout.get("assignments", [])
        assert "hardm_dot_matrix" not in source_ids
        assert not any("hardm" in sid.lower() for sid in surface_ids)
        for a in assignments:
            assert "hardm" not in (a.get("source") or "").lower()
            assert "hardm" not in (a.get("surface") or "").lower()


class TestHardmNotInZPlaneDefaults:
    def test_z_plane_defaults_has_no_hardm(self):
        from agents.studio_compositor.z_plane_constants import WARD_Z_PLANE_DEFAULTS

        assert "hardm_dot_matrix" not in WARD_Z_PLANE_DEFAULTS


class TestHardmNotInCompositorSource:
    """No active compositor source imports or references HARDM.

    Comments in *_retired/* files are exempt. The regex-style checks
    below scan *.py in the active ``agents/studio_compositor/`` tree
    for ``hardm`` tokens. Docstrings / comments mentioning HARDM as
    historical context are allowed; imports / class instantiation are
    not.
    """

    _ACTIVE_DIR = REPO_ROOT / "agents" / "studio_compositor"

    def _active_python_files(self):
        files = []
        for p in self._ACTIVE_DIR.rglob("*.py"):
            if "_retired" in p.parts:
                continue
            files.append(p)
        return files

    def test_no_hardm_imports(self):
        pat = re.compile(
            r"\bfrom\s+agents\.studio_compositor\.hardm_source\b|\bimport\s+hardm_source\b|\bimport\s+\.hardm_source\b"
        )
        offenders = []
        for p in self._active_python_files():
            if p.name == "test_hardm_retired.py":
                continue
            text = p.read_text(encoding="utf-8")
            if pat.search(text):
                offenders.append(str(p.relative_to(REPO_ROOT)))
        assert offenders == [], f"HARDM imports still present: {offenders}"

    def test_no_hardmsource_class_instantiation(self):
        pat = re.compile(r"\bHardmSource\b|\bHardmCairoSource\b")
        offenders = []
        for p in self._active_python_files():
            if p.name == "test_hardm_retired.py":
                continue
            text = p.read_text(encoding="utf-8")
            if pat.search(text):
                offenders.append(str(p.relative_to(REPO_ROOT)))
        assert offenders == [], f"HARDM class references still present: {offenders}"


class TestHardmNotInWardLists:
    """HARDM ward id must not appear in any active ward enumeration."""

    _ACTIVE_DIR = REPO_ROOT / "agents" / "studio_compositor"

    def test_no_hardm_in_active_ward_lists(self):
        # Look for the bare token ``"hardm_dot_matrix"`` in Python
        # string literals — indicates an active ward-list entry.
        pat = re.compile(r'"hardm_dot_matrix"')
        offenders = []
        for p in self._ACTIVE_DIR.rglob("*.py"):
            if "_retired" in p.parts or p.name == "test_hardm_retired.py":
                continue
            text = p.read_text(encoding="utf-8")
            if pat.search(text):
                offenders.append(str(p.relative_to(REPO_ROOT)))
        assert offenders == [], f"HARDM ward-id literals still present: {offenders}"
