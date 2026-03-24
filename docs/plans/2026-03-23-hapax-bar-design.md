# Hapax Bar — Design Document

**Date:** 2026-03-23
**Status:** Draft
**Scope:** Replace Waybar with a Python + Astal GTK4 status bar driven by the Logos API

---

## 1. Problem Statement

Waybar is a config-file bar. It polls shell scripts on fixed intervals and displays text. The Hapax ecosystem cannot:

- Push state into the bar (no inbound IPC)
- Dynamically add/remove/reorder modules
- React to system events in real time (health transitions, mode switches, agent activity)
- Apply design language tokens programmatically (CSS swap requires SIGUSR1 + full reload)
- Control bar behavior from agents (e.g., flash a module on critical health, show transient alerts)

The bar should be a **Logos-governed surface** — a Tier 1 interface that the system drives, not a passive consumer of script output.

## 2. Decision: Python + Astal Libraries via PyGObject

### Why Astal (not Fabric, not raw GTK4)

| Criterion | Astal + Python | Fabric | Raw GTK4 |
|---|---|---|---|
| GTK version | **4** (current) | 3 (maintenance) | 4 |
| Hyprland bindings | AstalHyprland (reactive, socket-based) | Own implementation | DIY |
| System services | Tray, Audio, Bluetooth, Network, MPRIS, Notifd — all as typelibs | Built-in but GTK3 | DIY |
| Language | Python (stack-native) | Python | Python |
| Layer shell | Astal.Window wraps gtk4-layer-shell | gtk-layer-shell (GTK3) | gtk4-layer-shell directly |
| Maturity risk | No tagged releases, bus-factor-1 | v0.0.2, bus-factor-1, flagship consumer archived | Stable (GTK upstream) |
| Arch packaging | 28 AUR packages, individually installable | pip/AUR | pacman (gtk4, gtk4-layer-shell) |

Astal gives us production-grade system service bindings (tray, audio, bluetooth, network, MPRIS, notifications) that would take weeks to reimplement. The Python path is confirmed viable — official examples in the Astal repo, 4+ third-party projects, and a dedicated `astal-py` bindings package.

### Risk: Astal has no stable release

Mitigation: Pin to a known-good commit via AUR package version or local build. The typelib interface is GObject Introspection, which is mechanically stable — breakage would require changing GIR namespaces, which is extremely unlikely for a library already shipping typelibs.

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      hapax-bar (Python)                      │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │ Astal    │  │ Astal    │  │ Astal    │  │ Logos API  │  │
│  │ Hyprland │  │ Wp/Audio │  │ Tray     │  │ Client     │  │
│  │ (typelib)│  │ (typelib)│  │ (typelib)│  │ (HTTP)     │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬──────┘  │
│       │              │              │              │          │
│  ┌────┴──────────────┴──────────────┴──────────────┴──────┐  │
│  │                   Widget Layer (GTK4)                   │  │
│  │    GObject.bind_property() + signal connections         │  │
│  └────────────────────────┬───────────────────────────────┘  │
│                           │                                  │
│  ┌────────────────────────┴───────────────────────────────┐  │
│  │              Astal.Window (gtk4-layer-shell)            │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │         Control Socket (Unix domain, JSON protocol)     │  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
    Hyprland IPC         PipeWire/WP         Logos API :8051
