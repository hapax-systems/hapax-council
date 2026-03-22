# Cockpit Actionability Design

**Date**: 2026-03-09
**Status**: Approved
**Scope**: Make cockpit data panels actionable — connect scout, briefing, health, drift, and nudge panels to the agent execution system. Add scout decision workflow.

## Problem Statement

The cockpit displays rich operational data (scout recommendations, briefing action items, health failures, drift findings) but is mostly read-only. Users see what needs doing but can't act on it. Scout recommendations dead-end entirely — no decision tracking or adoption workflow exists.

## Design Decisions

1. **Unified action pattern**: All actionable items navigate to the agent grid with pre-filled config. User reviews and clicks Run. No fire-and-forget.
2. **Agent grid pre-fill via React context**: Panels set `pendingAgentRun` state, which auto-opens the agent config modal with flags pre-filled on the dashboard.
3. **Scout gets a decision workflow**: Record adopt/defer/dismiss decisions. Adopted recommendations trigger research agent for migration plan generation.
4. **Command parsing**: Frontend utility extracts agent name + flags from command strings like `uv run python -m agents.health_monitor --fix`.

## Section 1: Agent Grid Pre-fill Mechanism

React state in shared app context. When a panel wants to trigger an agent run, it sets:

```typescript
pendingAgentRun: { agent: string, flags: Record<string, string> } | null
```

**Flow:**
1. User clicks action button on any data panel
2. App sets `pendingAgentRun` with agent name and flags
3. React Router navigates to `/` (dashboard)
4. AgentGrid detects pending run, auto-opens AgentConfigModal with flags pre-filled
5. User reviews and clicks Run, SSE output streams as normal
6. `pendingAgentRun` cleared

No backend changes needed — frontend state management only.

## Section 2: Action Buttons on Data Panels

### Health panel
When `failed > 0`, show "Auto-fix" button. Triggers: `health_monitor --fix`.

### Drift panel
When `drift_count > 0`, show "Fix drift" button. Triggers: `drift_detector --fix`.

### Briefing panel
Each action item with a `command` field gets a play button. Command string parsed to extract agent name and flags. Items without commands stay display-only.

### Nudge list
Nudges with `command_hint` already show play icon. Change: clicking "act" records the decision AND navigates to agent grid with parsed command. Nudges without command hints behave as today (record decision only).

### Command parsing utility

```typescript
function parseAgentCommand(cmd: string): { agent: string; flags: Record<string, string> } | null
```

Parses strings like `uv run python -m agents.health_monitor --fix --history` into `{ agent: "health_monitor", flags: { "--fix": "", "--history": "" } }`. Returns null if command doesn't match `agents.<name>` pattern.

## Section 3: Scout Decision Workflow

### Decision states
Each scout recommendation: `pending` (default), `adopted`, `deferred`, `dismissed`.

### Backend (ai-agents)

**New endpoints:**
- `POST /api/scout/{component}/decide` — accepts `{ decision: "adopted" | "deferred" | "dismissed", notes?: string }`. Appends to `profiles/scout-decisions.jsonl`.
- `GET /api/scout/decisions` — returns all decisions for cross-referencing with current recommendations.

**Storage:** `profiles/scout-decisions.jsonl` with fields: `component`, `decision`, `timestamp`, `notes`.

**Plan generation:** When adopted, research agent triggered via agent execution system with prompt scoped to migration evaluation. Output saved to `profiles/scout-plans/{component}.md`.

### Frontend (hapax-logos)

Each scout recommendation gets 3 action buttons: Adopt (green), Defer (yellow), Dismiss (red).

- **Adopt**: records decision + navigates to agent grid with research agent pre-filled for migration plan
- **Defer/Dismiss**: records decision, recommendation dims/moves to bottom
- Already-decided recommendations show status badge instead of action buttons
- Decisions merged with scout report data on display

### Data flow
1. Scout agent runs weekly → `profiles/scout-report.json`
2. Cockpit reads report + decisions, merges for display
3. User adopts → decision recorded + research agent triggered
4. Research agent → migration plan in `profiles/scout-plans/`
5. Next scout run sees adoption history, adjusts recommendations

## Section 4: Testing

### Backend
- Scout decision endpoint: 3 tests (record, retrieve, adopt triggers plan flag)

### Frontend
- Manual validation (no test suite in hapax-logos):
  - Health: fail a check → "Auto-fix" appears → navigates to agent grid with `health_monitor --fix`
  - Drift: "Fix drift" when drift_count > 0
  - Briefing: play button on command items → parses and navigates
  - Nudge: act on command_hint nudge → navigates to agent grid
  - Scout: adopt/defer/dismiss buttons → adopt navigates to research agent
