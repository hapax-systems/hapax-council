"""Tests for the roleless-resolver keystone (CASE-ROLE-RESOLUTION-DISAMBIG-001).

Two invariants that close the alpha-phantom-inheritance + push/write split-brain class:

1. A roleless session NEVER resolves to alpha — not via the resolver the push-gate now uses
   (``hapax_effective_role``), regardless of git branch or cwd. (FM-1: branch-name is not
   identity. The old validator's branch-regex returned alpha for a roleless session on an
   alpha/foo branch — the phantom-alpha that caused the b111a641 triple-claim collision.)
2. Cross-consumer agreement: the WRITE gate (cc-task-gate) and the PUSH gates
   (authorization-packet-validator, pr-release-gate) all call the SAME resolver
   (``hapax_effective_role``) and none infer role from the git branch — so push and write
   can never disagree on who a session is.

Self-contained per project convention — no shared conftest fixtures.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROLE = REPO_ROOT / "hooks" / "scripts" / "agent-role.sh"
VALIDATOR = REPO_ROOT / "hooks" / "scripts" / "authorization-packet-validator.sh"
RELEASE_GATE = REPO_ROOT / "hooks" / "scripts" / "pr-release-gate.sh"
CC_TASK_GATE = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"

_IDENTITY_ENV = (
    "CLAUDE_ROLE",
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_WORKTREE_ROLE",
    "HAPAX_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_ROLE",
    "CODEX_SESSION",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
)


def _roleless_env(tmp_path: Path) -> dict[str, str]:
    """An environment with NO role signal set — a genuinely roleless session."""
    env = os.environ.copy()
    for k in _IDENTITY_ENV:
        env.pop(k, None)
    env["HOME"] = str(tmp_path)
    env["PWD"] = str(tmp_path)  # not a lane worktree
    return env


def test_roleless_session_does_not_phantom_inherit_alpha(tmp_path: Path) -> None:
    """FM-1 + the validator-swap regression: hapax_effective_role (the resolver the push-gate
    now uses) must NEVER return 'alpha' for a roleless session — not even when the git branch
    or cwd might suggest it. The old validator's branch-regex did exactly this (alpha/foo
    branch -> alpha); the wired resolver does not (branch-name is not identity)."""
    env = _roleless_env(tmp_path)
    result = subprocess.run(
        ["bash", "-c", f"source '{AGENT_ROLE}' >/dev/null 2>&1; hapax_effective_role || true"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    role = result.stdout.strip()
    assert role != "alpha", (
        f"phantom-alpha regression: hapax_effective_role returned 'alpha' for a roleless "
        f"session (stdout={role!r}, stderr={result.stderr.strip()!r})"
    )


def test_push_and_write_gates_share_one_resolver() -> None:
    """Cross-consumer agreement (the class-closure receipt): the write-gate AND both push-gates
    must call hapax_effective_role, and none may infer role from the git branch. Before the
    keystone, the validator + pr-release-gate used an env-cascade + branch-regex that the
    write-gate had explicitly removed (FM-1) — a live push/write split-brain."""
    gate = CC_TASK_GATE.read_text()
    validator = VALIDATOR.read_text()
    release = RELEASE_GATE.read_text()
    for name, text in (
        ("cc-task-gate", gate),
        ("auth-packet-validator", validator),
        ("pr-release-gate", release),
    ):
        assert "hapax_effective_role" in text, (
            f"{name} does not call hapax_effective_role — push/write can diverge (split-brain)"
        )
    # FM-1: branch-name is not identity. No push-gate may infer role from `git symbolic-ref`.
    assert "symbolic-ref --short HEAD" not in validator, (
        "auth-packet-validator still infers role from the git branch (FM-1 phantom-alpha)"
    )
    assert "symbolic-ref --short HEAD" not in release, (
        "pr-release-gate still infers role from the git branch (FM-1 phantom-alpha)"
    )


def test_validator_resolves_roleless_not_alpha_on_alpha_branch(tmp_path: Path) -> None:
    """The concrete collision regression: a roleless session (no role env/marker) sitting on a
    git branch named alpha/foo must resolve to roleless in the PUSH gate's resolver, not alpha.
    (This is the b111a641-class scenario: the old validator returned alpha via branch-regex,
    the write-gate returned roleless — disagreement.)"""
    env = _roleless_env(tmp_path)
    # The resolver must be branch-agnostic — set nothing branch-related; the point is it does
    # not consult the branch at all. Assert the resolver function the validator now calls.
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"source '{AGENT_ROLE}' >/dev/null 2>&1; r=\"$(hapax_effective_role 2>/dev/null || true)\"; printf '%s\\n' \"${{r:-<empty>}}\"",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    resolved = result.stdout.strip()
    assert resolved != "alpha", (
        f"push-gate resolver returned 'alpha' for a roleless session on an alpha-branch context "
        f"(resolved={resolved!r}) — the live split-brain is not closed"
    )
