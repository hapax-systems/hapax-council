# KDE Plasma Environment Overhaul

**Date:** 2026-05-16
**Status:** Approved
**Scope:** 10 independent DE improvements — config changes, package installs, 2 scripts

## Context

Operator runs KDE Plasma 6.6.5 (KWin Wayland) on CachyOS with dual monitors (DP-1 2560x1440@165Hz, DP-2 1920x1200@60Hz). Workload: 15 tmux sessions (6 Claude, 8 Codex, 1 work), OBS livestream, hapax-logos visual surface, Chrome, Dolphin, 20 Docker containers, GPU inference. 24/7 uptime with auto-reboot on panic. Two working modes (R&D/Research) with distinct color palettes (Gruvbox/Solarized).

Current state: zero window rules, zero KWin scripts, one Activity, default panel widgets, no notification management, PlasmaZones manual tiling, session restore disabled, Klipper unconfigured, KDE Connect minimally used.

## 1. KWin Window Rules

File: `~/.config/kwinrulesrc`

| App | Desktop | Monitor | Behavior |
|-----|---------|---------|----------|
| Konsole | 1 | DP-1 | Normal placement |
| foot | 1 | DP-1 | Normal placement |
| Chrome | 2 | DP-1 | Normal placement |
| OBS | 3 | DP-2 | Skip taskbar, no close on exit |
| hapax-logos | 1 | DP-1 | Fullscreen, above |
| Dolphin | 2 | DP-2 | Normal placement |
| Spectacle | All | — | All desktops, keep above |

Rules use `wmclass` matching. Force placement on first appearance only.

## 2. Yakuake

Install `yakuake` via pacman. Configure:
- Hotkey: F12
- Font: JetBrains Mono Nerd Font 11pt
- Colorscheme: Gruvbox Dark
- Default command: `tmux attach -t work || tmux new -s work`
- Width: 100%, height: 60%
- Autostart: add to `~/.config/autostart/`

## 3. Polonium Auto-Tiling (replaces PlasmaZones)

Install `kwin-polonium` from AUR. Remove PlasmaZones:
- `systemctl --user stop plasmazones.service`
- `systemctl --user disable plasmazones.service`
- Remove plasmazones KWin plugin

Polonium config (`~/.config/kwinrc` `[Script-polonium]`):
- Default layout: three-column (25/50/25)
- Tile popup dialogs: false
- Inner/outer gaps: 4px
- Filter: exclude OBS, Spectacle, KRunner, polkit

## 4. Notification Management

File: `~/.config/plasmanotifyrc`

- Enable notification history, retain 100 entries
- Per-app rules:
  - `LLM Stack`: suppress below `critical` urgency
  - `OBS`: suppress entirely (visual feedback sufficient)
- DND shortcut: `Meta+Shift+N` via `~/.config/kglobalshortcutsrc`
- Auto-DND during livestream: extend `hapax-working-mode` to toggle inhibit via `qdbus6 org.freedesktop.Notifications /org/freedesktop/Notifications org.freedesktop.Notifications.Inhibit`

## 5. KWin Lane-Focus Script

KWin script at `~/.local/share/kwin/scripts/hapax-lane-focus/`:
- Reads Konsole window titles to identify tmux session names
- `Meta+1` through `Meta+6`: focus all windows belonging to alpha/beta/gamma/delta/epsilon/zeta lane
- Implementation: KWin scripting API (`workspace.windowList()`, filter by `caption` regex)

## 6. KDE Activities (R&D / Research)

Create two Activities via `qdbus6 org.kde.ActivityManager`:
- **R&D**: Gruvbox palette, `#1d2021` solid wallpaper
- **Research**: Solarized palette, `#002b36` solid wallpaper

Extend `hapax-working-mode` script to:
1. Switch KDE Activity via D-Bus
2. Apply per-activity Plasma theme (panel accent colors)

Each activity maintains its own window set automatically (KDE native behavior).

## 7. Panel Optimization

Modify `~/.config/plasma-org.kde.plasma.desktop-appletsrc`:
- Remove: `org.kde.plasma.battery` (desktop, no battery)
- Add: `org.kde.plasma.systemmonitor.cpu` (compact CPU graph)
- Add: `org.kde.plasma.systemmonitor.memory` (compact RAM gauge)
- Keep all existing systray items

GPU monitoring: use existing `nvidia-smi` alias + system tray tooltip (no widget available for NVIDIA GPU in Plasma).

## 8. Startup Recovery

Systemd user unit `hapax-desktop-recovery.service` (Type=oneshot, After=plasma-core.target):
- Wait for KWin ready via D-Bus
- Launch: Konsole with `work` tmux, Chrome, hapax-logos
- Idempotent: skip if windows already exist

## 9. Clipboard History (Klipper)

File: `~/.config/klipperrc`
- History size: 500
- Enable image support
- Bind `Meta+V` to clipboard history popup
- Sync selection and clipboard

## 10. KDE Connect Enhancement

Via `kdeconnect-cli` and KDE Connect settings:
- Enable notification sync: critical desktop notifications → phone
- Enable clipboard sync: bidirectional
- Configure run-command plugin:
  - `toggle-livestream`: triggers OBS scene switch
  - `toggle-dnd`: toggles Do Not Disturb
- Route `notify-send --urgency=critical` notifications to phone via KDE Connect notification forwarding

## Implementation Order

1. Package installs (yakuake, kwin-polonium)
2. Remove PlasmaZones
3. Window rules
4. Polonium config
5. Yakuake config
6. Notification management
7. Panel optimization
8. Clipboard config
9. Activities setup
10. KWin lane-focus script
11. Startup recovery service
12. KDE Connect config

## Risk

- Polonium may conflict with remaining PlasmaZones config — clean removal first
- Activity switching resets window placement — window rules compensate
- KWin script API surface is limited — lane-focus may need fallback to `xdotool` via Xwayland
