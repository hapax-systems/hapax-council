"""Unclaimed cc-close must not clear leases. Successful typed close still does.

cc-claim writes both ``cc-active-task-<role>`` and
``cc-active-task-<role>-<session_id>``. The bash rewriter cleared those files
even without a claim publication. Slice-2 close is claim-bound: no publication,
no mutation, including leases. Dual-lease clearing on a successful close is
pinned by ``test_done_close_projects_every_terminal_surface_atomically``.
"""

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
    "CLAUDE_ROLE",
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_THREAD_NAME",
    "CODEX_SESSION_NAME",
    "CODEX_SESSION",
    "CODEX_ROLE",
    "CODEX_HOME",
)


def _vault(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def _write_task(vault_root: Path, task_id: str, *, status: str = "in_progress") -> Path:
    path = vault_root / "active" / f"{task_id}.md"
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


def _cache(home: Path) -> Path:
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _run_close(
    home: Path, task_id: str, *, role: str, session_id: str | None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = role
    if session_id is not None:
        env["HAPAX_SESSION_ID"] = session_id
    return subprocess.run(
        ["bash", str(SCRIPT), task_id, "--status", "withdrawn"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_unclaimed_close_refuses_and_does_not_clear_leases(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    legacy = cache / "cc-active-task-eta"
    session = cache / "cc-active-task-eta-sess123"
    legacy_sidecar = cache / "cc-claim-epoch-eta"
    session_sidecar = cache / "cc-claim-epoch-eta-sess123"
    legacy.write_text("foo\n", encoding="utf-8")
    session.write_text("foo\n", encoding="utf-8")
    legacy_sidecar.write_text("1780000000 foo\n", encoding="utf-8")
    session_sidecar.write_text("1780000000 foo\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id="sess123")

    assert result.returncode != 0
    assert "REFUSED" in result.stderr
    assert legacy.read_text(encoding="utf-8") == "foo\n"
    assert session.read_text(encoding="utf-8") == "foo\n"
    assert legacy_sidecar.read_text(encoding="utf-8") == "1780000000 foo\n"
    assert session_sidecar.read_text(encoding="utf-8") == "1780000000 foo\n"


def test_unclaimed_close_preserves_session_lease_naming_a_different_task(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    session = cache / "cc-active-task-eta-sess123"
    sidecar = cache / "cc-claim-epoch-eta-sess123"
    session.write_text("other-task\n", encoding="utf-8")
    sidecar.write_text("1780000000 other-task\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id="sess123")

    assert result.returncode != 0
    assert session.read_text(encoding="utf-8").strip() == "other-task"
    assert sidecar.read_text(encoding="utf-8").strip() == "1780000000 other-task"


def test_close_without_session_id_refuses_and_does_not_clear_legacy(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    legacy = cache / "cc-active-task-eta"
    legacy.write_text("foo\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id=None)

    assert result.returncode == 2
    assert "terminal_close_identity_missing" in result.stderr
    assert legacy.read_text(encoding="utf-8") == "foo\n"
