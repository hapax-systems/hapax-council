# Hapax waybar modules

Bash modules that surface hapax operator-awareness state on the always-on
GTK4 status bar. Each script reads its source directly from `/dev/shm`
(or the canonical `state.json`) and emits one waybar-shaped JSON
payload per invocation. waybar polls them on a per-module interval.

## Constitutional invariants

- **No click handlers.** Refusal log + awareness state are daemon-fed
  and daemon-read. Operator detail surface is the Logos sidebar, not
  waybar. Click affordances would re-introduce the HITL loop the
  awareness-as-data substrate refuses (per `feedback_full_automation_or_no_engagement`).
- **No blink / strobe / flash classes.** CSS `.high` applies a slight
  contrast bump only — never a pulse (per `feedback_no_blinking_homage_wards`).
- **Read straight from authoritative source.** The refusals module
  reads `/dev/shm/hapax-refusals/log.jsonl`, NOT a state.json
  derivative — so it works even if the awareness runner stalls.
  The state-derived modules (publishing, fleet, stream, oudepode,
  daimonion stance) read `/dev/shm/hapax-awareness/state.json`.

## Install

The scripts are designed to be symlinked or copied into
`~/.local/bin/`:

```fish
for script in /home/hapax/projects/hapax-council/scripts/waybar/hapax-waybar-*
    ln -sf $script ~/.local/bin/(basename $script)
end
```

Then add the per-module entry (and `"custom/<name>"` reference in
the module list) to `~/.config/waybar/config.jsonc`.

## Modules

| Script | Source | Interval | cc-task |
|---|---|---|---|
| `hapax-waybar-refusals-1h` | `/dev/shm/hapax-refusals/log.jsonl` | 60s | `awareness-waybar-refusals-1h` |
| `hapax-waybar-publishing` | `state.json:.publishing_pipeline` | 30s | `awareness-waybar-publishing` |
| `hapax-waybar-fleet` | `state.json:.hardware_fleet` | 30s | `awareness-waybar-fleet` |
| `hapax-waybar-stream` | `state.json:.stream` | 1s | `awareness-waybar-stream` |
| `hapax-waybar-oudepode` | `state.json:.music_soundcloud` | 30s | `awareness-waybar-oudepode` |
| `hapax-waybar-operational-alerts` | `state.json:.mail` | 30s | `mail-monitor-operational-awareness-phase-2` |
| `hapax-waybar-pipewire-graph` | `~/hapax-state/pipewire-graph/egress-health.jsonl` | 5s | `audio-graph-ssot-p2-daemon-shadow` |

State-derived modules treat `mtime > 90s` on `state.json` as stale and
emit `class:"stale"` rather than dummy zeroes — so the bar visibly
dims when the awareness runner has stopped publishing.

## waybar config snippet — refusals-1h

```jsonc
"custom/refusals-1h": {
    "exec": "hapax-waybar-refusals-1h",
    "interval": 60,
    "return-type": "json",
    "format": "{}",
    "tooltip": true
}
```

Add `"custom/refusals-1h"` to the module list (e.g. in `modules-right`
or wherever ambient ops state belongs in the bar layout).

## CSS — refusals-1h

```css
#custom-refusals-1h {
    /* Default: subdued. Refusals are ambient, not alerts. */
    color: @text-muted;
}

#custom-refusals-1h.high {
    /* > 10 refusals/hr — slight contrast bump, NO pulse. */
    color: @text-emphasis;
}
```

## waybar config snippet — pipewire-graph

```jsonc
"custom/pipewire-graph": {
    "exec": "hapax-waybar-pipewire-graph",
    "interval": 5,
    "return-type": "json",
    "format": "{}",
    "tooltip": true
}
```

Classes are `green`, `yellow`, `red`, and `stale`. The module is a
shadow-mode indicator only; it does not mutate the graph or expose click
handlers.
