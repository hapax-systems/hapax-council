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
# MANDATORY for all interfaces. Claude Code fires this hook directly;
# Codex fires it via codex-hook-adapter.sh (unconditionally since the
# 2026-05-19 codex-lane-crashout-prevention fix).
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

# Daemon-independent escape-grant substrate (reform Phase 4, NEW-2/INV-4). Gives
# this shim `escape_grant_allows <gate>`: a pure file read that honors a signed
# EscapeGrant when the gate would otherwise fail closed — no RPC, works with the
# kernel down.
if [[ -f "$SCRIPT_DIR/escape-grant.sh" ]]; then
  # shellcheck source=escape-grant.sh
  . "$SCRIPT_DIR/escape-grant.sh"
fi

# This gate's scope name for escape grants (a grant must cover this exact gate,
# or "*"). One gate, not a global off-switch.
GATE_NAME="cc-task-gate"

# _emit_block — every BLOCK routes its existing message through here on stdin.
# Before failing closed it honors a signed EscapeGrant covering this gate (a pure
# file read, daemon-independent: NEW-2/INV-4). When no grant is present the
# original operator-facing text is printed unchanged and the shim exits 2. The
# trailing `exit 2` at each call site is an unreachable fail-closed backstop.
_emit_block() {
  local _msg
  _msg="$(cat)"
  if declare -F escape_grant_allows >/dev/null 2>&1 && escape_grant_allows "$GATE_NAME"; then
    echo "cc-task-gate: escape grant honored for '$GATE_NAME' — allowed (logged, daemon-independent)." >&2
    exit 0
  fi
  printf '%s\n' "$_msg" >&2
  exit 2
}

# _record_retro_grant_obligation — deprecation backstop for the unconditional
# HAPAX_METHODOLOGY_EMERGENCY off-switch (master design §4.4 / §7 NEW-2: the
# emergency switch is incident-only and now incurs a MANDATORY signed EscapeGrant
# within 1h). Writes a pending obligation that scripts/coord-retro-grant-watch
# escalates (ntfy) if no covering grant lands before the deadline. Best-effort.
_record_retro_grant_obligation() {
  local role="${1:-unknown}" task="${2:-unknown}" case_id="${3:-unknown}"
  local tool="${4:-unknown}" trigger="${5:-HAPAX_METHODOLOGY_EMERGENCY}"
  local obligations="${HOME}/.cache/hapax/coord-retro-grant-obligations.jsonl"
  local ledger="${HAPAX_METHODOLOGY_LEDGER:-${HOME}/.cache/hapax/methodology-emergency-ledger.jsonl}"
  local now_s deadline_s
  now_s="$(date +%s 2>/dev/null || echo 0)"
  deadline_s=$((now_s + 3600))
  mkdir -p "$(dirname "$obligations")" 2>/dev/null || true
  printf '{"ts":"%s","ts_s":%s,"deadline_s":%s,"status":"pending","gate":"%s","trigger":"%s","role":"%s","task":"%s","case":"%s","tool":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$now_s" "$deadline_s" "$GATE_NAME" "$trigger" "$role" "$task" "$case_id" "$tool" \
    >>"$obligations" 2>/dev/null || true
  printf '{"ts":"%s","kind":"retro_grant_obligation","role":"%s","task":"%s","case":"%s","tool":"%s","deadline_s":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$role" "$task" "$case_id" "$tool" "$deadline_s" \
    >>"$ledger" 2>/dev/null || true
  echo "cc-task-gate: retro-grant obligation recorded (1h deadline). HAPAX_*_OFF is DEPRECATED —" >&2
  echo "  sign a scoped escape instead: scripts/coord-grant-mint --scope $GATE_NAME --reason '<incident>'." >&2
}

# --- 1. Read tool invocation from stdin ---
input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null || echo "")"

bash_cmd=""
mutation_surface_hint="source"

