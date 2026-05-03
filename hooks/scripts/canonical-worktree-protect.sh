#!/usr/bin/env bash
# canonical-worktree-protect.sh — PreToolUse hook (Bash commands)
#
# Refuses git invocations that would leave the canonical worktree
# (/home/hapax/projects/hapax-council) on a non-main ref.
#
# WHY THIS EXISTS
# ---------------
# The canonical worktree is the deploy target for `rebuild-service.sh`,
# which correctly refuses to deploy from a feature-branch state. When
# parallel agents check out feature branches in the canonical, the deploy
# gate fails silently and services run stale code. The 2026-05-03
# deployment audit (PR #2434) traced 2.5+ hours of missed deploys to this
# exact failure mode. This hook is the structural prevention layer.
#
# THE CANONICAL MUST ALWAYS BE ON `main`. Any agent that wants to work
# on a feature branch must use a dedicated worktree (~/.cache/hapax/<slot>
# or .claude/worktrees/<slot>).
#
# DETERMINING CANONICALITY
# ------------------------
#   1. Resolve the toplevel of $PWD via `git rev-parse --show-toplevel`.
#   2. Compare against the canonical path /home/hapax/projects/hapax-council
#      (resolved via `realpath` to handle symlinks).
#   3. If they match exactly, we are in canonical.
#
# BLOCKED IN CANONICAL
# --------------------
#   - git checkout <other-ref>      (would move HEAD off main)
#   - git switch   <other-ref>      (same)
#   - git checkout -b <branch>      (would attach HEAD to a new branch)
#   - git checkout -B <branch>      (same, except -B main = recovery)
#   - git switch   -c <branch>      (same)
#   - git switch   --create <branch>(same)
#   - git reset --hard <other-ref>  (would move HEAD off main)
#
# ALLOWED IN CANONICAL
# --------------------
#   - git checkout main / git switch main          (no-op on main)
#   - git checkout -B main / git switch -C main    (recovery to main)
#   - git checkout -- <file> / git checkout -- .   (file restore)
#   - git pull / git pull --ff-only / git fetch    (advance main FF)
#   - git reset --hard origin/main                 (operator recovery)
#   - git reset --hard main / HEAD~N (no other ref)(local recovery on main)
#   - git worktree add ...                         (does not move canonical HEAD)
#   - All non-checkout/switch/reset git commands   (status, log, etc.)
#   - All non-git commands                         (always passthrough)
#
# OPERATOR ESCAPE HATCH
# ---------------------
# Set HAPAX_CANONICAL_PROTECT_BYPASS=1 to override. The hook logs a
# warning to stderr but allows the command. Operator-explicit, and only
# the operator's interactive shell will have this set.
#
# FAIL-OPEN ON ERROR
# ------------------
# Any unexpected failure (jq missing, git not in PATH, parse error, etc.)
# allows the command. Better to miss a block than to wedge the agent.
set -euo pipefail

# Test override: HAPAX_CANONICAL_PATH_OVERRIDE allows the test suite to
# point this hook at a sandbox path. Production runs always use the
# default canonical path. The override is intentionally not documented
# as an operator escape hatch — operators use HAPAX_CANONICAL_PROTECT_BYPASS.
CANONICAL_PATH="${HAPAX_CANONICAL_PATH_OVERRIDE:-/home/hapax/projects/hapax-council}"

INPUT="$(cat)"
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0

[ "$TOOL" = "Bash" ] || exit 0

CMD="$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
[ -n "$CMD" ] || exit 0

# Operator-explicit bypass.
if [ "${HAPAX_CANONICAL_PROTECT_BYPASS:-0}" = "1" ]; then
    echo "warning: HAPAX_CANONICAL_PROTECT_BYPASS=1 set; canonical-worktree-protect skipped" >&2
    exit 0
fi

# Strip quoted strings before pattern matching to avoid false positives
# from commit messages or echo'd text that mention git commands. Use
# sed -z so the regex spans newlines (multi-line heredocs in quotes).
CMD_STRIPPED="$(printf '%s' "$CMD" | sed -zE "s/'[^']*'//g; s/\"[^\"]*\"//g")"

# Quick filter: if the command does not contain any of the three
# state-mutating verbs we care about, exit fast. Saves the canonical
# resolution for the 99.9% of bash commands that aren't git mutations.
if ! echo "$CMD_STRIPPED" | grep -qE '\bgit\s+(checkout|switch|reset)\b'; then
    exit 0
