"""Unclaimed cc-close must refuse without rewriting notes.

The historical bash rewriter moved files before admission and had its own
prefix-vs-exact duplicate check. Slice-2 close is claim-bound: no publication,
no mutation. Prefix/exact duplicate identity lives on the typed task store
(`test_sdlc_task_store.py`). These tests pin the wrapper's fail-closed surface.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-close"


def _write_task(
    vault_root: Path,
    state: str,
    filename: str,
    task_id: str,
    *,
    status: str = "in_progress",
) -> Path:
    path = vault_root / state / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: {status}
            completed_at:
            updated_at:
            pr:
            ---

            # {task_id}

            ## Session log
            """
        ),
        encoding="utf-8",
    )
    return path


def _run_close(home: Path, task_id: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "test-role"
    return subprocess.run(
        ["bash", str(SCRIPT), task_id, "--status", "withdrawn"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _vault(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def test_unclaimed_close_refuses_and_does_not_move_note_with_prefix_neighbor(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    active = _write_task(vault, "active", "foo.md", "foo")
    closed_neighbor = _write_task(vault, "closed", "foo-bar.md", "foo-bar", status="done")
    before_active = active.read_bytes()
    before_closed = closed_neighbor.read_bytes()

    result = _run_close(home, "foo")

    assert result.returncode != 0
    assert "REFUSED" in result.stderr
    assert active.is_file()
    assert active.read_bytes() == before_active
    assert closed_neighbor.read_bytes() == before_closed
    assert not (vault / "closed" / "foo.md").exists()


def test_unclaimed_close_refuses_and_does_not_mutate_true_duplicate(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    active = _write_task(vault, "active", "foo.md", "foo")
    closed = _write_task(vault, "closed", "foo.md", "foo", status="done")
    before_active = active.read_bytes()
    before_closed = closed.read_bytes()

    result = _run_close(home, "foo")

    assert result.returncode != 0
    assert "REFUSED" in result.stderr
    assert active.read_bytes() == before_active
    assert closed.read_bytes() == before_closed


def test_unclaimed_close_refuses_without_session_identity(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "active", "foo.md", "foo")

    result = _run_close(home, "foo")

    assert result.returncode == 2
    assert "terminal_close_identity_missing" in result.stderr