bash_is_mutating() {
  local cmd="$1"
  # Match known write/runtime/release families. Read-only shell remains
  # available without a claim so blocked lanes can inspect and report state.
  printf '%s' "$cmd" | grep -Eiq \
    '(^|[;&|()[:space:]])((git[[:space:]]+(commit|push|apply|reset|checkout|switch|branch|merge|rebase|tag))|(gh[[:space:]]+(api|pr[[:space:]]+(create|merge|edit|close|reopen)|repo|release))|(python[0-9.]*[[:space:]]*<<)|(python[0-9.]*[[:space:]].*(-c|--command).*([.]write_text|[.]write_bytes|open\(|shutil[.]|os[.](remove|unlink|rename|replace)|Path\())|(sed[[:space:]].*-i)|(perl[[:space:]].*-p?i)|(tee([[:space:]]|$))|(cat[[:space:]].*>[[:space:]])|(cp|install|touch|truncate|chmod|chown|mkdir|rm|mv)([[:space:]]|$)|(uv[[:space:]]+pip[[:space:]]+install)|(pip3?[[:space:]]+install)|(pacman|paru|apt|dnf|npm|pnpm|yarn)([[:space:]]|$)|(systemctl|journalctl[[:space:]].*--vacuum|ssh|scp|rsync|docker[[:space:]]+(compose[[:space:]])?(up|down|restart|rm|run|exec)|kill|pkill)([[:space:]]|$))'
}

bash_is_runtime_mutation() {
  local cmd="$1"
  printf '%s' "$cmd" | grep -Eiq \
    '(^|[;&|()[:space:]])((systemctl)|(ssh|scp|rsync)([[:space:]]|$)|(uv[[:space:]]+pip[[:space:]]+install)|(pip3?[[:space:]]+install)|(pacman|paru|apt|dnf)([[:space:]]|$)|(docker[[:space:]]+(compose[[:space:]])?(up|down|restart|rm|run|exec))|(kill|pkill)([[:space:]]|$))'
}

bash_source_mutation_requires_scope() {
  local cmd="$1"
  # The sed/perl/cat sub-patterns are anchored with [^|;&]* (not greedy .*) so the
  # mutating flag/redirect must belong to the sed/perl/cat invocation itself and
  # cannot be borrowed from a downstream command across a pipe or separator. This
  # kills the `sed 's/x/y/' f | grep -iE p` false positive (the `-i` there is grep's)
  # while keeping a real `sed -i …` / `cat … > f` blocked. (FR-BASH-MUTATION-FALSE-POSITIVES)
  printf '%s' "$cmd" | grep -Eiq \
    '(^|[;&|()[:space:]])((git[[:space:]]+(apply|reset|checkout|switch|merge|rebase))|(python[0-9.]*[[:space:]]*<<)|(python[0-9.]*[[:space:]].*(-c|--command).*([.]write_text|[.]write_bytes|open\(|shutil[.]|os[.](remove|unlink|rename|replace)|Path\())|(sed[[:space:]][^|;&]*-i)|(perl[[:space:]][^|;&]*-p?i)|(tee([[:space:]]|$))|(cat[[:space:]][^|;&]*>[[:space:]])|(cp|install|touch|truncate|chmod|chown|mkdir|rm|mv)([[:space:]]|$))'
}

github_tool_is_mutating() {
  local name="$1"
  printf '%s' "$name" | grep -Eiq \
    '(create|update|delete|merge|push|commit|file|branch|tag|release|pull_request|issue_comment)'
}

