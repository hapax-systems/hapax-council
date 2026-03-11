# Scout Feedback Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make scout decision-aware (skip dismissed/deferred components for 90 days) and surface actionable scout recommendations in Claude Code session context.

**Architecture:** Scout agent reads `profiles/scout-decisions.jsonl` at run start, suppresses components with active dismiss/defer cooldowns, and includes a `skipped` list in the report. Session hook reads `profiles/scout-report.json` via jq and emits a one-line summary of actionable items.

**Tech Stack:** Python 3.12, Pydantic, pytest, bash, jq

---

### Task 1: Decision Loading and Cooldown Logic

**Files:**
- Modify: `~/projects/hapax-council/agents/scout.py:48-58` (constants area)
- Modify: `~/projects/hapax-council/agents/scout.py:81-86` (ScoutReport model)
- Modify: `~/projects/hapax-council/agents/scout.py:353-406` (run_scout function)
- Test: `~/projects/hapax-council/tests/test_scout_decision_awareness.py`

**Step 1: Write the failing tests**

Create `~/projects/hapax-council/tests/test_scout_decision_awareness.py`:

```python
"""Tests for scout decision-awareness (cooldown suppression)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.scout import load_decisions, DECISION_COOLDOWN_DAYS


@pytest.fixture
def decisions_file(tmp_path):
    return tmp_path / "scout-decisions.jsonl"


def _write_decision(path: Path, component: str, decision: str, days_ago: int) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    with open(path, "a") as f:
        f.write(json.dumps({
            "component": component,
            "decision": decision,
            "timestamp": ts,
            "notes": "",
        }) + "\n")


def test_dismissed_within_cooldown_skipped(decisions_file):
    _write_decision(decisions_file, "vector-database", "dismissed", days_ago=30)
    decisions = load_decisions(decisions_file)
    assert "vector-database" in decisions
    assert decisions["vector-database"]["decision"] == "dismissed"
    # 30 days < 90 day cooldown → should be active
    ts = datetime.fromisoformat(decisions["vector-database"]["timestamp"])
    age_days = (datetime.now(timezone.utc) - ts).days
    assert age_days < DECISION_COOLDOWN_DAYS


def test_dismissed_past_cooldown_evaluated(decisions_file):
    _write_decision(decisions_file, "vector-database", "dismissed", days_ago=100)
    decisions = load_decisions(decisions_file)
    assert "vector-database" in decisions
    ts = datetime.fromisoformat(decisions["vector-database"]["timestamp"])
    age_days = (datetime.now(timezone.utc) - ts).days
    assert age_days >= DECISION_COOLDOWN_DAYS


def test_deferred_within_cooldown_skipped(decisions_file):
    _write_decision(decisions_file, "embedding-model", "deferred", days_ago=60)
    decisions = load_decisions(decisions_file)
    assert "embedding-model" in decisions
    assert decisions["embedding-model"]["decision"] == "deferred"
    ts = datetime.fromisoformat(decisions["embedding-model"]["timestamp"])
    age_days = (datetime.now(timezone.utc) - ts).days
    assert age_days < DECISION_COOLDOWN_DAYS


def test_adopted_not_skipped(decisions_file):
    _write_decision(decisions_file, "agent-framework", "adopted", days_ago=10)
    decisions = load_decisions(decisions_file)
    assert "agent-framework" in decisions
    assert decisions["agent-framework"]["decision"] == "adopted"
    # Adopted components should never be suppressed — caller checks this


def test_latest_decision_wins(decisions_file):
    _write_decision(decisions_file, "vector-database", "dismissed", days_ago=100)
    _write_decision(decisions_file, "vector-database", "dismissed", days_ago=10)
    decisions = load_decisions(decisions_file)
    # Most recent decision (10 days ago) should win
    ts = datetime.fromisoformat(decisions["vector-database"]["timestamp"])
    age_days = (datetime.now(timezone.utc) - ts).days
    assert age_days < 15


def test_missing_file_returns_empty(tmp_path):
    decisions = load_decisions(tmp_path / "nonexistent.jsonl")
    assert decisions == {}
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_scout_decision_awareness.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_decisions' from 'agents.scout'`

**Step 3: Add constant, load_decisions function, update ScoutReport, and modify run_scout**

In `~/projects/hapax-council/agents/scout.py`, after line 53 (`REPORT_MD = ...`), add:

```python
DECISIONS_FILE = PROFILES_DIR / "scout-decisions.jsonl"
DECISION_COOLDOWN_DAYS = 90
```

After the `ScoutReport` class (line 86), before the Component Registry section comment, add:

```python
def load_decisions(path: Path | None = None) -> dict[str, dict]:
    """Load scout decisions, returning latest decision per component."""
    path = path or DECISIONS_FILE
    if not path.is_file():
        return {}
    decisions: dict[str, dict] = {}
    for line in path.read_text().strip().splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            component = record.get("component", "")
            existing = decisions.get(component)
            if existing is None or record.get("timestamp", "") > existing.get("timestamp", ""):
                decisions[component] = record
        except json.JSONDecodeError:
            continue
    return decisions
```

Update `ScoutReport` to add the `skipped` field — change line 86 from:

```python
    errors: list[str] = Field(default_factory=list, description="Components that failed to scan")
```

to:

```python
    errors: list[str] = Field(default_factory=list, description="Components that failed to scan")
    skipped: list[str] = Field(default_factory=list, description="Components skipped due to active decisions")
```

In `run_scout()`, after `usage_map = _build_usage_map()` (line 377) and before the report construction (line 379), add decision loading:

```python
    # Load operator decisions for cooldown suppression
    decisions = load_decisions()
```

