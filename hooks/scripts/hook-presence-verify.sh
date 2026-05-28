#!/usr/bin/env bash
# hook-presence-verify.sh — SessionStart hook.
#
# Verifies that every hook command registered in ~/.claude/settings.json
# points at an existing, executable script. The audit found that all hooks
# hardcode the canonical worktree path; if that checkout is mid-rebuild (or a
# script is moved/renamed), the entire guardrail set silently no-ops with no
# signal. This surfaces such gaps at session start so the operator knows the
# gates are partially dark before relying on them.
#
# Advisory (SessionStart): always exit 0; prints a loud WARNING on any gap.
# Disable: HAPAX_HOOK_PRESENCE_VERIFY_OFF=1
set -euo pipefail

[ "${HAPAX_HOOK_PRESENCE_VERIFY_OFF:-0}" = "1" ] && exit 0

# Consume any stdin payload (SessionStart provides session metadata).
cat >/dev/null 2>&1 || true

command -v jq >/dev/null 2>&1 || exit 0

settings="${HAPAX_SETTINGS_FILE:-$HOME/.claude/settings.json}"
[ -f "$settings" ] || exit 0

missing=""
total=0
while IFS= read -r cmd; do
  [ -z "$cmd" ] && continue
  # A command may carry args; the script is the first whitespace-delimited token.
  script="${cmd%% *}"
  case "$script" in
    /*) ;;          # absolute path — verifiable
    *) continue ;;  # inline/relative command — not a script path, skip
  esac
  total=$((total + 1))
  if [ ! -x "$script" ]; then
    missing="${missing}
  - ${script}"
  fi
done < <(jq -r '.hooks // {} | to_entries[] | .value[]? | .hooks[]? | .command // empty' "$settings" 2>/dev/null)

if [ -n "$missing" ]; then
  cat >&2 <<EOF
WARNING (hook-presence-verify): registered hook script(s) missing or not executable —
the governance guardrail set may be partially DARK this session:$missing

  Checked $total absolute hook command(s) in $settings.
  Likely cause: the canonical worktree is mid-rebuild, or a hook was moved.
  Restore the canonical checkout before relying on the gates.
EOF
fi

exit 0
