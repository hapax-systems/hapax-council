# Axiom Governance Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the 4 gaps identified in the axiom governance evaluation: add recovery hints, session-aware cross-checking, push-based governance delivery, and broader tool coverage.

**Architecture:** All changes extend existing hook scripts and agents — no new services or infrastructure. Hooks are bash scripts in `~/projects/hapax-system/hooks/scripts/`. Agent code is in `~/projects/ai-agents/`. Hook config is in `~/.claude/settings.json`. Testing uses pytest (ai-agents) and direct bash invocation (hooks).

**Tech Stack:** Bash (hooks), Python/Pydantic (agents), pytest (tests), jq (JSON parsing in hooks)

**Repos involved:**
- `~/projects/hapax-system/` — hook scripts, settings.json changes
- `~/projects/ai-agents/` — briefing integration, axiom tool instrumentation, tests

---

## Task 1: Expand Hook Coverage to MCP Filesystem Tools

The simplest change — a config-only update to `~/.claude/settings.json` so the axiom-scan PreToolUse hook also fires on MCP filesystem write/edit tools. Currently these bypass all axiom enforcement.

**Files:**
- Modify: `~/.claude/settings.json` (hooks.PreToolUse[0].matcher)

**Step 1: Read current settings.json and verify the matcher**

Read `~/.claude/settings.json` and confirm the current PreToolUse matcher for axiom-scan is:
```json
{"matcher": "Edit|Write|MultiEdit"}
```

**Step 2: Update the matcher to include MCP filesystem tools**

Change the matcher to:
```json
{"matcher": "Edit|Write|MultiEdit|mcp__filesystem__write_file|mcp__filesystem__edit_file"}
```

This works because Claude Code's hook system supports `|`-separated tool name matching, and MCP tools use the `mcp__<server>__<tool>` naming convention.

**Step 3: Verify the axiom-scan.sh script handles MCP tool input format**

Read `axiom-scan.sh` line 13 and confirm it extracts content via:
```bash
jq -r '.tool_input.new_string // .tool_input.content // empty'
```

MCP filesystem's `write_file` uses `.tool_input.content` and `edit_file` uses `.tool_input.new_content`. If `edit_file` uses a different field name, add it to the jq chain. Check the MCP filesystem tool schema if unsure — use the `mcp__filesystem__write_file` tool with dummy input to inspect the schema, or check docs.

If `edit_file` uses `new_content` instead of `new_string`, update line 13 of `axiom-scan.sh`:
```bash
CONTENT="$(echo "$INPUT" | jq -r '.tool_input.new_string // .tool_input.content // .tool_input.new_content // empty' 2>/dev/null || true)"
```

Also update the file_path extraction (line 20) to handle MCP's `path` field:
```bash
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // "unknown"' 2>/dev/null || echo unknown)"
```

**Step 4: Manual smoke test**

In a terminal, test the hook with MCP-shaped input:
```bash
printf '{"tool_name":"mcp__filesystem__write_file","tool_input":{"path":"/tmp/test-axiom.py","content":"class User_Manager:\\n    pass\\n"},"session_id":"test"}' | bash ~/projects/hapax-system/hooks/scripts/axiom-scan.sh
echo "Exit code: $?"
```

Expected: Exit code 2, stderr contains "Axiom violation".

**Step 5: Commit**

```bash
cd ~/projects/hapax-system && git add hooks/scripts/axiom-scan.sh
git commit -m "feat: handle MCP filesystem tool input fields in axiom-scan"
```

Settings.json is not in a git repo, so note the change in a commit message or the MEMORY.md.

---

## Task 2: Add Recovery Hints to axiom-scan.sh

When the hook blocks a violation, it should tell the agent *how to proceed*, not just what was blocked. This implements ABC's first-tier fallback (automated guidance).

**Files:**
- Modify: `~/projects/hapax-system/hooks/scripts/axiom-scan.sh:58-78`
- Test: `~/projects/ai-agents/tests/test_axiom_hooks.py`

**Step 1: Write the failing tests**

Add tests to `~/projects/ai-agents/tests/test_axiom_hooks.py` in the `TestAxiomScan` class:

```python
def test_recovery_hint_for_auth_violation(self):
    """Blocked auth pattern should include recovery guidance."""
    result = _run_hook(AXIOM_SCAN, {
        "file_path": "/tmp/test.py",
        "content": "class Auth_Manager:\n    pass\n",
    })
    assert result.returncode == 2
    assert b"Recovery:" in result.stderr

def test_recovery_hint_for_mgmt_violation(self):
    """Blocked management governance pattern should include recovery guidance."""
    result = _run_hook(AXIOM_SCAN, {
        "file_path": "/tmp/test.py",
        "content": "class Feedback_Generator:\n    pass\n",
    })
    assert result.returncode == 2
    assert b"Recovery:" in result.stderr
    assert b"management_governance" in result.stderr
```

