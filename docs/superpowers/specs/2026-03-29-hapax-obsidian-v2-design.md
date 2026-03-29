# Hapax Obsidian Plugin v2 — Context-First System Companion

**Date:** 2026-03-29
**Status:** Design
**Replaces:** obsidian-hapax v1.0.0 (chat sidebar, management-focused, March 5 2026)

## Problem

The v1 plugin is a management chat sidebar built for the Work vault. In 24 days the hapax ecosystem has gained: a vault-native sprint engine (28 measures, 7 gates, posterior tracking), 352 migrated research notes with backlinks, real-time stimmung, DMN continuous cognition, Bayesian validation infrastructure, and a Tauri-native Logos app. The plugin knows about none of this.

Meanwhile the corporate_boundary axiom means work vault features belong in officium, not in a personal plugin. The plugin needs to be reimagined as a **Personal vault companion** that surfaces hapax system state contextually alongside whatever note the operator is viewing.

## Solution

A context-first Obsidian plugin for the Personal vault. No chat. No LLM calls. No direct filesystem reads. The plugin detects the active note type, fetches relevant system state from logos-api (:8051), and renders a contextual sidebar. Lightweight write-back actions (acknowledge gates, transition measures, dismiss nudges) go through logos-api; the sprint tracker agent propagates changes to vault notes on next tick.

## Architecture

```
Active Note
  (frontmatter: id, type, model, tags; path pattern)
    |
    v
ContextResolver
  classifies note → NoteKind enum
  extracts identifiers (measure ID, gate ID, model name, research domain)
    |
    v
LogosClient (single HTTP client, localhost:8051)
  GET endpoints with TTL caching
  POST endpoints for write-back actions
    |
    v
ContextPanel (Obsidian ItemView, right sidebar)
  renders sections based on NoteKind
  action buttons dispatch POSTs
  auto-refreshes on active-leaf-change + interval
```

## Note Classification

The ContextResolver determines note kind from frontmatter properties and vault path. Classification is deterministic with no LLM involvement.

### NoteKind Enum

```typescript
enum NoteKind {
  Measure,        // sprint/measures/*.md — has frontmatter id like "7.1"
  Gate,           // sprint/gates/*.md — has frontmatter id like "G1"
  SprintSummary,  // sprint/sprints/*.md
  PosteriorTracker, // sprint/_posterior-tracker.md
  Research,       // hapax-research/**/*.md with tag hapax/research/*
  Concept,        // 33 Permanent notes/*.md with tag type/concept
  Briefing,       // 30-system/briefings/*.md
  Nudges,         // 30-system/nudges.md
  Unknown,        // anything else
}
```

### Detection Rules (evaluated in order, first match wins)

| Rule | Path Pattern | Frontmatter | NoteKind |
|------|-------------|-------------|----------|
| 1 | `sprint/measures/` | `id` matches `\d+\.\d+` | Measure |
| 2 | `sprint/gates/` | `id` matches `G\d+` | Gate |
| 3 | `sprint/sprints/` | — | SprintSummary |
| 4 | `_posterior-tracker.md` | — | PosteriorTracker |
| 5 | `30-system/briefings/` | — | Briefing |
| 6 | `30-system/nudges.md` | — | Nudges |
| 7 | `hapax-research/` | tag contains `hapax/research` | Research |
| 8 | `33 Permanent notes/` | tag contains `type/concept` | Concept |
| 9 | — | — | Unknown |

Path matching uses vault-relative paths. Frontmatter accessed via Obsidian's `MetadataCache`.

## Context Panel Rendering

Each NoteKind maps to a panel layout. Panels are composed of reusable **sections** — small rendering units that can appear in multiple NoteKind layouts.

### Sections

