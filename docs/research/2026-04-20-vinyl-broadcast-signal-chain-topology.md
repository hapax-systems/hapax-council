# Vinyl Broadcast Signal Chain — Full Topology and Engineering

Status: research
Date: 2026-04-20
Operator: single hip-hop producer ("LegomenaLive" YouTube channel)
Parent doc: `docs/research/2026-04-20-vinyl-collection-livestream-broadcast-safety.md` (governance/§7 routes hardware at coarse granularity; this doc goes deep on the full physical + software signal chain)
Stack under analysis: Korg Handytraxx Play → Endorphin.es Evil Pet + Torso S-4 (granular/sampler outboard) → PreSonus Studio 24c (USB ADC/DAC) + Zoom L6 (USB multitrack mixer in Altset 2) → PipeWire (no DAW) → MediaMTX → YouTube RTMP
Register: engineering-precise. All numeric latencies are vendor-published or empirically observed; folk numbers are flagged as such.

---

## §1 TL;DR

**Recommended topology: candidate (B) — "L6 as Front-of-House, 24c as Voice/Capture Bridge."** The Handytraxx feeds an L6 stereo line pair (ch3-stereo). The Evil Pet and Torso S-4 occupy the remaining stereo line pairs as parallel FX returns, fed from L6 AUX/SEND (post-fader send, monitored pre-broadcast). The L6 master mix bus already exits the L6 USB multitrack altset 2 as channels 7-8 (L/R MAIN out per [Zoom L6 manual §USB block diagram](https://zoomcorp.com/media/documents/E_L6.pdf)) and lands in PipeWire as `alsa_input.usb-ZOOM_Corporation_L6.multitrack` AUX6/AUX7. The 24c retains its existing role: In 1 = Cortado contact mic; In 2 = reserved (used in the existing config as the L12 mix bus return — to be retired in this topology since L6 supplants L12); Out 1 = operator monitor headphones (via 24c headphone amp); Out 2 = Hapax voice send to Evil Pet (preserved per existing `hapax-vinyl-to-stream.conf`). PipeWire `module-filter-chain` inserts a four-stage broadcast safety chain on the L6-master-tap before it reaches `hapax-livestream-tap`: (1) LSP Pitch Shifter or builtin pitch resampler at ~+6.0% (Smitelli floor), (2) LSP Multiband Compressor (broadcast glue, ~3:1 ratio, low-thresh), (3) LSP Stereo Tools (M/S width control, mono-compatibility check), (4) x42 dpl.lv2 brick-wall true-peak limiter ceiling −1.5 dBTP. Operator cue is the 24c headphone output driven from a separate L6 PFL/SOLO bus (L6 supports per-channel PFL → headphone), so cue is fully decoupled from the broadcast bus.

Critical numbers:

- **End-to-end live broadcast latency: ≈ 5–12 s** (dominated by RTMP/CDN, not by host stack). Per [VideoSDK YouTube RTMP guide](https://www.videosdk.live/developer-hub/rtmp/youtube-rtmp), default RTMP is 2-3s; YouTube CDN adds 5-15s. Host-stack latency is ≤30 ms even with the full FX chain.
- **Operator monitor latency from needle to ear: ≈ 4–8 ms** (analog in L6 → analog out L6 to 24c headphone tap; nothing routes through the host).
- **24c USB roundtrip: 3.67 ms / 162 samples at 16-sample buffer** ([PreSonus 24c Owner's Manual](https://www.fmicassets.com/Damroot/Original/10001/OM_2777700403_Studio_24c_EN.pdf)).
- **PipeWire host quantum (current): 128 frames @ 48 kHz = 2.67 ms** per buffer, configured in `~/.config/pipewire/pipewire.conf.d/10-voice-quantum.conf`.
- **L6 internal converter: 32-bit float** processing ([Zoom L6 product page](https://zoomcorp.com/en/us/digital-mixer-multi-track-recorders/digital-mixer-recorder/livetrak-l6-final/)) — no internal headroom anxiety up to L6 master fader.
- **Evil Pet I/O: pro-line +4 dBu, internal 32-bit float, 48 kHz / 24-bit converters** ([Endorphin.es Evil Pet product page](https://www.endorphin.es/modules/p/evil-pet)).
- **YouTube broadcast loudness target: −14 LUFS integrated, true-peak ≤ −1.5 dBTP** for safe transcode ([Critical Listening Lab loudness targets](https://www.criticallisteninglab.com/en/learn/loudness); [Sweetwater LUFS standards](https://www.sweetwater.com/insync/loudness-standards-lufs-peaks-and-streaming-limits/)).
- **Internal reference: −18 dBFS = 0 VU**, peak budget −6 dBFS at FX returns, −1.5 dBFS true-peak at the limiter brickwall.

The Handytraxx Play emits **line-level**, not phono-level, after its internal preamp (LINE OUT max 2.3 V_p, [Korg Handytraxx Play manual](https://cdn.korg.com/us/support/download/files/a179fc60a4266b29f2f0eb82c3eb0887.pdf?response-content-disposition=inline%3Bfilename%3Dhandytraxx_play_OM_En2.pdf&response-content-type=application/pdf%3B)) — this is the single most consequential gain-staging fact in the chain. **Do not engage 24c In 1/2 as Hi-Z (instrument)** for vinyl; **do** engage line mode.

Justification (one paragraph): the L6 is functionally a small live-mixing console with per-channel PFL/SOLO, AUX sends, and a 32-bit-float master bus that is **already** exposed as a USB multitrack endpoint. Routing the Handytraxx and FX returns through the L6 reuses hardware that already supports the operator's needs (cue, send/return, fader-driven balance) at sub-millisecond analog latency. The 24c is wrong as front-of-house (only 2 inputs, no AUX, no PFL); it is right as the operator's voice/contact-mic interface and as the headphone amp. The PipeWire filter-chain insertion at the broadcast tap (not at any operator-monitor surface) keeps performance latency ≤ 8 ms while applying the deterministic ≥6% pitch transformation and brickwall limiter that protect the channel from Content ID and DMCA.

---

## §2 Three Candidate Topologies

### §2.1 Candidate A — "24c at front, L6 as USB return mux"

```
Handytraxx Play
  │ 2.3 V_p line-level RCA → RCA→1/4" TRS adaptor
  ▼
PreSonus 24c In 1+2 (line, NOT Hi-Z)
  │ 24c USB → PipeWire alsa_input.usb-PreSonus_Studio_24c
  ▼
PipeWire DSP graph (filter-chain):
  ├─ tap 1 → loopback → 24c Out 2 → Evil Pet IN
  │                                  Evil Pet OUT → L6 ch3-stereo
  ├─ tap 2 → loopback → 24c Out 2 (mux/time-share) → Torso S-4 IN
  │                                  Torso OUT → L6 ch5-stereo
  └─ tap 3 → broadcast filter-chain → hapax-livestream-tap → MediaMTX
                                                              ▼
                                                         YouTube RTMP

L6 master USB multitrack → PipeWire (return path for FX-treated outboard)
                         → mixed in software → broadcast tap

Cortado MKIII contact mic → 24c In 1? CONFLICT (only 2 inputs, vinyl wants both)
Operator headphones      → 24c headphone out (monitor mix from PipeWire)
```

Trade-offs:

- **Gain staging:** poor. Handytraxx's 2.3 V_p (~+9.4 dBu peak) is hot; 24c In 1/2 line mode tops at ~+10 dBu before clipping. Workable but tight; the trim pot has to sit near minimum and any onboard Handytraxx FX boost (filter resonance peak, looper retrigger) will clip the converter.
- **Latency:** worst of the three options. Vinyl audio crosses USB twice (24c capture, 24c playback to FX), then the L6 USB return crosses once more. At 128 quantum 48 kHz, that's ~3 × 2.67 ms PipeWire-side + 2 × 3.67 ms 24c USB roundtrip = **~15 ms operator monitor latency**, audible to a turntablist.
- **Headroom:** Handytraxx → 24c is a known choke point. No headroom margin for FX boosts.
- **Monitoring/cue:** broken. The operator wants to PFL the next track without that PFL hitting the broadcast. With a single 24c headphone out driven from PipeWire, building a cue mix that excludes the broadcast bus requires a dedicated PipeWire monitor sink and software cue logic — slow to operate, error-prone.
- **Mode-switching (A/B/C/D):** every mode requires a PipeWire reroute via `pactl move-sink-input` or filter-chain edit — high friction.
- **Cortado contact mic:** has nowhere to live. Both 24c inputs are claimed by vinyl. Forces the operator to choose between vinyl and contact mic per session, which kills the cross-modal hand-activity detection used by the Bayesian Presence Engine (see council CLAUDE.md § Bayesian Presence Detection).

**Verdict: rejected.** Inputs and headphone surface fight each other.

### §2.2 Candidate B — "L6 as front-of-house, 24c as voice/capture bridge" (RECOMMENDED)

```
Handytraxx Play
  │ 2.3 V_p line RCA → RCA→1/4" TRS
  ▼
Zoom L6 ch3 (stereo line input)
  │ trim → fader → AUX1 send (post-fader, to Evil Pet)
  │             → AUX2 send (post-fader, to Torso S-4)
  │             → master L/R mix
  ▼
Evil Pet (granular):  L6 AUX1 → Evil Pet IN
                      Evil Pet OUT → L6 ch4 (stereo line input, FX RETURN slot)
Torso S-4 (sampler):  L6 AUX2 → Torso S-4 IN
                      Torso S-4 OUT → L6 ch5 (stereo line input, FX RETURN slot)

L6 channel mix:  ch3 (Handytraxx dry, low blend) + ch4 (Evil Pet wet) + ch5 (Torso wet)
              → L6 master L/R bus (32-bit float internal)
              → L6 USB Altset 2 multitrack:
                  AUX0..AUX5  = ch1..ch6 individual pre-fader/post-fader streams
                  AUX6..AUX7  = MASTER L/R post-master-fader (THE BROADCAST SOURCE)

PipeWire reads alsa_input.usb-ZOOM_Corporation_L6.multitrack (12 ch):
  ├─ filter-chain pulls AUX6+AUX7 as broadcast bus
  │   └─ chain:
  │       (1) LSP Pitch Shifter (+6.0% formant-corrected)  — Content ID floor
  │       (2) LSP Multiband Compressor (3-band, ~3:1)      — broadcast glue
  │       (3) LSP Stereo Tools (M/S width 0.95, mono check) — broadcast safety
  │       (4) x42 dpl.lv2 brickwall (true-peak, −1.5 dBTP) — encoder safety
  │   → hapax-livestream-tap  → MediaMTX  → YouTube RTMP
  └─ separate filter-chain pulls AUX0..AUX5 individually if multi-channel archival
    is enabled (e.g. for VOD re-mix); not required for live

PreSonus 24c (separate role — voice/perception bridge):
  In 1: Cortado MKIII contact mic (UNCHANGED — Bayesian presence dependency)
  In 2: reserved for ad-hoc capture (mic, line, USB-only test instrument)
  Out 1: operator monitor (24c headphone amp), driven from L6 MONITOR OUT
         (analog patch: L6 MONITOR L/R → 24c not needed; L6 has its own
         dedicated stereo MONITOR OUT 1/4" → operator headphones direct;
         24c headphone is for Hapax-only system audio when needed)
  Out 2: Hapax voice send (UNCHANGED — `hapax-private` virtual sink → Evil Pet)
         NOTE: this is a separate, parallel path used for Hapax TTS modulation,
         not for vinyl. Evil Pet has only one IN; in this topology Evil Pet
         is shared between vinyl (L6 AUX1) and Hapax voice (24c Out 2) via
         a passive 1/4" Y-cable summing them. Acceptable because Hapax voice
         is rarely active during turntablist mode (CPAL gating).
         If Y-cable summing causes audible Hapax bleed during vinyl performance,
         option: route Hapax voice send to Torso S-4 INSTEAD of Evil Pet.

Operator cue:
  L6 PFL/SOLO bus → L6 PHONES OUT (1/4" stereo TRS) → operator headphones
  This is fully analog inside the L6, sub-millisecond latency, decoupled
  from the broadcast bus. PFL on any L6 channel monitors that channel
  pre-fader without affecting master.
```

Trade-offs:

- **Gain staging:** good. Handytraxx 2.3 V_p hits L6 line input with the trim providing 30+ dB of attenuation range. L6 internal 32-bit-float means no headroom anxiety up the chain to the master fader.
- **Latency:** best. Vinyl never enters the host for monitoring — operator hears it through the L6 analog mixer in **<2 ms** (L6 internal DSP + analog path). Broadcast path crosses USB once (L6 → PipeWire) → ~3-5 ms USB + 2.67 ms quantum + filter-chain (~2-5 ms LSP plugins, see §4) = **~10-13 ms** to `hapax-livestream-tap`. Then encoder/network. Operator monitor decouples from broadcast.
- **Headroom:** L6 32-bit float internal eliminates intermediate-stage clipping. Only the L6 ADC ceiling and the 24c ADC ceiling matter — both are sized for pro-line +4 dBu.
- **Monitoring/cue:** **proper DJ cue**. L6 PFL → L6 PHONES OUT is the standard live-mixing pattern. Operator can pre-listen to any channel without affecting the broadcast.
- **Mode-switching (A/B/C/D):** physical faders. MODE A is "ch3 fader up, ch4/5 fader down." MODE B is the inverse. MODE C is "ch3 fader fully down, bed-music channel up." MODE D is "ch3 down, ch4 up at unity, ch5 muted." All single-finger moves; can also be MIDI-mapped via Erica Synths MIDI Dispatch sending CC to L6 (L6 accepts MIDI CC fader control per [Zoom L6 manual](https://zoomcorp.com/manuals/l6-en/)).
- **Cortado contact mic:** preserved. Bayesian presence engine intact.
- **Hapax voice path:** preserved (24c Out 2 → Evil Pet) but with the Y-cable summing caveat, or with redirection to Torso S-4 as alternative.
- **Send/return discipline:** post-fader sends from L6 ch3 to AUX1/AUX2 mean the FX wetness scales with the dry fader — a genre-standard "FX follows volume" behaviour.

**Verdict: recommended.** Best fit for the operator's actual gear and DJ ergonomics.

### §2.3 Candidate C — "Hybrid: outboard inserts on L6, 24c does broadcast capture"

```
Handytraxx → L6 ch3 (line)
L6 ch3 INSERT (1/4" TRS insert send/return) → Evil Pet → ch3 INSERT return
L6 ch4 INSERT → Torso S-4 → ch4 INSERT return
L6 master L/R analog out → 24c In 1+2 (line)
24c USB → PipeWire → broadcast filter-chain → hapax-livestream-tap

(Cortado moves to L6 ch1 XLR, with phantom power)
Operator headphones: L6 PHONES OUT
```

Trade-offs:

- **Critical blocker: L6 has no per-channel insert sends.** Per [Zoom L6 manual](https://zoomcorp.com/media/documents/E_L6.pdf), L6 channel jacks are XLR/TRS combo (ch1/2) and stereo TRS line (ch3-6). There are no Y-cable insert points on individual channels. This topology is **not implementable** without external splitting hardware.
- Even if L6 had inserts, series insert (vs parallel send) ties the dry signal's wetness to a single FX engine — lose the ability to layer Evil Pet + Torso S-4 in parallel.
- Latency comparable to Candidate B but with a redundant analog→ADC stage at the 24c (master out → 24c In) vs Candidate B's direct L6 USB.
- Cortado at L6 ch1 actually works (XLR + 48V available on L6 ch1/2), and frees the 24c, but the topology hits the "no insert" wall.

**Verdict: rejected.** Architecturally clean idea, but L6 hardware does not support series inserts.

### §2.4 Topology comparison matrix

| Dimension | A (24c-front) | B (L6-front) ✓ | C (insert) |
|---|---|---|---|
| Operator monitor latency | ~15 ms | **~2 ms** | ~6 ms |
| Broadcast tap latency (host stack only) | ~12 ms | ~10-13 ms | ~10-13 ms |
| Gain headroom at vinyl input | tight | **wide (32-bit float)** | wide |
| Cue/PFL ergonomics | host-side, friction | **L6 PFL bus, native** | L6 PFL bus, native |
| Mode-switch friction | high (PW reroute) | **low (faders + MIDI CC)** | low |
| Cortado preservation | broken | **preserved** | preserved (moves to L6 ch1) |
| Hapax voice path preserved | yes | **yes (with caveat)** | broken (24c claimed) |
| Implementability | yes | **yes** | **no (L6 lacks inserts)** |
| Send/return architecture | software send | **post-fader AUX send (parallel)** | series insert |

---

## §3 Gain Staging Across the Chain

### §3.1 Reference levels

Industry convention used here: **−18 dBFS digital = 0 VU analog = +4 dBu line level**. A typical broadcast-friendly working level is signal averaging at −18 dBFS ± 3 dB on the integrated meter, with peaks ≤ −6 dBFS at the FX-return stage and ≤ −1.5 dBFS true-peak at the post-limiter brickwall ([Sweetwater "Understanding Signal Levels"](https://www.sweetwater.com/insync/understanding-signal-levels-audio-gear/); [AESTD1008.1.21-9](https://www.aes.org/technical/documentDownloads.cfm?docID=731)).

### §3.2 Per-node budget (Candidate B)

| Node | Output level (typ.) | Max output | Headroom note |
|---|---|---|---|
| Handytraxx Play LINE OUT | ~+4 dBu (typical loud cut) | 2.3 V_p ≈ +9.4 dBu | Hot for a "portable" turntable; line, not phono. ([Korg manual](https://cdn.korg.com/us/support/download/files/a179fc60a4266b29f2f0eb82c3eb0887.pdf?response-content-disposition=inline%3Bfilename%3Dhandytraxx_play_OM_En2.pdf&response-content-type=application/pdf%3B)) |
| L6 ch3 line input trim | adjust to peaks at -10 dBFS on L6 LED ladder | converter handles +24 dBu before clip per Zoom 32-bit float spec | 32-bit float = no internal clipping risk between trim and master fader |
| L6 AUX1 send to Evil Pet | post-fader, attenuator 0 to −∞ dB | depends on L6 master and AUX trim | Set such that Evil Pet IN sees nominal +4 dBu → -18 dBFS internal |
| Evil Pet IN | accepts up to +4 dBu pro-line ([Endorphin.es spec](https://www.endorphin.es/modules/p/evil-pet)) | +4 dBu before AD clip | Internal 32-bit float; no clipping past ADC |
| Evil Pet OUT (granular wet) | ≤ +4 dBu, content-dependent | +4 dBu | Granular output can have transient peaks; allow 6 dB headroom on L6 ch4 trim |
| L6 ch4 (Evil Pet return) | trim to peaks -10 dBFS | 32-bit float internal | Use VU on L6 ladder, not peak |
| Torso S-4 IN/OUT | Elektron-class line level (~+4 dBu) ([Torso S-4 manual](https://downloads.torsoelectronics.com/s-4/manual/The%20S-4%20Manual%201v0v4a.pdf)) | +4 dBu | Same as Evil Pet |
| L6 master fader | output sized for +4 dBu pro-line | +24 dBu pre-master-clip | Master is the single point of broadcast-side gain control |
| L6 USB out (AUX6/7 master) | 32-bit float dB-correct, samples directly = master fader amplitude | n/a (32-bit float) | PipeWire reads samples in [-1.0, +1.0] for normal range; values >1.0 valid until limiter |
| PipeWire DSP (filter-chain) | floating-point, -∞ headroom internally | n/a | LSP plugins have internal oversampling on limiter (4x for x42 dpl.lv2) |
| x42 dpl.lv2 brickwall | output ceiling −1.5 dBTP (config) | hard ceiling | Final stage; never let clip indicator light |
| MediaMTX → RTMP encoder | takes filter-chain output as floats | AAC LC encoder | AAC ceiling implicit via dpl.lv2; no further headroom budgeting needed |

### §3.3 Concrete trim-pot starting points (Candidate B)

These are starting points for first calibration. Re-trim with pink noise:

1. **L6 ch3 (Handytraxx) trim:** start at 9 o'clock (low). Play loudest expected cut. Adjust until L6 channel LED ladder shows peaks at the -10 dB tick.
2. **L6 AUX1 send to Evil Pet:** unity (12 o'clock). Watch Evil Pet input LED (if any) or trim Evil Pet's input control to nominal.
3. **Evil Pet IN trim:** adjust so granular processor's internal level is well-fed but transients don't overload (Evil Pet's internal 32-bit float means ADC is the only critical stage; transient peaks at +4 dBu are safe).
4. **L6 ch4 (Evil Pet return) trim:** adjust until peaks at -10 dB on L6 LED ladder.
5. **L6 master fader:** unity (0 dB). The L6 USB master out should average -18 dBFS, peaks -6 dBFS in PipeWire.
6. **PipeWire chain → x42 dpl.lv2:** ceiling -1.5 dBTP, threshold -3.0 dBFS. Watch gain-reduction LED — should fire only on transients, not continuously.

### §3.4 Why software brickwall, not hardware

The operator does not own hardware analog-domain compressors or limiters. Software brickwall (x42 dpl.lv2) is the right choice because:

- It runs at the very last stage before encoder hand-off — no analog path can color it.
- True-peak detection (4× oversampling per [x42 dpl.lv2 docs](https://github.com/x42/dpl.lv2)) catches inter-sample peaks invisible to peak meters and clipping at AAC encode.
- LV2 plugin inserts via PipeWire `module-filter-chain` add ≤2 ms of latency (look-ahead) — irrelevant for broadcast.
- Free, open-source, Linux-native — no licensing complexity.

### §3.5 Why no compressor on the Handytraxx-direct branch

A common mistake is to compress the dry vinyl branch heavily. Compression of vinyl is genre-coded (mastering decisions are baked into the cut); aggressive recompression flattens the dynamic identity of the source. Use the multiband compressor only at the **broadcast tap**, after the FX returns are mixed in — this glues the layered mix without destroying the source's dynamics.

---

## §4 Latency Budget

### §4.1 Per-node latency table (Candidate B)

| Node | Latency (each direction) | Source |
|---|---|---|
| Handytraxx Play (analog playback) | n/a (continuous physical) | mechanical |
| L6 ch3 ADC + DSP (32-bit float) | ~0.5-1 ms | Zoom L6 32-bit float internal pipeline ([Zoom L6 product page](https://zoomcorp.com/en/us/digital-mixer-multi-track-recorders/digital-mixer-recorder/livetrak-l6-final/)) |
| L6 AUX1 send DAC → Evil Pet IN ADC | ~1-2 ms | Two analog converters; vendor-typical |
| Evil Pet granular processing | content-dependent: short grain (1-30 ms) = look-ahead negligible; long grain = up to grain length | [Endorphin.es Evil Pet docs](https://www.endorphin.es/modules/p/evil-pet) |
| Evil Pet OUT DAC → L6 ch4 ADC | ~1-2 ms | Same as above |
| L6 master mix → L6 USB out | ~1 ms internal | Zoom 32-bit float pipeline |
| L6 USB → PipeWire ALSA capture | ~2-3 ms (hardware-dependent) | USB Audio Class 2 typical |
| PipeWire quantum (current 128 @ 48k) | 2.67 ms per buffer | `10-voice-quantum.conf`; [PipeWire docs](https://docs.pipewire.org/page_man_pipewire-props_7.html) |
| filter-chain LSP Pitch Shifter | ~2-3 ms (FFT-based pitch) | LSP plugin internal |
| filter-chain LSP Multiband Comp | ~1 ms (look-ahead optional) | [LSP plugin docs](https://lsp-plug.in) |
| filter-chain LSP Stereo Tools | <0.5 ms | LSP plugin docs |
| filter-chain x42 dpl.lv2 brickwall | ~1.5 ms (look-ahead window) | [x42 dpl.lv2](https://github.com/x42/dpl.lv2) |
| `hapax-livestream-tap` → MediaMTX | <1 ms | local socket |
| MediaMTX RTMP buffering | 100-500 ms (configurable) | [MediaMTX](https://github.com/bluenviron/mediamtx); [VideoSDK](https://www.videosdk.live/developer-hub/rtmp/youtube-rtmp) |
| YouTube CDN buffering | 5-15 s | YouTube live latency tuning, normal vs low-latency vs ultra-low-latency mode |

### §4.2 Two latencies, separately tracked

**Performance latency (operator monitor — ear-to-needle):**

```
needle → cartridge → Handytraxx output → analog cable → L6 ch3 ADC + DSP →
L6 master mix → L6 PHONES OUT → operator headphones
```

Total: **<2 ms.** This is critical. Turntablism requires sub-10ms monitor; <2 ms is studio-grade.

This path **does not enter the host computer.** It does not depend on PipeWire quantum, USB, plugin chain, or any encoder buffer. It is fully analog inside the L6 (with one ADC/DAC pass for the L6's internal 32-bit-float mix bus).

**Broadcast latency (viewer ear, end-to-end):**

```
needle → L6 → USB → PipeWire (2.67 ms quantum) →
filter-chain (~5-7 ms) → MediaMTX (~100-500 ms) →
YouTube RTMP ingest (~1-2 s) → CDN distribution (~3-10 s) → viewer
```

Total: **~5-12 s** typical (YouTube standard latency mode). Low-latency mode reduces to ~2-3 s; ultra-low-latency mode ~1 s but with higher buffering risk on viewer side.

This delay is irrelevant to performance because the operator is monitoring on the analog path. The broadcast-side delay only affects chat/viewer interaction (not in scope for vinyl performance).

### §4.3 PipeWire quantum sanity check

Current `~/.config/pipewire/pipewire.conf.d/10-voice-quantum.conf`:

```
default.clock.quantum     = 128
default.clock.min-quantum = 64
default.clock.max-quantum = 1024
default.clock.allowed-rates = [ 16000 44100 48000 ]
```

128 @ 48 kHz = 2.67 ms per buffer. This is correct for the operator's stack: it provides headroom for the 4-stage broadcast filter-chain without xrun risk on a desktop CPU under streaming load. **Do not lower below 128** for vinyl-broadcast use — broadcast does not benefit from sub-2 ms quantum, and lowering risks xruns when the compositor is also active. ([PipeWire low-latency docs](https://oneuptime.com/blog/post/2026-03-02-configure-pipewire-low-latency-audio-ubuntu/view); [Arch wiki PipeWire](https://wiki.archlinux.org/title/PipeWire))

The 64-sample minimum is reserved for voice-fx-chain when daimonion is using the chain interactively; vinyl broadcast keeps the default 128.

### §4.4 Outboard FX latency disclosure (Evil Pet, Torso S-4)

Endorphin.es and Torso do not publish formal block-diagram latency numbers. Empirical observations from community sources:

- Evil Pet: at short grain settings (<30 ms grain length), the wet output appears to lag the input by approximately one grain length (so ~10-30 ms typical). At long grain (>200 ms), perceived delay is content-dependent and the granular re-synthesis effectively decouples from input timing. This is a feature, not a defect — granular wet is not expected to be phase-coherent with dry. ([Endorphin.es Evil Pet review](https://synthanatomy.com/2025/10/endorphin-es-evil-pet-an-mpe-polyphonic-granular-synthesizer.html); [Perfect Circuit overview](https://www.perfectcircuit.com/signal/endorphines-evil-pet-review))
- Torso S-4: as a sampler, the wet signal is event-triggered (not flow-through), so latency is "at sample-trigger plus internal DSP". Per [Sound on Sound review](https://www.soundonsound.com/reviews/torso-electronics-s-4), DSP is responsive enough for live use; no measured number published.

Implication for the topology: do not attempt to phase-align Evil Pet/Torso outputs with the dry vinyl branch. They are deliberately non-coherent. Mix them as parallel layers, not as series effects.

---

## §5 Monitoring / Cue Architecture

### §5.1 The DJ cue requirement

The operator needs to hear the **next track** before it goes live. Standard DJ practice is "split cue" or "PFL" (pre-fade listen): the channel being cued is audible in headphones at full volume, while the master mix continues unaffected to the audience/broadcast. ([Digital DJ Tips: split cue](https://www.digitaldjtips.com/dj-tips-tricks-what-split-cue-is-why-you-may-want-to-use-it/); [Mixxx hardware setup](https://manual.mixxx.org/2.0/en/chapters/setup))

### §5.2 Why the 24c is wrong as a cue surface

The PreSonus Studio 24c has **2 outputs and 1 stereo headphone amp** ([PreSonus 24c page](https://www.presonus.com/products/studio-24c)). The two TRS outputs and the headphone amp are all driven from the same internal DAC (the headphone amp is a parallel feed). There is no separate cue/master stereo pair. To use it for cue, the operator would need:

1. A software cue mix in PipeWire (cue stream → 24c headphone via routing) **plus** a master broadcast mix (master stream → 24c outputs 1/2). This requires **two separate stereo mixes built in software**, with `pavucontrol`/`pactl move` to route — high friction.
2. Or a Y-splitter on the 24c headphone out to send L=master + R=cue to a single headphone (the [Algoriddim "split cue"](https://www.algoriddim.com/hardware/precueing) technique). This sacrifices stereo on both master and cue and is a workaround, not a solution.

Neither of these is acceptable for real-time DJ work. The 24c is a 2-channel interface designed for tracking, not for DJ cue.

### §5.3 Why the L6 is right as a cue surface

The L6 has:

- Per-channel **PFL/SOLO** button per [Zoom L6 manual](https://zoomcorp.com/manuals/l6-en/)
- Dedicated **MONITOR/HEADPHONE OUT** stereo TRS jack
- Cue mix internal to the mixer (PFL'd channel(s) appear in the headphone bus, master mix is unaffected)

This is the standard small-format-mixer cue topology. Operator presses PFL on ch3 (Handytraxx) when cuing the next record; PFL releases when the track is live. No software involvement.

### §5.4 Monitoring topology (Candidate B)

```
L6 master L/R bus  ─►  L6 USB Altset 2 AUX6/AUX7  ─►  PipeWire broadcast tap
                  ─►  L6 MONITOR OUT (analog stereo TRS) → operator headphones
                                                          (default, no PFL active)

When PFL pressed on ch3 (vinyl):
L6 ch3 pre-fader  ─►  L6 PHONES bus (replaces or sums with master, per L6 cue mode)
L6 master  ─►  USB broadcast (UNAFFECTED)
```

The 24c Out 1 / Out 2 / headphone are then free for:

- Hapax voice (Out 2 → Evil Pet IN, existing config)
- System audio playback (24c headphone amp, e.g. notifications routed to `hapax-private`)
- Reserved analog sends (Out 1 currently unused in vinyl topology)

### §5.5 Pre-stream rehearsal monitoring

Before going live, the operator may want to listen to the broadcast tap with delay-compensation (to verify the FX chain sounds correct without performing live).

PipeWire pattern: route `hapax-livestream-tap` monitor port → `pavucontrol` → 24c headphone output. This gives the operator the **post-FX-chain** signal in the 24c headphones. Latency is irrelevant here (rehearsal, not performance), so the ~10-13 ms host latency is fine.

For live performance, **do not use this monitoring path** — the operator should be hearing the L6 PHONES OUT (analog, sub-2 ms), not the post-broadcast tap.

---

## §6 Redundancy + Crash Recovery

### §6.1 Failure modes and intended behavior

| Failure | Current behavior | Desired behavior | Topology B impact |
|---|---|---|---|
| Evil Pet powers off mid-stream | L6 ch4 fader still up, no signal arrives — ch4 silent. Master mix continues with dry + Torso. | Same. Granular branch silently drops out; dry + Torso continue. Operator notices visually (Evil Pet LEDs off) and pulls ch4 fader. | Battery: Evil Pet has DC jack only; mains-powered. Failure scenarios: USB power loss, DC adapter loose. Not battery-related. |
| Torso S-4 freezes | Same as Evil Pet — silent ch5. Mix continues. | Same. | Torso S-4 is software-rich; freeze is plausible. Power-cycle to recover. |
| 24c USB disconnect | PipeWire detects disconnect, alsa_input.usb-PreSonus disappears. Cortado capture stops. Hapax voice send stops. Vinyl broadcast UNAFFECTED (vinyl never went through 24c). | Same. WirePlumber auto-reconnect on re-enumeration ([WirePlumber ALSA docs](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/alsa.html)). | Topology B's strength: vinyl is independent of 24c. Cortado/Hapax-voice loss is degraded mode but vinyl streams. |
| L6 USB disconnect | PipeWire detects, alsa_input.usb-ZOOM_Corporation_L6.multitrack disappears. Vinyl broadcast STOPS. Operator headphones still work (analog L6 PHONES OUT). | Auto-reconnect via WirePlumber. Static-image fallback in MediaMTX while waiting for reconnect. | Critical failure for broadcast. Operator must be able to detect quickly (degraded-stream signal — see council CLAUDE.md compositor budget tracker). Mitigation: a fallback PipeWire null-source feeds silence + status text overlay when L6 is missing. |
| L6 falls out of Altset 2 | Multitrack alias goes silent or returns wrong channel mapping. | `hapax-l6-evilpet-capture.conf` already locks Altset 2 via `api.alsa.use-acp = false` and explicit `api.alsa.path = "hw:L6,0"` with 12-channel S32LE format. Re-instantiation after disconnect should re-apply the format. | If altset doesn't restick: documented procedure in `2026-04-19-l6-multitrack-mode.md` (USB1/2 + SOUND PAD 2 + POWER button combo to re-lock). |
| PipeWire xrun storm | Degraded audio (clicks, drops). Compositor budget tracker should detect via `publish_costs`. | Quantum auto-bump from 128 to 256 (PipeWire dynamic quantum). Logged. | If sustained, drop filter-chain stages: bypass LSP Multiband Comp first (cheapest to drop), then LSP Stereo Tools, keeping only Pitch Shifter + brickwall. Mode-switch via filter-chain reload. |
| Filter-chain plugin crash | LSP/x42 plugins are LV2 in-process inside PipeWire; a crash kills the filter-chain and downstream sink. | Restart the filter-chain via `systemctl --user restart pipewire`. Stream interrupted ~3-5 s. Static-image MediaMTX fallback covers the gap. | Mitigation: cron-style or systemd timer health check on `hapax-livestream-tap` monitor activity; restart filter-chain if silent for >10 s with vinyl playing. |
| Handytraxx battery dies | Audio stops at L6 ch3. | Plug DC adapter (dual-power per [Korg manual](https://cdn.korg.com/us/support/download/files/a179fc60a4266b29f2f0eb82c3eb0887.pdf?response-content-disposition=inline%3Bfilename%3Dhandytraxx_play_OM_En2.pdf&response-content-type=application/pdf%3B)). | Operator pre-flight: verify Handytraxx on AC, not battery, before any session. |

### §6.2 Where audio falls back if Evil Pet crashes

In topology B, the dry Handytraxx → L6 ch3 → master mix branch is ALWAYS independent of the FX returns. Evil Pet crash = ch4 silent; dry + Torso continue. Operator pulls ch4 fader and continues.

If both Evil Pet AND Torso crash simultaneously (rare), the broadcast becomes pure dry vinyl (MODE A from §7 of the parent doc) — which is the **highest** legal-risk mode. Operator must immediately pull ch3 fader (MODE C — bed-music safe) until FX recover.

### §6.3 PipeWire xrun storm recovery

Per [PipeWire issue tracker](https://github.com/PipeWire/pipewire/blob/master/NEWS) and [Arch wiki](https://wiki.archlinux.org/title/PipeWire), recent versions include increased adapter retry counts to absorb transient xruns. The operator's quantum config (min 64, max 1024) gives PipeWire room to dynamically bump quantum if the load demands it. The filter-chain plugins (LSP, x42) are mature LV2 plugins with stable real-time behavior; xruns will more likely come from the GStreamer compositor than from the broadcast filter-chain.

### §6.4 USB device reconnect

WirePlumber's ALSA monitor handles UDev hot-plug events ([WirePlumber 0.5 ALSA docs](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/alsa.html)). When a USB audio device disappears, the corresponding `alsa_input.*` / `alsa_output.*` nodes are torn down; on reappearance, they are re-created with the same name (because the device descriptor is stable). Filter-chains and loopbacks targeting these nodes by `target.object` will **re-link automatically** when the target reappears. This is how the existing `hapax-l6-evilpet-capture.conf` recovers from L6 disconnects today.

Critical: existing `~/.config/wireplumber/wireplumber.conf.d/51-presonus-no-suspend.conf` and `50-studio24c.conf` both set `session.suspend-timeout-seconds = 0` for the 24c, preventing PipeWire from suspending the 24c after idle (which can trigger reconnect on next use, with associated latency). **Apply the same to the L6** in a new `52-l6-no-suspend.conf` — see §8.

---

## §7 VST Chain — Host + Plugin Recommendations

### §7.1 No DAW required

The operator's stack does not currently have a DAW or VST host in the chain. The recommendation is **to keep it that way** and use PipeWire's native `module-filter-chain` for the broadcast safety chain. Justification:

- PipeWire `module-filter-chain` is a first-class graph node — no IPC, no JACK round-trip, no separate process to crash.
- Supports LADSPA, LV2, sofa, ffmpeg, ebur128, builtin filter types ([PipeWire filter-chain docs](https://docs.pipewire.org/page_module_filter_chain.html)).
- Can be configured declaratively in a conf file alongside the existing `voice-fx-chain.conf`, `hapax-livestream-tap.conf`, etc.
- Hot-reloadable via `systemctl --user restart pipewire` (~3 s).
- Lower latency than Carla/JACK: filter-chain runs in PipeWire's RT thread directly, no client-process scheduling.

### §7.2 When a DAW host would be appropriate

- Multi-track recording of the L6 individual channels for post-stream remix → [Ardour](https://ardour.org/) or [Reaper Linux](https://www.reaper.fm/) would be appropriate, **separately from broadcast**.
- VST3 plugins not available in LV2 form → [Carla](https://kx.studio/Applications:Carla) as an LV2-host wrapper inside the PipeWire filter-chain, or as a standalone JACK client. ([Carla / PipeWire integration guide](https://www.benashby.com/resources/pipewire-vst-carla/))

For the broadcast chain specifically, no VST3-only plugin is needed (LSP and x42 cover all required functions).

### §7.3 Plugin recommendations (broadcast safety chain)

All of these are **free, open-source, Linux-native LV2** plugins. Install via:

```fish
sudo pacman -S lsp-plugins x42-plugins calf-plugins
```

| Stage | Plugin | URI / install | Purpose |
|---|---|---|---|
| 1. Pitch shift | LSP Pitch Shifter Mono/Stereo | `http://lsp-plug.in/plugins/lv2/pitch_shifter_stereo` | Apply ≥6% pitch offset to defeat Content ID per [Smitelli 2020](https://www.scottsmitelli.com/articles/youtube-audio-content-id/). LSP supports formant-corrected pitch shifting. |
| 2. Multiband compressor | LSP Multiband Compressor MB Stereo | `http://lsp-plug.in/plugins/lv2/mb_compressor_stereo_lr_x4` | 3-4 band glue. Tame transient peaks per band; ratio ~3:1, soft knee. ([LSP Dynamikprozessor](https://vstwarehouse.com/d/lsp-dynamikprozessor-plugin-series/)) |
| 3. Stereo tools | LSP Stereo Tools | `http://lsp-plug.in/plugins/lv2/stereo` | M/S width control, mono compatibility check, side-channel level. Set width 0.95 — slightly de-stereoed. ([Calf Stereo Tools](https://calf-studio-gear.org/) is an alternative.) |
| 4. Brickwall limiter | x42 dpl.lv2 (Stereo) | `http://gareus.org/oss/lv2/dpl#stereo` | True-peak look-ahead limiter with 4× oversampling. Ceiling −1.5 dBTP. Threshold −3 dBFS. ([x42 dpl.lv2 GitHub](https://github.com/x42/dpl.lv2)) |

Why this specific stack:

- **LSP Pitch Shifter** beats the builtin PipeWire `bq_*` filters because true pitch-shift requires phase-vocoder or PSOLA, not biquad EQ. LSP is the only Linux-native plugin family with documented FFT pitch shifting at LV2-host quality.
- **LSP Multiband Compressor** because single-band compression of a layered (dry + 2 FX) source flattens the bass and over-compresses transients in unison. Multiband lets bass breathe while taming high-frequency FX bursts.
- **LSP Stereo Tools** for the mono-compatibility check (some viewers will hear the broadcast in mono on phone speakers; bad stereo decorrelation collapses badly).
- **x42 dpl.lv2** because it is the de facto Linux LV2 brickwall limiter recommended by the EasyEffects/Ardour communities. True-peak detection with 4× oversampling catches inter-sample peaks that other limiters miss. ([EasyEffects feature request thread](https://github.com/wwmm/easyeffects/issues/1645))

### §7.4 Optional plugins (not in default chain)

| Plugin | When to add | Note |
|---|---|---|
| Calf Reverb | If operator wants always-on broadcast tail to soften abrupt track changes | Adds latency (~5-10 ms); usually do reverb at the FX-return stage (Evil Pet/Torso), not at broadcast |
| LSP Impulsnachhall (impulse reverb) | Higher-quality convolution reverb for special segments | Generally overkill for broadcast; FX returns already have reverb potential |
| Airwindows ConsoleX (LV2) | Subtle bus saturation/glue at master | [Airwindows Consolidated](https://www.airwindows.com/consolidated/) covers Console9, ConsoleX, ToTape — all CLAP/AU/VST3/LV2. Optional sweetening, not required for broadcast safety. |
| Airwindows ToTape9 | Tape-style soft saturation | Mastering-style sweetener |
| Calf Multi-band Limiter | Alternative to x42 dpl.lv2 | Functionally similar; x42 has truer true-peak detection |
| LSP Loudness Maximizer | Aggressive loudness push | Avoid for vinyl broadcast — overcompression destroys dynamic identity |

### §7.5 Why not a separate Carla/JACK process

- Adds an IPC hop (PipeWire → JACK shim → Carla → JACK shim → PipeWire) that is unnecessary.
- Adds another process that can crash and take down the broadcast.
- Carla is correct for **rehearsal/exploration** (live plugin tweaking, A/B-ing) but not for production broadcast.

For the broadcast chain, declarative PipeWire conf is the right answer.

---

## §8 PipeWire Conf Changes (Concrete)

### §8.1 New file: `~/.config/pipewire/pipewire.conf.d/55-broadcast-fx.conf`

This inserts the 4-stage LSP+x42 chain between L6 master USB capture and `hapax-livestream-tap`. It replaces the L6 capture tap currently in `hapax-l6-evilpet-capture.conf` for the AUX6/AUX7 channels (master), while leaving AUX0 (Evil Pet voice return) for the existing daimonion path.

**IMPORTANT:** Two separate filter-chains are needed: (a) AUX0 = Evil Pet/Torso voice return for daimonion (existing — KEEP), (b) AUX6+AUX7 = L6 master broadcast bus (NEW).

```ini
# ~/.config/pipewire/pipewire.conf.d/55-broadcast-fx.conf
#
# Broadcast safety chain: L6 master USB capture → 4-stage filter chain →
# hapax-livestream-tap.
#
# Inserted upstream of hapax-livestream-tap. Stages:
#   (1) LSP Pitch Shifter   — Smitelli +6% Content ID floor
#   (2) LSP MB Compressor   — broadcast glue
#   (3) LSP Stereo Tools    — mono compatibility check
#   (4) x42 dpl.lv2         — true-peak brickwall limiter
#
# 2026-04-20: derived from the broadcast-signal-chain-topology research doc.
# Do not bypass this chain on broadcast paths. Bypass-disable would expose
# the channel to Content ID claim and DMCA.

context.modules = [
    # Pull L6 master (AUX6 + AUX7) into a 2-ch capture node.
    {   name = libpipewire-module-loopback
        args = {
            node.description = "L6 Master (AUX6/AUX7) → broadcast-fx-in"
            capture.props = {
                node.name      = "hapax-l6-master-capture"
                node.description = "L6 master capture (USB Altset 2 AUX6/7)"
                target.object  = "alsa_input.usb-ZOOM_Corporation_L6-00.multitrack"
                audio.channels = 12
                audio.position = [ AUX0 AUX1 AUX2 AUX3 AUX4 AUX5 AUX6 AUX7 AUX8 AUX9 AUX10 AUX11 ]
                stream.channelmap = [ AUX6 AUX7 ]
            }
            playback.props = {
                node.name      = "hapax-broadcast-fx-in"
                target.object  = "hapax-broadcast-fx-chain"
                audio.channels = 2
                audio.position = [ FL FR ]
            }
        }
    }

    # 4-stage LV2 filter chain.
    {   name = libpipewire-module-filter-chain
        args = {
            node.description = "Hapax Broadcast FX Chain"
            audio.rate = 48000
            audio.channels = 2
            audio.position = [ FL FR ]
            filter.graph = {
                nodes = [
                    # Stage 1: Pitch Shifter (+6.0% — Smitelli floor)
                    { type = lv2 name = pitch
                      plugin = "http://lsp-plug.in/plugins/lv2/pitch_shifter_stereo"
                      control = { "pitch" = 1.06  "fade_in" = 0.005  "fade_out" = 0.005 } }

                    # Stage 2: Multiband Compressor (broadcast glue)
                    { type = lv2 name = comp
                      plugin = "http://lsp-plug.in/plugins/lv2/mb_compressor_stereo_lr_x4"
                      # Defaults give 4-band 3:1 ratio with soft knee. Tune live.
                    }

                    # Stage 3: Stereo Tools (M/S width 0.95)
                    { type = lv2 name = stereo
                      plugin = "http://lsp-plug.in/plugins/lv2/stereo"
                      control = { "ms_balance" = 0.0  "side_gain" = -0.45 } }

                    # Stage 4: True-peak brickwall limiter (-1.5 dBTP ceiling)
                    { type = lv2 name = brickwall
                      plugin = "http://gareus.org/oss/lv2/dpl#stereo"
                      control = { "threshold" = -3.0  "release" = 50.0
                                  "tp" = 1.0          "mode" = 1.0 } }
                ]
                links = [
                    { output = "pitch:out_l"      input = "comp:in_l" }
                    { output = "pitch:out_r"      input = "comp:in_r" }
                    { output = "comp:out_l"       input = "stereo:in_l" }
                    { output = "comp:out_r"       input = "stereo:in_r" }
                    { output = "stereo:out_l"     input = "brickwall:in_l" }
                    { output = "stereo:out_r"     input = "brickwall:in_r" }
                ]
                inputs  = [ "pitch:in_l"        "pitch:in_r" ]
                outputs = [ "brickwall:out_l"   "brickwall:out_r" ]
            }
            capture.props = {
                node.name = "hapax-broadcast-fx-chain"
                node.description = "Hapax Broadcast FX (input)"
                media.class = "Audio/Sink"
                audio.channels = 2
                audio.position = [ FL FR ]
            }
            playback.props = {
                node.name = "hapax-broadcast-fx-out"
                node.description = "Hapax Broadcast FX (output)"
                target.object = "hapax-livestream-tap"
                audio.channels = 2
                audio.position = [ FL FR ]
            }
        }
    }
]
```

Notes on this conf:

- LV2 plugin URIs must match the installed plugins. Verify with `lv2ls | grep -E "lsp-plug|gareus"`.
- LSP Pitch Shifter URI may differ by version — use `lv2info <uri>` to confirm port names (`in_l`/`in_r`/`out_l`/`out_r` may be `In L`/`In R` etc.).
- Control names (`pitch`, `threshold`, etc.) per [LSP Plugins manual](https://lsp-plug.in/?page=manuals) and [x42 dpl.lv2 docs](https://github.com/x42/dpl.lv2). Verify with `lv2info`.
- `stream.channelmap = [ AUX6 AUX7 ]` is the loopback selecting only the L6 master channels from the 12-ch multitrack stream. Verify this property name; if PipeWire rejects it, fall back to a `module-filter-chain` with builtin `copy` nodes wired only to AUX6/7 inputs (same pattern as `hapax-l6-evilpet-capture.conf` uses for AUX0).

### §8.2 New file: `~/.config/wireplumber/wireplumber.conf.d/52-l6-no-suspend.conf`

```ini
# Disable suspend on the Zoom L6 USB capture — broadcast bus must stay
# live continuously. Mirror of the existing 51-presonus-no-suspend.conf
# pattern.
monitor.alsa.rules = [
  {
    matches = [
      { node.name = "~alsa_input.usb-ZOOM_Corporation_L6*" }
    ]
    actions = {
      update-props = {
        session.suspend-timeout-seconds = 0
      }
    }
  }
]
```

### §8.3 Modifications to existing files

**`hapax-vinyl-to-stream.conf`** — RETIRE for vinyl-broadcast (the L6 supplants the 24c In 2 = "L12 mix bus" path that this file originally targeted). Keep the file disabled or delete after the new chain is verified live.

**`hapax-l6-evilpet-capture.conf`** — KEEP. The AUX0 Evil-Pet-voice-return path is independent of the new AUX6/7 broadcast path and serves daimonion voice modulation. Both filter-chains can coexist on the same multitrack capture.

**`hapax-livestream-tap.conf`** — KEEP unchanged. The new `55-broadcast-fx.conf` writes into `hapax-livestream-tap`, same producer→null-sink pattern.

**`voice-fx-chain.conf`** — KEEP unchanged. Hapax voice path is independent.

**`50-hapax-voice-duck.conf`** — KEEP. Role-based ducking continues to apply to the Multimedia/Notification roles; Assistant ducking continues to fire for Hapax TTS. Unrelated to vinyl chain.

### §8.4 Conf install + verification

```fish
# Install
cp 55-broadcast-fx.conf ~/.config/pipewire/pipewire.conf.d/
cp 52-l6-no-suspend.conf ~/.config/wireplumber/wireplumber.conf.d/

# Reload
systemctl --user restart pipewire pipewire-pulse wireplumber

# Verify nodes exist
pw-cli ls Node | grep -E "broadcast-fx|l6-master"

# Verify graph topology
pw-link -l | grep -E "l6-master|broadcast-fx|livestream-tap"
```

---

## §9 Test Plan to Validate the New Chain

### §9.1 End-to-end latency measurement

**Performance latency (operator monitor, sub-2 ms target):**

1. Patch a 1 kHz sine generator into Handytraxx LINE OUT (or play a known cut).
2. Observe Handytraxx output (analog scope on RCA) and L6 PHONES OUT (analog scope on TRS) simultaneously.
3. Trigger a sharp transient (needle drop, or sine generator gate). Measure time delta on scope.
4. Expected: <2 ms.

**Broadcast tap latency (host stack, ~10-13 ms target):**

1. With the chain live, capture the broadcast tap via `pw-cat --record /tmp/tap.wav --target hapax-livestream-tap.monitor`.
2. Use a recording loopback to feed L6 ch3 a 1 kHz sine with a sharp gate edge.
3. Time the edge in `/tmp/tap.wav` vs the gate trigger. Expected: ~10-13 ms.

**End-to-end broadcast latency (viewer ear, ~5-12 s target):**

1. Stream live to a private/unlisted YouTube broadcast.
2. On a phone, watch the broadcast.
3. Trigger a sharp percussive on Handytraxx; time the delay until heard on phone.
4. Expected: 5-12 s in standard latency; 2-3 s in low-latency mode; ~1 s in ultra-low-latency mode.

### §9.2 Gain staging (LUFS measurement)

1. Capture 5 minutes of representative live mix into `/tmp/broadcast-sample.wav` via `pw-cat --record --target hapax-livestream-tap.monitor`.
2. Measure integrated loudness:
   ```fish
   ebur128 /tmp/broadcast-sample.wav
   # or
   loudness-scanner -l /tmp/broadcast-sample.wav
   ```
3. Expected: integrated LUFS in **−16 to −13 LUFS** range (YouTube target).
4. Measure true-peak:
   ```fish
   ffmpeg -i /tmp/broadcast-sample.wav -af ebur128=peak=true -f null -
   ```
5. Expected: true-peak ≤ **−1.5 dBTP**. If higher, brickwall limiter is misconfigured.

### §9.3 xrun-free under load

1. Start broadcast filter-chain and L6 capture.
2. Start studio compositor (full GStreamer pipeline + cameras + RTMP egress).
3. Start hapax-daimonion (CPAL + STT + TTS).
4. Run for 30 minutes with vinyl playing through the chain.
5. Monitor xruns:
   ```fish
   pw-top -b
   # Watch the ERR column for the broadcast-fx-chain and L6 capture nodes.
   ```
6. Expected: ERR count remains 0 across all nodes for 30 min.

### §9.4 LUFS verification at YouTube ingest

1. Stream live to a private YouTube broadcast.
2. Open YouTube Studio → Stream Health.
3. Confirm "Bitrate normal", "Stream resolution", and audio level indicators.
4. After stream ends, download the unlisted VOD.
5. Re-measure LUFS of the YouTube transcode:
   ```fish
   ffmpeg -i youtube-transcode.mp4 -af ebur128 -f null -
   ```
6. Expected: integrated LUFS within ~1 dB of what we measured at the tap (YouTube's normalization should leave −14 LUFS audio mostly untouched).

### §9.5 Mode-switch verification

1. Set up chain in MODE A (ch3 fader up, ch4/5 down).
2. Switch to MODE B (faders inverse) via L6 fader move.
3. Confirm broadcast tap shifts to FX-dominant via spectral analysis (e.g. `meterbridge`, or a temporary LSP Spectrum Analyzer plugin teed off).
4. Switch to MODE C (ch3 fader full down, bed-music fader up).
5. Confirm dry vinyl is fully muted from broadcast tap.
6. Switch to MODE D (Evil Pet ch4 dominant, others muted).
7. Confirm broadcast tap shows granular re-synthesis dominant.

### §9.6 Failure-mode drill

1. Mid-stream, unplug L6 USB.
2. Observe: PipeWire detects disconnect, broadcast tap goes silent within 2 s. MediaMTX should hold last frame or fall to static-image fallback.
3. Re-plug L6 USB.
4. Observe: PipeWire re-instantiates `alsa_input.usb-ZOOM_Corporation_L6-00.multitrack`. Filter-chain auto-relinks (target.object resolution).
5. Vinyl audio resumes within 5-10 s.
6. Repeat with 24c USB unplug — confirm vinyl broadcast UNAFFECTED (only Cortado/Hapax voice impacted).

---

## §10 Open Questions

1. **Does the PipeWire `stream.channelmap` property pull a subset of multitrack channels reliably?** The existing `hapax-l6-evilpet-capture.conf` uses a `module-filter-chain` with builtin `copy` and explicit `null` mapping to extract AUX0 only. If `stream.channelmap` doesn't work in module-loopback for AUX6/7 selection, the new conf must use the same pattern (`copy` builtins with mostly-null inputs).
2. **Does the L6 master USB output carry the L6's onboard FX (reverbs, delay, echo) or only the dry mix?** Per [Zoom L6 manual](https://zoomcorp.com/manuals/l6-en/), L6 has built-in effects on MIC/LINE channels (1/2). For the topology, the operator should treat L6 onboard FX as "may or may not be in the broadcast bus" — verify per-channel routing in L6 settings.
3. **Does the L6 master USB include the SOUND PAD outputs?** The L6 has 4 sound pads (drum kit / sample triggers). These should appear on the master mix bus and therefore in AUX6/7 broadcast. Verify.
4. **Is the Evil Pet input balanced or unbalanced?** [Endorphin.es spec](https://www.endorphin.es/modules/p/evil-pet) says "1/4″ TS unbalanced". L6 AUX sends are TRS balanced. A TRS-to-TS cable will work but loses balanced advantages; use short cable runs (<1 m).
5. **What is the actual measured operator-monitor latency on the L6?** Vendor does not publish a number. Empirical measurement (§9.1) is required.
6. **Will Hapax voice (24c Out 2 → Evil Pet IN) and L6 AUX1 → Evil Pet IN coexist via passive Y-cable?** Resistor-summed Y-cables introduce ~6 dB attenuation but are otherwise acceptable. If audible bleed during vinyl performance, alternatives: (a) reroute Hapax voice to Torso S-4 instead, (b) use a small mixer at Evil Pet input (defeats purpose of L6 supplanting L12), (c) gate Hapax voice off during turntablist mode (CPAL gating already does this).
7. **What happens when L6 is in 32-bit float USB mode vs 24-bit?** The conf currently specifies `audio.format = S32LE`. For 32-bit-float capture, this should be `audio.format = F32LE`. Verify L6 USB mode and adjust.
8. **Does YouTube's live ingest accept variable-rate audio frames from PipeWire-driven encoders correctly?** The MediaMTX → RTMP path is well-tested for fixed-rate; the broadcast filter-chain should not introduce sample-rate variation, but verify with stream-health monitoring.
9. **Should the broadcast FX chain include an EBU R128 metering node (filter-chain `type = ebur128`)?** PipeWire supports inline R128 metering as a filter-chain type. Adding a measurement-only node would publish live LUFS to an inspectable property; useful for live monitoring but adds CPU. Decide based on operator preference.
10. **Is there a way to A/B compare pre-FX vs post-FX broadcast bus during rehearsal?** Could be done via a switcher loopback that flips between `l6-master-capture.monitor` and `broadcast-fx-out.monitor` with `pw-link` reroute. Operator tooling.

---

## §11 Sources

### Primary — manufacturer specs and manuals

- [PreSonus Studio 24c product page](https://www.presonus.com/products/studio-24c)
- [PreSonus Studio 24c Owner's Manual (PDF, fmicassets)](https://www.fmicassets.com/Damroot/Original/10001/OM_2777700403_Studio_24c_EN.pdf)
- [PreSonus Studio 24c Owner's Manual (PDF, B&H)](https://www.bhphotovideo.com/lit_files/484666.pdf)
- [PreSonus answers — main outputs balanced or unbalanced](https://answers.presonus.com/68438/presonus-studio-24c-are-the-main-outputs-balanced-unbalanced)
- [PreSonus answers — input combo jacks accept balanced TRS](https://answers.presonus.com/61711/the-input-combo-jacks-the-studio-24c-accept-balanced-trs-input)
- [Zoom LiveTrak L6 product page](https://zoomcorp.com/en/us/digital-mixer-multi-track-recorders/digital-mixer-recorder/livetrak-l6-final/)
- [Zoom L6 Operation Manual (web)](https://zoomcorp.com/manuals/l6-en/)
- [Zoom L6 Operation Manual (PDF)](https://zoomcorp.com/media/documents/E_L6.pdf)
- [Zoom L6 QuickTour (PDF)](https://zoomcorp.com/media/documents/E_L6_QuickTour.pdf)
- [Zoom L6 Sweetwater quickstart](https://www.sweetwater.com/sweetcare/articles/zoom-livetrak-l6-digital-mixer-quickstart-guide/)
- [Zoom L6 MusicRadar review](https://www.musicradar.com/music-tech/recording/zoom-livetrak-l6-review)
- [Endorphin.es Evil Pet product page](https://www.endorphin.es/modules/p/evil-pet)
- [Endorphin.es Evil Pet user manual (Manuals.plus)](https://manuals.plus/m/068472d380f335f9e901241a8c81ed421e1fc3973820446abe12e8e5eaeb4335)
- [Endorphin.es Evil Pet (Perfect Circuit overview)](https://www.perfectcircuit.com/signal/endorphines-evil-pet-review)
- [Endorphin.es Evil Pet (Synth Anatomy review)](https://synthanatomy.com/2025/10/endorphin-es-evil-pet-an-mpe-polyphonic-granular-synthesizer.html)
- [Torso Electronics S-4 product page](https://torsoelectronics.com/pages/s-4)
- [Torso S-4 manual 1v0v4a (PDF)](https://downloads.torsoelectronics.com/s-4/manual/The%20S-4%20Manual%201v0v4a.pdf)
- [Torso S-4 Sound on Sound review](https://www.soundonsound.com/reviews/torso-electronics-s-4)
- [Torso S-4 Perfect Circuit](https://www.perfectcircuit.com/torso-s-4.html)
- [Korg Handytraxx Play user guide (Manuals.plus)](https://manuals.plus/korg/handy-traxx-play-portable-record-player-manual)
- [Korg Handytraxx Play Owner's Manual (PDF)](https://cdn.korg.com/us/support/download/files/a179fc60a4266b29f2f0eb82c3eb0887.pdf?response-content-disposition=inline%3Bfilename%3Dhandytraxx_play_OM_En2.pdf&response-content-type=application/pdf%3B)
- [Korg Handytraxx Play (Korg US)](https://www.korg.com/us/products/dj/handytraxx_play/)
- [Erica Synths MIDI Dispatch product page](https://www.ericasynths.lv/shop/standalone-instruments-1/midi-dispatch/)
- [Erica Synths MIDI Dispatch (Synthtopia)](https://www.synthtopia.com/content/2025/09/06/erica-synths-debuts-midi-dispatch/)
- [Erica Synths MIDI Dispatch (Sound on Sound)](https://www.soundonsound.com/news/erica-synths-launch-midi-dispatch)
- [Erica Synths MIDI Dispatch (Perfect Circuit)](https://www.perfectcircuit.com/erica-midi-dispatch.html)
- [Erica Synths MIDI Dispatch (Music Tech)](https://musictech.com/news/gear/erica-synth-midi-dispatch/)

### Primary — Linux audio infrastructure (PipeWire, WirePlumber, ALSA)

- [PipeWire docs index](https://docs.pipewire.org/)
- [PipeWire: module-filter-chain](https://docs.pipewire.org/page_module_filter_chain.html)
- [PipeWire: module-loopback](https://docs.pipewire.org/page_module_loopback.html)
- [PipeWire: pw-loopback CLI](https://docs.pipewire.org/page_man_pw-loopback_1.html)
- [PipeWire: pipewire-props (clock, quantum, suspend)](https://docs.pipewire.org/page_man_pipewire-props_7.html)
- [PipeWire: pipewire.conf](https://docs.pipewire.org/page_man_pipewire_conf_5.html)
- [WirePlumber 0.5 ALSA configuration](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/alsa.html)
- [Arch Wiki: PipeWire](https://wiki.archlinux.org/title/PipeWire)
- [Arch manpage: libpipewire-module-loopback](https://man.archlinux.org/man/libpipewire-module-loopback.7.en)
- [Arch manpage: libpipewire-module-filter-chain](https://man.archlinux.org/man/libpipewire-module-filter-chain.7.en)
- [Pro-audio configuration guide (oneuptime)](https://oneuptime.com/blog/post/2026-03-02-configure-pipewire-low-latency-audio-ubuntu/view)
- [PipeWire pro-audio guide (EndeavourOS forum)](https://forum.endeavouros.com/t/pipewire-pro-audio-a-sorta-guide/26544)
- [PipeWire suspend disable (EndeavourOS forum)](https://forum.endeavouros.com/t/pipewire-disable-suspend-of-sink/58125)
- [PipeWire low-latency audio (Botmonster)](https://botmonster.com/posts/fix-pipewire-audio-linux-low-latency-recording/)
- [PipeWire NEWS (release notes)](https://github.com/PipeWire/pipewire/blob/master/NEWS)
- [PipeWire bit-perfect audio (Arch BBS)](https://bbs.archlinux.org/viewtopic.php?id=290859)
- [PipeWire xrun audible latency (Arch BBS)](https://bbs.archlinux.org/viewtopic.php?id=270879)

### Primary — LV2 plugins (LSP, x42, Calf, Airwindows)

- [LSP Plugins Project (lsp-plug.in)](https://lsp-plug.in/?page=news)
- [LSP Plugins Releases (GitHub)](https://github.com/sadko4u/lsp-plugins/releases)
- [LSP Begrenzer (Limiter)](https://vstwarehouse.com/d/lsp-begrenzer-limiter-plugin-series/)
- [LSP Dynamikprozessor (Compressor)](https://vstwarehouse.com/d/lsp-dynamikprozessor-plugin-series/)
- [LSP Impulsnachhall (Impulse Reverb)](https://vstwarehouse.com/d/lsp-impulsnachhall-impulse-reverb-plugin-series/)
- [LSP 1.2.8 release announcement (Ardour discourse)](https://discourse.ardour.org/t/lsp-plugins-1-2-8-released/108983)
- [x42 plugins index](https://x42-plugins.com/x42/)
- [x42 dpl.lv2 (GitHub)](https://github.com/x42/dpl.lv2)
- [x42 Digital Peak Limiter page](https://x42-plugins.com/x42/x42-limiter)
- [x42-plugins on Debian](https://packages.debian.org/sid/sound/x42-plugins)
- [x42 meters.lv2 (GitHub)](https://github.com/x42/meters.lv2)
- [Calf Studio Gear](https://calf-studio-gear.org/)
- [Calf manpage (Arch)](https://man.archlinux.org/man/calf.7.en)
- [Calf Studio Gear (Wikipedia)](https://en.wikipedia.org/wiki/Calf_Studio_Gear)
- [LV2 plugins for mixing (Libre Music Production)](https://linuxaudio.github.io/libremusicproduction/html/articles/lv2-plugins-mixing-my-favorite-basic-plugins-zthmusic.html)
- [Carla audio plugin host (KXStudio)](https://kx.studio/Applications:Carla)
- [Carla GitHub](https://github.com/falkTX/Carla)
- [PipeWire VST stacks using Carla (Ben Ashby)](https://www.benashby.com/resources/pipewire-vst-carla/)
- [Airwindows Consolidated](https://www.airwindows.com/consolidated/)
- [Airwindows Console9](https://www.airwindows.com/console9/)
- [Airwindows ConsoleX](https://www.airwindows.com/consolex/)
- [Airwindows ToTape7](https://www.airwindows.com/totape7/)

### Primary — broadcast/loudness standards and tooling

- [EBU R 128 (Wikipedia)](https://en.wikipedia.org/wiki/EBU_R_128)
- [Loudness Measurement EBU R128, Fons Adriaensen (PDF)](https://kokkinizita.linuxaudio.org/papers/loudness-meter-pres.pdf)
- [Ebumeter quick guide](https://kokkinizita.linuxaudio.org/linuxaudio/ebumeter-doc/quickguide.html)
- [loudness-scanner (GitHub)](https://github.com/jiixyj/loudness-scanner)
- [libebur128 (GitHub)](https://github.com/jiixyj/libebur128)
- [ebur128 manpage (Ubuntu)](https://manpages.ubuntu.com/manpages/trusty/man1/ebur128.1.html)
- [LKFS/LUFS meter for Linux (LinuxMusicians thread)](https://linuxmusicians.com/viewtopic.php?t=19981)
- [Sweetwater: Loudness Standards](https://www.sweetwater.com/insync/loudness-standards-lufs-peaks-and-streaming-limits/)
- [Sweetwater: Understanding Signal Levels](https://www.sweetwater.com/insync/understanding-signal-levels-audio-gear/)
- [Critical Listening Lab: Loudness Targets](https://www.criticallisteninglab.com/en/learn/loudness)
- [iZotope: mastering for streaming platforms](https://www.izotope.com/en/learn/mastering-for-streaming-platforms)
- [Clickyapps: target LUFS YouTube TikTok Spotify](https://clickyapps.com/creator/video/guides/lufs-targets-2025)
- [Sweetwater: how to master audio for YouTube](https://www.sweetwater.com/insync/how-to-master-audio-for-youtube/)
- [AESTD1008.1.21-9 technical document](https://www.aes.org/technical/documentDownloads.cfm?docID=731)

### Primary — RTMP / streaming infrastructure

- [VideoSDK: YouTube RTMP guide](https://www.videosdk.live/developer-hub/rtmp/youtube-rtmp)
- [MediaMTX (GitHub)](https://github.com/bluenviron/mediamtx)
- [MediaMTX latency discussion](https://github.com/bluenviron/mediamtx/discussions/3871)
- [YouTube Live Streaming Ingestion Protocol Comparison](https://developers.google.com/youtube/v3/live/guides/ingestion-protocol-comparison)
- [YouTube Help: Live encoder settings, bitrates, resolutions](https://support.google.com/youtube/answer/2853702)
- [OBS low-latency live streaming (HN thread)](https://news.ycombinator.com/item?id=41424954)

### Secondary — DJ practice, cue, vinyl gain

- [Digital DJ Tips: split cue](https://www.digitaldjtips.com/dj-tips-tricks-what-split-cue-is-why-you-may-want-to-use-it/)
- [Native Instruments: Traktor with external interface](https://support.native-instruments.com/hc/en-us/articles/210300885-How-to-Use-TRAKTOR-DJ-with-an-External-Audio-Interface)
- [Algoriddim: pre-cueing with headphones](https://www.algoriddim.com/hardware/precueing)
- [Mixxx hardware setup](https://manual.mixxx.org/2.0/en/chapters/setup)
- [VirtualDJ: master and headphones](https://virtualdj.com/manuals/virtualdj/settings/audiosetup/masterheadphones.html)
- [Vinyl Engine: phono preamp gain calculation](https://www.vinylengine.com/turntable_forum/viewtopic.php?t=116026)
- [Vinyl Engine: where best to add gain](https://www.vinylengine.com/turntable_forum/viewtopic.php?t=109564)
- [DJ splitter cable guide (djgear2k)](https://djgear2k.com/dj-splitter-cable-guide/)

### Secondary — Content ID and broadcast safety (cross-link to parent doc)

- [Scott Smitelli, "Fun with YouTube's Audio Content ID System"](https://www.scottsmitelli.com/articles/youtube-audio-content-id/)
- [Digital DJ Tips: 3 vital steps for DJing on YouTube without copyright hassle](https://www.digitaldjtips.com/3-vital-steps-for-djing-on-youtube-without-copyright-hassle/)
- Parent doc, this repo: `docs/research/2026-04-20-vinyl-collection-livestream-broadcast-safety.md`
- Sibling doc, this repo: `docs/research/2026-04-19-l6-multitrack-mode.md`
- Sibling doc, this repo: `docs/research/2026-04-14-audio-path-baseline.md`

### Internal config references (operator's existing PipeWire configs reviewed for this doc)

- `~/.config/pipewire/pipewire.conf.d/10-voice-quantum.conf`
- `~/.config/pipewire/pipewire.conf.d/voice-fx-chain.conf`
- `~/.config/pipewire/pipewire.conf.d/hapax-vinyl-to-stream.conf`
- `~/.config/pipewire/pipewire.conf.d/hapax-l6-evilpet-capture.conf`
- `~/.config/pipewire/pipewire.conf.d/hapax-livestream-tap.conf`
- `~/.config/pipewire/pipewire.conf.d/hapax-stream-split.conf`
- `~/.config/wireplumber/wireplumber.conf.d/50-hapax-voice-duck.conf`
- `~/.config/wireplumber/wireplumber.conf.d/50-presonus-default.conf`
- `~/.config/wireplumber/wireplumber.conf.d/50-studio24c.conf`
- `~/.config/wireplumber/wireplumber.conf.d/51-presonus-no-suspend.conf`