# Cognition / diagnostic surfaces are never release-risk: operator auto-memory,
# the personal vault (notes, relay receipts), and ephemeral scratch (/dev/shm,
# project /tmp diagnostics). Edits to these are allowed regardless of claim,
# authority, stage, or scope — a blocked lane must still be able to think, take
# notes, and report state. Their integrity is enforced by content-validating
# writers, not the claim gate. (FR-SCOPE-GATES-COGNITION)
#
# Deliberately NARROW vs the design's bare "/tmp": only /tmp/hapax-* diagnostic
# scratch is carved out, so an unclaimed lane cannot write arbitrary /tmp source.
# Repo docs/*.md are deliberately NOT carved here — they keep the existing
# docs_mutation_authorized gate below; broadening cognition to repo docs is a
# separate, explicit follow-on (it would change the docs-authorization invariant).
is_cognition_path() {
  local p="$1"
  [[ -z "$p" ]] && return 1
  # operator auto-memory at any depth under ~/.claude/**/memory/
  if [[ "$p" == "$HOME"/.claude/* && ( "$p" == */memory/* || "$p" == */memory ) ]]; then
    return 0
  fi
  case "$p" in
    # The governance SSOT (cc-task + request notes) is NOT cognition: it keeps its
    # dedicated content-validated bootstrap/claim path so notes cannot be forged or
    # edited unclaimed. Must precede the general vault rule below.
    "$HOME"/Documents/Personal/20-projects/hapax-cc-tasks/*) return 1 ;;
    "$HOME"/Documents/Personal/20-projects/hapax-requests/*) return 1 ;;
    "$HOME"/Documents/Personal/*) return 0 ;;  # personal vault (cognition / PARA notes)
    /dev/shm/*) return 0 ;;                     # ephemeral diagnostic scratch
    /tmp/hapax-*|/tmp/hapax/*) return 0 ;;      # project diagnostic scratch
  esac
  return 1
}

# --- 2. Only gate file-mutating tools ---
# Covers Claude Code (Edit/Write/Bash) AND Codex (apply_patch/exec_command_pty)
# tool names. The codex-hook-adapter normalizes before calling this script, but
# defense-in-depth: if this hook is invoked directly, Codex tool names still match.
case "$tool_name" in
  Edit|Write|MultiEdit|NotebookEdit|apply_patch|ApplyPatch|functions.apply_patch|patch)
    ;;
  Bash|exec_command_pty|exec_command|shell|shell_command|unified_exec)
    bash_cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // .tool_input.cmd // .tool_input.shell_command // empty' 2>/dev/null || echo "")"
    if ! bash_is_mutating "$bash_cmd"; then
      exit 0
    fi
    if bash_is_runtime_mutation "$bash_cmd"; then
      mutation_surface_hint="runtime"
    fi
    ;;
  mcp__github__*)
    if ! github_tool_is_mutating "$tool_name"; then
      exit 0
    fi
    ;;
  *)
    exit 0
    ;;
esac

# --- 2b. Extract edit path for docs-vs-source classification (section 10) ---
edit_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // .tool_input.notebook_path // empty' 2>/dev/null || echo "")"

# --- 2c. Cognition / diagnostic surfaces: always-allow (FR-SCOPE-GATES-COGNITION) ---
# Placed BEFORE the claim/authority/stage/scope blocks so memory, vault notes,
# and ephemeral scratch are never gated — a blocked lane can still think, take
# notes, and report state. Fail-open-WITH-ledger: an advisory + a ledger line
# are emitted (never silent), but no operator gate stands in the way.
if [[ -n "$edit_path" ]] && is_cognition_path "$edit_path"; then
  _cog_role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-unknown}}}"
  _cog_ledger="$HOME/.cache/hapax/methodology-emergency-ledger.jsonl"
  mkdir -p "$(dirname "$_cog_ledger")" 2>/dev/null || true
  printf '{"ts":"%s","kind":"cognition_allow","role":"%s","tool":"%s","path":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$_cog_role" "$tool_name" "$edit_path" \
    >> "$_cog_ledger" 2>/dev/null || true
  echo "cc-task-gate: cognition surface — allowed (advisory, logged): $edit_path" >&2
  exit 0
fi

# --- 3. Bypass for incident response (DEPRECATED — incident-only, now ledgered) ---
# Historically a silent, unconditional, unscoped off-switch — the audit's core
# complaint was that it logged NOTHING. It still works for incident response but
# is now recorded to the methodology ledger (the digest counts it) and points the
# operator at the scoped, signed, daemon-independent escape-grant path instead.
if [[ "${HAPAX_CC_TASK_GATE_OFF:-0}" == "1" ]]; then
  _gate_off_role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-unknown}}}"
  _gate_off_ledger="${HAPAX_METHODOLOGY_LEDGER:-$HOME/.cache/hapax/methodology-emergency-ledger.jsonl}"
  mkdir -p "$(dirname "$_gate_off_ledger")" 2>/dev/null || true
  printf '{"ts":"%s","kind":"cc_task_gate_off_bypass","role":"%s","tool":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$_gate_off_role" "$tool_name" \
    >>"$_gate_off_ledger" 2>/dev/null || true
  echo "cc-task-gate: HAPAX_CC_TASK_GATE_OFF bypass used — LEDGERED. This switch is DEPRECATED" >&2
  echo "  (incident-only). Prefer a scoped signed escape: scripts/coord-grant-mint --scope $GATE_NAME." >&2
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
  _record_retro_grant_obligation "unknown" "unknown" "unknown" "$tool_name" "HAPAX_METHODOLOGY_EMERGENCY"
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

# --- 3c. Shadow decision log (reform 3b PRODUCER source) ---------------------
# From here on every exit is a genuine GATED decision (the non-mutating / cognition
# / bypass / bootstrap early-outs above are NOT logged). Append this gate's REAL
# exit code + the resolved state it decided on to a cache JSONL so
# scripts/policy-decide-shadow-replay can diff it against shared.policy_decide.
# The legacy verdict recorded here is THIS gate's own exit code — never a
# re-derivation via _LEGACY_*_RE, which is exactly the drift the 3b-cutover unit
# must eliminate. Advisory only: `set +e` in the trap guarantees the logging can
# never change the verdict, and HAPAX_GATE_DECISION_LOG_OFF=1 kills it outright.
_shadow_decision_log="${HAPAX_GATE_DECISION_LOG:-$HOME/.cache/hapax/cc-task-gate-decisions.jsonl}"
_emit_gate_decision() {
  local rc=$?
  trap - EXIT
  set +e
  if [[ "${HAPAX_GATE_DECISION_LOG_OFF:-0}" == "1" ]]; then
    return 0
  fi
  if command -v jq >/dev/null 2>&1; then
    mkdir -p "$(dirname "$_shadow_decision_log")" 2>/dev/null
    jq -cn \
      --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --argjson legacy_exit "$rc" \
      --arg role "${role:-}" \
      --arg session_id "${session_id:-}" \
      --arg task_id "${task_id:-}" \
      --arg tool_name "${tool_name:-}" \
      --arg command "${bash_cmd:-}" \
      --arg file_path "${edit_path:-}" \
      --arg mutation_surface "${mutation_surface_hint:-source}" \
      --arg status "${status:-}" \
      --arg assigned_to "${assigned:-}" \
      --arg authority_case "${authority_case:-}" \
      --arg parent_spec "${parent_spec:-}" \
      --arg stage "${case_stage:-}" \
      --arg implementation_authorized "${impl_authorized:-}" \
      --arg source_mutation_authorized "${src_authorized:-}" \
      --arg docs_mutation_authorized "${docs_authorized:-}" \
      --arg runtime_mutation_authorized "${runtime_authorized:-}" \
      --arg mutation_scope_refs "${mutation_scope_refs:-}" \
      '{ts:$ts, legacy_exit:$legacy_exit, role:$role, session_id:$session_id, task_id:$task_id, tool_name:$tool_name, command:$command, file_path:$file_path, mutation_surface:$mutation_surface, status:$status, assigned_to:$assigned_to, authority_case:$authority_case, parent_spec:$parent_spec, stage:$stage, implementation_authorized:$implementation_authorized, source_mutation_authorized:$source_mutation_authorized, docs_mutation_authorized:$docs_mutation_authorized, runtime_mutation_authorized:$runtime_mutation_authorized, mutation_scope_refs:$mutation_scope_refs}' \
      >> "$_shadow_decision_log" 2>/dev/null
  fi
  return 0
}
trap '_emit_gate_decision' EXIT

# --- 4. Determine session identity (coordination reform Phase 1, cluster 6) ---
# Single source of truth in agent-role.sh (sourced above): explicit env →
# agent-role recovery → relay presence → role-less-but-claimable fallback
# ("roleless"). Branch-prefix inference was REMOVED (FM-1): a worktree's git
# branch is not identity — it produced phantom roles (usually alpha) that
# clobbered the role's shared claim file. The role-less degraded mode (audit B)
# lives inside hapax_effective_role: a session with a session id but no role
# resolves to "roleless" and stays fully governed (authority/stage/scope still
# enforced below) rather than being hard-blocked. "No role" never means "no
# escape."
session_id=""
if declare -F hapax_session_id >/dev/null 2>&1; then
  session_id="$(hapax_session_id 2>/dev/null || true)"
fi
if declare -F hapax_effective_role >/dev/null 2>&1; then
  role="$(hapax_effective_role 2>/dev/null || true)"
else
  role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-}}}"
fi
if [[ -z "$role" ]]; then
  # No identity at all (no role AND no session id) — genuinely unkeyable.
  _emit_block <<EOF
cc-task-gate: BLOCKED — cannot determine session role (set HAPAX_AGENT_ROLE, CODEX_ROLE, or CLAUDE_ROLE).
  Protected mutations require a role or a session id. Bypass: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
  exit 2
fi

# Session-keyed claim lookup with legacy fallback. cc-claim keys a claim to
# <role>-<session_id> so two same-role sessions never collide (FM-2); a pre-reform
# claim at the legacy <role> path is still honoured through the cutover.
claim_file=""
if [[ -n "$session_id" ]] && [[ -f "$HOME/.cache/hapax/cc-active-task-$role-$session_id" ]]; then
  claim_file="$HOME/.cache/hapax/cc-active-task-$role-$session_id"
elif [[ -f "$HOME/.cache/hapax/cc-active-task-$role" ]]; then
  claim_file="$HOME/.cache/hapax/cc-active-task-$role"
fi
if [[ -z "$claim_file" ]]; then
  _emit_block <<EOF
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

# Lease heartbeat (reform Phase 1, cluster 6): refresh the resolved claim file's
# mtime — this session is demonstrably alive (it is making a gated call against a
# valid claim). cc-claim treats a claim older than the lease TTL as free, so this
# keeps a live session's lease from aging out and being reaped while a dead
# session's lease still expires. Best-effort; never blocks the decision below.
touch "$claim_file" 2>/dev/null || true

task_id="$(head -n1 "$claim_file" | tr -d '[:space:]')"
if [[ -z "$task_id" ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — claim file is empty for role '$role'.
  Bypass: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
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
  _emit_block <<EOF
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

# Use a tiny inline python to extract status + assignment + AuthorityCase
# fields. `authority_case` is canonical; `case_id` is accepted only as a
# backwards-compatible alias.
# Output format:
# status assigned blocked authority parent_spec route_schema stage impl src docs runtime scope_refs
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
lines = front.splitlines()
idx = 0
def normalize_value(key, val):
    val = val.strip().strip('"').strip("'")
    if key == "mutation_scope_refs" and val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return ""
        items = [
            part.strip().strip('"').strip("'")
            for part in inner.split(",")
            if part.strip()
        ]
        return "\x1f".join(items)
    return val
while idx < len(lines):
    raw = lines[idx]
    line = raw.strip()
    idx += 1
    if not line or line.startswith("#") or ":" not in line:
        continue
    key, _, val = line.partition(":")
    key = key.strip()
    val = normalize_value(key, val)
    if val:
        fields[key] = val
        continue
    items = []
    while idx < len(lines):
        child = lines[idx].strip()
        if child.startswith("- "):
            items.append(child[2:].strip().strip('"').strip("'"))
            idx += 1
            continue
        if not child:
            idx += 1
            continue
        break
    fields[key] = "\x1f".join(items)
status = fields.get("status", "")
assigned = fields.get("assigned_to", "")
blocked_reason = fields.get("blocked_reason", "")
authority_case = fields.get("authority_case") or fields.get("case_id", "")
parent_spec = fields.get("parent_spec", "")
route_schema = fields.get("route_metadata_schema", "")
stage = fields.get("stage", "")
impl_auth = fields.get("implementation_authorized", "")
src_auth = fields.get("source_mutation_authorized", "")
docs_auth = fields.get("docs_mutation_authorized", "")
runtime_auth = fields.get("runtime_mutation_authorized", "")
scope_refs = fields.get("mutation_scope_refs", "")
print(
    f"{status}\t{assigned}\t{blocked_reason}\t{authority_case}\t{parent_spec}\t"
    f"{route_schema}\t{stage}\t{impl_auth}\t{src_auth}\t{docs_auth}\t"
    f"{runtime_auth}\t{scope_refs}"
)
PYEOF
)"

status="$(printf '%s' "$parse_output" | cut -f1)"
assigned="$(printf '%s' "$parse_output" | cut -f2)"
blocked_reason="$(printf '%s' "$parse_output" | cut -f3)"
authority_case="$(printf '%s' "$parse_output" | cut -f4)"
parent_spec="$(printf '%s' "$parse_output" | cut -f5)"
route_schema="$(printf '%s' "$parse_output" | cut -f6)"
case_stage="$(printf '%s' "$parse_output" | cut -f7)"
impl_authorized="$(printf '%s' "$parse_output" | cut -f8)"
src_authorized="$(printf '%s' "$parse_output" | cut -f9)"
docs_authorized="$(printf '%s' "$parse_output" | cut -f10)"
runtime_authorized="$(printf '%s' "$parse_output" | cut -f11)"
mutation_scope_refs="$(printf '%s' "$parse_output" | cut -f12-)"

# --- 8. Check assigned_to ---
if [[ "$assigned" != "$role" ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — task '$task_id' is assigned to '$assigned', not '$role'.

  Note: $note_path
  Either this session has the wrong role, or the operator reassigned
  the task. Refresh the claim file or update the task's assigned_to.
EOF
  exit 2
fi

# --- 9. Check status ---
_transition_claimed=false
case "$status" in
  in_progress)
    # Status OK — fall through to AuthorityCase validation (section 10).
    ;;
  claimed)
    # Defer claimed → in_progress until after AuthorityCase/scope validation.
    # A denied first mutation must not leave the task note marked active.
    _transition_claimed=true
    ;;
  blocked)
    _emit_block <<EOF
cc-task-gate: BLOCKED — task '$task_id' is in BLOCKED state.

  Reason: ${blocked_reason:-(no reason set)}
  Note:   $note_path

  Operator must edit the task to status: in_progress (or claimed) to resume.
EOF
    exit 2
    ;;
  pr_open|merge_queue|ci_green|ready|ready_for_review|review_ready|ready_for_merge)
    # PR-open / merge-queue / ready-family: the owning lane may still mutate
    # files (CI fixes, review feedback, queue/closeout maintenance). The
    # ready-family was previously unhandled here and fell to *) → BLOCK,
    # stranding the ~88 active `ready` tasks (the gate blocked exactly the
    # statuses the autoqueue admits). SSOT: shared/sdlc_lifecycle.py
    # TASK_MUTABLE_STATUSES, pinned by
    # tests/hooks/test_cc_task_gate.py::TestStatusVocabularyDrift.
    # Fall through to AuthorityCase validation (section 10).
    ;;
  done|withdrawn|superseded|completed|complete|closed|fulfilled|resolved|withdrawn_stale|closed_superseded|rejected|refused|not_applicable|deferred|closed_poisoned)
    _emit_block <<EOF
cc-task-gate: BLOCKED — task '$task_id' is terminal ('$status').

  Note: $note_path

  This task has shipped or been withdrawn. Claim a fresh task:
    cc-claim <task_id>
EOF
    exit 2
    ;;
  offered|"")
    _emit_block <<EOF
cc-task-gate: BLOCKED — task '$task_id' is in '$status' state, not claimed.

  Note: $note_path

  Run \`cc-claim $task_id\` to claim it before mutating files.
EOF
    exit 2
    ;;
  *)
    _emit_block <<EOF
cc-task-gate: BLOCKED — unknown status '$status' for task '$task_id'.
  Bypass: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
    exit 2
    ;;
esac

# --- 10. AuthorityCase validation (SDLC Reform Slice 2) ---
# `authority_case` is canonical for current cc-tasks. Missing authority on a
# mutating tool is a hard block; migration compatibility belongs in explicit
# read-only/intake paths, not source/runtime mutation.
is_nullish() {
  local value
  value="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]' | xargs)"
  case "$value" in
    ""|null|none|"~"|"[]") return 0 ;;
    *) return 1 ;;
  esac
}

# Idempotently set a single frontmatter key in a cc-task note: replace the key
# if present, else insert it before the closing '---'. Atomic (tmp + rename).
# Used to stamp a derived/defaulted field durably so downstream release/packet
# checks read it consistently. Best-effort: returns non-zero on any failure.
_stamp_frontmatter_field() {
  local note="$1" key="$2" value="$3"
  python3 - "$note" "$key" "$value" <<'PYEOF' 2>/dev/null || return 1
import sys
from pathlib import Path

path, key, value = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text(encoding="utf-8")
if not text.startswith("---"):
    sys.exit(1)
end = text.find("\n---", 4)
if end < 0:
    sys.exit(1)
front, body = text[4:end], text[end:]
out, found = [], False
for line in front.splitlines():
    stripped = line.strip()
    if stripped.startswith(f"{key}:") or stripped.startswith(f"{key} :"):
        out.append(f"{key}: {value}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}: {value}")
new = "---\n" + "\n".join(out) + body
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(new, encoding="utf-8")
tmp.replace(path)
PYEOF
}

# authority_case and parent_spec remain HARD requirements: they are the verified
# root of authority, not derivable defaults. Error messages point at in-session
# repair (cc-task-repair, next cluster) rather than a dead end.
if is_nullish "$authority_case"; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — mutating task '$task_id' has no authority_case.

  Task: $note_path
  Current field may be missing or legacy-only. Modern mutating work requires
  authority_case plus a non-null parent_spec before any source/runtime change.
  Repair in place (next cluster): cc-task-repair $task_id --backfill-authority
EOF
  exit 2
fi

if is_nullish "$parent_spec"; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — mutating task '$task_id' has no non-null parent_spec.

  AuthorityCase: $authority_case
  Task: $note_path

  Create or attach the parent request/spec first. Read-only diagnosis and
  governed bootstrap note creation remain allowed; source/runtime mutation does not.
  Repair in place (next cluster): cc-task-repair $task_id --attach-parent-spec
EOF
  exit 2
fi

# route_metadata_schema has exactly one legal value (1). A nullish value is a
# template/migration gap, not an authority defect — default it in-memory and log
# a ledger line (fail-open-WITH-ledger) instead of bricking authorized work.
# (FR-AUTHORITY-FIELDS-FIRST-MUTATION-BLOCK)
if is_nullish "$route_schema"; then
  route_schema=1
  _route_ledger="$HOME/.cache/hapax/methodology-emergency-ledger.jsonl"
  mkdir -p "$(dirname "$_route_ledger")" 2>/dev/null || true
  printf '{"ts":"%s","kind":"route_schema_defaulted","role":"%s","task":"%s","case":"%s","value":1}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$role" "$task_id" "$authority_case" \
    >> "$_route_ledger" 2>/dev/null || true
  echo "cc-task-gate: route_metadata_schema missing — defaulted to 1 (logged for review)." >&2
fi

# Direct docs/report mutations are allowed to happen before implementation
# when the task explicitly authorizes docs mutation. Source/runtime mutation
# still requires S6 + implementation authorization below.
_is_docs_edit=false
if [[ -n "$edit_path" ]]; then
  case "$edit_path" in
    */docs/*|*/CLAUDE.md|*/README.md|*.md) _is_docs_edit=true ;;
  esac
