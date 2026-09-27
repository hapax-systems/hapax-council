"""Tests for scripts/check-legal-name-leaks.sh.

Pin the per-pattern + per-whitelist behaviour. Patterns are
constructed at runtime via string concatenation so this file itself
does not become a PII guard tripwire (the actual legal-name spelling
never appears as a contiguous literal in source).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check-legal-name-leaks.sh"

# Construct the legal-name spelling at runtime to avoid embedding the
# literal in this source. The pii-guard pre-commit hook scans repo
# files; encoding the test fixtures inline as concatenated tokens
# keeps this test file out of the trip set while still exercising the
# script's detection.
_FIRST = "R" + "y" + "a" + "n"
_LAST = "K" + "l" + "e" + "e" + "b" + "e" + "r" + "g" + "e" + "r"
_FULL = f"{_FIRST} {_LAST}"
_FULL_MIDDLE = f"{_FIRST} Lee {_LAST}"


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    assert SCRIPT.exists() and SCRIPT.is_file()
    assert shutil.which("bash") is not None
    return tmp_path


def _run_full(
    script_args: list[str], env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    # Never read the host's real principal registry from a test.
    run_env = {
        **os.environ,
        "HAPAX_PRINCIPAL_NAME_MAP": "/nonexistent/hapax-test/principal-name-map.yaml",
        **(env or {}),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *script_args], capture_output=True, text=True, env=run_env
    )


def _run(script_args: list[str], env: dict[str, str] | None = None) -> int:
    """Invoke the guard with the given args; return its exit code."""
    return _run_full(script_args, env).returncode


# Registered principals' given names come from the gitignored local registry
# when it is provisioned. Synthetic token only: no real name in any file.
_SYNTHETIC = "Zorblaxine"


def test_registry_given_name_fails_without_echoing_it(fixture_dir: Path) -> None:
    registry = fixture_dir / "principal-name-map.yaml"
    registry.write_text(f"principal-a2: {_SYNTHETIC}\n", encoding="utf-8")
    f = fixture_dir / "doc.md"
    f.write_text(f"met {_SYNTHETIC} today\n", encoding="utf-8")
    result = _run_full([str(f)], {"HAPAX_PRINCIPAL_NAME_MAP": str(registry)})
    assert result.returncode == 1
    assert f"{f}:1" in result.stderr
    assert _SYNTHETIC.lower() not in (result.stderr + result.stdout).lower()


def test_registry_absent_falls_back_to_the_surname(fixture_dir: Path) -> None:
    f = fixture_dir / "doc.md"
    f.write_text(f"met {_SYNTHETIC} today\n", encoding="utf-8")
    assert _run([str(f)]) == 0
    f.write_text(f"met {_LAST} today\n", encoding="utf-8")
    assert _run([str(f)]) == 1


def test_unreadable_registry_fails_closed(fixture_dir: Path) -> None:
    registry = fixture_dir / "principal-name-map.yaml"
    registry.mkdir()
    f = fixture_dir / "doc.md"
    f.write_text("clean\n", encoding="utf-8")
    result = _run_full([str(f)], {"HAPAX_PRINCIPAL_NAME_MAP": str(registry)})
    assert result.returncode == 2
    assert "principal-name-map" in result.stderr


def test_clean_file_passes(fixture_dir: Path) -> None:
    f = fixture_dir / "clean.md"
    f.write_text("Operator: Oudepode\n", encoding="utf-8")
    assert _run([str(f)]) == 0


def test_legal_name_full_fails(fixture_dir: Path) -> None:
    f = fixture_dir / "leak.md"
    f.write_text(f"Author: {_FULL}\n", encoding="utf-8")
    assert _run([str(f)]) == 1


def test_legal_name_with_middle_fails(fixture_dir: Path) -> None:
    f = fixture_dir / "leak3.md"
    f.write_text(f"Author: {_FULL_MIDDLE}\n", encoding="utf-8")
    assert _run([str(f)]) == 1


def test_case_insensitive_match(fixture_dir: Path) -> None:
    f = fixture_dir / "leak4.md"
    f.write_text(f"{_FULL.lower()}\n", encoding="utf-8")
    assert _run([str(f)]) == 1


def test_family_surname_alone_fails(fixture_dir: Path) -> None:
    # The surname alone names every household member, registered or not.
    f = fixture_dir / "registered-identity-leak.md"
    f.write_text(f"subject: {_LAST}\n", encoding="utf-8")
    assert _run([str(f)]) == 1


@pytest.mark.parametrize(
    "identifier", ["principal-c1", "principal-c2", "principal-a1", "principal-a2"]
)
def test_opaque_principal_ids_pass(fixture_dir: Path, identifier: str) -> None:
    # The opaque IDs replace the names and must stay usable in any file: the
    # follow-on PRs (#4717, #4558) use them outside the scanner's whitelist.
    f = fixture_dir / "opaque-principal.md"
    f.write_text(f"subject: {identifier}\n", encoding="utf-8")
    assert _run([str(f)]) == 0


def test_email_is_not_gated(fixture_dir: Path) -> None:
    """The operator's email is an operational identifier, not a
    referent-policy target. mail-monitor specs and integration tests
    legitimately reference it.
    """
    f = fixture_dir / "emailonly.md"
    f.write_text("Forward to " + "rylklee" + "@" + "gmail.com\n", encoding="utf-8")
    assert _run([str(f)]) == 0


def test_all_four_sanctioned_referents_pass(fixture_dir: Path) -> None:
    f = fixture_dir / "all_refs.md"
    body = (
        "The Operator says hello.\n"
        "Oudepode is the canonical referent.\n"
        "Oudepode The Operator agrees.\n"
        "OTO concurs.\n"
    )
    f.write_text(body, encoding="utf-8")
    assert _run([str(f)]) == 0


def test_whitelisted_path_skipped(fixture_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The script's own whitelist must shield zenodo + axioms-contracts files.

    The whitelist is glob-based and resolved against the path argument;
    we exercise it by pointing at an actual whitelisted repo path and
    confirming the script accepts it cleanly even if the legal name is
    present.
    """
    zenodo = REPO_ROOT / ".zenodo.json"
    if not zenodo.exists():
        pytest.skip(".zenodo.json absent in this checkout")
    monkeypatch.chdir(REPO_ROOT)
    # Pass the path as repo-relative so the whitelist glob matches.
    assert _run([".zenodo.json"]) == 0
