# Audio Topology Reference Manual

Single source of truth for the Hapax PipeWire broadcast audio architecture.
All other audio docs (runbook, handoff, config README) defer to this document.

> **⚠ INTERIM MPC-ONLY (2026-05-29): the ZOOM L-12 was physically removed.**
> The Akai MPC Live III is the sole interface until the MOTU UltraLite mk5 +
> FadeFox MX12 land (~2026-05-30/31). The broadcast return now runs
> **PC → MPC → PC** entirely over the MPC's own 24-channel USB return — no L-12.
> The MPC internal mixer returns two stereo busses to the host:
> **capture_AUX0/1 = public mix** (music + voice + YouTube, broadcast-bound) and
> **capture_AUX2/3 = private monitor** (fenced from broadcast). The L-12 sections
> below are retained as ORPHANED until the MOTU/FadeFox migration retires them.

**Architecture principle:** MPC-first for explicitly specified livestream
sources only. Music, public TTS, and YouTube enter MPC Live III over USB; the
MPC sums them into its public mix and returns it on the MPC's own USB capture
(capture_AUX0/1), which reaches the livestream. Private TTS enters MPC AUX8/9
for private monitoring only, and the private return (capture_AUX2/3) is fenced
from broadcast. Under-specified host sources have no MPC, OBS, or livestream
egress.

**Last verified:** 2026-05-29 (interim MPC-only; L-12 removed)

---

## 1. Hardware Signal Path

```
  ┌──────────────────────────────────────────────────────────┐
  │                      HOST PC                             │
  │                                                          │
  │  Music ──→ music-duck ──→ music-loudnorm ──→ MPC AUX0/1 │
  │  TTS ────→ voice-fx ───→ loudnorm ────────→ MPC AUX2/3  │
  │  PC ─────→ pc-loudnorm ───────────────→ disabled/no egress│
  │  YouTube → yt-loudnorm ───────────────────→ MPC AUX6/7  │
  │  Private → private-monitor-bridge ─────────→ MPC AUX8/9  │
  │  M8 ─────→ m8-loudnorm ───────────────→ disabled/no egress│
  └─────────────┬────────────────────────────────────────────┘
                │ USB out (send)              ▲ USB in (return)
                ▼                             │
  ┌────────────────────────────────────────────────────────┐
  │  MPC LIVE III  (interim sole interface — L-12 removed)  │
  │  DSP mix + effects                                      │
  │  Public mix (music+voice+youtube) → USB out 1/2 ────────┼─→ host capture_AUX0/1
  │  Private monitor mix             → USB out 3/4 ─────────┼─→ host capture_AUX2/3 (FENCED)
  └────────────────────────────────────────────────────────┘
                                              │ USB capture_AUX0/1 (public only)
                                              ▼
  ┌──────────────────────────────────────────────────────────┐
  │  hapax-mpc-usb-return-capture (USB transient clamp)      │
  │  → livestream-tap → broadcast-master → broadcast-normalized│
  │  → obs-broadcast-remap → OBS → Twitch/YouTube           │
  └──────────────────────────────────────────────────────────┘

  capture_AUX2/3 (private monitor) is NOT captured into broadcast and is
  fenced from every broadcast node by config/hapax/audio-forbidden-links.conf.
```

## 2. MPC USB Channel Map (Fixed)

### Send (host → MPC, USB IN / playback_AUX*)

| USB Channels | AUX Pair | Source            | PipeWire Playback Node         |
|-------------|----------|-------------------|--------------------------------|
| AUX0/1      | IN 1/2   | Music (SoundCloud)| hapax-music-loudnorm-playback  |
| AUX2/3      | IN 3/4   | TTS voice         | hapax-loudnorm-playback        |
| AUX4/5      | IN 5/6   | Disabled          | PC/default multimedia fail-closed |
| AUX6/7      | IN 7/8   | YouTube (send enabled; broadcast eligibility gated `blocked_until_smoke`) | hapax-yt-loudnorm-playback |
| AUX8/9      | IN 9/10  | Private TTS only  | hapax-private-playback         |

### Return (MPC → host, USB OUT / capture_AUX*) — interim MPC-only

| USB Channels | AUX Pair | Content           | PipeWire Capture Node          |
|-------------|----------|-------------------|--------------------------------|
| AUX0/1      | OUT 1/2  | **Public mix** (music + voice + YouTube, summed in MPC) — broadcast-bound | hapax-mpc-usb-return-capture → livestream-tap |
| AUX2/3      | OUT 3/4  | **Private monitor** — operator-only, **FENCED** from every broadcast node | (not captured into broadcast) |

