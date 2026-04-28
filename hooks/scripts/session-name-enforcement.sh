#!/usr/bin/env bash
# session-name-enforcement.sh — PreToolUse hook (Bash commands)
#
# Blocks Bash commands that reference a non-approved session name.
# The governance-approved Claude session-name set is:
#
#   alpha beta gamma delta epsilon
#
# Codex thread names use `cx-<color-word>` (for example `cx-red`) to
# avoid Greek-string ambiguity while staying visually distinct from
# Claude roles.
#
# Any other greek-letter-shaped token (zeta, eta, theta, iota, kappa,
# lambda, mu, nu, xi, omicron, pi, rho, sigma, tau, upsilon, phi,
# chi, psi, omega) appearing as a session identifier is blocked.
#
# False-positive shield — the hook is conservative. It only fires
# when the unknown-session name appears:
#
#   * As a `session=<name>` / `--session <name>` / `-s <name>` flag.
#   * As a filename segment `session-<name>` or `<name>-session`.
#   * As a directory segment `hapax-council--<name>/` (the operator's
#     worktree-slot convention).
#   * As an argument immediately after `claude-session`, `hapax-session`,
#     `session-context.sh`, or `hapax-whoami`.
#
# Plain-English mentions ("zeta in Greek") or quoted strings in
# longer commands are not blocked. The intent is catching
# automation that reads a session name from config / env / CLI
# flags and uses it to spawn a Claude instance or select a
# worktree, not policing operator chatter.
#
# Rationale: session-naming is a governance invariant (task #152).
# The invariant exists because tooling (session-context.sh,
# hapax-whoami, the worktree cap hook) all assume the approved
# set. A silent drift into "sigma" or "zeta" would break invariants
# on four surfaces simultaneously with no single error surfacing.
#
# Exit codes:
#   0 — no violation OR not a Bash tool call
#   2 — unknown session name detected; command blocked

set -euo pipefail

INPUT="$(cat)"
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
[ "$TOOL" = "Bash" ] || exit 0

CMD="$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
[ -n "$CMD" ] || exit 0

# Strip quoted strings before matching so commit messages / echo'd
# text mentioning "zeta" don't trigger. Reuses the strip pattern
# from no-stale-branches.sh.
CMD_STRIPPED="$(printf '%s' "$CMD" | sed -zE "s/'[^']*'//g; s/\"[^\"]*\"//g")"

# Greek-letter session names that are NOT in the approved set.
# Case-insensitive. This is an explicit deny-list rather than an
# approved-only allow-list — over-matching on allow-list would
# false-positive on `alpha-bearing-string` etc.
UNAPPROVED='zeta|eta|theta|iota|kappa|lambda|mu|nu|xi|omicron|sigma|tau|upsilon|phi|chi|psi|omega'

# Assemble the regex for where an unapproved name can appear.
# Each pattern is an anchor that strongly implies "this is being
# used as a session identifier", not a substring of an unrelated word.
#
#   1. session=<name> / --session <name> / -s <name>
#   2. hapax-council--<name>/ worktree slot
#   3. immediately following session-context.sh / hapax-whoami /
#      hapax-session / claude-session
#   4. session-<name>.sh or <name>-session.sh filenames
#
# shellcheck disable=SC2016
patterns=(
    "(session=|--session[[:space:]]+|--session=|-s[[:space:]]+)(${UNAPPROVED})\\b"
    "hapax-council--(${UNAPPROVED})/"
    "(session-context\\.sh|hapax-whoami|hapax-session|claude-session)[[:space:]]+(${UNAPPROVED})\\b"
    "session-(${UNAPPROVED})\\.sh"
    "(${UNAPPROVED})-session\\.sh"
)

violation=""
for pat in "${patterns[@]}"; do
    match="$(echo "$CMD_STRIPPED" | grep -oiE "$pat" | head -1 || true)"
    if [ -n "$match" ]; then
        violation="$match"
        break
    fi
done

if [ -n "$violation" ]; then
    echo "BLOCKED: Unknown session name referenced: '$violation'" >&2
    echo "  Approved session names: alpha, beta, gamma, delta, epsilon" >&2
    echo "  Governance: docs/governance/ (session-naming invariant, task #152)" >&2
    echo "  Command: $(echo "$CMD" | head -c 120)" >&2
    exit 2
fi

exit 0
