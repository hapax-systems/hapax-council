#!/usr/bin/env bash
# check-vscode-sister-extensions — diff the two vscode CLAUDE.md files and
# assert that the only differences are the known intentional axes (port +
# perspective phrasing).
#
# The two files at:
#   $WORKSPACE/hapax-council/vscode/CLAUDE.md
#   $WORKSPACE/hapax-officium/vscode/CLAUDE.md
# are kept byte-near-identical. This guard catches drift introduced by edits
# to one but not the other.
#
# Allowed differences (regex patterns the script tolerates on each `<` and
# `>` line):
#   - "8051" or "8050" (logos API ports)
#   - "council" or "officium"
#   - the sister-extension warning's role-aware phrasing
#
# Usage:
#   scripts/check-vscode-sister-extensions.sh                         # auto
#   scripts/check-vscode-sister-extensions.sh path/to/A path/to/B     # explicit
#
# Exits 0 if the diff matches the allowlist, 1 if unexpected drift is found,
# 2 on usage / file errors.

set -euo pipefail

WORKSPACE="${WORKSPACE:-$HOME/projects}"
# Default council vscode CLAUDE.md is read from the beta worktree, NOT the
# alpha primary worktree. Alpha is periodically detached by
# hapax-rebuild-logos.timer (see feedback_rebuild_logos_worktree_detach in
# operator memory) and its working-tree content does not always match HEAD.
# Beta is operator-stable and always at origin/main.
COUNCIL_CANONICAL="${COUNCIL_CANONICAL:-$WORKSPACE/hapax-council--beta}"

if [[ $# -eq 2 ]]; then
    a=$1
    b=$2
elif [[ $# -eq 0 ]]; then
    a="$COUNCIL_CANONICAL/vscode/CLAUDE.md"
    b="$WORKSPACE/hapax-officium/vscode/CLAUDE.md"
else
    echo "usage: $0 [path-A path-B]" >&2
    exit 2
fi

for f in "$a" "$b"; do
    if [[ ! -f "$f" ]]; then
        printf 'check-vscode-sister-extensions: missing file: %s\n' "$f" >&2
        exit 2
    fi
done

# Allowed-drift regex applied to both `< ` and `> ` diff output lines.
# Lines matching this are tolerated; lines NOT matching are reported.
allowed_re='(805[01]|hapax-(council|officium)|targets the (council|officium) Logos API)'

# Capture the diff in plain (NOT unified) format. Plain diff prefixes
# removed lines with `< ` and added lines with `> `, which the case statement
# below pattern-matches. Unified format would prefix with `-`/`+` and the
# loop would never match, silently passing every check.
if diff_output=$(diff "$a" "$b"); then
    printf 'check-vscode-sister-extensions: %s and %s are byte-identical.\n' "$(basename "$(dirname "$a")")" "$(basename "$(dirname "$b")")"
    exit 0
fi

# Walk the diff. Any `< ` or `> ` line that doesn't contain an allowed token
# is considered drift.
unexpected=0
unexpected_lines=()
while IFS= read -r line; do
    case "$line" in
        '< '*|'> '*)
            content=${line:2}
            if [[ -n "$content" ]] && ! grep -qE "$allowed_re" <<<"$content"; then
                unexpected=$((unexpected + 1))
                unexpected_lines+=("$line")
            fi
            ;;
    esac
done <<<"$diff_output"

if [[ $unexpected -gt 0 ]]; then
    printf 'check-vscode-sister-extensions: %d unexpected diff line(s):\n' "$unexpected" >&2
    printf '  %s\n' "${unexpected_lines[@]}" >&2
    echo >&2
    echo "Both files should differ ONLY on logos API port and perspective phrasing." >&2
    echo "If you intentionally introduced new drift, update the allowed_re in this script." >&2
    exit 1
fi

printf 'check-vscode-sister-extensions: drift is within the allowed axes (port + perspective).\n'
