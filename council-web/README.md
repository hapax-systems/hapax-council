# council-web

React SPA dashboard for the Hapax agent system. Provides health monitoring, agent execution, chat, nudge management, demo viewing, and management oversight in a single-page web interface.

## Quick start

```bash
pnpm install      # install dependencies
pnpm dev          # dev server on :5173
pnpm build        # type-check + production build
pnpm lint         # ESLint
pnpm preview      # preview production build
```

Requires the cockpit API backend running at :8051. Start it from the project root:

```bash
uv run cockpit-api    # FastAPI on :8051
```

Vite proxies `/api` requests to `http://127.0.0.1:8051` in dev mode.

## Architecture

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

## Tech stack

- **React 19** + **TypeScript 5.9** (strict mode)
- **Vite 7** with `@vitejs/plugin-react`
- **Tailwind CSS 4** via `@tailwindcss/vite`
- **TanStack React Query** for server state
- **React Router 7** (BrowserRouter)
- **Recharts** for health history charts
- **Lucide React** for icons
- **react-markdown** + remark-gfm for markdown rendering

## API layer

All backend calls go through `src/api/client.ts` which hits `/api/*` (proxied to :8051). Types in `src/api/types.ts` mirror the Python dataclasses in `cockpit/data/`. React Query hooks in `src/api/hooks.ts` wrap the client. SSE streaming for chat in `src/api/sse.ts`.

## Conventions

- **pnpm only** — never npm or yarn
- TypeScript strict mode enforced (`strict: true`, `noUnusedLocals`, `noUnusedParameters`)
- Tailwind for all styling — no CSS modules or styled-components
- Functional components only
- Flat component folders grouped by feature
- API types must stay in sync with cockpit backend dataclasses

No test runner is currently configured.
