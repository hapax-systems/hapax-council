---
date: 2026-04-21
author: delta
audience: operator + delta (implementation)
register: scientific, neutral
status: design — ready for operator ratification of target LUFS
scope: level-matching design for every PC-originated stream entering L-12 CH 11/12 via Ryzen analog-stereo, so the single hardware fader calibrates once across a dissimilar source set
source_trigger: operator 2026-04-21 — "figure out the optimal levels for every stream that enters my l12 via pc so that fader isn't doing dumb things over a dissimilar group of streams"
---

# PC → L-12 CH 11/12 level-matching design

## Problem

L-12 CH 11/12 receives Ryzen analog-stereo output, which mixes a dissimilar set of PC-originated streams:

| Stream source | Typical unprocessed peak | Typical unprocessed RMS | Spectral character |
|---|---|---|---|
| YouTube music beds (via yt-loudnorm OR raw) | −3 to 0 dBFS | −14 to −9 LUFS | broadband, wide dynamics |
| Hapax voice (Kokoro TTS) | −3 to −1 dBFS | −16 to −12 LUFS | mid-band dominant, fast transients |
| Browser / streaming video | −1 to 0 dBFS | −24 to −9 LUFS (highly variable) | broadband, unpredictable |
| Notifications (chimes, system) | 0 dBFS | −18 to −6 LUFS peak-heavy | transient, sparse |
| PC-audio general | wildly variable | wildly variable | anything |

With unmatched levels, a single L-12 CH 11/12 trim is a compromise: set too high, voice + chimes clip; set too low, YT music is inaudible. Operator spends cognitive load on the fader that should be spent on the stream.

## Principle

**Every PC-originated stream must exit Ryzen at the same target loudness.** The target is defined as:

- **Integrated loudness:** **−18 LUFS** (industry standard for digital sources entering a line-level mixer input)
- **True peak:** **−1 dBTP** (standard ceiling against inter-sample peak clipping at ADC / codec)
- **Rationale:** −18 LUFS matches pro audio "0 VU" reference — professional digital line level, the convention mixers like the ZOOM L-12 are calibrated for. Keeps the L-12 CH 11/12 fader in its useful range (neither crushed against the top nor buried at the bottom) when set at unity. Downstream broadcast deliverable normalization (YouTube normalizes to −14 LUFS, EBU R128 to −23 LUFS) happens AFTER the main mix — not our problem at this stage.

When every source hits Ryzen at −18 LUFS / −1 dBTP, the L-12 CH 11/12 trim becomes a **single additive offset** (e.g. +6 dB trim to reach −14 LUFS at main mix) that works identically for voice, music, video, notifications.

## Stream-by-stream design

### 1. YouTube music beds

**Current path:** ffmpeg (yt-player) → role.multimedia loopback → pc-loudnorm → Ryzen.

**Current config (`config/pipewire/pc-loudnorm.conf`):**
- threshold −14 dB, ratio 3:1, makeup +3 dB, limit −1 dBTP
- Integrated loudness output: ~−14 LUFS

**Target config changes:**
- Lower threshold to −16 dB (tighter compression floor)
- Keep ratio 3:1
- **Drop makeup gain from +3 dB to −1 dB**
- Keep limit at −1 dBTP
- Integrated loudness output becomes ~−18 LUFS

Alternatively, add a dedicated yt-loudnorm between the yt-player ffmpeg output and pc-loudnorm so YT's wide dynamics get pre-conditioned before hitting pc-loudnorm's broadband compressor. This is already scaffolded as `hapax-yt-loudnorm` sink (see yt-loudnorm.conf) but it's IDLE — ffmpeg bypasses it. Wiring yt-player through it is a separate fix (not in this design's scope).

### 2. Hapax voice (TTS)

**Designed path:** daimonion pw-cat → voice-fx-chain (biquad EQ) → voice-fx-loudnorm (SC4 + limiter) → Ryzen.

**Currently BYPASSED** — streams hit role.assistant loopback → Ryzen directly. See `docs/research/2026-04-21-livestream-surface-inventory-audit.md` §3.K and cc-task lssh-012. Persistent fix lands in `config/wireplumber/55-hapax-voice-role-retarget.conf` (this repo).

**Current voice-fx-loudnorm config:**
- SC4 threshold −18 dB, ratio 3:1, makeup 0 dB
- Limiter ceiling −1 dBTP
- Integrated loudness output: ~−14 LUFS (matches pc-loudnorm old target)

**Target config changes:**
- Keep SC4 threshold −18 dB, ratio 3:1
- **Add −1 dB makeup gain** (so output sits at −18 LUFS integrated)
- Keep limiter ceiling at −1 dBTP
- Voice-fx-chain UPSTREAM stays unchanged (EQ is intent-preserving; loudness math is on voice-fx-loudnorm).

### 3. Browser / streaming video (generic PC audio)

**Current path:** browser → role.multimedia loopback → pc-loudnorm → Ryzen. Shared with YouTube beds.

**Target:** same pc-loudnorm re-tune as YouTube beds (−18 LUFS / −1 dBTP). No separate config needed.

