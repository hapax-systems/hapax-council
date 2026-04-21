---
date: 2026-04-20
author: delta
audience: operator + alpha + delta (execution)
register: scientific, engineering-normative
status: strategy design — inventory + normalization targets + ducking matrix + impl phases
related:
  - docs/research/2026-04-20-mixquality-skeleton-design.md (§10.8 MixQuality composite metric)
  - docs/research/2026-04-14-audio-path-baseline.md (pre-24c-retirement baseline)
  - config/wireplumber/50-hapax-voice-duck.conf (shipped: role-based 3-tier duck)
  - agents/hapax_daimonion/vocal_chain.py (voice modulation CC map)
  - agents/hapax_daimonion/vinyl_chain.py (Mode D granular wash)
operator-directive-load-bearing: |
  "Make sure we have a normalization and ducking strategy for ALL audio
  and their interactions."
  + context from earlier tonight: "All of this should get normalized
  along with everything else pre-ducking operations, etc anyhow."
---

# Audio Normalization + Ducking Strategy — Full Source Matrix

## §1. Scope

Covers every audio source that can reach the broadcast aggregate
(L6 Main Mix → USB → OBS → YouTube RTMP) plus every source the
operator monitors privately (L6 Main Out → L12 → monitors; L6 Phones).
Defines:

1. Per-source normalization target (LUFS, dBFS peak, crest factor)
2. Master-bus normalization target (broadcast compliance)
3. Ducking priority matrix (who ducks whom, by how much, for what reason)
4. Enforcement mechanism (PipeWire filter-chain / WirePlumber policy /
   L6 hardware / OBS-side / combinations)
5. MixQuality coupling (gauge emits + alerts per §10.8 of mixquality-
   skeleton-design)

Out of scope (deferred to separate docs):
- Audio effect design beyond level/ducking (Evil Pet + S-4 parameter
  sculpting — covered in `vocal_chain.py` + `vinyl_chain.py`)
- Monitor-path vs broadcast-path EQ differences (separate operator
  preference work)

---

## §2. Source inventory (every audio source that can reach the mix)

| # | Source | Physical path | PipeWire node | Typical LUFS (unnormalized) | Reaches broadcast? |
|---|---|---|---|---|---|
| S1 | **Hapax TTS (Kokoro 82M CPU)** | voice-fx → PC Ryzen line-out → L6 ch 5 AUX 1 → Evil Pet → L6 ch 3 | `hapax-voice-fx-capture` → `alsa_output.pci-0000_73_00.6.analog-stereo` | -22 to -14 (variable by phoneme) | YES via Evil Pet return on ch 3 |
| S2 | **Vinyl (Korg Handytrax)** | analog → L6 ch 4 (+ AUX 1 to Evil Pet when Mode D) | L6 multitrack ch 4 | -18 to -6 (cut-dependent) | YES via ch 4 fader + optional Mode-D return |
| S3 | **Operator voice (Rode Wireless Pro)** | receiver XLR → L6 ch 1 | L6 multitrack ch 1 (pending patch) | -22 to -10 | YES via ch 1 fader |
| S4 | **Contact mic (Cortado MKIII)** | XLR +48V → L6 ch 2 | L6 multitrack ch 2 | -40 to -20 (percussive bursts) | PRIVATE — drives presence detection, NOT in broadcast by default. Operator can open ch 2 fader for performative moments. |
| S5 | **YouTube audio (operator-selected)** | browser → PipeWire default sink → `hapax-livestream` | `hapax-livestream` sink | -14 target but sources vary | YES via hapax-livestream → (future) L6 USB playback |
| S6 | **System notifications** | app → Notification role → `role.notification` loopback → `hapax-private` (24c retired; needs retarget) | `role.notification` loopback | highly variable | **NO — governance-forbidden on broadcast.** Notifications go to operator-private sink only. |
| S7 | **Sound effects / stingers** | daimonion → Assistant role → ducking applies | `role.assistant` loopback | -14 to -6 | YES (when recruited) |
| S8 | **Environmental room mic (Blue Yeti)** | USB → PC | `alsa_input.usb-Blue_Microphones_Yeti` | -30 to -18 | PRIVATE — feeds presence detection, ambient-energy signal; NOT in broadcast. |