```

### 3.1 Process Model

- Single Python process, GLib main loop (`GLib.MainLoop`)
- One `Astal.Window` per display (HDMI-A-1, DP-1), anchored top, exclusive zone
- Astal service singletons (Hyprland, WirePlumber, Tray, Network, MPRIS) initialized once, shared across windows
- Logos API client polls endpoints on the same cadence as the API cache (30s fast, 5min slow)
- Control socket at `$XDG_RUNTIME_DIR/hapax-bar.sock` for inbound commands

### 3.2 Control Socket Protocol

JSON-over-Unix-socket. One JSON object per line. Enables agents, scripts, and `hapax-working-mode` to push state:

```json
{"cmd": "theme", "mode": "research"}
{"cmd": "flash", "module": "health", "duration_ms": 3000}
{"cmd": "toast", "text": "Deploy complete", "severity": "healthy", "duration_ms": 5000}
{"cmd": "set", "module": "custom.label", "text": "recording", "class": "critical"}
{"cmd": "refresh", "modules": ["health", "gpu"]}
{"cmd": "visibility", "module": "mpris", "visible": false}
```

### 3.3 Data Flow

| Data | Source | Mechanism | Cadence |
|---|---|---|---|
| Workspaces, active window, submap | Hyprland IPC | AstalHyprland signals (push) | Real-time |
| Volume, mic, audio devices | PipeWire | AstalWp signals (push) | Real-time |
| System tray | DBus | AstalTray signals (push) | Real-time |
| Network | NetworkManager | AstalNetwork signals (push) | Real-time |
| MPRIS (media) | DBus | AstalMpris signals (push) | Real-time |
| Health status | Logos API `/api/health` | HTTP poll | 30s |
| GPU | Logos API `/api/gpu` | HTTP poll | 30s |
| Working mode | Logos API `/api/working-mode` | HTTP poll + socket push | 5min / instant on switch |
| Docker containers | Logos API `/api/infrastructure` | HTTP poll | 30s |
| LLM cost | Logos API `/api/cost` | HTTP poll | 5min |
| CPU, memory, disk | `/proc`, `/sys` | `GLib.timeout_add()` poll | 3-5s |
| CPU temperature | hwmon sysfs | `GLib.timeout_add()` poll | 3s |
| Failed systemd units | `systemctl --user` | `GLib.timeout_add()` poll | 30s |

Key insight: 7 of 14 data sources are **real-time push** via Astal services. Waybar polled all of them.

## 4. Module Inventory

Replicate all 20 current waybar modules. Grouped by data source:

### Astal-native (real-time, signal-driven)

| Module | Astal Library | Waybar Equivalent |
|---|---|---|
| Workspaces | `AstalHyprland` | `hyprland/workspaces` |
| Active Window | `AstalHyprland` | `hyprland/window` |
| Submap | `AstalHyprland` | `hyprland/submap` |
| Volume | `AstalWp` | `pulseaudio` |
| Mic | `AstalWp` | `pulseaudio#mic` |
| Media (MPRIS) | `AstalMpris` | `mpris` |
| System Tray | `AstalTray` | `tray` |
| Network | `AstalNetwork` | `network` |

### Logos API (HTTP poll)

| Module | Endpoint | Current Script |
|---|---|---|
| Health Status | `/api/health` | `hapax-status.sh` |
| GPU | `/api/gpu` | `gpu-status.sh` |
| Working Mode | `/api/working-mode` | `working-mode.sh` |
| Docker | `/api/infrastructure` | `docker-status.sh` |
| Cost | `/api/cost` | (new, currently in hapax-status.sh tooltip) |

### Local System (sysfs/proc poll)

| Module | Source |
|---|---|
| CPU usage | `/proc/stat` |
| Memory | `/proc/meminfo` |
| Disk | `os.statvfs("/")` |
| CPU Temperature | `/sys/devices/pci0000:00/0000:00:18.3/hwmon/temp1_input` |
| Failed Units | `systemctl --user --state=failed` |

### Waybar-only (need Astal/GTK equivalent)

| Module | Replacement |
|---|---|
| Idle Inhibitor | `AstalHyprland` dispatch `dpms` + toggle state |
| Privacy Indicators | PipeWire node monitoring (camera/mic in use) |
| Clock | `GLib.timeout_add(60000)` + `datetime.now()` |

## 5. Theming

### 5.1 Design Language Compliance

Per `docs/logos-design-language.md` §11.1, the bar is a governed surface. Requirements:

- **Font:** JetBrains Mono (§1.6)
- **Colors:** CSS custom properties only, no hardcoded hex (§3)
- **Severity ladder:** green-400 / yellow-400 / orange-400 / red-400 / zinc-700 (§3.7)
- **Two palettes:** Gruvbox Hard Dark (R&D) and Solarized Dark (Research)

### 5.2 Implementation

Two CSS files (`hapax-bar-rnd.css`, `hapax-bar-research.css`) defining the same custom properties with different values. Theme switch is a single `app.apply_css(path)` call — no process restart, no signal hack.

```css
/* hapax-bar-rnd.css */
* {
    --bg-primary: #1d2021;
    --bg-secondary: #282828;
    --text-primary: #ebdbb2;
    --text-secondary: #a89984;
    --border: #3c3836;
    --green-400: #b8bb26;
    --yellow-400: #fabd2f;
    --orange-400: #fe8019;
    --red-400: #fb4934;
    --blue-400: #83a598;
    --zinc-700: #665c54;
}
```

### 5.3 Mode Switch Propagation

Current flow requires `killall -SIGUSR1 waybar` (full reload). New flow:

1. `hapax-working-mode` writes mode file + sends socket command to bar
2. Bar receives `{"cmd": "theme", "mode": "research"}`
3. Bar calls `app.apply_css("hapax-bar-research.css")`
4. All widgets re-render with new palette. No restart. Sub-second.

## 6. Click Handlers

All current waybar click actions preserved:

| Module | Click | Scroll |
|---|---|---|
| Workspaces | Switch to workspace | — |
| Working Mode | Toggle mode (calls `hapax-working-mode`) | — |
| Health Status | Open Logos app (`xdg-open http://localhost:8051`) | — |
| CPU | Open `foot -e htop` | — |
| Memory | Open `foot -e htop` | — |
| GPU | Open `foot -e nvtop` | — |
| Docker | Open `foot -e docker ps -a` | — |
| Volume | Toggle mute | ±2% volume |
| Mic | Toggle mute | ±2% volume |
| MPRIS | Play/pause | Next/prev track |
| Clock | Toggle date format | — |
| Idle Inhibitor | Toggle DPMS inhibit | — |

## 7. Multi-Monitor

Two bar instances, same as current waybar:

| Display | Workspaces | Modules |
|---|---|---|
| HDMI-A-1 (primary) | 1–5 | All 20 modules |
| DP-1 (secondary) | 11–15 | Subset: workspaces, submap, window, working-mode, health, gpu, cpu, memory, clock |

Each display gets its own `Astal.Window` with `gdkmonitor` targeting. Module visibility configured per-window.

## 8. Systemd Integration

```ini
# hapax-bar.service
[Unit]
Description=Hapax Status Bar (Astal/GTK4)
PartOf=graphical-session.target
After=logos-api.service

[Service]
Type=simple
ExecStart=/home/hapax/.local/bin/hapax-bar
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
```

Replace waybar exec in Hyprland config with `systemctl --user start hapax-bar.service`.

## 9. Fallback / Graceful Degradation

- If Logos API is unreachable: show last-known values with `[stale]` indicator, read `health-history.jsonl` as fallback (same as current waybar script)
- If Astal libraries not installed: fail to start with clear error message listing missing typelibs
- If Hyprland IPC unavailable: workspace/window modules show "—", other modules unaffected

## 10. File Layout

```
hapax-council/
├── hapax_bar/
│   ├── __init__.py
│   ├── __main__.py          # Entry point
│   ├── app.py                # Application + GLib main loop + socket server
│   ├── bar.py                # Window factory (per-monitor bar construction)
│   ├── modules/
│   │   ├── __init__.py
│   │   ├── workspaces.py     # AstalHyprland
│   │   ├── window_title.py   # AstalHyprland
│   │   ├── submap.py         # AstalHyprland
│   │   ├── audio.py          # AstalWp (volume + mic)
│   │   ├── mpris.py          # AstalMpris
│   │   ├── tray.py           # AstalTray
│   │   ├── network.py        # AstalNetwork
│   │   ├── health.py         # Logos API
│   │   ├── gpu.py            # Logos API
│   │   ├── working_mode.py   # Logos API + socket
│   │   ├── docker.py         # Logos API
│   │   ├── cost.py           # Logos API
│   │   ├── sysinfo.py        # CPU, memory, disk, temp (proc/sysfs)
│   │   ├── systemd.py        # Failed units
│   │   ├── clock.py          # GLib timer
│   │   ├── idle.py           # DPMS inhibit toggle
│   │   └── privacy.py        # PipeWire node monitoring
│   ├── logos_client.py       # Async HTTP client for Logos API
│   ├── socket_server.py      # Unix domain socket for inbound control
│   ├── theme.py              # CSS loading + mode switch
│   └── styles/
│       ├── hapax-bar-rnd.css
│       └── hapax-bar-research.css
├── systemd/units/
│   └── hapax-bar.service
```

Module entry point: `uv run python -m hapax_bar`

## 11. Dependencies

### System (pacman/paru)

```
gtk4 gtk4-layer-shell gobject-introspection
libastal-4-git libastal-io-git
libastal-hyprland-git libastal-wireplumber-git
libastal-tray-git libastal-network-git
libastal-mpris-git libastal-notifd-git
```

### Python (uv)

```
PyGObject>=3.50
pycairo
httpx          # async HTTP for Logos API polling
```

No external `astal-py` dependency. Write a thin ~100-line `reactive.py` in-tree providing `Variable`, `Binding`, and `astalify` constructor pattern. See §14 for rationale.

## 12. Migration Path

