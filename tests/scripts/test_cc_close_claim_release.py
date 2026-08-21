"""cc-close must release the claim of the session that is actually claiming it.

The claim plane has three participants and one fact — *which role holds this
claim*:

* the WRITER, ``cc-claim``, which binds role via ``hapax_effective_role``
* the READER, ``cc-task-gate.impl.sh``, which binds role via ``hapax_effective_role``
* the RELEASER, ``cc-close``, which bound role via ``hapax_agent_identity``

Those two resolvers agree for every session that carries an explicit role, and
disagree for exactly one case: a session with a session id but no role signal.
``hapax_agent_identity`` returns EMPTY there; ``hapax_effective_role`` returns
the literal ``roleless``. ``cc-close`` guards its whole claim-release block with
``[[ -n "$role" ]]``, so with the divergent resolver the block was skipped, the
lease survived the close, and the gate — resolving through the other function —
found a lease naming a task that had just moved to ``closed/`` and blocked every
subsequent mutation with ``claimed task not found in vault``.

Measured twice on 2026-08-21, both times immediately after a *clean* close: a
session that finished its work correctly ended up worse off than one that
abandoned it, and both recoveries needed the operator.

``tests/scripts/test_cc_close_session_lease.py`` already pins the release LOOP
(reform finding #12/#13) but sets ``HAPAX_AGENT_ROLE=eta`` in every case, so
``$role`` is never empty and the guard above the loop is never exercised. The
repair was applied at the loop; the failure moved one level up to the binding.
These tests drive the roleless case end to end instead: real ``cc-close``, real
gate, real vault layout.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CC_CLOSE = REPO_ROOT / "scripts" / "cc-close"
GATE = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"

TASK_ID = "roleless-close-cycle"
SESSION_ID = "sess-roleless-e2e"
STRAND_MESSAGE = "not found in vault"
# The gate's post-close state for a session that closed correctly: no claim held, and
# the role still resolves. Recoverable — the session can claim again — and distinct
# from the strand, where a lease points at a task that no longer exists in active/.
RECOVERABLE_DENIAL = "no claimed task for role 'roleless'"

# Every signal agent-role.sh consults to resolve an explicit role. The session
# running pytest sets several of these; stripping them is what makes the
# subprocess genuinely roleless rather than inheriting the harness lane.
_ROLE_SIGNAL_ENV = (
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_AGENT_INTERFACE",
    "HAPAX_WORKTREE_ROLE",
    "HAPAX_AGENT_SLOT",
    "CLAUDE_ROLE",
    "CODEX_THREAD_NAME",
    "CODEX_SESSION_NAME",
    "CODEX_SESSION",
    "CODEX_ROLE",
    "CODEX_HOME",
)

# A PATH without ~/.local/bin: `hapax-whoami` is an identity source of last
# resort inside hapax_agent_identity, and letting the operator's real one
# answer would make "roleless" depend on the developer's window manager.
_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def _env(home: Path, *, session_id: str | None = SESSION_ID) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _ROLE_SIGNAL_ENV}
    env.pop("HAPAX_SESSION_ID", None)
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    env["HOME"] = str(home)
    env["PATH"] = _SYSTEM_PATH
    # XDG_RUNTIME_DIR into the sandbox so the `systemctl --user start
    # hapax-cc-hygiene.service` that follows a successful clear cannot reach the
    # operator's real session bus. A test must not start live units.
    env["XDG_RUNTIME_DIR"] = str(home / "run")
    env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    if session_id is not None:
        env["HAPAX_SESSION_ID"] = session_id
    return env


def _vault(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    (home / "run").mkdir(parents=True, exist_ok=True)
    return root


def _write_task(vault_root: Path, scope_ref: str) -> Path:
    """An authorized, roleless-claimed task — the shape the gate ACCEPTS, so the
    pre-close leg of the cycle proves the gate permits rather than merely
    failing differently."""
    path = vault_root / "active" / f"{TASK_ID}.md"
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {TASK_ID}
            title: "{TASK_ID}"
            status: in_progress
            assigned_to: roleless
            priority: p2
            authority_case: CASE-SYSTEM-INTEGRITY-20260611
            parent_spec: 30-areas/hapax/synthesis-representation-without-enforcement-2026-08-20.md
            route_metadata_schema: 1
            stage: S6_IMPLEMENTING
            implementation_authorized: true
            source_mutation_authorized: true
            mutation_scope_refs:
              - {scope_ref}
            completed_at:
            updated_at:
            pr:
            ---

            # {TASK_ID}

            ## Session log
            """
        ),
        encoding="utf-8",
    )
    return path