Note: the second test uses `class Feedback_Generator` (a class name pattern) rather than a function definition, to avoid triggering the axiom hook on this plan file itself.

**Step 2: Run tests to verify they fail**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_axiom_hooks.py::TestAxiomScan::test_recovery_hint_for_auth_violation tests/test_axiom_hooks.py::TestAxiomScan::test_recovery_hint_for_mgmt_violation -v
```

Expected: FAIL — stderr doesn't contain "Recovery:" yet.

**Step 3: Add recovery hints to axiom-scan.sh**

In `~/projects/hapax-system/hooks/scripts/axiom-scan.sh`, replace lines 58-78 (the match handling block inside the for loop) with:

```bash
  MATCHED="$(echo "$SCANNABLE" | grep -Ei "$pattern" 2>/dev/null | head -1 || true)"
  if [ -n "$MATCHED" ]; then
    MATCHED="$(echo "$MATCHED" | sed 's/^[[:space:]]*//')"
    # Identify which axiom domain the pattern belongs to
    case "$pattern" in
      *feedback*|*to_say*|*Feedback_Generator*|*Coaching_Recommender*)
        DOMAIN="management_governance"
        IMPLS="mg-boundary-001, mg-boundary-002"
        DESC="This generates feedback/coaching language prohibited by management governance."
        RECOVERY="Keep the data aggregation but remove generated language. Surface patterns and open loops; let the operator formulate their own words."
        ;;
      *)
        DOMAIN="single_user"
        IMPLS="su-auth-001, su-feature-001, su-privacy-001, su-security-001, su-admin-001"
        DESC="This introduces multi-user scaffolding prohibited by axiom governance."
        # Sub-categorize recovery hint
        case "$pattern" in
          *[Aa]uth*|*[Pp]ermission*|*[Rr]ole*|*authenticate*|*authorize*|*login*|*logout*)
            RECOVERY="Remove auth/permission/role code entirely. The single user is always authorized. If protecting a dangerous operation, use a confirmation prompt instead."
            ;;
          *[Uu]ser*|*[Tt]enant*|*[Mm]ulti*)
            RECOVERY="Remove user/tenant abstraction. Reference the operator directly or use config values. There is exactly one user."
            ;;
          *[Ss]haring*|*[Cc]ollab*)
            RECOVERY="Remove sharing/collaboration features. If the goal is data export, implement direct file export instead."
            ;;
          *)
            RECOVERY="Remove the multi-user scaffolding. If the underlying goal is valid, reimplement assuming a single operator with full access."
            ;;
        esac
        ;;
    esac
    echo "Axiom violation (T0/$DOMAIN): pattern matched in $FILE_PATH" >&2
    echo "Matched: $MATCHED" >&2
    echo "$DESC" >&2
    echo "Relevant T0 implications: $IMPLS" >&2
    echo "Recovery: $RECOVERY" >&2
    exit 2
  fi
```

**Step 4: Run tests to verify they pass**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_axiom_hooks.py::TestAxiomScan -v
```

Expected: ALL PASS (including existing tests — no regressions).

**Step 5: Commit**

```bash
cd ~/projects/hapax-system && git add hooks/scripts/axiom-scan.sh
git commit -m "feat: add recovery hints to axiom-scan PreToolUse hook"

cd ~/projects/ai-agents && git add tests/test_axiom_hooks.py
git commit -m "test: add recovery hint assertions for axiom-scan"
```

---

## Task 3: Add Recovery Hints to axiom-commit-scan.sh

Mirror the recovery hints from Task 2 into the Bash tool hook for git commit/push scans.

**Files:**
- Modify: `~/projects/hapax-system/hooks/scripts/axiom-commit-scan.sh:59-79`
- Test: `~/projects/ai-agents/tests/test_axiom_hooks.py`

**Step 1: Write the failing test**

Add to `TestAxiomCommitScan` class:

```python
def test_recovery_hint_in_commit_scan(self):
    """Commit scan violations should include recovery guidance."""
    # Verify the script source contains Recovery output (can't easily simulate git state).
    script = Path.home() / "projects" / "hapax-system" / "hooks" / "scripts" / "axiom-commit-scan.sh"
    content = script.read_text()
    assert 'echo "Recovery: $RECOVERY"' in content
```

