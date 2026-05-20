#!/usr/bin/env bash
# cc-task-closure-gate.sh — PreToolUse hook (closure-discipline gate)
#
# Blocks `mv` / `git mv` operations that move a cc-task .md from
#   ~/Documents/Personal/20-projects/hapax-cc-tasks/active/
# into
#   ~/Documents/Personal/20-projects/hapax-cc-tasks/closed/
# when the source file's `## Acceptance criteria` section contains any
# unchecked `- [ ]` checkbox.
#
# Operator dispatch 2026-05-03T00:25Z. Audit found 3 cc-task closure
# errors in 24h:
#   - #2243 closed satisfying 0 of 7 ACs
#   - #2252 closed with explicit AC #5 deviation
#   - #2259 closed with 3 of 8 ACs deferred
# Pattern: closure = "I worked on it" instead of "criteria met".
#
# Reads PreToolUse JSON from stdin per the Claude Code hook contract.
# Inspects ``tool_input.command`` for shell or Python file-move
# invocations whose path patterns match the active→closed transition.
# Calls the pure-logic gate ``scripts/cc-task-closure-check.py`` to read
# the source file and answer "any unchecked AC?" — exits 2 (block) if so.
#
# Bypass: ``HAPAX_CC_TASK_CLOSURE_GATE_OFF=1`` disables the hook
# (incident response only).
#
# Failure mode: fail-OPEN on infrastructure errors (python missing,
# vault unreadable). The cost asymmetry favors permissivity for hook
# infra failures — if the hook breaks, sessions keep working.
#
# Companion: ``scripts/cc-close`` invokes the same checker directly
# because it uses python ``path.unlink()`` not bash ``mv`` (so this
# Bash PreToolUse hook can't see it). Both surfaces share one gate.

set -euo pipefail

if [[ "${HAPAX_CC_TASK_CLOSURE_GATE_OFF:-0}" == "1" ]]; then
  exit 0
fi

if ! command -v python3 &>/dev/null; then
  # fail-OPEN
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKER="$SCRIPT_DIR/../../scripts/cc-task-closure-check.py"

if [[ ! -x "$CHECKER" ]] && [[ ! -f "$CHECKER" ]]; then
  # fail-OPEN — checker missing
  exit 0
fi

# Read PreToolUse JSON (Claude Code hook contract).
input=$(cat)

# Extract tool_name + tool_input.command. The python helper does the
# JSON parse so the bash side stays minimal.
analysis=$(python3 - "$input" <<'PYEOF'
import json
import re
import sys

raw = sys.argv[1]
try:
    payload = json.loads(raw)
except json.JSONDecodeError:
    # Malformed input → fail-OPEN
    print("FAIL_OPEN: malformed PreToolUse JSON")
    sys.exit(0)

tool_name = payload.get("tool_name") or ""
if tool_name != "Bash":
    print("PASS: not Bash")
    sys.exit(0)

cmd = (payload.get("tool_input") or {}).get("command") or ""
# Match any active cc-task note and any closed cc-task destination in the
# same command. This covers `mv`, `git mv`, Python `shutil.move`, and
# `Path.rename` snippets while still ignoring non-closure file movement.
path_re = re.compile(
    r"(?P<path>['\"]?[^'\"\s,()]*hapax-cc-tasks/(?:active|closed)/"
    r"[A-Za-z0-9._/-]+\.md['\"]?)"
)
paths = [m.group("path").strip("'\"") for m in path_re.finditer(cmd)]
src = next((p for p in paths if "/hapax-cc-tasks/active/" in p and p.endswith(".md")), "")
has_closed_destination = any("/hapax-cc-tasks/closed/" in p for p in paths) or bool(
    re.search(r"\S*hapax-cc-tasks/closed(?:/|\s|$)", cmd)
)
if not src or not has_closed_destination:
    print("PASS: not an active->closed cc-task mv")
    sys.exit(0)

print(f"GATE_CHECK: {src}")
PYEOF
)

case "$analysis" in
  PASS:*)
    exit 0
    ;;
  FAIL_OPEN:*)
    exit 0
    ;;
  GATE_CHECK:*)
    src_path="${analysis#GATE_CHECK: }"
    if [[ ! -f "$src_path" ]]; then
      # source missing → not an active-mv we can gate; let the mv fail naturally
      exit 0
    fi
    # Invoke the shared checker. Exit 2 + stderr if any unchecked AC.
    if ! python3 "$CHECKER" "$src_path"; then
      exit 2
    fi
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