**Caveat:** if video and music beds play simultaneously, pc-loudnorm's compressor sums them before the broadband curve fires — mix could sound over-compressed. If operator reports this, add a per-source pre-chain later. Not worth pre-solving.

### 4. Notifications (chimes, system sounds) — MUST LEAVE L-12

**Current:** `hapax-notification-private` routes notifications to L-12 `analog-surround-40` (MASTER OUT monitor only), explicitly NOT captured by `hapax-l12-evilpet-capture`.

**Operator invariant 2026-04-21** (`feedback_l12_equals_livestream_invariant.md`): *"Nothing should go to the l12 that shouldn't end up in the livestream."* Notifications aren't meant for broadcast, so they must leave the L-12 entirely.

**Target:** retarget `hapax-notification-private-playback` to a non-L-12 monitor destination. Candidates:
- Yeti stereo microphone analog-stereo (card 10) — its headphone jack doubles as a monitor output.
- Bluetooth iLoud micro (already on-host).
- A new virtual null-sink whose monitor the operator can capture via headphone adapter or USB.

**Scope:** separate cc-task (lssh-014). Not blocking the level-matching loudnorm re-tune (this design's main thrust) — notifications were already out of scope for CH 11/12 levels; they're now also out of scope for L-12 entirely as a governance matter.

### 5. Hapax-private (DMN-internal audio)

**Current path:** Same as notifications but semantically distinct — DMN internal audio uses this path for operator-private monitoring. Goes to Ryzen today.

**Target:** leave at native levels. DMN-private is not broadcast (routed separately via L-6 ch 5 per the `hapax-private` node description). If it hits Ryzen → L-12 CH 11/12, that's a routing bug separate from level-matching.

## Summary — proposed end-state

| Source | Path | Loudness target | Config location |
|---|---|---|---|
| YouTube beds | role.multimedia → pc-loudnorm → Ryzen | −18 LUFS / −1 dBTP | pc-loudnorm.conf (re-tune) |
| Browser / video | role.multimedia → pc-loudnorm → Ryzen | −18 LUFS / −1 dBTP | pc-loudnorm.conf (shared) |
| Hapax voice | role.assistant → voice-fx-chain → voice-fx-loudnorm → Ryzen | −18 LUFS / −1 dBTP | voice-fx-loudnorm.conf (re-tune) + 55-hapax-voice-role-retarget.conf (routing fix) |
| Notifications | role.notification → hapax-notification-private → L-12 MASTER OUT (monitor only) | n/a — already isolated from broadcast | already shipped |
| DMN-private | (private monitoring; not broadcast) | unchanged | — |

After these changes land:

- L-12 CH 11/12 trim calibrated ONCE for −18 LUFS input.
- All PC-originated audio arrives at that reference level regardless of source.
- Fader does one job, predictably.

## Decisions (operator-ratified 2026-04-21: "whatever the industry says")

1. **Target: −18 LUFS integrated / −1 dBTP.** Pro audio digital line-level convention (0 VU = −18 dBFS reference). This is the standard for digital sources hitting a line-level analog mixer input like the ZOOM L-12. Downstream broadcast normalization (YouTube at −14 LUFS, EBU R128 at −23 LUFS) is a separate concern handled post-mix.
2. **Notification handling: already isolated** via `hapax-notification-private` → L-12 MASTER OUT (monitor only). Not in broadcast path. No additional work required.
3. **Deployment timing: operator-scheduled low-risk window.** Config changes require a PipeWire restart, which has a non-trivial risk of re-triggering the Ryzen HDA pin-glitch (see `reference_ryzen_codec_pin_glitch.md`). Don't hot-deploy during a live broadcast.

## Current live band-aid (non-persistent, 2026-04-21 ~23:10-23:15 UTC)

Per-stream sink-input volume attenuation to approximate the −18 LUFS design without waiting for config deploy:

| Stream | sink-input | Volume | dB |
|---|---|---|---|
| pc-loudnorm → Ryzen | SI100 | 40% | −24 dB |
| voice-fx-loudnorm → Ryzen (dormant path) | SI105 | 50% | −18 dB |
| role.assistant → Ryzen (actual voice path) | SI516 | 35% | −27 dB |
| hapax-private → Ryzen | SI93 | 100% | 0 dB |

All reset on next PipeWire restart. The persistent fixes in `config/pipewire/pc-loudnorm.conf` + `config/pipewire/voice-fx-loudnorm.conf` + the new notification loudnorm replace the need for these attenuations.

## References

- Audit: `docs/research/2026-04-21-livestream-surface-inventory-audit.md` §3.K (TTS bypass) + general audio paths
- Related: `reference_ryzen_codec_pin_glitch.md` (Ryzen HDA recovery — do not redeploy pipewire mid-stream)
- Related: `reference_default_sink_elevation_breaks_roles.md` (role-loopback routing class of failures)
- Voice chain config: `config/pipewire/voice-fx-chain.conf`, `config/pipewire/voice-fx-loudnorm.conf`
- PC loudnorm config: `config/pipewire/pc-loudnorm.conf`
- New retarget rule: `config/wireplumber/55-hapax-voice-role-retarget.conf`
- cc-tasks: lssh-012 (TTS bypass fix), lssh-013 (this design's implementation)