**Step 2: Run test to verify it fails**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_axiom_hooks.py::TestAxiomCommitScan::test_recovery_hint_in_commit_scan -v
```

Expected: FAIL — the string isn't in the script yet.

**Step 3: Add recovery hints to axiom-commit-scan.sh**

In `~/projects/hapax-system/hooks/scripts/axiom-commit-scan.sh`, replace the pattern scan loop (lines 59-79) with the same recovery hint logic used in axiom-scan.sh:

```bash
for pattern in "${AXIOM_PATTERNS[@]}"; do
  MATCHED="$(echo "$ADDED_LINES" | grep -Ei "$pattern" 2>/dev/null | head -1 || true)"
  if [ -n "$MATCHED" ]; then
    MATCHED="$(echo "$MATCHED" | sed 's/^[[:space:]]*//')"
    # Identify which axiom domain the pattern belongs to
    case "$pattern" in
      *feedback*|*to_say*|*Feedback_Generator*|*Coaching_Recommender*)
        DOMAIN="management_governance"
        DESC="This generates feedback/coaching language prohibited by management governance."
        RECOVERY="Keep the data aggregation but remove generated language. Surface patterns and open loops; let the operator formulate their own words."
        ;;
      *)
        DOMAIN="single_user"
        DESC="This introduces multi-user scaffolding prohibited by axiom governance."
        case "$pattern" in
          *[Aa]uth*|*[Pp]ermission*|*[Rr]ole*|*authenticate*|*authorize*|*login*|*logout*)
            RECOVERY="Remove auth/permission/role code entirely. The single user is always authorized."
            ;;
          *[Uu]ser*|*[Tt]enant*|*[Mm]ulti*)
            RECOVERY="Remove user/tenant abstraction. There is exactly one user."
            ;;
          *[Ss]haring*|*[Cc]ollab*)
            RECOVERY="Remove sharing/collaboration features."
            ;;
          *)
            RECOVERY="Remove the multi-user scaffolding. Reimplement assuming a single operator with full access."
            ;;
        esac
        ;;
    esac
    echo "Axiom violation in staged/branch changes (T0/$DOMAIN):" >&2
    echo "Matched: $MATCHED" >&2
    echo "$DESC" >&2
    echo "Recovery: $RECOVERY" >&2
    exit 2
  fi
done
```

**Step 4: Run tests to verify they pass**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_axiom_hooks.py -v
```

Expected: ALL PASS.

**Step 5: Commit**

```bash
cd ~/projects/hapax-system && git add hooks/scripts/axiom-commit-scan.sh
git commit -m "feat: add recovery hints to axiom-commit-scan hook"

cd ~/projects/ai-agents && git add tests/test_axiom_hooks.py
git commit -m "test: verify recovery hint presence in commit scan"
```

---

## Task 4: Add Bash File-Write Bypass Detection to axiom-commit-scan.sh

Extend the Bash hook to catch common file-writing patterns that bypass Write/Edit hooks: `sed -i`, `tee`, `>` redirect, `python -c`.

**Files:**
- Modify: `~/projects/hapax-system/hooks/scripts/axiom-commit-scan.sh:34-37`
- Test: `~/projects/ai-agents/tests/test_axiom_hooks.py`

**Step 1: Write the failing tests**

Add to `TestAxiomCommitScan`:

```python
def test_detects_sed_i_with_violation(self):
    """sed -i writing auth patterns should be caught."""
    result = _run_hook(AXIOM_COMMIT_SCAN, {
        "command": "sed -i 's/pass/class User_Manager:\\n    pass/' /tmp/test.py",
    }, tool_name="Bash")
    assert result.returncode == 2
    assert b"Axiom violation" in result.stderr

def test_detects_python_c_with_violation(self):
    """python -c writing auth patterns should be caught."""
    result = _run_hook(AXIOM_COMMIT_SCAN, {
        "command": "python -c \"open('/tmp/test.py','w').write('class Auth_Service:\\n    pass')\"",
    }, tool_name="Bash")
    assert result.returncode == 2

def test_allows_safe_sed(self):
    """sed -i with safe content should pass."""
    result = _run_hook(AXIOM_COMMIT_SCAN, {
        "command": "sed -i 's/old/new/' /tmp/test.py",
    }, tool_name="Bash")
    assert result.returncode == 0

def test_allows_safe_redirect(self):
    """echo redirect with safe content should pass."""
    result = _run_hook(AXIOM_COMMIT_SCAN, {
        "command": "echo 'hello world' > /tmp/test.txt",
    }, tool_name="Bash")
    assert result.returncode == 0
```