1. Build hapax-bar alongside waybar (both can run simultaneously for testing)
2. Validate module-by-module parity against waybar output
3. Smoke test with Playwright on a dedicated Hyprland workspace (not active workspace)
4. Switch Hyprland config from `exec-once = waybar` to `exec-once = systemctl --user start hapax-bar`
5. Keep waybar config intact for 2 weeks as rollback
6. Remove waybar config after confidence period

## 13. Future Capabilities (Not in Scope, But Enabled)

Once the bar is a Python process with a control socket:

- **Transient alerts:** agents push toasts to the bar (deploy status, voice pipeline state)
- **Dynamic modules:** show/hide modules based on context (e.g., show recording indicator only when compositor is active)
- **Agent activity:** real-time indicator when LLM agents are running
- **Stimmung integration:** bar color temperature shifts based on operator state
- **Notification center:** AstalNotifd integration for desktop notifications managed in the bar

---

## 14. Resolved Questions

### 14.1 `astal-py` vs raw PyGObject

**Decision: Write own ~100-line `reactive.py`.** The `astal-py` package (0x6e6174/astal-py) is dead — 0 stars, 1 author, 5 commits, dormant since March 2025, upstream PR was closed without merge. It has bugs (missing parens, consumed iterators, logic errors in controller wiring) and a fragile `ctypes.CDLL` hack for GTK4 child management. Astal's own official Python examples use raw PyGObject.

The useful patterns (Variable, Binding, astalify constructor) total ~80 lines of actual logic. We write these in-tree with proper typing and no external risk.

### 14.2 GTK4 CSS Variable Support

**Decision: Use standard `var(--name)` with `:root`.** GTK4 supports CSS custom properties since 4.16. Our system has GTK4 4.20.3. The syntax is identical to web CSS:

```css
:root {
    --bg-primary: #1d2021;
    --green-400: #b8bb26;
}
window { background: var(--bg-primary); }
```

The legacy `@define-color` / `@color` mechanism is deprecated since 4.16. Astal adds no CSS compilation layer — stylesheets go straight to GTK's CSS engine. No workarounds needed.

### 14.3 PipeWire Privacy Monitoring

**Decision: Use AstalWp — fully sufficient.** `AstalWpNode` has a `state` property (`RUNNING` = actively processing). `AstalWpVideo` provides `get_recorders()` (screenshare streams) with `recorder-added`/`recorder-removed` signals. `AstalWpStream` exposes `media_role` (CAMERA, SCREEN, COMMUNICATION) and application identity via `get_pw_property("application.name")`. No need for direct PipeWire/pw-cli access.

Implementation: watch `video.get_recorders()` and `audio.get_recorders()` for nodes with `state == RUNNING`. Show privacy indicator per active stream.

### 14.4 Hyprland Monitor Hotplug

**Decision: Fully supported.** `AstalHyprland` emits `monitor-added(Monitor)` and `monitor-removed(int id)` signals wired to Hyprland's `monitoraddedv2`/`monitorremoved` IPC events. Each `Monitor` object also has a `removed()` signal. Dynamic `Astal.Window` creation/destruction in response is straightforward.

Implementation: on startup, create bar windows for all current monitors. Connect to `monitor-added` to create new windows, `monitor-removed` to destroy them. Use monitor `name` property for targeting.

### 14.5 Performance Baseline

**Deferred to implementation.** Benchmark after the first working prototype. Waybar's idle footprint is ~15MB RSS / <0.5% CPU. If the GTK4+Python bar exceeds 50MB RSS or 1% idle CPU, investigate. GLib main loop with signal-driven updates (no polling for Astal-native modules) should be efficient.

---

## 15. Risk Register

| Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|
| Astal breaks API without semver | Medium | Medium | Pin AUR package to known-good commit; typelib interface is mechanically stable |
| GTK4 CSS property gaps vs web CSS | Low | Low | Confirmed working on GTK 4.20; `color-mix()` available for computed colors |
| PyGObject binding bugs for Astal typelibs | Low | Low | One known Vala GIR bug already patched upstream; 4+ projects prove the path |
| `gtk4-layer-shell` preload requirement | Low | Certain | `CDLL("libgtk4-layer-shell.so")` before GTK init; or use `Astal.Window` which wraps it |
| Bus-factor-1 on Astal | Medium | Medium | GObject typelib interface is stable even if upstream goes dormant; we consume libraries, not framework |
| Performance regression vs waybar | Low | Low | Benchmark during implementation; fallback to waybar if unacceptable |
