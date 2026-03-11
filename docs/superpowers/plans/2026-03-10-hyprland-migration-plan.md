# Hyprland Migration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate desktop environment from COSMIC to Hyprland with the "Terminal Sublime" aesthetic, preserving all system services (WiFi, BT, audio, video), and updating the voice daemon for Hyprland compatibility.

**Architecture:** Install Hyprland + ecosystem via PPA, write config files per the aesthetic design spec, mask conflicting COSMIC portal, update voice daemon references (cosmic-screenshot to grim, cosmic-term to foot), verify all hardware/network services.

**Tech Stack:** Hyprland (compositor), waybar (bar), foot (terminal), mako (notifications), hyprlock/hypridle (lock/idle), fuzzel (launcher), grim/slurp (screenshots), hyprpaper (wallpaper), tmux (terminal management), JetBrainsMono Nerd Font

**Reference Specs:**
- Aesthetic: `docs/superpowers/specs/2026-03-10-hyprland-aesthetic-design.md`
- Capabilities: `~/projects/distro-work/docs/hyprland-migration-capabilities.md`

---

## Chunk 1: System Installation

### Task 1: Install Hyprland and Ecosystem Packages

**Files:**
- None (system package installation)

- [ ] **Step 1: Add Hyprland PPA**

```bash
sudo add-apt-repository ppa:cppiber/hyprland
sudo apt update
```

