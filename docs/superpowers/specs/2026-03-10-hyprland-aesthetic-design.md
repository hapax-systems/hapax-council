# Hyprland Desktop Aesthetic — Design Spec

> **Status:** Approved
> **Date:** 2026-03-10
> **Scope:** Hyprland compositor + waybar + foot + mako + hyprlock + fuzzel + hyprpaper

## Problem

Migrating from COSMIC to Hyprland requires a complete desktop aesthetic. The default Hyprland look is generic. The operator prizes beauty through functionalism, minimalism, articulated proportions, and deliberate placement — not decoration.

## Goal

A cohesive desktop aesthetic rooted in BitchX/ACiD Productions/90s BBS visual culture, tempered by COSMIC's modern warmth. Every visual element carries information. Color encodes meaning. Borders contain, never decorate. The canvas is darkness; elements float on it.

---

## Section 1: Design Principles

### Source Material Hierarchy

1. **Primary:** BitchX IRC client (dense, data-carrying status bars, color = meaning), ACiD Productions ANSI art (blue-cyan-white gradient family, black negative space, flat elements on void), 90s BBS culture (color-coded menus, box-drawn frames, information hierarchy through brightness)
2. **Secondary:** COSMIC Desktop dark theme (warm neutrals, desaturated accents, `#49BAC8` teal)

### Governing Rules

1. **Functionalism** — Every visual element carries information. Waybar modules earn their space or are removed. No ornamental gradients, shadows, or blur.
2. **Minimalism** — Black negative space is the canvas. Elements are flat on darkness. No depth effects (shadows, blur, frosted glass).
3. **Proportions** — All spacing derives from a 2px base unit. Gaps, borders, padding are integer multiples. Consistent, deliberate, proportional.
4. **Color = Meaning** — Cyan = information/focus. Amber = actionable. Red = alert. Gray = secondary. Brightness encodes importance (BBS paradigm).

---

## Section 2: Color Palette

Derived from the ACiD blue-cyan-white gradient family. COSMIC's warmth tempers the harshest classic ANSI values.

