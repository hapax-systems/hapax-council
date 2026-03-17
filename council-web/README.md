# council-web — Operational Dashboard

A React single-page application that provides real-time operational visibility into the hapax-council agent system. Health monitoring, agent execution, streaming chat, nudge management, and demo browsing — backed by the cockpit API via Server-Sent Events and React Query.

This is a Tier 1 interface: interactive, human-facing, read-heavy. It consumes the cockpit API (:8051) but never writes to the filesystem-as-bus directly. All mutations go through API endpoints that the reactive engine processes.

## Why This Dashboard Exists

The `executive_function` axiom (weight 95) requires that system state be visible without investigation. The operator should never have to SSH into the home server, check log files, or run diagnostic commands to understand what agents are doing. The dashboard satisfies this requirement by surfacing everything the operator needs — health status, agent output, active nudges, cost tracking, data freshness — in a single interface that pushes state changes to the browser rather than waiting to be polled.

The `useHealthToasts` hook is the most direct expression of this axiom in the frontend. It watches health status and surfaces degradation as non-intrusive toast notifications. A Docker container goes down, a systemd timer misses its schedule, a Qdrant collection drops below threshold — the operator sees it without looking for it.

## Architecture

**Server state** is managed exclusively through TanStack React Query. Every backend call goes through `src/api/client.ts`, which hits `/api/*` (Vite proxies to :8051 in dev). Types in `src/api/types.ts` mirror the Python dataclasses in `cockpit/data/`. There is no local state management library — React Query is the single source of truth for anything that comes from the backend. This avoids the synchronization bugs that emerge when frontend state diverges from backend state.

**Streaming chat** uses Server-Sent Events (`src/api/sse.ts`) for the chat interface, handling Anthropic-style `content_block_delta` events, tool call rendering, and reconnection. Messages are streamed token-by-token with markdown rendering.

**Contextual panels** — 15 sidebar panels show information relevant to the operator's current focus: system health, VRAM utilization, Docker containers, systemd timers, morning briefing, goals, scout findings, inference cost, documentation drift, management context, accommodation status, and data freshness. Each panel polls at intervals appropriate to its data, from 30 seconds (health) to once per session (briefing).

## Design Decisions

**No test runner.** The dashboard is a thin presentation layer over a comprehensively tested backend. For a system with one user who is also the developer, the cost of maintaining frontend tests exceeds the value. If this changes, the architecture supports adding tests without refactoring.

**Tailwind only.** No CSS modules, no styled-components. Styling is collocated with markup. One fewer abstraction to maintain.

**Feature-based folders.** Components are grouped by what they do (chat, dashboard, demos, sidebar, shared), not by type. Each feature folder is self-contained.

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
| `/insight` | InsightPage | Analysis and insights |
| `/demos` | DemosPage | Browse and view generated capability demos |
| `/studio` | StudioPage | Studio control panel for visual effects and camera management |
| `/hapax` | HapaxPage | Hapax Corpora — full-screen generative visual canvas (the agent's visual body) |

## Stack

React 19, TypeScript 5.9 (strict), Vite 7, Tailwind CSS 4, TanStack React Query, React Router 7, Recharts, Lucide React, react-markdown + remark-gfm, JetBrains Mono.

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
    sidebar/        15 contextual panels
  hooks/            useHealthToasts, useInputHistory, useKeyboardShortcuts, useSSE
  pages/            DashboardPage, ChatPage, DemosPage
  utils.ts          Shared utilities
```
