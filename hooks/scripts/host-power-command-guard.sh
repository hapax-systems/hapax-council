#!/usr/bin/env bash
# host-power-command-guard.sh — PreToolUse hook that blocks agent-issued host
# power state changes.
#
# Policy: Claude/Codex/Gemini/Vibe lanes must not power off, reboot, halt, or
# kexec the workstation from Bash tool calls. Those commands require an
# explicit operator action outside agent execution.
#
# Returns exit 2 to block the tool call with a message. Fails open on parse
# infrastructure errors so a broken guard does not wedge unrelated work.
set -euo pipefail

INPUT="$(cat)" || exit 0
TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0

[ "$TOOL" = "Bash" ] || exit 0

CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
[ -n "$CMD" ] || exit 0

set +e
RESULT="$(python3 - "$CMD" <<'PYEOF'
from __future__ import annotations

import os
import re
import shlex
import sys

command = sys.argv[1]

POWER_BINARIES = {"poweroff", "reboot", "halt", "shutdown"}
SYSTEMCTL_POWER_SUBCOMMANDS = {
    "poweroff",
    "reboot",
    "halt",
    "kexec",
    "soft-reboot",
    "suspend-then-hibernate",
    "hibernate",
    "suspend",
    "hybrid-sleep",
}
LOGINCTL_POWER_SUBCOMMANDS = {"poweroff", "reboot", "halt", "terminate-seat"}
SHELLS = {"bash", "sh", "zsh", "fish"}
SEGMENT_SEPARATORS = {";", "&&", "||", "|", "\n"}
GROUP_TOKENS = {"(", ")", "{", "}"}
WRAPPERS = {"command", "builtin", "exec", "noglob", "time"}


def strip_heredoc_bodies(text: str) -> str:
    """Remove heredoc bodies while preserving the command lines that start them."""
    output: list[str] = []
    terminator: str | None = None
    allow_tabs = False
    marker_re = re.compile(r"<<-?\s*(['\"]?)([A-Za-z0-9_.-]+)\1")
    for line in text.splitlines():
        if terminator is not None:
            candidate = line.lstrip("\t") if allow_tabs else line
            if candidate.strip() == terminator:
                terminator = None
                allow_tabs = False
            continue
        output.append(line)
        match = marker_re.search(line)
        if match:
            terminator = match.group(2)
            allow_tabs = "<<-" in match.group(0)
    return "\n".join(output)


def shell_tokens(text: str) -> list[str]:
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def basename(token: str) -> str:
    return os.path.basename(token)


def skip_assignments(tokens: list[str], index: int) -> int:
    while index < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", tokens[index]):
        index += 1
    return index


def skip_sudo(tokens: list[str], index: int) -> int:
    if index >= len(tokens) or basename(tokens[index]) != "sudo":
        return index
    index += 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if token in {"-u", "-g", "-h", "-p", "-C", "-T"}:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        break
    return index


def skip_env(tokens: list[str], index: int) -> int:
    if index >= len(tokens) or basename(tokens[index]) != "env":
        return index
    index += 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if token in {"-i", "-0"} or token.startswith("-"):
            index += 1
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", token):
            index += 1
            continue
        break
    return index


def unwrap_command(tokens: list[str], index: int) -> int:
    previous = -1
    while previous != index and index < len(tokens):
        previous = index
        index = skip_assignments(tokens, index)
        index = skip_sudo(tokens, index)
        index = skip_env(tokens, index)
        while index < len(tokens) and tokens[index] in WRAPPERS:
            index += 1
            index = skip_assignments(tokens, index)
            index = skip_sudo(tokens, index)
            index = skip_env(tokens, index)
    return index


def systemctl_subcommand(tokens: list[str], index: int) -> str | None:
    index += 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return None


def blocked_at(tokens: list[str], start: int) -> str | None:
    index = unwrap_command(tokens, start)
    if index >= len(tokens):
        return None
    exe = basename(tokens[index])
    if exe in POWER_BINARIES:
        return " ".join(tokens[start : min(len(tokens), index + 2)])
    if exe == "systemctl":
        subcommand = systemctl_subcommand(tokens, index)
        if subcommand in SYSTEMCTL_POWER_SUBCOMMANDS:
            return " ".join(tokens[start : min(len(tokens), index + 3)])
    if exe == "loginctl":
        subcommand = systemctl_subcommand(tokens, index)
        if subcommand in LOGINCTL_POWER_SUBCOMMANDS:
            return " ".join(tokens[start : min(len(tokens), index + 3)])
    if exe in SHELLS:
        cursor = index + 1
        while cursor < len(tokens):
            token = tokens[cursor]
            if token == "-c" and cursor + 1 < len(tokens):
                nested = detect(tokens[cursor + 1])
                if nested:
                    return nested
                return None
            cursor += 1
    return None


def detect(text: str) -> str | None:
    try:
        tokens = shell_tokens(strip_heredoc_bodies(text))
    except ValueError:
        return None
    at_segment_start = True
    for index, token in enumerate(tokens):
        if token in SEGMENT_SEPARATORS or token in GROUP_TOKENS:
            at_segment_start = True
            continue
        if not at_segment_start:
            continue
        blocked = blocked_at(tokens, index)
        if blocked:
            return blocked
        at_segment_start = False
    return None


blocked = detect(command)
if blocked:
    print(blocked)
    raise SystemExit(2)
raise SystemExit(0)
PYEOF
)"
STATUS=$?
set -e

if [ "$STATUS" -eq 2 ]; then
    cat >&2 <<MSG
BLOCKED: host power-state command is prohibited from agent Bash tools.

Matched command: $RESULT

Do not run poweroff, reboot, shutdown, halt, kexec, or systemctl/loginctl
power-state verbs from a Claude/Codex/Gemini/Vibe lane. Host power changes
require an explicit operator action outside agent execution.
MSG
    exit 2
fi

exit 0
