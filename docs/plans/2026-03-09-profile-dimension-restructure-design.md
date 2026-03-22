# Profile Dimension Restructure & Interview System Overhaul

**Date**: 2026-03-09
**Status**: Approved
**Scope**: Full design — dimension taxonomy, interview system, sync agent migration, context tools. Implement in phases.

## Problem Statement

The profile dimension taxonomy (14 flat string dimensions in `PROFILE_DIMENSIONS`) was designed when the profiler extracted facts from config files and Claude Code transcripts. The system now has 10 continuous sync agents, always-on audio, workspace vision with face detection and activity classification, and derivative signal collectors — producing rich behavioral data that the original taxonomy cannot represent.

### Observed Drift

Sync agents have already invented their own dimensions because the canonical 14 don't fit:

| Sync Agent | Writes to | Canonical? |
|---|---|---|
| gmail_sync | `communication` | No — should be `communication_style` |
| chrome_sync | `interests` | No — not in the 14 |
| youtube_sync | `interests` | No — not in the 14 |
| obsidian_sync | `knowledge` | No — should be `knowledge_domains` |

Micro-probes use 4 nonexistent dimensions: `work_patterns`, `tool_preferences`, `creative_preferences`, `decision_style`.

### Root Cause

The dimensions conflate **who the operator is** (stable traits, interview-sourced) with **how the operator behaves** (observable patterns, sync-agent-sourced). When the only data source was "the operator told us," that conflation was fine. Now the system observes behavior directly, and the taxonomy can't represent what it sees.

## Design Decisions

1. **Two-tier taxonomy**: Dimensions are explicitly categorized as `trait` or `behavioral`. The profiler, interview system, and context tools are structurally aware of the distinction.
2. **Consumer-oriented**: Each dimension must justify its existence by naming which agents/systems change behavior based on its data. No dimension exists purely as a filing cabinet.
3. **Design everything, implement in phases**: Complete design covering dimensions, interview overhaul, sync migration, and context tools. Implementation in 6 independent phases.

## New Dimension Taxonomy (12 dimensions)

### Trait Dimensions (6) — stable, interview-sourced, change slowly

#### `identity`
- **Description**: Who the operator is — roles, background, stated skills, affiliations
- **Consumers**: System prompt fragment (all agents), profiler digest
- **Producers**: Interview, config files, profiler extraction

#### `neurocognitive`
- **Description**: Stable cognitive traits — demand sensitivity, sensory preferences, cognitive style, accommodation needs
- **Consumers**: System prompt fragment (all agents), nudge framing, notification priority/timing
- **Producers**: Interview, micro-probes

#### `values`
- **Description**: Principles, aesthetic sensibility, decision heuristics, philosophy
- **Consumers**: Demo content generation, scout report framing, management_prep tone
- **Producers**: Interview, profiler extraction

#### `communication_style`
- **Description**: How the operator prefers to receive/give information, tone calibration
- **Consumers**: All agent output formatting, briefing structure, notification verbosity
- **Producers**: Interview, profiler extraction

#### `management`
- **Description**: Management approach, team philosophy, coaching style. Axiom-constrained: never generates feedback language.
- **Consumers**: management_prep, meeting_lifecycle, cockpit management collector
- **Producers**: Interview, management vault notes

#### `relationships`
- **Description**: People context, relational history, meeting cadence expectations
- **Consumers**: management_prep (1:1 context), meeting_lifecycle, calendar context
- **Producers**: Interview, vault contact notes, calendar sync

### Behavioral Dimensions (6) — dynamic, observation-sourced, update continuously

#### `work_patterns`
- **Description**: Time allocation, task switching, project engagement, focus sessions, daily/weekly rhythms
- **Consumers**: Briefing (what to surface when), nudges (timing), workspace vision (activity mode baseline)
- **Producers**: Calendar sync, screen context, Claude Code sync, git history

#### `energy_and_attention`
- **Description**: Focus duration, presence patterns, circadian rhythm, fatigue signals, productive windows
- **Consumers**: Nudge timing, interview/probe gating, notification priority, briefing delivery time
- **Producers**: Workspace vision (face detection, activity mode), audio processor (activity patterns), calendar sync (meeting density)

#### `information_seeking`
- **Description**: Research patterns, content consumption, learning interests, browsing depth
- **Consumers**: Scout report topics, digest content selection, profiler source discovery
- **Producers**: Chrome sync, YouTube sync, Obsidian sync, Drive sync

#### `creative_process`
- **Description**: Production sessions, creative flow triggers, aesthetic development, sampling habits
- **Consumers**: Demo content, music-related context in briefing, studio skill
- **Producers**: Audio processor (music classification), screen context, interview

#### `tool_usage`
- **Description**: Tool preferences, adoption patterns, workflow toolchain, development environment
- **Consumers**: Context tools (constraint lookup), profiler extraction targeting
- **Producers**: Chrome sync, Claude Code sync, shell history, git repos

#### `communication_patterns`
- **Description**: Response cadence, meeting density, collaboration frequency, async vs sync preference
- **Consumers**: management_prep (meeting prep timing), nudges (communication staleness), briefing
- **Producers**: Gmail sync, calendar sync, audio processor (speaker count)

