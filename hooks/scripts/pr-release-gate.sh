#!/usr/bin/env bash
# pr-release-gate.sh — PreToolUse hook (Bash + github MCP).
#
# Keystroke-time release-evidence gate for `gh pr create` / `gh pr merge`
# and their MCP equivalents. Mirrors the release blockers that
# scripts/cc-pr-autoqueue.py applies at the timer — AVSDLC evidence
# (shared.release_gate.evaluate_avsdlc_release_gate) plus the task's
# authority fields — so the verdict appears immediately rather than
# minutes later. For `gh pr merge` it additionally requires the linked
# task's `release_authorized: true` (a merge IS a release).
#
# DISTINCT from push-gate.sh: push-gate is an unconditional "ask the
# operator" approval block. This gate is CONDITIONAL — it blocks only when
# release evidence is actually missing, so autonomous PR creation for
# evidence-complete tasks is never impeded.
#
# Resolution mirrors cc-task-gate.sh: ~/.cache/hapax/cc-active-task-<role>
# names the task_id; the note lives under the cc-tasks vault.
#
# Fail posture: a resolvable note with real blockers → exit 2 (block). An
# unresolvable note or broken precheck infra → loud advisory + exit 0. The
# autoqueue remains the backstop; this additive gate must not wedge the PR
# workflow on infra hiccups.
#
# Bypass: HAPAX_PR_RELEASE_GATE_OFF=1
set -euo pipefail

[ "${HAPAX_PR_RELEASE_GATE_OFF:-0}" = "1" ] && exit 0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [ -f "$SCRIPT_DIR/agent-role.sh" ]; then
  # shellcheck source=agent-role.sh
  . "$SCRIPT_DIR/agent-role.sh"
fi

# Advisory gate: without jq we cannot parse the event. Degrade quietly
# (the autoqueue still enforces) rather than blocking every Bash call.
command -v jq >/dev/null 2>&1 || exit 0

input="$(cat)"
tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null || echo "")"

action=""
case "$tool_name" in
  Bash)
    cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")"
    [ -n "$cmd" ] || exit 0
    if printf '%s' "$cmd" | grep -qE '(^|[[:space:]]|[;&|(])gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$)'; then
      action="create"
    elif printf '%s' "$cmd" | grep -qE '(^|[[:space:]]|[;&|(])gh[[:space:]]+pr[[:space:]]+merge([[:space:]]|$)'; then
      action="merge"
    else
      exit 0
    fi
    ;;
  mcp__github__create_pull_request) action="create" ;;
  mcp__github__merge_pull_request) action="merge" ;;
  *) exit 0 ;;
esac

# --- resolve role through the single resolver (same as cc-task-gate + auth-packet-validator);
# FM-1: branch-name is not identity (the prior branch-regex was phantom-alpha inference). ---
if declare -F hapax_effective_role >/dev/null 2>&1; then
  role="$(hapax_effective_role 2>/dev/null || true)"
else
  role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-${CLAUDE_ROLE:-}}}"
fi
if [ -z "$role" ]; then
  echo "pr-release-gate: ADVISORY — cannot determine session role; skipping release precheck." >&2
  exit 0
fi

claim_file="$HOME/.cache/hapax/cc-active-task-$role"
if [ ! -f "$claim_file" ]; then
  echo "pr-release-gate: ADVISORY — no claimed task for '$role'; skipping release precheck." >&2
  exit 0
fi
task_id="$(head -n1 "$claim_file" | tr -d '[:space:]')"
[ -n "$task_id" ] || exit 0

vault="$HOME/Documents/Personal/20-projects/hapax-cc-tasks"
note=""
for candidate in "$vault/active/$task_id-"*.md "$vault/active/$task_id.md"; do
  if [ -f "$candidate" ]; then
    note="$candidate"
    break
  fi
done
if [ -z "$note" ]; then
  echo "pr-release-gate: ADVISORY — claimed task '$task_id' note not found; skipping." >&2
  exit 0
fi

precheck="$REPO_ROOT/scripts/avsdlc-release-precheck.py"
[ -f "$precheck" ] || exit 0

merge_flag=()
[ "$action" = "merge" ] && merge_flag=(--merge)

set +e
out="$(cd "$REPO_ROOT" && uv run --quiet python "$precheck" "$note" "${merge_flag[@]}" 2>&1)"
rc=$?
set -e

case "$rc" in
  0)
    if [ "$action" = "create" ]; then
      echo "pr-release-gate: release evidence OK for $task_id. Confirm the test suite passed locally before opening this PR (test-before-push)." >&2
    fi
    exit 0
    ;;
  1)
    cat >&2 <<EOF
pr-release-gate: BLOCKED — release evidence incomplete for '$task_id' ($action).
$out
  Task: $note
  This mirrors the cc-pr-autoqueue release gate, surfaced at keystroke time.
  Resolve the blockers above, or bypass for incident response:
    HAPAX_PR_RELEASE_GATE_OFF=1
EOF
    exit 2
    ;;
  *)
    echo "pr-release-gate: ADVISORY — release precheck could not run (rc=$rc); autoqueue remains the backstop." >&2
    [ -n "$out" ] && printf '%s\n' "$out" >&2
    exit 0
    ;;
esac
