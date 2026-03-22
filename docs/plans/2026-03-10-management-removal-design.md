# Design: Remove Management (People-Data) from ai-agents

**Date:** 2026-03-10
**Status:** Approved
**Principle:** Cut along the people-data boundary. Everything that reads from `10-work/people/` or models team member state gets removed. Knowledge flow agents stay untouched.

## Deletions

### Agents (2 files)
- `agents/management_prep.py`
- `agents/meeting_lifecycle.py`

### Shared modules (1 file)
- `shared/management_bridge.py`

### Cockpit data collectors (2 files)
- `logos/data/management.py` — PersonState, ManagementSnapshot, collect_management_state
- `logos/data/team_health.py` — depends entirely on management.py

### Tests (5 files)
- `tests/test_management_prep.py`
- `tests/test_meeting_lifecycle.py`
- `tests/test_management_bridge.py`
- `tests/test_management.py`
- `tests/test_team_health.py`

### Systemd (1 timer + service)
- `systemd/units/meeting-prep.timer`
- `systemd/units/meeting-prep.service`

## Surgical Edits

### `shared/vault_writer.py`
Remove people-specific functions:
- `write_1on1_prep_to_vault`
- `write_team_snapshot_to_vault`
- `write_management_overview_to_vault`

Keep: `write_digest_to_vault`, `write_briefing_to_vault`, `write_nudges_to_vault`, `write_to_vault`

### `logos/data/nudges.py`
Remove management-related nudge rules that import from `cockpit.data.management`. Keep system/knowledge nudge rules.

### `logos/api/cache.py`
Remove the `collect_management_state` call and `/management` cache path.

### `tests/test_nudges.py`
Remove tests for management nudge rules.

### `tests/test_vault_writer.py`
Remove tests for deleted vault_writer functions.

### `tests/test_transcript_parser.py`
Remove PersonState imports/references.

## Unchanged (knowledge flow)
- briefing.py, digest.py, profiler.py, scout.py, all *_sync.py agents
- shared/calendar_context.py, shared/vault_writer.py (trimmed)
- logos/data/goals.py, agents.py, emergence.py (non-people collectors)
- All systemd timers except meeting-prep

## Constraints
- Do not remove anything that breaks knowledge flow systems
- All management functionality already lives in hapax-mgmt
- After removal, re-evaluate uncommitted axiom_patterns.txt management safety patterns
