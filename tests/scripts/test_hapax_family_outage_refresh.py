"""M150: `hapax-family-outage-refresh --help` must not run the refresh.

The script was hand-installed in ~/.local/bin with no argument parsing, so any invocation rewrote
the review team's family-outage state. On 2026-09-25 a `--help` meant to read its usage executed it.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-family-outage-refresh"


def _state_home(tmp_path: Path, state: dict) -> tuple[Path, Path]:
    home = tmp_path / "home"
    path = home / ".cache" / "hapax" / "review-team" / "family-outage.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    return home, path


def _run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
        timeout=60,
        check=False,
    )


STATE = {
    "glm": {"observed_at": "2026-01-01T00:00:00Z", "until": "2099-01-01T00:00:00Z", "note": "held"},
    "codex": {"observed_at": "2026-01-01T00:00:00Z", "outage_started_at": "2026-01-01T00:00:00Z"},
    "muse": {"observed_at": "2026-01-01T00:00:00Z", "until": "2000-01-01T00:00:00Z"},
}


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_prints_usage_and_leaves_the_state_byte_identical(tmp_path: Path, flag: str) -> None:
    home, path = _state_home(tmp_path, STATE)
    before = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    result = _run(home, flag)

    assert result.returncode == 0, result.stderr
    assert "usage: hapax-family-outage-refresh" in result.stdout
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_mtime


@pytest.mark.parametrize("args", [["--dry-run"], ["refresh"], ["", "x"]])
def test_any_other_argument_is_refused_without_writing(tmp_path: Path, args: list[str]) -> None:
    home, path = _state_home(tmp_path, STATE)
    before = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    result = _run(home, *args)

    assert result.returncode == 2
    assert "usage: hapax-family-outage-refresh" in result.stderr
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_mtime


def test_no_arguments_restamps_only_entries_whose_until_is_ahead(tmp_path: Path) -> None:
    home, path = _state_home(tmp_path, STATE)

    result = _run(home)

    assert result.returncode == 0, result.stderr
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["glm"]["observed_at"] != "2026-01-01T00:00:00Z"  # until ahead: kept fresh
    assert after["glm"]["until"] == "2099-01-01T00:00:00Z"
    assert after["glm"]["note"] == "held"
    assert after["codex"] == STATE["codex"]  # no until: untouched
    assert after["muse"] == STATE["muse"]  # until passed: untouched
    assert "glm observed_at=" in result.stdout


def test_a_missing_state_file_is_a_no_op(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    result = _run(home)

    assert result.returncode == 0, result.stderr
    assert not (home / ".cache" / "hapax" / "review-team" / "family-outage.json").exists()
