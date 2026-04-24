# Livestream Audio Unified Architecture — Design Spec

**Status:** approved-by-operator (2026-04-23). Supersedes the ad-hoc per-source loudnorm tunings.

**Origin research:** `docs/research/2026-04-23-livestream-audio-unified-architecture.md`

**Goal (operator, verbatim):** "I am CONSTANTLY having to either mess with faders myself or worry about pumping or poor ducking or getting levels adjusted by claude code on the software side. I never want to worry about this again." → Easy to maintain, easy to extend, reliable, excellent listener experience. **One time forever.**

This spec crystallizes the operator-confirmed decisions on top of the research doc. Implementation phases are in the companion plan: `docs/superpowers/plans/2026-04-23-livestream-audio-unified-architecture-plan.md`.

## 1. Operator-confirmed decisions (2026-04-23)

| # | Decision | Notes |
|---|---|---|
| 1 | **Egress target = −14 LUFS-I, −1.0 dBTP true-peak.** YouTube-aligned. | Single canonical constant; same value used across stream egress, RTMP encoder, OBS audio mixer. |
| 2 | **All sources route through Evil Pet by default; nothing dry by default.** Routing topology is declarative + per-source overridable in a single config file readable by both operator and Hapax. | Big shift from research-doc draft (which had music bypass Evil Pet). New default: every source → L-12 channel that lands on AUX-B → Evil Pet → broadcast. Override via `dry: true` per source in `config/audio-routing.yaml`. |
| 3 | **Retire `agents/studio_compositor/audio_ducking.py` 4-state FSM and its `hapax-ytube-ducked` / `hapax-24c-ducked` sinks** in Phase 5. | Subsumed by sidechain ducking at the broadcast bus. |
| 4 | **Sidechain envelope detection on `hapax-pn-tts`** as the TTS-active trigger (NOT reviving CPAL `tts_active` SHM publisher). | Fail-open if daimonion crashes; no liveness coupling. |
| 5 | **Notifications stay on Yeti headphone jack only** for now. | Tracked as future-TODO; not a blocker. |
| 6 | **One-time L-12 LINE switch + trim recalibration on CH11/12 during Phase 1 deploy** is fine. | Operator present, 5-minute action. PipeWire restarts during Phase 1+ are also fine **while operator is present** — but see #7. |
| 7 | **NEW: OBS-source survivability across PipeWire restarts is in scope.** When operator is away, PipeWire restart currently forces manual remove + re-add of the OBS audio source. Phase 2 fixes this at the root. | Acceptance: `systemctl --user restart pipewire wireplumber pipewire-pulse` → OBS audio chain is reading the same source name post-restart, no operator touch required. |

## 2. Architecture in one diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          SOURCES                                     │
├──────────────┬──────────────┬──────────────┬───────────────────────┤
│  music       │  TTS         │  vinyl       │  voice (Rode)         │
│  ↓           │  ↓           │  ↓           │  ↓                    │
│  pre-norm    │  pre-norm    │  pre-norm    │  pre-norm             │
│  −18 LUFS    │  −18 LUFS    │  −18 LUFS    │  −18 LUFS             │
│  −1 dBTP     │  −1 dBTP     │  −1 dBTP     │  −1 dBTP              │
└──────┬───────┴──────┬───────┴──────┬───────┴────────┬──────────────┘
       │              │              │                │
       └──────────────┴──────────────┴────────────────┘
                                   │
                  ┌────────────────▼────────────────┐
                  │  ROUTING POLICY (config/audio-  │
                  │  routing.yaml)                  │
                  │                                 │
                  │  per-source: wet=true (default) │
                  │              | dry=true         │
                  └────────────────┬────────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              │                                          │
              ▼                                          ▼
       ┌──────────────┐                          ┌──────────────┐
       │  WET path    │                          │  DRY path    │
       │  → L-12 CH   │                          │  → broadcast │
       │  → AUX-B     │                          │  bus direct  │
       │  → Evil Pet  │                          │              │
       │  → broadcast │                          │              │
       │  bus         │                          │              │
       └──────┬───────┘                          └──────┬───────┘
              │                                          │
              └────────────────┬─────────────────────────┘
                               │
                  ┌────────────▼─────────────┐
                  │ DUCKING MATRIX           │
                  │ (sidechain LV2 comps)    │
                  │                          │
                  │  trigger.operator-vad ─→ duck music −12 dB │
                  │  trigger.tts-active   ─→ duck music −8 dB  │
                  └────────────┬─────────────┘
                               │
                  ┌────────────▼─────────────┐
                  │ MASTER BUS               │
                  │ hapax-broadcast-master   │
                  │ true-peak limiter        │
                  │ −1.0 dBTP ceiling        │
                  │ ebur128 metering →       │
                  │ Prometheus               │
                  └────────────┬─────────────┘
                               │
                  ┌────────────▼─────────────┐
                  │ STABLE OBS-INGEST SINK   │
                  │ hapax-obs-ingest         │
                  │ (string-stable name,     │
                  │  survives PW restart)    │
                  └────────────┬─────────────┘
                               │
                  ┌────────────▼─────────────┐
                  │ OBS audio source         │
                  │ → NVENC → AAC → RTMP →   │
                  │ YouTube                  │
                  └──────────────────────────┘
