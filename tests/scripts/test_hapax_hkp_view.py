from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from shared.hkp_bundle_export import export_shadow_bundle

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-hkp-view"
GENERATED_AT = "2026-06-19T06:10:00Z"


def test_cli_writes_json_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    export_shadow_bundle(
        [source],
        bundle_id="cli-viewer",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "cli-viewer",
            "--report-id",
            "cli-report",
            "--generated-at",
            GENERATED_AT,
            "--json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["bundle_count"] == 1
    assert payload["row_count"] == 1
    assert payload["support_label"] == "support_non_authoritative_projection_state"
    assert Path(payload["markdown_path"]).is_relative_to(
        tmp_path / "home" / ".cache" / "hapax" / "hkp-reports"
    )
    assert Path(payload["json_path"]).is_file()


def test_cli_text_output_reports_support_label(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_task(source_root / "tasks" / "demo.md")
    export_shadow_bundle(
        [source],
        bundle_id="cli-viewer",
        source_root=source_root,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "cli-viewer",
            "--report-id",
            "cli-report",
            "--generated-at",
            GENERATED_AT,
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "OK " in result.stdout
    assert "bundles\t1" in result.stdout
    assert "rows\t1" in result.stdout
    assert "support_label\tsupport_non_authoritative_projection_state" in result.stdout


def test_cli_rejects_report_root_outside_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--report-root",
            str(tmp_path / "outside-reports"),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "HKP research viewer report output must be under" in result.stderr
    assert "next-action" in result.stderr


def _write_task(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                "type: cc-task",
                "task_id: cli-viewer-demo",
                'title: "CLI Viewer Demo"',
                "authority_case: CASE-HKP-TEST",
                "parent_spec: /tmp/spec.md",
                "route_metadata_schema: 1",
                "quality_floor: deterministic_ok",
                "mutation_surface: source",
                "authority_level: authoritative",
                "---",
                "",
                "body that should not appear in viewer output\n",
            ]
        ),
        encoding="utf-8",
    )
    return path
