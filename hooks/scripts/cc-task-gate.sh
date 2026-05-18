#!/usr/bin/env bash
# cc-task-gate.sh — PreToolUse hook (D-30 Phase 3)
#
# Blocks file-mutating tool calls unless the current CC session has
# CLAIMED a task in the Obsidian vault SSOT and that task is in
# `in_progress` (or about to transition there from `claimed`).
#
# Operator-facing surface for all CC work lives at:
#   ~/Documents/Personal/20-projects/hapax-cc-tasks/
#
# Each session writes its current claim to:
#   ~/.cache/hapax/cc-active-task-{role}
# (one line: the vault task_id, e.g. "ef7b-020")
#
# This hook is OFF BY DEFAULT until D-30 Phase 7 validation completes.
# Activate in Codex by launching `hapax-codex --task-gate`.
#
# Bypass: HAPAX_CC_TASK_GATE_OFF=1 disables the hook (incident response).
#
# Failure mode: FAIL-CLOSED on infrastructure errors for protected
# mutations (Edit/Write/Bash-destructive). Amendment 1 (HAZ-006):
# fail-open permitted unauthorized protected mutations. Protected
# surfaces now block; emergency bypass via HAPAX_METHODOLOGY_EMERGENCY=1
# with audit receipt.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/agent-role.sh" ]]; then
  # shellcheck source=agent-role.sh
  . "$SCRIPT_DIR/agent-role.sh"
fi

# --- 1. Read tool invocation from stdin ---
input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null || echo "")"

# --- 2. Only gate file-mutating tools ---
case "$tool_name" in
  Edit|Write|MultiEdit|NotebookEdit)
    ;;
  Bash)
    # Only gate destructive Bash invocations. Read-only commands stay
    # ungated (saves on hook overhead for the common ls/cat/grep paths).
    bash_cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")"
    case "$bash_cmd" in
      *"git commit"*|*"git push"*|*" > "*|*" >> "*|*"rm "*|*"mv "*) ;;
      *) exit 0 ;;
    esac
    ;;
  *)
    exit 0
    ;;
esac

# --- 2b. Extract edit path for docs-vs-source classification (section 10) ---
edit_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // .tool_input.notebook_path // empty' 2>/dev/null || echo "")"

# --- 3. Bypass for incident response ---
if [[ "${HAPAX_CC_TASK_GATE_OFF:-0}" == "1" ]]; then
  exit 0
fi
# Methodology emergency bypass (logged in section 10 when case_id is present;
# here as early-out when infrastructure prevents reaching section 10).
if [[ "${HAPAX_METHODOLOGY_EMERGENCY:-0}" == "1" ]]; then
  _emergency_ledger="$HOME/.cache/hapax/methodology-emergency-ledger.jsonl"
  mkdir -p "$(dirname "$_emergency_ledger")" 2>/dev/null || true
  printf '{"ts":"%s","role":"unknown","task":"unknown","case":"unknown","tool":"%s","reason":"early_infra_bypass"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$tool_name" \
    >> "$_emergency_ledger" 2>/dev/null || true
  echo "cc-task-gate: EMERGENCY BYPASS (early) — logged" >&2
  exit 0
fi

# --- 3b. Unclaimed governance-intake bootstrap allowance ---
# The task gate must not deadlock the lifecycle it enforces. A session without
# a claim may create a new request or offered cc-task note, but only through a
# path-scoped, content-validated Write event. Ordinary source/runtime/system
# mutation and manual claim-file writes still fail closed below.
set +e
_bootstrap_output="$(
  printf '%s' "$input" | python3 "$SCRIPT_DIR/cc-task-gate-bootstrap.py" 2>&1
)"
_bootstrap_rc=$?
set -e
case "$_bootstrap_rc" in
  0)
    [[ -n "$_bootstrap_output" ]] && printf '%s\n' "$_bootstrap_output" >&2
    exit 0
    ;;
  10)
    ;;
  *)
    [[ -n "$_bootstrap_output" ]] && printf '%s\n' "$_bootstrap_output" >&2
    exit 2
    ;;