| Section | Data Source | Content |
|---------|-----------|---------|
| `SprintStatus` | `GET /api/sprint` | One-liner: "Sprint 0 Day 1 — 3/28 completed, 4 blocked" |
| `StimmungBadge` | `GET /api/stimmung` | Stance label + colored dot (nominal=green, cautious=yellow, degraded=orange, critical=red) |
| `NudgeCount` | `GET /api/nudges` | "3 active nudges" with expand-to-list |
| `MeasureDetail` | `GET /api/sprint/measures/{id}` | Status badge, effort, posterior gain, WSJF, day/block schedule |
| `MeasureDeps` | `GET /api/sprint/measures` | Dependency tree: "Blocked by: 7.1 (pending)" / "Blocks: 7.3, 7.4" with status badges |
| `GateAssociation` | `GET /api/sprint/gates/{gate}` | Gate condition, status, result if evaluated |
| `ModelPosterior` | `GET /api/sprint` | "Salience: 0.61 baseline → 0.64 current (+0.03 gained, +0.25 possible)" |
| `GateDetail` | `GET /api/sprint/gates/{id}` | Condition, trigger measure + status, downstream measures + status, result value |
| `Burndown` | `GET /api/sprint` | Completed/pending/blocked/skipped per sprint, effort consumed vs total |
| `PosteriorTable` | `GET /api/sprint` | Live table: 6 models x (baseline, gained, current, possible, measures completed) |
| `ResearchContext` | `GET /api/sprint/measures` | Which measures cite this research, which model it supports, current posterior |
| `ConceptBacklinks` | Obsidian MetadataCache | Notes that reference this concept (via backlinks API) |
| `HealthSnapshot` | `GET /api/health` | Healthy/degraded/failed counts |
| `NudgeList` | `GET /api/nudges` | Full nudge list with dismiss/act buttons |
| `StimmungDetail` | `GET /api/stimmung` | All dimensions with values and trends (nominal dims hidden) |

### NoteKind → Sections

| NoteKind | Sections (top to bottom) |
|----------|------------------------|
| **Measure** | `MeasureDetail` → `MeasureDeps` → `GateAssociation` (if gated) → `ModelPosterior` → `SprintStatus` |
| **Gate** | `GateDetail` → `SprintStatus` |
| **SprintSummary** | `Burndown` → `StimmungBadge` → `NudgeCount` |
| **PosteriorTracker** | `PosteriorTable` → `SprintStatus` |
| **Research** | `ResearchContext` → `ModelPosterior` (if model identified from tag) → `SprintStatus` |
| **Concept** | `ConceptBacklinks` → `ResearchContext` (if linked measures found) → `SprintStatus` |
| **Briefing** | `HealthSnapshot` → `StimmungDetail` → `NudgeCount` → `SprintStatus` |
| **Nudges** | `NudgeList` → `SprintStatus` |
| **Unknown** | `SprintStatus` → `StimmungBadge` → `NudgeCount` |

The Unknown layout is intentionally minimal — one line of sprint progress, a colored stimmung dot, and nudge count. Non-intrusive on notes that have nothing to do with hapax.

## Logos API Endpoints

### Existing (no changes needed)

| Endpoint | Returns |
|----------|---------|
| `GET /api/health` | `{status, healthy, degraded, failed, checks[]}` |
| `GET /api/nudges` | `{nudges: [{category, priority_score, title, detail, source_id}]}` |
| `GET /api/goals` | `{primary: [...], secondary: [...]}` |

### New Endpoints Required

#### GET /api/sprint

Returns the current sprint state. Reads `/dev/shm/hapax-sprint/state.json`.

```json
{
  "current_sprint": 0,
  "current_day": 0,
  "measures_completed": 3,
  "measures_total": 28,
  "measures_in_progress": 1,
  "measures_blocked": 4,
  "measures_skipped": 0,
  "measures_pending": 20,
  "effort_completed": 4.5,
  "effort_total": 91.2,
  "gates_passed": 1,
  "gates_failed": 0,
  "gates_pending": 6,
  "next_block": {"measure": "6.3", "title": "Threshold-cross telemetry", "day": 1, "scheduled": "1400-1600"},
  "blocking_gate": null,
  "models": {
    "Salience / Biased Competition": {"baseline": 0.61, "gained": 0.03, "current": 0.64, "possible": 0.89, "completed": 1, "total": 4},
    ...
  }
}
```

#### GET /api/sprint/measures

Returns all measure frontmatter. Reads vault notes in `~/Documents/Personal/20 Projects/hapax-research/sprint/measures/`.

```json
{
  "measures": [
    {"id": "7.1", "title": "Log missing salience signals", "model": "Salience / Biased Competition", "status": "completed", "sprint": 0, "day": 1, "block": "0930-1000", "effort_hours": 0.25, "posterior_gain": 0.03, "gate": null, "depends_on": [], "blocks": ["7.2", "7.3"], "completed_at": "2026-03-30T09:45:00Z", "result_summary": "3 signals logging"},
    ...
  ]
}
```

#### GET /api/sprint/measures/{id}

Returns single measure detail. Same schema as array element above.

#### GET /api/sprint/gates

Returns all gate frontmatter.

