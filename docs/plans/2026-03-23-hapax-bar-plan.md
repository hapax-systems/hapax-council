# Hapax Bar — Implementation Plan

**Date:** 2026-03-23
**Design:** [hapax-bar-design.md](2026-03-23-hapax-bar-design.md)
**Branch:** `feat/hapax-bar`
**Worktree:** `hapax-council` (alpha session)

---

## Phasing Strategy

Five phases, each producing a testable artifact. Each phase is a PR-worthy batch. No phase depends on future work — every phase leaves the system in a working state.

---

## Phase 1: Skeleton + Core Bootstrap

**Goal:** A GTK4 window appears as a Wayland layer-shell bar with a clock and theme switching. Proves the Astal-from-Python path works.

### Prerequisites (one-time system setup)

```fish
paru -S libastal-4-git libastal-io-git gtk4-layer-shell gobject-introspection
```

### Tasks

1. **Create `hapax_bar/` directory structure:**
   ```
   hapax_bar/
   ├── __init__.py
   ├── __main__.py
   ├── app.py
   ├── bar.py
   ├── reactive.py
   ├── theme.py
   └── styles/
       ├── hapax-bar-rnd.css
       └── hapax-bar-research.css
   ```

2. **`reactive.py`** (~100 lines): Thin reactive wrapper providing:
   - `Variable(initial)` — value container with `get()`, `set()`, `subscribe()`, `poll(interval_ms, fn)`
   - `Binding(emitter, prop)` — GObject property wrapper with `.transform(fn)`, `.subscribe(cb)`
   - `bind(emitter, prop)` — shorthand constructor
   - All subscriptions auto-disconnect on widget destroy via `hook(widget, emitter, signal, cb)`

3. **`app.py`**: `Gtk.Application` subclass:
   - `CDLL("libgtk4-layer-shell.so")` in module scope
   - `do_command_line` override: init CSS, create bar windows, show
   - CSS via `Gtk.CssProvider` + `Gtk.StyleContext.add_provider_for_display()`
   - Read working mode from `~/.cache/hapax/working-mode` on startup → load correct CSS

4. **`bar.py`**: `Astal.Window` subclass:
   - `anchor = TOP | LEFT | RIGHT`, `exclusivity = EXCLUSIVE`
   - `Gtk.CenterBox` with left/center/right `Gtk.Box` containers
   - Clock label: `GLib.timeout_add(60_000)` updating `Gtk.Label`

5. **`theme.py`**: CSS loader:
   - `load_theme(mode: str)` — loads `styles/hapax-bar-{mode}.css`
   - `switch_theme(mode: str)` — replaces active CSS provider (no restart)
   - Read `~/.cache/hapax/working-mode` for initial mode

6. **CSS files**: Port current waybar styles to GTK4 CSS:
   - `:root` block with `var(--name)` custom properties
   - Base widget styles: font, spacing, padding
   - Severity classes: `.healthy`, `.degraded`, `.failed`, `.warning`, `.critical`
   - JetBrains Mono font

7. **`__main__.py`**: Entry point (`uv run python -m hapax_bar`)

8. **Test manually**: Run alongside waybar, verify bar appears, clock ticks, theme loads.

### Acceptance

- Bar renders on primary display with correct theme colors
- Clock shows current time, updates every minute
- `hapax-working-mode research` followed by socket command (Phase 4) or manual restart switches theme
- No crashes for 10 minutes idle

---

## Phase 2: Astal-Native Modules (Real-Time)

**Goal:** All signal-driven modules working. These are the modules where Astal gives us the biggest win over waybar (real-time vs polled).

### Prerequisites

```fish
paru -S libastal-hyprland-git libastal-wireplumber-git libastal-tray-git libastal-network-git libastal-mpris-git
```

### Tasks

1. **`modules/workspaces.py`**: `AstalHyprland`
   - Connect to `notify::workspaces` + `notify::focused-workspace`
   - Render workspace buttons (1-5 for HDMI-A-1, 11-15 for DP-1)
   - Click → `ws.focus()`
   - Active workspace highlighted (CSS class `.focused`)

2. **`modules/window_title.py`**: `AstalHyprland`
   - Bind `focused-client.title` to label
   - Max length truncation (60/50 chars per display)

3. **`modules/submap.py`**: `AstalHyprland`
   - Bind to `notify::submap` signal (note: verify exact property name)
   - Show `[{submap}]` when active, hide when empty

4. **`modules/audio.py`**: `AstalWp`
   - Speaker: bind `volume-icon` and `volume` to icon + label
   - Mic: same for default source
   - Click: toggle mute via `speaker.set_mute(not speaker.get_mute())`
   - Scroll: ±2% volume via `speaker.set_volume()`

