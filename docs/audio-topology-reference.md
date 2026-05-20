# Audio Topology Reference Manual

Single source of truth for the Hapax PipeWire broadcast audio architecture.
All other audio docs (runbook, handoff, config README) defer to this document.

**Architecture principle:** MPC-first. All host audio enters MPC Live III over
USB, exits MPC over TRS, enters L-12 physical inputs, and only then reaches
the livestream through L-12 USB capture. No dry host signal enters the
livestream.

**Last verified:** 2026-05-20

---

## 1. Hardware Signal Path

```
  ┌──────────────────────────────────────────────────────────┐
  │                      HOST PC                             │
  │                                                          │
  │  Music ──→ music-duck ──→ music-loudnorm ──→ MPC AUX0/1 │
  │  TTS ────→ voice-fx ───→ loudnorm ────────→ MPC AUX2/3  │
  │  PC ─────→ pc-loudnorm ────────────────────→ MPC AUX4/5  │
  │  YouTube → yt-loudnorm ────────────────────→ MPC AUX6/7  │
  │  Private → private-monitor-bridge ─────────→ MPC AUX8/9  │
  │  M8 ─────→ m8-loudnorm ───────→ L-12 USB return FL/FR   │
  └─────────────┬─────────────────────┬──────────────────────┘
                │ USB                 │ USB
                ▼                     ▼
  ┌─────────────────────┐   ┌──────────────────────┐
  │  MPC LIVE III       │   │  ZOOM L-12           │
  │  DSP mix + effects  │   │  CH 1-8: instruments │
  │  Out 1/2 → L-12 9/10│   │  CH 9/10: MPC return │
  │  Out 3/4 → L-12 11/12│  │  CH 11/12: MPC voice │
  └─────────────────────┘   │  AUX B → Evil Pet    │
                            │  USB capture → host  │
                            └──────────┬───────────┘
                                       │ USB capture
                                       ▼
  ┌──────────────────────────────────────────────────────────┐
  │  livestream-tap → broadcast-master → broadcast-normalized│
  │  → obs-broadcast-remap → OBS → Twitch/YouTube           │
  └──────────────────────────────────────────────────────────┘
```

## 2. MPC USB Channel Map (Fixed)

| USB Channels | AUX Pair | Source            | PipeWire Playback Node         |
|-------------|----------|-------------------|--------------------------------|
| AUX0/1      | IN 1/2   | Music (SoundCloud)| hapax-music-loudnorm-playback  |
| AUX2/3      | IN 3/4   | TTS voice         | hapax-loudnorm-playback        |
| AUX4/5      | IN 5/6   | PC/system audio   | hapax-pc-loudnorm-playback     |
| AUX6/7      | IN 7/8   | YouTube audio     | hapax-yt-loudnorm-playback     |
| AUX8/9      | IN 9/10  | Private/assistant | hapax-private-playback + hapax-notification-private-playback |

## 3. Schema V4 Generated Tables

Generated from `config/audio-topology.yaml` via
`shared.audio_topology_generator.generate_audio_graph_reference_tables`.

<!-- audio-graph-v4-generated:start -->
### Route Classes

| ID | Kind | Broadcast | Private | Autoconnect | Fail Closed | Recovery |
| --- | --- | --- | --- | --- | --- | --- |
| mpc-first-broadcast | broadcast | yes | no | no | yes | hold |
| private-monitor-fail-closed | private | no | yes | no | yes | hold |
| optional-hardware-fail-closed | optional | no | no | no | yes | operator-promote |
| aec-reference-only | aec-reference | no | yes | no | yes | hold |

### Port Groups

| ID | Node | Role | Route Class | Fail Closed | Ports |
| --- | --- | --- | --- | --- | --- |
| mpc-content-return-output | mpc-usb-output | broadcast | mpc-first-broadcast | yes | mpc-usb-output-aux0, mpc-usb-output-aux1 |
| mpc-voice-return-output | mpc-usb-output | broadcast | mpc-first-broadcast | yes | mpc-usb-output-aux2, mpc-usb-output-aux3 |
| l12-content-return-input | l12-capture | broadcast | mpc-first-broadcast | yes | l12-capture-aux8, l12-capture-aux9 |
| l12-voice-return-input | l12-capture | broadcast | mpc-first-broadcast | yes | l12-capture-aux10, l12-capture-aux11 |
| mpc-private-monitor-output | mpc-usb-output | private | private-monitor-fail-closed | yes | mpc-usb-output-aux8, mpc-usb-output-aux9 |

### Channel Pairs