```json
{
  "gates": [
    {"id": "G1", "title": "DMN hallucination containment", "model": "DMN Continuous Substrate", "trigger_measure": "4.1", "condition": "contradiction_rate < 0.15", "status": "pending", "result_value": null, "downstream_measures": ["4.2", "4.3", "4.4", "4.5"], "nudge_required": true, "acknowledged": false},
    ...
  ]
}
```

#### GET /api/sprint/gates/{id}

Returns single gate detail.

#### GET /api/stimmung

Returns current stimmung state. Reads `/dev/shm/hapax-stimmung/state.json`.

```json
{
  "overall_stance": "cautious",
  "dimensions": {
    "health": {"value": 0.072, "trend": "stable"},
    "resource_pressure": {"value": 0.0, "trend": "stable"},
    "error_rate": {"value": 0.0, "trend": "stable"},
    "processing_throughput": {"value": 0.118, "trend": "stable"},
    "perception_confidence": {"value": 0.071, "trend": "stable"},
    "llm_cost_pressure": {"value": 0.0, "trend": "stable"},
    "grounding_quality": {"value": 0.0, "trend": "stable"},
    "operator_stress": {"value": 0.0, "trend": "stable"},
    "operator_energy": {"value": 0.7, "trend": "stable"},
    "physiological_coherence": {"value": 0.5, "trend": "stable"}
  },
  "timestamp": 1774773921.23
}
```

#### POST /api/sprint/measures/{id}/transition

Transitions a measure's status. Writes to `/dev/shm/hapax-sprint/completed.jsonl` (same signal format as the PostToolUse hook). The sprint tracker agent processes on next tick.

Request:
```json
{"status": "completed", "result_summary": "contradiction_rate: 0.08"}
```

Response:
```json
{"ok": true, "measure_id": "4.1", "new_status": "completed"}
```

Valid transitions: `pending → in_progress`, `pending → completed`, `in_progress → completed`.

#### POST /api/sprint/gates/{id}/acknowledge

Acknowledges a failed gate. Writes `{"acknowledged": true}` to `/dev/shm/hapax-sprint/nudge.json`.

Response:
```json
{"ok": true, "gate_id": "G1"}
```

#### POST /api/nudges/{source_id}/dismiss

Dismiss a nudge. Proxies to existing nudge_dismiss logic.

#### POST /api/nudges/{source_id}/act

Act on a nudge. Proxies to existing nudge_act logic.

## Logos API Cache Strategy

The plugin caches API responses client-side to avoid hammering localhost.

| Endpoint | Cache TTL | Refresh Trigger |
|----------|-----------|----------------|
| `/api/sprint` | 30s | Active leaf change, interval |
| `/api/sprint/measures` | 60s | Active leaf change |
| `/api/sprint/measures/{id}` | 30s | Active leaf change |
| `/api/sprint/gates` | 60s | Active leaf change |
| `/api/sprint/gates/{id}` | 30s | Active leaf change |
| `/api/stimmung` | 15s | Interval only |
| `/api/health` | 30s | Active leaf change |
| `/api/nudges` | 60s | Active leaf change, after action |

"Active leaf change" means the cache is checked (and potentially refreshed) when the user navigates to a different note. "Interval" means a background timer refreshes regardless of navigation.

After any POST action (transition, acknowledge, dismiss), the relevant GET cache is invalidated immediately.

## Write-Back Actions

All mutations go through logos-api. The plugin never writes to the vault — the sprint tracker agent handles vault propagation on next tick (5 min max).

| Action | UI Element | API Call | Where Available |
|--------|-----------|----------|----------------|
| Start measure | "Start" button on MeasureDetail section | `POST /api/sprint/measures/{id}/transition` `{"status": "in_progress"}` | Measure notes (status=pending) |
| Complete measure | "Complete" button + text input for result_summary | `POST /api/sprint/measures/{id}/transition` `{"status": "completed", "result_summary": "..."}` | Measure notes (status=pending or in_progress) |
| Acknowledge gate | "Acknowledge" button on GateDetail section | `POST /api/sprint/gates/{id}/acknowledge` | Gate notes (status=failed, acknowledged=false) |
| Dismiss nudge | "Dismiss" button per nudge item | `POST /api/nudges/{source_id}/dismiss` | Nudges note, NudgeList section |
| Act on nudge | "Act" button per nudge item | `POST /api/nudges/{source_id}/act` | Nudges note, NudgeList section |

Action buttons are conditionally rendered based on current state. A completed measure doesn't show "Start" or "Complete". A passed gate doesn't show "Acknowledge". Dismissed nudges disappear after cache refresh.

## Plugin Settings

