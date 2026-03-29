# Vault-Native Sprint Engine

**Date:** 2026-03-29
**Status:** Design
**Context:** Bayesian Validation R&D Schedule (27 measures, 7 gates, 3 sprints, 21 days)

## Problem

The R&D schedule (`docs/research/bayesian-validation-schedule.md`) is a static markdown file. No automation tracks progress, surfaces the next block, evaluates gates, or updates posteriors. The operator must manually cross-reference the schedule, remember which day/block is current, and update checklists. This is exactly the kind of executive function work the system is designed to eliminate.

## Solution

A vault-native sprint engine that:
1. Stores each measure as a frontmatter-rich `.md` note in the Personal Obsidian vault
2. Uses a Claude Code PostToolUse hook to detect measure completion and update vault notes
3. Runs a council timer agent to compute sprint state, evaluate gates, and generate nudges
4. Renders a live dashboard in Obsidian via the Bases feature (first-party, frontmatter-driven views)

## Architecture

```
Claude Code session
  completes work (commits, writes analysis docs)
    |
    v
PostToolUse hook (sprint-tracker.sh)
  reads tool output, matches to active measure via output file patterns
  writes completion signal to /dev/shm/hapax-sprint/completed.jsonl
    |
    v
Sprint agent (agents/sprint_tracker.py, 5-min timer)
  reads /dev/shm/hapax-sprint/completed.jsonl
  reads vault measure notes (frontmatter state)
  evaluates gates, updates posteriors, computes next block
  writes updated frontmatter to vault notes
  writes sprint summary to vault
  emits nudge to /dev/shm if gate fired or next block due
  sends notification if gate blocks
    |
    v
Obsidian Bases
  renders table/board view from frontmatter (read-only display)
```

## Vault Structure

```
~/Documents/Personal/
  20 Projects/
    hapax-research/
      sprint/
        _dashboard.md          <- Bases view definition (TABLE from "sprint/measures")
        _gates.md              <- Bases view for gates only
        _posterior-tracker.md   <- Running posterior table (auto-updated)
        measures/
          7.1-log-salience-signals.md
          4.1-impingement-contradiction-scan.md
          7.2-claim-5-correlation.md
          ... (27 measure notes)
        gates/
          G1-dmn-hallucination.md
          G2-salience-correlation.md
          ... (7 gate notes)
        sprints/
          sprint-0.md           <- Sprint summary (auto-updated daily)
          sprint-1.md
          sprint-2.md
          sprint-3.md
```

## Frontmatter Schema

### Measure Note

```yaml
---
id: "7.1"
title: "Log missing salience signals"
model: "Salience / Biased Competition"
model_id: 7
sprint: 0
day: 1
block: "0930-1000"
status: pending          # pending | in_progress | completed | blocked | skipped
priority: P0
effort_hours: 0.25
posterior_gain: 0.03
wsjf_score: 2.40
eisenhower: Q1
gate: null               # gate ID if this measure is downstream of a gate
output_files:            # files that indicate completion (glob patterns)
  - "agents/hapax_voice/conversation_pipeline.py"
output_docs:             # research docs this measure produces
  - null
deviation: null          # deviation ID if frozen-path change needed
depends_on: []           # measure IDs that must complete first
blocks: ["7.2", "7.3"]  # measure IDs this unblocks
completed_at: null       # ISO 8601 timestamp
result_summary: null     # one-line result after completion
---

# 7.1 Log Missing Salience Signals

**Model:** Salience / Biased Competition (posterior 0.61)
**Posterior gain:** +0.03 (enables +0.12 via 7.2)
**Effort:** 15 minutes

## What

Add 3 `hapax_score()` calls after line 1161 of `conversation_pipeline.py` to log `novelty`, `concern_overlap`, and `dialog_feature_score` to Langfuse.

## Why

Every Phase A voice session without these signals logged is permanent data loss for Claim 5 correlation analysis. This is a hard prerequisite for measure 7.2.

## Requires

DEVIATION-025 (conversation_pipeline.py is frozen during Phase A).

## Acceptance Criteria

- [ ] DEVIATION-025 filed and committed
- [ ] 3 new hapax_score() calls present after line 1161
- [ ] Existing tests pass (no behavioral change)
- [ ] Next voice session shows novelty/concern_overlap/dialog_feature_score in Langfuse trace

## Result

_(auto-populated on completion)_
```