**Step 2: Run tests to verify they fail**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_axiom_hooks.py::TestAxiomCommitScan::test_detects_sed_i_with_violation tests/test_axiom_hooks.py::TestAxiomCommitScan::test_detects_python_c_with_violation -v
```

Expected: FAIL — these commands currently pass through (exit 0).

**Step 3: Add file-write detection to axiom-commit-scan.sh**

Restructure the command detection section. Replace lines 18-56 of `axiom-commit-scan.sh` (everything between `COMMAND` extraction and the pattern scan loop) with:

```bash
# Detect git commit
if echo "$COMMAND" | grep -qE '\bgit\s+commit\b'; then
  DIFF="$(git diff --cached 2>/dev/null || true)"
  if [ -z "$DIFF" ]; then
    exit 0
  fi
  ADDED_LINES="$(echo "$DIFF" | grep '^+[^+]' | sed 's/^+//' || true)"

# Detect git push
elif echo "$COMMAND" | grep -qE '\bgit\s+push\b'; then
  BASE="$(git merge-base HEAD main 2>/dev/null || git merge-base HEAD master 2>/dev/null || true)"
  if [ -z "$BASE" ]; then
    exit 0
  fi
  DIFF="$(git diff "$BASE"...HEAD 2>/dev/null || true)"
  if [ -z "$DIFF" ]; then
    exit 0
  fi
  ADDED_LINES="$(echo "$DIFF" | grep '^+[^+]' | sed 's/^+//' || true)"

# Detect Bash file-writing commands (bypass protection)
elif echo "$COMMAND" | grep -qE '(sed\s+-i|tee\s|>\s|python\s+-c|perl\s+-[ip])'; then
  ADDED_LINES="$COMMAND"

else
  # Not a monitored command — pass through
  exit 0
fi

if [ -z "$ADDED_LINES" ]; then
  exit 0
fi

# Strip comments before scanning (full-line and trailing inline comments)
ADDED_LINES="$(echo "$ADDED_LINES" | sed -E \
  -e 's/^[[:space:]]*#[^!].*$//' \
  -e 's/[[:space:]]#[[:space:]].*$//' \
  -e 's/^[[:space:]]*\/\/.*$//' \
  -e 's/[[:space:]]\/\/[[:space:]].*$//' \
  -e 's/<!--.*-->//' \
  -e '/^[[:space:]]*$/d')"

if [ -z "$ADDED_LINES" ]; then
  exit 0
fi
```

**Step 4: Run tests to verify they pass**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_axiom_hooks.py -v
```

Expected: ALL PASS (new and existing tests).

**Step 5: Commit**

```bash
cd ~/projects/hapax-system && git add hooks/scripts/axiom-commit-scan.sh
git commit -m "feat: detect Bash file-write bypass patterns in commit scan hook"

cd ~/projects/ai-agents && git add tests/test_axiom_hooks.py
git commit -m "test: add Bash file-write bypass detection tests"
```

---

## Task 5: Add SessionStart Axiom Nudge

Extend `session-context.sh` to push pending axiom items (pending precedents, stale sweep warnings) into every Claude Code session start. This converts pull-based governance to push-based.

**Files:**
- Modify: `~/projects/hapax-system/hooks/scripts/session-context.sh:53` (append after existing output)

**Step 1: Read current session-context.sh**

Verify it ends after the GPU output block (~line 53). The new code appends after that.

**Step 2: Add axiom nudge section**

Append to `session-context.sh` after the GPU block:

```bash
# Axiom governance nudge (push-based — surfaces status every session)
PENDING_PRECEDENTS=0
if [ -d "$HOME/.cache/cockpit/precedents" ]; then
  LAST_REVIEWED="$HOME/.cache/cockpit/.last-reviewed"
  if [ -f "$LAST_REVIEWED" ]; then
    PENDING_PRECEDENTS=$(find "$HOME/.cache/cockpit/precedents/" -name "*.json" -newer "$LAST_REVIEWED" 2>/dev/null | wc -l)
  else
    PENDING_PRECEDENTS=$(find "$HOME/.cache/cockpit/precedents/" -name "*.json" 2>/dev/null | wc -l)
  fi
fi
if [ "$PENDING_PRECEDENTS" -gt 0 ]; then
  echo "Axioms: $PENDING_PRECEDENTS precedent(s) pending review (run /axiom-review)"
fi

LAST_SWEEP=$(ls -t "$HOME/.cache/axiom-audit"/baseline-*.json 2>/dev/null | head -1)
if [ -n "$LAST_SWEEP" ]; then
  SWEEP_AGE=$(( ($(date +%s) - $(stat -c %Y "$LAST_SWEEP")) / 86400 ))
  if [ "$SWEEP_AGE" -gt 7 ]; then
    echo "Axioms: Last compliance sweep was ${SWEEP_AGE} days ago (run /axiom-sweep)"
  fi
fi
```

