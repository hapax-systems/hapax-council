# Cockpit Web Migration Design

**Date:** 2026-03-02
**Status:** Approved
**Scope:** Replace Textual TUI cockpit with web frontend (React SPA + FastAPI backend)

## Motivation

The Textual TUI has hit two fundamental ceilings:
1. **Mobile/remote access** — logos is locked to a local terminal, inaccessible from phone or other machines via Tailscale
2. **Feature ceiling** — rich visualizations (charts, gauges), responsive layout, interactive UI patterns that terminals fundamentally can't support

## Decision

Replace the Textual TUI entirely with a web-based cockpit. No dual-maintenance — the Textual UI code gets deleted after migration. The `--once` snapshot CLI mode may be preserved if useful.

## Architecture

### Overview

```
┌─────────────────┐    HTTP/SSE     ┌──────────────────┐
│  React SPA       │ ◄────────────► │  FastAPI Backend  │
│  (hapax-logos)   │                │  (logos/api/)   │
│  Vite + pnpm     │                │  in ai-agents     │
└─────────────────┘                └──────────┬───────┘
                                              │
                               imports directly│
                                              ▼
                                   ┌──────────────────┐
                                   │  logos/data/*   │
                                   │  cockpit/chat_*   │
                                   │  logos/runner   │
                                   │  (existing Python)│
                                   └──────────────────┘
```

**Backend** stays in `~/projects/hapax-council/`. The existing `logos/data/` pure dataclass collectors are imported directly by the FastAPI app. No reimplementation.

**Frontend** is a new repo at `~/projects/hapax-logos/` (React 19 + Vite + TypeScript + pnpm).

**Deployment** is a new Docker service `logos-api` bound to `127.0.0.1:8050`, accessible over Tailscale.

### What stays, what goes

| Component | Action |
|-----------|--------|
| `logos/data/` (14 collectors) | **Keep** — unchanged, consumed by API |
| `logos/chat_agent.py` (985 LOC) | **Keep** — consumed by chat API endpoints |
| `logos/interview.py` (655 LOC) | **Keep** — consumed by interview API endpoints |
| `logos/copilot.py` (255 LOC) | **Keep** — consumed by copilot API endpoint |
| `logos/runner.py` (160 LOC) | **Keep** — consumed by agent execution endpoint |
| `logos/snapshot.py` (364 LOC) | **Keep** — `--once` CLI mode |
| `logos/accommodations.py` | **Keep** — consumed by API |
| `cockpit/micro_probes.py` | **Keep** — consumed by API |
| `cockpit/manual.py` | **Keep** — consumed by API |
| `cockpit/voice.py` | **Keep** — consumed by API |
| `logos/api/` | **New** — FastAPI app |
| `cockpit/app.py` (545 LOC) | **Delete** — Textual app |
| `cockpit/screens/` (4 screens) | **Delete** — Textual UI |
| `cockpit/widgets/` (7 widgets) | **Delete** — Textual UI |
| `cockpit/*.tcss` (2 files) | **Delete** — Textual CSS |

Net: ~2,300 LOC of Textual UI deleted. ~5,200 LOC of business logic preserved.

## API Design

### Data Endpoints (polling)

| Endpoint | Source Module | Client Poll Cadence |
|----------|-------------|-------------------|
| `GET /api/health` | `data/health.py` | 30s |
| `GET /api/health/history` | `data/health.py` | on-demand |
| `GET /api/gpu` | `data/gpu.py` | 30s |
| `GET /api/infrastructure` | `data/infrastructure.py` | 30s |
| `GET /api/briefing` | `data/briefing.py` | 5min |
| `GET /api/scout` | `data/scout.py` | 5min |
| `GET /api/drift` | `data/drift.py` | 5min |
| `GET /api/cost` | `data/cost.py` | 5min |
| `GET /api/goals` | `data/goals.py` | 5min |
| `GET /api/readiness` | `data/readiness.py` | 5min |
| `GET /api/management` | `data/management.py` | 5min |
| `GET /api/nudges` | `data/nudges.py` | 5min |
| `GET /api/agents` | `data/agents.py` | static |
| `GET /api/snapshot` | `snapshot.py` | on-demand |
| `GET /api/accommodations` | `accommodations.py` | on-demand |

### Action Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/agents/{name}/run` | Launch agent (body: `{flags: [...]}`) |
| `GET /api/agents/{name}/output` | SSE stream of agent stdout/stderr |
| `POST /api/decisions` | Record nudge decision |

### Chat Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/chat/message` | Send message, response is SSE stream |
| `POST /api/chat/new` | Create new session |
| `GET /api/chat/history` | Get message history for display |
| `POST /api/chat/interview/start` | Start interview |
| `POST /api/chat/interview/end` | End interview |
| `POST /api/chat/interview/skip` | Skip current topic |
| `GET /api/chat/interview/status` | Interview progress |

### Caching