### Dropped Dimensions (migration paths)

| Old Dimension | Migration Target |
|---|---|
| `hardware` | Drop — infrastructure state lives in component-registry.yaml |
| `knowledge_domains` | `identity` (stated expertise) + `information_seeking` (observed interests) |
| `software_preferences` | `tool_usage` (observed) + `values` (stated preferences) |
| `technical_skills` | `identity` (stated) + `tool_usage` (observed) |
| `music_production` | `creative_process` (behavioral) + `identity` (gear/background) + `values` (aesthetic) |
| `workflow` | `work_patterns` (behavioral) + `tool_usage` (toolchain) |
| `decision_patterns` | `values` (heuristics) + `work_patterns` (observed decision timing) |
| `philosophy` | `values` |
| `team_leadership` | `management` (merged) |
| `neurocognitive_profile` | `neurocognitive` (renamed) |

## Dimension Definition Structure

`PROFILE_DIMENSIONS` becomes a registry of typed definitions in `shared/dimensions.py`:

```python
@dataclass(frozen=True)
class DimensionDef:
    name: str                           # snake_case identifier
    kind: Literal["trait", "behavioral"]
    description: str                    # one-line purpose
    consumers: tuple[str, ...]          # agent/system names that act on this
    primary_sources: tuple[str, ...]    # what writes facts into this
    interview_eligible: bool = True     # can the interview system target this?
```

Key behaviors:
- Interview planner queries `kind == "trait"` dimensions plus sparse behavioral ones
- Sync agents validate writes against `kind == "behavioral"` — writing to a trait dimension is a bug
- Profile gap analysis uses the registry to compute coverage per-kind
- Context tools present trait vs behavioral data differently
- `interview_eligible` defaults True; set False for purely observational dimensions (e.g., `communication_patterns`)

Helper functions:
- `get_dimension_names() -> list[str]` — backward-compatible name list
- `get_dimension(name) -> DimensionDef | None` — lookup by name
- `get_dimensions_by_kind(kind) -> list[DimensionDef]` — filter by trait/behavioral
- `validate_behavioral_write(dimension, source)` — assertion for sync agents

## Interview System Overhaul

### Trigger Modes

The interview system shifts from bootstrap-only to three invocation modes:

#### 1. System-initiated: calibration
Triggered when the system detects a reason to verify observed data:
- Behavioral dimension shows significant pattern shift
- Observed patterns contradict trait facts
- Workspace vision detects sustained activity pattern change

Short interviews (2-5 questions). Can be delivered as enhanced micro-probes rather than full sessions. The planner receives specific observations and generates verification questions.

#### 2. System-initiated: gap-driven
Triggered when trait dimensions have insufficient coverage or behavioral dimensions lack interview-eligible context:
- Profile staleness (no interview in N days + trait dimensions below threshold)
- New dimension added with zero facts
- Nudge system surfaces as action item

Closest to current bootstrap mode but scoped to specific gaps, not full survey.

#### 3. Operator-initiated: on-demand
Operator starts via logos UI or voice. Planner asks what they want to discuss or operator states intent. No gap analysis required — operator intent drives topic selection.

### Interview Trigger Model

```python
class InterviewTrigger(BaseModel):
    mode: Literal["calibration", "gap", "on_demand"]
    reason: str = ""                          # why the system is asking
    observations: list[str] = []              # observed data to calibrate against
    target_dimensions: list[str] = []         # specific dimensions to focus on
    operator_intent: str = ""                 # what the operator wants (on_demand)
```

Planner prompt varies by mode:
- **Calibration**: "Here are recent observations. Generate questions that verify, refine, or challenge these observations with the operator."
- **Gap**: Current behavior, scoped to `target_dimensions`.
- **On-demand**: "The operator wants to discuss: {intent}. Generate questions that explore this topic and capture relevant facts."

### Interview History

New persistent state: `profiles/interview-history.jsonl`. Each completed interview appends:

```python
class InterviewRecord(BaseModel):
    timestamp: str
    mode: Literal["calibration", "gap", "on_demand"]
    reason: str
    dimensions_covered: list[str]
    facts_recorded: int
    insights_recorded: int
    duration_seconds: int
    topics_explored: int
    topics_total: int
```

Enables: staleness detection, back-off logic, history available to planner.

### Incremental Fact Persistence

Facts persist to `{COCKPIT_STATE_DIR}/interview-pending.jsonl` on each `record_fact` tool call. `end_interview()` merges into profile and clears pending file. Session crashes no longer lose facts.

### Micro-Probes Evolution

- **Hardcoded probes** remain for neurocognitive trait discovery
- **Calibration probes** generated by sync agents via `{COCKPIT_STATE_DIR}/calibration-probes.jsonl`
- **Pool reset**: probes for still-sparse dimensions re-queue with different wording
- **Dimension names** fixed to new taxonomy

### Gating

