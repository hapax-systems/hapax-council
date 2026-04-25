"""AUDIT-22 Phase B-2 — linter for contract redaction entries.

Pins the behavior of ``scripts/verify-redaction-transforms.py``: every
``redactions:`` entry in every ``axioms/contracts/publication/*.yaml``
file must be either a registered transform name (in
:data:`shared.governance.publication_allowlist.REDACTION_TRANSFORMS`)
or a dict-key pattern (a string with optional wildcard suffix).

Anything else is a typo or unregistered transform — flagged as a
hard error.

Why this matters: the AUDIT-22 Phase B wire-in (#1384) only fires
the transform pipeline for registered names. Contract entries naming
unregistered transforms silently no-op. The linter closes that gap
at CI time so production never ships a misnamed transform.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify-redaction-transforms.py"


def _run(contracts_dir: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT)]
    if contracts_dir is not None:
        cmd.extend(["--contracts-dir", str(contracts_dir)])
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)


def _write_contract(
    directory: Path,
    surface: str,
    *,
    redactions: list[str],
    state_kinds: list[str] | None = None,
) -> Path:
    path = directory / f"{surface}.yaml"
    payload = {
        "surface": surface,
        "state_kinds": state_kinds or ["chronicle.high_salience"],
        "redactions": redactions,
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


class TestScriptExists:
    def test_script_present_at_canonical_path(self) -> None:
        assert SCRIPT.exists(), f"linter script missing: {SCRIPT}"

    def test_script_executable(self) -> None:
        assert SCRIPT.is_file()


class TestProductionContractsClean:
    """Catches the very thing this PR (Phase B-2) fixes: contract
    entries named ``operator_legal_name`` are now matched against the
    registered transform of the same name. Pin this so future renames
    can't drift the contract entries out of registry alignment."""

    def test_production_contracts_pass(self) -> None:
        result = _run()
        assert result.returncode == 0, (
            f"production contracts failed linter\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestRegisteredTransformAccepted:
    def test_operator_legal_name_passes(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, "x", redactions=["operator_legal_name"])
        result = _run(tmp_path)
        assert result.returncode == 0

    def test_email_address_passes(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, "x", redactions=["email_address"])
        result = _run(tmp_path)
        assert result.returncode == 0

    def test_gps_coordinate_passes(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, "x", redactions=["gps_coordinate"])
        result = _run(tmp_path)
        assert result.returncode == 0


class TestDictKeyPatternAccepted:
    def test_wildcard_suffix_passes(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, "x", redactions=["operator_profile.*"])
        result = _run(tmp_path)
        assert result.returncode == 0

    def test_dotted_key_passes(self, tmp_path: Path) -> None:
        """``chat.author_id`` is a literal dict-key pattern — the
        publication_allowlist matches keys whose name equals the
        pattern. Linter accepts it because it doesn't try to be
        a transform."""
        _write_contract(tmp_path, "x", redactions=["chat.author_id"])
        result = _run(tmp_path)
        assert result.returncode == 0


class TestUnknownTransformRejected:
    """The behavior under test: any redaction entry that is neither a
    registered transform NOR a dict-key pattern (no dot, no wildcard,
    not a registered transform name) is a likely typo or unregistered
    transform — fail the lint."""

    def test_typo_legal_name_rejected(self, tmp_path: Path) -> None:
        """``legal_name`` is the pre-Phase-B-2 name; reject it after
        rename so contracts can't accidentally use the old name."""
        _write_contract(tmp_path, "x", redactions=["legal_name"])
        result = _run(tmp_path)
        assert result.returncode != 0
        assert "legal_name" in (result.stdout + result.stderr)

    def test_typo_random_word_rejected(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, "x", redactions=["foobarbaz"])
        result = _run(tmp_path)
        assert result.returncode != 0
        assert "foobarbaz" in (result.stdout + result.stderr)


class TestEmptyContract:
    def test_no_redactions_field_passes(self, tmp_path: Path) -> None:
        path = tmp_path / "x.yaml"
        path.write_text(yaml.safe_dump({"surface": "x", "state_kinds": ["y"]}), encoding="utf-8")
        result = _run(tmp_path)
        assert result.returncode == 0

    def test_empty_directory_passes(self, tmp_path: Path) -> None:
        result = _run(tmp_path)
        assert result.returncode == 0


class TestMultipleContracts:
    """Contract scope: linter walks the entire dir, fails fast on the
    first bad entry but reports all bad entries before exiting."""

    def test_one_bad_among_many_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, "good_a", redactions=["operator_legal_name"])
        _write_contract(tmp_path, "good_b", redactions=["email_address"])
        _write_contract(tmp_path, "bad", redactions=["unknown_transform"])
        result = _run(tmp_path)
        assert result.returncode != 0
        assert "unknown_transform" in (result.stdout + result.stderr)
        assert "bad.yaml" in (result.stdout + result.stderr)


@pytest.fixture
def malformed_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "broken.yaml"
    path.write_text("surface: x\nredactions: [\n", encoding="utf-8")
    return path


class TestMalformedYaml:
    def test_malformed_yaml_reported(self, tmp_path: Path, malformed_yaml: Path) -> None:
        """Malformed YAML is a structural error (not a redaction
        violation). Exit non-zero with a clear diagnostic."""
        result = _run(tmp_path)
        assert result.returncode != 0
        assert "broken.yaml" in (result.stdout + result.stderr)