fi

# Emergency bypass with audit logging
if [[ "${HAPAX_METHODOLOGY_EMERGENCY:-0}" == "1" ]]; then
  _emergency_ledger="$HOME/.cache/hapax/methodology-emergency-ledger.jsonl"
  mkdir -p "$(dirname "$_emergency_ledger")"
  printf '{"ts":"%s","role":"%s","task":"%s","case":"%s","tool":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$role" "$task_id" "$authority_case" "$tool_name" \
    >> "$_emergency_ledger"
  echo "cc-task-gate: EMERGENCY BYPASS — logged to $_emergency_ledger" >&2
  _record_retro_grant_obligation "$role" "$task_id" "$authority_case" "$tool_name" "HAPAX_METHODOLOGY_EMERGENCY"
  exit 0
fi

# Stage must be S6 or later for implementation
_stage_num=""
if [[ "$case_stage" =~ ^S([0-9]+) ]]; then
  _stage_num="${BASH_REMATCH[1]}"
fi
# FR-STAGE-S6-TRAP: a blank/unparseable stage on a fully-authorized task
# (authority_case + parent_spec already verified non-null above, plus
# implementation_authorized: true) is a template gap, not a stage deficiency.
# Derive S6 AND stamp an explicit numeric stage into the note so downstream
# release/packet checks read it consistently (closes the shadow-denial brick
# where stage_num=-1 tripped a release-time denial). Fail-open-WITH-ledger.
# Source mutation still requires impl auth + scope below.
if [[ "$_is_docs_edit" != "true" && -z "$_stage_num" && "$impl_authorized" == "true" ]] \
   && ! is_nullish "$authority_case" && ! is_nullish "$parent_spec"; then
  _orig_stage="${case_stage:-<blank>}"
  case_stage="S6_IMPLEMENTATION"
  _stage_num=6
  _stamp_frontmatter_field "$note_path" "stage" "S6_IMPLEMENTATION" || true
  _stage_ledger="$HOME/.cache/hapax/methodology-emergency-ledger.jsonl"
  mkdir -p "$(dirname "$_stage_ledger")" 2>/dev/null || true
  printf '{"ts":"%s","kind":"stage_derived","role":"%s","task":"%s","case":"%s","from":"%s","to":"S6_IMPLEMENTATION"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$role" "$task_id" "$authority_case" "$_orig_stage" \
    >> "$_stage_ledger" 2>/dev/null || true
  echo "cc-task-gate: blank stage on authorized task — derived + stamped S6_IMPLEMENTATION (logged)." >&2
