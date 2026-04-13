#!/usr/bin/env bash
# monthly-claude-md-audit — run rot check + sister-extension check across the
# workspace and ntfy on findings.
#
# Wired into systemd/units/claude-md-audit.{service,timer} for monthly cadence.
# Operator can run by hand at any time.
#
# For council files this script intentionally reads from a known canonical
# worktree (default: hapax-council--beta) instead of auto-discovering, because
# the alpha worktree is periodically detached by hapax-rebuild-logos.timer
# (see hapax-council/feedback_rebuild_logos_worktree_detach memory) and may
# carry stale working-tree content that does not reflect origin/main.
#
# Reports via ntfy if any check fails; silent on success.

set -uo pipefail

WORKSPACE="${WORKSPACE:-$HOME/projects}"
COUNCIL_CANONICAL="${COUNCIL_CANONICAL:-$WORKSPACE/hapax-council--beta}"
NTFY_TOPIC="${NTFY_TOPIC:-hapax}"

# Resolve sibling scripts relative to this file's location.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROT_SCRIPT="$SCRIPT_DIR/check-claude-md-rot.sh"
VSCODE_SCRIPT="$SCRIPT_DIR/check-vscode-sister-extensions.sh"

if [[ ! -x "$ROT_SCRIPT" ]]; then
    echo "monthly-claude-md-audit: rot script missing: $ROT_SCRIPT" >&2
    exit 2
fi
if [[ ! -x "$VSCODE_SCRIPT" ]]; then
    echo "monthly-claude-md-audit: vscode checker missing: $VSCODE_SCRIPT" >&2
    exit 2
fi

# Build target list:
#   1. Council canonical (beta worktree) CLAUDE.md + vscode/CLAUDE.md
#   2. Sibling repos (officium, watch, phone, mcp, constitution, distro-work, atlas, tabbyAPI)
#   3. Workspace root CLAUDE.md (resolves dotfiles symlink)
#
# Worktree dirs (alpha hapax-council/, delta hapax-council--*) are excluded
# because their working-tree state is not authoritative.
targets=(
    "$COUNCIL_CANONICAL/CLAUDE.md"
    "$COUNCIL_CANONICAL/vscode/CLAUDE.md"
)

while IFS= read -r f; do
    targets+=("$f")
done < <(
    find "$WORKSPACE" -maxdepth 3 \
        \( -path "$WORKSPACE/hapax-council" \
           -o -path "$WORKSPACE/hapax-council--*" \
           -o -name .git \
           -o -name .venv \
           -o -name venv \
           -o -name node_modules \
        \) -prune \
        -o \( -name CLAUDE.md \( -type f -o -type l \) \) -print \
        2>/dev/null \
        | sort -u
)

# Filter out missing files and dedupe.
filtered=()
seen=()
for t in "${targets[@]}"; do
    [[ -e "$t" ]] || continue
    skip=0
    for s in "${seen[@]}"; do
        if [[ "$s" == "$t" ]]; then skip=1; break; fi
    done
    [[ $skip -eq 0 ]] || continue
    seen+=("$t")
    filtered+=("$t")
done
targets=("${filtered[@]}")

if [[ ${#targets[@]} -eq 0 ]]; then
    echo "monthly-claude-md-audit: no CLAUDE.md files found under $WORKSPACE" >&2
    exit 2
fi

failed=()
fail_log=$(mktemp)
trap 'rm -f "$fail_log"' EXIT

# Default-mode rot scan — should be clean.
if ! "$ROT_SCRIPT" "${targets[@]}" >>"$fail_log" 2>&1; then
    failed+=("rot:default")
fi

# Strict-mode rot scan — flags TODO/FIXME/XXX too. Informational, not blocking.
if ! "$ROT_SCRIPT" --strict "${targets[@]}" >>"$fail_log" 2>&1; then
    failed+=("rot:strict")
fi

# Sister vscode CLAUDE.md drift.
if ! "$VSCODE_SCRIPT" "$COUNCIL_CANONICAL/vscode/CLAUDE.md" "$WORKSPACE/hapax-officium/vscode/CLAUDE.md" >>"$fail_log" 2>&1; then
    failed+=("vscode-sister")
fi

if [[ ${#failed[@]} -gt 0 ]]; then
    body=$(printf 'Monthly CLAUDE.md audit found issues: %s\n\n' "${failed[*]}")
    body+=$(cat "$fail_log")

    if command -v curl >/dev/null 2>&1; then
        curl -sS -X POST -H "Title: CLAUDE.md monthly audit" \
            -d "$body" \
            "http://localhost:8080/$NTFY_TOPIC" >/dev/null 2>&1 || true
    fi

    printf '%s\n' "$body" >&2
    exit 1
fi

# Quiet success — log only at info.
printf 'monthly-claude-md-audit: %d file(s) clean.\n' "${#targets[@]}"
