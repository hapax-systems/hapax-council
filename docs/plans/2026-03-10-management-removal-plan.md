# Management (People-Data) Removal — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all people-data paths from ai-agents — management agents, cockpit people-data collectors, vault writer people functions, and associated tests/timers.

**Architecture:** Cut along the people-data boundary. Everything reading from `10-work/people/` or modeling team member state is removed. Knowledge flow agents (briefing, digest, profiler, scout, sync) stay untouched. hapax-mgmt already has its own copies of all removed code.

**Tech Stack:** Python, pytest, systemd

---

## Chunk 1: Delete Management Agents and Shared Modules

### Task 1: Delete management agents

**Files:**
- Delete: `agents/management_prep.py`
- Delete: `agents/meeting_lifecycle.py`

- [ ] **Step 1: Delete management_prep.py**

```bash
rm agents/management_prep.py
```

- [ ] **Step 2: Delete meeting_lifecycle.py**

```bash
rm agents/meeting_lifecycle.py
```

- [ ] **Step 3: Delete associated tests**

```bash
rm tests/test_management_prep.py
rm tests/test_meeting_lifecycle.py
```

- [ ] **Step 4: Run tests to verify no breakage**

Run: `uv run pytest tests/ -q --tb=short 2>&1 | tail -20`
Expected: All remaining tests pass (some import errors may surface — those are handled in later tasks)

- [ ] **Step 5: Commit**

```bash
git add -u
git commit -m "refactor: remove management_prep and meeting_lifecycle agents

People-data agents now live in hapax-mgmt. Removes agents and their tests."
```

### Task 2: Delete management_bridge and its test

**Files:**
- Delete: `shared/management_bridge.py`
- Delete: `tests/test_management_bridge.py`

- [ ] **Step 1: Delete files**

```bash
rm shared/management_bridge.py
rm tests/test_management_bridge.py
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/ -q --tb=short 2>&1 | tail -20`
Expected: PASS (nothing else imports management_bridge)

- [ ] **Step 3: Commit**

```bash
git add -u
git commit -m "refactor: remove shared/management_bridge.py

Only imported by its own test. People-data bridge now in hapax-mgmt."
```

### Task 3: Remove people-specific functions from vault_writer.py

**Files:**
- Modify: `shared/vault_writer.py` — remove lines 210-323 (write_1on1_prep_to_vault, write_team_snapshot_to_vault, write_management_overview_to_vault, create_coaching_starter, create_fb_record_starter)
- Modify: `tests/test_vault_writer.py` — remove TestWrite1on1PrepToVault, TestWriteTeamSnapshotToVault, TestWriteManagementOverviewToVault, TestCoachingStarter, TestFbRecordStarter classes

Keep these functions (used by briefing/digest):
- `write_to_vault`
- `write_briefing_to_vault`
- `write_digest_to_vault`
- `write_nudges_to_vault`
- `write_goals_to_vault`
- `write_bridge_prompt_to_vault`
- `create_decision_starter` (not people-specific — records decisions from meetings)

- [ ] **Step 1: Remove people-specific functions from vault_writer.py**

Remove these functions:
- `write_1on1_prep_to_vault` (lines 210-233)
- `write_team_snapshot_to_vault` (lines 236-256)
- `write_management_overview_to_vault` (lines 259-281)
- `create_coaching_starter` (lines 284-323)
- `create_fb_record_starter` (lines 326-366)

- [ ] **Step 2: Remove corresponding test classes from test_vault_writer.py**

Remove these classes:
- `TestWrite1on1PrepToVault` (lines 162-177)
- `TestWriteTeamSnapshotToVault` (lines 181-189)
- `TestWriteManagementOverviewToVault` (lines 193-208)
- `TestCoachingStarter` (lines 229-244)
- `TestFbRecordStarter` (lines 247-262)

Also remove their imports from the import block (line 18-19, 22-23):
- `write_1on1_prep_to_vault`
- `write_team_snapshot_to_vault`
- `write_management_overview_to_vault`
- `create_coaching_starter`
- `create_fb_record_starter`

- [ ] **Step 3: Run vault_writer tests**

