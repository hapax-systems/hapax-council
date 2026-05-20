# hapax-logos

Browser-hosted Logos control surface. The former Tauri/WebKit native shell is
decommissioned and the Rust `src-tauri` package is a fail-closed stub so the
active Cargo lockfile does not retain the retired GTK3/WebKitGTK dependency
graph.

## Architecture

- **React frontend**: operational views and live system topology, served in
  browser mode with Logos API fallbacks.
- **Production runtime**: `logos-api :8051` plus `studio-compositor` and
  `hapax-imagination`; see `docs/runbooks/tauri-logos-decommission.md`.
- **Native shell**: retired. `src-tauri` is retained only as a Cargo package
  stub that exits with the decommission message.

## Pages

| Page | Purpose |
|------|---------|
| **Dashboard** | Operational overview (health, agents, nudges) |
| **Chat** | Conversational agent interface |
| **Flow** | Live system anatomy visualization (React Flow) |
| **Insight** | System intelligence and analysis |
| **Demos** | Demo history and generation |
| **Studio** | Camera feeds, compositor control |
| **Visual** | Visual surface parameter control |
| **Hapax** | Full-screen ambient canvas |

## System Anatomy (Flow Page)

React Flow visualization of system topology. 9 nodes, 16 edges. Polls every 3s
through the Logos HTTP API fallback.

Enrichments: particle-density edges (throughput), breathing nodes (tick cadence), staleness color shift (green → amber), attention decay (unchanged nodes fade), consent state dots, gate barriers.

## Running

```bash
cd hapax-logos

# Browser mode:
pnpm dev                    # Vite at :5173
open http://localhost:5173/flow

# Native Tauri mode:
# decommissioned; use browser mode and logos-api :8051.
```

Requires logos API at :8051 for Flow page data.

## Stack

React 19, TypeScript 5.9, Vite 7, Tailwind 4, @xyflow/react, Recharts.
