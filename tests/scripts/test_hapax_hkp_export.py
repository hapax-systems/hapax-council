from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

import yaml

from shared.hkp_bundle_schema import validate_bundle

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-hkp-export"
GENERATED_AT = "2026-06-18T20:03:41Z"


def test_cli_exports_cache_bundle_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_source(source_root / "tasks" / "demo.md")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(source),
            "--bundle-id",
            "cli-bundle",
            "--source-root",
            str(source_root),
            "--source-root-id",
            "repo:test",
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
    bundle = Path(payload["bundle_path"])
    assert bundle.is_relative_to(tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow")
    assert payload["validation"]["ok"] is True
    assert validate_bundle(bundle).ok is True


def test_cli_rejects_output_outside_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_source(source_root / "tasks" / "demo.md")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(source),
            "--bundle-id",
            "cli-bundle",
            "--source-root",
            str(source_root),
            "--source-root-id",
            "repo:test",
            "--output-root",
            str(tmp_path / "outside-cache"),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "HKP bundle output must be under" in result.stderr
    assert "next-action" in result.stderr


def test_cli_rejects_unsafe_bundle_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_source(source_root / "tasks" / "demo.md")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(source),
            "--bundle-id",
            "foo/bar",
            "--source-root",
            str(source_root),
            "--source-root-id",
            "repo:test",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "bundle_id is not a safe cache path component" in result.stderr
    assert "next-action" in result.stderr


def test_cli_writes_shadow_catalog_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_source(source_root / "tasks" / "demo.md")
    export_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(source),
            "--bundle-id",
            "cli-bundle",
            "--source-root",
            str(source_root),
            "--source-root-id",
            "repo:test",
            "--generated-at",
            GENERATED_AT,
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert export_result.returncode == 0, export_result.stderr

    catalog_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--catalog",
            "--generated-at",
            GENERATED_AT,
            "--json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert catalog_result.returncode == 0, catalog_result.stderr
    payload = json.loads(catalog_result.stdout)
    assert payload["ok"] is True
    assert payload["bundle_count"] == 1
    catalog = Path(payload["catalog_path"])
    assert catalog.is_relative_to(tmp_path / "home" / ".cache" / "hapax" / "hkp-shadow-index")
    assert catalog.is_file()


def test_cli_catalog_text_output_reports_failure_next_action(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    source = _write_source(source_root / "tasks" / "missing-route.md", include_route_metadata=False)
    export_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(source),
            "--bundle-id",
            "gap-bundle",
            "--source-root",
            str(source_root),
            "--source-root-id",
            "repo:test",
            "--generated-at",
            GENERATED_AT,
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert export_result.returncode == 0, export_result.stderr

    catalog_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--catalog",
            "--generated-at",
            GENERATED_AT,
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert catalog_result.returncode == 1
    assert "FAIL " in catalog_result.stdout
    assert "bundles\t1" in catalog_result.stdout
    assert "findings\t" in catalog_result.stdout
    assert "next-action\tinspect catalog findings and regenerate invalid bundles" in (
        catalog_result.stdout
    )


def test_cli_value_error_formatter_adds_fallback_next_action() -> None:
    module = runpy.run_path(str(SCRIPT))
    format_value_error = module["_format_value_error"]

    assert "next-action" in format_value_error(ValueError("plain failure"))
    assert (
        format_value_error(ValueError("specific; next-action: do the specific thing"))
        == "specific; next-action: do the specific thing"
    )


def _write_source(path: Path, *, include_route_metadata: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "type": "cc-task",
        "task_id": "demo-task",
        "title": "Demo task",
        "status": "done",
    }
    if include_route_metadata:
        frontmatter.update(
            {
                "authority_case": "CASE-SDLC-REFORM-001",
                "parent_spec": "/redacted/spec.md",
                "route_metadata_schema": 1,
                "quality_floor": "frontier_required",
                "mutation_surface": "source",
                "authority_level": "authoritative",
            }
        )
    path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n# Demo\n",
        encoding="utf-8",
    )
    return path
