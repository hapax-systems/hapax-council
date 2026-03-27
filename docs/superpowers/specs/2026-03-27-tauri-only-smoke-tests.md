# Tauri-Only Migration — Smoke Test Plan

**Scope:** Exercises all functionality changed by the Tauri-only migration (PR #377) and visual surface in webview feature. Run after `cargo tauri dev` launches successfully.

**Prerequisites:**
- `logos-api` running on `:8051` (`systemctl --user start logos-api`)
- Docker containers up (`docker compose up -d`)
- Visual surface enabled (no `HAPAX_NO_VISUAL=1`)

---

## 1. Application Launch

| # | Test | How | Pass |
|---|------|-----|------|
| 1.1 | Tauri app launches | `cd hapax-logos && pnpm tauri dev` | Window appears, no crash |
| 1.2 | No exposed localhost | Open `http://localhost:5173` in a browser | Page loads (Vite serves assets) but **no API calls work** — no proxy, all invoke-only |
| 1.3 | Visual surface thread starts | Check terminal for `hapax-visual` thread log | Log shows `Using adapter: NVIDIA GeForce RTX 3090` |
| 1.4 | HTTP frame server starts | Check terminal for frame server log | `Visual frame server listening on http://127.0.0.1:8053` |
| 1.5 | Command relay starts | Check terminal log | `Command relay listening on ws://127.0.0.1:8052` |
| 1.6 | No CORS for browser | `curl -H "Origin: http://localhost:5173" -I http://127.0.0.1:8051/api/health` | No `Access-Control-Allow-Origin: http://localhost:5173` header |

## 2. API Client (invoke-only)

All API calls now go through Tauri IPC. Test representative endpoints from each tier.

| # | Test | How | Pass |
|---|------|-----|------|
| 2.1 | Health snapshot | Terrain surface loads, health badge shows score | Data renders, no fetch errors in console |
| 2.2 | GPU stats | GPU card visible in horizon or bedrock region | VRAM numbers displayed |
| 2.3 | Infrastructure | Infrastructure section shows container status | Docker containers listed |
| 2.4 | Working mode | Current mode (R&D/Research) displayed | Mode badge visible |
| 2.5 | Set working mode | Toggle mode via UI or invoke | Mode changes, no error |
| 2.6 | Goals | Goals section populated | Goal items rendered |
| 2.7 | Scout | Scout section shows evaluations | Items with status |
| 2.8 | Drift | Drift summary loads | Drift count displayed |
| 2.9 | Nudges | Nudge list loads | Nudge cards rendered |
| 2.10 | Agents | Agent list loads | Agent names displayed |
| 2.11 | Briefing | Briefing content loads | Text content rendered |
| 2.12 | Studio | Studio section shows camera/compositor status | Status indicators visible |
| 2.13 | Cost | Cost section loads | Token/cost data |
| 2.14 | Accommodations | Accommodation list loads | Items rendered |

### Proxy endpoints (Rust → FastAPI passthrough)

| # | Test | How | Pass |
|---|------|-----|------|
| 2.15 | Copilot | Navigate to a page that loads copilot | Copilot response renders |
| 2.16 | Governance heartbeat | Governance section loads | Heartbeat data |
| 2.17 | Consent contracts | Consent section loads | Contract list |
| 2.18 | Engine status | Engine section loads | Rule count, status |
| 2.19 | Profile | Profile section loads | Dimension data |
| 2.20 | Insight queries | Insight page loads query list | Previous queries listed |
| 2.21 | Fortress state | Fortress section loads (if DF running) | State data or graceful empty |

## 3. Streaming (SSE → Tauri Events)

| # | Test | How | Pass |
|---|------|-----|------|
| 3.1 | Agent run streaming | Navigate to investigation, run an agent | Output lines stream in real-time |
| 3.2 | Agent run cancel | Start an agent run, cancel mid-stream | Stream stops, "cancelled" message |
| 3.3 | Chat send | Open chat, send a message | Response streams token-by-token |
| 3.4 | Chat cancel | Start a chat response, cancel | Stream stops cleanly |
| 3.5 | Query execution | Run an insight query | Query result streams |
| 3.6 | No fetch in console | Open DevTools Network tab during streaming | Zero `fetch` requests to `:8051` — all traffic via IPC |

## 4. Command Registry + Relay

### Keyboard commands (local)

| # | Test | How | Pass |
|---|------|-----|------|
| 4.1 | Region focus | Press `H`, `F`, `G`, `W`, `B` | Corresponding region focuses |
| 4.2 | Depth cycling | Press focused region key repeatedly | Cycles surface → stratum → core |
| 4.3 | Investigation overlay | Press `/` | Investigation overlay opens |
| 4.4 | Manual | Press `?` | Manual drawer opens |
| 4.5 | Split pane | Press `S` | Split pane toggles |
| 4.6 | Detection overlay | Press `D` | Detection overlay toggles |
| 4.7 | Command palette | Press `Ctrl+P` | Palette opens with command list |
| 4.8 | Escape sequences | Press `Esc` from various states | Returns to default state |

### External relay (WebSocket on :8052)

| # | Test | How | Pass |
|---|------|-----|------|
| 4.9 | MCP execute | Run an MCP tool that sends a command (e.g., `mcp__hapax__workspace`) | Command executes, result returns |
| 4.10 | WS list | `websocat ws://127.0.0.1:8052` then send `{"type":"list","id":"1"}` | Returns JSON with command definitions |
| 4.11 | WS execute | Send `{"type":"execute","id":"2","path":"terrain.focus","args":{"region":"ground"}}` | Terrain focuses ground region |
| 4.12 | WS query | Send `{"type":"query","id":"3","path":"terrain.state"}` | Returns current terrain state |
| 4.13 | WS subscribe | Send `{"type":"subscribe","id":"4","pattern":"terrain.*"}` then press `G` | Receives event with `terrain.focus` path |
| 4.14 | Old relay dead | `websocat ws://127.0.0.1:8051/ws/commands` | Connection refused or no response |

## 5. Visual Surface in Webview

| # | Test | How | Pass |
|---|------|-----|------|
| 5.1 | Frame server responds | `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8053/frame` | `200` (or `503` if surface not yet rendering) |
| 5.2 | Frame is JPEG | `curl -s http://127.0.0.1:8053/frame | file -` | Reports JPEG image data |
| 5.3 | Frame file exists | `ls -la /dev/shm/hapax-visual/frame.jpg` | File exists, ~100-200KB, updating |
| 5.4 | BGRA still written | `ls -la /dev/shm/hapax-visual/frame.bgra` | File exists, ~8.3MB |
| 5.5 | Stats endpoint | `curl http://127.0.0.1:8053/stats` | JSON response (may be `{}` if no state.json) |
| 5.6 | Visual behind terrain | Look at the Logos UI | Shader visuals visible behind/between terrain regions |
| 5.7 | AmbientShader coexists | WebGL noise overlay still renders | Both layers visible (VisualSurface behind, AmbientShader on top) |
| 5.8 | Frame rate | Open DevTools Network, filter for `frame` | ~30 requests/sec to `:8053/frame` |
| 5.9 | Page hidden stops polling | Switch to another tab, watch Network | Requests to `/frame` stop |
| 5.10 | Page visible resumes | Switch back to Logos tab | Requests resume |

### Winit window toggle

| # | Test | How | Pass |
|---|------|-----|------|
| 5.11 | Default visible | Look for separate `hapax-visual` window | Window exists alongside Tauri webview |
| 5.12 | Hide window | In DevTools console: `__TAURI_INTERNALS__.invoke("toggle_visual_window", {visible: false})` | hapax-visual window disappears |
| 5.13 | Webview still shows frames | After hiding winit window | Shader visuals still render in webview (pipeline still runs headless) |
| 5.14 | Show window | `__TAURI_INTERNALS__.invoke("toggle_visual_window", {visible: true})` | Window reappears |

### Layer opacity control

| # | Test | How | Pass |
|---|------|-----|------|
| 5.15 | Set opacity via command | `__TAURI_INTERNALS__.invoke("set_visual_layer_param", {layer: "physarum", opacity: 0.0})` | Physarum layer disappears from visual surface |
| 5.16 | Restore opacity | `__TAURI_INTERNALS__.invoke("set_visual_layer_param", {layer: "physarum", opacity: 0.6})` | Physarum layer reappears |
| 5.17 | Control.json written | `cat /dev/shm/hapax-visual/control.json` | Shows JSON with layer_opacities |
| 5.18 | Multiple layers | Set gradient to 0.5, voronoi to 0.0 | Visual surface reflects both changes |

## 6. CSP and Security

| # | Test | How | Pass |
|---|------|-----|------|
| 6.1 | No external connections | DevTools Console, check for CSP violations | No violations (or only expected ones) |
| 6.2 | Frame server allowed | VisualSurface loads frames without CSP error | Images load from `:8053` |
| 6.3 | No proxy leaks | DevTools Network, look for requests to `:8051` | Zero direct requests to FastAPI |
| 6.4 | Blob URLs work | Camera snapshots, visual surface preview | blob: URLs load correctly |

## 7. Edge Cases and Degradation

| # | Test | How | Pass |
|---|------|-----|------|
| 7.1 | FastAPI down | Stop `logos-api`, interact with UI | Graceful errors, no crashes, data sections show loading/empty |
| 7.2 | Visual surface disabled | `HAPAX_NO_VISUAL=1 pnpm tauri dev` | App launches, no visual surface, frame server returns 503 |
| 7.3 | Frame server port conflict | `HAPAX_VISUAL_HTTP_PORT=9999 pnpm tauri dev` | Server starts on :9999 (but VisualSurface still fetches :8053 — known limitation, document only) |
| 7.4 | Relay port conflict | `HAPAX_RELAY_PORT=9998 pnpm tauri dev` | Relay starts on :9998 |
| 7.5 | Rapid region switching | Mash `H F G W B` rapidly | No crashes, no stale data, UI keeps up |
| 7.6 | Long streaming session | Run a 60+ second agent run | Stream completes, no memory growth in DevTools |
| 7.7 | Multiple chat messages | Send 5+ messages in sequence | Each streams correctly, no orphaned streams |

## 8. Regression: Pre-existing Functionality

| # | Test | How | Pass |
|---|------|-----|------|
| 8.1 | All terrain regions render | Visit terrain page, check all 5 regions | Horizon, Field, Ground, Watershed, Bedrock all show content |
| 8.2 | Depth cycling works | Click or keyboard through depths | Surface → Stratum → Core for each region |
| 8.3 | Studio (ground core) | Navigate to ground core | Camera feeds, effect graph, compositor visible |
| 8.4 | Detection overlay | Press `D`, verify detections render | Detection boxes/labels overlay |
| 8.5 | Classification inspector | Press `C` | Heatmap inspector opens |
| 8.6 | HLS streams | Check camera feeds in studio | Live camera feeds playing |
| 8.7 | Hapax page | Navigate to `/hapax` | System anatomy renders |
| 8.8 | Chat page | Navigate to `/chat` | Chat interface loads, sessions list |
| 8.9 | Insight page | Navigate to `/insight` | Query interface loads |
| 8.10 | Flow page | Navigate to `/flow` | System flow diagram renders |
| 8.11 | Demo system | Navigate to demos | Demo list loads |
| 8.12 | Toast notifications | Trigger a toast (health degradation, etc.) | Toast appears and auto-dismisses |
| 8.13 | Modal system | Trigger introspection modal | Modal renders with content |
| 8.14 | Manual drawer | Press `?` | Manual content loads from markdown |
| 8.15 | URL params | Add `?region=ground&depth=core` to URL | Navigates directly to ground core |

---

## Quick Validation Sequence

For a fast sanity check (5 minutes), run these in order:

1. `pnpm tauri dev` — app launches
2. Terrain loads with data in all regions
3. Press `G` `G` `G` — ground cycles to core (studio)
4. Press `/` — investigation overlay opens
5. Type a chat message — response streams
6. Press `Esc` — returns to terrain
7. `curl http://127.0.0.1:8053/frame | file -` — JPEG response
8. Check for visual surface behind terrain regions
9. `echo '{"type":"list","id":"1"}' | websocat ws://127.0.0.1:8052` — command list returns
10. DevTools Network — zero requests to `:8051`, frames flowing from `:8053`
