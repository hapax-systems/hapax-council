from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-capability-surface-delta-intake"
FIXTURES = REPO_ROOT / "config" / "capability-surface-delta-fixtures.json"
NOW = "2026-07-01T04:30:00Z"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_dry_run_reports_would_write_without_mutating_task_root(tmp_path: Path) -> None:
    result = _run(
        "--fixtures",
        str(FIXTURES),
        "--task-root",
        str(tmp_path),
        "--now",
        NOW,
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["applied"] is False
    assert payload["loaded"] == 3
    assert len(payload["would_write"]) == 3
    assert payload["written"] == []
    assert not (tmp_path / "active").exists()


def test_apply_writes_delta_tasks_and_is_idempotent(tmp_path: Path) -> None:
    result = _run(
        "--fixtures",
        str(FIXTURES),
        "--task-root",
        str(tmp_path),
        "--now",
        NOW,
        "--apply",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert len(payload["written"]) == 3
    assert len(list((tmp_path / "active").glob("*.md"))) == 3

    again = _run(
        "--fixtures",
        str(FIXTURES),
        "--task-root",
        str(tmp_path),
        "--now",
        NOW,
        "--apply",
        "--json",
    )

    assert again.returncode == 0, again.stderr
    second = json.loads(again.stdout)
    assert second["written"] == []
    assert len(second["skipped_existing"]) == 3
