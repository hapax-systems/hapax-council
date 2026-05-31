"""Daemon-independent conservative enforcement floor (master design section 4.1, NEW-CATCH-2).

When the SBCL coordination kernel is DOWN, the bash hook shim evaluates this
embedded floor instead of calling ``policy-decide`` over the UDS. It fail-CLOSES
exactly the irreversible-harm classes — release, egress, axiom, merge — and
fail-OPENS-with-ledger everything else, so a dead kernel never wedges reversible
work yet can never silently permit irreversible harm.

This is deliberately a small, pure, dependency-light function with its own test
suite: a bug anywhere else in the kernel must not be able to weaken the floor.
It classifies only the executed command head / edit path (never substring-matches
arbitrary argument bodies — FM-16).
"""

from __future__ import annotations

import argparse
import json
import re
import shlex

from shared.policy_decision import Decision, FailMode, Verdict

# --- Irreversible-harm classifiers (command head + edit path) -----------------

#: Constitutional governance surfaces — never mutate with the kernel down.
_AXIOM_PATH_RE = re.compile(r"(?:^|/)(?:axioms|shared/governance)/")

#: MCP tool names that publish or merge.
_MERGE_TOOLS = frozenset({"mcp__github__merge_pull_request"})
_RELEASE_TOOLS = frozenset({"mcp__github__create_pull_request", "mcp__github__push_files"})

#: External-egress markers (publication bus surfaces / publish entrypoints).
_EGRESS_PATH_RE = re.compile(r"(?:^|/)config/publication-hardening/")
_EGRESS_CMD_RE = re.compile(r"^(?:hapax-)?publish[-_a-z]*$|^hapax-publish")


def _head_tokens(command: str) -> list[str]:
    """Tokenize the FIRST simple command (up to a ; | && separator). Best-effort."""
    if not command:
        return []
    # Cut at the first shell control operator so we classify only the head.
    head = re.split(r"[;&|]|\n", command, maxsplit=1)[0]
    try:
        return shlex.split(head)
    except ValueError:
        return head.split()


def _is_merge(tool_name: str, tokens: list[str]) -> bool:
    if tool_name in _MERGE_TOOLS:
        return True
    if "gh" in tokens and "pr" in tokens and "merge" in tokens:
        return True
    # gh api ... pulls/<n>/merge
    return (
        "gh" in tokens and "api" in tokens and any("/merge" in t and "pulls" in t for t in tokens)
    )


def _is_release(tool_name: str, tokens: list[str]) -> bool:
    if tool_name in _RELEASE_TOOLS:
        return True
    if "gh" in tokens and "pr" in tokens and "create" in tokens:
        return True
    # git push to a protected/default branch
    return "git" in tokens and "push" in tokens and any(t in {"main", "master"} for t in tokens)


def _is_axiom(tokens: list[str], file_path: str) -> bool:
    if file_path and _AXIOM_PATH_RE.search(file_path):
        return True
    return any(_AXIOM_PATH_RE.search(t) for t in tokens)


def _is_egress(tokens: list[str], file_path: str) -> bool:
    if file_path and _EGRESS_PATH_RE.search(file_path):
        return True
    return bool(tokens) and bool(_EGRESS_CMD_RE.search(tokens[0]))


def _blocked(gate: str, reason: str) -> Decision:
    return Decision(
        verdict=Verdict.BLOCK,
        gate=gate,
        reason=reason,
        fail_mode=FailMode.FAIL_CLOSED,
        remediation_verb="wait for the kernel, or obtain an operator escape grant",
    )


def evaluate_floor(tool_name: str, *, command: str = "", file_path: str = "") -> Decision:
    """Decide allow/block for a tool-call using ONLY the conservative floor.

    Never raises. Irreversible-harm classes (merge/release/axiom/egress) fail
    CLOSED; everything else fails OPEN with a ledger marker.
    """
    try:
        tokens = _head_tokens(command)
        if _is_merge(tool_name, tokens):
            return _blocked("floor:merge", "merge is irreversible and the kernel is down")
        if _is_release(tool_name, tokens):
            return _blocked(
                "floor:release", "release/PR-create is irreversible and the kernel is down"
            )
        if _is_axiom(tokens, file_path):
            return _blocked(
                "floor:axiom", "axiom/governance mutation is constitutional and the kernel is down"
            )
        if _is_egress(tokens, file_path):
            return _blocked(
                "floor:egress", "external egress is irreversible and the kernel is down"
            )
    except Exception:  # noqa: BLE001 — the floor must never raise; degrade to fail-closed.
        return _blocked("floor:error", "floor classifier raised; failing closed for safety")
    return Decision(
        verdict=Verdict.ALLOW,
        gate="floor:reversible",
        reason="reversible op; kernel down — fail-open with ledger",
        fail_mode=FailMode.FAIL_OPEN_WITH_LEDGER,
    )


def main(argv: list[str] | None = None) -> int:
    """Daemon-independent CLI the hook shim invokes when the kernel is down.

    `python3 -m shared.policy_floor <tool_name> [--command CMD] [--file PATH]`
    prints the Decision as JSON and exits 0 (allow) / 2 (block) — the exit
    convention the PreToolUse hooks already use, so the shim can fall back to
    this floor without an RPC to a process that may be dead.
    """
    parser = argparse.ArgumentParser(prog="policy_floor")
    parser.add_argument("tool_name")
    parser.add_argument("--command", default="")
    parser.add_argument("--file", dest="file_path", default="")
    args = parser.parse_args(argv)
    decision = evaluate_floor(args.tool_name, command=args.command, file_path=args.file_path)
    print(
        json.dumps(
            {
                "verdict": decision.verdict.value,
                "gate": decision.gate,
                "reason": decision.reason,
                "fail_mode": decision.fail_mode.value,
                "remediation_verb": decision.remediation_verb,
                "policy_version": decision.policy_version,
            }
        )
    )
    return 0 if decision.allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