### Gate Note

```yaml
---
id: G1
title: "DMN hallucination containment"
model: "DMN Continuous Substrate"
model_id: 4
trigger_measure: "4.1"   # measure whose result evaluates this gate
condition: "contradiction_rate < 0.15"
status: pending           # pending | passed | failed | blocked
evaluated_at: null
result_value: null        # actual measured value
downstream_measures:      # measures removed if gate fails
  - "4.2"
  - "4.3"
  - "4.4"
  - "4.5"
nudge_required: true      # block-and-notify on failure
acknowledged: false       # operator must acknowledge before schedule continues
---

# G1: DMN Hallucination Containment

**Condition:** Impingement contradiction rate < 15%
**Evaluates after:** Measure 4.1 (Impingement contradiction scan)

## If PASS
Continue with DMN measures 4.2-4.5.

## If FAIL
Stop DMN investment. Mark measures 4.2-4.5 as `skipped`. Notify operator. Rescope to "fix hallucination containment first" before further DMN investment.

## Result

_(auto-populated on evaluation)_
```

## PostToolUse Hook: sprint-tracker.sh

Fires after every Bash and Write/Edit tool use. Detects measure completion via output file pattern matching.

**Matching strategy:**
1. On `Bash` with `git commit`: extract committed files from tool output, match against measure `output_files` globs
2. On `Write`/`Edit`: match written file path against measure `output_files` globs
3. On `Bash` with output containing research doc paths: match against measure `output_docs`

**Behavior:**
- If a match is found, append a completion signal to `/dev/shm/hapax-sprint/completed.jsonl`:
  ```json
  {"measure_id": "7.1", "timestamp": "2026-03-30T09:45:00Z", "trigger": "git commit", "files": ["conversation_pipeline.py"]}
  ```
- Does NOT update the vault directly (avoids race conditions with Obsidian sync)
- Exit 0 always (PostToolUse, never blocks)

**False positive handling:** The sprint agent validates completions against acceptance criteria before updating status. A file match is a *signal*, not a *confirmation*.

## Sprint Agent: agents/sprint_tracker.py

Timer-driven (5-minute interval). Deterministic (phase 0, no LLM).

### Tick cycle

1. **Read completion signals** from `/dev/shm/hapax-sprint/completed.jsonl`. Consume and truncate.

2. **Read vault measure notes** from `~/Documents/Personal/20 Projects/hapax-research/sprint/measures/`. Parse frontmatter.

3. **Process completions:**
   - For each signal, find matching measure by `id`
   - If measure status is `pending` or `in_progress`: transition to `completed`, set `completed_at`, write result_summary from signal
   - Update vault note frontmatter (atomic write: tmp + rename)
   - Check if completion unblocks downstream measures (update their `status` from `blocked` to `pending`)

4. **Evaluate gates:**
   - For each gate where `trigger_measure` is now `completed`:
   - Read the trigger measure's `result_summary`
   - Evaluate `condition` against result (simple numeric comparison)
   - If PASS: mark gate `passed`, continue
   - If FAIL: mark gate `failed`, set all `downstream_measures` to `skipped`, emit blocking nudge

5. **Compute sprint state:**
   - Count measures by status per sprint
   - Determine current day (from start date 2026-03-30)
   - Identify next scheduled block
   - Compute time budget (completed hours vs. scheduled hours)

6. **Write sprint summary** to vault: `sprints/sprint-N.md` with progress table, completed/remaining measures, posterior updates.

7. **Update posterior tracker:** Read all completed measures, sum `posterior_gain` per model, write updated table to `_posterior-tracker.md`.

