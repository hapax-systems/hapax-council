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
# Failure mode: fail-OPEN on infrastructure errors (vault unreadable,
# python missing, etc.) so the operator's session is never bricked by
# the hook itself. The cost asymmetry favors permissivity for hook
# failures — if the hook breaks, sessions keep working without the gate.

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

# --- 3. Bypass for incident response ---
if [[ "${HAPAX_CC_TASK_GATE_OFF:-0}" == "1" ]]; then
  exit 0
fi

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
  # Cannot determine role — fail-OPEN with stderr hint. Better to
  # let work proceed than to brick the session on a config gap.
  echo "cc-task-gate: cannot determine session role (set HAPAX_AGENT_ROLE, CODEX_ROLE, or CLAUDE_ROLE); allowing" >&2
  exit 0
fi

# --- 5. Read claim file ---
claim_file="$HOME/.cache/hapax/cc-active-task-$role"
if [[ ! -f "$claim_file" ]]; then
  cat >&2 <<EOF
cc-task-gate: BLOCKED — no claimed task for role '$role'.

  Claim a task before mutating files:
    cc-claim <task_id>

  Browse the offered queue in Obsidian:
    20-projects/hapax-cc-tasks/_dashboard/cc-offered.md
EOF
  exit 2
fi

task_id="$(head -n1 "$claim_file" | tr -d '[:space:]')"
if [[ -z "$task_id" ]]; then
  echo "cc-task-gate: claim file is empty for role '$role'; allowing (likely race)" >&2
  exit 0
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
  echo "cc-task-gate: python3 missing; cannot parse frontmatter; allowing" >&2
  exit 0
fi

# Use a tiny inline python to extract status + assigned_to + blocked_reason.
# Output format: "status\tassigned_to\tblocked_reason"
parse_output="$(python3 - "$note_path" <<'PYEOF'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if not text.startswith("---"):
    print("\t\t")
    sys.exit(0)
end = text.find("\n---", 4)
if end < 0:
    print("\t\t")
    sys.exit(0)
front = text[4:end]
status = ""
assigned = ""
blocked_reason = ""
for line in front.splitlines():
    line = line.strip()
    if line.startswith("status:"):
        status = line.split(":", 1)[1].strip()
    elif line.startswith("assigned_to:"):
        assigned = line.split(":", 1)[1].strip()
    elif line.startswith("blocked_reason:"):
        blocked_reason = line.split(":", 1)[1].strip().strip('"').strip("'")
print(f"{status}\t{assigned}\t{blocked_reason}")
PYEOF
)"

status="$(printf '%s' "$parse_output" | cut -f1)"
assigned="$(printf '%s' "$parse_output" | cut -f2)"
blocked_reason="$(printf '%s' "$parse_output" | cut -f3)"

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
    # Allowed.
    exit 0
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
    exit 0
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
    echo "cc-task-gate: unknown status '$status' for task '$task_id'; allowing (fail-OPEN on parser uncertainty)" >&2
    exit 0
    ;;
esac
