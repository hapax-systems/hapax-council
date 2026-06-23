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
release_kind="none"
case "$TOOL" in
  Bash|exec_command_pty|exec_command|shell|shell_command|unified_exec) ;;
  mcp__github__create_pull_request)
    release_tool=true
    release_kind="pr_create"
    ;;
  mcp__github__merge_pull_request)
    release_tool=true
    release_kind="merge"
    ;;
  mcp__github__push_files)
    release_tool=true
    release_kind="push_files"
    ;;
  *) exit 0 ;;
esac

CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // .tool_input.cmd // .tool_input.shell_command // empty' 2>/dev/null)" || exit 0
if [[ "$release_tool" != "true" ]]; then
  [ -n "$CMD" ] || exit 0
fi

# Only gate release/publication paths. Shell command parsing must tolerate
# common global-option forms such as `git -C repo push` and
# `gh --repo owner/repo pr create`.
is_release="$release_tool"
if [[ -n "$CMD" && "$is_release" != "true" ]]; then
  if ! command -v python3 &>/dev/null; then
    # Keep fail-closed behavior for obvious protected commands even if the
    # robust shell tokenizer is unavailable; the validation step below will
    # then block because python3 is required to read the authorization packet.
    if printf '%s' "$CMD" | grep -qE '(^|[;&|()[:space:]])git([[:space:]]+[^;&|()[:space:]]+)*[[:space:]]+push([[:space:]]|[;&|()]|$)'; then
      release_kind="push"
    elif printf '%s' "$CMD" | grep -qE '(^|[;&|()[:space:]])gh([[:space:]]+[^;&|()[:space:]]+)*[[:space:]]+pr[[:space:]]+create([[:space:]]|[;&|()]|$)'; then
      release_kind="pr_create"
    elif printf '%s' "$CMD" | grep -qE '(^|[;&|()[:space:]])gh([[:space:]]+[^;&|()[:space:]]+)*[[:space:]]+pr[[:space:]]+merge([[:space:]]|[;&|()]|$)|(^|[;&|()[:space:]])gh([[:space:]]+[^;&|()[:space:]]+)*[[:space:]]+api.*pulls.*/merge'; then
      release_kind="merge"
    fi
  else
    release_kind="$(python3 - "$CMD" <<'PYEOF' 2>/dev/null || printf 'none\n'
import shlex
import sys

cmd = sys.argv[1]
try:
    lexer = shlex.shlex(cmd, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    tokens = list(lexer)
except (TypeError, ValueError):
    tokens = (
        cmd.replace("&&", " && ")
        .replace("||", " || ")
        .replace(";", " ; ")
        .replace("|", " | ")
        .replace("(", " ( ")
        .replace(")", " ) ")
        .split()
    )

separators = {"&&", "||", ";", ";;", ";&", ";;&", "|", "(", ")"}


def _base(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _git_kind(index: int) -> str:
    j = index + 1
    while j < len(tokens):
        tok = tokens[j]
        if tok in separators:
            return "none"
        if tok in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
            j += 2
            continue
        if tok.startswith(("--git-dir=", "--work-tree=", "--namespace=")):
            j += 1
            continue
        if tok.startswith("-"):
            j += 1
            continue
        return "push" if tok == "push" else "none"
    return "none"


def _gh_kind(index: int) -> str:
    j = index + 1
    while j < len(tokens):
        tok = tokens[j]
        if tok in separators:
            return "none"
        if tok in {"-R", "--repo", "--hostname", "--config-dir"}:
            j += 2
            continue
        if tok.startswith(("--repo=", "--hostname=", "--config-dir=")):
            j += 1
            continue
        if tok.startswith("-"):
            j += 1
            continue
        if tok == "pr" and j + 1 < len(tokens):
            if tokens[j + 1] == "create":
                return "pr_create"
            if tokens[j + 1] == "merge":
                return "merge"
        if tok == "api":
            rest = " ".join(tokens[j + 1 :])
            return "merge" if "pulls/" in rest and "/merge" in rest else "none"
        if tok == "release":
            return "release"
        return "none"
    return "none"


seen_kind = "none"
for i, token in enumerate(tokens):
    binary = _base(token)
    if binary == "git":
        kind = _git_kind(i)
    elif binary == "gh":
        kind = _gh_kind(i)
    else:
        continue
    if kind in {"merge", "release"}:
        print(kind)
        break
    if kind != "none" and seen_kind == "none":
        seen_kind = kind
else:
    print(seen_kind)
PYEOF
)"
  fi
  [[ "$release_kind" != "none" ]] && is_release=true
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

# Determine role through the SAME single resolver the write-gate (cc-task-gate.impl.sh) uses,
# so push and write can never disagree on who a session is. FM-1: a worktree's git branch is
# NOT identity — the prior env-cascade + branch-regex fallback here produced phantom roles
# (e.g. a roleless session on an alpha/foo branch resolved to alpha), the live push/write
# split-brain behind the b111a641 triple-claim collision class. (CASE-ROLE-RESOLUTION-DISAMBIG-001.)
if declare -F hapax_effective_role >/dev/null 2>&1; then
  role="$(hapax_effective_role 2>/dev/null || true)"
else
  role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-}}}"