5. **`modules/mpris.py`**: `AstalMpris`
   - Show first non-Firefox player
   - Bind artist + title
   - Click: `player.play_pause()`
   - Scroll: `player.next()` / `player.previous()`

6. **`modules/tray.py`**: `AstalTray`
   - `item-added` / `item-removed` signals
   - `Gtk.MenuButton` with `Gtk.PopoverMenu` from item menu model
   - Bind `gicon` for icon

7. **`modules/network.py`**: `AstalNetwork`
   - Bind based on `primary` (wired → IP, wifi → SSID)
   - Disconnected state

8. **`bar.py` update**: Wire all modules into CenterBox layout matching current waybar positions.

9. **Multi-monitor**: Create bar window per monitor. Use `Gdk.Display.get_default().get_monitors()` for initial enumeration. Connect to `AstalHyprland` `monitor-added`/`monitor-removed` for hotplug.

### Acceptance

- All 8 Astal modules render and update in real-time
- Workspace clicks switch workspace
- Volume scroll changes system volume
- Tray icons appear and menus open
- Both monitors have bars with correct workspace ranges

---

## Phase 3: System + API Modules (Polled)

**Goal:** All remaining modules — local system stats and Logos API consumers.

### Tasks

1. **`logos_client.py`**: HTTP client for Logos API
   - Uses `urllib.request` (no httpx needed — simpler, no async in GLib loop)
   - `poll_endpoint(url, interval_ms, callback)` — wraps `GLib.timeout_add()`
   - Fallback: if API unreachable, read `profiles/health-history.jsonl`
   - Parses `X-Cache-Age` header for staleness detection

2. **`modules/health.py`**: `/api/health`
   - Display `{healthy}/{total}` with severity class
   - Click: `xdg-open http://localhost:8051`
   - Tooltip with failed check names (GTK4 tooltip on hover)

3. **`modules/gpu.py`**: `/api/gpu`
   - Display `[gpu:{temp}°C {mem_gb}G]`
   - Severity classes based on VRAM thresholds
   - Click: `foot -e nvtop`

4. **`modules/working_mode.py`**: `/api/working-mode`
   - Display `[R&D]` or `[RES]`
   - Click: call `hapax-working-mode` to toggle
   - Also responds to socket push for instant switch (Phase 4)

5. **`modules/docker.py`**: `/api/infrastructure`
   - Display `[dock:{count}]`
   - Click: `foot -e docker ps -a`

6. **`modules/cost.py`**: `/api/cost`
   - Display today's LLM cost in tooltip or as module

7. **`modules/sysinfo.py`**: Local proc/sysfs
   - CPU: read `/proc/stat`, calculate usage %, `GLib.timeout_add(3000)`
   - Memory: read `/proc/meminfo`, calculate %
   - Disk: `os.statvfs("/")`
   - Temperature: read hwmon sysfs path
   - Click handlers: `foot -e htop`

8. **`modules/systemd.py`**: Failed units
   - `subprocess.run(["systemctl", "--user", "--state=failed", "--no-pager", "-q"])`
   - `GLib.timeout_add(30_000)`
   - Show count if > 0, hide otherwise

9. **`modules/clock.py`**: Already exists from Phase 1, enhance:
   - Click toggles between `%H:%M` and `%Y-%m-%d %H:%M:%S`
   - Tooltip: calendar (use `Gtk.Calendar` in a `Gtk.Popover`)

10. **`modules/idle.py`**: DPMS inhibit toggle
    - Track state boolean
    - Click: `hyprctl dispatch dpms on/off` or use Astal Hyprland command dispatch

11. **`modules/privacy.py`**: PipeWire active streams
    - `AstalWp.get_default().get_video().get_recorders()` for camera/screenshare
    - `AstalWp.get_default().get_audio().get_recorders()` for mic
    - Watch `state` property for `RUNNING`
    - Show indicator icon when active

### Acceptance

- All 20 modules rendering (feature parity with waybar)
- API modules show live data, fall back gracefully when API is down
- Click handlers all work
- System stats update at correct intervals

---

## Phase 4: Control Socket + Integration

**Goal:** External processes can push state into the bar. Wire into existing ecosystem scripts.

### Tasks

1. **`socket_server.py`**: Unix domain socket server
   - Path: `$XDG_RUNTIME_DIR/hapax-bar.sock`
   - JSON-line protocol (one JSON object per `\n`)
   - Commands:
     - `{"cmd": "theme", "mode": "research|rnd"}` → `theme.switch_theme()`
     - `{"cmd": "refresh", "modules": ["health", "gpu"]}` → force re-poll
     - `{"cmd": "flash", "module": "health", "duration_ms": 3000}` → add+remove CSS class
     - `{"cmd": "toast", "text": "...", "severity": "...", "duration_ms": 5000}` → transient label
     - `{"cmd": "visibility", "module": "mpris", "visible": false}` → show/hide module
   - Uses `Gio.SocketService` or `Gio.ThreadedSocketService` (GLib-native, no threading issues)

