"""Daemon-independent conservative enforcement floor (master design section 4.1, NEW-CATCH-2).

When the SBCL coordination kernel is DOWN, the bash hook shim evaluates this
embedded floor instead of calling ``policy-decide`` over the UDS. It fail-CLOSES
exactly the irreversible-harm classes — release, egress, axiom, merge — and
fail-OPENS-with-ledger everything else, so a dead kernel never wedges reversible
work yet can never silently permit irreversible harm.

This is deliberately a small, pure, dependency-light module with its own test
suite: a bug anywhere else in the kernel must not be able to weaken the floor.

It classifies the EXECUTED program — not arbitrary argument bodies (FM-16). The
reform-fix closure (findings #5-#11) makes that classification robust against the
ways an irreversible head used to hide: leading wrappers (``env VAR=``, ``sudo``,
``timeout``, ``./path``), ``bash -c`` indirection, compound chains (``a && b``),
and egress spelled as a module/script target rather than a bare command name.
``irreversible_gate`` is the single classifier shared with the kernel-up
``policy_decide._is_gated_mutation`` mirror.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex

from shared.mcp_connector_policy import is_side_effecting_connector_tool
from shared.policy_decision import Decision, FailMode, Verdict

# --- Irreversible-harm classifiers (executed program / edit path) -------------

#: Constitutional + defense-in-depth governance surfaces — never mutate kernel-down.
#: axioms/ and shared/governance/ are constitutional; CODEOWNERS / CLAUDE.md /
#: pipewire configs are defense-in-depth (finding #11, low severity).
_AXIOM_PATH_RE = re.compile(
    r"(?:^|/)(?:axioms|shared/governance)/"
    r"|(?:^|/)CODEOWNERS$"
    r"|(?:^|/)CLAUDE\.md$"
    r"|config/pipewire/"
)

#: MCP tool names that merge.
_MERGE_TOOLS = frozenset({"mcp__github__merge_pull_request"})
#: MCP tool names that publish/release — incl. direct-commit tools that push a
#: commit straight to a branch (finding #10).
_RELEASE_TOOLS = frozenset(
    {
        "mcp__github__create_pull_request",
        "mcp__github__push_files",
        "mcp__github__create_or_update_file",
        "mcp__github__delete_file",
    }
)

#: Egress marker for the EDIT path: the allowlist config whose edit widens egress.
_EGRESS_PATH_RE = re.compile(r"(?:^|/)config/publication-hardening/")

#: Egress when the EXECUTED program is a publisher — a ``-m`` module, a script
#: path, or a direct publish entrypoint (finding #9). Matched against the program
#: being RUN, never an arbitrary path argument of an unrelated tool, so
#: ``git add <publisher>`` / ``cat <publisher>`` stay reversible.
_EGRESS_TARGET_RE = re.compile(
    r"(?:^|[./])agents[./]publication_bus(?:[./]|$)"
    r"|(?:^|[./])agents[./]publish_orchestrator(?:[./]|$)"
    r"|(?:^|[./])agents[./]marketing[./][\w./-]*publish"
    r"|(?:^|/)scripts/publish"
    r"|_publisher(?:\.py)?$"
)
#: Direct publish command head (basename), e.g. ``hapax-publish``, ``publish-x``.
_EGRESS_CMD_RE = re.compile(r"^(?:hapax-)?publish[-_a-z0-9]*$")

#: Leading wrapper commands that delegate to a following program (finding #5/#6).
_WRAPPERS = frozenset(
    {
        "env",
        "sudo",
        "doas",
        "time",
        "nice",
        "ionice",
        "nohup",
        "stdbuf",
        "timeout",
        "xargs",
        "command",
        "builtin",
        "exec",
        "setsid",
        "chrt",
        "taskset",
    }
)
#: Wrappers that take a single bare positional arg (a duration / priority) before
#: the delegated command.
_WRAPPERS_WITH_NUMERIC_ARG = frozenset({"timeout", "nice", "ionice", "chrt", "taskset"})
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ash", "ksh"})
_PY_RE = re.compile(r"^python[0-9.]*$")
_NET_FETCHERS = frozenset({"curl", "wget"})
#: A version-tag refspec, e.g. ``v1.2.3`` / ``1.2`` — a ``git push`` of one is a tag push.
_TAG_RE = re.compile(r"^v?\d+\.\d+")
#: curl/wget flags that turn the call into an outbound WRITE (irreversible egress).
_NET_WRITE_FLAG_RE = re.compile(
    r"^(?:-d|--data(?:-[a-z]+)?(?:=.*)?|--json|-F|--form|-T|--upload-file"
    r"|--post-data.*|--post-file.*|--method=(?:POST|PUT|PATCH|DELETE))$"
)

_REASONS = {
    "floor:merge": "merge is irreversible and the kernel is down",
    "floor:release": "release/PR-create/protected-push is irreversible and the kernel is down",
    "floor:axiom": "axiom/governance mutation is constitutional and the kernel is down",
    "floor:egress": "external egress is irreversible and the kernel is down",
    "floor:connector": "side-effecting MCP/app connector call requires receipts and the kernel is down",
}


# --- Command structure: wrappers, segments, indirection -----------------------


def _tokens(segment: str) -> list[str]:
    """shlex-tokenize a single simple command; degrade to whitespace split."""
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _split_top_level(command: str) -> list[str]:
    """Split on ``; && || |`` and newline at the TOP level only — operators inside
    quotes are NOT boundaries (so ``bash -c 'a && b'`` stays one segment). Best-effort."""
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if quote is not None:
            buf.append(c)
            if c == "\\" and quote == '"' and i + 1 < n:
                buf.append(command[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            buf.append(c)
            i += 1
            continue
        if c == "\n":
            segments.append("".join(buf))
            buf = []
            i += 1
            continue
        if command[i : i + 2] in ("||", "&&"):
            segments.append("".join(buf))
            buf = []
            i += 2
            continue
        if c in (";", "|"):
            segments.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    segments.append("".join(buf))
    return [s.strip() for s in segments if s.strip()]


def _strip_wrappers(tokens: list[str]) -> list[str]:
    """Drop leading ``VAR=val`` assignments and wrapper commands (env/sudo/timeout/…)
    so the real program head is what gets classified (findings #5/#6)."""
    i, n = 0, len(tokens)
    while i < n:
        tok = tokens[i]
        if _ASSIGN_RE.match(tok):
            i += 1
            continue
        if tok in _WRAPPERS:
            i += 1
            while i < n and (tokens[i].startswith("-") or _ASSIGN_RE.match(tokens[i])):
                i += 1
            if tok in _WRAPPERS_WITH_NUMERIC_ARG and i < n and tokens[i][:1].isdigit():
                i += 1
            continue
        break
    return tokens[i:]


def _dash_c_arg(tokens: list[str]) -> str | None:
    """The inner script of a ``sh -c <script>`` / ``bash -lc <script>`` head, else None."""
    for idx in range(1, len(tokens)):
        tok = tokens[idx]
        if tok == "-c" or (tok.startswith("-") and not tok.startswith("--") and "c" in tok[1:]):
            return tokens[idx + 1] if idx + 1 < len(tokens) else None
    return None


# --- Per-class classifiers (operate on one wrapper-stripped simple command) ----


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _is_merge(tool_name: str, tokens: list[str]) -> bool:
    if tool_name in _MERGE_TOOLS:
        return True
    if "gh" in tokens and "pr" in tokens and "merge" in tokens:
        return True
    return (
        "gh" in tokens and "api" in tokens and any("/merge" in t and "pulls" in t for t in tokens)
    )


def _is_dangerous_push(tokens: list[str]) -> bool:
    """A ``git push`` is irreversible when it force-pushes, pushes tags, or targets
    a protected ref (main/master) — directly or via a ``src:dst`` refspec (finding #10)."""
    flags = [t for t in tokens if t.startswith("-")]
    if any(f in {"-f", "--force"} or f.startswith("--force-with-lease") for f in flags):
        return True
    if any(f in {"--tags", "--follow-tags", "--mirror"} for f in flags):
        return True
    try:
        rest = tokens[tokens.index("push") + 1 :]
    except ValueError:
        rest = tokens
    for t in (t for t in rest if not t.startswith("-")):
        if ":" in t:
            dst = t.split(":", 1)[1]
            if dst in {"main", "master"} or dst.endswith(("/main", "/master")):
                return True
        elif t in {"main", "master"} or t.startswith("refs/tags/") or _TAG_RE.match(t):
            return True
    return False


def _is_release(tool_name: str, tokens: list[str]) -> bool:
    if tool_name in _RELEASE_TOOLS:
        return True
    if "gh" in tokens and "create" in tokens and ("pr" in tokens or "release" in tokens):
        return True
    if "git" in tokens and "push" in tokens:
        return _is_dangerous_push(tokens)
    return False


def _is_axiom(tokens: list[str], file_path: str) -> bool:
    if file_path and _AXIOM_PATH_RE.search(file_path):
        return True
    return any(_AXIOM_PATH_RE.search(t) for t in tokens)


def _net_writes(tokens: list[str]) -> bool:
    """True when a curl/wget carries a body/upload flag — an outbound network WRITE."""
    for idx, tok in enumerate(tokens):
        if _NET_WRITE_FLAG_RE.match(tok):
            return True
        if (
            tok in {"-X", "--request"}
            and idx + 1 < len(tokens)
            and tokens[idx + 1].upper() in {"POST", "PUT", "PATCH", "DELETE"}
        ):
            return True
    return False


def _is_egress_command(tokens: list[str]) -> bool:
    """Egress is keyed on the EXECUTED program: a direct publish entrypoint, an
    interpreter running a publisher module/script, or a data-writing curl/wget."""
    if not tokens:
        return False
    head = tokens[0]
    base = _basename(head)
    if _EGRESS_CMD_RE.match(base) or _EGRESS_TARGET_RE.search(head):
        return True
    if _PY_RE.match(base):
        skip_next = False
        for idx in range(1, len(tokens)):
            tok = tokens[idx]
            if skip_next:
                skip_next = False
                if _EGRESS_TARGET_RE.search(tok):  # the module after -m
                    return True
                continue
            if tok == "-m":
                skip_next = True
                continue
            if tok.startswith("-m") and len(tok) > 2:  # glued form: -m<module>
                if _EGRESS_TARGET_RE.search(tok[2:]):
                    return True
                continue
            if not tok.startswith("-") and _EGRESS_TARGET_RE.search(tok):  # a script arg
                return True
    return base in _NET_FETCHERS and _net_writes(tokens)


def _classify_command(command: str, _depth: int = 0) -> str | None:
    """Return the floor gate name if ANY simple command in the (possibly compound,
    possibly ``bash -c``-wrapped) line is irreversible, else None (findings #5-#9)."""
    command = command.replace("\\\n", "")  # join shell line-continuations first
    for segment in _split_top_level(command):
        tokens = _strip_wrappers(_tokens(segment))
        if not tokens:
            continue
        head = tokens[0]
        if _depth < 4 and head in _SHELLS:
            inner = _dash_c_arg(tokens)
            if inner is not None:
                gate = _classify_command(inner, _depth + 1)
                if gate:
                    return gate
                continue
        if _is_merge("", tokens):
            return "floor:merge"
        if _is_release("", tokens):
            return "floor:release"
        if _is_axiom(tokens, ""):
            return "floor:axiom"
        if _is_egress_command(tokens):
            return "floor:egress"
    return None


def irreversible_gate(tool_name: str, *, command: str = "", file_path: str = "") -> str | None:
    """The single source-of-truth irreversible-harm classifier.

    Returns the floor gate name (``floor:merge`` / ``release`` / ``axiom`` /
    ``egress``) for an irreversible tool-call, ``"floor:error"`` if classification
    itself raised, or ``None`` for a reversible call. Pure and TOTAL — never raises.
    Shared by ``evaluate_floor`` (kernel-down) and ``policy_decide._is_gated_mutation``
    (kernel-up mirror), so the two can never drift.
    """
    try:
        if is_side_effecting_connector_tool(tool_name):
            if tool_name in _MERGE_TOOLS:
                return "floor:merge"
            if tool_name in _RELEASE_TOOLS:
                return "floor:release"
            return "floor:connector"
        if tool_name in _MERGE_TOOLS:
            return "floor:merge"
        if tool_name in _RELEASE_TOOLS:
            return "floor:release"
        if file_path:
            if _AXIOM_PATH_RE.search(file_path):
                return "floor:axiom"
            if _EGRESS_PATH_RE.search(file_path):
                return "floor:egress"
        if command:
            return _classify_command(command)
        return None
    except Exception:  # noqa: BLE001 — the floor must never raise; degrade to fail-closed.
        return "floor:error"


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
    gate = irreversible_gate(tool_name, command=command, file_path=file_path)
    if gate == "floor:error":
        return _blocked("floor:error", "floor classifier raised; failing closed for safety")
    if gate is not None:
        return _blocked(gate, _REASONS.get(gate, "irreversible op; kernel down"))
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
