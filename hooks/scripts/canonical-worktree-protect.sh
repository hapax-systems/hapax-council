#!/usr/bin/env bash
# canonical-worktree-protect.sh — PreToolUse hook (Bash commands)
#
# Refuses git invocations that would leave the canonical worktree
# (/home/hapax/projects/hapax-council) on a non-main ref.
#
# WHY THIS EXISTS
# ---------------
# The canonical worktree is the operator surface and the local main-ref source
# for the post-merge deploy path trigger. `rebuild-service.sh` now deploys from
# a dedicated rebuild worktree, but branch-hopping in the canonical was the
# original failure mode that left services stale. The 2026-05-03 deployment
# audit traced 2.5+ hours of missed deploys to this exact pattern. This hook is
# the prevention layer that keeps canonical on main while agents work elsewhere.
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
PAYLOAD_CWD="$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)" || PAYLOAD_CWD=""

# Operator-explicit bypass.
if [ "${HAPAX_CANONICAL_PROTECT_BYPASS:-0}" = "1" ]; then
    echo "warning: HAPAX_CANONICAL_PROTECT_BYPASS=1 set; canonical-worktree-protect skipped" >&2
    exit 0
fi

# Strip quoted strings before pattern matching to avoid false positives
# from commit messages or echo'd text that mention git commands. Use
# sed -z so the regex spans newlines (multi-line heredocs in quotes).
CMD_STRIPPED="$(printf '%s' "$CMD" | sed -zE "s/'[^']*'//g; s/\"[^\"]*\"//g")"

_unquote_token() {
    local value="$1"
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
    printf '%s\n' "$value"
}

_resolve_path_from() {
    local base="$1" path="$2"
    path="$(_unquote_token "$path")"
    case "$path" in
        "~") path="$HOME" ;;
        "~/"*) path="$HOME/${path#~/}" ;;
    esac
    case "$path" in
        /*) realpath -m "$path" 2>/dev/null || printf '%s\n' "$path" ;;
        *) realpath -m "$base/$path" 2>/dev/null || printf '%s/%s\n' "$base" "$path" ;;
    esac
}

_command_cwd() {
    local cwd="${PAYLOAD_CWD:-$PWD}"
    local cd_arg git_c_arg

    # Common shell shape from agents: `cd /canonical && git switch feature`.
    cd_arg="$(printf '%s\n' "$CMD" | sed -nE 's/^[[:space:]]*cd[[:space:]]+([^;&|[:space:]]+)[[:space:]]*(&&|;).*$/\1/p' | sed -n '1p')"
    if [ -n "$cd_arg" ]; then
        cwd="$(_resolve_path_from "$cwd" "$cd_arg")"
    fi

    # Common git shape: `git -C /canonical switch feature`.
    git_c_arg="$(printf '%s\n' "$CMD" | sed -nE 's/(^|.*[;&|][[:space:]]*)git[[:space:]]+-C[[:space:]]+([^[:space:];&|]+)[[:space:]]+(checkout|switch|reset)([[:space:]]|$).*/\2/p' | sed -n '1p')"
    if [ -n "$git_c_arg" ]; then
        cwd="$(_resolve_path_from "$cwd" "$git_c_arg")"
    fi

    printf '%s\n' "$cwd"
}

# Quick filter: if the command does not contain any of the three
# state-mutating verbs we care about, exit fast. Saves the canonical
# resolution for the 99.9% of bash commands that aren't git mutations.
if ! echo "$CMD_STRIPPED" | grep -qE '\bgit([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+(checkout|switch|reset)\b'; then
    exit 0
fi

