"""Route/resource receipt gate for side-effecting local shell tools.

Read-only shell evidence is allowed under the normal claimed-task workflow.
Shell tools that control processes, mutate external state, publish, browse, or
otherwise consume governed local-tool capability require the same route decision
and task-bound route-authority receipt evidence as connector mutations.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.mcp_connector_policy import (
    _latest_route_decision,
    _load_route_receipts,
    _receipt_root,
    _route_decision_refusal,
    _sequence,
)

EFFECT_READ_ONLY = "read_only_evidence"
EFFECT_FILESYSTEM_MUTATION = "filesystem_mutation"
EFFECT_LOCAL_MUTATION = "local_mutation"
EFFECT_PROCESS_CONTROL = "process_control"
EFFECT_EXTERNAL_STATE = "external_state"
EFFECT_PUBLIC_EGRESS = "public_egress"
EFFECT_BROWSER_AUTOMATION = "browser_automation"
EFFECT_PROVIDER_SPEND = "provider_spend"
EFFECT_GOVERNANCE = "governance_mutation"

MUTATING_EFFECTS = frozenset(
    {
        EFFECT_LOCAL_MUTATION,
        EFFECT_PROCESS_CONTROL,
        EFFECT_EXTERNAL_STATE,
        EFFECT_PUBLIC_EGRESS,
        EFFECT_BROWSER_AUTOMATION,
        EFFECT_PROVIDER_SPEND,
        EFFECT_GOVERNANCE,
    }
)

EFFECT_TO_SURFACE = {
    EFFECT_LOCAL_MUTATION: "local",
    EFFECT_FILESYSTEM_MUTATION: "filesystem",
    EFFECT_PROCESS_CONTROL: "process_control",
    EFFECT_EXTERNAL_STATE: "external",
    EFFECT_PUBLIC_EGRESS: "public",
    EFFECT_BROWSER_AUTOMATION: "browser",
    EFFECT_PROVIDER_SPEND: "provider_spend",
    EFFECT_GOVERNANCE: "governance",
}

_SYSTEMCTL_MUTATING = frozenset(
    {
        "add-wants",
        "cancel",
        "daemon-reexec",
        "daemon-reload",
        "disable",
        "edit",
        "enable",
        "halt",
        "import-environment",
        "isolate",
        "kill",
        "link",
        "mask",
        "preset",
        "preset-all",
        "poweroff",
        "reboot",
        "reload",
        "reload-or-restart",
        "reset-failed",
        "restart",
        "revert",
        "set-default",
        "set-environment",
        "set-property",
        "start",
        "stop",
        "switch-root",
        "try-reload-or-restart",
        "try-restart",
        "unmask",
        "unset-environment",
    }
)

_TMUX_MUTATING = frozenset(
    {
        "attach",
        "break-pane",
        "detach-client",
        "display-popup",
        "join-pane",
        "kill-pane",
        "kill-server",
        "kill-session",
        "kill-window",
        "new-session",
        "new-window",
        "paste-buffer",
        "pipe-pane",
        "respawn-pane",
        "respawn-window",
        "send",
        "send-keys",
        "set",
        "set-buffer",
        "set-environment",
        "split-window",
        "switch-client",
    }
)

_GH_MUTATING_SUBCOMMANDS = {
    "api",
    "attestation",
    "auth",
    "cache",
    "codespace",
    "gist",
    "issue",
    "pr",
    "project",
    "release",
    "repo",
    "run",
    "secret",
    "ssh-key",
    "variable",
    "workflow",
}
_GH_PR_MUTATING = frozenset(
    {
        "checkout",
        "close",
        "comment",
        "create",
        "edit",
        "lock",
        "merge",
        "ready",
        "reopen",
        "review",
        "unlock",
        "update-branch",
    }
)
_GH_ISSUE_MUTATING = frozenset(
    {
        "close",
        "comment",
        "create",
        "delete",
        "develop",
        "edit",
        "lock",
        "pin",
        "reopen",
        "unlock",
        "unpin",
    }
)
_GH_REPO_MUTATING = frozenset(
    {
        "archive",
        "create",
        "delete",
        "deploy-key",
        "edit",
        "fork",
        "rename",
        "sync",
        "transfer",
        "unarchive",
    }
)
_GH_API_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_GIT_LOCAL_MUTATING = frozenset(
    {
        "add",
        "am",
        "apply",
        "branch",
        "checkout",
        "cherry-pick",
        "clean",
        "commit",
        "merge",
        "mv",
        "rebase",
        "reset",
        "restore",
        "revert",
        "rm",
        "stash",
        "switch",
        "tag",
        "worktree",
    }
)
_DOCKER_MUTATING = frozenset(
    {
        "build",
        "compose",
        "container",
        "create",
        "down",
        "exec",
        "kill",
        "login",
        "logout",
        "pause",
        "pull",
        "push",
        "restart",
        "rm",
        "rmi",
        "run",
        "start",
        "stop",
        "system",
        "unpause",
        "up",
        "volume",
    }
)
_READ_ONLY_HEADS = frozenset(
    {
        "awk",
        "bash",
        "cat",
        "date",
        "diff",
        "echo",
        "find",
        "git",
        "head",
        "jq",
        "ls",
        "nl",
        "pwd",
        "rg",
        "sed",
        "sort",
        "stat",
        "tail",
        "test",
        "true",
        "uv",
        "wc",
        "which",
    }
)
_SHELL_SEPARATORS = frozenset({"&&", "||", ";", "|", "(", ")"})
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")


@dataclass(frozen=True)
class LocalToolClassification:
    """Normalized side-effect classification for a shell command."""

    tool_id: str
    command_head: str
    effect_classes: tuple[str, ...]
    required_mutation_surfaces: tuple[str, ...]
    description: str
    matched_by: str

    @property
    def side_effecting(self) -> bool:
        return bool(set(self.effect_classes) & MUTATING_EFFECTS)


@dataclass(frozen=True)
class LocalToolReceiptGateResult:
    """Decision returned by the local-tool receipt gate."""

    allowed: bool
    reason_code: str
    message: str
    classification: LocalToolClassification | None = None
    route_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    receipt_ref: str | None = None


def _tokenize(command: str) -> list[str]:
    try:
        return shlex.split(command, comments=False, posix=True)
    except ValueError:
        # Malformed shell still reaches the real shell parser later. Classify it
        # fail-closed as a local tool invocation instead of treating it as
        # harmless evidence.
        return [command.strip()] if command.strip() else []


def _command_words(tokens: list[str]) -> list[str]:
    words: list[str] = []
    for token in tokens:
        if token in _SHELL_SEPARATORS:
            continue
        if not words and _ASSIGNMENT_RE.match(token):
            continue
        words.append(token)
    return words


def _has_mutating_systemctl(words: list[str]) -> bool:
    if "systemctl" not in words:
        return False
    start = words.index("systemctl") + 1
    return any(word in _SYSTEMCTL_MUTATING for word in words[start:])


def _has_mutating_tmux(words: list[str]) -> bool:
    if "tmux" not in words:
        return False
    start = words.index("tmux") + 1
    return any(word in _TMUX_MUTATING for word in words[start:])


def _has_mutating_gh_api(words: list[str]) -> bool:
    if "api" not in words:
        return False
    api_index = words.index("api")
    for index, word in enumerate(words[api_index + 1 :], start=api_index + 1):
        if word in {"-X", "--method"} and index + 1 < len(words):
            return words[index + 1].upper() in _GH_API_MUTATING_METHODS
        if word.startswith("-X") and len(word) > 2:
            return word[2:].upper() in _GH_API_MUTATING_METHODS
    return False


def _classify_gh(words: list[str]) -> LocalToolClassification | None:
    if "gh" not in words:
        return None
    gh_index = words.index("gh")
    tail = [word for word in words[gh_index + 1 :] if not word.startswith("-")]
    if not tail:
        return None
    group = tail[0]
    action = tail[1] if len(tail) > 1 else ""
    mutating = False
    if group == "api":
        mutating = _has_mutating_gh_api(words)
    elif group == "pr":
        mutating = action in _GH_PR_MUTATING
    elif group == "issue":
        mutating = action in _GH_ISSUE_MUTATING
    elif group == "repo":
        mutating = action in _GH_REPO_MUTATING
    elif group in _GH_MUTATING_SUBCOMMANDS:
        mutating = group not in {"auth"} or action not in {"status"}
    if not mutating:
        return None
    effects = (EFFECT_EXTERNAL_STATE, EFFECT_PUBLIC_EGRESS, EFFECT_GOVERNANCE)
    return _classification(
        tool_id="local_tool.gh",
        head="gh",
        effects=effects,
        matched_by="gh_mutation",
        description="GitHub CLI mutation or publication command.",
    )


def _classify_git(words: list[str]) -> LocalToolClassification | None:
    if "git" not in words:
        return None
    git_index = words.index("git")
    tail = [word for word in words[git_index + 1 :] if not word.startswith("-")]
    if not tail:
        return None
    action = tail[0]
    if action == "push":
        return _classification(
            tool_id="local_tool.git",
            head="git",
            effects=(EFFECT_EXTERNAL_STATE, EFFECT_PUBLIC_EGRESS, EFFECT_GOVERNANCE),
            matched_by="git_push",
            description="Git push publishes local state to an external repository.",
        )
    if action in _GIT_LOCAL_MUTATING:
        return _classification(
            tool_id="local_tool.git",
            head="git",
            effects=(EFFECT_FILESYSTEM_MUTATION,),
            matched_by="git_local_mutation",
            description=(
                "Git command mutates local repository state; existing claimed-task "
                "source gates cover this bounded filesystem mutation."
            ),
        )
    return None


def _has_browser_automation(words: list[str]) -> bool:
    return any(
        word == "playwright" or word.endswith("/playwright") or "hapax-playwright" in word
        for word in words
    )


def _classification(
    *,
    tool_id: str,
    head: str,
    effects: tuple[str, ...],
    matched_by: str,
    description: str,
) -> LocalToolClassification:
    surfaces = ["local_tool"]
    for effect in effects:
        surface = EFFECT_TO_SURFACE.get(effect)
        if surface:
            surfaces.append(surface)
    return LocalToolClassification(
        tool_id=tool_id,
        command_head=head,
        effect_classes=tuple(dict.fromkeys(effects)),
        required_mutation_surfaces=tuple(dict.fromkeys(surfaces)),
        description=description,
        matched_by=matched_by,
    )


def classify_local_tool_command(command: str) -> LocalToolClassification:
    """Classify a shell command for local-tool route/resource receipt gating."""

    tokens = _tokenize(command)
    words = _command_words(tokens)
    head = Path(words[0]).name if words else ""
    if not words or not head:
        return _classification(
            tool_id="local_tool.empty",
            head="",
            effects=(EFFECT_READ_ONLY,),
            matched_by="empty",
            description="Empty shell payload.",
        )
    if _has_mutating_systemctl(words):
        return _classification(
            tool_id="local_tool.systemctl",
            head="systemctl",
            effects=(EFFECT_PROCESS_CONTROL, EFFECT_LOCAL_MUTATION),
            matched_by="systemctl_mutation",
            description="systemctl command mutates runtime service state.",
        )
    if _has_mutating_tmux(words):
        return _classification(
            tool_id="local_tool.tmux",
            head="tmux",
            effects=(EFFECT_PROCESS_CONTROL, EFFECT_LOCAL_MUTATION),
            matched_by="tmux_mutation",
            description="tmux command controls agent/session process state.",
        )
    gh = _classify_gh(words)
    if gh is not None:
        return gh
    git = _classify_git(words)
    if git is not None:
        return git
    if _has_browser_automation(words):
        return _classification(
            tool_id="local_tool.playwright",
            head="playwright",
            effects=(EFFECT_BROWSER_AUTOMATION, EFFECT_EXTERNAL_STATE),
            matched_by="playwright",
            description="Browser automation can browse external state and consume browser resources.",
        )
    if head in {"ssh", "scp", "rsync"}:
        return _classification(
            tool_id=f"local_tool.{head}",
            head=head,
            effects=(EFFECT_EXTERNAL_STATE,),
            matched_by="remote_shell_or_copy",
            description="Remote shell/copy command mutates or observes external host state.",
        )
    if head in {"docker", "podman"} and any(word in _DOCKER_MUTATING for word in words[1:]):
        return _classification(
            tool_id=f"local_tool.{head}",
            head=head,
            effects=(EFFECT_PROCESS_CONTROL, EFFECT_LOCAL_MUTATION),
            matched_by="container_mutation",
            description="Container lifecycle command mutates runtime process/resource state.",
        )
    if head in {"curl", "wget"} and any(
        word.upper() in {"POST", "PUT", "PATCH", "DELETE"} for word in words
    ):
        return _classification(
            tool_id=f"local_tool.{head}",
            head=head,
            effects=(EFFECT_EXTERNAL_STATE, EFFECT_PUBLIC_EGRESS),
            matched_by="http_mutation",
            description="HTTP command uses a mutating method against external state.",
        )
    if head in _READ_ONLY_HEADS:
        return _classification(
            tool_id=f"local_tool.{head}",
            head=head,
            effects=(EFFECT_READ_ONLY,),
            matched_by="known_read_only",
            description="Known bounded shell evidence command.",
        )
    return _classification(
        tool_id=f"local_tool.{head}",
        head=head,
        effects=(EFFECT_READ_ONLY,),
        matched_by="unclassified_bounded_evidence",
        description=(
            "No representative side-effecting local-tool pattern matched; allowed as "
            "bounded evidence under the existing task and shell mutation gates."
        ),
    )


def _local_tool_receipt_match(
    *,
    route_id: str,
    task_id: str,
    required_surfaces: tuple[str, ...],
    receipt_root: Path,
    now: datetime,
) -> tuple[str | None, str | None]:
    from shared.dispatcher_policy import (
        _route_authority_receipt_is_fresh,
        route_authority_receipt_reference,
    )
    from shared.platform_capability_registry import normalize_route_id

    receipts = _load_route_receipts(receipt_root)
    local_tool_receipts = tuple(
        receipt for receipt in receipts if receipt.receipt_type == "local_tool_invocation"
    )
    if not local_tool_receipts:
        return "local_tool_invocation_receipt_absent", None

    route_matches = tuple(
        receipt
        for receipt in local_tool_receipts
        if normalize_route_id(receipt.route_id) == normalize_route_id(route_id)
    )
    if not route_matches:
        return "local_tool_invocation_route_mismatch", None

    task_matches = tuple(receipt for receipt in route_matches if task_id in receipt.task_ids)
    if not task_matches:
        return "local_tool_invocation_task_mismatch", None

    required = set(required_surfaces)
    surface_matches = tuple(
        receipt for receipt in task_matches if required.issubset(set(receipt.mutation_surfaces))
    )
    if not surface_matches:
        return "local_tool_invocation_surface_mismatch", None

    for receipt in surface_matches:
        if _route_authority_receipt_is_fresh(receipt, now=now):
            return None, route_authority_receipt_reference(receipt)
    return "local_tool_invocation_receipt_stale", None


def evaluate_local_tool_receipt_gate(
    command: str,
    *,
    task_id: str | None,
    role: str | None,
    ledger_path: str | Path | None = None,
    receipt_root: str | Path | None = None,
    now: datetime | None = None,
) -> LocalToolReceiptGateResult:
    """Evaluate route/quota/resource/authority evidence for a local shell tool."""

    classification = classify_local_tool_command(command)
    if not classification.side_effecting:
        return LocalToolReceiptGateResult(
            allowed=True,
            reason_code="read_only_or_bounded_evidence",
            message="local shell command is read-only evidence or covered by existing task gates",
            classification=classification,
        )
    if not task_id:
        return LocalToolReceiptGateResult(
            allowed=False,
            reason_code="task_id_absent",
            message=(
                "side-effecting local tool requires a claimed task. Next action: "
                "claim the dispatched task before retrying the local tool invocation."
            ),
            classification=classification,
        )
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    ledger = Path(ledger_path) if ledger_path else None
    route_decision = _latest_route_decision(
        task_id=task_id,
        role=role,
        ledger_path=ledger if ledger is not None else _latest_default_ledger_path(),
    )
    route_refusal = _route_decision_refusal(route_decision, now=checked_at)
    if route_refusal is not None:
        return LocalToolReceiptGateResult(
            allowed=False,
            reason_code=route_refusal,
            message=(
                "side-effecting local tool requires a fresh green route decision "
                f"for task {task_id}. Next action: refresh the route through governed "
                "methodology dispatch so route, quota, and resource evidence are current."
            ),
            classification=classification,
        )
    assert route_decision is not None
    route_id = str(route_decision["route_id"])
    root = _receipt_root(receipt_root)
    if root is None:
        return LocalToolReceiptGateResult(
            allowed=False,
            reason_code="receipt_dir_disabled",
            message=(
                "route-authority receipt directory is disabled. Next action: restore "
                "HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR or the default receipt directory."
            ),
            classification=classification,
            route_id=route_id,
        )
    try:
        receipt_refusal, receipt_ref = _local_tool_receipt_match(
            route_id=route_id,
            task_id=task_id,
            required_surfaces=classification.required_mutation_surfaces,
            receipt_root=root,
            now=checked_at,
        )
    except ValueError as exc:
        return LocalToolReceiptGateResult(
            allowed=False,
            reason_code="route_authority_receipt_invalid",
            message=(
                f"{exc}. Next action: repair or remove malformed route-authority "
                "receipts, then mint a fresh local_tool_invocation receipt."
            ),
            classification=classification,
            route_id=route_id,
        )
    if receipt_refusal is not None:
        return LocalToolReceiptGateResult(
            allowed=False,
            reason_code=receipt_refusal,
            message=(
                "side-effecting local tool requires a fresh local_tool_invocation "
                f"receipt for route {route_id}, task {task_id}, surfaces "
                f"{','.join(classification.required_mutation_surfaces)}. Next action: "
                "mint a task-bound local_tool_invocation route-authority receipt after "
                "refreshing route/quota/resource evidence."
            ),
            classification=classification,
            route_id=route_id,
            evidence_refs=(
                *_sequence(route_decision.get("quota_evidence_refs")),
                *_sequence(route_decision.get("resource_state_refs")),
            ),
        )
    return LocalToolReceiptGateResult(
        allowed=True,
        reason_code="local_tool_receipts_ok",
        message="local-tool route, quota, resource, and authority receipt evidence is fresh",
        classification=classification,
        route_id=route_id,
        evidence_refs=(
            *_sequence(route_decision.get("quota_evidence_refs")),
            *_sequence(route_decision.get("resource_state_refs")),
        ),
        receipt_ref=receipt_ref,
    )


def _latest_default_ledger_path() -> Path:
    from shared.mcp_connector_policy import DEFAULT_ROUTE_DECISION_LEDGER, ROUTE_DECISION_LEDGER_ENV

    env_value = os.environ.get(ROUTE_DECISION_LEDGER_ENV)
    return Path(env_value) if env_value else DEFAULT_ROUTE_DECISION_LEDGER


def _classification_json(classification: LocalToolClassification | None) -> dict[str, Any]:
    if classification is None:
        return {"classified": False}
    return {
        "classified": True,
        "tool_id": classification.tool_id,
        "command_head": classification.command_head,
        "effect_classes": list(classification.effect_classes),
        "required_mutation_surfaces": list(classification.required_mutation_surfaces),
        "side_effecting": classification.side_effecting,
        "matched_by": classification.matched_by,
        "description": classification.description,
    }


def _gate_json(result: LocalToolReceiptGateResult) -> dict[str, Any]:
    return {
        "allowed": result.allowed,
        "reason_code": result.reason_code,
        "message": result.message,
        "route_id": result.route_id,
        "evidence_refs": list(result.evidence_refs),
        "receipt_ref": result.receipt_ref,
        "classification": _classification_json(result.classification),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="local_tool_policy")
    sub = parser.add_subparsers(dest="command_name", required=True)

    p_classify = sub.add_parser("classify")
    p_classify.add_argument("command")

    p_side = sub.add_parser("is-side-effecting")
    p_side.add_argument("command")

    p_gate = sub.add_parser("receipt-gate")
    p_gate.add_argument("command")
    p_gate.add_argument("--task-id", default="")
    p_gate.add_argument("--role", default="")
    p_gate.add_argument("--ledger", default=None)
    p_gate.add_argument("--receipt-dir", default=None)
    p_gate.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command_name == "classify":
            print(json.dumps(_classification_json(classify_local_tool_command(args.command))))
            return 0
        if args.command_name == "is-side-effecting":
            return 0 if classify_local_tool_command(args.command).side_effecting else 10

        result = evaluate_local_tool_receipt_gate(
            args.command,
            task_id=args.task_id or None,
            role=args.role or None,
            ledger_path=args.ledger,
            receipt_root=args.receipt_dir,
        )
    except Exception as exc:
        print(f"local_tool_policy: classifier error: {exc}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(_gate_json(result), sort_keys=True))
    elif result.allowed:
        print(f"local-tool-invocation-gate: allowed — {result.message}")
    else:
        print(
            f"local-tool-invocation-gate: BLOCKED — {result.reason_code}: {result.message}",
            file=sys.stderr,
        )
    return 0 if result.allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
