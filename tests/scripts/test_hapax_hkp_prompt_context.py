from __future__ import annotations

from pathlib import Path

import yaml

from shared.hkp_bundle_export import export_shadow_bundle
from shared.hkp_prompt_context import NON_AUTHORITY_BANNER, main


def _bundle(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    task = source_root / "tasks" / "a.md"
    task.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "type": "cc-task",
        "task_id": "cli-a",
        "title": "CLI task",
        "description": "desc",
        "status": "done",
        "depends_on": [],
        "privacy_class": "internal",
        "authority_case": "CASE-SDLC-REFORM-001",
        "parent_spec": "/redacted/spec.md",
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "mutation_surface": "source",
        "authority_level": "authoritative",
    }
    task.write_text(
        "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n# T\nbody\n", encoding="utf-8"
    )
    return export_shadow_bundle(
        [task],
        bundle_id="cli-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        source_commit="abc",
        generated_at="2026-06-19T20:03:41Z",
    ).bundle_path


def test_cli_emits_banner(tmp_path: Path, monkeypatch, capsys) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    rc = main([str(bundle)])
    assert rc == 0
    assert NON_AUTHORITY_BANNER in capsys.readouterr().out


def test_cli_json_mode(tmp_path: Path, monkeypatch, capsys) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    rc = main([str(bundle), "--json"])
    assert rc == 0
    assert '"concept_count"' in capsys.readouterr().out


def test_cli_rejects_non_local_api_base(tmp_path: Path, monkeypatch, capsys) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    rc = main([str(bundle), "--api-base", "https://api.anthropic.com"])
    assert rc == 2
    assert "local-only" in capsys.readouterr().err


def test_cli_accepts_local_api_base(tmp_path: Path, monkeypatch, capsys) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    rc = main([str(bundle), "--api-base", "http://localhost:5000/v1"])
    assert rc == 0