2. **`hapax-working-mode` script update**: After mode switch, send socket command:
   ```fish
   echo '{"cmd":"theme","mode":"'$mode'"}' | socat - UNIX-CONNECT:$XDG_RUNTIME_DIR/hapax-bar.sock
   ```
   Remove `killall -SIGUSR1 waybar` line.

3. **`health-watchdog` script update**: After health check completes, send refresh:
   ```fish
   echo '{"cmd":"refresh","modules":["health"]}' | socat - UNIX-CONNECT:$XDG_RUNTIME_DIR/hapax-bar.sock
   ```

4. **CLI helper**: `hapax-bar-ctl` — thin wrapper for socket commands:
   ```fish
   hapax-bar-ctl theme research
   hapax-bar-ctl flash health 3000
   hapax-bar-ctl toast "Deploy complete" healthy 5000
   ```

### Acceptance

- `echo '{"cmd":"theme","mode":"research"}' | socat - UNIX:$XDG_RUNTIME_DIR/hapax-bar.sock` switches theme instantly
- `hapax-working-mode research` switches bar theme (no restart)
- Health refresh pushed after health-watchdog runs
- Flash command adds CSS animation class temporarily

---

## Phase 5: Systemd + Migration

**Goal:** Replace waybar with hapax-bar in production.

### Tasks

1. **Systemd unit**: `systemd/units/hapax-bar.service`
   ```ini
   [Unit]
   Description=Hapax Status Bar (Astal/GTK4)
   PartOf=graphical-session.target
   After=logos-api.service

   [Service]
   Type=simple
   ExecStart=%h/.local/bin/hapax-bar
   Restart=on-failure
   RestartSec=2
   SuccessExitStatus=SIGTERM

   [Install]
   WantedBy=graphical-session.target
   ```

2. **Entry point script**: `~/.local/bin/hapax-bar`
   ```bash
   #!/bin/bash
   cd ~/projects/hapax-council
   exec uv run python -m hapax_bar "$@"
   ```

3. **Hyprland config update**: Replace `exec-once = waybar` with `exec-once = systemctl --user start hapax-bar`

4. **Install + enable**:
   ```fish
   bash systemd/scripts/install-units.sh
   systemctl --user enable hapax-bar.service
   ```

5. **Smoke test with Playwright**: On a dedicated Hyprland workspace (not active workspace), verify:
   - Bar renders correctly
   - All modules show data
   - Theme switch works
   - Click handlers work
   - No visual regressions vs waybar

6. **Cutover**: Stop waybar, start hapax-bar, verify for 1 hour. Keep waybar config for 2-week rollback window.

7. **Update health monitor**: Add `systemd.hapax-bar` check (process running). Remove any waybar-specific health checks if they exist.

### Acceptance

- hapax-bar starts on login via systemd
- Survives logout/login cycle
- All functionality matches or exceeds waybar
- Rollback to waybar possible within 60 seconds

---

## Dependency Graph

```
Phase 1 (skeleton)
    │
    ├── Phase 2 (astal modules)
    │       │
    │       └── Phase 3 (system + API modules)
    │               │
    │               ├── Phase 4 (control socket)
    │               │
    │               └── Phase 5 (systemd + migration)
    │
    └── [can start Phase 4 socket server alongside Phase 2]
```

Phases 2 and 3 can be partially interleaved (add modules as Astal packages are installed). Phase 4 socket server can start as early as Phase 1 since it's independent of module content.

---

## Estimated Scope

| Phase | Files | New Lines (est.) |
|---|---|---|
| 1 | 7 files | ~400 |
| 2 | 8 module files + bar.py update | ~600 |
| 3 | 10 module files + logos_client.py | ~700 |
| 4 | socket_server.py + 3 script updates + CLI | ~250 |
| 5 | 1 service file + 1 script + config updates | ~50 |
| **Total** | **~30 files** | **~2,000 lines** |

---

## Notes

- **No Blueprint/Meson.** The Astal GTK4 example uses Blueprint `.blp` files and Meson for building. We skip this entirely — widgets built imperatively in Python, CSS loaded from file. This avoids a build step and keeps the bar as a simple `uv run` module.
- **No `astal-py`.** We write our own `reactive.py` (~100 lines). The external package is dead (0 stars, unmaintained, bugs, upstream PR rejected).
- **No `httpx`.** `urllib.request` is sufficient for simple GET polling on `GLib.timeout_add`. Keeps dependencies minimal.
- **GTK4 imperative widgets.** The GTK3 Astal example proves imperative widget construction works well. We use standard `Gtk.Box`, `Gtk.Label`, `Gtk.Button`, `Gtk.Image`, `Gtk.CenterBox` — no custom widget subclasses needed except for the bar window itself.