Interviews and micro-probes respect:
- **Workspace presence**: face detection confirms operator is present
- **Activity mode**: no probes during meetings or production sessions
- **Calendar awareness**: no interview starts within 15 minutes of a scheduled meeting

## Sync Agent Migration

### Dimension Validation

Sync agents' `_generate_profile_facts()` gets validated — facts must target `kind == "behavioral"` dimensions in the registry. Enforced in test suites.

### Per-Agent Migration

| Agent | Current | New |
|---|---|---|
| `gcalendar_sync` | `workflow` ×4 | `work_patterns` (cadence, busy days) + `communication_patterns` (attendees, recurring) |
| `gmail_sync` | `communication` ×4 | `communication_patterns` (volume, senders, threads, response style) |
| `chrome_sync` | `interests` ×1 | `information_seeking` (top domains, patterns) |
| `youtube_sync` | `interests` ×3 | `information_seeking` (tags, subscriptions, categories) |
| `obsidian_sync` | `knowledge` ×3 | `information_seeking` (areas, tags, volume) |
| `claude_code_sync` | `workflow` ×2 | `tool_usage` (projects, session patterns) |
| `audio_processor` | (TBD) | `energy_and_attention` (activity) + `creative_process` (music) |

### Fact Migration

One-time migration script for `profiles/operator-profile.json`:
- Remap dimension names per table above
- Split facts using key heuristics for dimensions that fan out (e.g., `workflow` → `work_patterns` + `tool_usage`)
- Ambiguous keys default to the broader bucket
- Unmappable facts flagged in `profiles/migration-review.jsonl`

Key heuristic rules for `workflow` split:
- Keys containing `tool`, `prefer`, `editor`, `ide`, `cli` → `tool_usage`
- Keys containing `schedule`, `cadence`, `meeting`, `time`, `focus` → `work_patterns`
- Ambiguous → `work_patterns`

## Profiler & Context Tools Updates

### Profiler (`agents/profiler.py`)
- Import dimensions from `shared/dimensions.py` instead of hardcoded list
- Extraction prompt updated with 12 dimensions + descriptions + kind
- Synthesis narrative distinguishes trait ("the operator states...") from behavioral ("Observed pattern:...")
- `flush_interview_facts()` insight-to-dimension mapping updated:
  - `workflow_gap` → `work_patterns`
  - `goal_refinement` → `values`
  - `practice_critique` → `work_patterns`
  - `aspiration` → `values`
  - `contradiction` → dynamic (dimension of the contradicted fact)
  - `neurocognitive_pattern` → `neurocognitive`

### Profile Store (`shared/profile_store.py`)
- `search()` gains optional `kind` filter parameter
- Digest tagged with `kind` per dimension

### Context Tools (`shared/context_tools.py`)
- `get_profile_summary` presents trait/behavioral sections separately
- `search_profile` gains optional `kind` filter
- New tool: `get_dimension_coverage` — per-dimension fact count and confidence, grouped by kind

### Operator Module (`shared/operator.py`)
- No changes. `operator.json` (declared configuration) remains separate from profile dimensions (discovered knowledge).

## Implementation Phases

### Phase 1: Foundation (no behavioral changes)
- Create `shared/dimensions.py` with `DimensionDef` registry
- Add helper functions: `get_dimension_names()`, `get_dimension()`, `get_dimensions_by_kind()`, `validate_behavioral_write()`
- Update `agents/profiler.py` to import from registry
- Write migration script for `profiles/operator-profile.json`
- Update tests
- **Ship criterion**: all existing tests pass, profile loads correctly with new dimensions

### Phase 2: Sync agent migration
- Update 7 sync agents' `_generate_profile_facts()` to new dimension names
- Fix micro-probe dimension names
- Add `validate_behavioral_write()` to sync agent test suites
- Run migration script on live profile
- **Ship criterion**: all sync agents write to valid dimensions, no orphan facts

### Phase 3: Interview system overhaul
- Add `InterviewTrigger` model and `trigger` parameter to `generate_interview_plan()`
- Update planner prompts per trigger mode
- Add interview history persistence
- Incremental fact persistence during interviews
- Update `analyze_profile()` to use dimension registry
- **Ship criterion**: interviews can be started in all 3 modes, facts persist incrementally

### Phase 4: Probe & gating evolution
- Fix remaining micro-probe issues
- Add calibration probe JSONL mechanism
- Add probe pool reset logic
- Integrate workspace presence gating
- Integrate calendar awareness
- **Ship criterion**: probes respect presence/activity gates, calibration probes flow from sync agents

### Phase 5: Context tools & consumers
- Update `ProfileStore.search()` with `kind` filter
- Update context tools for trait/behavioral presentation
- Add `get_dimension_coverage` tool
- Update profiler synthesis prompts
- Update interview agent to use `ProfileStore.search()`
- **Ship criterion**: agents see trait/behavioral distinction in context, semantic search used in interviews

### Phase 6: System-initiated triggers
- Calibration probe generation from sync agents (pattern shift detection)
- Gap-driven interview nudges (staleness threshold)
- Integration with nudge system
- Notification on interview completion
- **Ship criterion**: system autonomously suggests interviews when warranted