| ID | Left Port | Right Port | Route Class | Label |
| --- | --- | --- | --- | --- |
| mpc-content-return | mpc-usb-output-aux0 | mpc-usb-output-aux1 | mpc-first-broadcast | MPC content return to L-12 CH9/10 |
| mpc-voice-return | mpc-usb-output-aux2 | mpc-usb-output-aux3 | mpc-first-broadcast | MPC voice return to L-12 CH11/12 |
| mpc-private-monitor | mpc-usb-output-aux8 | mpc-usb-output-aux9 | private-monitor-fail-closed | MPC private monitor ingress AUX8/9 |

### Physical Edges

| ID | Source Ports | Target Ports | Medium | Route Class | Channel Pair | Fail Closed |
| --- | --- | --- | --- | --- | --- | --- |
| mpc-out-1-2-to-l12-ch9-10 | mpc-usb-output-aux0, mpc-usb-output-aux1 | l12-capture-aux8, l12-capture-aux9 | trs | mpc-first-broadcast | mpc-content-return | yes |
| mpc-out-3-4-to-l12-ch11-12 | mpc-usb-output-aux2, mpc-usb-output-aux3 | l12-capture-aux10, l12-capture-aux11 | trs | mpc-first-broadcast | mpc-voice-return | yes |

### Hardware Patches

| ID | Source Device | Target Device | Route Class | Fail Closed | Physical Edges |
| --- | --- | --- | --- | --- | --- |
| mpc-trs-returns-to-l12 | mpc-live-iii | zoom-l12 | mpc-first-broadcast | yes | mpc-out-1-2-to-l12-ch9-10, mpc-out-3-4-to-l12-ch11-12 |

### Optional Device Lifecycle

| Device | Nodes | Default State | Absent OK | Fail Closed | Promotion Gate |
| --- | --- | --- | --- | --- | --- |
| blue-yeti-headphone-output | yeti-headphone-output | absent | yes | yes | private-monitor-only |
| respeaker-xvf3800 | respeaker-xvf3800-array-source, respeaker-xvf3800-aec-reference-output | absent | yes | yes | explicit-operator-promotion |
| torso-s4 | s4-analog-out-1-2, s4-source, s4-output, s4-loopback | absent | yes | yes | route-policy-owner |
| dirtywave-m8 | m8-usb-source, m8-instrument-capture, m8-loudnorm | absent | yes | yes | reconciler-owned-handoff |
| polyend-tracker-mini | polyend-instrument-source, polyend-instrument-capture, polyend-loudnorm | absent | yes | yes | route-policy-owner |
<!-- audio-graph-v4-generated:end -->

## 4. Source Inventory

| Source | Service/Origin | PipeWire Entry Point | Chain | Status |
|--------|---------------|---------------------|-------|--------|
| SoundCloud music | `hapax-music-player.service` (yt-dlp → ffmpeg → pw-cat) | hapax-music-loudnorm (direct) | loudnorm → MPC AUX0/1 | Active |
| TTS voice | `hapax-daimonion.service` (Chatterbox/Kokoro → role.broadcast) | hapax-voice-fx-capture | voice-fx → loudnorm → MPC AUX2/3 | Active |
| PC multimedia | WirePlumber role.multimedia loopback | hapax-pc-loudnorm | pc-loudnorm → MPC AUX4/5 | Active |
| YouTube bed | Browser/OBS → manual sink selection | hapax-yt-loudnorm | yt-loudnorm → MPC AUX6/7 | Active |
| Private assistant | WirePlumber role.assistant loopback | hapax-private | private-monitor-bridge → MPC AUX8/9 | Active |
| Notifications | WirePlumber role.notification loopback | hapax-notification-private | notification-monitor-bridge → MPC AUX8/9 | Active |
| M8 instrument | USB audio device (Dirtywave M8) | hapax-m8-loudnorm | m8-loudnorm → L-12 USB return FL/FR | Transient |
| Operator voice | Rode Wireless Pro → L-12 physical CH5 | L-12 direct (no PipeWire) | L-12 hardware mix → USB capture | Always on |
| L-12 instruments | Physical mics/guitars on L-12 CH1-8 | hapax-l12-evilpet-capture | evilpet-capture → livestream-tap | Always on |

**SoundCloud is NOT a browser.** The music daemon (`hapax-music-player.service`)
uses yt-dlp to download tracks and ffmpeg + pw-cat to pipe audio directly to
`hapax-music-loudnorm`. The playlist lives at
`~/hapax-state/music-repo/soundcloud.jsonl`, replenished by
`hapax-soundcloud-adapter.service`.

## 5. Signal Flow Per Use Case

### 5a. TTS Voice → Livestream

```
Daimonion (role.broadcast)
  → output.loopback.sink.role.broadcast
  → hapax-voice-fx-capture (EQ: HP, low-mid cut, presence, air)
  → hapax-voice-fx-playback
  → hapax-loudnorm-capture (true-peak limiter, -18 dBFS)
  → hapax-loudnorm-playback
  → MPC USB IN 3/4 (AUX2/3)
  → MPC DSP mix → MPC TRS Out 3/4
  → L-12 CH 11/12 (physical)
  → L-12 USB capture AUX10/11
  → hapax-l12-usb-return-capture → hapax-l12-usb-return-playback
  → hapax-livestream-tap
  → hapax-broadcast-master-capture → hapax-broadcast-normalized
  → hapax-obs-broadcast-remap → OBS
```