Expected: PPA added, package list updated. This PPA provides Hyprland 0.54.x built with gcc-15 (Pop!_OS stock gcc-13 is insufficient for Hyprland's C++26 requirement).

- [ ] **Step 2: Install Hyprland core + ecosystem**

```bash
sudo apt install hyprland hyprlock hypridle xdg-desktop-portal-hyprland hyprpaper
```

Expected: Compositor, lock screen, idle manager, XDG portal, wallpaper daemon installed.

- [ ] **Step 3: Install desktop tools**

```bash
sudo apt install waybar foot mako-notifier grim slurp wf-recorder \
  cliphist wlogout playerctl brightnessctl xdg-desktop-portal-gtk
```

Expected: Status bar, terminal, notifications, screenshot tools, clipboard history, utilities installed. fuzzel is already installed.

- [ ] **Step 4: Install JetBrainsMono Nerd Font**

```bash
mkdir -p ~/.local/share/fonts
cd /tmp
curl -fLO https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.tar.xz
tar xf JetBrainsMono.tar.xz -C ~/.local/share/fonts/
fc-cache -fv
```

Expected: `fc-list | grep JetBrainsMono` shows multiple font variants.

- [ ] **Step 5: Install tray applets for WiFi and Bluetooth**

```bash
sudo apt install network-manager-gnome blueman
```

Expected: `nm-applet` and `blueman-applet` available for Waybar systray. NetworkManager and BlueZ are already running as system-level daemons. Saved WiFi networks (in `/etc/NetworkManager/system-connections/`) and paired BT devices (in `/var/lib/bluetooth/`) persist across DE switches.

- [ ] **Step 6: Mask COSMIC XDG portal to prevent conflicts**

```bash
systemctl --user mask xdg-desktop-portal-cosmic.service
```

Expected: COSMIC's portal won't compete with Hyprland's portal, which would cause 30-second app launch timeouts.

- [ ] **Step 7: Install tmux (if not present)**

```bash
sudo apt install tmux
uv pip install libtmux
tmux -V
```

Expected: tmux available, libtmux importable from Python.

---

## Chunk 2: Configuration Files

### Task 2: Write Hyprland Compositor Config

**Files:**
- Create: `~/.config/hypr/hyprland.conf`

- [ ] **Step 1: Create config directory**

```bash
mkdir -p ~/.config/hypr
```

- [ ] **Step 2: Write hyprland.conf**

Write `~/.config/hypr/hyprland.conf` with full compositor configuration covering: monitor setup, NVIDIA env vars, input settings, aesthetic settings (from design spec), keybinds, window rules, autostart programs.

Key sections:
- Monitor: `monitor = , preferred, auto, 1`
- NVIDIA env vars: LIBVA_DRIVER_NAME, __GLX_VENDOR_LIBRARY_NAME, GBM_BACKEND, WLR_NO_HARDWARE_CURSORS, ELECTRON_OZONE_PLATFORM_HINT
- XDG env vars: XDG_CURRENT_DESKTOP=Hyprland, XDG_SESSION_TYPE=wayland, QT_QPA_PLATFORM=wayland, MOZ_ENABLE_WAYLAND=1
- Aesthetic: gaps_in=2, gaps_out=4, border_size=2, active_border=rgb(00c8c8), inactive_border=rgb(2a2a30), rounding=0, inactive_opacity=0.92, no shadows, no blur
- Animations: snap bezier (0.25, 1.0, 0.5, 1.0), popin 90% windows, slide workspaces
- Keybinds: Super+Return=foot, Super+Q=killactive, Super+D=fuzzel, Super+1-0=workspaces, Super+Shift+1-0=move-to-workspace, Super+HJKL=focus, Super+Shift+HJKL=move, Print=grim screenshot, media keys via wpctl, LLM hotkeys (Super+Shift+A/L/M/T/R), Super+Shift+Escape=hyprlock
- Autostart: waybar, hyprpaper, mako, hypridle, cliphist wl-paste watchers, nm-applet --indicator, blueman-applet, polkit agent
- Window rules: opacity 1.0 override for mpv, firefox, chrome (prevent inactive dim on video)

- [ ] **Step 3: Verify config syntax**

```bash
hyprctl reload 2>&1 || echo "Not running yet, syntax check deferred to first boot"
```

### Task 3: Write Waybar Config

**Files:**
- Create: `~/.config/waybar/config.jsonc`
- Create: `~/.config/waybar/style.css`

- [ ] **Step 1: Create config directory**

```bash
mkdir -p ~/.config/waybar
```

- [ ] **Step 2: Write config.jsonc**

Modules-left: hyprland/workspaces. Modules-center: hyprland/window. Modules-right: custom/gpu, cpu, memory, pulseaudio, network, tray, clock. Height 24px, top position, margins 0/4/4/0. Include tray module for nm-applet and blueman-applet. Network module shows essid for wifi, "eth" for wired, "offline" for disconnected. GPU module polls nvidia-smi every 5 seconds.

- [ ] **Step 3: Write style.css**

Full CSS from aesthetic design spec Section 5, plus tray and network styling. JetBrainsMono Nerd Font 12px. Background #141418, border-bottom 2px #2a2a30. Active workspace cyan text + cyan underline. All modules padded 0 8px, color #909098. Clock color #c0c0c0.

### Task 4: Write foot Terminal Config

**Files:**
- Create: `~/.config/foot/foot.ini`

- [ ] **Step 1: Create config directory and write config**

```bash
mkdir -p ~/.config/foot
```

JetBrainsMono Nerd Font size 11, pad 8x4, scrollback 10000, block cursor no blink. Full 16-color palette from aesthetic design spec Section 3. Background 0a0a0a, foreground c0c0c0, selection cyan-on-black inverted.

### Task 5: Write mako Notification Config

**Files:**
- Create: `~/.config/mako/config`

- [ ] **Step 1: Create config directory and write config**

```bash
mkdir -p ~/.config/mako
```

From aesthetic design spec Section 6. JetBrainsMono 11, background #141418, text #c0c0c0, border 2px, no radius, padding 8, width 320, max-visible 3, top-right anchor, 5s timeout, no icons. Urgency: low=ash border, normal=cyan border, critical=red border+no timeout.

### Task 6: Write hyprlock Config

**Files:**
- Create: `~/.config/hypr/hyprlock.conf`

- [ ] **Step 1: Write hyprlock.conf**

From aesthetic design spec Section 7. Black background (rgba 10,10,10), no blur. Input field 300x40, outline 2px cyan, inner #141418, rounding 0, placeholder "password" in smoke gray. Check color amber, fail color ember. Two labels: $TIME in cyan 28pt centered at y+80, $USER in smoke 14pt centered at y+50.

### Task 7: Write hypridle Config

**Files:**
- Create: `~/.config/hypr/hypridle.conf`

- [ ] **Step 1: Write hypridle.conf**

Lock on suspend (loginctl lock-session), DPMS on after sleep. Lock after 300s idle, DPMS off after 600s idle with resume handler.

### Task 8: Write hyprpaper Config

**Files:**
- Create: `~/.config/hypr/hyprpaper.conf`

- [ ] **Step 1: Write hyprpaper.conf**

Use the existing ACiD BBS wallpaper from COSMIC backgrounds: `/usr/share/backgrounds/cosmic/acid-bbs-wallpaper.png`. Splash disabled, IPC enabled, fit_mode cover, no monitor filter (applies to all).

### Task 9: Write fuzzel Config

**Files:**
- Create: `~/.config/fuzzel/fuzzel.ini`

- [ ] **Step 1: Create config directory and write config**

```bash
mkdir -p ~/.config/fuzzel
```

From aesthetic design spec Section 8. JetBrainsMono 12, 10 lines, width 40 chars, no icons. Colors: background 141418, text c0c0c0, prompt cyan, placeholder smoke, match amber, selection slate+cyan, border ash, radius 0, border width 2.

---

## Chunk 3: First Boot and Hardware Verification

### Task 10: First Boot Verification

**Files:**
- None (manual verification at login screen)

- [ ] **Step 1: Log out of COSMIC**

Log out. At the login screen (cosmic-greeter), select "Hyprland" session from the session picker.

- [ ] **Step 2: Log in and verify basics**

Verify: waybar at top, ACiD BBS wallpaper, Super+Return opens foot, Super+D opens fuzzel, cyan active borders, tight gaps.

- [ ] **Step 3: Verify WiFi connectivity**

```bash
nmcli connection show --active
nmcli device wifi list
ping -c 3 8.8.8.8
```

Expected: Current WiFi active, internet reachable, all saved networks available. nm-applet in waybar tray.

- [ ] **Step 4: Verify Bluetooth**

```bash
bluetoothctl devices
bluetoothctl info <MAC>
```

Expected: Paired devices listed, blueman-applet in tray. Test connecting BT audio (iLoud monitors).

- [ ] **Step 5: Verify audio**

```bash
wpctl status
wpctl set-volume @DEFAULT_AUDIO_SINK@ 50%
speaker-test -c 2 -t wav -l 1
aconnect -l
```

Expected: PipeWire running, audio plays, MIDI ports visible, media keys work.

- [ ] **Step 6: Verify webcam**

```bash
v4l2-ctl --list-devices
```

Expected: Webcam listed. v4l2 is kernel-level, compositor-independent.

- [ ] **Step 7: Verify screen sharing portal**

```bash
systemctl --user status xdg-desktop-portal-hyprland
systemctl --user status xdg-desktop-portal
```

Expected: Both active. Test screen sharing in Firefox on a WebRTC test page.

- [ ] **Step 8: Verify NVIDIA GPU**

```bash
nvidia-smi
hyprctl monitors -j
```

Expected: GPU visible, monitor listed correctly, waybar GPU module shows usage.

- [ ] **Step 9: Verify screenshots**

Press Print, then: `wl-paste > /tmp/test-screenshot.png && file /tmp/test-screenshot.png`

Expected: Full-screen screenshot captured to clipboard.

- [ ] **Step 10: Verify notifications**

```bash
notify-send "Test" "Hyprland notifications working"
notify-send -u critical "Critical" "Red border test"
```

Expected: Cyan border normal, red border critical, top-right position.

- [ ] **Step 11: Verify lock screen**

Press Super+Shift+Escape. Expected: BBS-style login prompt on black.

---

## Chunk 4: Voice Daemon Updates

### Task 11: Update Screen Capturer (cosmic-screenshot to grim)

**Files:**
- Modify: `agents/hapax_voice/screen_capturer.py`
- Modify: `tests/hapax_voice/test_screen_capturer.py`
- Modify: `tests/hapax_voice/conftest.py`

- [ ] **Step 1: Write the failing test**

Update test mocks: change `"cosmic-screenshot" in cmd[0]` to `"grim" in cmd[0]`. Update fake output generation to match grim behavior (grim takes output path as argument, writes PNG directly).

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_screen_capturer.py -v`
Expected: FAIL (screen_capturer.py still calls cosmic-screenshot)

- [ ] **Step 2: Update screen_capturer.py**

Replace cosmic-screenshot subprocess call with grim. grim is simpler: `grim <output_path>` writes PNG directly. No --interactive or --notify flags needed. Update docstring.

- [ ] **Step 3: Run tests to verify pass**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_screen_capturer.py -v`
Expected: All PASS

- [ ] **Step 4: Update conftest.py skip condition**

Change `_has_command("cosmic-screenshot")` to `_has_command("grim")`.

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/screen_capturer.py tests/hapax_voice/test_screen_capturer.py tests/hapax_voice/conftest.py
git commit -m "fix: replace cosmic-screenshot with grim for Hyprland migration"
```

### Task 12: Update Activity Mode (cosmic-term to foot)

**Files:**
- Modify: `agents/hapax_voice/activity_mode.py`
- Modify: `tests/hapax_voice/test_workspace_analyzer.py`

- [ ] **Step 1: Write the failing test**

Change mock data `"app": "cosmic-term"` to `"app": "foot"`. Run tests expecting failure.

- [ ] **Step 2: Update activity_mode.py**

Change `_CODE_APPS` set: replace `"cosmic-term"` with `"foot"`.

- [ ] **Step 3: Run tests to verify pass**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_workspace_analyzer.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_voice/activity_mode.py tests/hapax_voice/test_workspace_analyzer.py
git commit -m "fix: replace cosmic-term with foot in activity mode detection"
```

### Task 13: Update LLM System Prompts

**Files:**
- Modify: `agents/hapax_voice/screen_analyzer.py`
- Modify: `agents/hapax_voice/workspace_analyzer.py`

- [ ] **Step 1: Update screen_analyzer.py prompt**

Change `(COSMIC/Wayland)` to `(Hyprland/Wayland)` in system prompt.

- [ ] **Step 2: Update workspace_analyzer.py prompt**

Change `(Linux/COSMIC/Wayland)` to `(Linux/Hyprland/Wayland)` in system prompt.

- [ ] **Step 3: Run full voice daemon test suite**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_voice/screen_analyzer.py agents/hapax_voice/workspace_analyzer.py
git commit -m "fix: update voice daemon LLM prompts from COSMIC to Hyprland"
```

### Task 14: Update Component Registry

**Files:**
- Modify: `profiles/component-registry.yaml`

- [ ] **Step 1: Update COSMIC references**

Change "Must work on COSMIC/Wayland" to "Must work on Hyprland/Wayland". Change cosmic-screenshot note to reference grim.

- [ ] **Step 2: Commit**

```bash
git add profiles/component-registry.yaml
git commit -m "docs: update component registry for Hyprland migration"
```

---

## Chunk 5: tmux Setup and Integration Verification

### Task 15: Configure tmux for Agent Use

**Files:**
- Create: `~/.tmux.conf`

- [ ] **Step 1: Write tmux.conf**

Terminal Sublime-themed tmux config: history-limit 50000, mouse on, true color support for foot, escape-time 10, base-index 1. Status bar: bg #141418, fg #606068, left shows session name in cyan, right shows time in smoke. Window status: inactive smoke, active cyan. Pane borders: inactive ash, active cyan. Message style: slate bg, bone fg.

- [ ] **Step 2: Verify tmux launches correctly**

```bash
tmux new-session -s test
tmux list-sessions
tmux kill-session -t test
```

Expected: Clean lifecycle, colors match aesthetic.

- [ ] **Step 3: Verify libtmux from Python**

```bash
cd ~/projects/hapax-council && uv run python -c "import libtmux; print('libtmux OK')"
```

Expected: No errors.

### Task 16: Full Integration Smoke Test

**Files:**
- None (verification only)

- [ ] **Step 1: Run full test suite**

```bash
cd ~/projects/hapax-council && uv run pytest tests/ -q
```

Expected: All 1524+ tests pass.

- [ ] **Step 2: Verify Docker services**

```bash
curl -s http://127.0.0.1:4000/health | head -1
curl -s http://127.0.0.1:6333/collections | head -1
curl -s http://127.0.0.1:8051/api/health | head -1
```

Expected: All respond. Docker is system-level, unaffected by DE switch.

- [ ] **Step 3: Verify agent invocation**

```bash
cd ~/projects/hapax-council && eval "$(<.envrc)"
uv run python -m agents.health_monitor --history 2>&1 | tail -5
```

Expected: Runs, outputs status.

- [ ] **Step 4: Verify voice daemon check**

```bash
cd ~/projects/hapax-council && uv run python -m agents.hapax_voice --check
```

Expected: Config validation passes, no COSMIC references.

---

## Chunk 6: Documentation Updates

### Task 17: Update distro-work References

**Files:**
- Modify: `~/projects/distro-work/CLAUDE.md`
- Modify: `~/projects/distro-work/docs/hyprland-migration-capabilities.md`

- [ ] **Step 1: Update status**

Change capabilities doc status from "Migration planned" to "Active". Verify distro-work CLAUDE.md desktop section is accurate.

- [ ] **Step 2: Commit in distro-work**

```bash
cd ~/projects/distro-work
git add CLAUDE.md docs/hyprland-migration-capabilities.md
git commit -m "docs: update Hyprland migration status to active"
```

### Task 18: Update ai-agents CLAUDE.md

**Files:**
- Modify: `~/projects/hapax-council/CLAUDE.md`

- [ ] **Step 1: Update any COSMIC references**

If CLAUDE.md references COSMIC, update to Hyprland. Add note about grim replacing cosmic-screenshot if voice daemon section exists.

---

## Rollback Procedure

If anything goes wrong:

1. **At login screen:** Select "COSMIC" session instead of "Hyprland". Immediate rollback, no changes needed.
2. **Portal conflict:** `systemctl --user unmask xdg-desktop-portal-cosmic.service` and re-login to COSMIC.
3. **Full removal:** `sudo apt remove hyprland hyprlock hypridle hyprpaper xdg-desktop-portal-hyprland waybar foot mako-notifier`

Both sessions coexist permanently. COSMIC is never uninstalled.
