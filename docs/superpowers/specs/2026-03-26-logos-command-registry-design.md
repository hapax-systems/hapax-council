# Logos Command Registry

A centralized, hierarchical command registry for the Logos frontend. Every action — focusing a region, activating a preset, toggling an overlay — is a registered command with typed arguments, return values, and observable events. All input surfaces (keyboard, clicks, Playwright, MCP, voice) are thin adapters over the same dispatch.

## Architecture

```
┌─────────────┐  ┌───────────┐  ┌──────────┐  ┌───────────┐
│  Keyboard   │  │ Playwright│  │   MCP     │  │   Voice   │
│  Adapter    │  │ (window.  │  │ (WS via   │  │ (WS via   │
│             │  │  __logos)  │  │ :8051)    │  │ :8051)    │
└──────┬──────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
       │               │              │               │
       └───────────────┴──────┬───────┴───────────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Command Registry  │
                    │                    │
                    │  execute(path, args) → result
                    │  query(path) → value
                    │  list(domain?) → commands[]
                    │  subscribe(pattern, cb)
                    │  sequences registry
                    └─────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
        ┌─────▼─────┐  ┌─────▼─────┐  ┌──────▼──────┐
        │  Terrain   │  │  Studio   │  │  Overlay    │  ...
        │  Domain    │  │  Domain   │  │  Domain     │
        └───────────┘  └───────────┘  └─────────────┘
```

All consumers call the same `execute()`. The registry lives in React context and is exposed as `window.__logos` for programmatic access. Playwright uses `window.__logos` directly (zero latency). External consumers (MCP, voice) use a WebSocket relay through the Logos API.

## Core API

```typescript
interface ArgDef {
  type: "string" | "number" | "boolean";
  required?: boolean;
  enum?: string[];
  description?: string;
}

interface CommandResult {
  ok: boolean;
  error?: string;
  state?: unknown;  // post-execution state snapshot, command-specific
}

interface CommandDef {
  path: string;
  description: string;
  args?: Record<string, ArgDef>;
  execute: (args: Record<string, unknown>) => CommandResult | Promise<CommandResult>;
  query?: () => unknown;
}

interface CommandEvent {
  path: string;
  args: Record<string, unknown>;
  result: CommandResult;
  timestamp: number;
  source?: string;  // "keyboard" | "playwright" | "ws" | "palette" | "click"
}

interface LogosAPI {
  execute(path: string, args?: Record<string, unknown>): Promise<CommandResult>;
  query(path: string): unknown;
  list(domain?: string): CommandDef[];
  subscribe(pattern: string | RegExp, cb: (event: CommandEvent) => void): () => void;
  getState(): Record<string, unknown>;
  debug: boolean;
}
```

## Command Domains

Each domain is a hook that registers commands with the registry on mount. Domains own their state — the registry routes to them.

### terrain — region focus, depth, grid layout

| Command | Args | Description |
|---------|------|-------------|
| `terrain.focus` | `{ region: RegionName \| null }` | Focus a region (cycles depth if already focused) or unfocus |
| `terrain.depth.set` | `{ region: RegionName, depth: "surface" \| "stratum" \| "core" }` | Set specific depth |
| `terrain.depth.cycle` | `{ region: RegionName }` | Cycle surface → stratum → core |
| `terrain.collapse` | none | Reset all regions to surface, unfocus |

Queries: `terrain.focusedRegion`, `terrain.depths`, `terrain.coreMiddle`

### studio — camera/effects controls

| Command | Args | Description |
|---------|------|-------------|
| `studio.smooth.enable` | none | Enable smooth/HLS mode |
| `studio.smooth.disable` | none | Disable smooth/HLS mode |
| `studio.smooth.toggle` | none | Toggle smooth/HLS mode |
| `studio.preset.activate` | `{ name: string }` | Activate a named preset |
| `studio.preset.cycle` | `{ direction: "next" \| "prev" }` | Cycle to next/previous preset |
| `studio.recording.toggle` | none | Toggle recording (server-side) |

Queries: `studio.smoothMode`, `studio.activePreset`, `studio.recording`

### overlay — investigation, voice, classification inspector

| Command | Args | Description |
|---------|------|-------------|
| `overlay.set` | `{ name: string }` | Set active overlay |
| `overlay.clear` | none | Clear active overlay |
| `overlay.toggle` | `{ name: string }` | Toggle a specific overlay |

Queries: `overlay.active`

### detection — classification tier and visibility