Run: `uv run pytest tests/test_vault_writer.py -v`
Expected: Remaining tests pass (write_to_vault, briefing, digest, nudges, goals, bridge_prompt, decision_starter, atomic_write)

- [ ] **Step 4: Commit**

```bash
git add shared/vault_writer.py tests/test_vault_writer.py
git commit -m "refactor: remove people-specific vault writer functions

Removes write_1on1_prep, write_team_snapshot, write_management_overview,
create_coaching_starter, create_fb_record_starter. These live in hapax-mgmt.
Keeps briefing, digest, nudges, goals, and decision vault writers."
```

## Chunk 2: Remove Cockpit People-Data Path

### Task 4: Delete cockpit/data/management.py and cockpit/data/team_health.py

**Files:**
- Delete: `cockpit/data/management.py`
- Delete: `cockpit/data/team_health.py`
- Delete: `tests/test_management.py`
- Delete: `tests/test_team_health.py`

- [ ] **Step 1: Delete files**

```bash
rm cockpit/data/management.py
rm cockpit/data/team_health.py
rm tests/test_management.py
rm tests/test_team_health.py
```

- [ ] **Step 2: Run tests (expect some failures from dependents)**

Run: `uv run pytest tests/ -q --tb=line 2>&1 | tail -30`
Expected: Failures in test_nudges.py, test_transcript_parser.py, and possibly cockpit API tests. These are fixed in Tasks 5-7.

- [ ] **Step 3: Commit (with known breakage — fixed in next tasks)**

```bash
git add -u
git commit -m "refactor: remove cockpit people-data collectors

Removes cockpit/data/management.py (PersonState, ManagementSnapshot) and
cockpit/data/team_health.py. Dependents fixed in following commits."
```

### Task 5: Remove management nudge rules from nudges.py

**Files:**
- Modify: `cockpit/data/nudges.py` — remove `_collect_management_nudges`, `_collect_team_health_nudges`, `_collect_career_staleness_nudges` functions and their calls in `collect_nudges`
- Modify: `tests/test_nudges.py` — remove tests for management nudge rules

- [ ] **Step 1: Remove management nudge functions from nudges.py**

Remove these functions:
- `_collect_management_nudges` (lines 376-436)
- `_collect_team_health_nudges` (lines 439-467)
- `_collect_career_staleness_nudges` (lines 470-509)

- [ ] **Step 2: Remove calls in collect_nudges()**

In `collect_nudges()` (around lines 646-648), remove:
```python
    _collect_management_nudges(nudges)
    _collect_team_health_nudges(nudges)
    _collect_career_staleness_nudges(nudges)
```

- [ ] **Step 3: Remove management nudge tests from test_nudges.py**

Remove all tests that import `ManagementSnapshot`, `PersonState`, `CoachingState`, `FeedbackState` from `cockpit.data.management`. These are the test functions/classes that reference management nudge rules.

- [ ] **Step 4: Run nudge tests**

Run: `uv run pytest tests/test_nudges.py -v`
Expected: All remaining nudge tests pass

- [ ] **Step 5: Commit**

```bash
git add cockpit/data/nudges.py tests/test_nudges.py
git commit -m "refactor: remove management nudge rules

Removes _collect_management_nudges, _collect_team_health_nudges,
_collect_career_staleness_nudges and their tests. System/knowledge nudges intact."
```

### Task 6: Remove management from cockpit API cache and routes

**Files:**
- Modify: `cockpit/api/cache.py` — remove management field and collector call
- Modify: `cockpit/api/routes/data.py` — remove `/management` endpoint

- [ ] **Step 1: Edit cache.py**

In `DataCache` class, remove:
```python
    management: Any = None
```

In `_refresh_slow_sync`, remove the import:
```python
        from cockpit.data.management import collect_management_state
```

And remove from the collector list:
```python
            ("management", collect_management_state),
```

- [ ] **Step 2: Edit routes/data.py**

Remove the `/management` endpoint:
```python
@router.get("/management")
async def get_management():
    return _slow_response(_to_dict(cache.management))
```

- [ ] **Step 3: Run cockpit API tests**

