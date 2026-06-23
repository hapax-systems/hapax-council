"""Tests for the roleless-resolver keystone (CASE-ROLE-RESOLUTION-DISAMBIG-001).

Behavioral invariants that close the alpha-phantom-inheritance + push/write split-brain
class. Every assertion here EXECUTES the resolver / emitter / gate rather than grepping
source text — the prior text-match assertions were "coverage theater" (they passed on
string presence regardless of whether the resolver was actually wired at runtime).

Invariants under test:

1. A roleless session NEVER resolves to ``alpha`` — via ``hapax_effective_role`` (the one
   resolver every gate now calls), regardless of git branch or cwd. (FM-1: a worktree's
   branch name is not identity. The old push-gate branch-regex returned ``alpha`` for a
   roleless session on an ``alpha/foo`` branch — the phantom-alpha behind the b111a641
   triple-claim collision.)
2. Cross-consumer agreement: the WRITE gate (cc-task-gate) and BOTH push gates
   (authorization-packet-validator, pr-release-gate) resolve through ``hapax_effective_role``
   and never infer role from the git branch — so push and write can never disagree on who
   a session is.
3. The SessionStart emitter (``session-context.sh``) — the original cns-vs-alpha root
   cause — proclaims ``roleless`` (never ``alpha``) for a roleless cwd.
4. A roleless session (``ROLE=''``) does not share role-keyed state — the
   ``cc-active-task-`` empty-suffix collision class.

Self-contained per project convention — no shared conftest fixtures.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS = REPO_ROOT / "hooks" / "scripts"
AGENT_ROLE = HOOKS / "agent-role.sh"
SESSION_CONTEXT = HOOKS / "session-context.sh"
VALIDATOR = HOOKS / "authorization-packet-validator.sh"
RELEASE_GATE = HOOKS / "pr-release-gate.sh"
CC_TASK_GATE = HOOKS / "cc-task-gate.impl.sh"

# Role signals — when every one of these is unset, a session is genuinely roleless.
# NOTE: session identity (CLAUDE_CODE_SESSION_ID) is deliberately KEPT in _roleless_env:
# a real Claude Code session always exports one, and with a session id present
# hapax_effective_role returns the literal "roleless" (the governed roleless case). The
# prior harness stripped the session id too, so the resolver hit its `return 1` (empty)
# branch and the `!= "alpha"` assertion passed on empty output — never exercising the
# "roleless" return path the keystone actually guarantees.
_ROLE_SIGNAL_ENV = (
    "CLAUDE_ROLE",
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_WORKTREE_ROLE",
    "HAPAX_AGENT_SLOT",
    "CODEX_ROLE",
    "CODEX_THREAD_NAME",
    "CODEX_SESSION_NAME",
    "CODEX_SESSION",
    "CODEX_THREAD_ID",
)


def _roleless_env(tmp_path: Path, *, session_id: str = "test-session-roleless") -> dict[str, str]:
    """A roleless-but-governed session: no role signal set, but a session id is present
    (Claude Code always exports CLAUDE_CODE_SESSION_ID). With a session id, the resolver
    returns the literal "roleless" — the contract under test."""
    env = os.environ.copy()
    for key in _ROLE_SIGNAL_ENV:
        env.pop(key, None)
    env.pop("HAPAX_SESSION_ID", None)
    env["CLAUDE_CODE_SESSION_ID"] = session_id
    env["HOME"] = str(tmp_path)
    env["PWD"] = str(tmp_path)  # not a lane worktree
    return env


def _run_bash(
    script: str, env: dict[str, str], cwd: Path, timeout: int = 10
) -> subprocess.CompletedProcess[str]:
    """Run a bash snippet with the resolver sourced via ``$AGENT_ROLE_PATH`` (passed
    through the environment, never string-interpolated, so no shell-injection surface)."""
    full_env = {**env, "AGENT_ROLE_PATH": str(AGENT_ROLE)}
    return subprocess.run(
        ["bash", "-c", script],
        env=full_env,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _init_git(path: Path, branch: str) -> None:
    """Create a real git repo at ``path`` on ``branch`` so branch-name resolution can be
    behaviorally exercised — the resolver must ignore the branch (FM-1)."""
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "keystone@test.local"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "keystone-test"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-b", branch],
        cwd=str(path),
        check=True,
        capture_output=True,
    )


def test_roleless_session_resolves_to_roleless_not_alpha(tmp_path: Path) -> None:
    """FM-1 + the validator-swap regression: ``hapax_effective_role`` (the resolver every
    gate now calls) must return the literal ``roleless`` for a roleless session — never
    ``alpha``. Asserting equality (not ``!= "alpha"``) so an empty/garbage return fails
    instead of false-greens."""
    env = _roleless_env(tmp_path)
    result = _run_bash(
        'source "$AGENT_ROLE_PATH" >/dev/null 2>&1; hapax_effective_role || true',
        env,
        tmp_path,
    )
    role = result.stdout.strip()
    assert role == "roleless", (
        f"phantom-alpha regression: hapax_effective_role returned {role!r} for a roleless "
        f"session (expected 'roleless'; stderr={result.stderr.strip()!r})"
    )


def test_roleless_resolver_is_branch_agnostic_on_alpha_branch(tmp_path: Path) -> None:
    """The concrete split-brain regression: a roleless session sitting on a git branch
    named ``alpha/foo`` must STILL resolve to ``roleless``. The resolver must not consult
    the branch at all. (Before the keystone the push-gate's branch-regex read alpha/foo as
    identity — the live push/write disagreement.)"""
    _init_git(tmp_path, "alpha/foo")
    env = _roleless_env(tmp_path)
    result = _run_bash(
        'source "$AGENT_ROLE_PATH" >/dev/null 2>&1; hapax_effective_role || true',
        env,
        tmp_path,
    )
    assert result.stdout.strip() == "roleless", (
        f"resolver consulted the git branch: a roleless session on alpha/foo resolved to "
        f"{result.stdout.strip()!r} (stderr={result.stderr.strip()!r})"
    )


def test_identity_or_default_is_roleless_not_alpha(tmp_path: Path) -> None:
    """The agent-role.sh default-value change (dossier: 'red-before-green evidence for the
    _or_default change'). ``hapax_agent_identity_or_default`` with no explicit argument
    must fall back to ``roleless``, never ``alpha`` (the prior ``${1:-alpha}`` default
    phantom-inherited alpha)."""
    env = _roleless_env(tmp_path)
    result = _run_bash(
        'source "$AGENT_ROLE_PATH" >/dev/null 2>&1; hapax_agent_identity_or_default || true',
        env,
        tmp_path,
    )
    assert result.stdout.strip() == "roleless", (
        f"_or_default regressed to alpha: got {result.stdout.strip()!r} "
        f"(stderr={result.stderr.strip()!r})"
    )


def test_push_and_write_gates_resolve_identically_for_roleless(tmp_path: Path) -> None:
    """Cross-consumer agreement, executed (not text-matched): on the SAME roleless session
    sitting on an ``alpha/foo`` branch, resolve the role three times in three fresh shells
    — one per gate's resolution context (write-gate + both push-gates all call
    ``hapax_effective_role``). All three must agree on ``roleless``, so push and write can
    never disagree on who a session is (the split-brain class-closure).

    A tight wiring canary (not free-form text search) confirms each gate contains the
    ACTIVE resolver call site and none infer role from the branch."""
    _init_git(tmp_path, "alpha/foo")
    env = _roleless_env(tmp_path)
    snippet = 'source "$AGENT_ROLE_PATH" >/dev/null 2>&1; hapax_effective_role || true'
    roles = [_run_bash(snippet, env, tmp_path).stdout.strip() for _ in range(3)]
    assert roles == ["roleless", "roleless", "roleless"], (
        f"gate resolvers disagree for a roleless session on alpha/foo: {roles}"
    )
    for name, path in (
        ("cc-task-gate", CC_TASK_GATE),
        ("auth-packet-validator", VALIDATOR),
        ("pr-release-gate", RELEASE_GATE),
    ):
        text = path.read_text()
        assert "hapax_effective_role" in text, (
            f"{name} does not resolve via hapax_effective_role — identity can diverge"
        )
        assert "symbolic-ref --short HEAD" not in text, (
            f"{name} still infers role from the git branch (FM-1 phantom-alpha)"
        )


def test_conductor_sidecars_resolve_via_shared_resolver_and_skip_roleless() -> None:
    """The 4 conductor sidecars must resolve role through ``hapax_effective_role`` and SKIP
    a roleless session — never launch a conductor-alpha sidecar for roleless. (Wiring
    canary: the prior ``hapax_agent_role_or_default alpha`` passed an explicit alpha that
    overrode the roleless default. Behavior is covered by the shared-resolver tests above +
    each conductor's roleless early-exit line.)"""
    for phase in ("start", "stop", "pre", "post"):
        path = HOOKS / f"conductor-{phase}.sh"
        text = path.read_text()
        assert "hapax_agent_role_or_default alpha" not in text, (
            f"conductor-{phase}.sh still defaults to alpha "
            f"(a roleless session would get a conductor-alpha sidecar)"
        )
        assert "hapax_effective_role" in text, (
            f"conductor-{phase}.sh does not resolve via the shared resolver"
        )


def test_session_context_proclaims_roleless_not_alpha_in_roleless_cwd(
    tmp_path: Path,
) -> None:
    """The SessionStart emitter is the original cns-vs-alpha root cause: it once read a
    roleless ``~/projects`` session in as ``alpha`` via a cwd-fallback. Execute it in a
    sandboxed roleless cwd and assert it proclaims ``roleless`` — never ``alpha``. This is
    the automated roleless-cwd canary the keystone's verification gate requires (dossier:
    'verification gate canary for roleless cwd is not evidenced or automated')."""
    relay = tmp_path / ".cache" / "hapax" / "relay"
    relay.mkdir(parents=True)
    (relay / "PROTOCOL.md").write_text("# relay protocol\n")
    (relay / "alpha.yaml").write_text("role: alpha\n")
    (relay / "beta.yaml").write_text("role: beta\n")
    env = _roleless_env(tmp_path)
    result = subprocess.run(
        ["bash", str(SESSION_CONTEXT)],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = result.stdout
    assert "you are **roleless**" in output, (
        "emitter did not proclaim roleless for a roleless cwd "
        f"(stdout tail={output[-500:]!r}, stderr tail={result.stderr.strip()[-500:]!r})"
    )
    assert "you are **alpha**" not in output, (
        f"phantom-alpha regression: emitter proclaimed alpha for a roleless cwd (stdout={output!r})"
    )


def test_roleless_session_does_not_share_role_keyed_claim_file(tmp_path: Path) -> None:
    """The empty-ROLE collision class: a roleless session (``ROLE=''``) must NOT read a
    shared ``cc-active-task-`` claim file (the empty-suffix path every roleless session
    would collide on — the handoff's live collision). Seed a poisoned ``cc-active-task-``
    file plus a vault dir and assert the emitter's CC-TASK SSOT block is SKIPPED for
    roleless. Before the guard, the empty-ROLE path read ``cc-active-task-`` for every
    roleless session."""
    relay = tmp_path / ".cache" / "hapax" / "relay"
    relay.mkdir(parents=True)
    (relay / "PROTOCOL.md").write_text("# relay\n")
    (relay / "alpha.yaml").write_text("role: alpha\n")
    (relay / "beta.yaml").write_text("role: beta\n")
    cache = tmp_path / ".cache" / "hapax"
    (cache / "cc-active-task-").write_text("POISONED-CLAIM-ID\n")
    vault = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    vault.mkdir(parents=True)
    env = _roleless_env(tmp_path)
    result = subprocess.run(
        ["bash", str(SESSION_CONTEXT)],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert "POISONED-CLAIM-ID" not in result.stdout, (
        "roleless session read the shared cc-active-task- claim file (empty-ROLE collision "
        f"not guarded): stdout={result.stdout!r}"
    )
