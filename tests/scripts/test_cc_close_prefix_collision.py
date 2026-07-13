from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-close"

_IDENTITY_ENV = (
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_AGENT_INTERFACE",
    "HAPAX_SESSION_ID",
    "HAPAX_CLAIM_RESUME_SESSION_ID",
    "CLAUDE_ROLE",
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
    "CODEX_SESSION_NAME",
    "CODEX_SESSION",
    "CODEX_ROLE",
)


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
            assigned_to: test-role
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
    env = {key: value for key, value in os.environ.items() if key not in _IDENTITY_ENV}
    env["HOME"] = str(home)
    env["HAPAX_AGENT_NAME"] = "test-role"
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


def test_prefix_collision_does_not_block_distinct_closed_task(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "active", "foo.md", "foo")
    _write_task(vault, "closed", "foo-bar.md", "foo-bar", status="done")

    result = _run_close(home, "foo")

    assert result.returncode == 0, result.stderr
    assert not (vault / "active" / "foo.md").exists()
    assert (vault / "closed" / "foo.md").exists()
    assert (vault / "closed" / "foo-bar.md").exists()


def test_true_exact_duplicate_is_blocked(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "active", "foo.md", "foo")
    _write_task(vault, "closed", "foo.md", "foo", status="done")

    result = _run_close(home, "foo")

    assert result.returncode == 8
    assert "closed task duplicate" in result.stderr
    assert (vault / "active" / "foo.md").exists()


def test_descriptor_style_true_duplicate_is_blocked(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "active", "foo-descriptor.md", "foo")
    _write_task(vault, "closed", "foo-other.md", "foo", status="done")

    result = _run_close(home, "foo")

    assert result.returncode == 8
    assert "closed task duplicate" in result.stderr
    assert (vault / "active" / "foo-descriptor.md").exists()


def test_no_closed_tasks_allows_close(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "active", "foo.md", "foo")

    result = _run_close(home, "foo")

    assert result.returncode == 0, result.stderr
    assert not (vault / "active" / "foo.md").exists()
    assert (vault / "closed" / "foo.md").exists()