esac

# --- 4. Determine session role ---
role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-}}}"
if [[ -z "$role" ]] && declare -F hapax_agent_role >/dev/null 2>&1; then
  role="$(hapax_agent_role 2>/dev/null || true)"
fi
if [[ -z "$role" ]]; then
  # Infer from relay file presence: if exactly one of alpha/beta/delta/epsilon
  # has a recently-modified yaml file (within last 1h), use that role.
  relay_dir="$HOME/.cache/hapax/relay"
  if [[ -d "$relay_dir" ]]; then
    candidates=()
    for r in alpha beta delta epsilon; do
      f="$relay_dir/$r.yaml"
      if [[ -f "$f" ]]; then
        candidates+=("$r")
      fi
    done
    if [[ ${#candidates[@]} -eq 1 ]]; then
      role="${candidates[0]}"
    fi
  fi
fi
if [[ -z "$role" ]]; then
  _branch_name="$(git symbolic-ref --short HEAD 2>/dev/null || true)"
  if [[ "$_branch_name" =~ ^([a-z]+)/ ]]; then
    _branch_role="${BASH_REMATCH[1]}"
    case "$_branch_role" in
      alpha|beta|gamma|delta|epsilon|zeta) role="$_branch_role" ;;
    esac
  fi
fi
if [[ -z "$role" ]]; then
  echo "cc-task-gate: BLOCKED — cannot determine session role (set HAPAX_AGENT_ROLE, CODEX_ROLE, or CLAUDE_ROLE)." >&2
  echo "  Protected mutations require role identification. Bypass: HAPAX_METHODOLOGY_EMERGENCY=1" >&2
  exit 2
fi
claim_file="$HOME/.cache/hapax/cc-active-task-$role"
if [[ ! -f "$claim_file" ]]; then
  cat >&2 <<EOF
cc-task-gate: BLOCKED — no claimed task for role '$role'.

  Claim a task before mutating files:
    cc-claim <task_id>

  To start new work without bypassing the gate, use the Write tool to create
  one of these validated, audited bootstrap notes:
    20-projects/hapax-requests/active/REQ-<timestamp>-<slug>.md
    20-projects/hapax-cc-tasks/active/<task_id>.md

  Then run request-intake-consumer / cc-claim through the normal lifecycle.
  Do not write ~/.cache/hapax/cc-active-task-* by hand.

  Browse the offered queue in Obsidian:
    20-projects/hapax-cc-tasks/_dashboard/cc-offered.md
EOF
  exit 2
fi

task_id="$(head -n1 "$claim_file" | tr -d '[:space:]')"
if [[ -z "$task_id" ]]; then
  echo "cc-task-gate: BLOCKED — claim file is empty for role '$role'." >&2
  echo "  Bypass: HAPAX_METHODOLOGY_EMERGENCY=1" >&2
  exit 2
fi

# --- 6. Locate task note in vault ---
vault_root="$HOME/Documents/Personal/20-projects/hapax-cc-tasks"
note_path=""
for candidate in "$vault_root/active/$task_id-"*.md; do
  if [[ -f "$candidate" ]]; then
    note_path="$candidate"
    break
  fi
done
if [[ -z "$note_path" && -f "$vault_root/active/$task_id.md" ]]; then
  note_path="$vault_root/active/$task_id.md"
fi
if [[ -z "$note_path" ]]; then
  cat >&2 <<EOF
cc-task-gate: BLOCKED — claimed task '$task_id' not found in vault.

  Claim file:    $claim_file (says '$task_id')
  Vault search:  $vault_root/active/$task_id-*.md or $vault_root/active/$task_id.md

  Either the task was moved to closed/ (no longer claimable) or the
  claim file is stale. Re-claim a fresh task:
    cc-claim <task_id>
EOF
  exit 2
fi

# --- 7. Parse frontmatter via python (jq doesn't do YAML) ---
if ! command -v python3 &>/dev/null; then
  echo "cc-task-gate: BLOCKED — python3 missing; cannot validate AuthorityCase." >&2
  echo "  Bypass: HAPAX_METHODOLOGY_EMERGENCY=1" >&2
  exit 2
fi

# Use a tiny inline python to extract status + assigned_to + blocked_reason
# + AuthorityCase fields (case_id, stage, implementation_authorized,
# source_mutation_authorized, docs_mutation_authorized).
# Output format: "status\tassigned_to\tblocked_reason\tcase_id\tstage\timpl_auth\tsrc_auth\tdocs_auth"
parse_output="$(python3 - "$note_path" <<'PYEOF'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if not text.startswith("---"):
    print("\t\t\t\t\t\t\t")
    sys.exit(0)
end = text.find("\n---", 4)
if end < 0:
    print("\t\t\t\t\t\t\t")
    sys.exit(0)
front = text[4:end]
fields = {}
for line in front.splitlines():
    line = line.strip()
    if ":" in line:
        key, _, val = line.partition(":")
        fields[key.strip()] = val.strip().strip('"').strip("'")
status = fields.get("status", "")
assigned = fields.get("assigned_to", "")
blocked_reason = fields.get("blocked_reason", "")
case_id = fields.get("case_id", "")
stage = fields.get("stage", "")
impl_auth = fields.get("implementation_authorized", "")
src_auth = fields.get("source_mutation_authorized", "")
docs_auth = fields.get("docs_mutation_authorized", "")
print(f"{status}\t{assigned}\t{blocked_reason}\t{case_id}\t{stage}\t{impl_auth}\t{src_auth}\t{docs_auth}")
PYEOF
)"

status="$(printf '%s' "$parse_output" | cut -f1)"
assigned="$(printf '%s' "$parse_output" | cut -f2)"
blocked_reason="$(printf '%s' "$parse_output" | cut -f3)"
case_id="$(printf '%s' "$parse_output" | cut -f4)"
case_stage="$(printf '%s' "$parse_output" | cut -f5)"
impl_authorized="$(printf '%s' "$parse_output" | cut -f6)"
src_authorized="$(printf '%s' "$parse_output" | cut -f7)"
docs_authorized="$(printf '%s' "$parse_output" | cut -f8)"

# --- 8. Check assigned_to ---
if [[ "$assigned" != "$role" ]]; then
  cat >&2 <<EOF
cc-task-gate: BLOCKED — task '$task_id' is assigned to '$assigned', not '$role'.

  Note: $note_path
  Either this session has the wrong role, or the operator reassigned
  the task. Refresh the claim file or update the task's assigned_to.
EOF
  exit 2
fi

# --- 9. Check status ---
case "$status" in
  in_progress)
    # Status OK — fall through to AuthorityCase validation (section 10).
    ;;
  claimed)
    # Auto-transition claimed → in_progress on first mutation.
    # The hook itself does the transition (atomic via tmp+rename inside
    # python) so the session doesn't need a separate cc-start helper.
    python3 - "$note_path" <<'PYEOF'
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
new_text = text.replace(
    "status: claimed", "status: in_progress", 1
).replace(
    "updated_at: ", f"updated_at: {now}\n# was: ", 1
).replace(
    "## Session log\n",
    f"## Session log\n- {now} hook transitioned claimed → in_progress on first mutation\n",
    1,
)
# Use replace-line for updated_at instead of the hacky # was: dance.
import re
text2 = re.sub(
    r"^updated_at:.*$",
    f"updated_at: {now}",
    text,
    count=1,
    flags=re.MULTILINE,
)
text3 = text2.replace(
    "status: claimed", "status: in_progress", 1
).replace(
    "## Session log\n",
    f"## Session log\n- {now} hook transitioned claimed → in_progress on first mutation\n",
    1,
)
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(text3, encoding="utf-8")
tmp.replace(path)
PYEOF
    exit 0
    ;;
  blocked)
    cat >&2 <<EOF
