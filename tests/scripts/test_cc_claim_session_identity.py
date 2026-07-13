"""cc-claim session-identity wiring — taxonomy-a3-session-identity-20260611.

The claim surface must carry the session id (FM-2 session-keyed file) without
ever widening the claim FILE format: out-of-scope readers
(scripts/request-intake-consumer reads the whole file as one task id;
scripts/hapax-rte-state treats any ``cc-active-task-<lane>-*`` glob hit as a
lease) require claim files to stay a single task-id line. Identity rides in
the session-keyed FILENAME and the task note's session log, never in extra
claim-file lines.

Claim-by-pid unrepresentable: a pid-shaped session id (the retired
``<role>-$$`` launcher fallback) must be refused as a claim key — legacy
role-keyed claim only, with a warning.

Self-contained per project convention — no shared conftest fixtures.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-claim"

_UUID = "12345678-1234-4321-8765-123456789abc"

_IDENTITY_ENV = (
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_AGENT_INTERFACE",
    "HAPAX_SESSION_ID",
    "CLAUDE_ROLE",
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_SESSION",
    "CODEX_SESSION_NAME",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
    "CODEX_ROLE",
    "CODEX_HOME",
)


def _write_task(home: Path, task_id: str) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    path = root / "active" / f"{task_id}.md"
    path.write_text(
        "\n".join(
            [
                "---",
                "type: cc-task",
                f"task_id: {task_id}",
                f'title: "{task_id}"',
                "status: offered",
                "assigned_to: unassigned",
                "kind: build",
                "authority_case: CASE-TEST-001",
                "parent_spec: /tmp/isap-test.md",
                "depends_on: []",
                "created_at: 2026-05-09T00:00:00Z",
                "updated_at: 2026-05-09T00:00:00Z",
                "claimed_at: null",
                "---",
                "",
                f"# {task_id}",
                "",
                "## Session log",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _claim(home: Path, task_id: str, *, session_id: str | None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for var in _IDENTITY_ENV:
        env.pop(var, None)
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "epsilon"
    if session_id is not None:
        env["HAPAX_SESSION_ID"] = session_id
    return subprocess.run(
        ["bash", str(SCRIPT), task_id],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_keyable_session_id_writes_single_line_session_keyed_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "task-sid")
    result = _claim(home, "task-sid", session_id=_UUID)
    assert result.returncode == 0, result.stderr

    legacy = home / ".cache" / "hapax" / "cc-active-task-epsilon"
    keyed = home / ".cache" / "hapax" / f"cc-active-task-epsilon-{_UUID}"
    assert legacy.read_text(encoding="utf-8") == "task-sid\n"
    assert keyed.read_text(encoding="utf-8") == "task-sid\n"
    # Single-line invariant: request-intake-consumer reads the WHOLE file as a
    # task id; any extra line silently unclaims the task in its accounting.
    for claim_file in (legacy, keyed):
        assert len(claim_file.read_text(encoding="utf-8").splitlines()) == 1


def test_session_log_line_carries_session_id(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "task-log")
    result = _claim(home, "task-log", session_id=_UUID)
    assert result.returncode == 0, result.stderr

    text = note.read_text(encoding="utf-8")
    assert f"claimed (cc-claim, session={_UUID})" in text


def test_pid_shaped_session_id_is_refused_as_claim_key(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "task-pid")
    # The exact shape the pre-fix launcher fallback minted: <role>-$$.
    result = _claim(home, "task-pid", session_id="epsilon-12345")
    assert result.returncode == 8

    cache = home / ".cache" / "hapax"
    assert not list(cache.glob("cc-active-task-epsilon*"))
    assert "not claim-keyable" in result.stderr
    # An unkeyable id must not be stamped into the session log either.
    note_text = (
        home
        / "Documents"
        / "Personal"
        / "20-projects"
        / "hapax-cc-tasks"
        / "active"
        / "task-pid.md"
    ).read_text(encoding="utf-8")
    assert "session=epsilon-12345" not in note_text


def test_whitespace_wrapped_session_id_is_refused_before_any_claim_write(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "task-whitespace")

    result = _claim(home, "task-whitespace", session_id=f" {_UUID} ")

    assert result.returncode == 8
    assert "not claim-keyable" in result.stderr
    assert "status: offered" in note.read_text(encoding="utf-8")
    cache = home / ".cache" / "hapax"
    assert not list(cache.glob("cc-active-task-epsilon*"))


def test_no_session_id_still_claims_legacy_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "task-bare")
    result = _claim(home, "task-bare", session_id=None)
    assert result.returncode == 0, result.stderr

    cache = home / ".cache" / "hapax"
    assert (cache / "cc-active-task-epsilon").read_text(encoding="utf-8") == "task-bare\n"
    assert not list(cache.glob("cc-active-task-epsilon-*"))
