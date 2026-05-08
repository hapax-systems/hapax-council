#!/usr/bin/env bash
# authorization-packet-validator.sh — PreToolUse hook (Bash commands)
#
# Blocks git push / gh pr create / gh pr merge unless the active
# AuthorityCase has a valid authorization packet with required no-go
# fields. Tasks without case_id (pre-methodology) are allowed.
#
# Required no-go fields on every authorization packet:
#   implementation_authorized, source_mutation_authorized,
#   docs_mutation_authorized, release_authorized, public_current
#
# Bypass: HAPX_METHODOLOGY_EMERGENCY=1 (logged to emergency ledger).
# Failure mode: fail-OPEN on infrastructure errors.
#
# SDLC Reform Slice 2 (CASE-SDLC-REFORM-001, SLICE-002-HOOKS-ENFORCEMENT)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/agent-role.sh" ]]; then
  . "$SCRIPT_DIR/agent-role.sh"
fi

INPUT="$(cat)"
TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
[ "$TOOL" = "Bash" ] || exit 0

CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
[ -n "$CMD" ] || exit 0

# Only gate push/PR commands
is_release=false
echo "$CMD" | grep -qE '^\s*git\s+push(\s|$)' && is_release=true
echo "$CMD" | grep -qE '^\s*gh\s+pr\s+(create|merge)(\s|$)' && is_release=true
echo "$CMD" | grep -qE '^\s*gh\s+api.*pulls.*/merge' && is_release=true
[ "$is_release" = true ] || exit 0

# Determine role
role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-}}}"
if [[ -z "$role" ]] && declare -F hapax_agent_role >/dev/null 2>&1; then
  role="$(hapax_agent_role 2>/dev/null || true)"
fi
if [[ -z "$role" ]]; then
  echo "authorization-packet-validator: cannot determine role; allowing (fail-OPEN)" >&2
  exit 0
fi

# Read claim file
claim_file="$HOME/.cache/hapax/cc-active-task-$role"
if [[ ! -f "$claim_file" ]]; then
  exit 0
fi
task_id="$(head -n1 "$claim_file" | tr -d '[:space:]')"
if [[ -z "$task_id" ]]; then
  exit 0
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
  exit 0
fi

# Parse frontmatter
if ! command -v python3 &>/dev/null; then
  echo "authorization-packet-validator: python3 missing; allowing (fail-OPEN)" >&2
  exit 0
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

case_id = fields.get("case_id", "")
if not case_id:
    print("no_case")
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

# Pre-methodology tasks: allow
if [[ "$validation" == "no_case" || "$validation" == "no_frontmatter" ]]; then
  exit 0
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
    echo "authorization-packet-validator: unexpected validation result '$validation'; allowing (fail-OPEN)" >&2
    exit 0
    ;;
esac
