from __future__ import annotations

import importlib.machinery
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-hkp-export-sdlc"
GENERATED_AT = "2026-06-19T20:00:00Z"

_mod = importlib.machinery.SourceFileLoader("hkp_export_sdlc", str(SCRIPT)).load_module()
run_sdlc_export = _mod.run_sdlc_export
sdlc_sources = _mod.sdlc_sources


def _write_task(path: Path, *, task_id: str, depends_on: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "type": "cc-task",
        "task_id": task_id,
        "title": f"Task {task_id}",
        "description": "d",
        "status": "done",
        "depends_on": depends_on,
        "privacy_class": "internal",
        "authority_case": "CASE-SDLC-REFORM-001",
        "parent_spec": "/redacted/spec.md",
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "mutation_surface": "source",
        "authority_level": "authoritative",
    }
    path.write_text(
        "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n# T\nbody\n", encoding="utf-8"
    )


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    cct = root / "20-projects" / "hapax-cc-tasks"
    _write_task(cct / "active" / "a.md", task_id="sdlc-a", depends_on=["sdlc-b"])
    _write_task(cct / "closed" / "b.md", task_id="sdlc-b", depends_on=[])
    return root


def test_sdlc_sources_collects_active_and_closed(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    sources = sdlc_sources(root)
    assert len(sources) == 2
    assert {p.name for p in sources} == {"a.md", "b.md"}


def test_run_sdlc_export_resolves_cross_state_edges(tmp_path: Path, monkeypatch) -> None:
    # default cache root resolves under the monkeypatched HOME (exporter enforces
    # output under ~/.cache/hapax/hkp-shadow).
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = _vault(tmp_path)
    result = run_sdlc_export(vault_root=root, generated_at=GENERATED_AT)
    assert result.concept_count == 2
    edges = [
        json.loads(line)
        for line in (result.bundle_path / "_hkp" / "edges.jsonl").read_text().splitlines()
        if line.strip()
    ]
    # active -> closed depends_on resolves within the single bundle
    assert any(e["to_uid"] == "hkp:cc-task:sdlc-b" for e in edges)


def test_run_sdlc_export_no_sources_exits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    empty = tmp_path / "empty"
    (empty / "20-projects" / "hapax-cc-tasks" / "active").mkdir(parents=True)
    with pytest.raises(SystemExit):
        run_sdlc_export(vault_root=empty, generated_at=GENERATED_AT)


def test_cli_json_smoke(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    home = str(tmp_path / "home")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--vault-root", str(root), "--json"],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": home},
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["concept_count"] == 2


def _write_metadata_gap_task(path: Path, task_id: str) -> None:
    # missing authority_case/parent_spec/route_metadata_schema -> route_metadata_gap error finding
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "type": "cc-task",
        "task_id": task_id,
        "title": task_id,
        "status": "offered",
        "depends_on": [],
    }
    path.write_text(
        "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n# T\nbody\n", encoding="utf-8"
    )


def _gap_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    _write_metadata_gap_task(
        root / "20-projects" / "hapax-cc-tasks" / "active" / "gap.md", "sdlc-gap"
    )
    return root


def test_cli_default_exit_zero_despite_error_findings(tmp_path: Path) -> None:
    root = _gap_vault(tmp_path)
    home = str(tmp_path / "home")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--vault-root", str(root), "--json"],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": home},
    )
    assert proc.returncode == 0, proc.stderr  # projection succeeds; findings are advisory
    assert json.loads(proc.stdout)["error_findings"] >= 1


def test_cli_strict_exits_nonzero_on_error_findings(tmp_path: Path) -> None:
    root = _gap_vault(tmp_path)
    home = str(tmp_path / "home")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--vault-root",
            str(root),
            "--json",
            "--fail-on-error-findings",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": home},
    )
    assert proc.returncode == 1
