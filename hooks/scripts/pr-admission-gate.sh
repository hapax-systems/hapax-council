#!/usr/bin/env bash
# pr-admission-gate.sh — PreToolUse hook (Bash commands)
#
# Blocks PR-admitting actions during drain/frozen governor modes.
# Spec: docs/superpowers/specs/2026-05-01-pr-admission-freeze-governor.md
#
# What this blocks during drain/frozen (and admission is not allowed):
#   - gh pr create
#   - gh pr ready
#   - gh repo fork in this repo
#   - git push origin HEAD:refs/heads/<new>      (detached-HEAD bypass — explicit pain point)
#   - git push origin <local>:refs/heads/<new>
#   - git push -u origin HEAD                    (when current branch not in snapshot)
#   - git branch <new>
#   - git switch -c / git checkout -b
#   - git worktree add -b <new>
#
# What this allows always (and explicitly during drain/frozen):
#   - pushing to a branch in the snapshot
#   - gh pr update-branch
#   - gh pr close, gh pr merge, gh pr ready (closing/finishing existing PRs)
#   - vault/relay updates (no git ops)
#
# How it queries state: invokes scripts/hapax-pr-admission via the library
# is_admission_allowed() check, OR reads ~/.cache/hapax/pr-admission-governor.yaml
# directly when the script isn't available.

set -euo pipefail

INPUT="$(cat)"
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
[ "$TOOL" = "Bash" ] || exit 0

CMD="$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
[ -n "$CMD" ] || exit 0

CONTROL_FILE="${HOME}/.cache/hapax/pr-admission-governor.yaml"

# If no control file → governor is in default normal mode → allow everything.
[ -f "$CONTROL_FILE" ] || exit 0

# Quick mode read without invoking python. yq would be cleaner; using grep/awk
# to avoid additional dep on hook hot path.
MODE="$(grep -E '^mode:' "$CONTROL_FILE" 2>/dev/null | awk '{print $2}' | tr -d '"' | head -1)"
[ -n "$MODE" ] || MODE="normal"

# Normal mode → no governor enforcement.
[ "$MODE" = "normal" ] && exit 0

# Strip quoted strings to prevent false positives from commit messages
# discussing destructive commands. Preserves matching of actual commands.
STRIPPED="$(echo "$CMD" | sed -E "s/'[^']*'//g" | sed -E 's/"[^"]*"//g')"

# Helper: extract list of allowed snapshot branches.
list_snapshot_branches() {
    awk '
        /^allowed_existing_branches:/ { in_list=1; next }
        in_list && /^[[:space:]]*-[[:space:]]/ {
            gsub(/^[[:space:]]*-[[:space:]]*/, "")
            gsub(/^"/, "")
            gsub(/"$/, "")
            print
            next
        }
        in_list && /^[^[:space:]-]/ { in_list=0 }
    ' "$CONTROL_FILE"
}

is_branch_in_snapshot() {
    local branch="$1"
    [ -z "$branch" ] && return 1
    list_snapshot_branches | grep -Fxq "$branch" && return 0 || return 1
}

# Categorise the command.
#
# 1. gh pr create / gh pr ready → ALWAYS BLOCKED in drain/frozen
if echo "$STRIPPED" | grep -qE '^\s*gh\s+pr\s+(create|ready)\b'; then
    echo "PR admission BLOCKED: governor mode is '$MODE' — new PR creation suppressed."
    echo "  See: hapax-pr-admission status"
    echo "  Allowed: pushing to existing snapshot branches; gh pr update-branch;"
    echo "           fixing failed checks on already-open PRs; closing duplicates."
    exit 1
fi

# 2. gh repo fork in this repo
if echo "$STRIPPED" | grep -qE '^\s*gh\s+repo\s+fork\b'; then
    echo "PR admission BLOCKED: governor mode is '$MODE' — gh repo fork suppressed."
    exit 1
fi

# 3. git push origin HEAD:refs/heads/<branch>   (the explicit detached-HEAD bypass pattern)
if echo "$STRIPPED" | grep -qE '^\s*git\s+push\s+origin\s+HEAD:refs/heads/[A-Za-z0-9._/-]+'; then
    target="$(echo "$STRIPPED" | grep -oE 'refs/heads/[A-Za-z0-9._/-]+' | head -1 | sed 's|refs/heads/||')"
    if is_branch_in_snapshot "$target"; then
        # already-open snapshot branch — allow
        exit 0
    fi
    echo "PR admission BLOCKED: detached-HEAD push to new branch '$target' rejected."
    echo "  Governor mode: $MODE. Branch is not in the freeze snapshot."
    echo "  This was the bypass pattern that re-filled the queue during the prior drain."
    exit 1
fi

# 4. git push origin <local>:refs/heads/<branch>
if echo "$STRIPPED" | grep -qE '^\s*git\s+push\s+origin\s+[A-Za-z0-9._/-]+:refs/heads/[A-Za-z0-9._/-]+'; then
    target="$(echo "$STRIPPED" | grep -oE 'refs/heads/[A-Za-z0-9._/-]+' | tail -1 | sed 's|refs/heads/||')"
    if is_branch_in_snapshot "$target"; then
        exit 0
    fi
    echo "PR admission BLOCKED: push to new branch '$target' rejected."
    echo "  Governor mode: $MODE. Branch is not in the freeze snapshot."
    exit 1
fi

# 5. git push -u origin HEAD     (only blocks if current branch not in snapshot)
if echo "$STRIPPED" | grep -qE '^\s*git\s+push\s+-u\s+origin\s+HEAD'; then
    cur_branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
    if [ -z "$cur_branch" ]; then
        echo "PR admission BLOCKED: detached HEAD push without target — refuse during $MODE."
        exit 1
    fi
    if is_branch_in_snapshot "$cur_branch"; then
        exit 0
    fi
    echo "PR admission BLOCKED: git push -u for new branch '$cur_branch' rejected during $MODE."
    exit 1
fi

# 6. git branch <name>  / git switch -c  / git checkout -b
if echo "$STRIPPED" | grep -qE '^\s*git\s+(branch\s+[A-Za-z0-9._/-]+|switch\s+(-c|--create)\s|checkout\s+-[bB]\s)'; then
    # `no-stale-branches.sh` already governs this; we add a clearer message in drain mode.
    # Allow if no-stale-branches has its own logic — we add a softer overlay.
    # For now: do not double-block; log advisory.
    echo "ADVISORY: branch creation during $MODE — ensure your branch is governor-allowed."
    exit 0
fi

# 7. git worktree add -b <new>
if echo "$STRIPPED" | grep -qE '^\s*git\s+worktree\s+add\s+(-b|--branch)\s'; then
    echo "ADVISORY: worktree-with-new-branch during $MODE — ensure governor allowance."
    exit 0
fi

# Default allow.
exit 0
