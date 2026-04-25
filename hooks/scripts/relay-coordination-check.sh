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

# Detect the current session. CLAUDE_ROLE env var wins if set (used by
# the cc-claim CLI + tests); otherwise infer from worktree basename.
SELF="${CLAUDE_ROLE:-}"
if [ -z "$SELF" ]; then
  THIS_WT_BASENAME="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo)")"
  case "$THIS_WT_BASENAME" in
    hapax-council--beta) SELF="beta" ;;
    hapax-council--main-red) SELF="beta" ;;
    hapax-council) SELF="alpha" ;;
    hapax-council--delta*) SELF="delta" ;;
    hapax-council--cascade*) SELF="delta" ;;
    hapax-council--epsilon*) SELF="epsilon" ;;
    hapax-council--op-referent*) SELF="epsilon" ;;
    *) SELF="" ;;
  esac
fi

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

if [ "$ANY_MATCH" = true ]; then
  cat >&2 <<EOF
ADVISORY: editing '$EDIT_PATH' — peer relay match.
$ADVISORY
Recent convergence notes: tail -20 ${RELAY_DIR}/convergence.log
Consider checking peer relay yaml(s) for in-flight edits before proceeding.
This is informational; the edit will not be blocked.
EOF
fi

# ── AUDIT-06+26: explicit path-claim BLOCKING layer ──────────────────
#
# The advisory above is doc-only. It did not prevent the worktree-
# collision incidents that hit alpha (#1347 recovery) and beta (Phase 1
# recovery) within a single 24h window. v4 §3.4 row AUDIT-06 (WSJF 11)
# adds an explicit path-claim BLOCK.
#
# Schema in each session yaml (~/.cache/hapax/relay/{alpha,beta,delta,
# epsilon}.yaml):
#
#     path_claims:
#       - path: agents/studio_compositor/durf_source.py
#         until: 2026-04-25T05:00:00Z   # ISO-8601 UTC, exclusive
#         reason: "AUDIT-01 redaction primitive"
#
# Match: a peer's claim with path P blocks an Edit/Write to any path Q
# such that Q == P, OR Q starts with P + "/" (P is a directory-claim
# covering its subtree). Stale claims (until <= now) skip silently.
#
# Bypass: HAPAX_RELAY_CHECK_HOOK=0 OR HAPAX_INCIDENT=1.

[ "${HAPAX_INCIDENT:-0}" = "1" ] && exit 0

NOW_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Resolve EDIT_PATH to repo-relative form. Worktrees prefix with
# /home/.../hapax-council[--*]/...; strip up to the first known
# repo-relative segment so peer-yaml paths (repo-relative) match.
EDIT_RELPATH="$EDIT_PATH"
case "$EDIT_RELPATH" in
  /*hapax-council*/agents/*|/*hapax-council*/shared/*|/*hapax-council*/logos/*|/*hapax-council*/tests/*|/*hapax-council*/scripts/*|/*hapax-council*/hooks/*|/*hapax-council*/hapax-logos/*|/*hapax-council*/docs/*|/*hapax-council*/config/*|/*hapax-council*/.github/*|/*hapax-council*/axioms/*)
    EDIT_RELPATH="$(printf '%s' "$EDIT_PATH" | sed -E 's|^.*hapax-council[^/]*/||')"
    ;;
esac

BLOCK_PEER=""
BLOCK_PATH=""
BLOCK_UNTIL=""
BLOCK_REASON=""

for yaml in "$RELAY_DIR"/*.yaml; do
  [ -f "$yaml" ] || continue
  PEER="$(basename "$yaml" .yaml)"
  [ "$PEER" = "$SELF" ] && continue
  case "$PEER" in
    onboarding-*|PROTOCOL|glossary|working-mode|alpha-status|beta-status) continue ;;
  esac

  # Parse path_claims — minimal yaml subset:
  #     path_claims:
  #       - path: <p>
  #         until: <iso8601>
  #         reason: "<text>"
  CLAIMS_TSV="$(awk '
    BEGIN { in_pc=0; cur_path=""; cur_until=""; cur_reason="" }
    /^path_claims:[[:space:]]*$/ { in_pc=1; next }
    in_pc && /^[A-Za-z_][A-Za-z0-9_-]*:/ { in_pc=0 }
    in_pc && /^[[:space:]]*-[[:space:]]+path:[[:space:]]*/ {
      if (cur_path != "") { print cur_path "\t" cur_until "\t" cur_reason }
      sub(/^[[:space:]]*-[[:space:]]+path:[[:space:]]*/, ""); gsub(/^"|"$/, "")
      cur_path=$0; cur_until=""; cur_reason=""; next
    }
    in_pc && /^[[:space:]]+until:[[:space:]]*/ {
      sub(/^[[:space:]]+until:[[:space:]]*/, ""); gsub(/^"|"$/, ""); cur_until=$0; next
    }
    in_pc && /^[[:space:]]+reason:[[:space:]]*/ {
      sub(/^[[:space:]]+reason:[[:space:]]*/, ""); gsub(/^"|"$/, ""); cur_reason=$0; next
    }
    END { if (cur_path != "") print cur_path "\t" cur_until "\t" cur_reason }
  ' "$yaml")"

  [ -z "$CLAIMS_TSV" ] && continue

  while IFS=$'\t' read -r CLAIM_PATH CLAIM_UNTIL CLAIM_REASON; do
    [ -z "$CLAIM_PATH" ] && continue
    # TTL check — skip stale.
    if [ -n "$CLAIM_UNTIL" ] && [ "$CLAIM_UNTIL" \< "$NOW_UTC" ]; then
      continue
    fi
    # Exact match OR prefix-with-slash (directory claim).
    if [ "$EDIT_RELPATH" = "$CLAIM_PATH" ] \
       || [ "${EDIT_RELPATH#${CLAIM_PATH}/}" != "$EDIT_RELPATH" ]; then
      BLOCK_PEER="$PEER"
      BLOCK_PATH="$CLAIM_PATH"
      BLOCK_UNTIL="$CLAIM_UNTIL"
      BLOCK_REASON="$CLAIM_REASON"
      break 2
    fi
  done <<< "$CLAIMS_TSV"
done

if [ -n "$BLOCK_PEER" ]; then
  cat >&2 <<EOF
BLOCKED: '$EDIT_RELPATH' is claimed by peer session '$BLOCK_PEER'.
  claim path : $BLOCK_PATH
  claim until: $BLOCK_UNTIL
  reason     : $BLOCK_REASON

Resolution paths:
  1. Wait for the claim to expire (UTC now: $NOW_UTC)
  2. Coordinate with $BLOCK_PEER via ~/.cache/hapax/relay/$BLOCK_PEER.yaml
  3. If incident response: HAPAX_INCIDENT=1 to bypass
  4. If the claim is stale and the peer is gone:
     edit ~/.cache/hapax/relay/$BLOCK_PEER.yaml to drop the claim, retry.

This block prevents worktree-collision incidents (alpha #1347, beta
Phase 1 recovery in 24h window 2026-04-24/25). See v4 §3.4 AUDIT-06.
EOF
  exit 1
fi

exit 0