| Command | Args | Description |
|---------|------|-------------|
| `detection.tier.set` | `{ tier: 1 \| 2 \| 3 }` | Set detection tier |
| `detection.tier.cycle` | none | Cycle tier 1 → 2 → 3 → 1 |
| `detection.visibility.toggle` | none | Toggle detection layer visibility |

Queries: `detection.tier`, `detection.visible`

### nav — page navigation

| Command | Args | Description |
|---------|------|-------------|
| `nav.go` | `{ path: string }` | Navigate to route |
| `nav.manual.toggle` | none | Toggle operations manual |
| `nav.palette.toggle` | none | Toggle command palette |

Queries: `nav.currentPath`

### split — split pane control

| Command | Args | Description |
|---------|------|-------------|
| `split.open` | `{ region: RegionName }` | Open split pane for region |
| `split.close` | none | Close split pane |
| `split.toggle` | `{ region?: RegionName }` | Toggle split (uses focused region if omitted) |
| `split.fullscreen.toggle` | none | Toggle split fullscreen |

Queries: `split.region`, `split.fullscreen`

### data — query refresh

| Command | Args | Description |
|---------|------|-------------|
| `data.refresh` | `{ key?: string }` | Invalidate all or specific queries |

## Sequences

Named sequences are registered alongside atomic commands. They execute in order, waiting for React state to settle between steps.

```typescript
registry.sequence("studio.enter", [
  { command: "terrain.focus", args: { region: "ground" } },
  { command: "terrain.depth.set", args: { region: "ground", depth: "core" } },
  { command: "studio.smooth.enable" },
]);

registry.sequence("studio.exit", [
  { command: "studio.smooth.disable" },
  { command: "terrain.collapse" },
]);

registry.sequence("escape", [
  // Hierarchical dismiss — first successful step stops the chain
  // overlay.clear → split.close → terrain depth collapse → terrain.focus(null)
]);
```

Sequences appear in `list()` and are executable via `execute("studio.enter")`. They return the result of the last executed step, or the first failure.

**State settling:** Between steps, `await new Promise(r => setTimeout(r, 0))` lets React process state updates. Individual steps can specify `settle: <ms>` for longer waits if needed.

**Early exit:** Sequences support `{ stopOnSuccess: true }` for priority-chain patterns (like Escape, where the first successful step should end the sequence).

## Keyboard Adapter

A single `useKeyboardAdapter` hook replaces all 6+ scattered `addEventListener("keydown")` handlers. It maps key combinations to command paths:

```typescript
interface KeyBinding {
  key: string;
  modifiers?: { ctrl?: boolean; shift?: boolean; alt?: boolean; meta?: boolean };
  command: string;
  args?: Record<string, unknown>;
  when?: string;  // condition query path — binding only active when truthy
}

const KEY_MAP: KeyBinding[] = [
  { key: "h", command: "terrain.focus", args: { region: "horizon" } },
  { key: "f", command: "terrain.focus", args: { region: "field" } },
  { key: "g", command: "terrain.focus", args: { region: "ground" } },
  { key: "w", command: "terrain.focus", args: { region: "watershed" } },
  { key: "b", command: "terrain.focus", args: { region: "bedrock" } },
  { key: "/", command: "overlay.toggle", args: { name: "investigation" } },
  { key: "Escape", command: "escape" },
  { key: "s", command: "split.toggle" },
  { key: "d", command: "detection.tier.cycle" },
  { key: "D", modifiers: { shift: true }, command: "detection.visibility.toggle" },
  { key: "e", command: "studio.smooth.toggle", when: "terrain.focusedRegion=ground" },
  { key: "r", command: "studio.recording.toggle", when: "terrain.focusedRegion=ground" },
  { key: "[", command: "studio.preset.cycle", args: { direction: "prev" }, when: "terrain.focusedRegion=ground" },
  { key: "]", command: "studio.preset.cycle", args: { direction: "next" }, when: "terrain.focusedRegion=ground" },
  { key: "?", command: "nav.manual.toggle" },
  { key: "c", command: "nav.go", args: { path: "/chat" } },
  { key: "i", command: "nav.go", args: { path: "/insight" } },
  { key: "r", command: "data.refresh" },
];
```

The `when` clause uses the query system — `when: "terrain.focusedRegion=ground"` means the binding only fires if `query("terrain.focusedRegion") === "ground"`. Bindings earlier in the list take priority when multiple match the same key. This enables context-dependent overrides: e.g., `r` maps to `studio.recording.toggle` (when ground focused) and falls through to `data.refresh` otherwise.

