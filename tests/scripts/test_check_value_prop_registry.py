"""Tests for scripts/check-value-prop-registry.py (v1 structural checks)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-value-prop-registry.py"
COMMITTED_REGISTRY = REPO_ROOT / "docs/repo-pres/value-prop-registry.yaml"


def _base_registry() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "audiences": {
            "testers": {"weight": 90},
            "low_interest": {"weight": 40},
        },
        "registry": [
            {
                "value_proposition_id": "sample-prop",
                "rank": 1,
                "implementation_maturity": "present",
                "audience_ids": {"testers": 90},
                "claim_ceiling": "Sample ceiling; no stronger claim.",
                "technical_items": ["sample mechanism shipped"],
                "target_surfaces": ["council-docs"],
                "freshness_source": "sample tests green at HEAD",
                "stale_behavior": "block_public_current",
            }
        ],
    }


def _write_registry(path: Path, registry: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    return path


def _run_checker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def test_committed_registry_passes_default_run() -> None:
    assert COMMITTED_REGISTRY.exists()
    result = _run_checker()
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "value-prop registry OK" in result.stdout


def test_minimal_fixture_registry_passes(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path / "registry.yaml", _base_registry())
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"


def test_unknown_audience_id_fails_c1(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["registry"][0]["audience_ids"] = {"ghost_audience": 90}
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Hapax.ValuePropRegistry.C1" in result.stdout
    assert "ghost_audience" in result.stdout
    assert "Next action:" in result.stdout


def test_zero_placement_high_weight_audience_fails_c2(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["audiences"]["orphan_audience"] = {"weight": 80}
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Hapax.ValuePropRegistry.C2" in result.stdout
    assert "orphan_audience" in result.stdout
    assert "Next action:" in result.stdout


def test_present_top_rank_row_without_target_surfaces_fails_c2(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["registry"][0]["target_surfaces"] = []
    # Keep the audience below the placement floor so only the row-level rule fires.
    registry["audiences"]["testers"]["weight"] = 70
    registry["registry"][0]["audience_ids"] = {"testers": 70}
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Hapax.ValuePropRegistry.C2" in result.stdout
    assert "sample-prop" in result.stdout


def test_planned_row_without_freshness_source_fails_c3(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["registry"][0]["implementation_maturity"] = "planned"
    del registry["registry"][0]["freshness_source"]
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Hapax.ValuePropRegistry.C3" in result.stdout
    assert "freshness_source" in result.stdout
    assert "Next action:" in result.stdout


def test_vault_row_targeting_readme_surface_fails_c6(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["registry"][0]["evidence_visibility"] = "vault"
    registry["registry"][0]["target_surfaces"] = ["council-readme"]
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Hapax.ValuePropRegistry.C6" in result.stdout
    assert "council-readme" in result.stdout
    assert "Next action:" in result.stdout


def test_ryanklee_org_link_fails_c8(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["registry"][0]["tangible_benefit"] = "See github.com/ryanklee/hapax-council for code"
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Hapax.ValuePropRegistry.C8" in result.stdout
    assert "github.com/ryanklee" in result.stdout
    assert "Next action:" in result.stdout


def test_missing_registry_file_exits_2(tmp_path: Path) -> None:
    result = _run_checker("--registry", str(tmp_path / "missing.yaml"))
    assert result.returncode == 2, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "value-prop registry not found" in result.stderr