### 5b. Music → Livestream

```
hapax-music-player.service (pw-cat → hapax-music-loudnorm directly)
  → hapax-music-loudnorm (true-peak limiter, -18 dBFS)
  → hapax-music-loudnorm-playback
  → MPC USB IN 1/2 (AUX0/1)
  → MPC DSP mix → MPC TRS Out 1/2
  → L-12 CH 9/10 → ... → livestream-tap → OBS
```

Music ducking: `hapax-audio-ducker.service` writes gain to `hapax-music-duck`
mixer nodes when operator voice (Rode VAD) or TTS is active.

### 5c. Private Audio (NOT Broadcast)

```
role.assistant → hapax-private (null sink)
  → hapax-private:monitor → hapax-private-monitor-capture
  → hapax-private-playback → MPC AUX8/9
  → MPC headphone only (NOT routed to TRS outputs)
```

## 6. Critical Invariants

| # | Invariant | Failure Mode |
|---|-----------|-------------|
| 1 | Anything entering L-12 reaches broadcast | Silent audio leak if L-12 input isn't captured |
| 2 | L-12 hardware settings never change | Every problem is software-side |
| 3 | MPC AUX assignments are fixed (§2) | Wrong audio on wrong bus |
| 4 | OBS binds to broadcast-normalized or obs-broadcast-remap only | Bypasses master limiter |
| 5 | TTS path: role.broadcast → voice-fx → loudnorm → MPC AUX2/3 | Voice silently disappears |
| 6 | Broadcast loopback must never be muted | Graph looks correct but no audio flows |
| 7 | No webcam mics in broadcast chain | Room audio leaks to stream |
| 8 | No dry host signal to livestream (MPC-first) | Untreated audio on stream |

## 7. Node Protection Status (2026-05-20)

| Node | autoconnect | dont-fallback | Reconciler | Protection |
|------|------------|--------------|-----------|-----------|
| hapax-music-loudnorm-playback | false | true | yes | FULL |
| hapax-loudnorm-playback (TTS) | false | true | yes | FULL |
| hapax-pc-loudnorm-playback | false | true | yes | FULL |
| hapax-yt-loudnorm-playback | false | true | yes | FULL |
| hapax-music-duck-playback | — | true | yes | FULL |
| hapax-pc-broadcast-playback | false | true | — | GUARDED |
| hapax-polyend-loudnorm-playback | false | true | — | GUARDED |
| hapax-private-playback | false | true | yes | FULL + HEAVY |
| hapax-notification-private-playback | false | true | yes | FULL + HEAVY |
| hapax-pc-monitor-playback | — | true | — | TARGET + HEAVY |
| hapax-m8-loudnorm-playback | false | true | yes | FULL |

## 8. Reconciler & Sidechain Ducking

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

## 9. Troubleshooting

| Symptom | Check |
|---------|-------|
| No music playing | `systemctl --user status hapax-music-player` + `wc -l ~/hapax-state/music-repo/soundcloud.jsonl` |
| TTS silent on stream | `scripts/hapax-audio-routing-check` + check broadcast loopback mute |
| Webcam mic on stream | `pw-link -l \| grep 'alsa_input.usb-046d'` + verify WirePlumber block |
| Audio bleeding | `pw-link -l` for unauthorized links + reconciler forbidden-links |
| L-12 USB missing | `pw-cli ls Node \| grep -i zoom` + physical reconnect |
| No audio at all | Check MPC USB device present + reconciler running + PipeWire healthy |

## 10. Decommissioned

| Item | Retired | Notes |
|------|---------|-------|
| PreSonus Studio 24c | 2026-05-03 | Archived; never mention |
| hapax-tts-duck (software ducker) | 2026-04-23 | Replaced by MPC-routed voice chain |
| hapax-source-activate.timer | 2026-05-20 | Was regenerating configs; permanently disabled |

## 11. Key Files

| File | Purpose |
|------|---------|
| `~/.config/pipewire/pipewire.conf.d/hapax-*.conf` | Filter-chain definitions |
| `~/.config/hapax/audio-link-map.conf` | Reconciler desired-state links |
| `~/.config/hapax/audio-forbidden-links.conf` | Reconciler forbidden links |
| `~/.config/wireplumber/wireplumber.conf.d/80-block-webcam-mic-autolink.conf` | Webcam mic block |
| `scripts/hapax-audio-routing-check` | 11-invariant validation |
| `shared/audio_loudness.py` | Loudness constants (gain values SSOT) |