The MPC public mix MUST exclude the private source (operator-owned MPC mixer
setting). The software fence (audio-forbidden-links.conf) is defense-in-depth.

## 3. Source Inventory

| Source | Service/Origin | PipeWire Entry Point | Chain | Status |
|--------|---------------|---------------------|-------|--------|
| SoundCloud music | `hapax-music-player.service` (yt-dlp → ffmpeg → pw-cat) | hapax-music-loudnorm (direct) | loudnorm → MPC AUX0/1 | Active |
| TTS voice | `hapax-daimonion.service` (Chatterbox/Kokoro → role.broadcast) | hapax-voice-fx-capture | voice-fx → loudnorm → MPC AUX2/3 | Active |
| PC multimedia | WirePlumber role.multimedia loopback | hapax-pc-loudnorm | no MPC/livestream egress | Disabled/fail-closed |
| YouTube bed | Browser/OBS → manual sink selection | hapax-yt-loudnorm | loudnorm → MPC AUX6/7 (send enabled; broadcast eligibility gated `blocked_until_smoke`) | Send active |
| Private assistant | WirePlumber role.assistant loopback | hapax-private | private-monitor-bridge → MPC AUX8/9 | Active |
| Notifications | WirePlumber role.notification loopback | hapax-notification-private | no MPC/livestream egress | Disabled/fail-closed |
| M8 instrument | USB audio device (Dirtywave M8) | hapax-m8-loudnorm | no MPC/livestream egress | Disabled/fail-closed |
| Operator voice | Rode Wireless Pro → MPC physical input (interim; was L-12 CH5) | MPC mix → public return | MPC public mix → capture_AUX0/1 | Always on (operator-routed in MPC) |
| L-12 instruments | _ORPHANED — L-12 removed 2026-05-29_ (was physical mics/guitars on L-12 CH1-8) | ~~hapax-l12-evilpet-capture~~ | retired until MOTU/FadeFox | Orphaned |

**SoundCloud is NOT a browser.** The music daemon (`hapax-music-player.service`)
uses yt-dlp to download tracks and ffmpeg + pw-cat to pipe audio directly to
`hapax-music-loudnorm`. The playlist lives at
`~/hapax-state/music-repo/soundcloud.jsonl`, replenished by
`hapax-soundcloud-adapter.service`.

Default/unclassified desktop audio must also resolve to fail-closed
`hapax-pc-loudnorm`. The default sink must never be a physical hardware or
broadcast-path device (MPC, L-12, S-4, M8, Yeti, HDMI, or Bluetooth).

## 4. Signal Flow Per Use Case

### 4a. TTS Voice → Livestream

```
Daimonion (role.broadcast)
  → output.loopback.sink.role.broadcast
  → hapax-voice-fx-capture (EQ: HP, low-mid cut, presence, air)
  → hapax-voice-fx-playback
  → hapax-loudnorm-capture (true-peak limiter, -18 dBFS)
  → hapax-loudnorm-playback
  → MPC USB IN 3/4 (AUX2/3)
  → MPC DSP mix → MPC public mix → MPC USB OUT 1/2
  → host capture_AUX0/1
  → hapax-mpc-usb-return-capture → hapax-mpc-usb-return-playback
  → hapax-livestream-tap
  → hapax-broadcast-master-capture → hapax-broadcast-normalized
  → hapax-obs-broadcast-remap → OBS
```

### 4b. Music → Livestream

```
hapax-music-player.service (pw-cat → hapax-music-loudnorm directly)
  → hapax-music-loudnorm (true-peak limiter, -18 dBFS)
  → hapax-music-loudnorm-playback
  → MPC USB IN 1/2 (AUX0/1)
  → MPC DSP mix → MPC public mix → MPC USB OUT 1/2
  → host capture_AUX0/1 → hapax-mpc-usb-return-capture → livestream-tap → OBS
```

Music ducking: `hapax-audio-ducker.service` writes gain to `hapax-music-duck`
mixer nodes when operator voice (Rode VAD) or TTS is active.

### 4c. Private Audio (NOT Broadcast)

```
role.assistant → hapax-private (null sink)
  → hapax-private:monitor → hapax-private-monitor-capture
  → hapax-private-playback → MPC AUX8/9 (send)
  → MPC private monitor mix → MPC USB OUT 3/4 → host capture_AUX2/3 (return)
  → operator private monitor ONLY — FENCED from every broadcast node
    (audio-forbidden-links.conf: capture_AUX2/3 → livestream-tap /
     broadcast-master / broadcast-normalized / obs-broadcast-remap all denied)
```

