#!/usr/bin/env bash
# Regression tests for cc-task closure gate (Bash PreToolUse hook +
# pure-logic checker). Per cc-task
# cc-task-closure-hook-acceptance-criteria-gate.
#
# Self-contained — uses tmp dirs for vault fixtures and stubbed
# PreToolUse JSON. Does not touch the operator's actual vault.
#
# Run via: bash tests/scripts/test_cc_task_closure_gate.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOOK="$REPO_ROOT/hooks/scripts/cc-task-closure-gate.sh"
CHECKER="$REPO_ROOT/scripts/cc-task-closure-check.py"

if [[ ! -f "$HOOK" ]]; then
  echo "FAIL: hook not found at $HOOK" >&2
  exit 1
fi
if [[ ! -f "$CHECKER" ]]; then
  echo "FAIL: checker not found at $CHECKER" >&2
  exit 1
fi

PASS=0
FAIL=0
FAILURES=()

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    PASS=$((PASS + 1))
    echo "  PASS: $name"
  else
    FAIL=$((FAIL + 1))
    FAILURES+=("$name (expected=$expected actual=$actual)")
    echo "  FAIL: $name (expected=$expected actual=$actual)" >&2
  fi
}

run_checker() {
  # Run the checker on a path; return exit code.
  python3 "$CHECKER" "$1" 2>/dev/null && echo 0 || echo $?
}

