"""CLI tests for hapax-capability-onboarding-intake."""

from __future__ import annotations

import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-capability-onboarding-intake"


def _load():
    loader = SourceFileLoader("hapax_capability_onboarding_intake", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


mod = _load()


def test_cli_dry_run_no_ledger(tmp_path: Path, capsys) -> None:
    rc = mod.main(
        [
            "--dry-run",
            "--surface-id",
            "x.y",
            "--measurement-sufficiency",
            "partial",
            "--modal-class",
            "permitted",
            "--ledger-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["classify"]["disposition"] == "EXPLORE"
    assert list(tmp_path.iterdir()) == []


def test_cli_json_stdin_writes_explore(tmp_path: Path, capsys, monkeypatch) -> None:
    payload = json.dumps(
        {
            "surface_id": "new.slice",
            "measurement_sufficiency": "partial",
            "modal_class": "permitted",
        }
    )
    monkeypatch.setattr(
        "sys.stdin",
        type("S", (), {"read": staticmethod(lambda: payload)})(),
    )
    rc = mod.main(["--json", "-", "--ledger-root", str(tmp_path), "--source-ref", "cli:test"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["row"]["disposition"] == "EXPLORE"
    assert (tmp_path / "explore.jsonl").exists()