**Step 3: Manual smoke test**

Run the hook directly:
```bash
bash ~/projects/hapax-system/hooks/scripts/session-context.sh
```

Expected: Existing output (System Context, Axioms, Branch, Health, Docker, GPU) plus any new axiom nudge lines if there are pending precedents or a stale sweep.

**Step 4: Commit**

```bash
cd ~/projects/hapax-system && git add hooks/scripts/session-context.sh
git commit -m "feat: push axiom governance status into SessionStart context"
```

---

## Task 6: Add Sufficiency Probes to Daily Briefing

The briefing agent already surfaces pending precedents (lines 311-321). Extend it to also report sufficiency probe failures, making axiom health a push-based daily delivery.

**Files:**
- Modify: `~/projects/ai-agents/agents/briefing.py:311-321`
- Test: `~/projects/ai-agents/tests/test_briefing.py`

**Step 1: Write the failing test**

Add to `~/projects/ai-agents/tests/test_briefing.py`:

```python
def test_collect_axiom_status_includes_probes():
    """Axiom status collector should include probe results."""
    from agents.briefing import _collect_axiom_status
    status = _collect_axiom_status()
    assert "probe_total" in status
    assert "probe_failures" in status
    assert isinstance(status["probe_failures"], int)
    assert isinstance(status["failed_probes"], list)
```

**Step 2: Run test to verify it fails**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_briefing.py::test_collect_axiom_status_includes_probes -v
```

Expected: FAIL — `_collect_axiom_status` doesn't exist yet.

**Step 3: Add `_collect_axiom_status` and integrate into briefing**

In `~/projects/ai-agents/agents/briefing.py`, add this function before `generate_briefing()` (around line 165):

```python
def _collect_axiom_status() -> dict:
    """Collect axiom health: sufficiency probes + pending precedents."""
    result: dict = {
        "probe_total": 0,
        "probe_failures": 0,
        "failed_probes": [],
        "pending_precedents": 0,
    }
    try:
        from shared.sufficiency_probes import run_probes
        probes = run_probes()
        result["probe_total"] = len(probes)
        failures = [p for p in probes if not p.met]
        result["probe_failures"] = len(failures)
        result["failed_probes"] = [p.probe_id for p in failures]
    except Exception:
        pass
    try:
        from shared.axiom_precedents import PrecedentStore
        store = PrecedentStore()
        pending = store.get_pending_review(limit=50)
        result["pending_precedents"] = len(pending)
    except Exception:
        pass
    return result
```

Then replace the existing axiom enforcement section in `generate_briefing()` (lines 311-321):

```python
    # Axiom governance section (push-based delivery)
    axiom_section = ""
    try:
        axiom_status = _collect_axiom_status()
        parts = []
        if axiom_status["probe_failures"] > 0:
            passed = axiom_status["probe_total"] - axiom_status["probe_failures"]
            parts.append(f"- Sufficiency probes: {passed}/{axiom_status['probe_total']} passing")
            parts.append(f"- Failed: {', '.join(axiom_status['failed_probes'][:5])}")
        else:
            parts.append(f"- Sufficiency probes: {axiom_status['probe_total']}/{axiom_status['probe_total']} passing")
        if axiom_status["pending_precedents"] > 0:
            parts.append(f"- {axiom_status['pending_precedents']} agent precedent(s) awaiting operator review")
        if parts:
            axiom_section = "\n\n## Axiom Governance\n" + "\n".join(parts)
    except Exception:
        pass
```

**Step 4: Run tests to verify they pass**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_briefing.py -v
```

Expected: ALL PASS.

**Step 5: Commit**

```bash
cd ~/projects/ai-agents && git add agents/briefing.py tests/test_briefing.py
git commit -m "feat: add sufficiency probe results to daily briefing"
```

---

## Task 7: Add Usage Instrumentation to Axiom Tools

Add lightweight telemetry to `check_axiom_compliance()` and `record_axiom_decision()` so we can measure whether Layers 5-7 are earning their maintenance cost. After 30 days, review the log.

**Files:**
- Modify: `~/projects/ai-agents/shared/axiom_tools.py:25-30,109-115`
- Test: `~/projects/ai-agents/tests/test_axiom_tools.py`

**Step 1: Write the failing tests**

