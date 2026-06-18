# Audio Topology Reference Manual

Single source of truth for the Hapax PipeWire broadcast audio architecture.
All other audio docs (runbook, handoff, config README) defer to this document.

**Architecture principle:** The MOTU UltraLite mk5 is the single analog I/O hub.
Hapax's TTS voice is modulated by the Torso S-4 via an **analog hardware insert**
(dry send out the mk5, processed return back in). The operator's Rode mic, music,
and YouTube are summed **PC-side in software** (`hapax-livestream-tap`), limited, and
sent to OBS. The Faderfox MX12 is a **redundant manual control surface** that rides
on top of automation. Under-specified host sources have no broadcast egress.

**Last verified:** 2026-06-02 (`scripts/hapax-audio-routing-check` → all invariants pass)

---

## 1. Hardware Signal Path

```
  ┌──────────────────────────────── HOST PC (PipeWire) ───────────────────────────────┐
  │  TTS(role.broadcast) → voice-fx → loudnorm ─┐                                       │
  │  Rode(mk5 IN1) → mic-rode ──────────────────┤                                       │
  │  music → music-loudnorm ────────(duck)──────┤                                       │
  │  youtube → yt-loudnorm ─────────(duck)──────┤                                       │
  │  PC / private / notification → fail-closed (no broadcast egress)                    │
  └───────────────┬─────────────────────────────┴──────────────────────────────────────┘
                  │ dry voice            ▲ wet voice / Rode / music / youtube
        mk5 OUT 3/4│ (pro-output AUX2/3)  │ (→ hapax-livestream-tap sum bus)
                  ▼                       │
        ┌──────────────────┐   mk5 IN 3/4 (pro-input AUX2/3)
        │   TORSO S-4       │──────────────┘
        │  Material=Bypass  │   (granular / filter / color / space on the line input)
        └──────────────────┘
                                hapax-livestream-tap (software sum)
                                  → broadcast-master (safety-net limiter)
                                  → broadcast-normalized → obs-broadcast-remap → OBS → Twitch/YouTube
```

The mk5 is pinned to the **pro-audio** profile (WirePlumber
`14-hapax-mk5-pro-audio.conf`), exposing `alsa_output.usb-MOTU_UltraLite-mk5_…pro-output-0`
and `alsa_input.usb-MOTU_UltraLite-mk5_…pro-input-0` at 48 kHz.

## 2. mk5 Channel Map (operator-wired)

| Jack | PipeWire port | Connects | Role |
|------|---------------|----------|------|
| IN 1 | `pro-input-0:capture_AUX0` (mono) | Rode Wireless Pro | operator voice |
| IN 2 | `pro-input-0:capture_AUX1` (mono) | Cortado MKIII contact mic | perceptual / quarantine (`contact_mic`; NOT broadcast — see `config/perception-registry.yaml` cortado.hw_source) |
| IN 3 | `pro-input-0:capture_AUX2` | S-4 line out 1 | wet voice return L |
| IN 4 | `pro-input-0:capture_AUX3` | S-4 line out 2 | wet voice return R |
| OUT 3 | `pro-output-0:playback_AUX2` | S-4 line in 1 | dry voice send L |
| OUT 4 | `pro-output-0:playback_AUX3` | S-4 line in 2 | dry voice send R |
| Phones | `pro-output-0:playback_AUX10/11` | headphones | private/operator monitor |
| Main | `pro-output-0:playback_AUX0/1` | monitors | operator monitor (not broadcast) |

The S-4 must be in a `Material=Bypass` scene so its line inputs run through the FX
(granular/filter/color/space). The dynamic router recalls Bypass voice scenes
(`VOCAL-COMPANION` prog 1, `VOICE-SELF-MOD` prog 11) over MIDI; see `shared/s4_scenes.py`.

## 3. Source Inventory