fi

# Determine if we're in the canonical worktree.
# Compare resolved path of `git rev-parse --show-toplevel` against the
# resolved canonical path. Both sides go through realpath -m to handle
# symlinks and missing intermediate components.
toplevel="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$toplevel" ] || exit 0

resolved_toplevel="$(realpath -m "$toplevel" 2>/dev/null || echo "$toplevel")"
resolved_canonical="$(realpath -m "$CANONICAL_PATH" 2>/dev/null || echo "$CANONICAL_PATH")"

[ "$resolved_toplevel" = "$resolved_canonical" ] || exit 0

# We're in canonical. Decide if the command moves HEAD off main.

# Helper: emit blocked message and exit 2.
_block() {
    echo "BLOCKED: $1" >&2
    echo "" >&2
    echo "Canonical worktree (${CANONICAL_PATH}) must remain on main." >&2
    echo "It is the deploy target — feature branches break rebuild-service.sh." >&2
    echo "" >&2
    echo "To work on a feature branch, use a dedicated worktree:" >&2
    echo "  git worktree add ../hapax-council--<slug> -b alpha/<slug>" >&2
    echo "" >&2
    echo "Operator-explicit override: HAPAX_CANONICAL_PROTECT_BYPASS=1" >&2
    exit 2
}

# --- git checkout ---------------------------------------------------
if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+checkout(\s|$)'; then
    # File restore: `git checkout -- <path>` or `git checkout <ref> -- <path>`
    if echo "$CMD_STRIPPED" | grep -qE 'git\s+checkout\s.*\s--(\s|$)'; then
        exit 0
    fi
    # `git checkout main` / `git switch main`
    if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+checkout\s+main(\s|$)'; then
        exit 0
    fi
    # `git checkout -B main` (recovery)
    if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+checkout\s+-B\s+main(\s|$)'; then
        exit 0
    fi
    # `git checkout -b <branch>` / `-B <not-main>`: branch creation, blocked.
    if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+checkout\s+-[bB]\s'; then
        _block "git checkout -b/-B in canonical worktree creates a branch on canonical HEAD."
    fi
    # `git checkout <ref>` where ref is not main: would move HEAD off main.
    # Match: `git checkout <word>` where word does not start with `-` or `--`.
    if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+checkout\s+[^-][^[:space:]]*'; then
        _block "git checkout <ref> in canonical worktree would leave HEAD off main."
    fi
fi

# --- git switch -----------------------------------------------------
if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+switch(\s|$)'; then
    # `git switch main`
    if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+switch\s+main(\s|$)'; then
        exit 0
    fi
    # `git switch -C main` (recovery)
    if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+switch\s+-C\s+main(\s|$)'; then
        exit 0
    fi
    # `git switch -c|--create <branch>`: branch creation, blocked.
    if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+switch\s+(-c|--create)\s'; then
        _block "git switch -c in canonical worktree creates a branch on canonical HEAD."
    fi
    # `git switch <ref>` where ref is not main.
    if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+switch\s+[^-][^[:space:]]*'; then
        _block "git switch <ref> in canonical worktree would leave HEAD off main."
    fi
fi

# --- git reset ------------------------------------------------------
# `git reset --hard <ref>` is dangerous in canonical IF ref is anything
# other than main / origin/main / HEAD-relative. Recovery to main is fine.
if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+reset\s'; then
    # Allow non-hard resets (e.g. `git reset HEAD~1` for commit fixups; soft/mixed
    # only move the index/staging area, not HEAD's branch attachment).
    if ! echo "$CMD_STRIPPED" | grep -qE 'git\s+reset\s.*--hard\b'; then
        exit 0
    fi
    # Allow `git reset --hard` (no ref → resets to HEAD; HEAD stays on main).
    if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+reset\s+--hard\s*$'; then
        exit 0
    fi
    # Allow `git reset --hard main` / `origin/main` / `HEAD~N`.
    if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+reset\s+--hard\s+(origin/)?main(\s|$)'; then
        exit 0
    fi
    if echo "$CMD_STRIPPED" | grep -qE '^\s*git\s+reset\s+--hard\s+HEAD(~[0-9]+|\^+)?(\s|$)'; then
        exit 0
    fi
    # Anything else is blocked.
    _block "git reset --hard <other-ref> in canonical worktree would move HEAD off main."
fi

exit 0