Add to `~/projects/ai-agents/tests/test_axiom_tools.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch

def test_check_axiom_compliance_logs_usage(tmp_path):
    """check_axiom_compliance should log usage to JSONL file."""
    usage_log = tmp_path / "tool-usage.jsonl"
    with patch("shared.axiom_tools.USAGE_LOG", usage_log):
        import asyncio
        from shared.axiom_tools import check_axiom_compliance
        ctx = type("MockCtx", (), {"deps": None})()
        asyncio.run(check_axiom_compliance(ctx, "test situation"))
    assert usage_log.exists()
    entry = json.loads(usage_log.read_text().strip().split("\n")[0])
    assert entry["tool"] == "check_axiom_compliance"
    assert "ts" in entry

def test_record_axiom_decision_logs_usage(tmp_path):
    """record_axiom_decision should log usage to JSONL file."""
    usage_log = tmp_path / "tool-usage.jsonl"
    with patch("shared.axiom_tools.USAGE_LOG", usage_log):
        import asyncio
        from shared.axiom_tools import record_axiom_decision
        ctx = type("MockCtx", (), {"deps": None})()
        asyncio.run(record_axiom_decision(
            ctx, "single_user", "test", "compliant", "testing"
        ))
    assert usage_log.exists()
    entry = json.loads(usage_log.read_text().strip().split("\n")[0])
    assert entry["tool"] == "record_axiom_decision"
```

**Step 2: Run tests to verify they fail**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_axiom_tools.py::test_check_axiom_compliance_logs_usage tests/test_axiom_tools.py::test_record_axiom_decision_logs_usage -v
```

Expected: FAIL — no USAGE_LOG constant or logging code exists.

**Step 3: Add usage instrumentation to axiom_tools.py**

At the top of `shared/axiom_tools.py`, after the existing imports (around line 7), add:

```python
import time
from pathlib import Path

USAGE_LOG = Path.home() / ".cache" / "axiom-audit" / "tool-usage.jsonl"


def _log_tool_usage(tool_name: str) -> None:
    """Append a usage entry to the axiom tool usage log."""
    try:
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LOG.open("a") as f:
            f.write(json.dumps({"ts": time.time(), "tool": tool_name}) + "\n")
    except OSError:
        pass  # Never fail the tool call over logging
```

Then add `_log_tool_usage("check_axiom_compliance")` as the first line inside `check_axiom_compliance()` (after the docstring), and `_log_tool_usage("record_axiom_decision")` as the first line inside `record_axiom_decision()`.

**Step 4: Run tests to verify they pass**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_axiom_tools.py -v
```

Expected: ALL PASS.

**Step 5: Commit**

```bash
cd ~/projects/ai-agents && git add shared/axiom_tools.py tests/test_axiom_tools.py
git commit -m "feat: add usage telemetry to axiom compliance tools"
```

---

## Task 8: Add Session Accumulator to axiom-audit.sh

Extend the PostToolUse audit hook to track files written in the current session, enabling periodic cross-file awareness. Every 10th write, run a local LLM check across session files.

**Files:**
- Modify: `~/projects/hapax-system/hooks/scripts/axiom-audit.sh`

**Step 1: Read current axiom-audit.sh**

Confirm it currently just logs to JSONL and exits. The session_id field is already extracted (line 16).

**Step 2: Add session accumulator**

Replace the entire `axiom-audit.sh` with:

```bash
#!/usr/bin/env bash
# axiom-audit.sh — PostToolUse hook for axiom audit trail
# Logs every Edit/Write/MultiEdit to ~/.cache/axiom-audit/YYYY-MM-DD.jsonl
# Tracks session file writes and runs periodic cross-file axiom check.

INPUT="$(cat)"

AUDIT_DIR="$HOME/.cache/axiom-audit"
mkdir -p "$AUDIT_DIR"

AUDIT_FILE="$AUDIT_DIR/$(date +%Y-%m-%d).jsonl"

TOOL_NAME="$(echo "$INPUT" | jq -r '.tool_name // "unknown"' 2>/dev/null || echo unknown)"
FILE_PATH="$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // "unknown"' 2>/dev/null || echo unknown)"
SESSION_ID="$(echo "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo unknown)"

# Append audit entry
printf '{"timestamp":"%s","tool":"%s","file":"%s","session_id":"%s"}\n' \
  "$(date -Iseconds)" "$TOOL_NAME" "$FILE_PATH" "$SESSION_ID" >> "$AUDIT_FILE"

# Session accumulator — track files written per session
SESSION_FILE="$AUDIT_DIR/.session-${SESSION_ID}"
echo "$FILE_PATH" >> "$SESSION_FILE" 2>/dev/null || true
WRITE_COUNT=$(wc -l < "$SESSION_FILE" 2>/dev/null || echo 0)

# Every 10 writes, run cross-file axiom check via local LLM
if [ "$WRITE_COUNT" -gt 0 ] && [ $((WRITE_COUNT % 10)) -eq 0 ]; then
  # Collect first 30 lines of each unique file written this session
  CONTEXT=""
  SEEN=""
  while IFS= read -r f; do
    # Deduplicate
    case "$SEEN" in *"|$f|"*) continue ;; esac
    SEEN="$SEEN|$f|"
    if [ -f "$f" ]; then
      CONTEXT="${CONTEXT}--- ${f} ---\n$(head -30 "$f" 2>/dev/null || true)\n\n"
    fi
  done < "$SESSION_FILE"

  if [ -n "$CONTEXT" ]; then
    # Advisory check via local model — non-blocking, non-failing
    RESULT="$(printf '%b' "$CONTEXT" | timeout 10 aichat -m local-fast \
      "Do these files, taken together, introduce multi-user scaffolding, authentication, authorization, user management, or collaboration features? Answer only YES or NO with a one-line reason." \
      2>/dev/null || true)"
    if echo "$RESULT" | grep -qi "^YES"; then
      echo "WARNING: Session cross-check detected possible multi-action axiom concern across $WRITE_COUNT file writes." >&2
      echo "Reason: $RESULT" >&2
      echo "Files: $(sort -u "$SESSION_FILE" | tr '\n' ' ')" >&2
    fi
  fi
fi

exit 0
```

