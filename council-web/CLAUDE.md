# CLAUDE.md

React SPA dashboard for the Hapax agent system. Provides health monitoring, agent execution, chat, nudge management, demo viewing, and management oversight in a single-page web interface.

## Quick Start

```bash
pnpm install      # install dependencies
pnpm dev          # dev server on :5173
pnpm build        # type-check + production build
pnpm lint         # ESLint
pnpm preview      # preview production build
```

**Requires the cockpit API backend running at :8051.** Start it from `~/projects/hapax-council/`:
```bash
uv run cockpit    # FastAPI on :8051
```

Vite proxies `/api` requests to `http://127.0.0.1:8051` in dev mode.

## Tech Stack

- **React 19** + **TypeScript 5.9** (strict mode, noUnusedLocals/Parameters)
- **Vite 7** with `@vitejs/plugin-react`
- **Tailwind CSS 4** via `@tailwindcss/vite`
- **TanStack React Query** for server state
- **React Router 7** (BrowserRouter, 3 routes)
- **Recharts** for health history charts
- **Lucide React** for icons
- **react-markdown** + remark-gfm for markdown rendering
- **JetBrains Mono** font

No test runner is currently configured.

## Project Structure

```
src/
  api/            API client, React Query hooks, SSE helpers, TypeScript types
  components/
    chat/         Chat UI (messages, input, streaming, tool calls)
    dashboard/    Agent grid, nudge list, output pane, copilot banner
    demos/        Demo list and detail views
    layout/       App layout shell, manual drawer, health toast watcher
    shared/       Reusable: command palette, error boundary, modals, markdown, toasts
    sidebar/      15 sidebar panels (health, VRAM, containers, timers, briefing,
                  goals, scout, cost, drift, management, accommodations, freshness)
  hooks/          useHealthToasts, useInputHistory, useKeyboardShortcuts, useSSE
  pages/          DashboardPage, ChatPage, DemosPage
  utils.ts        Shared utilities
```

## Routes

| Path | Page | Purpose |
|------|------|---------|
| `/` | DashboardPage | Health, agents, nudges, sidebar panels |
| `/chat` | ChatPage | Streaming chat with cockpit backend |
| `/demos` | DemosPage | Browse and view generated demos |

## API Layer

All backend calls go through `src/api/client.ts` which hits `/api/*` (proxied to :8051). Types in `src/api/types.ts` mirror the Python dataclasses in `~/projects/ai-agents/cockpit/data/`. React Query hooks in `src/api/hooks.ts` wrap the client. SSE streaming for chat in `src/api/sse.ts`.

## Conventions

- **pnpm only** — never npm or yarn
- TypeScript strict mode enforced (`strict: true`, `noUnusedLocals`, `noUnusedParameters`)
- Tailwind for all styling — no CSS modules or styled-components
- Functional components only
- Flat component folders grouped by feature (chat, dashboard, demos, sidebar, shared)
- API types must stay in sync with cockpit backend dataclasses

## Project Memory

### Stable Patterns
- React Query for server state management with hooks in `src/api/hooks.ts`
- SSE streaming via `src/api/sse.ts` for real-time chat updates
- Sidebar panels (15 total) for contextual information display
- Vite dev server proxies `/api` to cockpit backend at :8051
- Recharts used exclusively for health history visualization
- Lucide React for all UI icons

### Key Conventions
- All backend types defined in `src/api/types.ts` must mirror cockpit Python dataclasses
- Component organization: feature-based folders (chat, dashboard, demos, sidebar, shared)
- Streaming chat with tool call rendering in ChatPage
- Health monitoring with toast notifications via useHealthToasts hook
- Keyboard shortcuts managed centrally by useKeyboardShortcuts hook
- markdown rendering via react-markdown + remark-gfm plugin

### Architecture Notes
- Single-page app with 3 main routes: dashboard, chat, demos
- Layout shell in `components/layout/` manages app chrome and drawer
- Error boundaries in shared components for resilience
- Command palette in shared components for navigation
- No test runner currently configured
