#!/usr/bin/env bash
# methodology-ledger-digest.sh — read-only digest of the methodology gate-loosening ledger.
#
# The cc-task gate and authorization-packet validator append one JSONL line to
#   ~/.cache/hapax/methodology-emergency-ledger.jsonl
# for every gate loosening: emergency bypass, blank-stage→S6 derivation,
# route_metadata_schema default, and cognition-surface allow. This script renders
# a digest of that ledger so loosenings are REVIEWED, not silent
# (FR-EMERGENCY-BYPASS-UNSURFACED). It is purely advisory and never mutates.
#
# Three consumers share this one tool:
#   • SessionStart surfacing — session-context.sh prints its own inline 24h digest.
#   • Daily ntfy digest      — `methodology-ledger-digest.sh --since 24 --ntfy`
#   • CI PR check            — `methodology-ledger-digest.sh --since 168 --exit-code`
#       exits 2 when un-reviewed emergency bypasses exist, so a CI job can surface
#       them on a PR. (Wiring a timer / GitHub workflow is runtime/CI scope and is
#       deferred to a follow-on task; this script is the reusable, testable core.)
#
# Review SLA: emergency bypasses older than --sla hours (default 24) are flagged
# OVERDUE. Bypasses are the only entries that demand review; derivations, defaults,
# and cognition allows are informational.
set -euo pipefail

LEDGER="${HAPAX_METHODOLOGY_LEDGER:-$HOME/.cache/hapax/methodology-emergency-ledger.jsonl}"
SINCE_HOURS=24
SLA_HOURS=24
WANT_JSON=false
WANT_NTFY=false
WANT_EXIT_CODE=false

usage() {
  cat <<'USAGE'
methodology-ledger-digest.sh — digest the methodology gate-loosening ledger (read-only)

  --since HOURS    window to summarize (default 24)
  --sla HOURS      review-SLA threshold for emergency bypasses (default 24)
  --json           emit machine-readable JSON instead of text
  --ntfy           also send the text digest via ntfy (best-effort)
  --exit-code      exit 2 if un-reviewed emergency bypasses exist in the window
  --ledger PATH    override ledger path (default ~/.cache/hapax/methodology-emergency-ledger.jsonl)
  -h, --help       this help
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --since) SINCE_HOURS="$2"; shift 2 ;;
    --sla) SLA_HOURS="$2"; shift 2 ;;
    --json) WANT_JSON=true; shift ;;
    --ntfy) WANT_NTFY=true; shift ;;
    --exit-code) WANT_EXIT_CODE=true; shift ;;
    --ledger) LEDGER="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "methodology-ledger-digest: unknown arg '$1'" >&2; usage >&2; exit 64 ;;
  esac
done

if ! command -v jq >/dev/null 2>&1; then
  echo "methodology-ledger-digest: jq not found — cannot parse ledger." >&2
  exit 0
fi

if [ ! -f "$LEDGER" ]; then
  $WANT_JSON && echo '{"total":0,"bypasses":0,"overdue":false,"by_kind":{}}'
  $WANT_JSON || echo "Methodology ledger: empty (no loosenings recorded)."
  exit 0
fi

# Single jq pass produces a small JSON summary used by every output mode.
SUMMARY="$(jq -rs --argjson since "$SINCE_HOURS" --argjson sla "$SLA_HOURS" '
  (now - ($since * 3600)) as $cutoff
  | [ .[]
      | {kind: (.kind // "emergency_bypass"),
         t: (try (.ts | fromdateiso8601) catch 0)}
      | select(.t >= $cutoff) ] as $recent
  | ($recent | map(select(.kind | test("bypass")))) as $byp
  | ($recent | map(.t) | min) as $oldest
  | {
      total: ($recent | length),
      bypasses: ($byp | length),
      oldest_bypass_age_h: (if ($byp | length) > 0
        then ((now - ($byp | map(.t) | min)) / 3600 | floor) else 0 end),
      overdue: (if ($byp | length) > 0
        then ((now - ($byp | map(.t) | min)) / 3600) > $sla else false end),
      by_kind: ($recent | group_by(.kind)
        | map({key: .[0].kind, value: length}) | from_entries)
    }
' "$LEDGER" 2>/dev/null || echo '{"total":0,"bypasses":0,"overdue":false,"by_kind":{}}')"

if [ "$WANT_JSON" = true ]; then
  printf '%s\n' "$SUMMARY"
fi

TEXT="$(printf '%s' "$SUMMARY" | jq -r --argjson since "$SINCE_HOURS" '
  if .total == 0 then "Methodology ledger: no loosenings in the last \($since)h."
  else
    "Methodology ledger (\($since)h): \(.total) loosening(s) — "
    + ([.by_kind | to_entries[] | "\(.key)×\(.value)"] | join(", "))
    + (if .bypasses > 0
       then "\n  ⚠ \(.bypasses) emergency bypass(es) need REVIEW (oldest \(.oldest_bypass_age_h)h ago)"
            + (if .overdue then " — OVERDUE" else "" end)
       else "" end)
  end
' 2>/dev/null || true)"

if [ "$WANT_JSON" != true ]; then
  printf '%s\n' "$TEXT"
fi

if [ "$WANT_NTFY" = true ] && [ -n "$TEXT" ]; then
  # Best-effort notification. Prefer the project notifier; fall back to ntfy CLI.
  if command -v hapax-notify >/dev/null 2>&1; then
    printf '%s' "$TEXT" | hapax-notify --title "Methodology ledger" 2>/dev/null || true
  elif command -v ntfy >/dev/null 2>&1; then
    ntfy publish --title "Methodology ledger" hapax "$TEXT" 2>/dev/null || true
  fi
fi

if [ "$WANT_EXIT_CODE" = true ]; then
  BYPASSES="$(printf '%s' "$SUMMARY" | jq -r '.bypasses' 2>/dev/null || echo 0)"
  case "$BYPASSES" in
    ''|*[!0-9]*) BYPASSES=0 ;;
  esac
  [ "$BYPASSES" -gt 0 ] && exit 2
fi

exit 0
