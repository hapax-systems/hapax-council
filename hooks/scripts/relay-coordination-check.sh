#!/usr/bin/env bash
# relay-coordination-check.sh — PreToolUse hook (Edit / Write / MultiEdit / NotebookEdit)
#
# When an edit targets a cross-worktree-shared path, check the relay
# yaml files for any active peer that mentions the path or its
# directory in its prose fields (focus / current_item / decisions /
# context_artifacts). If a match is found, print a stderr advisory
# pointing at the peer's relay yaml so the operator can coordinate.
#
# Never blocks. Pure advisory.
#
# Disable via env var: HAPAX_RELAY_CHECK_HOOK=0

set -euo pipefail

[ "${HAPAX_RELAY_CHECK_HOOK:-1}" = "0" ] && exit 0

INPUT="$(cat)"

TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
case "$TOOL" in
  Edit|Write|MultiEdit|NotebookEdit) ;;
  *) exit 0 ;;
esac

EDIT_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // .tool_input.notebook_path // empty' 2>/dev/null)" || exit 0
[ -n "$EDIT_PATH" ] || exit 0

# Cross-worktree territory: the prefixes that surfaced in the past 7
# days of convergence-log friction. Only fire on these.
case "$EDIT_PATH" in
  *hapax-logos/crates/*) ;;
  *agents/studio_compositor/*) ;;
  *agents/reverie/*) ;;
  *agents/hapax_daimonion/*) ;;
  *agents/dmn/*) ;;
  *agents/visual_layer_aggregator/*) ;;
  *agents/effect_graph/*) ;;
  *shared/*) ;;
  *) exit 0 ;;
esac

RELAY_DIR="${HOME}/.cache/hapax/relay"
[ -d "$RELAY_DIR" ] || exit 0

# Compute a small set of search tokens from the edit path. We
# DELIBERATELY skip generic top-level directory names like "agents",
# "shared", "src", "crates" — they would match every relay yaml.
# Tokens we accept:
#   - basename (most specific)
#   - parent directory IF distinctive (>= 5 chars, not a generic noun)
BASENAME="$(basename "$EDIT_PATH")"
PARENT="$(basename "$(dirname "$EDIT_PATH")")"

# Drop generic / overly broad directory names from the parent token.
# These appear in every session's relay and would saturate the match.
case "$PARENT" in
  agents|shared|src|crates|tests|docs|scripts|hooks|tooling|hapax-logos)
    PARENT=""
    ;;
esac

# Detect the current session by looking at the worktree path. The relay
# yaml files are named by session (alpha/beta/delta). Skip the matching
# yaml so we do not match against our own focus.
THIS_WT_BASENAME="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo)")"
case "$THIS_WT_BASENAME" in
  hapax-council--beta) SELF="beta" ;;
  hapax-council) SELF="alpha" ;;
  hapax-council--delta*) SELF="delta" ;;
  hapax-council--cascade*) SELF="delta" ;;
  hapax-council--epsilon*) SELF="epsilon" ;;
  hapax-council--op-referent*) SELF="epsilon" ;;
  *) SELF="" ;;
esac

ANY_MATCH=false
ADVISORY=""

for yaml in "$RELAY_DIR"/*.yaml; do
  [ -f "$yaml" ] || continue
  PEER="$(basename "$yaml" .yaml)"
  [ "$PEER" = "$SELF" ] && continue
  case "$PEER" in
    onboarding-*|PROTOCOL|glossary|working-mode|alpha-status|beta-status) continue ;;
  esac

  STATUS_LINE="$(grep -E '^session_status:' "$yaml" 2>/dev/null | head -1 || true)"
  case "$STATUS_LINE" in
    *RETIRED*|*CLOSED*) continue ;;
  esac
  # Short status word for the advisory — first word after the colon.
  STATUS_SHORT="$(printf '%s' "$STATUS_LINE" | sed -nE 's/^session_status:\s*"?([A-Z][A-Z_]+).*$/\1/p')"
  [ -z "$STATUS_SHORT" ] && STATUS_SHORT="ACTIVE"

  # Extract prose-bearing lines: focus, current_item, decisions, context_artifacts, open_questions, convergence
  PROSE="$(grep -E '^(focus|current_item|next):|^\s+- (what|".*"):' "$yaml" 2>/dev/null || true)"
  PROSE="$PROSE
$(grep -A 200 '^context_artifacts:' "$yaml" 2>/dev/null | grep -E '^\s+-' | head -50 || true)"
  PROSE="$PROSE
$(grep -A 200 '^convergence:' "$yaml" 2>/dev/null | grep -E '^\s+-' | head -50 || true)"

  MATCHED_TOKEN=""
  for tok in "$BASENAME" "$PARENT"; do
    [ -z "$tok" ] && continue
    [ "$tok" = "/" ] && continue
    [ "$tok" = "." ] && continue
    # Require at least 5 chars for the parent token to avoid matching
    # short generic words like "dmn", "src". Basename is allowed any
    # length because filenames are inherently distinctive.
    if [ "$tok" = "$PARENT" ] && [ "${#tok}" -lt 5 ]; then
      continue
    fi
    if printf '%s' "$PROSE" | grep -qF "$tok"; then
      MATCHED_TOKEN="$tok"
      break
    fi
  done

  if [ -n "$MATCHED_TOKEN" ]; then
    ANY_MATCH=true
    ADVISORY="${ADVISORY}  - ${PEER} (${STATUS_SHORT}) mentions '${MATCHED_TOKEN}' in its relay
"
  fi
done

if [ "$ANY_MATCH" != true ]; then
  exit 0
fi

cat >&2 <<EOF
ADVISORY: editing '$EDIT_PATH' — peer relay match.
$ADVISORY
Recent convergence notes: tail -20 ${RELAY_DIR}/convergence.log
Consider checking peer relay yaml(s) for in-flight edits before proceeding.
This is informational; the edit will not be blocked.
EOF

exit 0