Server-side background tasks refresh data at the same cadence as the current Textual refresh cycles:
- **Fast (30s):** health, GPU, infrastructure
- **Slow (5min):** briefing, scout, drift, cost, goals, readiness, management, nudges

Endpoints return cached data. Clients poll at matching intervals via TanStack Query.

### Auth

None initially. Service bound to `127.0.0.1:8050`. Tailscale provides network-level authentication for remote access. API key auth can be added later if needed.

## Frontend Design

### Stack

- React 19 + TypeScript
- Vite (build)
- pnpm (package manager)
- TanStack Query (server state, polling)
- Tailwind CSS (utility-first styling, responsive)
- react-markdown + remark-gfm (chat rendering)
- Recharts (health trends, cost charts)
- Lucide React (icons)

### Layout

```
┌─────────────────────────────────────────────────────┐
│ Header: copilot line + system status indicators     │
├──────────────────────────┬──────────────────────────┤
│ Main Content (tabs):     │ Sidebar (collapsible):   │
│ ┌────────────────────┐   │ Health summary           │
│ │ Nudges / Actions   │   │ VRAM gauge               │
│ │ Agent Launcher     │   │ Readiness indicator      │
│ │ Output Pane        │   │ Goals                    │
│ └────────────────────┘   │ Timers                   │
│                          │ Freshness                │
├──────────────────────────┴──────────────────────────┤
│ Chat panel (expandable / slide-up from bottom)      │
└─────────────────────────────────────────────────────┘
```

**Mobile:** Sidebar collapses to hamburger. Chat goes full-screen. Nudges and agents stack vertically.

### Chat UI

- Streaming text with typing indicator
- Tool call visualization as collapsible cards (tool name + args + result)
- Interview mode with progress bar and topic indicators
- `/command` support via input prefix detection
- Message history with full markdown rendering
- Session info display (model, token count)

### New capabilities (beyond Textual)

- Health trend sparklines and charts
- VRAM gauge visualization
- Clickable nudge-to-action flow
- Agent output with ANSI color rendering
- Responsive mobile layout
- Deep-linkable views

## Streaming Protocol

### Chat messages (SSE)

```
POST /api/chat/message
Content-Type: application/json
{"text": "check health status"}

← HTTP 200
Content-Type: text/event-stream

data: {"type": "text_delta", "content": "Let me check..."}
data: {"type": "tool_start", "name": "check_health", "args": {}}
data: {"type": "tool_result", "name": "check_health", "result": "..."}
data: {"type": "text_delta", "content": "Health looks good..."}
data: {"type": "done", "tokens": {"input": 1200, "output": 350}}
```

### Agent execution (SSE)

```
POST /api/agents/health-monitor/run
Content-Type: application/json
{"flags": ["--history"]}

← HTTP 200
Content-Type: text/event-stream

data: {"type": "stdout", "line": "Running 49 checks..."}
data: {"type": "stdout", "line": "  [+] Docker daemon: ok"}
data: {"type": "exit", "code": 0, "duration": 3.2}
```

## Migration Phases

Each phase is independently deployable.

### Phase 1: API Skeleton + Dashboard

- FastAPI app with all data endpoints
- Background refresh tasks (30s/5min caching)
- React SPA: dashboard layout, sidebar, nudge list, agent list
- Docker compose service definition
- **Deliverable:** Functional read-only dashboard, accessible over Tailscale from phone

### Phase 2: Agent Execution

- Agent launch endpoints + SSE stdout streaming
- Agent launcher UI with flag configuration modal
- Output pane with streaming display + ANSI rendering
- Decision recording for nudge actions
- **Deliverable:** Can launch and monitor agents from the web UI

### Phase 3: Chat System

- Chat message endpoint + SSE streaming
- Chat UI: markdown rendering, tool call visualization, /commands
- Session management (new, history, persistence)
- Interview system (start, end, skip, progress display)
- **Deliverable:** Full chat feature parity with Textual

### Phase 4: Polish & Cleanup

- Copilot line (contextual observations header)
- Accommodations UI
- Health trend charts, VRAM gauge, cost sparklines
- Mobile responsive refinement
- Delete Textual code (screens/, widgets/, app.py, *.tcss)
- Remove `textual` from pyproject.toml dependencies
- **Deliverable:** Complete migration, old code removed

## Testing Strategy

- **Backend:** pytest for API endpoints (httpx test client), existing data collector tests unchanged
- **Frontend:** Vitest + React Testing Library for components, MSW for API mocking
- **Integration:** Playwright for end-to-end (chat streaming, agent launch flow)

## Risks

| Risk | Mitigation |
|------|-----------|
| Chat streaming fidelity | Phase 3 is dedicated to this. Existing ChatSession class stays in Python. |
| Interview system complexity | Interview agent + state machine stay unchanged. API just wraps them. |
| Docker socket access | logos-api container needs docker socket mount (same as existing services) |
| CORS | FastAPI CORS middleware, restrict to localhost origins |
| Mobile performance | TanStack Query deduplication + stale-while-revalidate. Minimal bundle with code splitting. |
