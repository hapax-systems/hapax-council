# Zoom L-12 LiveTrak — scene catalogue

This document is the canonical record of L-12 console scenes. Scenes are stored on the SD card; the front-panel `Scene` button recalls. Each scene captures fader positions, EQ, mute states, and AUX/MONITOR sends — but **NOT** monitor source-toggle button states (PHONES A/B/C source selectors), so toggle-discipline relies on physical tape-marks.

The L-12 USB capture surface exposes 14 channels: strips 1–12 + MASTER L/R (13/14). MONITOR busses A–E are **not** USB-exposed by hardware design. This is the architectural anchor for `feedback_l12_equals_livestream_invariant` (inverse direction): any audio that must leave the broadcast path goes through a MONITOR bus and is structurally absent from the broadcast capture inventory.

## Scene 1 — BROADCAST (default)

The everyday broadcast scene. All channels routed at unity to the broadcast capture path (USB strips 1–12). The current wet-return predicate is AUX8/9 content return plus AUX10/11 voice return; AUX5 is legacy Evil Pet evidence and is not sufficient to prove the scene healthy.

| Channel | Source | USB capture role | MONITOR A | MONITOR B (Evil Pet send) | Phantom |
|---------|--------|---------------------------------|-----------|---------------------------|---------|
| 1 (XLR) | Evil Pet return | AUX5 | 0 (anti-feedback) | 0 (anti-feedback) | OFF |
| 2 | Cortado MKIII contact mic | AUX1 | to taste | to taste | ON (+48V) |
| 3 (XLR) | reserve | — | — | — | bank 1-4 |
| 4 | Sampler chain | AUX3 | to taste | to taste | OFF |
| 5 (XLR) | Rode Wireless Pro RX | AUX4 | to taste | to taste | OFF |
| 6 (XLR) | Evil Pet return | AUX5 (mirror of CH1) | — | 0 (anti-feedback) | OFF |
| 7-8 | reserve | — | — | — | OFF |
| 9-10 | MPC content wet return L/R | AUX8/9 content return | — | to taste | OFF |
| 11-12 | MPC Hapax voice wet return L/R | AUX10/11 voice return | — | to taste | OFF |

**MASTER fader (broadcast layer):** drives room monitors; does NOT drive USB capture (capture is pre-fader/post-comp). Operator may move freely without disturbing broadcast levels.

**AUX0 / AUX2 / AUX6–AUX7 / AUX12–AUX13 (MASTER L/R):** intentionally not bound by the broadcast wet-return predicate. `hapax-l12-usb-return-capture` now binds AUX8/9 as the content return pair and AUX10/11 as the voice return pair. `hapax-l12-evilpet-capture` remains narrowed to AUX1/3/4/5 for legacy processor-return evidence, but AUX5 alone must not make the scene green. Source: researcher report a09d834c (`docs/research/2026-04-25-l12-aggregate-monitor.md`) plus accepted `l12-scene-wet-return-rebaseline` task.

### Wet-return predicate

The source-controlled scene check is intentionally stricter than the old AUX5 + AUX10/11 model:

- AUX8 and AUX9 must both show content-return signal when programme audio is expected.
- AUX10 and AUX11 must both show voice-return signal when Hapax voice return is expected.
- AUX10/11-only evidence is stale and cannot make public egress healthy.
- Real silence on either pair remains blocking unless a later authority explicitly marks that pair intentionally idle.

If the predicate remains blocked, physically inspect the L-12 front panel before changing software: scene name should read `BROADCAST-V2`; CH9/10 and CH11/12 should be unmuted at the expected scene levels; MPC Out 1/2 should land on CH9/10; MPC Out 3/4 should land on CH11/12; USB multichannel capture should still expose 14 channels.

## Scene 8 — MONITOR-WORK

Operator monitor mix on **MONITOR OUT C** (PHONES C). Pure-hardware path — internal L-12 latency ~1–2 ms, isolated from MASTER and from MONITOR B (Evil Pet send). Used when the operator plays samplers / vinyl / PC content in time with their own performance and must NOT listen to the post-loudnorm broadcast return (latency would drag subsequent strikes).

### MONITOR C fader-mode levels

| Channel | Source | Level | Reason |
|---------|--------|-------|--------|
| CH 1 (Evil Pet return) | — | −∞ | not a live source operator drives directly |
| CH 2 (Cortado contact mic) | — | **−∞** | operator hears desk vibrations directly via bone + desk conduction; re-injecting a delayed copy drags subsequent strikes |
| CH 3 (reserve) | — | −∞ | no live source |
| CH 4 (Sampler chain) | live | to taste | operator needs to hear sampler output for performance |
| CH 5 (Rode vocal) | — | **−∞** | operator hears DRY through bone conduction; re-introducing vocal would drag |
| CH 6 (Evil Pet wet return) | — | **−∞** | operator must not lock to delayed wet — drags subsequent vocal phrases |
| CH 7-8 (reserve) | — | −∞ | no live source |
| CH 9 / 10 (Handytraxx vinyl) | live | to taste | vinyl performance reference |
| CH 11 / 12 (PC L/R) | live | to taste | PC playback reference |
| MASTER C | — | to taste | overall monitor level |

### Toggle-discipline

- **PHONES C source toggle:** physical button above the PHONES C jack. **DOWN ("own mix")**. Tape-mark required (gaffer + arrow + handwritten "DOWN") because the L-12 does NOT save toggle states in scenes.
- After a Scene 1 → Scene 8 round-trip, PHONES C toggle remains DOWN (the tape mark is the visual reminder against accidental flip).

### Verification

| # | Check | Expected |
|---|-------|----------|
| A | sampler hit (CH 4) → PHONES C latency | < 5 ms; subjectively indistinguishable from pad mechanical click |
| B | broadcast LUFS-S during Scene 8 vs Scene 1 | within 1 LU (proves MONITOR-C work didn't leak onto MASTER) |
| C | `pactl list source-outputs short \| grep alsa_input.usb-ZOOM_Corporation_L-12` | only the 14 documented strips + MASTER channels — no MONITOR busses (structural property of L-12) |
| D | Scene 1 → Scene 8 → Scene 1 round-trip | PHONES C still produces C-mix without operator touching toggle (tape mark held) |

### Photo placeholder

`docs/audio/photos/` — to be populated with:
- `l12-scene-8-monitor-c-faders.jpg` — front panel showing C-fader-mode levels
- `l12-phones-c-toggle-down-tape.jpg` — close-up of PHONES C toggle with tape mark

## Cross-references

- `config/pipewire/hapax-l12-evilpet-capture.conf` — legacy processor-return capture filter chain (AUX1/3/4/5 narrowed surface)
- `config/pipewire/hapax-l12-usb-return-capture.conf` — current wet-return capture filter chain (AUX8/9 content plus AUX10/11 voice)
- `docs/research/2026-04-25-l12-aggregate-monitor.md` — research drop that validated the pure-hardware monitor mix vs the rejected software aggregate sink
- cc-task `monitor-aggregate-l12-scene-config` — the task this doc serves
- cc-task `feedback-prevention-evilpet-capture-narrow` — companion fix that closed the inverse direction of the L-12 invariant
