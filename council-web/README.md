# council-web — Operational Dashboard

React single-page application providing real-time operational visibility into the hapax-council agent system. Health monitoring, agent execution, streaming chat, nudge management, and demo browsing — all backed by the cockpit API via Server-Sent Events and React Query.

This is a Tier 1 interface: interactive, human-facing, read-heavy. It consumes the cockpit API (:8051) but never writes to the filesystem-as-bus directly. All mutations go through API endpoints that the reactive engine processes.

## Architecture

The dashboard is structured around three concerns: **server state management** (what the backend knows), **real-time streaming** (what's happening now), and **contextual information display** (what the operator needs to see given what they're looking at).

**Server state** is managed exclusively through TanStack React Query. Every backend call goes through `src/api/client.ts`, which hits `/api/*` (Vite proxies to :8051 in dev). Types in `src/api/types.ts` mirror the Python dataclasses in `cockpit/data/`. React Query hooks in `src/api/hooks.ts` wrap the client with appropriate stale times, retry policies, and cache invalidation. There is no local state management library — React Query is the single source of truth for anything that comes from the backend.

**Real-time streaming** uses Server-Sent Events (`src/api/sse.ts`) for the chat interface. The streaming implementation handles Anthropic-style `content_block_delta` events, tool call rendering, and graceful reconnection. Chat messages are streamed token-by-token with markdown rendering via `react-markdown` + `remark-gfm`.

**Contextual display** is provided by 15 sidebar panels that show information relevant to the operator's current focus: system health, VRAM utilization, Docker container status, systemd timer states, morning briefing, goals, scout findings, inference cost tracking, documentation drift, management context, accommodation status, and data freshness. These panels poll at intervals appropriate to their data — health every 30 seconds, briefing once per session, cost daily.

## Design Decisions

**No test runner.** The dashboard is a thin presentation layer over a well-tested backend. The cockpit API has comprehensive tests; the dashboard adds visual presentation. This is a deliberate choice for a single-operator system where the operator is also the developer — the cost of maintaining frontend tests exceeds the value for a system with one user.

**Tailwind only.** All styling uses Tailwind CSS 4 via `@tailwindcss/vite`. No CSS modules, no styled-components, no CSS-in-JS. This keeps the styling collocated with the markup and eliminates an entire category of abstraction.

**Feature-based organization.** Components are grouped by what they do (chat, dashboard, demos, sidebar, shared), not by what they are (components, containers, hooks). Each feature folder is self-contained.

**Health toast notifications.** The `useHealthToasts` hook watches health status and surfaces degradation as non-intrusive toasts. The operator doesn't need to check a dashboard to know something changed — the executive function axiom requires that state be visible without investigation.

## Quick Start

```bash
pnpm install      # install dependencies
pnpm dev          # dev server on :5173
pnpm build        # type-check + production build
pnpm lint         # ESLint
```

Requires the cockpit API at :8051:
```bash
cd ~/projects/hapax-council
uv run cockpit-api
```

## Routes

| Path | Page | Purpose |
|------|------|---------|
| `/` | DashboardPage | Health overview, agent grid, nudge list, sidebar panels |
| `/chat` | ChatPage | Streaming chat with tool call rendering |
| `/demos` | DemosPage | Browse and view generated capability demos |

## Stack

- **React 19** + **TypeScript 5.9** (strict mode)
- **Vite 7** with `@vitejs/plugin-react`
- **Tailwind CSS 4** via `@tailwindcss/vite`
- **TanStack React Query** — server state
- **React Router 7** — client-side routing (3 routes)
- **Recharts** — health history visualization
- **Lucide React** — icons
- **react-markdown** + remark-gfm — markdown rendering
- **JetBrains Mono** — monospace font

## Project Structure

```
src/
  api/              Client, React Query hooks, SSE streaming, TypeScript types
  components/
    chat/           Chat messages, input, streaming, tool call rendering
    dashboard/      Agent grid, nudge list, output pane, copilot banner
    demos/          Demo list and detail views
    layout/         App shell, manual drawer, health toast watcher
    shared/         Command palette, error boundary, modals, markdown, toasts
    sidebar/        15 contextual panels (health, VRAM, containers, timers,
                    briefing, goals, scout, cost, drift, management,
                    accommodations, freshness)
  hooks/            useHealthToasts, useInputHistory, useKeyboardShortcuts, useSSE
  pages/            DashboardPage, ChatPage, DemosPage
  utils.ts          Shared utilities
```