8. **Emit nudges:**
   - If a gate failed and `nudge_required`: write blocking nudge to `/dev/shm/hapax-sprint/nudge.json` with `acknowledged: false`. Send notification with priority `high`, tags `["warning"]`.
   - If next block is due within 1 hour: write informational nudge with block details.
   - If a sprint transition is imminent (last measure of sprint completing): write sprint review nudge.

9. **Write sensor state** to `/dev/shm/hapax-sprint/state.json`:
   ```json
   {
     "current_sprint": 0,
     "current_day": 1,
     "measures_completed": 3,
     "measures_total": 27,
     "measures_blocked": 0,
     "measures_skipped": 0,
     "gates_passed": 0,
     "gates_failed": 0,
     "gates_pending": 7,
     "next_block": {"measure": "6.3", "title": "Threshold-cross telemetry", "scheduled": "1400-1600"},
     "blocking_gate": null,
     "timestamp": 1774860000
   }
   ```

### Gate acknowledgment

When a gate fails and `nudge_required` is true:
- The nudge persists in `/dev/shm/hapax-sprint/nudge.json` until acknowledged
- Acknowledgment via hapax-mcp: `nudge_act(source_id="sprint:G1")`
- On acknowledgment: set gate `acknowledged: true`, allow schedule to continue (with skipped measures)
- Until acknowledged: no new measures from that model can transition to `in_progress`

### Notification integration

Uses `shared.notify.send_notification()`:
- Gate failure: `priority="high"`, `tags=["warning"]`, `click_url=obsidian_uri(...)` pointing to gate note
- Next block due: `priority="default"`, `tags=["gear"]`
- Sprint complete: `priority="default"`, `tags=["tada"]`

## Obsidian Bases Dashboard

### _dashboard.md

```markdown
---
bases:
  - name: Sprint Dashboard
    source: measures
    filter:
      - property: status
        operator: is not
        value: skipped
    sort:
      - property: day
        direction: asc
      - property: block
        direction: asc
    columns:
      - property: id
        width: 60
      - property: title
        width: 250
      - property: model
        width: 200
      - property: sprint
        width: 60
      - property: status
        width: 100
      - property: priority
        width: 60
      - property: effort_hours
        width: 80
      - property: posterior_gain
        width: 100
      - property: completed_at
        width: 140
---
```

### _gates.md

```markdown
---
bases:
  - name: Decision Gates
    source: gates
    sort:
      - property: id
        direction: asc
    columns:
      - property: id
        width: 60
      - property: title
        width: 300
      - property: status
        width: 100
      - property: condition
        width: 200
      - property: result_value
        width: 100
      - property: evaluated_at
        width: 140
---
```

## Measure-to-File Mapping

The hook matches committed/written files to measures. Complete mapping:

| Measure | Output Files (globs) | Output Docs |
|---------|---------------------|-------------|
| 7.1 | `agents/hapax_voice/conversation_pipeline.py` | -- |
| 4.1 | -- | `docs/research/dmn-impingement-analysis.md` |
| 7.2 | -- | (Langfuse query -- detected via experiment_runner output) |
| 4.5 | -- | (embedded in dmn-impingement-analysis.md) |
| 6.3 | `shared/stimmung.py` | -- |
| 6.2 | `agents/hapax_voice/conversation_pipeline.py`, `shared/stimmung.py` | -- |
| 6.5 | `agents/visual_layer_aggregator.py` | -- |
| 4.2 | -- | `docs/research/dmn-crisis-benchmark.md` |
| 3.1 | `tests/research/test_temporal_contrast.py` | -- |
| 6.1 | -- | `docs/research/stimmung-perturbation-results.md` |
| 4.3 | `agents/hapax_voice/*.py` (voice daemon DMN integration) | -- |
| 7.3 | -- | (Langfuse query result) |
| 6.4 | `agents/hapax_voice/*.py` (perception ground truth) | -- |
| 10.1 | `hapax-logos/crates/hapax-visual/**/*.wgsl` | -- |
| 10.2 | `hapax-logos/crates/hapax-visual/**/*.wgsl` | -- |
| 10.3 | -- | `docs/research/reverie-amendment-comparison.md` |
| 10.4 | `agents/hapax_voice/*.py` (soft escalation) | -- |
| 10.5 | -- | `docs/research/reverie-amendment-comparison.md` |
| 8.1 | -- | `docs/research/bayesian-tools-signal-audit.md` |
| 8.2 | `agents/hapax_voice/mode_selector.py` | -- |
| 8.3 | -- | (Langfuse query result) |
| 3.2 | `tests/test_protention_validation.py` | -- |
| 3.3 | `tests/research/*surprise*` | -- |
| 3.4 | -- | (embedded in bayesian-validation-results.md) |
| 7.4 | -- | (Langfuse query result) |
| 4.4 | -- | (embedded in dmn analysis) |
| 8.4 | -- | (embedded in bayesian-tools-signal-audit.md) |