def _seed_claim(home: Path, *, task_id: str = TASK_ID) -> dict[str, Path]:
    """Both lease forms cc-claim writes: the legacy <role> file and the
    session-keyed <role>-<sid> file, each with its cc-claim-epoch sidecar."""
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    files = {
        "legacy": cache / "cc-active-task-roleless",
        "legacy_epoch": cache / "cc-claim-epoch-roleless",
        "session": cache / f"cc-active-task-roleless-{SESSION_ID}",
        "session_epoch": cache / f"cc-claim-epoch-roleless-{SESSION_ID}",
    }
    for name, path in files.items():
        if name.endswith("epoch"):
            path.write_text(f"1780000000 {task_id}\n", encoding="utf-8")
        else:
            path.write_text(f"{task_id}\n", encoding="utf-8")
    return files


def _run_close(
    home: Path, script: Path = CC_CLOSE, *, task_id: str = TASK_ID
) -> subprocess.CompletedProcess[str]:
    # --status withdrawn isolates the claim-release block: the done-only gates
    # (rapid-close, AC checklist, PR-merge evidence) are skipped, while the
    # release runs for every terminal status.
    return subprocess.run(
        ["bash", str(script), task_id, "--status", "withdrawn"],
        env=_env(home),
        cwd=str(home),  # not a git repo: no path-inferred role (FM-1)
        text=True,
        capture_output=True,
        check=False,
    )


def _run_gate(home: Path, target: Path) -> subprocess.CompletedProcess[str]:
    """Drive the real gate the way Claude Code does: a PreToolUse JSON payload
    on stdin. Exit 2 is a block; the message is on stderr."""
    payload = json.dumps(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(target),
                "old_string": "a",
                "new_string": "b",
            },
        }
    )
    return subprocess.run(
        ["bash", str(GATE)],
        input=payload,
        env=_env(home),
        cwd=str(home),
        text=True,
        capture_output=True,
        check=False,
    )


def _divergent_cc_close(tmp_path: Path) -> Path:
    """A copy of the real cc-close with ONLY the resolver reverted to
    hapax_agent_identity — the mutation, encoded as a fixture so the causal link
    is pinned by the suite instead of by a one-off manual check.

    Layout is preserved (scripts/ beside hooks/) because cc-close resolves its
    helpers through $SCRIPT_DIR/../hooks/scripts.
    """
    root = tmp_path / "divergent"
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "hooks").symlink_to(REPO_ROOT / "hooks", target_is_directory=True)

    text = CC_CLOSE.read_text(encoding="utf-8")
    fixed = (
        'if [[ -z "$role" ]] && declare -F hapax_effective_role >/dev/null 2>&1; then\n'
        '  role="$(hapax_effective_role 2>/dev/null || true)"\n'
        "fi"
    )
    reverted = (
        'if [[ -z "$role" ]] && declare -F hapax_agent_identity >/dev/null 2>&1; then\n'
        '  role="$(hapax_agent_identity 2>/dev/null || true)"\n'
        "fi"
    )
    assert text.count(fixed) == 1, (
        "cc-close no longer binds role through hapax_effective_role exactly once — "
        "this mutation fixture is stale and is no longer proving anything"
    )
    dest = root / "scripts" / "cc-close"
    dest.write_text(text.replace(fixed, reverted), encoding="utf-8")
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR)
    return dest


