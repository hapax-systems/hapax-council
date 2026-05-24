#!/usr/bin/env bash
# authorization-packet-validator.sh — PreToolUse hook (Bash commands)
#
# Blocks git push / gh pr create / gh pr merge / gh api merge paths unless the active
# AuthorityCase has a valid authorization packet with required no-go
# fields. `authority_case` is canonical; `case_id` is a legacy alias.
#
# Required no-go fields on every authorization packet:
#   implementation_authorized, source_mutation_authorized,
#   docs_mutation_authorized, release_authorized, public_current
#
# Bypass: HAPX_METHODOLOGY_EMERGENCY=1 (logged to emergency ledger).
# Failure mode: FAIL-CLOSED on infra errors for push/PR (protected mutations).
# Amendment 1 (HAZ-006): fail-open permitted unauthorized mutations.
#
# SDLC Reform Slice 2 (CASE-SDLC-REFORM-001, SLICE-002-HOOKS-ENFORCEMENT)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/agent-role.sh" ]]; then
  . "$SCRIPT_DIR/agent-role.sh"
fi

INPUT="$(cat)"
TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
release_tool=false
case "$TOOL" in
  Bash|exec_command_pty|exec_command|shell|shell_command|unified_exec) ;;
  mcp__github__create_pull_request|mcp__github__merge_pull_request|mcp__github__push_files)
    release_tool=true
    ;;
  *) exit 0 ;;
esac

CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // .tool_input.cmd // .tool_input.shell_command // empty' 2>/dev/null)" || exit 0
if [[ "$release_tool" != "true" ]]; then
  [ -n "$CMD" ] || exit 0
fi

# Only gate release/publication paths. Match anywhere in chained commands.
is_release="$release_tool"
if [[ -n "$CMD" ]]; then
  echo "$CMD" | grep -qE '(^|[;&|()[:space:]])git[[:space:]]+push([[:space:]]|$)' && is_release=true
  echo "$CMD" | grep -qE '(^|[;&|()[:space:]])gh[[:space:]]+pr[[:space:]]+(create|merge)([[:space:]]|$)' && is_release=true
  echo "$CMD" | grep -qE '(^|[;&|()[:space:]])gh[[:space:]]+api.*pulls.*/merge' && is_release=true
fi
[ "$is_release" = true ] || exit 0

# Emergency bypass (early, before role resolution)
if [[ "${HAPAX_METHODOLOGY_EMERGENCY:-0}" == "1" ]]; then
  _ledger="$HOME/.cache/hapax/methodology-emergency-ledger.jsonl"
  mkdir -p "$(dirname "$_ledger")" 2>/dev/null || true
  printf '{"ts":"%s","role":"unknown","hook":"authorization-packet-validator","cmd":"%s","reason":"early_infra_bypass"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(echo "$CMD" | head -c 80)" \
    >> "$_ledger" 2>/dev/null || true
  echo "authorization-packet-validator: EMERGENCY BYPASS (early) — logged" >&2
  exit 0
fi

# Determine role
role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-}}}"
if [[ -z "$role" ]] && declare -F hapax_agent_role >/dev/null 2>&1; then
  role="$(hapax_agent_role 2>/dev/null || true)"
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
  echo "authorization-packet-validator: BLOCKED — cannot determine role for push/PR validation." >&2
  echo "  Bypass: HAPAX_METHODOLOGY_EMERGENCY=1" >&2
  exit 2
fi

# Read claim file
claim_file="$HOME/.cache/hapax/cc-active-task-$role"
if [[ ! -f "$claim_file" ]]; then
  echo "authorization-packet-validator: BLOCKED — no claimed task for release/PR command." >&2
  echo "  Release actions require a governed task claim with authority_case." >&2
  exit 2
fi
task_id="$(head -n1 "$claim_file" | tr -d '[:space:]')"
if [[ -z "$task_id" ]]; then
  echo "authorization-packet-validator: BLOCKED — claim file is empty for release/PR command." >&2
  exit 2
fi

# Locate task note
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
  echo "authorization-packet-validator: BLOCKED — claimed task '$task_id' not found for release/PR command." >&2
  exit 2
fi

# Parse frontmatter
if ! command -v python3 &>/dev/null; then
  echo "authorization-packet-validator: BLOCKED — python3 missing; cannot validate authorization packet." >&2
  echo "  Bypass: HAPAX_METHODOLOGY_EMERGENCY=1" >&2
  exit 2