```

## 3. Single source of truth — files

| File | Purpose | Owner |
|---|---|---|
| `shared/audio_loudness.py` | All LUFS / dBTP / dB / ms numeric constants. Imported by every audio-touching agent + by config-generator. | spec-controlled |
| `config/audio-routing.yaml` | Per-source declarative policy: `name`, `producer`, `wet|dry`, `pre_norm_target_lufs`, `sidechain_behavior` (`ducked_by` list), `broadcast`, `notes`. | operator + Hapax editable |
| `config/pipewire/generated/*.conf` | PipeWire filter-chain confs **GENERATED** from `audio-routing.yaml` + `shared/audio_loudness.py` by `scripts/generate-pipewire-audio-confs.py`. Never hand-edit. | generated |
| `config/pipewire/hapax-broadcast-master.conf` | The master safety-net (true-peak limiter + ebur128 meter). Derived from constants. | generated |
| `config/pipewire/hapax-obs-ingest.conf` | The string-stable named ingest sink OBS reads. | generated |
| `agents/audio_metering/` | libebur128 sidecar that listens on every named tap, exports Prometheus loudness metrics. | new |

**Hand-edit policy:** the only audio files an operator or Claude session edits are `shared/audio_loudness.py`, `config/audio-routing.yaml`, and the generator script. PipeWire `.conf` regen happens via `scripts/generate-pipewire-audio-confs.py --apply` (writes to `~/.config/pipewire/pipewire.conf.d/`, hot-reload via `systemctl --user reload pipewire` or restart if needed).

## 4. `shared/audio_loudness.py` schema (Phase 1)

```python
"""Single source of truth for every loudness / dynamics constant in the
livestream audio chain. NEVER hand-tune a sc4m threshold or a hard_limiter
ceiling outside this module — instead change the constant here and re-run
the PipeWire conf generator.
"""

from __future__ import annotations

# ── Egress (broadcast bus → OBS → YouTube) ─────────────────────────────
EGRESS_TARGET_LUFS_I: float = -14.0   # YouTube-aligned, operator confirmed 2026-04-23
EGRESS_TRUE_PEAK_DBTP: float = -1.0   # Brick-wall ceiling on master limiter
EGRESS_LRA_MAX_LU: float = 11.0       # Loudness range cap (broadcast-friendly)

# ── Per-source pre-normalization ──────────────────────────────────────
# Every source pre-normalizes to this target BEFORE entering the routing
# matrix. Sources arrive at the master bus already shaped; the master
# limiter is a safety net, not a primary level control.
PRE_NORM_TARGET_LUFS_I: float = -18.0
PRE_NORM_TRUE_PEAK_DBTP: float = -1.0
PRE_NORM_LRA_MAX_LU: float = 7.0

# ── Sidechain ducking depths (Phase 4) ────────────────────────────────
DUCK_DEPTH_OPERATOR_VOICE_DB: float = -12.0  # Music ducks 12 dB under operator voice
DUCK_DEPTH_TTS_DB: float = -8.0              # Music ducks 8 dB under TTS
DUCK_ATTACK_MS: float = 10.0                 # Sidechain attack
DUCK_RELEASE_MS: float = 400.0               # Slow release, no pumping
DUCK_LOOKAHEAD_MS: float = 5.0

# ── Master safety-net limiter ─────────────────────────────────────────
MASTER_LIMITER_LOOKAHEAD_MS: float = 5.0
MASTER_LIMITER_RELEASE_MS: float = 50.0       # Fast release on transient

# ── Headroom budget ───────────────────────────────────────────────────
HEADROOM_PER_STAGE_DB: float = 6.0           # Reserved per stage for transients
```

The generator script reads this module, substitutes constants into Jinja-style PipeWire conf templates, and writes the live confs.

## 5. `config/audio-routing.yaml` schema (Phase 6)

```yaml
# Declarative per-source routing policy. Operator + Hapax both edit this.
# Generator script writes the corresponding PipeWire confs.
sources:
  - name: music
    producer: hapax-music-player.service
    pre_norm: true                    # default true
    target_lufs_i: -18.0              # override default (PRE_NORM_TARGET_LUFS_I)
    routing: wet                      # default 'wet' = through Evil Pet via L-12 CH 11/12 → AUX-B
                                      # alternative: 'dry' = direct to broadcast bus
    ducked_by:                        # list of triggers that duck this source
      - operator_voice
      - tts
    broadcast: true                   # appears in master mix
    notes: "Lo-fi/boom-bap pool, oudepode + epidemic"

  - name: tts
    producer: hapax-daimonion.service
    pre_norm: true
    routing: wet                       # TTS through Evil Pet for character
    ducked_by: []                      # TTS doesn't get ducked (it's the trigger)
    broadcast: true

  - name: operator_voice
    producer: alsa_input.usb-PreSonus-Studio_24c.mic1
    pre_norm: true
    routing: wet                       # Rode voice through Evil Pet
    ducked_by: []
    broadcast: true

  - name: notifications
    producer: output.loopback.sink.role.notification
    pre_norm: false                    # Yeti monitor, never broadcast
    routing: dry                       # Headphone-only path
    broadcast: false                   # Operator override #5

  - name: contact_mic
    producer: alsa_input.usb-PreSonus-Studio_24c.mic2
    pre_norm: false
    broadcast: false                   # Perception only, never broadcast
```

Adding a new source = 1 commit, 1 file edit. Generator picks it up on next run.

## 6. Phase boundaries (acceptance criteria mapped to numbers)

Detail in `docs/superpowers/plans/2026-04-23-livestream-audio-unified-architecture-plan.md`. Headlines:

- **Phase 1 — Master safety net + OBS rebind + L-12 trim** (operator-present required)
- **Phase 2 — OBS-restart survivability** (zero-touch PW restart)
- **Phase 3 — Per-source pre-normalizers** (every source → −18 LUFS pre-norm)
- **Phase 4 — Sidechain ducking** (operator-VAD + TTS-active triggers)
- **Phase 5 — Retire `audio_ducking.py` + ducked sinks**
- **Phase 6 — Routing-as-code** (`config/audio-routing.yaml` + generator)
- **Phase 7 — Loudness telemetry** (libebur128 sidecar → Prometheus)
- **Phase 8 — Regression harness** (synthetic-stimulus tests)

## 7. Invariants the design preserves

- L-12 == livestream invariant: anything in L-12 reaches broadcast.
- Operator speech NEVER dropped (AEC, not VAD-frame-drop).
- Hapax-livestream sink is null-sink (no speaker loopback risk).
- Operator's L-12 faders sit at unity and STAY at unity post-Phase-1.
- PipeWire restarts never require operator to touch OBS post-Phase-2.
- Adding/removing a source never requires touching upstream stages.

## 8. Things this spec explicitly does NOT do

- Replace the WirePlumber role-based loopback system. Roles still exist; they're how sources reach the routing layer.
- Touch the AEC pipeline (separate concern; existing solution stays per memory `reference_pipewire_echo_cancel_enotsup_loop` until that's also re-engineered).
- Govern operator-monitor (headphone) audio. That's a separate path, kept on Yeti.
- Govern TTS character (the Voice FX presets). Those remain operator-curated.

## 9. Approval

Confirmed by operator 2026-04-23 with:
> "1. recommended 2. we need to make all pathing dynamic and optional in an easy to manage way for both me and for Hapax. but by default EVERYTHING should go through the evil pet and NOTHING should be dry. 3. y 4. whatever is rec 5. yes, until we have a better solution 6. Yup as long as I am here I don't care about pipewire restarts, just when I am away because I have to manually remove and then re-add the OBS source sink — but maybe we can fix this problem? We DEFINITELY SHOULD."