The adapter respects input focus (INPUT, TEXTAREA, contentEditable) as the current handlers do, but in one place.

## Playwright / Direct Access

```typescript
// window.__logos — available in dev and production
await window.__logos.execute("terrain.focus", { region: "ground" });
await window.__logos.execute("studio.preset.activate", { name: "ghost" });

// State queries
window.__logos.query("terrain.focusedRegion");  // "ground"
window.__logos.query("studio.smoothMode");       // false
window.__logos.getState();                        // full state tree

// Discovery
window.__logos.list("terrain");
// [{ path: "terrain.focus", description: "Focus a region or unfocus", args: {...} }, ...]

// Observe
const unsub = window.__logos.subscribe(/studio\./, (e) => console.log(e));

// Debug mode
window.__logos.debug = true;  // logs all events to console
```

## WebSocket Relay

New endpoint on Logos API: `ws://localhost:8051/ws/commands`

### Protocol

JSON messages, bidirectional.

**Client → Server:**
```json
{ "type": "execute", "id": "uuid-1", "path": "terrain.focus", "args": { "region": "ground" } }
{ "type": "query", "id": "uuid-2", "path": "terrain.focusedRegion" }
{ "type": "list", "id": "uuid-3", "domain": "terrain" }
{ "type": "subscribe", "id": "uuid-4", "pattern": "studio.*" }
{ "type": "unsubscribe", "id": "uuid-4" }
```

**Server → Client:**
```json
{ "type": "result", "id": "uuid-1", "data": { "ok": true, "state": "ground" } }
{ "type": "event", "subscription": "uuid-4", "path": "studio.preset.activate", "args": { "name": "ghost" }, "result": { "ok": true }, "timestamp": 1711468800000 }
```

### Relay Implementation

The FastAPI backend is a dumb pipe:
1. Frontend connects to `ws://localhost:8051/ws/commands` on boot and maintains the connection.
2. External clients also connect to the same endpoint.
3. Backend forwards external client messages to the frontend WS connection.
4. Frontend processes commands via the registry and sends results back.
5. Backend routes results back to the originating external client by `id`.
6. Subscription events are forwarded to external clients that subscribed to matching patterns.

The backend holds no command state and interprets no commands. If the frontend WS is not connected, external commands return `{ ok: false, error: "frontend not connected" }`.

## UI Feedback

A `CommandFeedback` component subscribes to the event bus:
- **Failures:** Transient toast with error message (e.g., `terrain.focus: invalid region "foo"`). Auto-dismiss after 3s.
- **Success:** Silent by default.
- **Debug mode:** All events logged to browser console with timestamps.

The CommandPalette reads its command list from `registry.list()` instead of maintaining a hardcoded list. Search, fuzzy matching, and execution all route through the registry.

## File Structure

### New files

```
src/lib/commandRegistry.ts          — Core registry class (framework-agnostic)
src/contexts/CommandRegistryContext.tsx — React context + provider + window.__logos binding
src/lib/commands/terrain.ts          — Terrain domain registration
src/lib/commands/studio.ts           — Studio domain registration
src/lib/commands/overlay.ts          — Overlay domain registration
src/lib/commands/detection.ts        — Detection domain registration
src/lib/commands/nav.ts              — Nav domain registration
src/lib/commands/split.ts            — Split domain registration
src/lib/commands/data.ts             — Data domain registration
src/lib/commands/sequences.ts        — Built-in sequence definitions
src/lib/keyboardAdapter.ts           — Single keyboard handler + key map
src/lib/commandRelay.ts              — WebSocket client for relay connection
src/components/terrain/CommandFeedback.tsx — Toast feedback component
```

### Deleted code

- All `useEffect` keyboard handlers in TerrainLayout (handleKey, DetectionKeyboardHandler, StudioKeyboardHandler)
- `useKeyboardShortcuts.ts` hook
- `useStudioShortcuts.ts` hook
- HapaxPage keyboard handler
- Inline command list in CommandPalette.tsx

### Modified files

- `CommandPalette.tsx` — reads from `registry.list()` instead of hardcoded array
- `TerrainLayout.tsx` — removes keyboard handlers, adds `CommandFeedback`
- `App.tsx` or layout root — wraps with `CommandRegistryProvider`
- Backend: new WS endpoint in Logos API routes

### Unchanged

- All React state management (TerrainContext, GroundStudioContext, ClassificationOverlayContext)
- Backend API endpoints (presets, recording, camera control)
- Visual layout, components, rendering
- KeyboardHintBar (updated to reflect current bindings via registry)
