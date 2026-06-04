"""The pure coordination policy-decide function + shadow-diff harness (Phase 3b).

Coordination reform Phase 3b (master design section 4.1). This is the first
bounded slice of lifting the three drifted cc-task-gate versions (779 / 651 / 427)
into ONE pure decision function returning the typed ``Decision`` from Phase 3a.

``policy_decide`` reproduces the gate's high-frequency decisions — claim, status,
stage, scope, authority — as a PURE function over already-resolved inputs (the
caller does the IO of reading the claim file and parsing frontmatter; this module
only decides). When the kernel is DOWN it delegates wholesale to
``shared.policy_floor.evaluate_floor``, so the irreversible-harm floor remains the
single source of truth for the daemon-down fallback (NEW-CATCH-2).

The single most important correction over the legacy gate is **argument-aware
classification** (FM-16): the legacy bash classifier substring-matches the whole
command, so ``git checkout -b <branch>`` — which writes no source — is wrongly
scope-blocked. ``policy_decide`` classifies the executed command HEAD instead, so
a branch op is not mistaken for a source mutation. ``legacy_bash_scope_block``
ports the legacy substring classifier verbatim so the shadow harness can diff the
two and record every such divergence as the evidence for cutover.

NO live enforcement change ships in this slice: the bash gate stays authoritative;
this module is exercised only by tests and the (later) shadow canary.
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

from shared.policy_decision import Decision, FailMode, Verdict
from shared.policy_floor import evaluate_floor, irreversible_gate
from shared.sdlc_lifecycle import (
    TASK_CLAIMABLE_STATUSES,
    TASK_MUTABLE_STATUSES,
    TASK_TERMINAL_STATUSES,
)

#: Bumped independently of the floor whenever this decision logic changes, so a
#: fleet-wide regression can be bisected to the exact policy_decide version.
#: 0.2.0 — scope convergence to the legacy allow-set (expanduser + sister-repo +
#: scratch-worktree normalization, /tmp + relay cognition, own-task-note bookkeeping,
#: argument-aware python/cp write detection): a strict relaxation that drives the
#: replayed tightenings toward 0. Re-enters the promotion ladder at shadow.
#: 0.3.0 — fix-cc-gate-fps: cat stdout-vs-stderr-redirect classification (a real
#: `cat > f` is a source write; `cat … 2>/dev/null` / `2>&1` / `&>` are NOT, so a
#: read-only cat is no longer misclassified) + vault-root anchoring of relative scope
#: refs in `_scope_forms`. Matches the live gate's lines 268/298 + scope-anchor fix;
#: any decision-logic change re-enters the promotion ladder at shadow.
POLICY_DECIDE_FN_VERSION = "0.3.0"

#: Where the shadow canary records legacy-vs-new divergences by default. A cache
#: path (not git-tracked); the real single daemon-owned log lands in Phase 4.
DEFAULT_SHADOW_LEDGER = Path(os.path.expanduser("~/.cache/hapax/policy-decide-shadow.jsonl"))


# --- Typed inputs -------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    """The tool invocation under decision. Edit/Write carry ``file_path``; Bash carries ``command``."""

    tool_name: str
    command: str = ""
    file_path: str = ""


@dataclass(frozen=True)
class TaskState:
    """The already-resolved claimed-task frontmatter the decision reads (no IO here)."""

    task_id: str
    assigned_to: str
    status: str
    authority_case: str | None = None
    parent_spec: str | None = None
    stage: str | None = None
    implementation_authorized: bool = False
    source_mutation_authorized: bool = False
    docs_mutation_authorized: bool = False
    runtime_mutation_authorized: bool = False
    mutation_scope_refs: tuple[str, ...] = ()


# --- Tool classification (argument-aware — the FM-16 fix) ---------------------

_EDIT_TOOLS = frozenset(
    {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch", "ApplyPatch", "patch"}
)
_BASH_TOOLS = frozenset(
    {"Bash", "exec_command_pty", "exec_command", "shell", "shell_command", "unified_exec"}
)

#: Command heads that always write the filesystem and therefore require scope.
_UNCONDITIONAL_SOURCE_CMDS = frozenset(
    {"tee", "cp", "install", "touch", "truncate", "chmod", "chown", "mkdir", "rm", "mv", "dd"}
)
#: git subcommands that mutate the WORKING TREE (need scope), vs ref/index/remote ops.
_GIT_SOURCE_SUBCMDS = frozenset({"apply", "reset", "merge", "rebase", "restore"})
#: git subcommands that mutate git state but write no source (so are NOT scope-bound).
#: ``branch`` is argument-aware (see ``_git_branch_mutates``): list/show forms read.
_GIT_MUTATING_SUBCMDS = _GIT_SOURCE_SUBCMDS | frozenset(
    {"commit", "push", "checkout", "switch", "tag", "add", "stash", "rm", "mv"}
)
#: ``git branch`` flags that mutate (delete/rename/copy/force/upstream); any other
#: form (list/show/--contains/…) is a read.
_GIT_BRANCH_MUTATING_FLAGS = frozenset(
    {
        "-d",
        "-D",
        "--delete",
        "-m",
        "-M",
        "--move",
        "-c",
        "-C",
        "--copy",
        "-f",
        "--force",
        "--edit-description",
        "-u",
        "--set-upstream-to",
        "--unset-upstream",
    }
)
#: ``git branch`` flags whose following positional is a VALUE, not a new branch name.
_GIT_BRANCH_READ_VALUE_FLAGS = frozenset(
    {
        "--contains",
        "--no-contains",
        "--merged",
        "--no-merged",
        "--points-at",
        "--sort",
        "--format",
        "--list",
        "--column",
    }
)
#: Command heads that ALWAYS mutate runtime/system state. systemctl/docker/
#: journalctl are subcommand-gated separately (a read like ``systemctl is-active``
#: or ``docker ps`` is NOT a mutation) — the FM-16 argument-aware fix.
_RUNTIME_CMDS = frozenset(
    {"ssh", "scp", "rsync", "kill", "pkill", "pacman", "paru", "apt", "dnf", "npm", "pnpm", "yarn"}
)
#: systemctl subcommands that mutate runtime state (mirror journalctl's --vacuum-
#: only rule: every other subcommand — is-active/status/show/list-*/… — is a read).
_SYSTEMCTL_MUTATING_SUBCMDS = frozenset(
    {
        "start",
        "stop",
        "restart",
        "try-restart",
        "reload",
        "reload-or-restart",
        "force-reload",
        "enable",
        "disable",
        "reenable",
        "preset",
        "preset-all",
        "mask",
        "unmask",
        "link",
        "revert",
        "set-property",
        "set-default",
        "isolate",
        "kill",
        "clean",
        "freeze",
        "thaw",
        "daemon-reload",
        "daemon-reexec",
        "edit",
        "switch-root",
        "default",
        "reboot",
        "poweroff",
        "halt",
        "kexec",
        "suspend",
        "hibernate",
        "hybrid-sleep",
        "emergency",
        "rescue",
    }
)
#: docker subcommands that mutate container/image/runtime state (ps/logs/inspect
#: stay reads); also matches ``docker compose <verb>``.
_DOCKER_MUTATING_SUBCMDS = frozenset(
    {
        "up",
        "down",
        "start",
        "stop",
        "restart",
        "kill",
        "rm",
        "rmi",
        "run",
        "exec",
        "create",
        "build",
        "pull",
        "push",
        "load",
        "import",
        "prune",
        "compose",
    }
)
_GH_MUTATING_SUBCMDS = frozenset({"api", "repo", "release"})
_GH_PR_MUTATING = frozenset({"create", "merge", "edit", "close", "reopen"})

_GITHUB_MUTATING_RE = re.compile(
    r"(create|update|delete|merge|push|commit|file|branch|tag|release|pull_request|issue_comment)"
)


def _head_tokens(command: str) -> list[str]:
    """Tokenize the FIRST simple command (up to a ; | && separator). Best-effort, never raises."""
    if not command:
        return []
    head = re.split(r"[;&|]|\n", command, maxsplit=1)[0]
    try:
        return shlex.split(head)
    except ValueError:
        return head.split()


def _bash_is_runtime(command: str) -> bool:
    tokens = _head_tokens(command)
    if not tokens:
        return False
    head = tokens[0]
    rest = tokens[1:]
    # Subcommand-gated runtime heads: a read (systemctl is-active, docker ps,
    # journalctl -n) is NOT a runtime mutation — only the mutating subcommands are.
    if head == "systemctl":
        return any(t in _SYSTEMCTL_MUTATING_SUBCMDS for t in rest)
    if head == "docker":
        return any(t in _DOCKER_MUTATING_SUBCMDS for t in rest)
    if head == "journalctl":
        return any(t.startswith("--vacuum") for t in rest)
    if head in _RUNTIME_CMDS:
        return True
    if head == "uv" and "pip" in tokens and "install" in tokens:
        return True
    return head in {"pip", "pip3"} and "install" in tokens


#: A genuine source WRITE inside a python payload: a write/append/create ``open()``
#: mode, a ``Path.write_*`` sink, a ``shutil`` copy/move, or an ``os`` path-mutating
#: call. A bare ``open(x)`` (read) or a string-building heredoc is NOT a source write
#: — the over-block the legacy substring ``open\(`` produced (it counted every open).
_PYTHON_WRITE_RE = re.compile(
    r"\.write_text\(|\.write_bytes\("
    r"|\bshutil\.(?:copy|copy2|copyfile|copytree|move)\("
    r"|\bos\.(?:remove|unlink|rename|replace|rmdir|removedirs|makedirs|mkdir)\("
    r"|\bopen\([^)]*,\s*['\"][^'\"]*[wax+]"
)
#: A quoted path-like literal (a no-whitespace token carrying a ``/``) — used to tell
#: whether a write targets ONLY ephemeral scratch/cognition (``/tmp``, vault, relay).
_PATH_LITERAL_RE = re.compile(r"""['"]([^'"\s]*/[^'"\s]*)['"]""")


def _python_writes_in_tree(command: str) -> bool:
    """A python payload is a scope-bound source write only when it has a write sink AND
    that write is not solely to ephemeral scratch/cognition (``/tmp``, vault,
    ``~/.cache/hapax/relay``). A read-only or string-building payload is never one."""
    if not _PYTHON_WRITE_RE.search(command):
        return False
    literals = _PATH_LITERAL_RE.findall(command)
    # A write whose every path literal is scratch/cognition is not an in-tree write.
    return not (literals and all(is_cognition_path(p) for p in literals))


def _unconditional_targets(head: str, tokens: list[str]) -> list[str]:
    """Best-effort filesystem targets an unconditional-source command writes."""
    positionals = [t for t in tokens[1:] if not t.startswith("-")]
    if not positionals:
        return []
    if head in {"cp", "mv", "install"}:
        return positionals[-1:]  # the destination is the trailing positional
    return positionals  # tee/touch/truncate/chmod/chown/mkdir/rm/dd: every positional


def _unconditional_writes_in_tree(head: str, tokens: list[str]) -> bool:
    """An unconditional-source command is a scope-bound source write only when SOME
    target is NOT ephemeral scratch/cognition; writing solely to ``/tmp`` (etc.) is
    not an in-tree source mutation (legacy-gate recorded-allow parity)."""
    targets = _unconditional_targets(head, tokens)
    if not targets:
        return True  # cannot see a target → fail safe (scope-bound)
    return any(not is_cognition_path(t) for t in targets)


#: Redirections whose '>' does NOT send cat's stdout to a file: fd duplications
#: (``2>&1``, ``>&2``, ``2>&-``), the both-streams operator (``&>`` / ``&>>``), and
#: stderr-or-higher-fd to a file (``2>``, ``2>>``, ``3>``, …). Stripped before testing
#: for a real stdout redirect, so a read-only ``cat … 2>/dev/null`` is not misread as a
#: write (fix-cc-gate-fps Fix 1; mirrors cc-task-gate.impl.sh ``_cat_writes_file``).
_NON_STDOUT_REDIRECT_RE = re.compile(r"[0-9]*>&[0-9-]+|&>>?|[2-9][0-9]*>>?")


def _cat_writes_to_file(command: str) -> bool:
    """True iff a ``cat`` command redirects its STDOUT to a file (``> f`` / ``>> f`` /
    ``1> f``) — a real write. Only the FIRST simple command's redirections count
    (``_head_tokens`` splits off a pipe/separator and shlex-tokenizes, so a quoted '>'
    in a later arg cannot trip it); stderr/fd redirections are stripped first. A bare
    ``>`` / ``>>`` / ``1>`` keeps its '>' and is the only thing that returns True."""
    cleaned = _NON_STDOUT_REDIRECT_RE.sub(" ", " ".join(_head_tokens(command)))
    return ">" in cleaned


def _bash_is_source_scope(command: str) -> bool:
    """Argument-aware: does the command HEAD write source that must be scope-checked?

    Unlike the legacy substring classifier this does NOT flag ``git checkout``/
    ``switch``/``branch`` (ref ops that write no source) — the FM-16 fix — nor a
    write whose sole target is ephemeral scratch/cognition (``/tmp``, vault, relay),
    nor a read-only python payload (a bare ``open(x)`` is not a write), nor a ``cat``
    whose only redirection is stderr/an fd (``2>/dev/null``, ``2>&1``, ``&>``).
    """
    tokens = _head_tokens(command)
    if not tokens:
        return False
    head = tokens[0]
    if head in _UNCONDITIONAL_SOURCE_CMDS:
        return _unconditional_writes_in_tree(head, tokens)
    if head == "cat":
        return _cat_writes_to_file(command)
    if head in {"sed", "perl"}:
        return any(t == "-i" or t.startswith("-i") or re.match(r"^-p?i$", t) for t in tokens[1:])
    if head == "git" and len(tokens) > 1 and tokens[1] in _GIT_SOURCE_SUBCMDS:
        return True
    if head.startswith("python"):
        return _python_writes_in_tree(command)
    return False


def _git_branch_mutates(args: list[str]) -> bool:
    """``git branch`` mutates only on delete/rename/copy/force/upstream or a positional
    (new) branch name; list/show forms (-a/-v/--show-current/--contains X/…) are reads.
    The FM-16 reader whitelist — branch creation is also gated by no-stale-branches."""
    prev_value_flag = False
    for arg in args:
        if arg in _GIT_BRANCH_MUTATING_FLAGS or arg.startswith("--set-upstream-to="):
            return True
        if arg in _GIT_BRANCH_READ_VALUE_FLAGS:
            prev_value_flag = True
            continue
        if arg.startswith("-"):
            prev_value_flag = False
            continue
        if prev_value_flag:  # the value of a read flag (e.g. --contains HEAD), not a name
            prev_value_flag = False
            continue
        return True  # a positional → a (new) branch name to create/operate on
    return False


def _bash_is_mutating(command: str) -> bool:
    tokens = _head_tokens(command)
    if not tokens:
        return False
    head = tokens[0]
    if head in _UNCONDITIONAL_SOURCE_CMDS:
        return True
    if head in {"sed", "perl"}:
        return _bash_is_source_scope(command)
    if head == "cat":
        return _cat_writes_to_file(command)
    if _bash_is_runtime(command):
        return True
    if head == "git" and len(tokens) > 1:
        if tokens[1] == "branch":
            return _git_branch_mutates(tokens[2:])
        if tokens[1] in _GIT_MUTATING_SUBCMDS:
            return True
    if head == "gh" and len(tokens) > 1:
        sub = tokens[1]
        if sub in _GH_MUTATING_SUBCMDS:
            return True
        if sub == "pr" and len(tokens) > 2 and tokens[2] in _GH_PR_MUTATING:
            return True
    if head.startswith("python"):
        return "<<" in command or _bash_is_source_scope(command)
    return False


def _is_gated_mutation(tool_name: str, command: str) -> bool:
    if tool_name in _EDIT_TOOLS:
        return True
    if tool_name in _BASH_TOOLS:
        # Mirror the floor's irreversible-harm SSOT so module-target egress and the
        # other floor classes are never short-circuited here as "non-mutating"
        # (otherwise the kernel-down floor at _decide never even runs on them).
        return (
            _bash_is_mutating(command) or irreversible_gate(tool_name, command=command) is not None
        )
    if tool_name.startswith("mcp__github__"):
        return bool(_GITHUB_MUTATING_RE.search(tool_name))
    return False


# --- Cognition carve-out (NEW-3: a blocked lane can always think) -------------

_DOCS_PATH_RE = re.compile(r"(?:^|/)docs/|(?:^|/)(?:CLAUDE|README)\.md$|\.md$")


def is_cognition_path(path: str) -> bool:
    """Memory / personal vault notes / coordination receipts / ephemeral scratch —
    always writable, ungated (a blocked lane must still think and report state)."""
    if not path:
        return False
    path = os.path.expanduser(path)
    home = os.path.expanduser("~")
    if path.startswith(home + "/.claude/") and ("/memory/" in path or path.endswith("/memory")):
        return True
    personal = home + "/Documents/Personal"
    # Governance SSOT under the vault is NOT cognition (keeps its validated path).
    if path.startswith(personal + "/20-projects/hapax-cc-tasks/"):
        return False
    if path.startswith(personal + "/20-projects/hapax-requests/"):
        return False
    if path.startswith(personal + "/"):
        return True
    # Inter-session relay receipts: status a blocked lane writes to report state. The
    # governance-sensitive cc-active-task-* claim files share ~/.cache/hapax/ and are
    # deliberately NOT carved out (only the relay/ subtree is).
    if path.startswith(home + "/.cache/hapax/relay/"):
        return True
    if path.startswith("/dev/shm/"):
        return True
    # Ephemeral /tmp scratch (verify scripts, PR bodies, commit-message files) — the
    # master design's "bare /tmp", broader than the legacy gate's /tmp/hapax-* only.
    return path.startswith("/tmp/")


#: Canonical cognition-carve-out corpus: ``(path_template, expected_is_cognition)``.
#: The SINGLE shared spec both ``is_cognition_path`` implementations are pinned against
#: — the live bash gate (``cc-task-gate.impl.sh``) and THIS module. ``{HOME}`` renders
#: to the caller's home. These are the surfaces that decide Edit/Write always-allow;
#: both languages MUST agree here (INV-5) or the shadow->cutover would silently flip
#: enforcement at the most load-bearing boundary. The cross-language half is verified by
#: the parity test in ``tests/hooks/test_cc_task_gate.py``; THIS module's conformance
#: gates cutover via ``cognition_carveout_parity_ok`` (see ``evaluate_shadow_clean``).
#:
#: NB — policy_decide's ``is_cognition_path`` is intentionally BROADER than the gate's on
#: two NON-carve-out surfaces (bare ``/tmp`` and ``~/.cache/hapax/relay/`` receipts),
#: where it doubles as the command-target scratch classifier (``_unconditional_writes_in_tree``).
#: Those are pinned separately in ``tests/test_policy_decide.py`` and are deliberately
#: NOT in this corpus — they are a strict LOOSENING the asymmetry gate already accepts.
COGNITION_CARVEOUT_PARITY_CORPUS: tuple[tuple[str, bool], ...] = (
    ("{HOME}/.claude/projects/x/memory/note.md", True),  # operator auto-memory (deep)
    ("{HOME}/.claude/x/memory", True),  # ``…/memory`` suffix
    ("{HOME}/Documents/Personal/daily/n.md", True),  # personal vault note
    ("/dev/shm/hapax/x", True),  # ephemeral diagnostic scratch
    ("/tmp/hapax-foo.md", True),  # /tmp/hapax-* project scratch
    ("/tmp/hapax/bar", True),  # /tmp/hapax/ project scratch
    ("{HOME}/Documents/Personal/20-projects/hapax-cc-tasks/active/t.md", False),  # cc-task SSOT
    ("{HOME}/Documents/Personal/20-projects/hapax-requests/r.md", False),  # request SSOT
    ("{HOME}/projects/hapax-council/shared/x.py", False),  # repo source
    ("{HOME}/.claude/settings.json", False),  # ~/.claude, not memory
    ("{HOME}/.claude/memoryfoo", False),  # 'memory' not a path component
    ("{HOME}/Documents/Personalish/x", False),  # Personal-prefix boundary
    ("", False),  # empty path
)


def cognition_carveout_parity_ok() -> bool:
    """True iff THIS module's ``is_cognition_path`` matches the canonical carve-out
    corpus for every entry — the cutover-eligibility parity gate.

    A divergence means policy_decide would classify an Edit/Write carve-out surface
    differently from the live bash gate, silently flipping which writes are
    always-allowed the moment policy_decide becomes authoritative. The cross-language
    half (the bash gate also matching the corpus) is enforced by the parity test in
    ``tests/hooks/test_cc_task_gate.py``. Reads ``~`` via the same ``$HOME`` that
    ``is_cognition_path`` itself resolves, so both stay on one home.
    """
    home = os.path.expanduser("~")
    return all(
        is_cognition_path(template.replace("{HOME}", home)) is expected
        for template, expected in COGNITION_CARVEOUT_PARITY_CORPUS
    )


#: The vault roots holding the governance SSOT notes (cc-task + request notes).
_TASK_NOTE_ROOTS = ("/20-projects/hapax-cc-tasks/", "/20-projects/hapax-requests/")


def _is_own_task_note(path: str, task_id: str) -> bool:
    """True iff ``path`` is the governance note for THIS claimed task (``<task_id>.md``).

    The note basename must be exactly ``<task_id>.md`` under the cc-task/request vault
    roots — so a session may keep its own note (session log, stage, AC boxes) but not
    forge or edit another task's note through this carve-out.
    """
    if not task_id or not path:
        return False
    p = os.path.expanduser(path)
    if not any(root in p for root in _TASK_NOTE_ROOTS):
        return False
    return p.rsplit("/", 1)[-1] == f"{task_id}.md"


def _is_docs_path(path: str) -> bool:
    return bool(path) and bool(_DOCS_PATH_RE.search(path))


# --- Field helpers ------------------------------------------------------------


def _is_nullish(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().strip('"').strip("'").lower() in {"", "null", "none", "~", "[]"}


def _stage_num(stage: str | None) -> int | None:
    if not stage:
        return None
    match = re.match(r"^S(\d+)", stage.strip())
    return int(match.group(1)) if match else None


#: The workspace roots that contain a worktree's checkout: ``~/projects/<wt>/`` (the
#: interface-qualified lanes + sister repos) and ``…/scratch/<name>/`` (transient
#: scratch clones under the cache, e.g. ``/data/cache/hapax/scratch/nmq/``). The shadow
#: REPLAY diffs decisions logged from MANY worktrees in ONE process and the decision
#: rows record no cwd, so scope resolution must be cwd-INDEPENDENT: it cannot mirror the
#: live gate's ``Path.cwd()``-anchored ``resolve`` (the replay's cwd is not the
#: decision's worktree). Reducing BOTH sides to repo-relative form yields the same
#: verdict the live gate returned in that worktree. ``/projects/`` is tried first so a
#: repo carrying its OWN inner ``scratch/`` dir still anchors on the workspace root.
_WORKTREE_ANCHORS = ("/projects/", "/scratch/")


def _scope_forms(path: str) -> tuple[str, ...]:
    """The cwd-independent normalized forms a path presents for scope comparison.

    ``os.path.expanduser`` first (legacy-gate ``os.path.expanduser`` parity,
    cc-task-gate.impl.sh:838 — so a ``~/projects/<repo>/…`` or ``~/Documents/…`` ref
    matches the absolute target), then ``./``-strip. An ABSOLUTE workspace path
    ``<home>/projects/<wt>/<rest>`` yields BOTH:

    * the worktree-relative ``<wt>/<rest>`` — so a ref that names the sibling repo
      dir explicitly (``hapax-coord/src/x``, from a cross-repo task whose cwd was
      ``~/projects/``) matches; and
    * the repo-relative ``<rest>`` — so a bare ``shared/x`` ref (cwd was the
      worktree) matches.

    The ``/projects/`` anchor is the FIRST occurrence (a repo may carry an inner
    ``projects/`` dir). A path under the personal vault (``~/Documents/Personal/``)
    additionally yields its vault-root-relative form, so a vault cc-task's relative
    ``20-projects/hapax-cc-tasks/`` scope ref matches the absolute note path
    (fix-cc-gate-fps Fix 2). Any other path (``/tmp`` scratch, an already-relative ref)
    yields its single normalized form. Cwd-independent: the replay diffs decisions from
    many worktrees in one process with no recorded cwd.
    """
    p = os.path.expanduser(path.strip())
    while p.startswith("./"):
        p = p[2:]
    if not p:
        return ()
    if not p.startswith("/"):
        return (p,)
    forms = [p]
    # Vault-relative form: the vault root is a FIXED absolute prefix (unlike the
    # mid-path worktree markers below), so strip it to yield the vault-relative form.
    vault = os.path.expanduser("~/Documents/Personal/")
    if p.startswith(vault):
        forms.append(p[len(vault) :])
    # The EARLIEST worktree anchor wins, so an inner ``scratch/`` under a ``~/projects/``
    # worktree still anchors on the workspace root rather than the inner dir.
    anchor, alen = -1, 0
    for marker in _WORKTREE_ANCHORS:
        i = p.find(marker)
        if i != -1 and (anchor == -1 or i < anchor):
            anchor, alen = i, len(marker)
    if anchor != -1:
        tail = p[anchor + alen :]  # '<wt>/<rest>'
        slash = tail.find("/")
        rest = tail[slash + 1 :] if slash != -1 else ""
        forms.extend(f for f in (tail, rest) if f)
    return tuple(dict.fromkeys(forms))


def _scope_result(path: str, scope_refs: tuple[str, ...]) -> str:
    """One of 'allowed' / 'denied' / 'missing'.

    Compares the cwd-independent normalized forms (``_scope_forms``) of the target
    and each ref — both ``expanduser``'d and reduced to worktree-/repo-relative form
    — so an absolute worktree or sister-repo ``file_path`` matches a ``~``-prefixed,
    repo-dir-prefixed, or bare repo-relative ref exactly as the live (cwd-anchored)
    gate did when it ran inside that worktree.
    """
    real_refs = [r for r in scope_refs if r and not r.startswith(("cc-task:", "request:"))]
    if not real_refs:
        return "missing"
    targets = _scope_forms(path)
    for ref in real_refs:
        for rn in _scope_forms(ref):
            for target in targets:
                if target == rn:
                    return "allowed"
                if rn.endswith("/") and target.startswith(rn):
                    return "allowed"
                if not rn.endswith("/") and target.startswith(rn + "/"):
                    return "allowed"
    return "denied"


# --- Decision constructors ----------------------------------------------------


def _allow(gate: str, reason: str) -> Decision:
    return Decision(
        verdict=Verdict.ALLOW,
        gate=gate,
        reason=reason,
        fail_mode=FailMode.FAIL_OPEN_WITH_LEDGER,
        policy_version=POLICY_DECIDE_FN_VERSION,
    )


def _block(
    gate: str,
    reason: str,
    *,
    required_field: str | None = None,
    current_value: str | None = None,
    remediation_verb: str | None = None,
) -> Decision:
    return Decision(
        verdict=Verdict.BLOCK,
        gate=gate,
        reason=reason,
        fail_mode=FailMode.FAIL_CLOSED,
        required_field=required_field,
        current_value=current_value,
        remediation_verb=remediation_verb,
        policy_version=POLICY_DECIDE_FN_VERSION,
    )


def _status_gate(status: str) -> Decision | None:
    s = (status or "").strip().lower()
    if s in TASK_TERMINAL_STATUSES:
        return _block(
            "status:terminal",
            f"task is terminal ('{s}')",
            current_value=s,
            remediation_verb="cc-claim <fresh_task_id>",
        )
    if s == "blocked":
        return _block("status:blocked", "task is in BLOCKED state", current_value=s)
    if s in TASK_MUTABLE_STATUSES:
        return None
    if s in TASK_CLAIMABLE_STATUSES or s == "":
        return _block(
            "status:unclaimed",
            f"task is '{s or 'unset'}', not claimed",
            current_value=s,
            remediation_verb="cc-claim <task_id>",
        )
    return _block("status:unknown", f"unknown status '{s}'", current_value=s)


# --- The decision function ----------------------------------------------------


def policy_decide(
    tool_call: ToolCall,
    task: TaskState | None,
    role: str | None,
    *,
    kernel_up: bool = True,
) -> Decision:
    """Pure allow/block decision for a tool-call against the resolved session state.

    Reproduces the cc-task-gate's claim/status/stage/scope/authority decisions.
    When ``kernel_up`` is False the embedded floor (``evaluate_floor``) is the whole
    decision — delegating irreversible-harm to the single-source-of-truth floor.
    Never raises: any internal error degrades to a conservative block.
    """
    try:
        return _decide(tool_call, task, role, kernel_up)
    except Exception:  # noqa: BLE001 — a decision function must never raise; degrade to block.
        return _block("error", "policy_decide raised; failing closed for safety")


def _decide(
    tool_call: ToolCall, task: TaskState | None, role: str | None, kernel_up: bool
) -> Decision:
    name = tool_call.tool_name
    command = tool_call.command or ""
    path = tool_call.file_path or ""

    # 1. Only gated, mutating tool-calls are subject to policy.
    if not _is_gated_mutation(name, command):
        return _allow("non-mutating", "tool call does not mutate protected state")

    # 2. Cognition surfaces are always writable — a blocked lane must still think.
    if path and is_cognition_path(path):
        return _allow("cognition", "cognition/diagnostic surface — always writable")

    # 3. Kernel down: the embedded floor is the whole decision (irreversible-harm SSOT).
    if not kernel_up:
        return evaluate_floor(name, command=command, file_path=path)

    # 4. Identity.
    if not role:
        return _block("identity", "cannot determine session role", required_field="role")

    # 5. Claim.
    if task is None:
        return _block(
            "claim", "no claimed task for this session", remediation_verb="cc-claim <task_id>"
        )

    # 5b. The session's OWN claimed cc-task / request note (``<task_id>.md``) is
    #     governance bookkeeping — session log, stage transitions, AC checkboxes —
    #     allowed regardless of assignment/scope, the way the legacy content-validated
    #     bootstrap allows it (the note is rarely listed in its own
    #     mutation_scope_refs). A DIFFERENT task's note stays fully gated. This also
    #     survives a reconciler-unassign race (the note's assigned_to flips to
    #     'unassigned' mid-session while the session still holds the claim).
    if path and _is_own_task_note(path, task.task_id):
        return _allow(
            "own-task-note", "session's own claimed cc-task note — governance bookkeeping"
        )

    # 6. Assignment.
    if task.assigned_to != role:
        return _block(
            "assignment",
            f"task assigned to '{task.assigned_to}', not '{role}'",
            current_value=task.assigned_to,
        )

    # 7. Status.
    status_decision = _status_gate(task.status)
    if status_decision is not None:
        return status_decision

    # 8/9. Authority root: authority_case + parent_spec are hard requirements.
    if _is_nullish(task.authority_case):
        return _block(
            "authority:case",
            "mutating task has no authority_case",
            required_field="authority_case",
            remediation_verb="cc-task-repair --backfill-authority",
        )
    if _is_nullish(task.parent_spec):
        return _block(
            "authority:parent_spec",
            "mutating task has no parent_spec",
            required_field="parent_spec",
            remediation_verb="cc-task-repair --attach-parent-spec",
        )

    is_docs = _is_docs_path(path)
    is_runtime = name in _BASH_TOOLS and _bash_is_runtime(command)

    # 10. Stage (source/runtime only) with the FR-STAGE-S6-TRAP derive.
    if not is_docs:
        stage_num = _stage_num(task.stage)
        if stage_num is None and task.implementation_authorized:
            stage_num = 6  # authority_case + parent_spec verified; blank stage is a template gap.
        if stage_num is None or stage_num < 6:
            return _block(
                "stage",
                f"stage '{task.stage or '<blank>'}' is < S6",
                current_value=task.stage or "",
                remediation_verb="cc-stage-advance <task> S6_IMPLEMENTATION",
            )

    # 11. Implementation authorization (source/runtime only).
    if not is_docs and not task.implementation_authorized:
        return _block(
            "authority:implementation",
            "implementation_authorized is not true",
            required_field="implementation_authorized",
        )

    # 12. Surface authorizations.
    if is_docs and not task.docs_mutation_authorized and not task.source_mutation_authorized:
        return _block(
            "authority:docs",
            "task does not authorize docs mutation",
            required_field="docs_mutation_authorized",
        )
    if is_runtime and not task.runtime_mutation_authorized:
        return _block(
            "authority:runtime",
            "task does not authorize runtime mutation",
            required_field="runtime_mutation_authorized",
        )
    if not is_docs and not is_runtime and not task.source_mutation_authorized:
        return _block(
            "authority:source",
            "task does not authorize source mutation",
            required_field="source_mutation_authorized",
        )

    # 13. Shell source mutations carry no scope-verifiable path. Argument-aware
    #     (FM-16): only a TRUE working-tree source write blocks here. ``_bash_is_source_scope``
    #     now inspects the payload precisely — a read-only python (a bare ``open(x)``),
    #     a write whose sole target is scratch/cognition (``/tmp``, vault, relay), and a
    #     branch op are NOT source writes — so the crude pre-strip the legacy gate used
    #     (cc-task-gate.sh:791) is superseded: it mangled the very mode/target tokens this
    #     check reads (e.g. it deleted the ``'w'`` from ``open('x','w')``). The raw command
    #     is classified instead; the legacy strip lives on only in ``legacy_bash_scope_block``.
    if name in _BASH_TOOLS and not path and not is_runtime and _bash_is_source_scope(command):
        return _block(
            "scope:command",
            "shell source mutation cannot be scope-verified",
            remediation_verb="use Edit/Write so the target is scope-checked",
        )

    # 14. Edit-path scope.
    if path:
        result = _scope_result(path, task.mutation_scope_refs)
        if result == "missing":
            return _block(
                "scope:missing",
                "task has no mutation_scope_refs",
                required_field="mutation_scope_refs",
            )
        if result == "denied":
            return _block(
                "scope:denied", "path is outside the task's mutation_scope_refs", current_value=path
            )

    return _allow("authorized", "all gates passed")


# --- The legacy bash classifier (the FM-16 locus — ported verbatim) -----------
#
# These regexes are the PRE-FM-16 over-broad substring classifier — the snapshot
# the shadow harness diffs against to produce cutover evidence, and the example the
# divergence demo (TestShadowCompare) pins. They are deliberately NOT converged onto
# the now argument-aware classifier above: the live gate already shipped the FM-16
# fix (argument-aware systemctl/git/quoted-arg handling), so the production shadow's
# legacy baseline is the gate's REAL exit code (see cc-task-gate.impl.sh §3c), not a
# re-derivation here. The remaining legacy→modern convergence (retiring these REs)
# is owned by reform-policy-decide-converge-20260601. Cutover stays verdict-stable
# because the ACTIVE classifier (_bash_is_mutating/_bash_is_runtime) matches the new
# bash gate on the read-only corpus — pinned by the parity test in tests/hooks/.

_LEGACY_MUTATING_RE = re.compile(
    r"(^|[;&|()\s])((git\s+(commit|push|apply|reset|checkout|switch|branch|merge|rebase|tag))"
    r"|(gh\s+(api|pr\s+(create|merge|edit|close|reopen)|repo|release))"
    r"|(python[0-9.]*\s*<<)"
    r"|(python[0-9.]*\s.*(-c|--command).*([.]write_text|[.]write_bytes|open\(|shutil[.]|"
    r"os[.](remove|unlink|rename|replace)|Path\())"
    r"|(sed\s.*-i)|(perl\s.*-p?i)|(tee(\s|$))|(cat\s.*>\s)"
    r"|(cp|install|touch|truncate|chmod|chown|mkdir|rm|mv)(\s|$)"
    r"|(uv\s+pip\s+install)|(pip3?\s+install)"
    r"|(pacman|paru|apt|dnf|npm|pnpm|yarn)(\s|$)"
    r"|(systemctl|journalctl\s.*--vacuum|ssh|scp|rsync|"
    r"docker\s+(compose\s)?(up|down|restart|rm|run|exec)|kill|pkill)(\s|$))",
    re.IGNORECASE,
)

_LEGACY_RUNTIME_RE = re.compile(
    r"(^|[;&|()\s])((systemctl)|(ssh|scp|rsync)(\s|$)|(uv\s+pip\s+install)|(pip3?\s+install)"
    r"|(pacman|paru|apt|dnf)(\s|$)|(docker\s+(compose\s)?(up|down|restart|rm|run|exec))"
    r"|(kill|pkill)(\s|$))",
    re.IGNORECASE,
)

_LEGACY_SOURCE_SCOPE_RE = re.compile(
    r"(^|[;&|()\s])((git\s+(apply|reset|checkout|switch|merge|rebase))"
    r"|(python[0-9.]*\s*<<)"
    r"|(python[0-9.]*\s.*(-c|--command).*([.]write_text|[.]write_bytes|open\(|shutil[.]|"
    r"os[.](remove|unlink|rename|replace)|Path\())"
    r"|(sed\s[^|;&]*-i)|(perl\s[^|;&]*-p?i)|(tee(\s|$))|(cat\s[^|;&]*>\s)"
    r"|(cp|install|touch|truncate|chmod|chown|mkdir|rm|mv)(\s|$))",
    re.IGNORECASE,
)


def _strip_quotes_and_comments(command: str) -> str:
    """Mirror the gate's pre-scope strip: drop quoted spans + trailing comments."""
    stripped = re.sub(r"'[^']*'", "", command)
    stripped = re.sub(r'"[^"]*"', "", stripped)
    return re.sub(r"(^|\s)#[^\n]*", "", stripped)


def legacy_bash_scope_block(command: str) -> bool:
    """Reproduce the LEGACY gate's bash source-scope BLOCK verdict for a command.

    True iff the legacy substring gate would block the command at its
    source-mutation-scope check: mutating AND not a runtime mutation AND its
    quote-stripped form matches the source-scope classifier.
    """
    if not command or not _LEGACY_MUTATING_RE.search(command):
        return False
    if _LEGACY_RUNTIME_RE.search(command):
        return False
    return bool(_LEGACY_SOURCE_SCOPE_RE.search(_strip_quotes_and_comments(command)))


# --- Shadow-diff harness ------------------------------------------------------


@dataclass(frozen=True)
class ShadowRecord:
    """One legacy-vs-new comparison. ``diverged`` is the cutover-evidence signal."""

    tool_name: str
    command: str
    file_path: str
    legacy_blocked: bool
    new_decision: Decision
    diverged: bool
    task_id: str = ""

    def to_row(self) -> dict[str, object]:
        return {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "command": self.command[:200],
            "file_path": self.file_path,
            "legacy_blocked": self.legacy_blocked,
            "new_verdict": self.new_decision.verdict.value,
            "new_gate": self.new_decision.gate,
            "new_reason": self.new_decision.reason,
            "diverged": self.diverged,
            "policy_version": self.new_decision.policy_version,
        }


def shadow_compare(
    tool_call: ToolCall,
    task: TaskState | None,
    role: str | None,
    *,
    legacy_blocked: bool,
    kernel_up: bool = True,
) -> ShadowRecord:
    """Compute the new decision and diff it against the observed legacy verdict.

    Pure and total: never raises. ``legacy_blocked`` is the legacy bash gate's
    real verdict (in live shadow operation, its exit code; in tests, supplied).
    """
    decision = policy_decide(tool_call, task, role, kernel_up=kernel_up)
    diverged = bool(decision.blocked) != bool(legacy_blocked)
    return ShadowRecord(
        tool_name=tool_call.tool_name,
        command=tool_call.command or "",
        file_path=tool_call.file_path or "",
        legacy_blocked=bool(legacy_blocked),
        new_decision=decision,
        diverged=diverged,
        task_id=task.task_id if task is not None else "",
    )


def record_divergence(record: ShadowRecord, *, ledger_path: str | os.PathLike[str]) -> None:
    """Append the comparison to the shadow ledger. Best-effort; never raises (advisory)."""
    try:
        path = Path(ledger_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_row()) + "\n")
    except Exception:  # noqa: BLE001 — the shadow ledger is advisory; a write failure must not block.
        pass


def run_shadow(
    tool_call: ToolCall,
    task: TaskState | None,
    role: str | None,
    *,
    legacy_blocked: bool,
    kernel_up: bool = True,
    ledger_path: str | os.PathLike[str] = DEFAULT_SHADOW_LEDGER,
) -> ShadowRecord:
    """Compare legacy-vs-new and record ONLY divergences to the ledger; return the record."""
    record = shadow_compare(
        tool_call, task, role, legacy_blocked=legacy_blocked, kernel_up=kernel_up
    )
    if record.diverged:
        record_divergence(record, ledger_path=ledger_path)
    return record


# --- The live PRODUCER + the cutover EVALUATOR (reform fix: unblock 3b-cutover)
#
# Phase 3b shipped the harness above but nothing invoked it on a live tool-call
# stream, so the 3b-cutover gate sat on an evidence-shaped predicate with no
# producer. These two functions close that loop:
#
#   PRODUCER  — cc-task-gate.sh logs its REAL exit code + the state it decided on
#               to a decision log; ``replay_decision_log`` (run by a systemd timer)
#               replays it through ``policy_decide`` and rebuilds the divergence
#               ledger. The legacy verdict is the gate's OWN exit code, never a
#               re-derivation via _LEGACY_*_RE (closes the drift 3b-cutover flags).
#   EVALUATOR — ``evaluate_shadow_clean`` turns the ledger into the checkable
#               "shadow-week-clean + asymmetric-divergence" predicate the gate
#               needs, so a real ledger can actually unblock it (and an empty one
#               correctly cannot).

#: The gate's decision log: one JSON row per GATED decision, carrying the gate's
#: REAL exit code (``legacy_exit``) and the resolved state it decided on.
DEFAULT_DECISION_LOG = Path(os.path.expanduser("~/.cache/hapax/cc-task-gate-decisions.jsonl"))


def _decision_row_bool(row: dict[str, object], key: str) -> bool:
    return str(row.get(key) or "").strip().lower() == "true"


def _decision_row_field(row: dict[str, object], key: str) -> str | None:
    value = row.get(key)
    if value in (None, ""):
        return None
    return str(value)


def _task_from_decision_row(row: dict[str, object]) -> TaskState | None:
    """Rebuild the TaskState the gate decided on from a decision-log row (no vault IO)."""
    task_id = str(row.get("task_id") or "").strip()
    if not task_id:
        return None
    scope_raw = str(row.get("mutation_scope_refs") or "")
    scope = tuple(part for part in scope_raw.split("\x1f") if part.strip())
    return TaskState(
        task_id=task_id,
        assigned_to=str(row.get("assigned_to") or ""),
        status=str(row.get("status") or ""),
        authority_case=_decision_row_field(row, "authority_case"),
        parent_spec=_decision_row_field(row, "parent_spec"),
        stage=_decision_row_field(row, "stage"),
        implementation_authorized=_decision_row_bool(row, "implementation_authorized"),
        source_mutation_authorized=_decision_row_bool(row, "source_mutation_authorized"),
        docs_mutation_authorized=_decision_row_bool(row, "docs_mutation_authorized"),
        runtime_mutation_authorized=_decision_row_bool(row, "runtime_mutation_authorized"),
        mutation_scope_refs=scope,
    )


def _iter_jsonl(path: Path):
    """Yield well-formed JSON objects from a JSONL file; skip blanks/garbage; tolerate absence."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(row, dict):
            yield row


def _atomic_write_lines(path: Path, lines: list[str]) -> None:
    """Atomically (tmp + replace) write newline-terminated lines. Best-effort; never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".replay-tmp")
        tmp.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def replay_decision_log(
    decision_log_path: str | os.PathLike[str],
    shadow_ledger_path: str | os.PathLike[str],
    *,
    kernel_up: bool = True,
) -> dict[str, int]:
    """Replay the gate's REAL-verdict decision log through ``policy_decide``.

    For each logged gated decision, recompute the new ``policy_decide`` verdict and
    diff it against the gate's REAL exit code (``legacy_exit == 2`` ⇒ blocked). The
    divergence ledger is REBUILT atomically from the full log on every call — a
    derived projection, so the timer can run repeatedly with no offset drift or
    double-counting. Returns counts (``total`` / ``divergences`` / ``loosening`` /
    ``tightening``) for the evaluator. Never raises.
    """
    shadow_ledger_path = Path(shadow_ledger_path)
    summary = {"total": 0, "divergences": 0, "loosening": 0, "tightening": 0}
    out_lines: list[str] = []
    for row in _iter_jsonl(Path(decision_log_path)):
        summary["total"] += 1
        tool_call = ToolCall(
            tool_name=str(row.get("tool_name") or ""),
            command=str(row.get("command") or ""),
            file_path=str(row.get("file_path") or ""),
        )
        task = _task_from_decision_row(row)
        role = str(row.get("role") or "") or None
        try:
            legacy_blocked = int(row.get("legacy_exit", 0)) == 2
        except (ValueError, TypeError):
            legacy_blocked = False
        record = shadow_compare(
            tool_call, task, role, legacy_blocked=legacy_blocked, kernel_up=kernel_up
        )
        if record.diverged:
            summary["divergences"] += 1
            if legacy_blocked and record.new_decision.allowed:
                summary["loosening"] += 1
            elif not legacy_blocked and record.new_decision.blocked:
                summary["tightening"] += 1
            ledger_row = record.to_row()
            # Carry the ORIGINAL gate-decision ts (the ledger's own ``ts`` is the
            # replay time) so the evaluator can window divergences by when the gate
            # actually decided — the window-restart boundary reads this field.
            ledger_row["decision_ts"] = str(row.get("ts") or "")
            out_lines.append(json.dumps(ledger_row))
    _atomic_write_lines(shadow_ledger_path, out_lines)
    return summary


