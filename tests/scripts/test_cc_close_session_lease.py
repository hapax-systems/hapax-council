"""cc-close has no shell-level lease or note mutation path."""

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


def test_unadmitted_withdrawal_preserves_all_claim_state(tmp_path: Path) -> None:
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

    assert result.returncode == 2
    assert "terminal_close_operator_disposition_receipt_required" in result.stderr
    assert legacy.read_text(encoding="utf-8") == "foo\n"
    assert session.read_text(encoding="utf-8") == "foo\n"
    assert legacy_sidecar.read_text(encoding="utf-8") == "1780000000 foo\n"
    assert session_sidecar.read_text(encoding="utf-8") == "1780000000 foo\n"
    assert (vault / "active" / "foo.md").exists()
    assert not (vault / "closed" / "foo.md").exists()


def test_unadmitted_close_preserves_lease_naming_a_different_task(
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

    assert result.returncode == 2
    assert session.exists(), "a session lease for different work must not be clobbered"
    assert sidecar.exists(), "a sidecar for different work must not be clobbered"
    assert session.read_text(encoding="utf-8").strip() == "other-task"


def test_close_without_session_id_preserves_legacy_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    legacy = cache / "cc-active-task-eta"
    legacy.write_text("foo\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id=None)

    assert result.returncode == 2
    assert legacy.read_text(encoding="utf-8") == "foo\n"
    assert (vault / "active" / "foo.md").exists()


def test_raw_retroactive_and_bypass_environment_cannot_mutate(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    note = _write_task(vault, "foo")
    cache = _cache(home)
    claim = cache / "cc-active-task-eta"
    claim.write_text("foo\n", encoding="utf-8")
    before_note = note.read_bytes()
    before_claim = claim.read_bytes()
    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
    env.update(
        HOME=str(home),
        HAPAX_AGENT_ROLE="eta",
        HAPAX_SESSION_ID="sess123",
        HAPAX_CANON_ECHO_ENFORCEMENT="0",
        HAPAX_CANON_BOUND_CLOSE_ENFORCEMENT="0",
        HAPAX_RAPID_CLOSE_OFF="1",
        HAPAX_CC_TASK_CLOSURE_GATE_OFF="1",
        HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF="1",
        HAPAX_PR_MERGE_GATE_OFF="1",
    )
    result = subprocess.run(
        ["bash", str(SCRIPT), "foo", "--retroactive"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "raw --retroactive is retired" in result.stderr
    assert note.read_bytes() == before_note
    assert claim.read_bytes() == before_claim
