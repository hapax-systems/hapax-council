#!/usr/bin/env bash
# hapax-whoami-audit.sh — print + verify the current Claude Code session identity.
#
# Wraps `scripts/hapax-whoami` and adds invariant enforcement: the
# resolved identity (env-first, then session-role marker, then window
# title) must be one of the governance-approved lanes — the canonical
# vocabulary (SSOT: hooks/scripts/agent-role.sh assert-identity):
#
#   greek slots: alpha beta gamma delta epsilon zeta eta theta
#   agy         — agy CLI lane
#   cx-<color>  — Codex thread identity (for example cx-red)
#   cc-<name>   — relay-coordinated Claude lane (for example cc-zai)
#   vbe-<n>     — Vibe lane
#
# Any other name (kappa and beyond, "claude", etc.) exits non-zero so
# callers — CI jobs, audit hooks, `session-context.sh` — surface the
# violation without guessing the correct identity.
#
# Exit codes:
#   0 — identity valid; printed to stdout on the first line
#   1 — hapax-whoami failed (no foot ancestor, no title, etc.)
#   2 — hapax-whoami succeeded but the returned name is not in the
#       approved set; violating name printed to stdout prefixed with "INVALID: "
#
# Usage:
#   hapax-whoami-audit.sh                 # prints identity or INVALID: <name>
#   hapax-whoami-audit.sh --quiet         # no stdout, exit code only
#   hapax-whoami-audit.sh --expect alpha  # succeed only if identity == alpha

set -eu

# Resolve the wrapped script relative to this one so an uninstalled
# checkout works the same as an installed layout.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WHOAMI_BIN="${SCRIPT_DIR}/hapax-whoami"

if [ ! -x "$WHOAMI_BIN" ]; then
    # Fall back to PATH resolution for installed layouts.
    WHOAMI_BIN="$(command -v hapax-whoami || true)"
fi

if [ -z "${WHOAMI_BIN}" ] || [ ! -x "${WHOAMI_BIN}" ]; then
    echo "hapax-whoami-audit: hapax-whoami binary not found" >&2
    exit 1
fi

# Approved session-name set — the canonical lane vocabulary (mirror of
# hooks/scripts/agent-role.sh assert-identity): greek slots alpha..theta + agy.
# Codex cx-<color>, Claude relay cc-<name>, and Vibe vbe-<n> lanes are approved by
# regex below so each lane does not need a governance amendment.
APPROVED_NAMES="alpha beta gamma delta epsilon zeta eta theta agy"

quiet=false
expected=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --quiet|-q) quiet=true ;;
        --expect) shift; expected="${1:-}" ;;
        --help|-h)
            sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "hapax-whoami-audit: unknown arg: $1" >&2; exit 1 ;;
    esac
    shift
done

identity="$("$WHOAMI_BIN" 2>/dev/null || true)"

if [ -z "$identity" ]; then
    [ "$quiet" = true ] || echo "hapax-whoami-audit: whoami returned empty identity" >&2
    exit 1
fi

# Approved-set membership check.
matched=false
case "$identity" in
    cx-[a-z]* | cc-[a-z]* | vbe-[0-9]* | agy-[a-z0-9-]*)
        matched=true
        ;;
    *)
        for name in $APPROVED_NAMES; do
            if [ "$identity" = "$name" ]; then
                matched=true
                break
            fi
        done
        ;;
esac

if [ "$matched" != true ]; then
    if [ "$quiet" != true ]; then
        echo "INVALID: $identity"
        echo "hapax-whoami-audit: '$identity' is not in approved set: $APPROVED_NAMES or cx-<color>/cc-<name>/vbe-<n>" >&2
    fi
    exit 2
fi

# Optional: match against --expect.
if [ -n "$expected" ] && [ "$identity" != "$expected" ]; then
    [ "$quiet" = true ] || echo "hapax-whoami-audit: expected '$expected', got '$identity'" >&2
    exit 2
fi

[ "$quiet" = true ] || echo "$identity"
exit 0