def _parse_decision_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


def evaluate_shadow_clean(
    decision_log_path: str | os.PathLike[str],
    shadow_ledger_path: str | os.PathLike[str],
    *,
    min_days: float = 7.0,
    min_decisions: int = 200,
    window_start: datetime | None = None,
) -> dict[str, object]:
    """Compute "shadow-week-clean + asymmetric-divergence" for the 3b-cutover gate.

    CLEAN iff BOTH:

    * **coverage** — the decision log spans ``>= min_days`` AND carries
      ``>= min_decisions`` gated decisions. An empty/short log (no real producer
      evidence) is therefore NOT clean — the exact freeze-blocks-thaw bug this fix
      closes: the old gate had a clean-shaped predicate but nothing producing the
      evidence, so it could neither be satisfied nor honestly read.
    * **asymmetry** — every divergence is a LOOSENING (legacy blocked, policy_decide
      allows: the FM-16 false-positive being fixed) and there are ZERO TIGHTENING
      divergences (legacy allowed, policy_decide blocks). Zero tightening proves
      policy_decide is a strict relaxation of the legacy gate — it only removes
      over-blocks, never adds a new block that would regress live work at cutover.

    When ``window_start`` is set, only decisions whose REAL gate-decision time is at or
    after it are counted (the non-destructive window-restart boundary) — coverage reads
    the decision log's ``ts`` and asymmetry reads each ledger row's ``decision_ts``. The
    full log is preserved as evidence; the boundary simply scopes the clean window so
    pre-convergence historical drift cannot poison a fresh accrual.

    Returns a structured verdict (never raises). The caller decides exit status.
    """

    def _after_window(value: object) -> bool:
        if window_start is None:
            return True
        ts = _parse_decision_ts(value)
        return ts is not None and ts >= window_start

    total = 0
    timestamps: list[datetime] = []
    for row in _iter_jsonl(Path(decision_log_path)):
        if not _after_window(row.get("ts")):
            continue
        total += 1
        ts = _parse_decision_ts(row.get("ts"))
        if ts is not None:
            timestamps.append(ts)

    span_days = 0.0
    if len(timestamps) >= 2:
        span_days = (max(timestamps) - min(timestamps)).total_seconds() / 86400.0

    divergences = loosening = tightening = 0
    for row in _iter_jsonl(Path(shadow_ledger_path)):
        if not row.get("diverged"):
            continue
        # Window by the original decision time (falls back to the ledger ts for rows
        # written before decision_ts was stamped).
        if not _after_window(row.get("decision_ts") or row.get("ts")):
            continue
        divergences += 1
        legacy_blocked = bool(row.get("legacy_blocked"))
        new_verdict = str(row.get("new_verdict") or "")
        if legacy_blocked and new_verdict == "allow":
            loosening += 1
        elif not legacy_blocked and new_verdict == "block":
            tightening += 1

    coverage_ok = total >= min_decisions and span_days >= min_days
    asymmetric_ok = tightening == 0
    # The cognition-carve-out parity gate (reform-cognition-path-parity): a divergence
    # between this module's is_cognition_path and the canonical carve-out corpus would
    # silently flip which Edit/Write surfaces are always-allowed the moment policy_decide
    # becomes authoritative, so it blocks cutover exactly like a tightening divergence.
    parity_ok = cognition_carveout_parity_ok()
    clean = coverage_ok and asymmetric_ok and parity_ok

    reasons: list[str] = []
    if total < min_decisions:
        reasons.append(f"insufficient evidence: {total} decisions < {min_decisions} required")
    if span_days < min_days:
        reasons.append(f"short window: {span_days:.1f}d span < {min_days}d shadow week")
    if tightening:
        reasons.append(
            f"{tightening} TIGHTENING divergence(s): policy_decide newly blocks allowed work"
        )
    if not parity_ok:
        reasons.append(
            "cognition-carve-out parity broken: is_cognition_path diverges from the "
            "canonical corpus — cutover would silently flip Edit/Write enforcement"
        )

    return {
        "clean": clean,
        "coverage_ok": coverage_ok,
        "asymmetric_ok": asymmetric_ok,
        "parity_ok": parity_ok,
        "total_decisions": total,
        "span_days": round(span_days, 2),
        "divergences": divergences,
        "loosening": loosening,
        "tightening": tightening,
        "min_days": min_days,
        "min_decisions": min_decisions,
        "window_start": _iso(window_start) if window_start is not None else None,
        "reasons": reasons,
    }


