"""Tests for scripts/check-legal-name-leaks.sh.

Pin the per-pattern + per-whitelist behaviour. Patterns are
constructed at runtime via string concatenation so this file itself
does not become a PII guard tripwire (the actual legal-name spelling
never appears as a contiguous literal in source).
"""

from __future__ import annotations

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


def _run(script_args: list[str]) -> int:
    """Invoke the guard with the given args; return its exit code."""
    return subprocess.run(
        ["bash", str(SCRIPT), *script_args],
        capture_output=True,
        text=True,
    ).returncode


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
