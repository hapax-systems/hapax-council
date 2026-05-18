#!/usr/bin/env bash
# hapax-relay-p0-broadcast.sh — fan out a P0 inflection to all peer yamls.
#
# P-6 of the absence-class-bug-prevention-and-remediation epic. When a
# session detects a P0 incident (broadcast silence, identity-correction,
# operator-blocking bug), it can call this script to:
#
#   1. Write the P0 inflection to ~/.cache/hapax/relay/inflections/<ts>-...
#   2. Atomically touch each peer yaml's `p0_broadcast_inbox` field so
#      the next session-cycle picks it up before any other work
#   3. Set `wakeup_reason: P0_BROADCAST` on each peer yaml so any 270s
#      schedule-wakeup ticks fire immediately
#
# Usage:
#   hapax-relay-p0-broadcast.sh <severity> <inflection-file>
#
# severity: P0 (immediate; collapses 270s floor) or P1 (next cycle)
# inflection-file: path to the markdown body of the inflection
#
# Constitutional binders:
#   - feedback_no_operator_approval_waits — P0 broadcast NEVER blocks on operator
#   - feedback_schedule_wakeup_270s_always — overridden ONLY by severity=P0
#   - feedback_never_stall_revert_acceptable — P0 broadcast is a non-stall surface

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROLE_HELPER="$SCRIPT_DIR/../hooks/scripts/agent-role.sh"
if [[ -f "$ROLE_HELPER" ]]; then
    # shellcheck source=../hooks/scripts/agent-role.sh
    . "$ROLE_HELPER"
fi

if [[ $# -lt 2 ]]; then
    echo "usage: hapax-relay-p0-broadcast.sh <severity> <inflection-file>" >&2
    echo "  severity: P0 | P1" >&2
    echo "  inflection-file: path to a markdown file containing the body" >&2
    exit 1
fi

SEVERITY="$1"
INFLECTION_BODY="$2"

if [[ "$SEVERITY" != "P0" && "$SEVERITY" != "P1" ]]; then
    echo "ERROR: severity must be P0 or P1, got '$SEVERITY'" >&2
    exit 2
fi

if [[ ! -f "$INFLECTION_BODY" ]]; then
    echo "ERROR: inflection body not found at $INFLECTION_BODY" >&2
    exit 2
fi

RELAY_DIR="$HOME/.cache/hapax/relay"
INFLECTIONS_DIR="$RELAY_DIR/inflections"
SOURCE_SESSION="${HAPAX_AGENT_NAME:-${CODEX_THREAD_NAME:-${CODEX_SESSION_NAME:-${CODEX_SESSION:-${CODEX_ROLE:-${HAPAX_AGENT_ROLE:-${CLAUDE_ROLE:-}}}}}}}"
if [[ -z "$SOURCE_SESSION" ]] && declare -F hapax_agent_identity >/dev/null 2>&1; then
    SOURCE_SESSION="$(hapax_agent_identity 2>/dev/null || true)"
fi
SOURCE_SESSION="${SOURCE_SESSION:-unknown}"
TS=$(date -u +"%Y%m%dT%H%M%SZ")

mkdir -p "$INFLECTIONS_DIR"

# 1. Write the inflection
INFLECTION_PATH="$INFLECTIONS_DIR/${TS}-${SOURCE_SESSION}-${SEVERITY}-broadcast.md"
{
    echo "# ${SEVERITY} broadcast → all peer sessions"
    echo ""
    echo "**From:** ${SOURCE_SESSION}"
    echo "**Severity:** ${SEVERITY}"
    echo "**Time:** $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo ""
    cat "$INFLECTION_BODY"
} > "$INFLECTION_PATH"

# 2. Atomically touch each peer yaml — append p0_broadcast_inbox + (P0)
#    set wakeup_reason: P0_BROADCAST. Use yq if available; otherwise
#    fall back to a sentinel-line append (peer's session-context.sh
#    parser tolerates either).
PEERS=()
for peer_yaml in "$RELAY_DIR"/*.yaml; do
    [[ -f "$peer_yaml" ]] || continue
    peer="$(basename "$peer_yaml" .yaml)"
    case "$peer" in
        alpha|beta|delta|epsilon|cx-*) ;;
        *) continue ;;
    esac
    PEERS+=("$peer")
done

if [[ "${HAPAX_P0_BROADCAST_DUAL_WRITE_MQ:-0}" == "1" ]]; then
    RECIPIENTS_CSV=""
    for peer in "${PEERS[@]}"; do
        [[ "$peer" == "$SOURCE_SESSION" ]] && continue
        if [[ -z "$RECIPIENTS_CSV" ]]; then
            RECIPIENTS_CSV="$peer"
        else
            RECIPIENTS_CSV="${RECIPIENTS_CSV},${peer}"
        fi
    done
    if [[ -n "$RECIPIENTS_CSV" ]]; then
        python3 - "$SCRIPT_DIR" "${HAPAX_RELAY_MQ_DB:-$RELAY_DIR/messages.db}" "$RECIPIENTS_CSV" "$SOURCE_SESSION" "$SEVERITY" "$INFLECTION_PATH" <<'PY' || true
import sys
from pathlib import Path

script_dir = Path(sys.argv[1])
repo_root = script_dir.parent
db_path = Path(sys.argv[2]).expanduser()
recipients = sys.argv[3]
source = sys.argv[4]
severity = sys.argv[5]
inflection_path = Path(sys.argv[6])

sys.path.insert(0, str(repo_root))

try:
    from shared.relay_mq import send_message
    from shared.relay_mq_envelope import Envelope

    db_path.parent.mkdir(parents=True, exist_ok=True)
    envelope = Envelope(
        sender=source,
        message_type="escalation",
        priority=0 if severity == "P0" else 1,
        subject=f"{severity} broadcast from {source}",
        recipients_spec=recipients,
        payload_path=str(inflection_path),
        tags=["p0-broadcast", "legacy-relay"],
    )
    send_message(db_path, envelope)
except Exception:
    pass
PY
    fi
fi

APPENDED_COUNT=0
for peer in "${PEERS[@]}"; do
    [[ "$peer" == "$SOURCE_SESSION" ]] && continue  # don't write to own yaml
    peer_yaml="$RELAY_DIR/$peer.yaml"
    [[ ! -f "$peer_yaml" ]] && continue

    tmp="$peer_yaml.broadcast-tmp"
    {
        cat "$peer_yaml"
        echo ""
        echo "# ── ${SEVERITY} broadcast appended ${TS} from ${SOURCE_SESSION} ──"
        echo "p0_broadcast_inbox_${TS}: \"${INFLECTION_PATH}\""
        if [[ "$SEVERITY" == "P0" ]]; then
            echo "wakeup_reason: P0_BROADCAST"
        fi
    } > "$tmp"
    mv -f "$tmp" "$peer_yaml"  # atomic rename
    APPENDED_COUNT=$((APPENDED_COUNT + 1))
done

echo "${SEVERITY} broadcast: wrote $INFLECTION_PATH + appended to ${APPENDED_COUNT} peer yamls"