# --- The window-restart boundary + the cutover-eligibility receipt --------------
#
# Converging policy_decide removes the SYSTEMATIC over-blocks, but the historical
# decision log still carries a few genuinely-permissive-legacy decisions (a roleless
# merge, a scratch worktree, an out-of-scope test edit) policy_decide correctly blocks.
# Those are not relaxation regressions, so rather than DESTRUCTIVELY rotate the log
# (losing the evidence), the operator stamps a window-start boundary: a fresh 7-day
# window accrues clean from current decisions while the full log is preserved. The
# receipt makes eligibility (and the countdown to it) a durable, readable artifact so a
# cutover is neither forgotten nor forced on the calendar alone.

#: The non-destructive window-restart boundary (an ISO instant); absent ⇒ full history.
DEFAULT_WINDOW_START = Path(os.path.expanduser("~/.cache/hapax/policy-decide-window-start"))
#: The durable cutover-eligibility receipt (span/asymmetry/eligible/countdown).
DEFAULT_CUTOVER_RECEIPT = Path(
    os.path.expanduser("~/.cache/hapax/policy-decide-cutover-receipt.json")
)


def load_window_start(
    path: str | os.PathLike[str] = DEFAULT_WINDOW_START,
) -> datetime | None:
    """Read the window-restart boundary; an absent/garbage file means no boundary."""
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None
    return _parse_decision_ts(text)