| Source | Service/Origin | PipeWire entry | Chain | Status |
|--------|---------------|----------------|-------|--------|
| TTS voice | `hapax-daimonion` → role.broadcast | hapax-voice-fx-capture | voice-fx → loudnorm → mk5 OUT3/4 → S-4 → mk5 IN3/4 → voice-wet → tap | Active |
| Operator voice | Rode Wireless Pro → mk5 IN 1 | hapax-mic-rode-capture | mic-rode → livestream-tap | Active (never dropped) |
| SoundCloud music | `hapax-music-player.service` (yt-dlp → pw-cat) | hapax-music-loudnorm | loudnorm → livestream-tap | Active |
| YouTube bed | browser/OBS → yt sink | hapax-yt-loudnorm | loudnorm → livestream-tap | Active when used |
| PC multimedia | WirePlumber role.multimedia | hapax-pc-loudnorm | no broadcast egress | Fail-closed |
| Private assistant | role.assistant | hapax-private | monitor → mk5 Phones only | Active (fenced) |
| Notifications | role.notification | hapax-notification-private | no egress | Fail-closed |

**SoundCloud is NOT a browser** — `hapax-music-player.service` (yt-dlp → ffmpeg →
pw-cat) pipes directly to `hapax-music-loudnorm`. Playlist:
`~/hapax-state/music-repo/soundcloud.jsonl` (replenished by `hapax-soundcloud-adapter`).

Default/unclassified desktop audio resolves to fail-closed `hapax-pc-loudnorm`. The
default sink must never be a physical/broadcast device (mk5, S-4, M8, Yeti, HDMI, BT).

## 4. Signal Flow — TTS Voice → Livestream (the S-4 analog insert)

```
Daimonion (role.broadcast) → input.loopback.sink.role.broadcast-output
  → hapax-voice-fx-capture (EQ) → hapax-voice-fx-playback
  → hapax-loudnorm-capture → hapax-loudnorm-playback
  → mk5 pro-output AUX2/3  ═══ analog ═══>  S-4 line in (Material=Bypass FX)
  S-4 line out  ═══ analog ═══>  mk5 pro-input AUX2/3
  → hapax-voice-wet-capture (transient clamp) → hapax-voice-wet-playback
  → hapax-livestream-tap → hapax-broadcast-master → hapax-broadcast-normalized
  → hapax-obs-broadcast-remap → OBS
```

Only the **wet** (S-4-processed) voice reaches broadcast; the dry send leaves the PC
and never enters the sum bus. Music ducking: `hapax-audio-ducker` writes the SSOT
duck depth (operator-VAD −12 dB, TTS / hosting-segment −8 dB, deepest-duck-wins) to
the dedicated `hapax-music-duck-mk5` node inserted between `hapax-music-loudnorm` and
the `livestream-tap` sum (`music-loudnorm → music-duck-mk5 → livestream-tap`,
reconciler-owned). It does **not** lower the `hapax-music-loudnorm` 0.35 passthrough
gain — that node is a pinned audited passthrough, and co-opting it would conflate
loudness-normalization with ducking. Default duck gain 1.0 = transparent (a dead
daemon fails OPEN; music never silenced). Deploying the `hapax-music-duck-mk5` conf
is alpha-gated: the node must exist live before the regenerated link map is applied.

## 5. Critical Invariants (validated by `scripts/hapax-audio-routing-check`)

| # | Invariant | Failure mode |
|---|-----------|-------------|
| 1 | TTS: role.broadcast → voice-fx → loudnorm → mk5 OUT AUX2/3 | Voice never reaches the S-4 |
| 2 | S-4 wet: mk5 IN AUX2/3 → voice-wet → livestream-tap | Modulated voice silent on stream |
| 3 | Rode: mk5 IN AUX0 → mic-rode → livestream-tap | Operator voice dropped |
| 4 | music/yt → livestream-tap | Beds silent |
| 5 | livestream-tap → broadcast-master → broadcast-normalized → obs-remap → OBS | Bypasses limiter / no audio |
| 6 | private/PC/notification fenced from tap, master, and mk5 dry send AUX2/3 | Private/PC leaks to broadcast |
| 7 | default sink = fail-closed pc-loudnorm | Desktop audio hits hardware/broadcast |
| 8 | ALSA-targeting confs set passive/dont-reconnect | Webcam-mic room-hijack on device loss |
| 9 | no webcam mic in voice-wet/mic-rode capture | Room audio leaks |
| 10 | no retired L-12/MPC node feeds the tap | Stale routing |
| 11 | broadcast/voice nodes not muted | Graph correct but silent |
| 12 | reconciler active + link-map targets mk5 + forbidden-links present | Boundaries unmaintained |

