"""Tests for scripts/team-metadata-probe."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = REPO_ROOT / "scripts" / "team-metadata-probe"


def _load_probe():
    loader = importlib.machinery.SourceFileLoader("team_metadata_probe_test", str(PROBE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


def test_antigrav_is_not_registered_as_live_probe_capacity() -> None:
    mod = _load_probe()
    assert "antigravity" not in mod.KNOWN_LANES
    assert "antigrav" not in mod.MODEL_DEFAULTS
    assert "antigrav" not in mod.TOOL_DEFAULTS