Run: `uv run pytest tests/ -k "cockpit or cache or route" -v 2>&1 | tail -30`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add cockpit/api/cache.py cockpit/api/routes/data.py
git commit -m "refactor: remove management from cockpit API cache and routes

Removes /management endpoint and collect_management_state from refresh loop."
```

### Task 7: Fix transcript_parser tests

**Files:**
- Modify: `tests/test_transcript_parser.py` — replace PersonState imports with simple mock

- [ ] **Step 1: Replace PersonState with a simple dataclass in tests**

In `tests/test_transcript_parser.py`, the `TestMapSpeakers` class imports `PersonState` from the now-deleted `cockpit.data.management`. Replace with a simple mock:

Change the three test methods to use:
```python
from types import SimpleNamespace
# Replace PersonState(...) with SimpleNamespace(name=...)
```

For example, change:
```python
from cockpit.data.management import PersonState
segments = [TranscriptSegment(speaker="Alice Smith", text="hi")]
people = [PersonState(name="Alice Smith")]
```
to:
```python
from types import SimpleNamespace
segments = [TranscriptSegment(speaker="Alice Smith", text="hi")]
people = [SimpleNamespace(name="Alice Smith")]
```

- [ ] **Step 2: Run transcript parser tests**

Run: `uv run pytest tests/test_transcript_parser.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_transcript_parser.py
git commit -m "fix: replace PersonState with SimpleNamespace in transcript parser tests

PersonState was removed with cockpit/data/management.py. map_speakers_to_people
only uses .name attribute, so SimpleNamespace works identically."
```

## Chunk 3: Remove Systemd Timer and Final Verification

### Task 8: Delete meeting-prep systemd units

**Files:**
- Delete: `systemd/units/meeting-prep.timer`
- Delete: `systemd/units/meeting-prep.service`

- [ ] **Step 1: Delete timer and service files**

```bash
rm systemd/units/meeting-prep.timer
rm systemd/units/meeting-prep.service
```

- [ ] **Step 2: Commit**

```bash
git add -u
git commit -m "refactor: remove meeting-prep systemd timer

Timer moved to hapax-mgmt with the management agents."
```

### Task 9: Full test suite verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass. No imports from deleted modules remain.

- [ ] **Step 2: Grep for stale references**

```bash
rg "management_prep|meeting_lifecycle|management_bridge|cockpit\.data\.management|cockpit\.data\.team_health" --type py -l
```

Expected: No matches in source files (docs/plans references are fine).

- [ ] **Step 3: Verify no broken imports**

```bash
uv run python -c "from cockpit.api.cache import DataCache; print('cache OK')"
uv run python -c "from cockpit.data.nudges import collect_nudges; print('nudges OK')"
uv run python -c "from shared.vault_writer import write_briefing_to_vault; print('vault OK')"
```

Expected: All print "OK"

- [ ] **Step 4: Update CLAUDE.md agent count and layout**

In `CLAUDE.md`, update the agent count and remove management agents from the layout section. The project layout lists "28 agents (12 LLM-driven + 11 deterministic + voice daemon + demo pipeline)" — adjust to reflect removal of management_prep and meeting_lifecycle.

- [ ] **Step 5: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md after management removal

Removes management_prep and meeting_lifecycle from agent roster."
```

### Task 10: Re-evaluate axiom patterns

After all management code is removed, review the uncommitted changes in `shared/axiom_patterns.txt` (commit 67bde25). The management safety patterns (mg-boundary-001, mg-boundary-002) may no longer be needed in ai-agents if there's no management code left to scan. Evaluate whether to:
- Keep them as guardrails preventing future re-introduction
- Remove them since the code they protect against is gone
- Move them to hapax-mgmt where the management code lives

- [ ] **Step 1: Check current axiom_patterns.txt status**

```bash
git diff HEAD shared/axiom_patterns.txt
git log --oneline -5 -- shared/axiom_patterns.txt
```

- [ ] **Step 2: Decide and act based on findings**

If patterns are committed (67bde25), evaluate keeping vs removing.
If uncommitted, evaluate committing vs discarding.

- [ ] **Step 3: Commit decision**

Commit with rationale in message.