| Setting | Type | Default | Synced | Notes |
|---------|------|---------|--------|-------|
| `logosApiUrl` | string | `http://localhost:8051` | No | Device-local; different machines may have different ports |
| `refreshInterval` | number | 30 (seconds) | Yes | Background refresh cadence for stimmung + sprint |
| `showOnUnknownNotes` | boolean | true | Yes | Show minimal context (sprint + stimmung + nudges) on non-hapax notes |
| `collapsedSections` | string[] | [] | Yes | Sections the user has manually collapsed (persisted) |

## Plugin Lifecycle

### onload()

1. Register `ContextPanel` view type
2. Add ribbon icon (activate panel)
3. Register `workspace.on('active-leaf-change')` handler → re-resolve context
4. Start background refresh timer (stimmung + sprint at `refreshInterval`)
5. Load settings

### onunload()

1. Clear refresh timer
2. Detach view

### Active Leaf Change Handler

1. Get active file from workspace
2. Read frontmatter from MetadataCache
3. Call `ContextResolver.classify(file, frontmatter)` → NoteKind + identifiers
4. If NoteKind changed or identifiers changed: fetch new data from LogosClient, re-render panel
5. If same NoteKind and identifiers: skip (cached data is still valid)

## Styling

Minimal CSS. Uses Obsidian's native CSS variables for colors and spacing. Custom styles only for:

- Status badges (colored pills: green=completed, blue=in_progress, gray=pending, red=blocked, dimmed=skipped)
- Stimmung dot (4 colors matching stance)
- Action buttons (Obsidian's native button style + mod-cta for primary actions)
- Section headers (collapsible, matching Obsidian's callout style)
- Posterior values (monospace, right-aligned in table)

No custom fonts, no external CSS, no dark/light theme overrides — inherit everything from Obsidian.

## Removed from v1

| Feature | Reason |
|---------|--------|
| Chat sidebar | No LLM calls; context panel replaces interaction model |
| LLM provider config (LiteLLM/OpenAI/Anthropic) | No LLM calls |
| Qdrant/Ollama direct connections | Logos-api handles search |
| InterviewEngine / management setup | Officium concern, dropped per corporate_boundary axiom |
| Work vault detection + commands (/prep, /review-week, /growth, /team-risks) | Personal vault only |
| Knowledge search modal | Obsidian native search + Bases |
| Profile modal | Context panel shows relevant profile data |
| Status bar health display | Context panel replaces |
| Slash command system | No chat |
| Decision capture modal | Not needed in Personal vault |
| Team snapshot generation | Officium concern |

## New in v2

| Feature | Description |
|---------|-------------|
| Context resolver | Note-type detection from frontmatter + path patterns |
| Sprint-aware sidebar | Measure deps, gate status, burndown, posterior tracking |
| Stimmung display | Stance badge + dimension detail (non-nominal only) |
| Research enrichment | Concept backlinks, model association, measure dependencies |
| Write-back actions | Measure transitions, gate acknowledgment, nudge management |
| Single API dependency | Logos-api only — no direct filesystem, no LLM, no vector DB |
| 9 new logos-api endpoints | 4 sprint GET + 2 sprint POST + 1 stimmung GET + 2 nudge POST |

## Implementation Scope

### Plugin (TypeScript, Obsidian API)

- `main.ts` — Plugin lifecycle, view registration, settings
- `context-resolver.ts` — NoteKind classification from frontmatter + path
- `logos-client.ts` — HTTP client with TTL caching, single dependency on :8051
- `context-panel.ts` — ItemView rendering sections based on NoteKind
- `sections/` — Individual section renderers (sprint-status, measure-detail, gate-detail, stimmung-badge, nudge-list, posterior-table, etc.)
- `settings.ts` — PluginSettingTab with 4 settings
- `styles.css` — Minimal: status badges, stimmung dot, action buttons

### Logos API (Python, FastAPI)

- `logos/api/routes/sprint.py` — 6 new endpoints (4 GET, 2 POST)
- `logos/api/routes/stimmung.py` — 1 new endpoint (GET, reads /dev/shm)
- `logos/api/routes/nudges.py` — 2 new endpoints (POST dismiss/act, if not already exposed)

### No Changes Required

- Sprint tracker agent (already writes to /dev/shm and vault)
- Stimmung collector (already writes to /dev/shm)
- Vault notes (plugin reads frontmatter via Obsidian API, never writes)
- MCP server (unaffected — parallel access path)
- Logos Tauri app (unaffected — parallel display surface)
