# Cycle Modes (Dev/Prod) Design

**Date**: 2026-03-09
**Status**: Approved
**Scope**: Two-mode cycle system — timer overrides, agent-internal threshold adjustments, CLI script, logos API.

## Problem Statement

The hapax agent automation and workflow timers were designed for a normal work and development pace. Timer schedules operate on daily/weekly cadence. During heavy development, work moves orders of magnitude faster — code changes every few minutes, new patterns emerge, the profile needs updating, briefings go stale within hours.

The critical context refresh pipeline currently completes end-to-end once per 24 hours:

```
sync agents (collect) → profiler (extract) → digest (synthesize) → briefing (present)
```

During heavy dev, this pipeline should complete in under 1 hour.

### Root Cause

Timer schedules are hardcoded for steady-state operation. There is no mechanism to contract cycles when the operator is in a high-velocity work mode.

## Design Decisions

1. **Two discrete modes**: `dev` and `prod`. No continuous dial — the operator is either heads-down coding or in normal work mode.
2. **Manual switching**: CLI command + logos web toggle. No auto-detection.
3. **Systemd timer overrides**: Uses systemd's native drop-in directory pattern. Base timer files remain unchanged.
4. **Agent-aware**: Agents read the mode file at invocation to adjust internal thresholds (probe cooldowns, cache TTLs).
5. **Single source of truth**: Mode file at `~/.cache/hapax/cycle-mode`. CLI script and logos API both read/write it.

## Mode File

**Path:** `~/.cache/hapax/cycle-mode`

Plain text, contains `dev` or `prod`. Defaults to `prod` when absent or invalid.

**Shared reader:** `shared/cycle_mode.py`

```python
from enum import StrEnum
from pathlib import Path

class CycleMode(StrEnum):
    PROD = "prod"
    DEV = "dev"

MODE_FILE = Path.home() / ".cache" / "hapax" / "cycle-mode"

def get_cycle_mode() -> CycleMode:
    try:
        return CycleMode(MODE_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return CycleMode.PROD
```

## Timer Override Structure

### Directory Layout

```
systemd/
  units/              # existing prod schedules (unchanged)
  overrides/
    dev/              # dev-mode timer overrides
      claude-code-sync.timer
      obsidian-sync.timer
      chrome-sync.timer
      gdrive-sync.timer
      profile-update.timer
      digest.timer
      daily-briefing.timer
      drift-detector.timer
      knowledge-maint.timer
```

