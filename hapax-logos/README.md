# hapax-logos

Tauri 2 desktop application. A wgpu-powered generative surface renders system state as ambient visuals. A React control panel provides operational views and a live system topology.

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
| **Hapax** | Full-screen ambient canvas |

## System Anatomy (Flow Page)

React Flow visualization of system topology. 9 nodes, 16 edges. Polls every 3s from /dev/shm via Tauri IPC or cockpit HTTP API fallback.

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
