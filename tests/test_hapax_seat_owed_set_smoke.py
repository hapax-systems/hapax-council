"""Small release pins for the read-only seat owed-set entry point."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hapax-seat-owed-set"


def _row(vault: Path, task_id: str, *, authorized: bool, blocked: str = "null") -> None:
    path = vault / "20-projects" / "hapax-cc-tasks" / "active" / f"{task_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"task_id: {task_id}\n"
        "status: offered\n"
        "assigned_to: unassigned\n"
        f"blocked_reason: {blocked}\n"
        f"implementation_authorized: {str(authorized).lower()}\n"
        "created_at: 2026-09-24T20:17:27Z\n"
        "---\n"
        "## Session log\n- 2026-09-24T20:17:27Z filed for the seat\n",
        encoding="utf-8",
    )


def _classes(vault: Path, *args: str) -> dict[str, list[str]]:
    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--vault",
            str(vault),
            "--commit",
            "WORKTREE",
            "--at",
            "2026-09-24T22:17:37+00:00",
            "--json",
            *args,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return {row["task_id"]: row["classes"] for row in json.loads(result.stdout)["rows"]}


def test_authorized_unassigned_row_remains_owed_without_bus(tmp_path: Path) -> None:
    _row(tmp_path, "authorized-row", authorized=True)
    assert _classes(tmp_path)["authorized-row"] == ["S2"]
    _row(tmp_path, "authorized-row", authorized=False)
    assert "S2" not in _classes(tmp_path)["authorized-row"]


def test_blocked_authority_is_owed_without_marker_or_bus(tmp_path: Path) -> None:
    _row(tmp_path, "blocked-row", authorized=False, blocked="await the coordinator")
    assert _classes(tmp_path, "--disable", "S1.marker,S5")["blocked-row"] == ["S1"]