## 5. Critical Invariants

| # | Invariant | Failure Mode |
|---|-----------|-------------|
| 1 | The MPC public mix (capture_AUX0/1) reaches broadcast; the private monitor return (capture_AUX2/3) is fenced from every broadcast node | Silent audio leak if the public return isn't captured; constitutional violation if private leaks to broadcast |
| 2 | The MPC public mix is operator-owned and must exclude private; software fence is defense-in-depth | Private content on broadcast if the MPC mixer includes it |
| 3 | MPC AUX assignments are fixed (§2) | Wrong audio on wrong bus |
| 4 | OBS binds to broadcast-normalized or obs-broadcast-remap only | Bypasses master limiter |
| 5 | TTS path: role.broadcast → voice-fx → loudnorm → MPC AUX2/3 | Voice silently disappears |
| 6 | Broadcast loopback must never be muted | Graph looks correct but no audio flows |
| 7 | No webcam mics in broadcast chain | Room audio leaks to stream |
| 8 | No dry host signal to livestream (MPC-first) | Untreated audio on stream |

## 6. Node Protection Status (2026-05-20)

| Node | autoconnect | dont-fallback | Reconciler | Protection |
|------|------------|--------------|-----------|-----------|
| hapax-music-loudnorm-playback | false | true | yes | FULL |
| hapax-loudnorm-playback (TTS) | false | true | yes | FULL |
| hapax-pc-loudnorm-playback | false | true | no live egress | DISABLED |
| hapax-yt-loudnorm-playback | false | true | no live egress | DISABLED |
| hapax-music-duck-playback | — | true | yes | FULL |
| hapax-pc-broadcast-playback | false | true | — | QUARANTINED |
| hapax-polyend-loudnorm-playback | false | true | — | GUARDED |
| hapax-private-playback | false | true | yes | FULL + HEAVY |
| hapax-notification-private-playback | false | true | forbidden | DISABLED |
| hapax-pc-monitor-playback | — | true | — | QUARANTINED |
| hapax-m8-loudnorm-playback | false | true | no live egress | DISABLED |

## 7. Reconciler & Sidechain Ducking

**Reconciler:** `hapax-audio-reconciler.service`
- Reads `~/.config/hapax/audio-link-map.conf` + `audio-forbidden-links.conf`
- Ticks every 2s, creates missing links, destroys forbidden ones
- Requires: pipewire + wireplumber (dies if either dies)

**Ducker:** `hapax-audio-ducker.service`
- Controls hapax-music-duck gain via pw-cli
- Rode VAD active → music gain 0.251 (-12 dB)
- TTS active → music gain 0.398 (-8 dB)
- Both → deepest duck wins; neither → 1.0 passthrough

**Validation:** `scripts/hapax-audio-routing-check` — run before/after config changes

## 8. Troubleshooting

| Symptom | Check |
|---------|-------|
| No music playing | `systemctl --user status hapax-music-player` + `wc -l ~/hapax-state/music-repo/soundcloud.jsonl` |
| TTS silent on stream | `scripts/hapax-audio-routing-check` + check broadcast loopback mute |
| Webcam mic on stream | `pw-link -l \| grep 'alsa_input.usb-046d'` + verify WirePlumber block |
| Audio bleeding | `pw-link -l` for unauthorized links + reconciler forbidden-links |
| L-12 USB missing | `pw-cli ls Node \| grep -i zoom` + physical reconnect |
| No audio at all | Check MPC USB device present + reconciler running + PipeWire healthy |

## 9. Decommissioned

| Item | Retired | Notes |
|------|---------|-------|
| PreSonus Studio 24c | 2026-05-03 | Archived; never mention |
| hapax-tts-duck (software ducker) | 2026-04-23 | Replaced by MPC-routed voice chain |
| hapax-source-activate.timer | 2026-05-20 | Was regenerating configs; permanently disabled |

## 10. Key Files

| File | Purpose |
|------|---------|
| `~/.config/pipewire/pipewire.conf.d/hapax-*.conf` | Filter-chain definitions |
| `~/.config/hapax/audio-link-map.conf` | Reconciler desired-state links |
| `~/.config/hapax/audio-forbidden-links.conf` | Reconciler forbidden links |
| `~/.config/wireplumber/wireplumber.conf.d/80-block-webcam-mic-autolink.conf` | Webcam mic block |
| `scripts/hapax-audio-routing-check` | 11-invariant validation |
| `shared/audio_loudness.py` | Loudness constants (gain values SSOT) |