def test_a_roleless_session_resolves_to_roleless_not_empty(tmp_path: Path) -> None:
    """The precondition the whole cycle rests on, asserted rather than assumed:
    in this harness the two resolvers really do disagree."""
    home = tmp_path / "home"
    _vault(home)
    snippet = (
        'source "$AGENT_ROLE_PATH" >/dev/null 2>&1; '
        'printf "identity=[%s] effective=[%s]" '
        '"$(hapax_agent_identity 2>/dev/null || true)" '
        '"$(hapax_effective_role 2>/dev/null || true)"'
    )
    env = {**_env(home), "AGENT_ROLE_PATH": str(REPO_ROOT / "hooks/scripts/agent-role.sh")}
    result = subprocess.run(
        ["bash", "-c", snippet],
        env=env,
        cwd=str(home),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.stdout.strip() == "identity=[] effective=[roleless]", (
        f"harness is not exercising the roleless divergence: {result.stdout!r}"
    )


def test_roleless_close_clears_its_own_lease(tmp_path: Path) -> None:
    """(a) + (b): the close announces the session-keyed path it cleared, and
    every lease form — claim file and cc-claim-epoch sidecar, session-keyed and
    legacy — is gone afterwards."""
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, str(home / "scratch.txt"))
    files = _seed_claim(home)

    result = _run_close(home)

    assert result.returncode == 0, result.stderr
    assert "cleared claim file" in result.stdout, (
        f"close did not announce a claim release\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert str(files["session"]) in result.stdout, (
        f"close cleared something, but not the session-keyed lease the gate reads "
        f"FIRST\nstdout={result.stdout}"
    )
    for name, path in files.items():
        assert not path.exists(), f"{name} lease leaked past the close: {path}"


def test_gate_permits_before_the_close_and_is_not_stranded_after(tmp_path: Path) -> None:
    """(c), end to end and in both directions: with the claim held the gate
    PERMITS the in-scope mutation; once the task is closed the gate must not
    report the strand.

    After a correct close the session holds no claim, so a protected mutation is
    refused — but for the RECOVERABLE reason (no claim held, role still resolving),
    never because a lease points at a task that no longer exists in active/. Both
    the return code and that exact reason are asserted, so this leg cannot pass on
    an unrelated failure or on a reworded strand message.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    target = home / "scratch.txt"
    target.write_text("a\n", encoding="utf-8")
    _write_task(vault, str(target))
    _seed_claim(home)

    before = _run_gate(home, target)
    assert before.returncode == 0, (
        "gate refused an in-scope mutation while the claim was held — the "
        f"post-close leg would prove nothing\nstderr={before.stderr}"
    )

    closed = _run_close(home)
    assert closed.returncode == 0, closed.stderr

    after = _run_gate(home, target)
    # Assert the CONCRETE post-close outcome, not merely the absence of a string.
    # Absence alone accepted any denial at all — an unrelated earlier failure, or a
    # reworded strand message, would have left this leg green while the session was
    # just as stuck. (Raised independently by two review seats.)
    #
    # Measured post-close state: rc 2, "no claimed task for role 'roleless'". That is
    # the RECOVERABLE denial and the assertion is deliberately on that exact reason:
    # the session holds no claim, which is correct after a close, and the gate names
    # the role — proving both that the lease was cleared and that the gate still
    # resolves this session's identity rather than losing it.
    assert after.returncode == 2, (
        f"unexpected post-close gate outcome rc={after.returncode}; the recoverable "
        f"denial is what this asserts\nstderr={after.stderr}"
    )
    assert RECOVERABLE_DENIAL in after.stderr, (
        "gate did not report the recoverable no-claim state after the close — it "
        f"failed for some other reason, so this leg proves nothing\nstderr={after.stderr}"
    )
    assert STRAND_MESSAGE not in after.stderr, (
        "session is stranded behind its own closed task: the lease survived the "
        f"close and the gate still reads it\nstderr={after.stderr}"
    )


def test_the_divergent_resolver_reproduces_the_strand(tmp_path: Path) -> None:
    """(d): the mutation. Revert ONLY the resolver and the same cycle must strand
    — the lease survives and the gate reports exactly the failure the operator
    hit twice. A test that stays green when the fix is removed is documentation,
    not verification.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    target = home / "scratch.txt"
    target.write_text("a\n", encoding="utf-8")
    _write_task(vault, str(target))
    files = _seed_claim(home)

    result = _run_close(home, _divergent_cc_close(tmp_path))
    assert result.returncode == 0, result.stderr

    assert files["session"].exists(), (
        "the divergent resolver did NOT leak the lease — the mutation fixture no "
        "longer reproduces the defect, so the tests above are not pinned by it"
    )
    assert "cleared claim file" not in result.stdout

    after = _run_gate(home, target)
    assert after.returncode == 2 and STRAND_MESSAGE in after.stderr, (
        "expected the leaked lease to strand the session under the divergent "
        f"resolver\nrc={after.returncode}\nstderr={after.stderr}"
    )