# Determine if we're in the canonical worktree.
# Compare resolved path of `git rev-parse --show-toplevel` against the
# resolved canonical path. Both sides go through realpath -m to handle
# symlinks and missing intermediate components.
COMMAND_CWD="$(_command_cwd)"
toplevel="$(git -C "$COMMAND_CWD" rev-parse --show-toplevel 2>/dev/null || true)"
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
    echo "It anchors deploy convergence — feature branches belong in session worktrees." >&2
    echo "" >&2
    echo "To work on a feature branch, use a dedicated worktree:" >&2
    echo "  git worktree add ../hapax-council--<slug> -b alpha/<slug>" >&2
    echo "" >&2
    echo "Operator-explicit override: HAPAX_CANONICAL_PROTECT_BYPASS=1" >&2
    exit 2
}

GIT_PREFIX='(^|[;&|][[:space:]]*)git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+'

# --- git checkout ---------------------------------------------------
if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}checkout([[:space:]]|$)"; then
    # File restore: `git checkout -- <path>` or `git checkout <ref> -- <path>`
    if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}checkout[[:space:]].*[[:space:]]--([[:space:]]|$)"; then
        exit 0
    fi
    # `git checkout main` / `git switch main`
    if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}checkout[[:space:]]+main([[:space:]]|$|[;&|])"; then
        exit 0
    fi
    # `git checkout -B main` (recovery)
    if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}checkout[[:space:]]+-B[[:space:]]+main([[:space:]]|$|[;&|])"; then
        exit 0
    fi
    # `git checkout -b <branch>` / `-B <not-main>`: branch creation, blocked.
    if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}checkout[[:space:]]+-[bB][[:space:]]"; then
        _block "git checkout -b/-B in canonical worktree creates a branch on canonical HEAD."
    fi
    # `git checkout <ref>` where ref is not main: would move HEAD off main.
    # Match: `git checkout <word>` where word does not start with `-` or `--`.
    if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}checkout[[:space:]]+[^-][^[:space:];&|]*"; then
        _block "git checkout <ref> in canonical worktree would leave HEAD off main."
    fi
fi

# --- git switch -----------------------------------------------------
if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}switch([[:space:]]|$)"; then
    # `git switch main`
    if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}switch[[:space:]]+main([[:space:]]|$|[;&|])"; then
        exit 0
    fi
    # `git switch -C main` (recovery)
    if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}switch[[:space:]]+-C[[:space:]]+main([[:space:]]|$|[;&|])"; then
        exit 0
    fi
    # `git switch -c|--create <branch>`: branch creation, blocked.
    if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}switch[[:space:]]+(-c|--create)[[:space:]]"; then
        _block "git switch -c in canonical worktree creates a branch on canonical HEAD."
    fi
    # `git switch <ref>` where ref is not main.
    if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}switch[[:space:]]+[^-][^[:space:];&|]*"; then
        _block "git switch <ref> in canonical worktree would leave HEAD off main."
    fi
fi

# --- git reset ------------------------------------------------------
# `git reset --hard <ref>` is dangerous in canonical IF ref is anything
# other than main / origin/main / HEAD-relative. Recovery to main is fine.
if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}reset[[:space:]]"; then
    # Allow non-hard resets (e.g. `git reset HEAD~1` for commit fixups; soft/mixed
    # only move the index/staging area, not HEAD's branch attachment).
    if ! echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}reset[[:space:]].*--hard\b"; then
        exit 0
    fi
    # Allow `git reset --hard` (no ref → resets to HEAD; HEAD stays on main).
    if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}reset[[:space:]]+--hard[[:space:]]*$"; then
        exit 0
    fi
    # Allow `git reset --hard main` / `origin/main` / `HEAD~N`.
    if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}reset[[:space:]]+--hard[[:space:]]+(origin/)?main([[:space:]]|$|[;&|])"; then
        exit 0
    fi
    if echo "$CMD_STRIPPED" | grep -qE "${GIT_PREFIX}reset[[:space:]]+--hard[[:space:]]+HEAD(~[0-9]+|\^+)?([[:space:]]|$|[;&|])"; then
        exit 0
    fi
    # Anything else is blocked.
    _block "git reset --hard <other-ref> in canonical worktree would move HEAD off main."
fi

exit 0
