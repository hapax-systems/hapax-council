#!/usr/bin/env bash
# Gate side-effecting MCP/app connector calls on route/quota/resource/authority receipts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [[ -f "$SCRIPT_DIR/agent-role.sh" ]]; then
  # shellcheck source=agent-role.sh
  . "$SCRIPT_DIR/agent-role.sh"
fi

input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null || echo "")"

if [[ -z "$tool_name" ]]; then
  exit 0
fi

classifier_rc=2
if command -v python3 >/dev/null 2>&1; then
  set +e
  PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}" \
    python3 -m shared.mcp_connector_policy is-side-effecting "$tool_name" >/dev/null 2>&1
  classifier_rc=$?
  set -e
fi
if [[ "$classifier_rc" == 1 ]]; then
  exit 0
fi
if [[ "$classifier_rc" != 0 ]]; then
  echo "mcp-connector-mutator-gate: BLOCKED — connector classifier failed for '$tool_name'." >&2
  echo "  Next action: repair shared.mcp_connector_policy or config/mcp-connector-tool-manifest.json, then retry." >&2
  exit 2
fi

session_id=""
if declare -F hapax_session_id >/dev/null 2>&1; then
  session_id="$(hapax_session_id 2>/dev/null || true)"
fi
if declare -F hapax_effective_role >/dev/null 2>&1; then
  role="$(hapax_effective_role 2>/dev/null || true)"
else
  role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-}}}"
fi
if [[ -z "${role:-}" ]]; then
  echo "mcp-connector-mutator-gate: BLOCKED — cannot determine session role." >&2
  echo "  Next action: relaunch through scripts/hapax-methodology-dispatch or assert the lane identity." >&2
  exit 2
fi

claim_file=""
if [[ -n "$session_id" && -f "$HOME/.cache/hapax/cc-active-task-$role-$session_id" ]]; then
  claim_file="$HOME/.cache/hapax/cc-active-task-$role-$session_id"
elif [[ -f "$HOME/.cache/hapax/cc-active-task-$role" ]]; then
  claim_file="$HOME/.cache/hapax/cc-active-task-$role"
fi
if [[ -z "$claim_file" ]]; then
  echo "mcp-connector-mutator-gate: BLOCKED — no claimed task for role '$role'." >&2
  echo "  Next action: claim the dispatched task with scripts/cc-claim before connector mutation." >&2
  exit 2
fi

task_id="$(head -n1 "$claim_file" | tr -d '[:space:]')"
if [[ -z "$task_id" ]]; then
  echo "mcp-connector-mutator-gate: BLOCKED — claim file is empty for role '$role'." >&2
  echo "  Next action: repair or remove the empty claim file, then run scripts/cc-claim for the dispatched task." >&2
  exit 2
fi

args=(
  -m shared.mcp_connector_policy
  receipt-gate
  "$tool_name"
  --task-id "$task_id"
  --role "$role"
)
if [[ -n "${HAPAX_ROUTE_DECISION_LEDGER:-}" ]]; then
  args+=(--ledger "$HAPAX_ROUTE_DECISION_LEDGER")
fi
if [[ -n "${HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR:-}" ]]; then
  args+=(--receipt-dir "$HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR")
fi

set +e
PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}" python3 "${args[@]}"
gate_rc=$?
set -e
if [[ "$gate_rc" -ne 0 ]]; then
  exit 2
fi