Key design decisions:
- Uses `SESSION_ID` from Claude Code hook input (not `$$` PID) for correct session scoping
- `timeout 10` prevents the LLM call from hanging
- Deduplicates files before collecting context
- Advisory only (exit 0 always) — never blocks the agent
- Fails silently if `aichat` or local model is unavailable

**Step 3: Manual smoke test**

```bash
# Simulate 10 PostToolUse calls to trigger the cross-check
for i in $(seq 1 10); do
  echo '{"tool_name":"Write","tool_input":{"file_path":"/tmp/test-audit-'$i'.py"},"session_id":"test-accum"}' | bash ~/projects/hapax-system/hooks/scripts/axiom-audit.sh
done
# Check that session file was created
cat ~/.cache/axiom-audit/.session-test-accum
# Clean up
rm -f ~/.cache/axiom-audit/.session-test-accum /tmp/test-audit-*.py
```

Expected: Session file contains 10 entries. On the 10th call, the cross-check runs (may warn or not depending on file content — the test files don't exist so it'll skip gracefully).

**Step 4: Commit**

```bash
cd ~/projects/hapax-system && git add hooks/scripts/axiom-audit.sh
git commit -m "feat: add session accumulator with periodic cross-file axiom check"
```

---

## Task 9: Add External API Call Advisory to Bash Hook

Add `corporate_boundary` advisory warnings when `curl`/`wget` to non-localhost URLs are detected in the Bash hook. Advisory only (exit 0) — surfaces awareness without blocking.

**Files:**
- Modify: `~/projects/hapax-system/hooks/scripts/axiom-commit-scan.sh` (add new elif branch)
- Test: `~/projects/ai-agents/tests/test_axiom_hooks.py`

**Step 1: Write the failing tests**

Add to `TestAxiomCommitScan`:

```python
def test_curl_localhost_passes(self):
    """curl to localhost should pass without warning."""
    result = _run_hook(AXIOM_COMMIT_SCAN, {
        "command": "curl http://localhost:4000/v1/models",
    }, tool_name="Bash")
    assert result.returncode == 0
    assert b"corporate_boundary" not in result.stderr

def test_curl_external_warns_in_corporate_context(self):
    """curl to external URL with .corporate-boundary marker should produce advisory."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        marker = Path(tmpdir) / ".corporate-boundary"
        marker.touch()
        result = subprocess.run(
            ["bash", str(AXIOM_COMMIT_SCAN)],
            input=json.dumps({
                "tool_name": "Bash",
                "tool_input": {"command": "curl https://api.example.com/data"},
                "session_id": "test",
            }).encode(),
            capture_output=True,
            timeout=10,
            cwd=tmpdir,
        )
    # Advisory only — still exit 0
    assert result.returncode == 0
```