Inside the `for spec in components:` loop (line 383), before the `log.info` call (line 384), add suppression check:

```python
        # Check decision cooldown
        decision = decisions.get(spec.key)
        if decision and decision.get("decision") in ("dismissed", "deferred"):
            try:
                decided_at = datetime.fromisoformat(decision["timestamp"])
                age_days = (datetime.now(timezone.utc) - decided_at).days
                if age_days < DECISION_COOLDOWN_DAYS:
                    report.skipped.append(f"{spec.key} ({decision['decision']} {age_days}d ago)")
                    print(f"Skipping: {spec.key} ({decision['decision']} {age_days}d ago, cooldown active)", file=sys.stderr)
                    continue
            except (ValueError, KeyError):
                pass  # Malformed timestamp — evaluate normally
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_scout_decision_awareness.py -v`
Expected: 6 passed

**Step 5: Update markdown formatter**

In `format_report_md()` (line 411), after the errors section (around line 456), before the final `return`, add:

```python
    if report.skipped:
        lines.append("## Skipped (decision cooldown)")
        for s in report.skipped:
            lines.append(f"- {s}")
        lines.append("")
```

**Step 6: Verify full test suite still passes**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_scout_decisions.py tests/test_scout_decision_awareness.py -v`
Expected: 9 passed (3 existing + 6 new)

**Step 7: Commit**

```bash
cd ~/projects/hapax-council
git add agents/scout.py tests/test_scout_decision_awareness.py
git commit -m "feat: add decision-aware scout runs with 90-day cooldown"
```

---

### Task 2: Session Hook Scout Context

**Files:**
- Modify: `~/projects/hapax-system/hooks/scripts/session-context.sh:107-108` (after axiom sweep block, before auto-memory seed)

**Step 1: Add scout context block**

In `~/projects/hapax-system/hooks/scripts/session-context.sh`, after the axiom sweep block (after line 107, before the `# Seed auto-memory` comment on line 109), add:

```bash
# Scout recommendations (actionable items from latest horizon scan)
SCOUT_REPORT="$HOME/projects/ai-agents/profiles/scout-report.json"
if [ -f "$SCOUT_REPORT" ]; then
  SCOUT_LINE="$(jq -r '
    (.generated_at // "") as $ts |
    [.recommendations[] | select(.tier == "adopt" or .tier == "evaluate")] as $actionable |
    if ($actionable | length) == 0 then empty
    else
      (now - ($ts | sub("Z$"; "+00:00") | fromdate)) / 86400 | floor | tostring as $age |
      if ($age | tonumber) > 8 then empty
      else
        ($actionable | group_by(.tier) | map(
          (.[0].tier) + ": " + (map(.component) | join(", "))
        ) | join(", ")) as $items |
        "Scout: \($actionable | length) actionable (\($items)) | \($age)d ago"
      end
    end
  ' "$SCOUT_REPORT" 2>/dev/null || true)"
  if [ -n "$SCOUT_LINE" ]; then
    echo "$SCOUT_LINE"
  fi
fi
```

**Step 2: Test manually**

Create a test scout report and run the hook:

```bash
# Create test report
cat > /tmp/test-scout-report.json << 'EOF'
{
  "generated_at": "2026-03-07T10:00:00Z",
  "components_scanned": 17,
  "recommendations": [
    {"component": "pydantic-ai", "current": "1.63.0", "tier": "adopt", "summary": "test", "confidence": "high", "migration_effort": "low"},
    {"component": "nomic-embed", "current": "v1.5", "tier": "evaluate", "summary": "test", "confidence": "medium", "migration_effort": "medium"},
    {"component": "qdrant", "current": "1.12", "tier": "current-best", "summary": "test", "confidence": "high", "migration_effort": ""}
  ]
}
EOF

# Test the jq expression directly
SCOUT_REPORT=/tmp/test-scout-report.json
jq -r '
  (.generated_at // "") as $ts |
  [.recommendations[] | select(.tier == "adopt" or .tier == "evaluate")] as $actionable |
  if ($actionable | length) == 0 then empty
  else
    (now - ($ts | sub("Z$"; "+00:00") | fromdate)) / 86400 | floor | tostring as $age |
    if ($age | tonumber) > 8 then empty
    else
      ($actionable | group_by(.tier) | map(
        (.[0].tier) + ": " + (map(.component) | join(", "))
      ) | join(", ")) as $items |
      "Scout: \($actionable | length) actionable (\($items)) | \($age)d ago"
    end
  end
' "$SCOUT_REPORT"
```

Expected output: `Scout: 2 actionable (adopt: pydantic-ai, evaluate: nomic-embed) | 2d ago`

**Step 3: Commit**

```bash
cd ~/projects/hapax-system
git add hooks/scripts/session-context.sh
git commit -m "feat: add scout recommendations to session context hook"
```

---

### Task 3: Validate

**Step 1: Run ai-agents tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_scout_decisions.py tests/test_scout_decision_awareness.py -v`
Expected: 9 passed

**Step 2: Test session hook end-to-end**

Run: `cd ~/projects/hapax-council && bash ~/projects/hapax-system/hooks/scripts/session-context.sh`
Expected: Output includes all existing lines (Axioms, Branch, Health, Docker, GPU, Profile, Cycle) plus Scout line if `profiles/scout-report.json` exists with actionable items less than 8 days old. If no scout report or no actionable items, Scout line is absent.

**Step 3: Verify scout dry-run still works**

Run: `cd ~/projects/hapax-council && uv run python -m agents.scout --dry-run 2>&1 | head -20`
Expected: Lists search queries for all registry components, no errors.
