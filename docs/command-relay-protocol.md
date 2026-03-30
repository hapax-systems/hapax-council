# Command Relay Protocol

WebSocket endpoint: `ws://127.0.0.1:8052/ws/commands`

Rust server in `hapax-logos/src-tauri/src/commands/relay.rs`. Bridges external clients (MCP, voice, automation scripts) to the Logos command registry inside the Tauri webview.

## Execute a command

```json
{"type": "execute", "id": "unique-id", "command": "terrain.focus", "args": {"region": "ground", "depth": "core"}}
```

**Required fields:**
- `type`: `"execute"` (also supports `"query"`, `"list"`)
- `id`: unique string for response correlation
- `command`: registered command path (see table below)
- `args`: command-specific arguments object

**Response:**
```json
{"id": "unique-id", "ok": true}
```

## Subscribe to events

```json
{"type": "subscribe", "id": "sub-1", "pattern": "terrain.*"}
```

Pattern uses glob syntax (`*` = any). Events matching the pattern are forwarded to the client.

## Unsubscribe

```json
{"type": "unsubscribe", "id": "sub-1"}
```

## Common commands

| Command | Args | Description |
|---------|------|-------------|
| `terrain.focus` | `{region, depth?}` | Focus region. With `depth`: set directly. Without: cycle surface→stratum→core. |
| `split.open` | `{region}` | Open split view with detail pane for region |
| `split.close` | `{}` | Close split view |
| `split.fullscreen` | `{}` | Toggle split fullscreen mode |
| `overlay.set` | `{name}` | Open overlay by name (`"investigation"`, `"voice"`) |
| `overlay.clear` | `{}` | Close active overlay |
| `overlay.toggle` | `{name}` | Toggle overlay |
| `detection.toggle` | `{}` | Toggle detection overlay visibility |
| `detection.tier` | `{tier}` | Set detection tier (1, 2, or 3) |
| `studio.preset` | `{name}` | Activate effect preset by name |
| `nav.page` | `{page}` | Navigate to page |

## Regions and depths

**Regions:** `horizon`, `field`, `ground`, `watershed`, `bedrock`

**Depths:** `surface` (default), `stratum` (expanded), `core` (immersive)

## Overlay names

- `investigation` — Chat, insight query, demos tabs
- `voice` — Voice interaction overlay (auto-shown when voice active)

## Timeout

Commands time out after 5 seconds if the frontend doesn't respond. The relay returns:
```json
{"id": "unique-id", "ok": false, "error": "timeout: no response from frontend"}
```

## Example: Python client

```python
import asyncio, json, websockets

async def set_ground_core():
    async with websockets.connect("ws://127.0.0.1:8052/ws/commands") as ws:
        await ws.send(json.dumps({
            "type": "execute",
            "id": "1",
            "command": "terrain.focus",
            "args": {"region": "ground", "depth": "core"}
        }))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(resp)

asyncio.run(set_ground_core())
```
