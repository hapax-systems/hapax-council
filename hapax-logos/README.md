# hapax-logos — The Visual Body

Tauri 2 desktop application that serves as Hapax's visual body. A wgpu-powered generative surface renders the system's experiential state as ambient art, while a React control panel provides operational views.

The display IS the agent. When nothing needs attention, Hapax plays — generative, surprising, alive. When signals arise, they layer on top of the visual richness. The operator doesn't read this display. They feel it.

## Architecture

- **Rust backend**: wgpu visual surface on dedicated thread, 6 GPU technique layers (gradient, reaction-diffusion, voronoi, wave, physarum, feedback), compositor with per-layer opacity blending, post-processing (vignette, sediment)
- **React frontend**: 8 pages (Dashboard, Chat, Flow, Insight, Demos, Studio, Visual, Hapax), Tauri IPC for commands and events
- **Output**: BGRA frames to `/dev/shm/hapax-visual/frame.bgra`, directive bridge via `/dev/shm/hapax-logos/directives.jsonl`

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
| **Hapax** | Full-screen ambient canvas — the Corpora surface |

## System Anatomy (Flow Page)

React Flow visualization of the system's circulatory anatomy. 9 nodes, 16 edges showing data flow topology. Polls every 3s from /dev/shm via Tauri IPC or cockpit HTTP API fallback.

Enrichments: particle-density edges (throughput), breathing nodes (tick cadence), staleness color shift (green → amber), attention decay (unchanged nodes fade), consent state dots, gate barriers.

## Running

```bash
cd hapax-logos

# Browser mode (recommended for Wayland):
pnpm dev                    # Vite at :5173
open http://localhost:5173/flow

# Tauri mode (native window):
HAPAX_NO_VISUAL=1 pnpm tauri dev   # Skip wgpu surface for Wayland compat
```

Requires cockpit API at :8051 for Flow page data.

## Stack

React 19, TypeScript 5.9, Vite 7, Tailwind 4, @xyflow/react, Recharts, Tauri 2, wgpu 24, winit 0.30.