fi
if [[ -z "$role" ]]; then
  echo "authorization-packet-validator: BLOCKED — cannot determine role for push/PR validation." >&2
  echo "  Release actions require a governed task claim with authority_case." >&2
  echo "  Governed path: cc-claim <id> a task with authority_case, or mint a coord-grant, then re-run." >&2
  exit 2
fi

# Read claim file — prefer the session-scoped claim, fall back to the legacy
# plain file (mirrors cc-task-gate.sh's resolution). The plain file is reaped
# routinely for non-slot roles (dev/dev2), so resolving ONLY the plain file
# wrongly blocks governed push/PR even when a valid session-suffixed claim
# exists. Additive + fallback-preserving: identical behaviour when no
# session-suffixed file is present.
session_id=""
if declare -F hapax_session_id >/dev/null 2>&1; then
  session_id="$(hapax_session_id 2>/dev/null || true)"
fi
if [[ -n "$session_id" ]] && [[ -f "$HOME/.cache/hapax/cc-active-task-$role-$session_id" ]]; then
  claim_file="$HOME/.cache/hapax/cc-active-task-$role-$session_id"
elif [[ -f "$HOME/.cache/hapax/cc-active-task-$role" ]]; then
  claim_file="$HOME/.cache/hapax/cc-active-task-$role"
else
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

validation="$(python3 - "$note_path" "$release_kind" <<'PYEOF'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
release_kind = sys.argv[2]
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
# FR-PACKET-VALIDATOR-TEMPLATE-GAP: an absent no-go field is not a malformed
# packet — default it to false at this PRESENCE check only, and ledger it. The
# default is confined here; it never leaks into cc-task-gate.sh's VALUE checks
# (those read the literal frontmatter), so "absent" deterministically reads as
# "not authorized" everywhere and nothing is masked.
defaulted = [f for f in required_nogo if f not in fields]
if defaulted:
    ledger = Path(os.path.expanduser("~/.cache/hapax/methodology-emergency-ledger.jsonl"))
    try:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "kind": "nogo_field_defaulted",
                        "hook": "authorization-packet-validator",
                        "task": fields.get("task_id", ""),
                        "case": authority_case,
                        "release_kind": release_kind,
                        "fields": defaulted,
                        "value": "false",
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    except OSError:
        pass

impl = fields.get("implementation_authorized", "false")
release = fields.get("release_authorized", "false")
stage = fields.get("stage", "")

# For push: implementation must be authorized
if impl != "true":
    print(f"impl_not_authorized:{impl}")
    sys.exit(0)

# Shadow denial check: if implementation is authorized,
# release_authorized should be explicitly false unless stage >= S7. Actual
# merge/release commands are checked after this with release_not_authorized.
stage_num = -1
if stage.startswith("S"):
    try:
        stage_num = int("".join(c for c in stage[1:] if c.isdigit()))
    except ValueError:
        pass

if stage_num < 7 and release != "false":
    print(f"shadow_denial_violation:release_authorized={release}")
    sys.exit(0)

if release_kind in {"merge", "release"} and release != "true":
    print(f"release_not_authorized:{release_kind}:{release}")
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
  release_not_authorized:*)
    detail="${validation#release_not_authorized:}"
    cat >&2 <<EOF
authorization-packet-validator: BLOCKED — release/merge command requires release_authorized: true.

  Task: $task_id
  Detail: $detail
  Note: $note_path

  PR creation and branch push require implementation authority; merge/release
  require explicit release authorization.
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