**Ambiguity resolution:** When a file matches multiple measures, the sprint agent uses dependency ordering -- the earliest uncompleted measure in the dependency chain gets credit. Operator can override via manual frontmatter edit in Obsidian.

## Claude Code Integration

### Hook registration

Add to project `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash|Write|Edit",
        "script": "hooks/scripts/sprint-tracker.sh"
      }
    ]
  }
}
```

### Session start context

The sprint agent writes `/dev/shm/hapax-sprint/state.json` every 5 minutes. The existing session-context hook (`session-context.sh`) should read this and include sprint state in the session startup message:

```
Sprint: 0 (Day 1) | Completed: 3/27 | Next: 6.3 Threshold-cross telemetry (1400-1600)
Gates: 0 passed, 0 failed, 7 pending | Blocking: none
```

This gives Claude Code immediate awareness of where we are in the schedule without reading the full document.

### Measure transition to in_progress

When Claude Code begins work on a measure, the hook detects the first file read/edit matching a pending measure's output_files and transitions it to `in_progress`. This provides real-time status without Claude Code needing to explicitly signal "I'm starting measure X."

## Systemd Integration

```ini
# systemd/hapax-sprint-tracker.service
[Unit]
Description=Hapax Sprint Tracker
After=hapax-secrets.service

[Service]
Type=oneshot
ExecStart=%h/projects/hapax-council/.venv/bin/python -m agents.sprint_tracker
Environment=HOME=%h
WorkingDirectory=%h/projects/hapax-council

[Install]
WantedBy=default.target
```

```ini
# systemd/hapax-sprint-tracker.timer
[Unit]
Description=Sprint Tracker Timer

[Timer]
OnBootSec=60s
OnUnitActiveSec=5min
AccuracySec=1s

[Install]
WantedBy=timers.target
```

## Scope Boundaries

**In scope:**
- Measure note CRUD in vault
- PostToolUse hook for completion detection
- Sprint agent for state computation + gate evaluation + nudge emission
- Obsidian Bases dashboard definition files
- Session-context integration for sprint awareness
- Notification on gate failure

**Out of scope:**
- Obsidian plugin development (Bases is first-party, no plugin needed)
- MCP tool additions (vault is filesystem, no structured API needed)
- Reactive engine rule (sprint agent is timer-driven, not event-driven -- simpler, avoids coupling to engine)
- LLM calls (entirely deterministic)
- Briefing agent integration (can be added later; sprint state is in /dev/shm for any consumer)

## Bootstrap

On first run, the sprint agent:
1. Creates vault directory structure if missing
2. Generates 27 measure notes + 7 gate notes from the schedule data (hardcoded in `agents/sprint_tracker.py` as a data structure, not parsed from the schedule markdown)
3. Creates Bases dashboard definition files
4. Writes initial sprint summary
5. Writes initial sensor state to /dev/shm

Subsequent runs are incremental (read signals, update state, write changes).