Each override file contains only the `[Timer]` section with the dev schedule. The `hapax-mode` script copies each into `~/.config/systemd/user/<timer>.timer.d/override.conf` (systemd's standard drop-in pattern).

### Dev Mode Schedules

| Timer | Prod | Dev | Rationale |
|-------|------|-----|-----------|
| claude-code-sync | 2h | 10min | Primary dev signal source |
| obsidian-sync | 30min | 10min | Notes change during dev |
| chrome-sync | 1h | 20min | Research during dev |
| gdrive-sync | 2h | 1h | Docs change during dev |
| profile-update | 6h | 45min | Must track code churn |
| digest | daily 06:45 | every 2h | Frequent synthesis |
| daily-briefing | daily 07:00 | every 4h | Frequent briefing |
| drift-detector | weekly Sun | daily 03:00 | Architecture changes in dev |
| knowledge-maint | weekly Sun | daily 04:30 | More ingestion = more dedup |

### Unchanged Timers

No override needed: gcalendar-sync, gmail-sync, youtube-sync, audio-processor, health-monitor, meeting-prep, scout, llm-backup, manifest-snapshot.

### Switching to Prod

Removes all `<timer>.timer.d/` drop-in directories, restoring the base timer files.

## Agent-Internal Threshold Adjustments

Agents that have time-based thresholds read `get_cycle_mode()` at invocation. No persistent state — just a function call.

| Agent/Module | Threshold | Prod | Dev | Why |
|---|---|---|---|---|
| `cockpit/micro_probes.py` | PROBE_COOLDOWN | 600s (10min) | 1800s (30min) | Don't interrupt deep work |
| `cockpit/micro_probes.py` | PROBE_IDLE_THRESHOLD | 300s (5min) | 900s (15min) | Longer focus blocks in dev |
| `logos/api/cache.py` | FAST_INTERVAL | 30s | 15s | Cockpit reflects changes faster |
| `logos/api/cache.py` | SLOW_INTERVAL | 300s | 120s | Same |

### Implementation Pattern

Each module replaces its constant with a function:

```python
# Before
PROBE_COOLDOWN = 600

# After
from shared.cycle_mode import get_cycle_mode, CycleMode

def _probe_cooldown() -> int:
    return 1800 if get_cycle_mode() == CycleMode.DEV else 600
```

Only 4 constants change across 2 files. Minimal footprint.

## CLI Script

**Path:** `scripts/hapax-mode` (installable to `~/.local/bin/hapax-mode`)

**Usage:**

```bash
hapax-mode dev       # switch to dev mode
hapax-mode prod      # switch to prod mode
hapax-mode           # print current mode
```

**Switch procedure:**

1. Write `dev` or `prod` to `~/.cache/hapax/cycle-mode`
2. For each timer in the override set:
   - **dev:** Create `~/.config/systemd/user/<timer>.timer.d/` and copy override conf
   - **prod:** Remove all `<timer>.timer.d/` drop-in directories
3. Run `systemctl --user daemon-reload`
4. Restart affected timers so new schedules take effect immediately
5. Send ntfy notification: `"Cycle mode → dev"` or `"Cycle mode → prod"`
6. Print summary of active timer schedules to stdout

**Error handling:** Validates argument is `dev` or `prod`, checks systemd user session available, exits non-zero on failure.

## Logos API

**Endpoints on existing FastAPI server (`logos/api/`):**

```
GET  /api/cycle-mode  → {"mode": "prod", "switched_at": "2026-03-09T14:30:00Z"}
PUT  /api/cycle-mode  → body: {"mode": "dev"} → runs hapax-mode script, returns new state
```

The PUT handler calls `hapax-mode` via subprocess — single source of truth for the switch procedure. `switched_at` is the mtime of the mode file.

**Cockpit-web:** Toggle in the system status area of the dashboard. This is a hapax-logos repo change (React). The design defines the API contract only — frontend implementation follows separately.

## Testing Strategy

### Unit Tests (`tests/test_cycle_mode.py`)

- `get_cycle_mode()` returns `prod` when file missing
- `get_cycle_mode()` returns `prod` when file contains invalid value
- `get_cycle_mode()` returns `dev` when file contains `dev`
- `CycleMode` enum has exactly two members

### Integration Tests (`tests/test_cycle_mode_integration.py`)

- `micro_probes._probe_cooldown()` returns 1800 in dev, 600 in prod (mock mode file)
- `cache.py` intervals adjust correctly per mode
- Logos API `GET /api/cycle-mode` returns current mode
- Logos API `PUT /api/cycle-mode` writes mode file and returns new state

### Timer Override Validation

- Test that all override files in `systemd/overrides/dev/` parse as valid systemd timer syntax (ini parser, `[Timer]` section present)

### CLI Script

Not unit-tested (bash). Validated manually and by the logos API integration test which exercises the same flow.

## Implementation Phases

### Phase 1: Foundation
- Create `shared/cycle_mode.py` with `CycleMode` enum and `get_cycle_mode()`
- Unit tests
- Commit

### Phase 2: Timer overrides
- Create `systemd/overrides/dev/` with 9 timer override files
- Timer syntax validation test
- Commit

### Phase 3: CLI script
- Create `scripts/hapax-mode` bash script
- Manual validation
- Commit

### Phase 4: Agent threshold adjustments
- Update `cockpit/micro_probes.py` (PROBE_COOLDOWN, PROBE_IDLE_THRESHOLD)
- Update `logos/api/cache.py` (FAST_INTERVAL, SLOW_INTERVAL)
- Integration tests
- Commit

### Phase 5: Logos API
- Add GET/PUT `/api/cycle-mode` endpoints
- Integration tests
- Commit