def restart_window(
    path: str | os.PathLike[str] = DEFAULT_WINDOW_START, *, now: datetime | None = None
) -> datetime:
    """Stamp the window-restart boundary at ``now`` (atomically) and return it.

    Non-destructive: the decision log and ledger are untouched — only decisions at or
    after this instant count toward the next clean window.
    """
    now = now or datetime.now(UTC)
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".restart-tmp")
        tmp.write_text(_iso(now) + "\n", encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass
    return now


def build_cutover_receipt(verdict: dict[str, object], *, now: datetime | None = None) -> dict:
    """Project an ``evaluate_shadow_clean`` verdict into a durable cutover receipt.

    ``cutover_eligible`` is the verdict's ``clean`` (coverage AND zero-tightening);
    ``countdown_days`` is the days of clean window still to accrue (0 once eligible).
    """
    now = now or datetime.now(UTC)
    span = float(verdict.get("span_days") or 0.0)
    min_days = float(verdict.get("min_days") or 7.0)
    eligible = bool(verdict.get("clean"))
    countdown = 0.0 if eligible else round(max(0.0, min_days - span), 2)
    return {
        "generated_at": _iso(now),
        "window_start": verdict.get("window_start"),
        "cutover_eligible": eligible,
        "asymmetric_ok": bool(verdict.get("asymmetric_ok")),
        "coverage_ok": bool(verdict.get("coverage_ok")),
        "parity_ok": bool(verdict.get("parity_ok")),
        "span_days": span,
        "min_days": min_days,
        "countdown_days": countdown,
        "total_decisions": verdict.get("total_decisions"),
        "tightening": verdict.get("tightening"),
        "loosening": verdict.get("loosening"),
        "policy_version": POLICY_DECIDE_FN_VERSION,
        "reasons": verdict.get("reasons") or [],
    }


def write_cutover_receipt(
    receipt: dict, *, path: str | os.PathLike[str] = DEFAULT_CUTOVER_RECEIPT
) -> None:
    """Persist the cutover receipt atomically (tmp + replace). Best-effort; never raises."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".receipt-tmp")
        tmp.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


# --- The auto-promotion state machine (reform fix: kill the manual 3b cutover) -
#
# ``evaluate_shadow_clean`` answers "is the shadow-week clean?" but nothing acted on
# a YES — ``3b-cutover`` was a MANUAL cliff a human had to step off by a deadline. A
# clean predicate that never promotes itself is the same freeze-blocks-thaw bug one
# layer up. This is the missing actuator: a reversible, version-stamped ladder
#
#   shadow ──clean──▶ canary ──clean ≥24h──▶ authoritative   (─not-clean──▶ shadow)
#
# that the promote timer advances one rung per clean tick and ROLLS BACK to shadow
# the instant the predicate fails (master design §4.1: "advisory-canary, reversible,
# never a hard cliff"). It only ever advances a recorded POSTURE — wiring that
# posture into the live gate verdict remains a separate, gated step (§4.1: the canary
# logs both decisions "before becoming the live verdict"). Per the permanent-canary
# discipline, any change to ``policy_decide`` (a new ``POLICY_DECIDE_FN_VERSION``)
# resets the ladder to shadow so the new logic must re-prove itself from scratch.

PROMOTION_SHADOW = "shadow"
PROMOTION_CANARY = "canary"
PROMOTION_AUTHORITATIVE = "authoritative"
_PROMOTION_STATES = frozenset({PROMOTION_SHADOW, PROMOTION_CANARY, PROMOTION_AUTHORITATIVE})

#: The canary dwells in dual-decision mode this long before it may go authoritative.
DEFAULT_CANARY_WINDOW_SECONDS = 24 * 3600

#: Current promotion posture (a projection); the audit trail is the ledger beside it.
DEFAULT_PROMOTION_STATE = Path(os.path.expanduser("~/.cache/hapax/policy-decide-promotion.json"))
DEFAULT_PROMOTION_LEDGER = Path(os.path.expanduser("~/.cache/hapax/policy-decide-promotion.jsonl"))

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class PromotionState:
    """The current promotion posture: which rung, stamped with the version that earned it."""

    state: str
    policy_version: str
    entered_state_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PromotionDecision:
    """One transition verdict from ``decide_promotion`` — pure, carries its own version stamp."""

    from_state: str
    to_state: str
    changed: bool
    reason: str
    clean: bool
    policy_version: str
    dwell_seconds: float
    now: datetime

    def next_state(self, current: PromotionState) -> PromotionState:
        """The posture to persist after this decision (entry clock resets only on a change)."""
        entered = self.now if self.changed else current.entered_state_at
        return PromotionState(
            state=self.to_state,
            policy_version=self.policy_version,
            entered_state_at=entered,
            updated_at=self.now,
        )


def decide_promotion(
    current: PromotionState,
    verdict: dict[str, object],
    *,
    policy_version: str,
    now: datetime,
    canary_window_seconds: float = DEFAULT_CANARY_WINDOW_SECONDS,
) -> PromotionDecision:
    """Pure ladder transition. ``verdict`` is an ``evaluate_shadow_clean`` result.

    Advances one rung per clean tick, requires a ``canary_window_seconds`` dwell before
    canary→authoritative, and rolls back to shadow on any not-clean verdict or any
    ``policy_version`` change (the permanent-canary reset). Never raises; never skips a
    rung; never hard-cuts straight to authoritative.
    """
    clean = bool(verdict.get("clean"))
    frm = current.state
    dwell = max(0.0, (now - current.entered_state_at).total_seconds())

    def decision(to_state: str, changed: bool, reason: str) -> PromotionDecision:
        return PromotionDecision(
            from_state=frm,
            to_state=to_state,
            changed=changed,
            reason=reason,
            clean=clean,
            policy_version=policy_version,
            dwell_seconds=dwell,
            now=now,
        )

    # Permanent-canary discipline: a new policy_decide version must re-prove from shadow.
    if current.policy_version != policy_version:
        return decision(
            PROMOTION_SHADOW,
            True,
            f"policy_version {current.policy_version}→{policy_version}: "
            "re-entering shadow (permanent-canary discipline)",
        )

    if frm == PROMOTION_SHADOW:
        if clean:
            return decision(
                PROMOTION_CANARY, True, "shadow-week clean → canary (dual-decision window opens)"
            )
        return decision(PROMOTION_SHADOW, False, _hold_reason(verdict))

    if frm == PROMOTION_CANARY:
        if not clean:
            return decision(
                PROMOTION_SHADOW,
                True,
                f"canary regression ({_hold_reason(verdict)}) → rollback to shadow",
            )
        if dwell >= canary_window_seconds:
            return decision(
                PROMOTION_AUTHORITATIVE,
                True,
                f"canary clean ≥{canary_window_seconds / 3600:.0f}h → authoritative-ready",
            )
        return decision(
            PROMOTION_CANARY,
            False,
            f"canary clean, {dwell / 3600:.1f}h/{canary_window_seconds / 3600:.0f}h elapsed",
        )

    if frm == PROMOTION_AUTHORITATIVE:
        if not clean:
            return decision(
                PROMOTION_SHADOW,
                True,
                f"authoritative regression ({_hold_reason(verdict)}) → rollback to shadow",
            )
        return decision(PROMOTION_AUTHORITATIVE, False, "authoritative steady (shadow-week clean)")

    return decision(PROMOTION_SHADOW, True, f"unknown promotion state '{frm}' → reset to shadow")


def _hold_reason(verdict: dict[str, object]) -> str:
    reasons = verdict.get("reasons")
    if isinstance(reasons, list) and reasons:
        return "; ".join(str(r) for r in reasons)
    return "shadow-week not clean"


def load_promotion_state(
    state_path: str | os.PathLike[str] = DEFAULT_PROMOTION_STATE,
) -> PromotionState:
    """Read the persisted posture; an absent/garbage file defaults to a fresh shadow rung."""
    fresh = PromotionState(PROMOTION_SHADOW, POLICY_DECIDE_FN_VERSION, _EPOCH, _EPOCH)
    try:
        data = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return fresh
    if not isinstance(data, dict):
        return fresh
    state = str(data.get("state") or PROMOTION_SHADOW)
    if state not in _PROMOTION_STATES:
        state = PROMOTION_SHADOW
    entered = _parse_decision_ts(data.get("entered_state_at")) or _EPOCH
    updated = _parse_decision_ts(data.get("updated_at")) or entered
    return PromotionState(
        state=state,
        policy_version=str(data.get("policy_version") or POLICY_DECIDE_FN_VERSION),
        entered_state_at=entered,
        updated_at=updated,
    )


def save_promotion_state(
    state: PromotionState, state_path: str | os.PathLike[str] = DEFAULT_PROMOTION_STATE
) -> None:
    """Persist the posture atomically (tmp + replace). Best-effort; never raises (advisory)."""
    try:
        path = Path(state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".promote-tmp")
        tmp.write_text(
            json.dumps(
                {
                    "state": state.state,
                    "policy_version": state.policy_version,
                    "entered_state_at": _iso(state.entered_state_at),
                    "updated_at": _iso(state.updated_at),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError:
        pass


def append_promotion_ledger(
    decision: PromotionDecision,
    next_state: PromotionState,
    *,
    ledger_path: str | os.PathLike[str] = DEFAULT_PROMOTION_LEDGER,
) -> None:
    """Append a transition row to the audit ledger. Best-effort; never raises (advisory)."""
    try:
        path = Path(ledger_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": _iso(decision.now),
            "from_state": decision.from_state,
            "to_state": decision.to_state,
            "changed": decision.changed,
            "reason": decision.reason,
            "clean": decision.clean,
            "policy_version": decision.policy_version,
            "dwell_seconds": round(decision.dwell_seconds, 1),
            "entered_state_at": _iso(next_state.entered_state_at),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except OSError:
        pass


def run_promotion_cycle(
    *,
    decision_log_path: str | os.PathLike[str] = DEFAULT_DECISION_LOG,
    shadow_ledger_path: str | os.PathLike[str] = DEFAULT_SHADOW_LEDGER,
    state_path: str | os.PathLike[str] = DEFAULT_PROMOTION_STATE,
    ledger_path: str | os.PathLike[str] = DEFAULT_PROMOTION_LEDGER,
    now: datetime | None = None,
    policy_version: str = POLICY_DECIDE_FN_VERSION,
    canary_window_seconds: float = DEFAULT_CANARY_WINDOW_SECONDS,
    min_days: float = 7.0,
    min_decisions: int = 200,
    replay: bool = False,
) -> dict[str, object]:
    """Evaluate the shadow-week and advance/roll-back the promotion ladder one rung.

    Optionally refreshes the divergence ledger first (``replay=True``) so coverage and
    asymmetry are read consistently. Persists the new posture every tick (so ``updated_at``
    tracks liveness) and appends to the audit ledger only on an actual transition.
    Advisory: it advances a posture, never the live gate verdict. Never raises.
    """
    now = now or datetime.now(UTC)
    if replay:
        replay_decision_log(decision_log_path, shadow_ledger_path)
    verdict = evaluate_shadow_clean(
        decision_log_path, shadow_ledger_path, min_days=min_days, min_decisions=min_decisions
    )
    current = load_promotion_state(state_path)
    decision = decide_promotion(
        current,
        verdict,
        policy_version=policy_version,
        now=now,
        canary_window_seconds=canary_window_seconds,
    )
    nxt = decision.next_state(current)
    save_promotion_state(nxt, state_path)
    if decision.changed:
        append_promotion_ledger(decision, nxt, ledger_path=ledger_path)
    return {
        "ts": _iso(now),
        "from_state": decision.from_state,
        "to_state": decision.to_state,
        "changed": decision.changed,
        "reason": decision.reason,
        "clean": decision.clean,
        "policy_version": decision.policy_version,
        "dwell_seconds": round(decision.dwell_seconds, 1),
        "verdict": verdict,
    }


# --- Advisory shadow CLI ------------------------------------------------------


def _task_from_json(blob: str) -> TaskState:
    """Build a TaskState from a JSON object of frontmatter fields (CLI input)."""
    data = json.loads(blob)
    return TaskState(
        task_id=str(data.get("task_id", "")),
        assigned_to=str(data.get("assigned_to", "")),
        status=str(data.get("status", "")),
        authority_case=data.get("authority_case"),
        parent_spec=data.get("parent_spec"),
        stage=data.get("stage"),
        implementation_authorized=bool(data.get("implementation_authorized", False)),
        source_mutation_authorized=bool(data.get("source_mutation_authorized", False)),
        docs_mutation_authorized=bool(data.get("docs_mutation_authorized", False)),
        runtime_mutation_authorized=bool(data.get("runtime_mutation_authorized", False)),
        mutation_scope_refs=tuple(data.get("mutation_scope_refs") or ()),
    )


def main(argv: list[str] | None = None) -> int:
    """Advisory shadow CLI: print the policy_decide verdict + legacy divergence.

    ``python -m shared.policy_decide <tool_name> [--command CMD] [--file PATH]
    [--role R] [--task-json JSON] [--assume-kernel-down] [--ledger PATH]``

    For a Bash command the legacy bash-gate verdict is auto-computed via
    ``legacy_bash_scope_block`` and diffed against ``policy_decide``; any
    divergence is appended to the shadow ledger. ADVISORY ONLY — this NEVER
    enforces and always exits 0. The bash gate remains the sole authority during
    the shadow window.
    """
    parser = argparse.ArgumentParser(prog="policy_decide")
    parser.add_argument("tool_name")
    parser.add_argument("--command", default="")
    parser.add_argument("--file", dest="file_path", default="")
    parser.add_argument("--role", default=None)
    parser.add_argument(
        "--task-json",
        dest="task_json",
        default=None,
        help="JSON object of TaskState fields (omit for an unclaimed session)",
    )
    parser.add_argument(
        "--assume-kernel-down",
        dest="kernel_down",
        action="store_true",
        help="evaluate the daemon-down embedded floor instead of the full decision",
    )
    parser.add_argument("--ledger", default=str(DEFAULT_SHADOW_LEDGER))
    args = parser.parse_args(argv)

    tool_call = ToolCall(args.tool_name, command=args.command, file_path=args.file_path)
    task = _task_from_json(args.task_json) if args.task_json else None
    legacy_blocked = legacy_bash_scope_block(args.command) if args.command else False
    record = run_shadow(
        tool_call,
        task,
        args.role,
        legacy_blocked=legacy_blocked,
        kernel_up=not args.kernel_down,
        ledger_path=args.ledger,
    )
    print(json.dumps(record.to_row()))
    return 0  # advisory: never enforces during the shadow window


def promote_main(argv: list[str] | None = None) -> int:
    """Advance the promotion ladder one rung — the reform 3b AUTO-PROMOTER entrypoint.

    Wired to ``policy-decide-promote.timer`` via ``python -m shared.policy_decide promote``.
    Each tick evaluates the shadow-week and advances/rolls-back the reversible,
    version-stamped posture — the missing actuator that turns a clean predicate into an
    actual promotion instead of the manual 3b-cutover cliff. ``--replay`` refreshes the
    divergence ledger from the decision log first so coverage + asymmetry read
    consistently. ADVISORY ONLY: it moves a recorded POSTURE, never the live gate
    verdict, and always exits 0.
    """
    parser = argparse.ArgumentParser(prog="policy_decide promote")
    parser.add_argument("--decision-log", default=str(DEFAULT_DECISION_LOG))
    parser.add_argument("--ledger", default=str(DEFAULT_SHADOW_LEDGER))
    parser.add_argument("--state", default=str(DEFAULT_PROMOTION_STATE))
    parser.add_argument("--promotion-ledger", default=str(DEFAULT_PROMOTION_LEDGER))
    parser.add_argument("--min-days", type=float, default=7.0)
    parser.add_argument("--min-decisions", type=int, default=200)
    parser.add_argument(
        "--replay",
        action="store_true",
        help="refresh the divergence ledger from the decision log before evaluating",
    )
    args = parser.parse_args(argv)
    result = run_promotion_cycle(
        decision_log_path=args.decision_log,
        shadow_ledger_path=args.ledger,
        state_path=args.state,
        ledger_path=args.promotion_ledger,
        min_days=args.min_days,
        min_decisions=args.min_decisions,
        replay=args.replay,
    )
    print(json.dumps(result, indent=2))
    return 0  # advisory: advances a posture, never the live gate verdict


def shadow_eval_main(argv: list[str] | None = None) -> int:
    """Evaluate "shadow-week-clean + asymmetric-divergence" — the 3b-cutover gate.

    The backing entrypoint for ``scripts/policy-decide-shadow-eval``. A non-destructive
    window-restart boundary scopes the clean window (``--restart-window`` stamps it at
    now; otherwise an already-stamped ``--window-start-file`` is honored) so pre
    -convergence historical drift cannot poison a fresh accrual while the full log/ledger
    are preserved. ``--receipt`` additionally writes a durable cutover-eligibility
    receipt. Exit 0 iff clean (cutover may proceed), 1 otherwise.
    """
    parser = argparse.ArgumentParser(prog="policy-decide-shadow-eval")
    parser.add_argument("--decision-log", default=str(DEFAULT_DECISION_LOG))
    parser.add_argument("--ledger", default=str(DEFAULT_SHADOW_LEDGER))
    parser.add_argument("--min-days", type=float, default=7.0, help="minimum window span in days")
    parser.add_argument(
        "--min-decisions",
        type=int,
        default=200,
        help="minimum gated decisions for the window to count as real evidence",
    )
    parser.add_argument(
        "--window-start-file",
        default=str(DEFAULT_WINDOW_START),
        help="non-destructive restart boundary: only decisions at/after it count (if stamped)",
    )
    parser.add_argument(
        "--restart-window",
        action="store_true",
        help="stamp the window-restart boundary at now, then evaluate the fresh window",
    )
    parser.add_argument(
        "--receipt",
        nargs="?",
        const=str(DEFAULT_CUTOVER_RECEIPT),
        default=None,
        help="also write a durable cutover-eligibility receipt (optional PATH; default cache path)",
    )
    args = parser.parse_args(argv)

    # The boundary scopes the clean window without destroying the full log/ledger.
    window_start = (
        restart_window(args.window_start_file)
        if args.restart_window
        else load_window_start(args.window_start_file)
    )
    result = evaluate_shadow_clean(
        args.decision_log,
        args.ledger,
        min_days=args.min_days,
        min_decisions=args.min_decisions,
        window_start=window_start,
    )
    print(json.dumps(result, indent=2))
    if args.receipt is not None:
        write_cutover_receipt(build_cutover_receipt(result), path=args.receipt)
    return 0 if result["clean"] else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "promote":
        raise SystemExit(promote_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "shadow-eval":
        raise SystemExit(shadow_eval_main(sys.argv[2:]))
    raise SystemExit(main())
