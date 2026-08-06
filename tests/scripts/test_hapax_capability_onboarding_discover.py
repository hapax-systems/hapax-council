"""CLI tests for hapax-capability-onboarding-discover."""

from __future__ import annotations

import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-capability-onboarding-discover"
FIXTURES = REPO_ROOT / "config" / "capability-surface-delta-fixtures.json"


def _load():
    loader = SourceFileLoader("hapax_capability_onboarding_discover_cli", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


mod = _load()


def test_cli_dry_run_fixtures_json(capsys) -> None:
    rc = mod.main(["--deltas", str(FIXTURES), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["count"] >= 1
    assert out["apply"] is False
    assert "admit_supply" not in out.get("dispositions", {})
    for item in out["results"]:
        assert item["classify"]["disposition"] != "admit_supply"


def test_cli_apply_writes_under_tmp(tmp_path: Path, capsys) -> None:
    rc = mod.main(
        [
            "--deltas",
            str(FIXTURES),
            "--apply",
            "--ledger-root",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["apply"] is True
    written = list(tmp_path.glob("*.jsonl"))
    assert written
    assert "admit_supply" not in out.get("dispositions", {})