run_hook_with_command() {
  # Build a PreToolUse JSON payload for a Bash mv command and pipe to
  # the hook. Echo the hook's exit code.
  local cmd="$1"
  local payload
  payload=$(python3 -c "import json,sys; print(json.dumps({'tool_name':'Bash','tool_input':{'command':sys.argv[1]}}))" "$cmd")
  echo "$payload" | bash "$HOOK" 2>/dev/null && echo 0 || echo $?
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

ACTIVE="$TMP/hapax-cc-tasks/active"
CLOSED="$TMP/hapax-cc-tasks/closed"
mkdir -p "$ACTIVE" "$CLOSED"

# ── Fixture 1: all ACs checked (closure permitted) ─────────────────
cat > "$ACTIVE/all-checked-task.md" <<'EOF'
---
type: cc-task
task_id: all-checked-task
title: "All ACs checked"
status: claimed
---

# All ACs checked

## Acceptance criteria

- [x] AC one done
- [x] AC two done
- [x] AC three done

## Closure evidence
EOF

# ── Fixture 2: one AC unchecked (closure BLOCKED) ──────────────────
cat > "$ACTIVE/unchecked-task.md" <<'EOF'
---
type: cc-task
task_id: unchecked-task
title: "One unchecked AC"
status: claimed
---

# One unchecked AC

## Acceptance criteria

- [x] First done
- [ ] Second NOT done — supposed to block
- [x] Third done

## Closure evidence
EOF

# ── Fixture 3: no AC section at all (closure permitted) ────────────
cat > "$ACTIVE/no-ac-section-task.md" <<'EOF'
---
type: cc-task
task_id: no-ac-section-task
title: "No AC section"
status: claimed
---

# No AC section

## Intent

Substantive supersession doc — no formal AC list.

## Closure evidence

Body explains.
EOF

# ── Fixture 4: AC section present but EMPTY (no checkboxes) ────────
cat > "$ACTIVE/empty-ac-task.md" <<'EOF'
---
type: cc-task
task_id: empty-ac-task
title: "Empty AC section"
status: claimed
---

# Empty AC section

## Acceptance criteria

(intentionally empty pending operator clarification)

## Closure evidence
EOF

echo "=== Pure-logic checker tests ==="
assert_eq "all-checked → exit 0" 0 "$(run_checker "$ACTIVE/all-checked-task.md")"
assert_eq "unchecked → exit 2" 2 "$(run_checker "$ACTIVE/unchecked-task.md")"
assert_eq "no-AC-section → exit 0" 0 "$(run_checker "$ACTIVE/no-ac-section-task.md")"
assert_eq "empty-AC-section → exit 0" 0 "$(run_checker "$ACTIVE/empty-ac-task.md")"

echo "=== Env-var bypass test ==="
assert_eq "HAPAX_CC_TASK_CLOSURE_GATE_OFF=1 unblocks" 0 \
  "$(HAPAX_CC_TASK_CLOSURE_GATE_OFF=1 python3 "$CHECKER" "$ACTIVE/unchecked-task.md" 2>/dev/null && echo 0 || echo $?)"

echo "=== Bash PreToolUse hook tests ==="
# 5. Hook on `mv active/unchecked-task.md closed/`: BLOCK (exit 2)
assert_eq "hook BLOCKS mv of unchecked" 2 \
  "$(run_hook_with_command "mv $ACTIVE/unchecked-task.md $CLOSED/")"

# 6. Hook on `mv active/all-checked-task.md closed/`: PASS (exit 0)
assert_eq "hook PASSES mv of all-checked" 0 \
  "$(run_hook_with_command "mv $ACTIVE/all-checked-task.md $CLOSED/")"

# 7. Hook on `git mv active/unchecked-task.md closed/`: BLOCK
assert_eq "hook BLOCKS git mv of unchecked" 2 \
  "$(run_hook_with_command "git mv $ACTIVE/unchecked-task.md $CLOSED/")"

# 8. Hook on a non-cc-task mv (regular file): PASS
assert_eq "hook PASSES mv of unrelated file" 0 \
  "$(run_hook_with_command "mv /tmp/foo.txt /tmp/bar.txt")"

# 9. Hook on `mv active/x.md other-dir/`: PASS (not active→closed)
assert_eq "hook PASSES mv to non-closed/" 0 \
  "$(run_hook_with_command "mv $ACTIVE/unchecked-task.md $TMP/elsewhere.md")"

# 10. Hook on a non-Bash tool: PASS (not in scope)
non_bash_payload='{"tool_name":"Read","tool_input":{"file_path":"/tmp/x"}}'
assert_eq "hook PASSES non-Bash tool" 0 \
  "$(echo "$non_bash_payload" | bash "$HOOK" 2>/dev/null && echo 0 || echo $?)"

# 11. Hook with HAPAX_CC_TASK_CLOSURE_GATE_OFF=1 + unchecked: PASS
assert_eq "env-off bypasses hook on unchecked" 0 \
  "$(HAPAX_CC_TASK_CLOSURE_GATE_OFF=1 bash -c "echo '$(python3 -c "import json; print(json.dumps({'tool_name':'Bash','tool_input':{'command':'mv $ACTIVE/unchecked-task.md $CLOSED/'}}))")' | bash '$HOOK'" 2>/dev/null && echo 0 || echo $?)"

echo "=== cc-close integration tests ==="
# 12. cc-close BLOCKS unchecked closure with the gate logic in-process.
CC_CLOSE="$REPO_ROOT/scripts/cc-close"
CC_TMP=$(mktemp -d)
CC_VAULT="$CC_TMP/Documents/Personal/20-projects/hapax-cc-tasks"
mkdir -p "$CC_VAULT/active" "$CC_VAULT/closed" "$CC_TMP/.cache/hapax"
cat > "$CC_VAULT/active/cc-close-fixture.md" <<EOF
---
type: cc-task
task_id: cc-close-fixture
status: claimed
completed_at:
updated_at:
pr:
---
# CC close fixture
## Acceptance criteria
- [ ] Should block close

## Session log
EOF
echo "cc-close-fixture" > "$CC_TMP/.cache/hapax/cc-active-task-test-role"

# Without bypass → exit 2
cc_close_blocked_rc=$(HOME="$CC_TMP" CLAUDE_ROLE=test-role bash "$CC_CLOSE" cc-close-fixture >/dev/null 2>&1 && echo 0 || echo $?)
assert_eq "cc-close BLOCKS unchecked → exit 2" 2 "$cc_close_blocked_rc"

# With bypass → exit 0 + actually moves
cc_close_bypass_rc=$(HOME="$CC_TMP" CLAUDE_ROLE=test-role HAPAX_CC_TASK_CLOSURE_GATE_OFF=1 bash "$CC_CLOSE" cc-close-fixture >/dev/null 2>&1 && echo 0 || echo $?)
assert_eq "cc-close BYPASS-on succeeds → exit 0" 0 "$cc_close_bypass_rc"
if [[ -f "$CC_VAULT/closed/cc-close-fixture.md" ]]; then
  PASS=$((PASS + 1))
  echo "  PASS: cc-close BYPASS-on actually moved file to closed/"
else
  FAIL=$((FAIL + 1))
  FAILURES+=("cc-close BYPASS-on did not move file")
  echo "  FAIL: cc-close BYPASS-on did not move file" >&2
fi
rm -rf "$CC_TMP"

echo
if [[ $FAIL -gt 0 ]]; then
  echo "=== $FAIL FAILURES ($PASS passed) ===" >&2
  for f in "${FAILURES[@]}"; do
    echo "  $f" >&2
  done
  exit 1
fi
echo "=== ALL $PASS TESTS PASSED ==="
exit 0
