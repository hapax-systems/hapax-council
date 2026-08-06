"""cc-claim session-identity wiring — taxonomy-a3-session-identity-20260611.

Restored for the canon-bound claim publication path (PR #4483). The predecessor
module was deleted in ``04f4a4934`` when ``cc-claim`` stopped being a frontmatter
mutator and became a dispatch-bound, canon-enforced publication engine
(``shared/sdlc_claim.py``). Two of its four cases asserted behaviour that the new
contract deliberately inverts, which is why it could not survive unchanged — but
the *property* it guarded is unchanged and still load-bearing, so the guard is
restored here against the current contract rather than dropped.

The property: **a session id without per-session entropy must never key a claim.**
Under the old contract a pid-shaped id degraded to a legacy role-keyed claim with
a warning (exit 0). Under canon echo enforcement it is a typed refusal (exit 2).
Either way the invariant is the same — ``cc-active-task-<role>-<pid>`` must not
exist — and this module asserts it on the current path.

The claim FILE format is also still narrow, and still for the same reason:
``scripts/request-intake-consumer`` reads a claim file whole as one task id, and
``scripts/hapax-rte-state`` treats any ``cc-active-task-<lane>-*`` glob hit as a
lease. Widening the file silently unclaims tasks in their accounting.

These cases exercise the refusal contract in ``scripts/cc-claim`` itself, which is
reached before any vault or canon state is consulted — so they are hermetic and
need no canon image, dispatch receipt, or event-log fixture.

Self-contained per project convention — no shared conftest fixtures.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-claim"

_UUID = "12345678-1234-4321-8765-123456789abc"

# Identity inputs that must be cleared so a developer's real session cannot leak
# into a test claim.
_IDENTITY_ENV = (
    "HAPAX_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_SESSION",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
)

# The all-or-none dispatch binding set (scripts/cc-claim:71-87). The idempotency
# key is deliberately NOT a member — it is optional and must not trip all-or-none.
_DISPATCH_ENV = {
    "HAPAX_CLAIM_DISPATCH_MESSAGE_ID": "msg-0001",
    "HAPAX_CLAIM_DISPATCH_BINDING_HASH": "sha256:" + "0" * 64,
    "HAPAX_CLAIM_DISPATCH_PLATFORM": "claude",
    "HAPAX_CLAIM_DISPATCH_MODE": "interactive",
    "HAPAX_CLAIM_DISPATCH_PROFILE": "beta",
    "HAPAX_CLAIM_DISPATCH_AUTHORITY_CASE": "CASE-TEST-001",
}


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


def _claim(
    home: Path,
    task_id: str,
    *,
    session_id: str | None,
    dispatch: dict[str, str] | None = None,
    force: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for var in _IDENTITY_ENV:
        env.pop(var, None)
    for var in _DISPATCH_ENV:
        env.pop(var, None)
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "epsilon"
    if session_id is not None:
        env["HAPAX_SESSION_ID"] = session_id
    if dispatch:
        env.update(dispatch)
    argv = ["bash", str(SCRIPT)]
    if force:
        argv.append("--force")
    argv.append(task_id)
    return subprocess.run(argv, env=env, text=True, capture_output=True, check=False)


def _claim_keys(home: Path) -> list[Path]:
    """Every session-keyed claim file for the test role."""
    cache = home / ".cache" / "hapax"
    if not cache.is_dir():
        return []
    return sorted(cache.glob("cc-active-task-epsilon-*"))


def test_pid_shaped_session_id_is_refused_as_claim_key(tmp_path: Path) -> None:
    """The core invariant, carried over from the pre-canon module.

    A pid-shaped id is the retired ``<role>-$$`` spawner fallback. It has no
    per-session entropy, so two concurrent lanes would mint colliding keys. The
    old contract degraded to legacy role keying; canon echo enforcement refuses
    outright. Both must agree that no ``cc-active-task-epsilon-<pid>`` appears.
    """
    home = tmp_path / "home"
    _write_task(home, "task-pid")
    result = _claim(home, "task-pid", session_id="epsilon-12345", dispatch=_DISPATCH_ENV)

    assert result.returncode == 2, result.stderr
    assert "non-PID session id" in result.stderr
    assert not _claim_keys(home), "a pid-shaped session id must never key a claim file"


def test_missing_session_id_is_refused_under_canon_enforcement(tmp_path: Path) -> None:
    """Was "legacy role-keyed claim only"; is now a typed refusal.

    Canon-bound publication binds a claim to a session, so an unkeyed claim is
    not representable. The predecessor asserted exit 0 with a legacy-only claim.
    """
    home = tmp_path / "home"
    _write_task(home, "task-bare")
    result = _claim(home, "task-bare", session_id=None, dispatch=_DISPATCH_ENV)

    assert result.returncode == 2, result.stderr
    assert "claim-keyable session id" in result.stderr
    assert not _claim_keys(home)


def test_dispatch_binding_is_required(tmp_path: Path) -> None:
    """Claim publication is an operational effect and must echo its dispatch."""
    home = tmp_path / "home"
    _write_task(home, "task-nodispatch")
    result = _claim(home, "task-nodispatch", session_id=_UUID)

    assert result.returncode == 2, result.stderr
    assert "exact dispatch binding flags" in result.stderr
    assert not _claim_keys(home)


def test_dispatch_binding_is_all_or_none(tmp_path: Path) -> None:
    """A partial binding is a distinct, earlier failure than a missing one.

    Distinguishing them matters: a partial binding means the caller built the
    dispatch echo and dropped a field, which is a wiring bug, not a policy stop.
    """
    home = tmp_path / "home"
    _write_task(home, "task-partial")
    partial = {"HAPAX_CLAIM_DISPATCH_MESSAGE_ID": "msg-0001"}
    result = _claim(home, "task-partial", session_id=_UUID, dispatch=partial)

    assert result.returncode == 1, result.stderr
    assert "all-or-none" in result.stderr
    assert not _claim_keys(home)


def test_force_is_retired_under_canon_enforcement(tmp_path: Path) -> None:
    """``--force`` used to steal a lease; a governed transition replaces it."""
    home = tmp_path / "home"
    _write_task(home, "task-force")
    result = _claim(
        home,
        "task-force",
        session_id=_UUID,
        dispatch=_DISPATCH_ENV,
        force=True,
    )

    assert result.returncode == 2, result.stderr
    assert "retired under canon echo enforcement" in result.stderr
    assert not _claim_keys(home)


def test_idempotency_key_alone_does_not_satisfy_the_binding(tmp_path: Path) -> None:
    """The idempotency key is outside the all-or-none set.

    It is accepted alongside a full binding but must not by itself look like one,
    or a caller could pass only the key and reach publication unbound.
    """
    home = tmp_path / "home"
    _write_task(home, "task-idem")
    result = _claim(
        home,
        "task-idem",
        session_id=_UUID,
        dispatch={"HAPAX_CLAIM_DISPATCH_IDEMPOTENCY_KEY": "idem-0001"},
    )

    assert result.returncode == 2, result.stderr
    assert "exact dispatch binding flags" in result.stderr
    assert not _claim_keys(home)