Post-24c-retirement gap: S6 notification loopback currently targets
`hapax-private` which was 24c Out 2 — now defunct. Notification path
needs retargeting to either the PC Ryzen headphone pair or a dedicated
L6 AUX 2 if available. **See §7 follow-ups.**

---

## §3. Normalization targets (per-source + master)

### §3.1 Per-source pre-mix normalization

Every source lands on the L6 at a predictable integrated loudness so
ducking and master limiting operate on a known-flat input matrix.

| Source | Pre-L6 target | Enforcement | Rationale |
|---|---|---|---|
| S1 TTS (Hapax voice) | **-18 LUFS integrated, -1 dBTP peak** | PipeWire filter-chain `voice-fx-chain.conf` adds `ebur128` loudness normalization + true-peak limiter between Kokoro output and PC line-out | Evil Pet doesn't perform loudness normalization; it colors dynamically. Normalize upstream so Evil Pet's output lands at a predictable level on L6 ch 3. |
| S2 Vinyl dry (through ch 4) | **-14 LUFS integrated** (pressing-dependent; operator compensates with Handytrax output + L6 trim) | Hardware only — the Handytrax + L6 ch 4 trim. Operator sets trim once per record, does NOT adjust during play. | Vinyl mastering varies wildly (1975 cuts push +4 dB louder than 1990 CDs). Software normalization would defeat the point of vinyl character. |
| S2 Vinyl Mode D return (ch 3 when Mode D) | **-16 LUFS integrated** (granular wash is denser than TTS; -16 gives it comparable loudness to S1 in mix) | MIDI CC 7 Volume on Evil Pet + ch 3 trim | Mode D output is denser than TTS; slight -2 LUFS offset keeps vinyl-granulated material from dominating. |
| S3 Operator voice (Rode) | **-18 LUFS integrated, -1 dBTP peak** | Rode Wireless Pro receiver has internal compression (always-on); L6 ch 1 trim sets final landing | Matches TTS target so both voices coexist without either hiding. |
| S4 Contact mic | **-22 LUFS RMS window** (private signal, consumed by DSP not broadcast; target is for DSP dynamic range, not listenability) | Hardware trim only | Contact mic feeds dsp.contact_mic_ir; consistent input level avoids DSP gain-staging drift. |
| S5 YouTube | **-14 LUFS streaming target** (YouTube's own target) | PipeWire filter-chain `hapax-yt-loudnorm` (NEW, §5): `ebur128` with target -14 LUFS, -1 dBTP, 11 LU range | YouTube's own loudness normalization would otherwise fight the operator's mix. Pre-normalizing at -14 = no system-level rescaling. |
| S7 SFX / stingers | **-16 LUFS, -1 dBTP peak** (slightly hotter than TTS) | daimonion-side pre-emission via `pydub.normalize` or equivalent | SFX should punch through TTS/music but not clip. |
| S8 Yeti room mic | **-24 LUFS RMS window** (private) | Hardware trim | Same rationale as contact mic. |

### §3.2 Master-bus target (L6 Main Mix → OBS)

**Broadcast target: -14 LUFS integrated, -1 dBTP peak, 11 LU short-term range.**

Conforms to YouTube's loudness guideline (-14 LUFS), avoids true-peak
clipping on platform re-encoding (-1 dBTP), preserves dynamic range
for musical content (11 LU short-term range). Enforcement:

1. **L6 hardware master fader** sets nominal level.
2. **PipeWire-side EBU R128 meter on the L6 Main Mix capture** (new):
   a filter-chain node between `alsa_input.usb-ZOOM_Corporation_L6-00.multitrack`
   and the OBS-bound monitor sink, running `ebur128` for live metering
   + true-peak limiter at -1 dBTP as the last safety net before OBS.
3. **OBS-side loudness monitor** (EBU R128 plugin, already available
   in OBS Studio 30+): informational display in operator UI, not
   enforcement.

---

## §4. Ducking priority matrix

Ducking is **not automatic for every pair** — some interactions
benefit from simultaneous presence (music plus TTS = radio aesthetic);
some require hard mutex (Mode D + TTS). Three tiers:

### §4.1 Tier A — HARD MUTEX (enforced at CC / routing level, not volume ducking)

| Condition | Action | Enforcement |
|---|---|---|
| Mode D active (flag `/dev/shm/hapax-compositor/mode-d-active`) | TTS path muted at source: VocalChainCapability skips send + CPAL defers utterance until Mode D off | `agents/hapax_daimonion/vinyl_chain.py::activate_mode_d` sets SHM flag; CPAL reads flag and queues utterance with `deferred_until_mode_d_off` marker. Hardware: operator drops ch 5 fader + AUX 1 send. |
| Evil Pet bypass OFF + TTS active + vinyl active on ch 4 AUX 1 | Cross-modulation artefact: two sources through Evil Pet simultaneously. Operator MUST drop one channel's AUX 1. | No software enforcement; operator discipline + procedure doc (§6.3 Hardware rule table). |
| System notifications (S6) → broadcast | FORBIDDEN — notifications never reach `hapax-livestream` sink | Already shipped: `config/wireplumber/50-hapax-voice-duck.conf` routes notification role to `hapax-private` via `policy.role-based.preferred-target`. Post-24c retarget needed (§7). |

### §4.2 Tier B — SOFT DUCK (volume-based, WirePlumber + filter-chain)

| Leader | Followers | Duck level | Attack / Release | Current state |
|---|---|---|---|---|
| S1 TTS active (Assistant role) | S5 YouTube, S7 SFX (Multimedia role) | -10 dB (from the 0.3 multiplier already shipped) | 50 ms attack / 200 ms release | **SHIPPED** via `role-based.duck-level = 0.3` in `50-hapax-voice-duck.conf` |
| S3 Operator voice (Rode ch 1) | S1 TTS on ch 3 | -6 dB | 50 ms / 300 ms | **NEW — needs L6-side VCA or PipeWire-side envelope-follower ducking.** See §5. Currently no ducking when operator speaks over Hapax. |
| S2 Vinyl on ch 4 (high RMS period) | S1 TTS on ch 3 | -4 dB | 100 ms / 500 ms | NEW (§5). Mild duck when vinyl is dense / bass-heavy so Hapax sits in a clearer midrange pocket. |
| Master bus over -10 LUFS short-term | All sources | -3 dB soft-knee via master compressor | 10 ms / 100 ms | NEW — master glue compressor at the PipeWire-side tap before OBS. |

### §4.3 Tier C — INFORMATIONAL (no automatic action; MixQuality emits + operator notified)

| Condition | Metric | Action |
|---|---|---|
| Any source > -6 dBTP peak over 3 s window | `hapax_mix_peak_ceiling_breach_total{source}` | Operator-visible warning; no auto-mute |
| MixQuality < 0.7 (from mixquality-skeleton §10.8) | `hapax_mix_quality{window=short}` | Dashboard yellow state |
| MixQuality < 0.5 | same gauge | Dashboard red state; recommend manual intervention or fallback preset |

---

## §5. Enforcement mechanism per row (concrete impl plan)

Three layers, each strictly responsible for one thing:

### §5.1 Per-source loudnorm: PipeWire filter-chain

New config `config/pipewire/hapax-loudnorm-chain.conf` — one filter-chain
per source needing pre-L6 normalization. Uses `filter-chain` with
`ebur128` (measure-only) + `linkwitz_transform` (peak limiter):

```
module.filter-chain.hapax-tts-norm:
  input  = hapax-voice-fx-playback (Evil-Pet-bound)
  filter = ebur128 {target = -18 LUFS}
         → limiter {ceiling = -1 dBTP, lookahead = 5 ms}
  output = alsa_output.pci-0000_73_00.6.analog-stereo

module.filter-chain.hapax-yt-norm:
  input  = hapax-yt-source (operator-playing YouTube sink)
  filter = ebur128 {target = -14 LUFS}
         → limiter {ceiling = -1 dBTP, lookahead = 5 ms}
  output = hapax-livestream (→ L6 USB playback)
```

PipeWire's `filter-chain` supports EBU R128 via the `ebur128` builtin
(PipeWire 1.0+; verify current version — if not, fall back to
`compressor`-based RMS approximation).

### §5.2 Ducking: WirePlumber policy + envelope-follower filter-chain

Tier B §4.2 ducking splits into two kinds:

- **Role-based** (TTS ducks music): already shipped. The shipped
  0.3 multiplier = -10 dB, which is correct for this tier.
- **Per-channel envelope-following** (operator voice ducks TTS;
  vinyl ducks TTS): cannot be done via role-based because both
  source and follower are on the broadcast path. Solution:
  `config/pipewire/hapax-sidechain-duck.conf` — a `sidechain`
  filter-chain where L6 ch 1 RMS envelope modulates the gain of
  the L6 ch 3 tap before the master bus.

### §5.3 Master bus limiter: filter-chain at L6 Main Mix capture

New `config/pipewire/hapax-master-limit.conf` — attaches to the L6
multitrack main-mix channel BEFORE it reaches the OBS sink. Contains:

- EBU R128 integrated loudness normalization to -14 LUFS (slow release,
  10 s window, ±1 LU tolerance — corrective gain only, not dynamics).
- True-peak limiter at -1 dBTP, 5 ms lookahead, -0.1 dB oversampling
  margin.
- Prometheus emit via filter-chain metrics socket:
  `hapax_mix_master_lufs`, `hapax_mix_master_peak_dbtp`.

### §5.4 MixQuality integration

The six sub-scores from `mixquality-skeleton-design.md` §2 already
cover: headroom, dynamic-range, balance, phase, clipping, silence.
Wire each §4.2/§4.3 metric into the sub-scores per the existing
skeleton. The MixQuality gauge becomes the go/no-go pre-flight for
broadcast: **< 0.7 should block go-live** until the operator resolves
the sub-score that dragged it down.

---

## §6. Operator-facing procedures

### §6.1 Startup checklist

1. `hapax-daimonion.service` active — verify `systemctl --user is-active hapax-daimonion`.
2. PipeWire filter-chains loaded — verify `pw-cat --list-targets` shows
   `hapax-voice-fx-norm`, `hapax-yt-norm`, `hapax-master-limit`.
3. L6 master fader at unity (0 dB).
4. L6 per-channel trims at the §3.1 values for each active source.
5. Evil Pet base scene written — run `scripts/evil-pet-configure-base.py`.
6. Mode D flag inactive — `hapax-vinyl-mode status` → "inactive".

### §6.2 Hardware rule table

| Situation | L6 channel state | Hapax state |
|---|---|---|
| Idle (no vinyl, Hapax may speak) | ch 3 fader UP (TTS return), ch 4 fader DOWN, ch 1 fader UP (operator) | Normal |
| Operator talking over music | ch 1 fader UP, ch 3 fader DOWN (Hapax ducks) OR wait for sidechain duck (§5.2) | TTS continues but ducked |
| Mode D broadcasting vinyl | ch 4 fader DOWN + AUX 1 UP, ch 3 fader UP (granular return), ch 5 fader DOWN + AUX 1 DOWN | `hapax-vinyl-mode on` |
| Exit Mode D back to TTS | ch 5 fader DOWN + AUX 1 UP, ch 3 fader UP (TTS return), ch 4 as desired | `hapax-vinyl-mode off` |

### §6.3 Hard rule (no software enforcement, operator discipline)

**Never have ch 4 AUX 1 UP + ch 5 AUX 1 UP simultaneously.** Both
channels feed the same AUX 1 → Evil Pet input, and mixing vinyl +
TTS pre-Evil-Pet produces unintelligible cross-modulation. The
operator's AUX 1 send knobs are a mutex — one channel's AUX 1 up at
a time, not both.

---

## §7. Post-24c-retirement follow-ups (pre-go-live)

| Item | Status | Owner | Effort |
|---|---|---|---|
| Retarget S6 notification loopback (was `hapax-private`/24c Out 2) → new operator-private destination | NEW (broken since 24c retirement) | delta | S (config edit + restart) |
| Ship `hapax-loudnorm-chain.conf` §5.1 with TTS + YT filter-chains | NEW | delta | M |
| Ship `hapax-sidechain-duck.conf` §5.2 with Rode → TTS envelope follower | NEW | delta | M (needs PipeWire sidechain investigation) |
| Ship `hapax-master-limit.conf` §5.3 at L6 Main Mix capture | NEW | delta | M |
| Wire MixQuality sub-scores to above metrics | NEW | delta | M (aligns with mixquality-skeleton-design.md) |
| Update `50-hapax-voice-duck.conf` notification `preferred-target` | NEW (24c retirement) | delta | S |
| Operator validates §3.1 levels against live performance | NEW | operator | — |

---

## §8. Why these targets and not others

- **-14 LUFS master**: YouTube's own loudness target. Pre-normalize
  here and YouTube doesn't rescale. Rescaling reveals encoding artefacts
  and changes crest factor mid-stream — bad for perceived consistency.
- **-18 LUFS voice sources**: 4 LU below master = ~4 dB headroom for
  music to occupy while voice is present. Standard radio-broadcast
  convention; proven across decades of mix engineering.
- **-1 dBTP true-peak**: YouTube re-encodes to AAC/Opus, both of which
  can introduce up to +0.3 dBTP over original. -1 dBTP ceiling gives
  platform re-encoding headroom without audible clipping.
- **50 ms attack / 200 ms release on TTS duck**: attack fast enough
  to catch the first syllable, release slow enough to avoid pumping
  during brief inter-word pauses.
- **Mode D is HARD MUTEX, not soft duck**: granular re-synthesis of TTS
  destroys phoneme coherence — speech becomes unintelligible, not just
  quieter. Mutex is correct.

---

## §9. Implementation phases

Each phase produces a shippable commit + live verification.

**Phase A (pre-go-live, delta owns)** — §5.1 voice-norm + §5.3 master-
limit. Touches `config/pipewire/*.conf` only. Restart PipeWire, smoke-
test with tone + speech utterance. Estimated: 1 session.

**Phase B (pre-go-live, delta owns)** — §5.1 YT-norm + §5.2 sidechain
duck (Rode → TTS). Requires PipeWire sidechain experiment. If sidechain
proves too complex, fall back to a simpler RMS-envelope modulator via
`calf` plugin. Estimated: 1-2 sessions.

**Phase C (post-go-live, delta owns)** — MixQuality sub-scores wired
to each tier's metric. Dashboard + alert routing. Estimated: 1 session.

**Phase D (post-go-live, delta owns)** — Mode D TTS mutex software
enforcement (CPAL reads SHM flag + defers utterance). Operator-
discipline approach works for go-live; software enforcement is
defense-in-depth. Estimated: 1 session.

---

## §10. Open questions

1. **RESOLVED 2026-04-21** — `ebur128` ships as a native SPA filter-graph
   plugin with `pipewire-audio`: `/usr/lib/spa-0.2/filter-graph/libspa-filter-graph-plugin-ebur128.so`.
   `calf` is NOT installed and NOT required. Existing `voice-fx-loudnorm.conf`
   + `yt-loudnorm.conf` use LADSPA `sc4m_1916` + `hard_limiter_1413` which
   meets the LUFS/dBTP target; upgrading to the SPA `ebur128` plugin is an
   optional future win (gives I/S/M sub-metrics natively) but not blocking.
2. **RESOLVED 2026-04-21** — L-12 capture side exposes a 14-channel
   `multichannel-input` profile: `alsa_input.usb-ZOOM_Corporation_L-12.*.multichannel-input`
   (Channel Map: AUX0..AUX13, 48 kHz s32le). Per project memory the
   hardware maps AUX0..AUX11 = per-input channels and AUX12/AUX13 = main
   L/R mix return. **The master-mix IS addressable** — Phase A §5.3 can
   read AUX12+AUX13 directly instead of inserting a filter-chain at the
   output sink. The filter-chain path becomes a fallback if the AUX12/13
   signal ever drops out.
3. **RESOLVED 2026-04-21** — Notifications already land cleanly:
   `config/wireplumber/92-hapax-notification-private.conf` routes the
   Notification role to the `hapax-notification-private` sink (IDLE, 2ch
   float32). Distinct from `hapax-livestream` — never reaches broadcast.
   No post-24c retarget required; the notification path is decoupled
   from the 24c retirement.
4. **DEFERRED — operator preference** — Full-auto ducking is the
   strategy default; operator invert via config flag remains available.
   No tech blocker; will flip if operator indicates otherwise.
5. Out of scope for this strategy — see vinyl-broadcast-ethics doc.

---

## §11. Success criteria

1. Every source lands on L6 at its §3.1 target ±2 LU.
2. Master bus stays at -14 ±1 LUFS integrated over any 30-min window.
3. No true-peak breach of -1 dBTP during any 1-hour broadcast window.
4. TTS is intelligible through music at all times (subjective; operator-
   validated via §6 checklist).
5. Mode D engagement does not produce audible TTS bleed (hard mutex
   verified live).
6. MixQuality gauge reads ≥ 0.85 for 95% of broadcast time.