## 6. Reconciler, Ducking, Manual Control

- **Reconciler** `hapax-audio-reconciler.service` — reads
  `~/.config/hapax/audio-link-map.conf` + `audio-forbidden-links.conf`, ticks ~2 s,
  creates missing desired links, destroys forbidden ones, and restores reviewed
  public egress nodes only when `wpctl get-volume` reports zero-volume drift.
  It does not own Faderfox/manual-trim targets or content stems. Recheck with
  `scripts/hapax-audio-routing-check` and the reconciler fake-`wpctl` tests.
- **Ducker** `hapax-audio-ducker.service` — writes the SSOT duck depth to the
  dedicated `hapax-music-duck-mk5` node under operator voice, broadcast TTS, or a
  live hosting segment (deepest-duck-wins). Single duck owner; no software TTS duck
  on mk5 (Hapax voice is analog via the S-4 insert). Reads the live mk5 Rode
  (`hapax-mic-rode-capture`) for operator VAD. Resolves node names from the topology
  SSOT (fail-open) so a future migration is picked up, not silently re-broken.
- **Dynamic router** `hapax-audio-router.service` — 5 Hz arbiter; recalls S-4 Bypass
  voice scenes over MIDI (Evil Pet decommissioned 2026-06).
- **Faderfox MX12 bridge** `hapax-faderfox-bridge.service` — `agents/faderfox_bridge.py`
  maps MX12 fader CC → a per-channel **manual trim** (PipeWire node volume) that
  MULTIPLIES the automation gain; map in `config/equipment/faderfox-mx12-controls.yaml`
  (verify CCs with `--learn`). Fail-safe: daemon death leaves automation governing.
- **Validation** `scripts/hapax-audio-routing-check` — run before/after any change; REVERT on failure.

## 7. Decommissioned

| Item | Retired | Notes |
|------|---------|-------|
| Zoom LiveTrak L-12 | 2026-05/06 | Hardware mixer; replaced by PC-side software sum |
| Akai MPC Live III | 2026-06 | USB interface; replaced by MOTU mk5 |
| "Evil Pet" hardware FX | 2026-06 | Replaced by the Torso S-4 analog insert |
| hapax-tts-duck (software ducker) | 2026-04-23 | Replaced by MPC-routed voice chain (now mk5) |
| hapax-music-duck (L-12 USB return ducker) | 2026-06 | Replaced by `hapax-music-duck-mk5` (governed mk5-native node, reconciler-owned) |

## 8. Key Files

| File | Purpose |
|------|---------|
| `config/pipewire/hapax-voice-wet.conf` | S-4 wet return capture |
| `config/pipewire/hapax-mic-rode.conf` | Rode mic capture |
| `config/wireplumber/14-hapax-mk5-pro-audio.conf` | mk5 profile pin |
| `config/hapax/audio-link-map.conf` | Reconciler desired-state links |
| `config/hapax/audio-forbidden-links.conf` | Reconciler forbidden links |
| `config/equipment/faderfox-mx12-controls.yaml` | MX12 fader → node map |
| `agents/faderfox_bridge.py` | MX12 → PipeWire manual-trim daemon |
| `scripts/hapax-audio-routing-check` | invariant validation |
| `shared/s4_scenes.py` | S-4 Bypass FX scene library |