fi

validation="$(python3 - "$note_path" <<'PYEOF'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if not text.startswith("---"):
    print("no_frontmatter")
    sys.exit(0)
end = text.find("\n---", 4)
if end < 0:
    print("no_frontmatter")
    sys.exit(0)
front = text[4:end]
fields = {}
for line in front.splitlines():
    line = line.strip()
    if ":" in line:
        key, _, val = line.partition(":")
        fields[key.strip()] = val.strip().strip('"').strip("'")

authority_case = (fields.get("authority_case") or fields.get("case_id", "")).strip()
if authority_case.lower() in {"", "null", "none", "~", "[]"}:
    print("no_authority_case")
    sys.exit(0)

parent_spec = fields.get("parent_spec", "")
if parent_spec.lower() in {"", "null", "none", "~", "[]"}:
    print("missing_parent_spec")
    sys.exit(0)

required_nogo = [
    "implementation_authorized",
    "source_mutation_authorized",
    "docs_mutation_authorized",
    "release_authorized",
    "public_current",
]
missing = [f for f in required_nogo if f not in fields]
if missing:
    print(f"missing_fields:{','.join(missing)}")
    sys.exit(0)

impl = fields.get("implementation_authorized", "false")
release = fields.get("release_authorized", "false")
stage = fields.get("stage", "")

# For push: implementation must be authorized
if impl != "true":
    print(f"impl_not_authorized:{impl}")
    sys.exit(0)

# Shadow denial check: if implementation is authorized,
# release_authorized should be explicitly false unless stage >= S7
stage_num = -1
if stage.startswith("S"):
    try:
        stage_num = int("".join(c for c in stage[1:] if c.isdigit()))
    except ValueError:
        pass

if stage_num < 7 and release != "false":
    print(f"shadow_denial_violation:release_authorized={release}")
    sys.exit(0)

print("valid")
PYEOF
)"

if [[ "$validation" == "no_authority_case" || "$validation" == "no_frontmatter" || "$validation" == "missing_parent_spec" ]]; then
  cat >&2 <<EOF
authorization-packet-validator: BLOCKED — release/PR command lacks governed task authority.

  Validation: $validation
  Task: $task_id
  Note: $note_path
EOF
  exit 2
fi

# Emergency bypass
if [[ "${HAPAX_METHODOLOGY_EMERGENCY:-0}" == "1" ]]; then
  _ledger="$HOME/.cache/hapax/methodology-emergency-ledger.jsonl"
  mkdir -p "$(dirname "$_ledger")"
  printf '{"ts":"%s","role":"%s","task":"%s","hook":"authorization-packet-validator","cmd":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$role" "$task_id" "$(echo "$CMD" | head -c 80)" \
    >> "$_ledger"
  echo "authorization-packet-validator: EMERGENCY BYPASS — logged" >&2
  exit 0
fi

# Validate
case "$validation" in
  valid)
    exit 0
    ;;
  missing_fields:*)
    missing="${validation#missing_fields:}"
    cat >&2 <<EOF
authorization-packet-validator: BLOCKED — missing required no-go fields.

  Task: $task_id
  Missing: $missing
  Note: $note_path

  The authorization packet must declare all no-go fields explicitly.
  To bypass for emergencies: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
    exit 2
    ;;
  impl_not_authorized:*)
    cat >&2 <<EOF
authorization-packet-validator: BLOCKED — implementation_authorized is not true.

  Task: $task_id
  Note: $note_path

  Create an Implementation Slice Authorization Packet (S5) first.
  To bypass for emergencies: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
    exit 2
    ;;
  shadow_denial_violation:*)
    detail="${validation#shadow_denial_violation:}"
    cat >&2 <<EOF
authorization-packet-validator: BLOCKED — shadow denial violation.

  Task: $task_id
  Detail: $detail (must be false at stage < S7)
  Note: $note_path

  To bypass for emergencies: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
    exit 2
    ;;
  *)
    echo "authorization-packet-validator: BLOCKED — unexpected validation result '$validation'." >&2
    echo "  Bypass: HAPAX_METHODOLOGY_EMERGENCY=1" >&2
    exit 2
    ;;
esac
