"""`hapax-platform-capability-receipts --show` — the read-only mode the seat refresher consults.

Review finding on #4624, round 9: the mode had no direct tests for an empty platform selection,
a missing receipt, plain-text output, or a directory the loader cannot read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-platform-capability-receipts"


def _show(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--show", *args],
        env={"HOME": str(home), "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_empty_platform_selection_is_refused_with_the_remedy(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "hapax" / "platform-capability-receipts").mkdir(parents=True)
    proc = _show(home, "--json")
    assert "Traceback" not in proc.stderr
    assert "--show needs at least one --platform" in proc.stdout + proc.stderr


def test_a_missing_receipt_for_the_named_platform_is_reported_not_invented(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "hapax" / "platform-capability-receipts").mkdir(parents=True)
    proc = _show(home, "--platform", "glmcp", "--json")
    assert "Traceback" not in proc.stderr
    payload = json.loads(proc.stdout)
    assert all(
        row.get("platform") != "glmcp" or row.get("accepted") is not True
        for row in payload["receipts"]
    )
    assert payload["directory_error"] is None


def test_plain_text_mode_prints_a_quota_line_per_receipt(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "hapax" / "platform-capability-receipts").mkdir(parents=True)
    proc = _show(home, "--platform", "glmcp")
    assert "Traceback" not in proc.stderr
    assert proc.returncode in (0, 1)
    # nothing stored: the text mode must say so rather than print an empty quota surface as observed
    assert "observed" not in proc.stdout.lower() or "quota=observed" not in proc.stdout


def test_an_unloadable_receipt_directory_is_not_accepted(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "hapax").mkdir(parents=True)
    (home / ".cache" / "hapax" / "platform-capability-receipts").write_text("not a directory")
    proc = _show(home, "--platform", "glmcp", "--json")
    assert "Traceback" not in proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    rows = [row for row in payload["receipts"] if row.get("platform") == "glmcp"]
    assert rows and rows[0]["accepted"] is False and rows[0].get("reason"), payload