fi
if [[ "$_is_docs_edit" != "true" && ( -z "$_stage_num" || "$_stage_num" -lt 6 ) ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — AuthorityCase '$authority_case' has invalid or insufficient stage '$case_stage' (< S6).

  Implementation requires stage >= S6 with implementation_authorized: true.
  Task: $note_path

  To bypass for emergencies: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
  exit 2
fi

# implementation_authorized must be true
if [[ "$_is_docs_edit" != "true" && "$impl_authorized" != "true" ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — AuthorityCase '$authority_case' does not have implementation_authorized: true.

  Current value: implementation_authorized: $impl_authorized
  Task: $note_path

  Create an Implementation Slice Authorization Packet (S5) first.
  To bypass for emergencies: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
  exit 2
fi

if [[ "$_is_docs_edit" == "true" && "$docs_authorized" != "true" ]]; then
  # Source mutation auth subsumes docs if source is authorized
  if [[ "$src_authorized" != "true" ]]; then
    _emit_block <<EOF
cc-task-gate: BLOCKED — AuthorityCase '$authority_case' does not authorize docs mutation.

  docs_mutation_authorized: $docs_authorized
  source_mutation_authorized: $src_authorized
  File: $edit_path
  Task: $note_path

  To bypass for emergencies: HAPAX_METHODOLOGY_EMERGENCY=1
EOF
    exit 2
  fi
fi

if [[ "$mutation_surface_hint" == "runtime" && "$runtime_authorized" != "true" ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — AuthorityCase '$authority_case' does not authorize runtime mutation.

  runtime_mutation_authorized: $runtime_authorized
  Command: ${bash_cmd:0:160}
  Task: $note_path

  Read-only runtime inspection remains allowed; restart/install/remote/process
  mutation requires an explicit runtime task.
EOF
  exit 2
fi

if [[ "$_is_docs_edit" != "true" && "$mutation_surface_hint" != "runtime" && "$src_authorized" != "true" ]]; then
  _emit_block <<EOF
cc-task-gate: BLOCKED — AuthorityCase '$authority_case' does not authorize source mutation.

  source_mutation_authorized: $src_authorized
  File: ${edit_path:-"(shell/mcp mutation)"}
  Task: $note_path
EOF
  exit 2
fi

if [[ -z "$edit_path" && -n "$bash_cmd" && "$mutation_surface_hint" != "runtime" ]]; then
  # Strip single/double-quoted spans + trailing comments before the source-scope
  # check so mutation tokens that appear only inside a message/echo payload (e.g.
  # `git commit -m "remove the rm and mv helpers"`) don't false-trigger the guard.
  # The quote-strip mirrors the proven no-stale-branches.sh:75 line (sed -z spans
  # newlines, so multi-line "$(cat <<'EOF'…)" payloads are stripped too); the
  # comment-strip only removes '#' at a word boundary so `${v#x}` / URL fragments
  # survive. NOT applied to bash_is_mutating / bash_is_runtime_mutation — those
  # stay raw so a quoted `systemctl` or python-write inside a heredoc still fails
  # closed. (FR-BASH-MUTATION-FALSE-POSITIVES)
  _cmd_stripped="$(printf '%s' "$bash_cmd" | sed -zE "s/'[^']*'//g; s/\"[^\"]*\"//g; s/(^|[[:space:]])#[^\n]*//g")"
  if bash_source_mutation_requires_scope "$_cmd_stripped"; then
    _emit_block <<EOF
cc-task-gate: BLOCKED — cannot verify mutation_scope_refs for shell source mutation.

  Command: ${bash_cmd:0:160}
  Task: $note_path
EOF
    exit 2
  fi
fi

if [[ -n "$edit_path" ]]; then
  scope_check="$(python3 - "$edit_path" "$mutation_scope_refs" <<'PYEOF'
import os
import sys
from pathlib import Path

target_raw, scope_blob = sys.argv[1], sys.argv[2]
if not scope_blob.strip():
    print("missing")
    sys.exit(0)

target = Path(target_raw)
if not target.is_absolute():
    target = Path.cwd() / target
try:
    target_resolved = target.resolve(strict=False)
except Exception:
    target_resolved = target.absolute()

allowed = False
for raw in scope_blob.split("\x1f"):
    item = raw.strip()
    if not item or item.startswith(("cc-task:", "request:")):
        continue
    scope = Path(os.path.expanduser(item))
    if not scope.is_absolute():
        scope = Path.cwd() / scope
    try:
        scope_resolved = scope.resolve(strict=False)
    except Exception:
        scope_resolved = scope.absolute()
    if str(scope_resolved).endswith(os.sep):
        if str(target_resolved).startswith(str(scope_resolved)):
            allowed = True
            break
    if target_resolved == scope_resolved:
        allowed = True
        break
    if scope.exists() and scope.is_dir():
        try:
            target_resolved.relative_to(scope_resolved)
            allowed = True
            break
        except ValueError:
            pass

print("allowed" if allowed else "denied")
PYEOF
)"
  case "$scope_check" in
    allowed) ;;
    missing)
      _emit_block <<EOF
cc-task-gate: BLOCKED — task '$task_id' has no mutation_scope_refs for direct file mutation.

  File: $edit_path
  Task: $note_path
EOF
      exit 2
      ;;
    *)
      _emit_block <<EOF
cc-task-gate: BLOCKED — file is outside this task's declared mutation_scope_refs.

  File: $edit_path
  Task: $note_path
EOF
      exit 2
      ;;
  esac
fi

if [[ "$_transition_claimed" == "true" ]]; then
  python3 - "$note_path" <<'PYEOF'
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
fi

exit 0
