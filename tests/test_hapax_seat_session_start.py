"""Red-first pins for the SessionStart seat wrapper.

``scripts/hapax-seat-session-start`` is the restored prior design carried from
git blob 73be55dbb: it never exits non-zero and never stays silent, so an
absent or broken ``hapax-seat-owed-set`` degrades to one orientation line
instead of failing the SessionStart hook. Tests (1) and (4) pin that fail-open
contract's unsafe cases.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hapax-seat-session-start"
ORIENTATION_REFERENCE = "30-areas/hapax/frame/COORDINATOR-SEAT.md"
BINARY_RELATIVE = Path(".local") / "bin" / "hapax-seat-owed-set"


def _run(home: Path) -> subprocess.CompletedProcess[str]:
    """Run the wrapper as the activation command does, with HOME pointed at a fixture."""

    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    return subprocess.run(
        [str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _plant_binary(home: Path, body: str) -> Path:
    binary = home / BINARY_RELATIVE
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(body, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


def _orientation_line(stdout: str) -> dict:
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert len(lines) == 1, stdout
    return json.loads(lines[0])


def test_wrapper_exits_zero_with_nothing_installed(tmp_path: Path) -> None:
    """Unsafe case: no owed-set binary exists under HOME, so nothing can be run."""

    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    assert _run(empty_home).returncode == 0
    assert _run(tmp_path / "absent-home").returncode == 0


def test_missing_binary_prints_orientation_line(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    result = _run(home)
    assert result.returncode == 0, result.stderr
    output = _orientation_line(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "SessionStart"
    assert ORIENTATION_REFERENCE in output["additionalContext"]


def test_installed_binary_is_invoked_with_session_start(tmp_path: Path) -> None:
    home = tmp_path / "home"
    record = tmp_path / "argv.txt"
    sentinel = (
        '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"owed-set ran"}}'
    )
    _plant_binary(
        home,
        f"#!/bin/bash\nprintf '%s\\n' \"$*\" > '{record}'\nprintf '%s\\n' '{sentinel}'\nexit 0\n",
    )
    result = _run(home)
    assert result.returncode == 0, result.stderr
    assert record.read_text(encoding="utf-8").strip() == "--session-start"
    assert sentinel in result.stdout
    assert ORIENTATION_REFERENCE not in result.stdout


def test_failing_binary_still_exits_zero(tmp_path: Path) -> None:
    """Unsafe case: the owed-set binary is present but exits 3 with stderr noise."""

    home = tmp_path / "home"
    _plant_binary(
        home,
        "#!/bin/bash\nprintf '%s\\n' 'owed-set exploded' >&2\nexit 3\n",
    )
    result = _run(home)
    assert result.returncode == 0, result.stderr
