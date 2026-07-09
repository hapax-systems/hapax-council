"""Tests for scripts/check-value-prop-registry.py (v1 structural + v2 claim-lint checks)."""

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


# ---------------------------------------------------------------------------
# v2 checks: C4 embargo lint, C5 required pairings, C7 comparative-claim pins,
# C9 pinned counts, C10 PII screen
# ---------------------------------------------------------------------------


def test_embargo_term_without_exception_fails_c4(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["registry"][0]["tangible_benefit"] = "This surface structurally cannot leak claims"
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Hapax.ValuePropRegistry.C4" in result.stdout
    assert "structurally cannot" in result.stdout
    assert "Next action:" in result.stdout


def test_embargo_term_with_reasoned_exception_passes_c4(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["registry"][0]["tangible_benefit"] = "This surface structurally cannot leak claims"
    registry["registry"][0]["embargo_exceptions"] = [
        {"term": "structurally cannot", "reason": "mention-not-use: fixture quotes the ban"}
    ]
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"


def test_absolute_phrase_without_paired_disclosure_fails_c5(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["constraints"] = [
        {
            "id": "required-pairings",
            "pairings": {"no false green": "merge-gate scoping disclosure"},
        }
    ]
    registry["registry"][0]["tangible_benefit"] = "Delivers no-false-green merges"
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Hapax.ValuePropRegistry.C5" in result.stdout
    assert "no false green" in result.stdout
    assert "merge-gate scoping disclosure" in result.stdout


def test_absolute_phrase_with_paired_disclosure_passes_c5(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["constraints"] = [
        {
            "id": "required-pairings",
            "pairings": {"no false green": "merge-gate scoping disclosure"},
        }
    ]
    registry["registry"][0]["tangible_benefit"] = "Delivers no-false-green merges"
    registry["registry"][0]["required_pairings"] = [
        "'no false green' ships with merge-gate scoping disclosure (scoped, fail-closed)"
    ]
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"


def test_comparative_claim_missing_scout_date_fails_c7(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["registry"][0]["comparative_claims"] = [
        {
            "claim": "no comparator ships this mechanism",
            "evidence_level": "DS",
            "comparator": "spec-kit v0.9.2",
        }
    ]
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Hapax.ValuePropRegistry.C7" in result.stdout
    assert "scout_date" in result.stdout


def test_stale_comparative_claim_fails_c7_with_refresh_hint(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["registry"][0]["comparative_claims"] = [
        {
            "claim": "no comparator ships this mechanism",
            "evidence_level": "DC",
            "scout_date": "2026-01-01",  # far beyond the 45-day default TTL
            "comparator": "spec-kit v0.9.2",
        }
    ]
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Hapax.ValuePropRegistry.C7" in result.stdout
    assert "refresh the comparator scout" in result.stdout
    assert "docs_internal" in result.stdout


def test_unpinned_comparative_claim_needs_docs_internal_c7(tmp_path: Path) -> None:
    registry = _base_registry()
    claim = {
        "claim": "no comparator ships this mechanism",
        "evidence_level": "DS",
        "scout_date": "2026-01-01",  # stale AND unpinned
    }
    registry["registry"][0]["comparative_claims"] = [claim]
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "pinned comparator" in result.stdout
    # The registry's own comparative-claim-hygiene escape: docs_internal quiets
    # both the missing pin and the stale scout (not quotable publicly anyway).
    claim["status"] = "docs_internal"
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"


def test_unpinned_numeric_fails_c9(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["registry"][0]["tangible_benefit"] = "Ships 47 hooks across the estate"
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Hapax.ValuePropRegistry.C9" in result.stdout
    assert "'47'" in result.stdout
    assert "Next action:" in result.stdout


def test_future_scout_date_fails_c7_fail_closed(tmp_path: Path) -> None:
    # fail-closed at the date boundary: a future-dated scout must not dodge the TTL
    registry = _base_registry()
    registry["registry"][0]["comparative_claims"] = [
        {
            "claim": "no comparator ships this mechanism",
            "evidence_level": "DC",
            "scout_date": "2099-01-01",
            "comparator": "spec-kit v0.9.2",
        }
    ]
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Hapax.ValuePropRegistry.C7" in result.stdout
    assert "in the future" in result.stdout


def test_pinned_numeric_and_excluded_tokens_pass_c9(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["registry"][0]["tangible_benefit"] = (
        "Since 2025 (v1.2.0, Gate-13, #4331, scouted 2026-07-01) ships 47 hooks"
    )
    registry["registry"][0]["pinned_counts"] = {"47": "tests/test_hook_registry.py count pin"}
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"


def test_axiom_registry_ref_without_pii_receipt_fails_c10(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["registry"][0]["technical_items"] = ["axioms/registry.yaml single_user axiom"]
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Hapax.ValuePropRegistry.C10" in result.stdout
    assert "pii_screen_receipt" in result.stdout
    assert "privacy-sensitive" in result.stdout


def test_axiom_registry_ref_with_pii_receipt_passes_c10(tmp_path: Path) -> None:
    registry = _base_registry()
    registry["registry"][0]["technical_items"] = ["axioms/registry.yaml single_user axiom"]
    registry["registry"][0]["pii_screen_receipt"] = (
        "2026-07-09 fixture screen: mechanics only, no axiom prose quoted"
    )
    registry_path = _write_registry(tmp_path / "registry.yaml", registry)
    result = _run_checker("--registry", str(registry_path))
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
