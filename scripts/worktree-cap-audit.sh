#!/usr/bin/env bash
# worktree-cap-audit.sh — inventory git worktrees + report cap status.
#
# Policy (see docs/runbooks/worktree-cap-policy.md):
#   Claude+Codex transition cap: 8 visible session worktrees.
#   Infrastructure worktrees under ~/.cache/, .claude/worktrees/, or .codex/worktrees/
#   (rebuild-scratch, agent scratch, etc.) are NOT counted.
#
# Classification rules:
#   * PRIMARY    — the top-level `hapax-council/` worktree (alpha)
#   * SECONDARY  — `hapax-council--beta/` (beta, permanent)
#   * SECONDARY  — `hapax-council--delta/` or any path matching
#                  `hapax-council--delta*` (delta, permanent since 2026-04-12)
#   * SECONDARY  — `hapax-council--epsilon/` or any path matching
#                  `hapax-council--epsilon*` (epsilon, permanent since 2026-04-24)
#   * CODEX      — `hapax-council--cx-<color>/` first-class Codex worktree
#   * SPONTANEOUS— any other `hapax-council--<slug>/` worktree
#   * INFRA      — any path containing `/.cache/`, `/.claude/worktrees/`, or `/.codex/worktrees/`
#   * UNKNOWN    — anything else (report + flag as likely leak)
#
# Exit codes:
#   0 — within cap, no unknowns
#   1 — within cap but UNKNOWN / uncategorizable worktrees present
#   2 — cap exceeded (> 5 session worktrees)
#
# Usage:
#   worktree-cap-audit.sh           # full report to stdout
#   worktree-cap-audit.sh --quiet   # exit code only
#   worktree-cap-audit.sh --json    # machine-readable summary

set -euo pipefail

quiet=false
json=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --quiet|-q) quiet=true ;;
        --json) json=true ;;
        --help|-h) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "worktree-cap-audit: unknown arg: $1" >&2; exit 1 ;;
    esac
    shift
done

if ! command -v git >/dev/null 2>&1; then
    echo "worktree-cap-audit: git not available" >&2
    exit 1
fi

# git worktree list is usually run from inside a worktree. If we're
# not in a repo, fall back to $PWD so the script is invocable from
# anywhere.
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
    echo "worktree-cap-audit: not inside a git worktree — cd into hapax-council* first" >&2
    exit 1
fi

# Parse `git worktree list` into (path, branch) tuples.
# Format: `<path>  <sha> [<branch>]` or `<path>  <sha> (detached HEAD)`.
worktrees=()
while IFS= read -r line; do
    [ -z "$line" ] && continue
    worktrees+=("$line")
done < <(git worktree list 2>/dev/null)

primary_count=0
secondary_count=0
codex_count=0
spontaneous_count=0
infra_count=0
unknown_count=0

declare -a primary_lines=()
declare -a secondary_lines=()
declare -a codex_lines=()
declare -a spontaneous_lines=()
declare -a infra_lines=()
declare -a unknown_lines=()

for line in "${worktrees[@]}"; do
    path="${line%% *}"
    case "$path" in
        */.cache/*|*/.claude/worktrees/*|*/.codex/worktrees/*)
            infra_count=$((infra_count + 1))
            infra_lines+=("$line")
            ;;
        */hapax-council)
            primary_count=$((primary_count + 1))
            primary_lines+=("$line")
            ;;
        */hapax-council--beta|*/hapax-council--beta/*|*/hapax-council--main-red|*/hapax-council--main-red/*)
            secondary_count=$((secondary_count + 1))
            secondary_lines+=("alpha/beta/delta/epsilon — beta: $line")
            ;;
        */hapax-council--delta*)
            secondary_count=$((secondary_count + 1))
            secondary_lines+=("alpha/beta/delta/epsilon — delta: $line")
            ;;
        */hapax-council--epsilon*|*/hapax-council--op-referent*)
            secondary_count=$((secondary_count + 1))
            secondary_lines+=("alpha/beta/delta/epsilon — epsilon: $line")
            ;;
        */hapax-council--cx-*)
            codex_count=$((codex_count + 1))
            codex_lines+=("$line")
            ;;
        */hapax-council--*)
            spontaneous_count=$((spontaneous_count + 1))
            spontaneous_lines+=("$line")
            ;;
        *)
            unknown_count=$((unknown_count + 1))
            unknown_lines+=("$line")
            ;;
    esac
done

session_count=$((primary_count + secondary_count + codex_count + spontaneous_count + unknown_count))
cap=8

if [ "$json" = true ]; then
    printf '{'
    printf '"primary": %d, ' "$primary_count"
    printf '"secondary": %d, ' "$secondary_count"
    printf '"codex": %d, ' "$codex_count"
    printf '"spontaneous": %d, ' "$spontaneous_count"
    printf '"infra": %d, ' "$infra_count"
    printf '"unknown": %d, ' "$unknown_count"
    printf '"session_total": %d, ' "$session_count"
    printf '"cap": %d, ' "$cap"
    if [ "$session_count" -gt "$cap" ]; then
        printf '"status": "over_cap"'
    elif [ "$unknown_count" -gt 0 ]; then
        printf '"status": "unknown_present"'
    else
        printf '"status": "ok"'
    fi
    printf '}\n'
elif [ "$quiet" != true ]; then
    echo "=== Worktree cap audit ==="
    echo "Policy: Claude+Codex transition cap = $cap visible session worktrees"
    echo "Infrastructure (~/.cache/, .claude/worktrees/, .codex/worktrees/) not counted."
    echo ""
    echo "PRIMARY ($primary_count):"
    for l in "${primary_lines[@]:-}"; do [ -n "$l" ] && echo "  $l"; done
    echo ""
    echo "SECONDARY permanent ($secondary_count):"
    for l in "${secondary_lines[@]:-}"; do [ -n "$l" ] && echo "  $l"; done
    echo ""
    echo "CODEX first-class ($codex_count):"
    for l in "${codex_lines[@]:-}"; do [ -n "$l" ] && echo "  $l"; done
    echo ""
    echo "SPONTANEOUS ($spontaneous_count):"
    for l in "${spontaneous_lines[@]:-}"; do [ -n "$l" ] && echo "  $l"; done
    echo ""
    echo "INFRASTRUCTURE not counted ($infra_count):"
    for l in "${infra_lines[@]:-}"; do [ -n "$l" ] && echo "  $l"; done
    echo ""
    if [ "$unknown_count" -gt 0 ]; then
        echo "UNKNOWN — likely leak ($unknown_count):"
        for l in "${unknown_lines[@]:-}"; do [ -n "$l" ] && echo "  $l"; done
        echo ""
    fi
    echo "Session worktree total: $session_count / $cap"
    if [ "$session_count" -gt "$cap" ]; then
        echo "STATUS: OVER CAP (cleanup required — see docs/runbooks/worktree-cap-policy.md)"
    elif [ "$unknown_count" -gt 0 ]; then
        echo "STATUS: UNKNOWN PRESENT (investigate uncategorized worktrees)"
    else
        echo "STATUS: OK"
    fi
fi

if [ "$session_count" -gt "$cap" ]; then
    exit 2
elif [ "$unknown_count" -gt 0 ]; then
    exit 1
fi
exit 0
