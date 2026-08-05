"""CLI tests for hapax-sdlc-router-shadow-compare."""

from __future__ import annotations

import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-sdlc-router-shadow-compare"


def _load():
    loader = SourceFileLoader("hapax_sdlc_router_shadow_compare_cli", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


mod = _load()


def test_cli_demo_json_no_write(tmp_path: Path, capsys) -> None:
    log = tmp_path / "sc.jsonl"
    rc = mod.main(
        [
            "--task-id",
            "cli-demo",
            "--json",
            "--no-write",
            "--log",
            str(log),
            "--router-state",
            str(tmp_path / "r.json"),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["task_id"] == "cli-demo"
    assert out["dispatch_mutated"] is False
    assert out["action"] in {"shadow", "route", "hold"}
    assert not log.exists()


def test_cli_writes_log(tmp_path: Path, capsys) -> None:
    log = tmp_path / "sc.jsonl"
    rc = mod.main(
        [
            "--task-id",
            "cli-write",
            "--json",
            "--log",
            str(log),
            "--router-state",
            str(tmp_path / "r.json"),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dispatch_mutated"] is False
    assert log.exists()
    assert len(log.read_text(encoding="utf-8").strip().splitlines()) == 1
