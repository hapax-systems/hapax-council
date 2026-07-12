"""cc-close must clear the session-keyed lease, not just the legacy one.

cc-claim (reform Phase 1, cluster 6) writes TWO claim files for a session:
the legacy ``cc-active-task-<role>`` and the session-keyed
``cc-active-task-<role>-<session_id>`` (agent-role.sh ``hapax_session_id``).
cc-close historically removed only the legacy file, leaking the session-keyed
lease until its 6h TTL — and the gate reads the session-keyed file FIRST, so it
kept seeing the just-closed task. Regression coverage for reform finding
#12/#13: cc-close must clear BOTH lease forms (the current session's only, and
only when the file still names the task being closed).
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-close"

# Identity env that agent-role.sh consults to resolve role / session id. The
# session running pytest sets several of these (HAPAX_AGENT_NAME, CLAUDE_ROLE,
# CLAUDE_CODE_SESSION_ID, ...); stripping them keeps the subprocess role/session
# deterministic instead of leaking the harness lane's identity into the script.
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
    # --status withdrawn isolates the claim-clearing block (the done-only gates —
    # rapid-close, AC checklist, PR-merge — are skipped; the claim clear runs for
    # every terminal status).
    return subprocess.run(
        ["bash", str(SCRIPT), task_id, "--status", "withdrawn"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cc_close_clears_both_legacy_and_session_keyed_lease(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    legacy = cache / "cc-active-task-eta"
    session = cache / "cc-active-task-eta-sess123"
    legacy_sidecar = cache / "cc-claim-epoch-eta"
    session_sidecar = cache / "cc-claim-epoch-eta-sess123"
    legacy_binding = cache / "cc-claim-dispatch-eta.json"
    session_binding = cache / "cc-claim-dispatch-eta-sess123.json"
    legacy.write_text("foo\n", encoding="utf-8")
    session.write_text("foo\n", encoding="utf-8")
    legacy_sidecar.write_text("1780000000 foo\n", encoding="utf-8")
    session_sidecar.write_text("1780000000 foo\n", encoding="utf-8")
    legacy_binding.write_text("{}\n", encoding="utf-8")
    session_binding.write_text("{}\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id="sess123")

    assert result.returncode == 0, result.stderr
    assert not legacy.exists(), f"legacy lease not cleared\nstdout={result.stdout}"
    assert not legacy_sidecar.exists(), f"legacy epoch sidecar leaked\nstdout={result.stdout}"
    assert not session.exists(), (
        f"session-keyed lease leaked (finding #12/#13)\nstdout={result.stdout}"
    )
    assert not session_sidecar.exists(), f"session epoch sidecar leaked\nstdout={result.stdout}"
    assert not legacy_binding.exists(), f"legacy dispatch sidecar leaked\nstdout={result.stdout}"
    assert not session_binding.exists(), f"session dispatch sidecar leaked\nstdout={result.stdout}"


def test_cc_close_preserves_session_lease_naming_a_different_task(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    session = cache / "cc-active-task-eta-sess123"
    sidecar = cache / "cc-claim-epoch-eta-sess123"
    binding = cache / "cc-claim-dispatch-eta-sess123.json"
    session.write_text("other-task\n", encoding="utf-8")
    sidecar.write_text("1780000000 other-task\n", encoding="utf-8")
    binding.write_text("{}\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id="sess123")

    assert result.returncode == 0, result.stderr
    assert session.exists(), "a session lease for different work must not be clobbered"
    assert sidecar.exists(), "a sidecar for different work must not be clobbered"
    assert binding.exists(), "a dispatch sidecar for different work must not be clobbered"
    assert session.read_text(encoding="utf-8").strip() == "other-task"


def test_cc_close_without_session_id_still_clears_legacy(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    legacy = cache / "cc-active-task-eta"
    legacy.write_text("foo\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id=None)

    assert result.returncode == 0, result.stderr
    assert not legacy.exists(), f"legacy lease not cleared\nstdout={result.stdout}"