| Role | Name | Hex | Derivation |
|------|------|-----|------------|
| Background | void | `#0a0a0a` | Near-black (pure `#000` harsh on modern panels; COSMIC's `#1B1B1B` too warm) |
| Surface | slate | `#141418` | Containers, bar background. Slight blue undertone from ACiD cool palette |
| Border inactive | ash | `#2a2a30` | Barely visible — recedes like BBS dark gray (ANSI color 8) borders |
| Border active | cyan | `#00c8c8` | Hero color. ACiD bright cyan pulled 20% toward COSMIC's `#49BAC8` |
| Text primary | bone | `#c0c0c0` | Classic terminal light gray — literal ANSI color 7 |
| Text secondary | smoke | `#606068` | Dark gray with slight blue — ANSI color 8 territory |
| Accent warm | amber | `#d4a017` | BBS "actionable" yellow, desaturated toward COSMIC's warm gold |
| Accent alert | ember | `#c43030` | BBS error red, slightly muted |
| Accent success | sage | `#5a9a6a` | COSMIC's sage green, darker than BBS bright green |
| Accent cool | ice | `#3a8fbf` | ACiD's intermediate blue step |

---

## Section 3: Terminal Palette (foot)

The terminal palette is where the BBS lineage is most direct. These are the actual ANSI colors programs will use.

```ini
[colors]
foreground = c0c0c0
background = 0a0a0a
alpha = 1.0
selection-foreground = 0a0a0a
selection-background = 00c8c8

# Standard (dim — structure and secondary info)
regular0 = 1a1a1e
regular1 = a03030
regular2 = 4a8a5a
regular3 = a08020
regular4 = 3a6a9a
regular5 = 7a4a8a
regular6 = 2a8a8a
regular7 = 909098

# Bright (emphasis and active elements)
bright0 = 404048
bright1 = c84040
bright2 = 5a9a6a
bright3 = d4a017
bright4 = 4a8abf
bright5 = 9a6aaa
bright6 = 00c8c8
bright7 = d0d0d8
```

Font and spacing:

```ini
[main]
font = JetBrainsMono Nerd Font:size=11
pad = 8x4
```

- Padding tight (8px horizontal, 4px vertical) — BBS terminals wasted nothing
- JetBrainsMono Nerd Font for Powerline/icon glyphs and legibility at small sizes

---

## Section 4: Compositor (Hyprland)

All spacing governed by the 2px base unit.

```conf
general {
    gaps_in = 2
    gaps_out = 4
    border_size = 2
    col.active_border = rgb(00c8c8)
    col.inactive_border = rgb(2a2a30)
    layout = dwindle
    resize_on_border = true
}

decoration {
    rounding = 0
    active_opacity = 1.0
    inactive_opacity = 0.92
    dim_inactive = false

    shadow {
        enabled = false
    }

    blur {
        enabled = false
    }
}

animations {
    enabled = true
    bezier = snap, 0.25, 1.0, 0.5, 1.0

    animation = windows, 1, 3, snap, popin 90%
    animation = windowsOut, 1, 3, snap, popin 90%
    animation = fade, 1, 3, snap
    animation = workspaces, 1, 3, snap, slide
    animation = border, 1, 5, snap
    animation = borderangle, 0
}

misc {
    disable_hyprland_logo = true
    disable_splash_rendering = true
    background_color = rgb(0a0a0a)
    force_default_wallpaper = 0
}
```

Design rationale:
- **No rounding** — Box-drawing characters are rectangular. So are windows.
- **No shadows, no blur** — ACiD art has no depth effects. Also saves GPU cycles.
- **Tight gaps** — BitchX density. 2px inner = windows close but borders visible.
- **Opacity for hierarchy** — BBS brightness convention. Active 100%, inactive 92%. Subtle but perceptible.
- **Fast animations** — "snap" bezier: quick transitions, not jarring. Popin 90% = minimal scale, just enough to register.

---

## Section 5: Status Bar (Waybar)

Replaces BitchX's double status bar. Dense, data-carrying, no wasted space.

### Config (`config.jsonc`)

```jsonc
{
    "layer": "top",
    "position": "top",
    "height": 24,
    "spacing": 0,
    "margin-top": 0,
    "margin-left": 4,
    "margin-right": 4,
    "margin-bottom": 0,

    "modules-left": [
        "hyprland/workspaces"
    ],
    "modules-center": [
        "hyprland/window"
    ],
    "modules-right": [
        "custom/gpu",
        "cpu",
        "memory",
        "pulseaudio",
        "clock"
    ],

    "hyprland/workspaces": {
        "format": "{id}",
        "on-click": "activate",
        "sort-by-number": true
    },
    "hyprland/window": {
        "max-length": 60,
        "separate-outputs": true
    },
    "cpu": { "format": "cpu {usage}%" },
    "memory": { "format": "mem {percentage}%" },
    "pulseaudio": { "format": "vol {volume}%" },
    "clock": {
        "format": "{:%H:%M}",
        "tooltip-format": "{:%Y-%m-%d %A}"
    },
    "custom/gpu": {
        "exec": "nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null || echo 'N/A'",
        "format": "gpu {}%",
        "interval": 5
    }
}
```

### Style (`style.css`)

```css
* {
    font-family: "JetBrainsMono Nerd Font", monospace;
    font-size: 12px;
    min-height: 0;
}

window#waybar {
    background-color: #141418;
    color: #c0c0c0;
    border-bottom: 2px solid #2a2a30;
}

#workspaces button {
    padding: 0 6px;
    color: #606068;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
}

#workspaces button.active {
    color: #00c8c8;
    border-bottom: 2px solid #00c8c8;
}

#workspaces button.urgent {
    color: #c43030;
    border-bottom: 2px solid #c43030;
}

#window {
    color: #606068;
}

#cpu, #memory, #custom-gpu, #pulseaudio, #clock {
    padding: 0 8px;
    color: #909098;
}

#clock {
    color: #c0c0c0;
}

tooltip {
    background-color: #141418;
    border: 1px solid #2a2a30;
    color: #c0c0c0;
}
```

Design notes:
- **24px height** — single line, full monitor width replaces BitchX's two 80-column lines
- **Monospace throughout** — reads like a terminal status line, not a desktop widget
- **Active workspace** — cyan text + cyan underline (BBS "bright = active")
- **Lowercase abbreviated labels** (`cpu`, `mem`, `gpu`, `vol`) — no icons, text-mode aesthetic
- **No border-radius, no module backgrounds** — information sits on the bar surface

---

## Section 6: Notifications (mako)

BBS system messages: brief, colored by urgency, positioned out of the way.

```ini
font=JetBrainsMono Nerd Font 11
background-color=#141418FF
text-color=#c0c0c0FF
border-color=#2a2a30FF
border-size=2
border-radius=0
padding=8
margin=4
width=320
height=120
max-visible=3
anchor=top-right
layer=overlay
default-timeout=5000
icon-path=
icons=0

[urgency=low]
border-color=#2a2a30FF
text-color=#606068FF

[urgency=normal]
border-color=#00c8c8FF

[urgency=critical]
border-color=#c43030FF
default-timeout=0
```

- **No icons** — text only, like BBS system messages
- **Border color = urgency** — sole visual differentiator. Low = invisible, normal = cyan, critical = red
- **No border-radius** — sharp rectangles
- **Top-right anchor** — visible but out of primary workspace

---

## Section 7: Lock Screen (hyprlock)

A BBS login prompt on black.

```conf
background {
    monitor =
    color = rgba(10,10,10,1.0)
    blur_passes = 0
}

input-field {
    monitor =
    size = 300, 40
    outline_thickness = 2
    outer_color = rgb(00c8c8)
    inner_color = rgb(141418)
    font_color = rgb(c0c0c0)
    fade_on_empty = true
    placeholder_text = <span foreground="#606068">password</span>
    dots_size = 0.25
    dots_spacing = 0.2
    rounding = 0
    check_color = rgb(d4a017)
    fail_color = rgb(c43030)
    fail_text = <span foreground="#c43030">denied ($ATTEMPTS)</span>
    position = 0, 0
    halign = center
    valign = center
}

label {
    monitor =
    text = $TIME
    color = rgb(00c8c8)
    font_size = 28
    font_family = JetBrainsMono Nerd Font
    position = 0, 80
    halign = center
    valign = center
}

label {
    monitor =
    text = $USER
    color = rgb(606068)
    font_size = 14
    font_family = JetBrainsMono Nerd Font
    position = 0, 50
    halign = center
    valign = center
}
```

Pure black screen. Centered: time in cyan, username in dark gray, thin-bordered input field. Like connecting to a BBS — just a login prompt in the void.

---

## Section 8: Launcher (fuzzel)

```ini
[main]
font=JetBrainsMono Nerd Font:size=12
lines=10
width=40
horizontal-pad=12
vertical-pad=8
inner-pad=8
icons-enabled=no
layer=overlay

[colors]
background=141418ff
text=c0c0c0ff
prompt=00c8c8ff
placeholder=606068ff
input=c0c0c0ff
match=d4a017ff
selection=1a1a2aff
selection-text=00c8c8ff
selection-match=d4a017ff
counter=606068ff
border=2a2a30ff

[border]
width=2
radius=0
```

- **Match highlight in amber** — BBS "actionable" color
- **Selection text in cyan** — active item gets the hero color
- **No icons** — text-only, like a BBS menu

---

## Section 9: Wallpaper

Solid `#0a0a0a` via hyprpaper. No image.

Future option: a piece of ACiD ANSI art from [16colo.rs](https://16colo.rs/group/acid) rendered to high-res PNG, positioned in the lower-right corner. But start with pure black — the windows ARE the visual content.

---

## Section 10: Proportional System

All spacing derives from the 2px base unit.

| Element | Size | Ratio to Base |
|---------|------|---------------|
| Border width | 2px | 1x |
| Gap inner | 2px | 1x |
| Gap outer | 4px | 2x |
| Bar height | 24px | 12x |
| Bar border | 2px | 1x |
| Notification border | 2px | 1x |
| Notification padding | 8px | 4x |
| Terminal padding | 8x4px | 4x/2x |
| Font size (terminal) | 11pt | -- |
| Font size (bar) | 12px | -- |

---

## Section 11: Color Semantics Reference

For agents and tools building on this desktop:

| Meaning | Color | Where Used |
|---------|-------|------------|
| Focus / active / primary info | cyan `#00c8c8` | Active border, active workspace, selection, lock screen time |
| Actionable / interactive | amber `#d4a017` | Match highlights, auth-checking state |
| Alert / error / critical | ember `#c43030` | Urgent notifications, auth failure, urgent workspace |
| Success / positive | sage `#5a9a6a` | -- (available for future agent use) |
| Secondary / supporting | ice `#3a8fbf` | -- (available for future agent use) |
| Primary text | bone `#c0c0c0` | Body text, clock |
| Secondary text | smoke `#606068` | Inactive items, placeholders, window title |
| Structure / borders | ash `#2a2a30` | Inactive borders, bar border, notification frames |
| Background | void `#0a0a0a` | Window background, compositor background |
| Surface | slate `#141418` | Bar background, notification background, input fields |