**Step 2: Run tests to verify current behavior**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_axiom_hooks.py::TestAxiomCommitScan::test_curl_localhost_passes -v
```

Expected: The localhost test should already pass (exit 0 for unrecognized commands before Task 4, or exit 0 from the file-write branch not matching after Task 4).

**Step 3: Add curl/wget detection to axiom-commit-scan.sh**

In `axiom-commit-scan.sh`, add a new `elif` branch after the file-write detection branch (from Task 4) and before the final `else` / `exit 0`:

```bash
# Detect curl/wget to non-localhost (corporate_boundary advisory)
elif echo "$COMMAND" | grep -qE '\b(curl|wget)\b'; then
  URL="$(echo "$COMMAND" | grep -oE 'https?://[^[:space:]"'"'"']+' | head -1)"
  if [ -z "$URL" ]; then
    exit 0
  fi
  # Allow localhost/127.0.0.1
  if echo "$URL" | grep -qE '^https?://(localhost|127\.0\.0\.1)'; then
    exit 0
  fi
  # Check if current directory has corporate_boundary marker
  if [ -f ".corporate-boundary" ]; then
    echo "Axiom advisory (T1/corporate_boundary): External API call detected" >&2
    echo "URL: $URL" >&2
    echo "Corporate boundary axiom requires sanctioned providers only (OpenAI, Anthropic)." >&2
    echo "If this is intentional, ensure the endpoint is employer-approved." >&2
  fi
  # Advisory only — never block
  exit 0
```

**Step 4: Run tests to verify they pass**

```bash
cd ~/projects/ai-agents && uv run pytest tests/test_axiom_hooks.py -v
```

Expected: ALL PASS.

**Step 5: Commit**

```bash
cd ~/projects/hapax-system && git add hooks/scripts/axiom-commit-scan.sh
git commit -m "feat: add corporate_boundary advisory for external API calls"

cd ~/projects/ai-agents && git add tests/test_axiom_hooks.py
git commit -m "test: add curl/wget corporate boundary advisory tests"
```

---

## Task 10: End-to-End Validation

Run full test suites across both repos. Manually verify hook behavior in a live Claude Code session.

**Step 1: Run all ai-agents tests**

```bash
cd ~/projects/ai-agents && uv run pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass. Pay special attention to:
- `test_axiom_hooks.py` — all hook tests including new ones
- `test_briefing.py` — new axiom status test
- `test_axiom_tools.py` — new usage instrumentation tests

**Step 2: Run hook scripts directly with edge cases**

```bash
# Test: empty input to axiom-scan
echo '{}' | bash ~/projects/hapax-system/hooks/scripts/axiom-scan.sh
echo "Empty input exit: $?"  # Expected: 0

# Test: axiom-scan on its own source (should be skipped)
printf '{"tool_name":"Write","tool_input":{"file_path":"axiom-scan.sh","content":"class User_Manager:\\n    pass"}}' | bash ~/projects/hapax-system/hooks/scripts/axiom-scan.sh
echo "Self-skip exit: $?"  # Expected: 0

# Test: session-context.sh outputs without error
bash ~/projects/hapax-system/hooks/scripts/session-context.sh
echo "Session context exit: $?"  # Expected: 0

# Test: axiom-audit.sh with valid input
echo '{"tool_name":"Write","tool_input":{"file_path":"/tmp/test.py"},"session_id":"validation"}' | bash ~/projects/hapax-system/hooks/scripts/axiom-audit.sh
echo "Audit exit: $?"  # Expected: 0
```

**Step 3: Clean up test artifacts**

```bash
rm -f ~/.cache/axiom-audit/.session-test-* ~/.cache/axiom-audit/.session-validation
rm -f /tmp/test-axiom*.py /tmp/test-audit-*.py
```

**Step 4: Verify settings.json is correctly configured**

```bash
cat ~/.claude/settings.json | jq '.hooks.PreToolUse[0].matcher'
```

Expected: `"Edit|Write|MultiEdit|mcp__filesystem__write_file|mcp__filesystem__edit_file"`

**Step 5: Commit any final fixes from validation**

If any fixes were needed, commit them. Then verify both repos are clean:

```bash
cd ~/projects/hapax-system && git status
cd ~/projects/ai-agents && git status
```

---

## Summary

| Task | Gap | What it does |
|------|-----|-------------|
| 1 | 4 (Coverage) | MCP filesystem tool coverage via settings.json matcher |
| 2 | 1 (Recovery) | Recovery hints in axiom-scan.sh |
| 3 | 1 (Recovery) | Recovery hints in axiom-commit-scan.sh |
| 4 | 4 (Coverage) | Bash file-write bypass detection |
| 5 | 3 (Push) | SessionStart axiom governance nudge |
| 6 | 3 (Push) | Sufficiency probes in daily briefing |
| 7 | 3 (Push) | Usage instrumentation for Layer 5-7 |
| 8 | 2 (Stateful) | Session accumulator with cross-file LLM check |
| 9 | 4 (Coverage) | Corporate boundary advisory for curl/wget |
| 10 | All | End-to-end validation |

**Deferred (30 days):** Review `~/.cache/axiom-audit/tool-usage.jsonl` to decide if Layers 5-7 should be marked dormant.