cc-task-gate: BLOCKED — task '$task_id' is in BLOCKED state.

  Reason: ${blocked_reason:-(no reason set)}
  Note:   $note_path

  Operator must edit the task to status: in_progress (or claimed) to resume.
EOF
    exit 2
    ;;
  pr_open)
    # PR-open is fine for further edits (CI fixes, review feedback).
    # Fall through to AuthorityCase validation (section 10).
    ;;
  done|withdrawn|superseded)
    cat >&2 <<EOF
cc-task-gate: BLOCKED — task '$task_id' is terminal ('$status').

  Note: $note_path

  This task has shipped or been withdrawn. Claim a fresh task:
    cc-claim <task_id>
EOF
    exit 2
    ;;
  offered|"")
    cat >&2 <<EOF
cc-task-gate: BLOCKED — task '$task_id' is in '$status' state, not claimed.

  Note: $note_path

  Run \`cc-claim $task_id\` to claim it before mutating files.
EOF
    exit 2
    ;;
  *)
    echo "cc-task-gate: BLOCKED — unknown status '$status' for task '$task_id'." >&2
    echo "  Bypass: HAPAX_METHODOLOGY_EMERGENCY=1" >&2
    exit 2
    ;;
esac

# --- 10. AuthorityCase validation (SDLC Reform Slice 2) ---
# If the task has a case_id, it's under the AuthorityCase methodology.
# Validate that the case stage and authorization fields allow mutation.
# Tasks without case_id predate the methodology — allowed (migration compat).
if [[ -z "$case_id" ]]; then
  exit 0
fi

# Emergency bypass with audit logging
if [[ "${HAPAX_METHODOLOGY_EMERGENCY:-0}" == "1" ]]; then
  _emergency_ledger="$HOME/.cache/hapax/methodology-emergency-ledger.jsonl"
  mkdir -p "$(dirname "$_emergency_ledger")"
  printf '{"ts":"%s","role":"%s","task":"%s","case":"%s","tool":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$role" "$task_id" "$case_id" "$tool_name" \
    >> "$_emergency_ledger"
  echo "cc-task-gate: EMERGENCY BYPASS — logged to $_emergency_ledger" >&2
  exit 0
fi

# Stage must be S6 or later for implementation
_stage_num=""
if [[ "$case_stage" =~ ^S([0-9]+) ]]; then
  _stage_num="${BASH_REMATCH[1]}"
fi
if [[ -n "$_stage_num" && "$_stage_num" -lt 6 ]]; then
  cat >&2 <<EOF
cc-task-gate: BLOCKED — AuthorityCase '$case_id' is at stage '$case_stage' (< S6).

  Implementation requires stage >= S6 with implementation_authorized: true.
  Task: $note_path

  To bypass for emergencies: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
  exit 2
fi

# implementation_authorized must be true
if [[ "$impl_authorized" != "true" ]]; then
  cat >&2 <<EOF
cc-task-gate: BLOCKED — AuthorityCase '$case_id' does not have implementation_authorized: true.

  Current value: implementation_authorized: $impl_authorized
  Task: $note_path

  Create an Implementation Slice Authorization Packet (S5) first.
  To bypass for emergencies: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
  exit 2
fi

# Determine if this is a docs-only mutation
_is_docs_edit=false
if [[ -n "$edit_path" ]]; then
  case "$edit_path" in
    */docs/*|*/CLAUDE.md|*/README.md|*/.md) _is_docs_edit=true ;;
  esac
fi

# For docs mutations, check docs_mutation_authorized
if [[ "$_is_docs_edit" == "true" && "$docs_authorized" != "true" ]]; then
  # Source mutation auth subsumes docs if source is authorized
  if [[ "$src_authorized" != "true" ]]; then
    cat >&2 <<EOF
cc-task-gate: BLOCKED — AuthorityCase '$case_id' does not authorize docs mutation.

  docs_mutation_authorized: $docs_authorized
  source_mutation_authorized: $src_authorized
  File: $edit_path
  Task: $note_path

  To bypass for emergencies: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
    exit 2
  fi
fi

exit 0
