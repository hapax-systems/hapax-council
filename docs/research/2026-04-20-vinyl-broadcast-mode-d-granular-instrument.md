# Vinyl Broadcast Mode D: Granular Wash as Content-ID Defeat and Compositional Instrument

**Status:** research
**Date:** 2026-04-20
**Operator:** single hip-hop producer (LegomenaLive YouTube channel)
**Parent doc:** `docs/research/2026-04-20-vinyl-collection-livestream-broadcast-safety.md` §7 (Mode D — "Granular wash")
**Sibling doc:** `docs/research/2026-04-19-evil-pet-s4-base-config.md` (signal compatibility + voice-chain CC map)
**Runtime hooks:** Programme primitive (`shared/programme.py`, commit `f6cc0b42b`); MonetizationRiskGate (`shared/governance/monetization_safety.py`, commit `0886d37ab`); MIDI Dispatch routing (commits `6d1ced049` + `fec97768d`)
**Register:** engaged practitioner — primary manufacturer documentation, practitioner-level testimony, academic source (Roads). Treats Content-ID empirics as time-decaying and granular technique as a long-standing aesthetic tradition.

---

## §1 TL;DR

Mode D — **vinyl source → Evil Pet → Torso S-4 → broadcast** with the granular engines fully engaged on both devices — is simultaneously the operator's strongest empirically-supported Content-ID defeat vector AND a compositional instrument with deep lineage in hip-hop, plunderphonics, vaporwave, and the Brainfeeder/Stones Throw beat-scene.

Three orthogonal claims justify treating Mode D as a first-class livestream practice rather than a defensive fallback:

1. **Empirical defeat (high confidence).** Smitelli 2020 establishes the ≥6% pitch / ≥6% time-stretch / ≥4–5% resampling thresholds for the public Content-ID fingerprint ([scottsmitelli.com](https://www.scottsmitelli.com/articles/youtube-audio-content-id/)). Granular re-synthesis with grain size ≤ 30 ms and high spray/jitter is *not* a thresholded transformation — it is a re-emission of the source from re-windowed micro-segments, producing a spectral-peak constellation distinct from the source even at modest density. Parent doc §5.3: "*granular synthesis at extreme settings is essentially a re-synthesis from grains and produces a fingerprint distinct from the source.*"

2. **Aesthetic legitimacy (settled).** From Curtis Roads' *Microsound* (2001) academic codification through John Oswald's *Plunderphonics* (1985) ([Wikipedia](https://en.wikipedia.org/wiki/Plunderphonics); [Oswald 1985 manifesto](https://econtact.ca/16_4/oswald_plunderphonics.html)) through Madlib's micro-chops on *Madvillainy* ([Loop Kitchen](https://loopkitchen.co.uk/blogs/loop-kitchen-blog/madlib-madvillainy-sampling-techniques)) and Burial's vinyl-crackle washes ([FACT 2016](https://www.factmag.com/2016/05/15/burial-turns-10-music-movie-video-game-roots/)) through Oneohtrix Point Never's *Replica* sampledelia ([Wikipedia](https://en.wikipedia.org/wiki/Replica_(Oneohtrix_Point_Never_album))) into Iglooghost's hyperpop sound-mangling ([Point Blank](https://www.pointblankmusicschool.com/blog/track-breakdown-iglooghost-shares-the-secrets-behind-his-production-techniques/)) — the genealogy of "vinyl-source-into-grains" as an idiom is older than YouTube. Mode D inherits this lineage; it is not a circumvention dressed in artistic clothing.

3. **Hardware fit (excellent).** The Evil Pet is an 8-voice polyphonic granular workstation with 512 MB / 10-minute buffer that *loves to process whatever is coming through, just like an effects pedal* ([Perfect Circuit overview](https://www.perfectcircuit.com/signal/endorphines-evil-pet-review)). The Torso S-4's Mosaic granular slot generates up to 128 grains with pitch-quantised scales and free/sync grain spawn ([Sound on Sound review](https://www.soundonsound.com/reviews/torso-electronics-s-4)). The chain-order **vinyl → Evil Pet → Torso S-4** stacks two independent granular re-syntheses in series, masking the source's spectral-peak constellation twice over.

The §7 proposal: nine **vinyl-source dimensions** (distinct from the nine vocal-chain dimensions) mapped to Evil Pet + Torso S-4 CCs via the same `vocal_chain.py`-style envelope machinery, gated by a Programme of role `livestream_director` whose `monetization_opt_ins` includes `mode_d_granular_wash` so MonetizationRiskGate permits the medium-risk capability.

---

## §2 Granular as Content ID defeat — empirical

### §2.1 The fingerprint object

YouTube Content ID and Shazam-family fingerprinters compute a *constellation map* — a sparse set of (time, frequency) coordinates of local spectrogram peaks, hashed in pairs to form database keys ([Wang/Shazam algorithm summary](https://www.cameronmacleod.com/blog/how-does-shazam-work); [Towards Data Science on Shazam](https://towardsdatascience.com/the-five-second-fingerprint-inside-shazams-instant-song-id/); [Wikipedia: Acoustic fingerprint](https://en.wikipedia.org/wiki/Acoustic_fingerprint)). The defeat surface is therefore **not** "destroy audio quality" but "redistribute spectral peaks so the hash pairs no longer match the reference."

A useful corollary: any transformation that re-emits the audio from windowed micro-segments — even at modest density — replaces the original peak constellation with a constellation derived from the windowing function's interaction with each grain, not from the original's continuous spectrum. The *original peaks no longer exist in the output* unless the grain is large enough to preserve them, which leads to the size analysis in §2.3.

### §2.2 Smitelli 2020 thresholds — the empirical baseline

Scott Smitelli's 2020 study ([scottsmitelli.com: Fun with YouTube's Audio Content ID System](https://www.scottsmitelli.com/articles/youtube-audio-content-id/)) is still the most-cited empirical decomposition of the defeat surface for the public Content ID fingerprint. The thresholds reported (parent doc §5.1):

| Modification | Defeat threshold | Notes |
|---|---|---|
| Pitch shift (preserve duration) | ≥6% in either direction | ≈ 1 semitone, perceptible |
| Time stretch (preserve pitch) | ≥6% in either direction | perceptible to attentive listener |
| Resampling (speed change) | ≥4% slower, ≥5% faster | both axes change together |
| Reversal | always defeats | musically inert for whole tracks |
| Stereo phase inversion | always defeats | fingerprinter is mono-collapsing |
| Volume change | never defeats | fingerprint is amplitude-invariant |
| White noise overlay | only at ≥45% N/S ratio | inversely proportional to source dominance |

Smitelli does **not** test granular re-synthesis directly. The closest analogue is the noise overlay measurement, which establishes that masking — replacing some fraction of the spectral content with non-source content — defeats fingerprinting only when the non-source content dominates the peak constellation. Granular generalises this: each grain is a window-modulated re-emission of a tiny slice of source, so the resulting constellation is the *grain-windowing constellation* rather than the *source constellation*. The defeat strength scales with grain density × position spray × pitch jitter — the parameters that scramble where, when, and at what frequency the new peaks land.

### §2.3 Grain size as the operative variable

The microsound literature (Roads 2001, *Microsound*; [Truax: Granular Synthesis](https://www.sfu.ca/~truax/gran.html); [Wikipedia: Granular synthesis](https://en.wikipedia.org/wiki/Granular_synthesis)) divides grain durations into three perceptual regions, each with distinct Content-ID-defeat implications:

**Short grains (1–30 ms).** This is the "microsound" regime where grains lose their character as audio events and become *spectral particles* — the windowing function dominates, individual grains are inaudible as discrete events, and the output is heard as continuous texture or pitched cloud. From a fingerprinting perspective, **this is the deepest defeat region**: each grain's spectrum is dominated by the convolution of its tiny audio slice with the window function, producing peaks that bear almost no relation to the source's peak constellation. Roads notes that 20 ms grains cover a one-second cloud at ~100 grains, with sub-50 ms gaps perceived as amplitude fluctuation rather than silence — meaning even sparse clouds in this region defeat fingerprinting.

**Medium grains (30–200 ms).** The traditional "granular synthesis" range. Source recognition is partial — recognisable pitch and timbre survive, but rhythmic and melodic structure scrambles. Fingerprinting defeat is intermediate: at low density / high spray, defeat is robust; at high density / low spray, the source can re-emerge. This is the region where granular *as a vocabulary* (rather than as a defeat tool) is most expressive.

**Long grains (200 ms – 2 s).** Approaches the boundary of "granular" vs "looping/chopping." At this scale, individual grains preserve enough of the source spectrum that fingerprinting re-attaches at moderate confidence. **This region is *not* a reliable defeat vector** unless combined with pitch jitter ≥6% per grain (which then satisfies the Smitelli threshold per-grain).

**Operative recommendation:** Mode D defaults to grain size 10–50 ms (short / lower-medium) for defeat robustness. Aesthetic mode-shifts can push grain size to 200–500 ms when source recognition is desired (e.g., quoting a recognisable hook in transformed form, where the legal/ethical posture is "audible attribution-by-quotation").

### §2.4 Spray, density, and position randomisation

The parameters that scramble *where* in the source each grain is drawn from, and *when* it is emitted, are the second axis of fingerprinting defeat after grain size. The relevant Evil Pet and S-4 controls:

- **Position spray** (Evil Pet `Spread`, Torso `Spray`) — randomises the read-head position within the buffer per grain. Even at modest spread (~30%), consecutive grains no longer come from contiguous source — the time-domain ordering of the source is destroyed, which destroys the time-frequency structure the fingerprinter expects.
- **Density / grain rate** (Evil Pet `Cloud`, Torso `Rate`) — controls grains per second. At 50–200 grains/sec with 20 ms grains, the output is a continuous texture; the fingerprinter's peak-picking sees a smeared spectrum rather than the source's sparse peaks.
- **Pitch jitter / detune** (Evil Pet `Detune`, Torso `Pitch + scale`) — per-grain pitch deviation. Even ±2% per-grain detune produces an output where no two grains share a pitch contour with the source; the constellation peaks land at scattered frequencies rather than the source's stable harmonics.
- **Grain shape / window** (Evil Pet `Shape`) — controls envelope of each grain (Gaussian, Hann, rectangular, exponential). Shape changes the spectral spread of the windowing artefact; rectangular windows produce wider sidelobes, which add more non-source peaks.

**Empirical synthesis:** the public-knowledge result (parent doc §5.5) is that *single-stage reverb does not defeat Content ID; granular re-synthesis does; layering with two or more independent transformation sources does*. Mode D operationalises both: granular re-synthesis (Evil Pet) layered with a second granular re-synthesis (Torso S-4), each with independent spray/density parameters.

### §2.5 What 2020-2026 community reporting actually shows

Hard practitioner reports of "I tried granular and it survived/failed Content ID" are not abundant in 2026 — most DJ-community reporting still focuses on the Smitelli thresholds (pitch ≥6%, time ≥6%, the "test upload" pre-flight workflow per [Digital DJ Tips](https://www.digitaldjtips.com/3-vital-steps-for-djing-on-youtube-without-copyright-hassle/)). Where granular comes up, it's typically as one component of a composite ("heavy granular + reverb + parallel layer") rather than tested alone. This is consistent with parent doc §5.5: granular is folk-knowledge effective but not isolated in the literature.

What this means operationally: **Mode D's defeat properties are derived from the underlying spectral-peak-constellation theory, not from a citable head-to-head test.** The operator should treat the §2.3 / §2.4 parameter regions as *probable* defeats, run the parent doc §8.1 pre-flight test on each new Mode D patch before relying on it, and re-test quarterly per parent doc §9.1 since the fingerprint algorithm evolves.

The strongest standing recommendation: combine Mode D's granular re-synthesis with the parent doc §7 ≥6% pitch/time VST stage at the post-encoder hand-off. This guarantees Smitelli-threshold defeat *even if* the fingerprint algorithm has been updated to detect short-grain re-synthesis. Two independent defeat vectors — only one needs to hold.

---

## §3 Granular as hip-hop instrument — aesthetic tradition

### §3.1 The lineage in one paragraph

Curtis Roads' *Microsound* (2001) provides the academic codification, but the practice is older and broader. John Oswald's *Plunderphonics* (1985, reissued *Plunderphonics 69/96*) established the use of vinyl-source manipulation as a compositional medium with a distinct ethic (audio piracy as compositional prerogative; [Oswald's own 1985 manifesto](https://econtact.ca/16_4/oswald_plunderphonics.html); [Wikipedia](https://en.wikipedia.org/wiki/Plunderphonics)). MPC-era boom-bap (Akai MPC-60 onwards) introduced *micro-chopping*: slicing recognisable phrases into sub-second fragments and reordering them ([Boom Bap ex Machina, Mike D'Errico thesis](https://www.cs.tufts.edu/~jacob/250hcm/MikeDErricoMAthesis.pdf)). The L.A. beat scene around Stones Throw and Brainfeeder (Madlib, J Dilla, Dibiase, Knxwledge, Mndsgn, Flying Lotus) refined micro-chopping into a *texture-first* aesthetic where the sample becomes a particle of source ([Micro-Chop on Madvillainy](https://medium.com/micro-chop/i-dont-remember-the-samples-i-use-hell-no-the-story-of-madvillainy-e6b378d4689c)). Burial inverted the technique, foregrounding *vinyl crackle and tape dropout as the texture itself* ([FACT on Burial 10 years on](https://www.factmag.com/2016/05/15/burial-turns-10-music-movie-video-game-roots/)). Oneohtrix Point Never's *Replica* (2011) and the broader vaporwave / hypnogogic-pop movement made vinyl-source granular wash an *album-length compositional thesis* rather than an effect ([Wikipedia: Replica](https://en.wikipedia.org/wiki/Replica_(Oneohtrix_Point_Never_album)); [Wikipedia: Vaporwave](https://en.wikipedia.org/wiki/Vaporwave)). Iglooghost and the Brainfeeder-adjacent hyperpop continuation pushed the per-grain manipulation density into the hundreds-of-events-per-second region ([Point Blank breakdown](https://www.pointblankmusicschool.com/blog/track-breakdown-iglooghost-shares-the-secrets-behind-his-production-techniques/); [DJ Mag](https://djmag.com/pointblank/watch-iglooghost-share-secrets-behind-his-production-techniques-point-blank)).

### §3.2 When granular is the music vs decorative

Three positions:

**Granular as decoration.** The classic case: a sustained synth or pad is fed through a granular processor for "shimmer" or "wash." The source remains identifiable; granular adds atmosphere. Most commercial use is in this register. *Not the Mode D target.*

**Granular as transformation.** The source is recognisable but transformed — chopped, micro-edited, pitch-quantised — so that the listener perceives both "the source" and "the operator's intervention." Hip-hop's micro-chopping tradition lives here: Madlib's "Fancy Clown" intro is a Zeze Hill record chopped into uneven micro-pieces and reassembled ([Loop Kitchen on Madvillainy](https://loopkitchen.co.uk/blogs/loop-kitchen-blog/madlib-madvillainy-sampling-techniques)); Burial's "Untrue" hooks are R&B vocal phrases time-stretched into agitated breakbeat sub-figures ([FACT 2016](https://www.factmag.com/2016/05/15/burial-turns-10-music-movie-video-game-roots/)). *Mode D's "Refraction" and "Stutter" sub-aesthetics live here.*

**Granular as constitutive.** The granular process IS the music — the source is a substrate, a colour palette, a generative seed, but not the foreground. Oneohtrix Point Never's *Replica* uses TV-advertisement audio as raw material that is recognisable only as *texture-of-the-1990s*, never as identifiable cues; the album is "chopped and screwed plunderphonics" per Stereogum's Miles Bowe ([Wikipedia: Replica](https://en.wikipedia.org/wiki/Replica_(Oneohtrix_Point_Never_album))). Vaporwave generalises this: a Diana Ross hook stretched to 30 seconds via PaulStretch, drowned in convolution reverb, becomes *not* a Diana Ross sample but *a vaporwave object*. *Mode D's "Distance," "Cloud," and "Decay" sub-aesthetics live here.*

### §3.3 Specific tracks for the operator's listening — see §8.

### §3.4 Vinyl-source-into-granular as a specific practice

A few touchstone moves:

- **The Madlib stitch.** Take a soul/jazz LP intro, chop into 4–10 micro-pieces of unequal length, reorder. The grain size here is "human-scale" (200–800 ms, MPC pad-length) but the *composition operation* is granular. Mode D scales this down into the sub-100 ms region.
- **The Burial smear.** Foreground vinyl crackle and tape dropout as the *bed*; layer R&B vocal grains on top at irregular intervals. The crackle/dropout is itself granular noise — Burial constructed it from sample-and-hold field-recording layers.
- **The vaporwave stretch.** Take a 4-bar lounge-jazz phrase, time-stretch 8x via granular phase-vocoder (PaulStretch is the canonical tool — [vaporwave production guide](https://www.plugg-supply.net/forum/news/vaporwave-history-sound-production-guide-2026-the-complete-breakdown)), drown in 8-second convolution reverb. The source becomes a sustained chord, no longer a melody. **This is Mode D's deepest "Cloud" setting.**
- **The OPN micro-event.** Sample a 0.5–2 second TV-ad fragment, granulate at 50 ms grain size with high spray, sequence grains into a pseudo-melody using grain pitch quantisation. The output is recognisable as "from the 90s" but unidentifiable as any specific source.

The operator's vinyl crate, fed into Mode D, draws on all four traditions simultaneously.

### §3.5 The MPC-to-granular continuity

The MPC's pad-based slicing is a discrete-grain operator at human pad-press density (1–10 grains/sec, 200ms-1s grain length). Modern granular hardware extends this continuum into the 100s of grains/sec, sub-30 ms region. The vocabulary — chop, retrigger, stutter, repeat, freeze, smear — is the *same vocabulary* operating at different time scales. The operator already speaks MPC-fluent (per workspace memory: hip-hop producer); Mode D is an extension of that fluency into Roads' microsound time scale, not a foreign technique.

---

## §4 Evil Pet deep capability + patches

### §4.1 Engine architecture

The Endorphin.es Evil Pet is a desktop polyphonic granular workstation with multi-FX, FM radio, sample player, and reel-recorder roles in a single device ([Endorphin.es product page](https://www.endorphin.es/modules/p/evil-pet); [Perfect Circuit overview](https://www.perfectcircuit.com/signal/endorphines-evil-pet-review); [Synth Anatomy](https://synthanatomy.com/2025/10/endorphin-es-evil-pet-an-mpe-polyphonic-granular-synthesizer.html)). The granular engine is **8-voice polyphonic** — eight independent grain streams can play simultaneously, each with its own position, pitch, and envelope. Conversion is **24-bit / 48 kHz with 32-bit internal headroom**. RAM is **512 MB**, giving a maximum **10-minute audio buffer** that refreshes continuously like a reel-to-reel tape. The 2.42" OLED visualises the current grain positions on the buffer waveform.

The signal flow inside the device is roughly: **input source (line / mic / FM / SD) → input gain → granular engine (parallel with dry path, governed by `Mix`) → digital oscillator layer → resonant multimode filter → saturator → reverb → master volume**. The granular engine takes the input audio as its grain source when source = LINE.

### §4.2 Granular-specific controls (manual + community knowledge)

Combined from [Endorphin.es product page](https://www.endorphin.es/modules/p/evil-pet), [manuals.plus user manual](https://manuals.plus/m/068472d380f335f9e901241a8c81ed421e1fc3973820446abe12e8e5eaeb4335), and [midi.guide CC chart](https://midi.guide/d/endorphines/evil-pet/):

| Control | Function | Range | Voice-chain CC | Mode-D usage |
|---|---|---|---|---|
| `Position` | Grain read-head position in buffer | 0–100% | (TBD) | spray center; modulate slowly for sweep |
| `/Spread` (SHIFT+Position) | Position randomisation per grain | 0–100% | (TBD) | **primary defeat axis — push to ≥40%** |
| `Size` | Grain duration; CW = forward, CCW = reverse | ~1 ms – 1 s | (TBD) | **primary defeat axis — keep ≤30 ms** |
| `/Cloud` (SHIFT+Size) | Grain density (grains per second) | low → high | (TBD) | push to high for "wash"; lower for "stutter" |
| `Pitch` | Per-voice pitch transposition | ±octaves | 44 (used for `vocal_chain.pitch_displacement`) | center for source-true; offset for "refraction" |
| `Grains` | Master grains volume / engine wet | 0–100% | 11 (clamped OFF for voice; **fully ON for Mode D**) | the primary on/off for Mode D |
| `/Detune` (SHIFT+Pitch) | Per-grain pitch jitter | 0–semitones | (TBD) | secondary defeat axis — small detune scrambles peaks |
| `Spread` (panning) | Stereo position randomisation | 0–100% | (TBD) | wide = "cloud"; narrow = "stutter" |
| `Shape` | Grain envelope window shape | discrete | (TBD) | rectangular = harsher, more spectral spread; Gaussian = smoothest |
| `Mix` | Master wet/dry between dry signal and processed | 0–100% | 40 | **set high (≥80%) for Mode D — kill the dry to defeat fingerprint** |
| `Volume` | Output level | 0–100% | 7 | unity unless feeding hot |

**Gap from voice-chain config:** the existing `2026-04-19-evil-pet-s4-base-config.md` §3.2 sets `Grains volume (CC 11) = 0` and `Mix (CC 40) = 50`. Mode D **inverts both**: `Grains volume = 110+, Mix = 100+ (or as close to fully wet as the device allows)`. This is the load-bearing distinction between the voice base config (granular off, dry signal preserved as speech) and Mode D (granular dominant, dry signal suppressed to defeat fingerprint).

### §4.3 Filter / saturator / reverb in Mode D

Mode D doesn't bypass the FX chain — it uses each block to deepen the granular wash:

- **Filter** (CC 70 freq, CC 71 reso, CC 80 type): a **bandpass** with slow filter sweep adds spectral motion; a **comb** filter introduces resonant artefacts that further scramble the constellation. Voice config keeps reso ≤60; Mode D can push reso to 80+ for "wet sweep" effect.
- **Saturator** (CC 39 amount, CC 84 type): the `bit-crush` mode at moderate setting (40–60) further fragments the granular output into quantised steps — a classic vaporwave/hypnogogic move. Voice config caps at 80 to preserve intelligibility; Mode D has no intelligibility constraint (it's not voice).
- **Reverb** (CC 91 amount, CC 93 tail, CC 95 type, CC 94 shimmer): the **shimmer** parameter is a 5th aesthetic move — adds octave-up reflections to the reverb tail, producing the OPN-adjacent "iridescent cloud" effect. Voice config disables shimmer (anthropomorphic); Mode D embraces it as a deliberate aesthetic.

### §4.4 Latency and buffer behaviour

The device uses a **continuously refreshing buffer up to 10 minutes** ([Perfect Circuit overview](https://www.perfectcircuit.com/signal/endorphines-evil-pet-review)). For Mode D's *live* vinyl playback, the buffer is constantly being filled with the latest vinyl audio; grains are read from this buffer at positions controlled by the Position knob. **The processing latency at 48 kHz with 32-bit internal is sub-frame (~21 µs)** for the granular engine itself; the audible latency is dominated by the grain size + the buffer-fill latency.

For Mode D performance, the implication is: **Position = ~95% (near the latest-written buffer point)** plays grains drawn from "the last few hundred ms of the vinyl"; **Position = 50%** plays grains from the middle of the buffer (audio from ~5 minutes ago). This is the operator's primary control over *temporal distance* — Mode D can be "currently playing vinyl, granulated" or "vinyl played 4 minutes ago, granulated NOW" depending on Position.

The buffer offers a non-defeat property the operator can use compositionally: *temporal collage*. Operator can drop one record, let the buffer fill, drop a different record, and Mode D will granulate both simultaneously by sweeping Position across the buffer. **This is a Mode D-exclusive compositional move that no other Mode supports.**

### §4.5 Patches / community-shared configurations for vinyl-source

The Evil Pet is recent (2025) and the public patch library is small. Key starting points:

- The official "Polyphonic Granular Workstation" demo ([Blip product page](https://weareblip.com/products/endorphin-es-evil-pet)) walks through processing an external instrument input — directly applicable to vinyl.
- Robert Cole's *Live granular techniques explored* video ([YouTube](https://www.youtube.com/watch?v=tXQzW5pEhNY)) is the most-referenced practitioner walkthrough.
- ModWiggler thread on the Evil Pet ([modwiggler.com](https://www.modwiggler.com/forum/viewtopic.php?t=296887)) collects user patches, primarily Eurorack-context but the granular-on-external-input subset transfers.

The operator should **build patches incrementally** rather than copy from community: the Mode D parameter region is operator-specific, optimised for the hip-hop vinyl crate and the operator's existing aesthetic. A starter patch is given in §7.4.

---

## §5 Torso S-4 deep capability + chain order

### §5.1 The S-4 architecture in one paragraph

The Torso Electronics S-4 is a 4-track sculpting sampler with a 5-slot device chain per track: **Material → Granular → Filter → Color → Space** ([Torso product page](https://torsoelectronics.com/products/s-4); [Sound on Sound review](https://www.soundonsound.com/reviews/torso-electronics-s-4); [MusicTech review](https://musictech.com/reviews/hardware-instruments/torso-electronics-s-4-review/); [MusicRadar review](https://www.musicradar.com/music-tech/samplers/torso-electronics-s-4-review)). Material can be **Bypass** (passes line-in directly into the chain) — which is the configuration that makes the S-4 useful as a vinyl/voice processor. The Mosaic granular slot is the centerpiece for Mode D.

### §5.2 Mosaic granular slot — deep dive

Mosaic supports **up to 128 grains** with **pitch-shifting up to ±36 semitones**, **grain spawn rate that can free-run or lock to tempo**, and **scale-quantised grain pitches** ([Sound on Sound review](https://www.soundonsound.com/reviews/torso-electronics-s-4); [Torso S-4 manual OS 1.0.4](https://downloads.torsoelectronics.com/s-4/manual/The%20S-4%20Manual%201v0v4a.pdf)). Eight rotaries control: **Pitch, Rate, Warp, Spray** (and four others — Density, Length, Position, Random/Pattern, depending on context).

The Mosaic-specific moves the operator should care about:

- **Pitch quantisation to scale.** Unlike Evil Pet's continuous Pitch, Mosaic can constrain per-grain pitches to a scale (chromatic, major, minor, custom). For a vinyl source, this means the granulated output is *musically coherent* — grains land on harmonically meaningful pitches even when the source's actual pitch is scrambled. **This is the primary aesthetic distinction between Mode D-Evil Pet-only and Mode D-via-S-4**: S-4 enforces musical structure on the chaos.
- **Rate sync.** Mosaic's grain spawn can lock to S-4's internal tempo (or external sync). At BPM-locked rate (1/16 grains, etc.), the granular output carries a rhythmic pulse — useful for keeping the granulated vinyl "in time" with the operator's broader livestream tempo context.
- **Warp.** Time-stretches each grain's playback within itself — a per-grain micro-time-stretch. Combined with high spray, Warp produces the "frozen in motion" effect characteristic of OPN's late work and Iglooghost's hyperpop transitions.
- **Built-in pattern modulation.** Mosaic includes pattern presets that automatically modulate grain pitches across the grain stream — quickly summoned variation without manual sequencing ([Sound on Sound review](https://www.soundonsound.com/reviews/torso-electronics-s-4)).

### §5.3 The other slots in Mode D

Material slot **must be Bypass** for line-in passthrough (per [voice-chain doc §4.1](file:///home/hapax/projects/hapax-council/docs/research/2026-04-19-evil-pet-s4-base-config.md)). Mosaic Granular slot is the **active centerpiece**. Filter (Ring), Color (Deform), Space (Vast) are **all engaged** for Mode D — unlike the voice-chain Mode B where Ring is conservative.

- **Ring (filter)** — at high resonance (≥60) and low decay (≤30%), Ring becomes a *pitched resonator* that adds tonal-melodic character to the granular cloud. The "Scale" parameter (chromatic / major / minor) constrains its resonant pitches to the same scale Mosaic is quantised to. **This is the move that makes Mode D *musical* rather than just textural.**
- **Deform (color)** — bit-crush at high setting (≥80) is the vaporwave move; tape-saturation at moderate (~50) is the lo-fi move; the two are mutually exclusive on the Deform device.
- **Vast (space)** — long delay (1/4 dotted, feedback ~70%) + long reverb (decay ~5s, size ~80%) is the "cathedral" Mode D setting. Short delay + short reverb is the "intimate" Mode D setting.

### §5.4 CC chart for Mode D

From the OS 1.0.4 manual ([downloads.torsoelectronics.com](https://downloads.torsoelectronics.com/s-4/manual/The%20S-4%20Manual%201v0v4a.pdf)) and the voice-chain doc §5.2 — the CCs already documented for the existing voice-chain map plus the Mosaic-specific CCs:

**Mosaic granular slot** (Channel 1, Track 1):

| Param | CC# (verify on device) | Mode-D range | Notes |
|---|---|---|---|
| Pitch | 65 | center 64 ± 30 | per-grain pitch (semitones) |
| Rate | 66 | 80–110 | grains/sec; high = wash, low = stutter |
| Warp | 67 | 30–80 | per-grain time-stretch |
| Spray | 68 | 60–110 | position randomisation — Mode D's primary defeat axis |
| Density | (TBD) | 80–120 | active grains simultaneously |
| Length | (TBD) | 10–40 | grain length in ms — Mode D keeps short |
| Position | (TBD) | 0–127 | buffer read position |
| Pattern | (TBD) | discrete | grain-pitch modulation pattern |

**Ring filter slot** (in Mode D): higher than voice-chain ranges:
- Cutoff (CC 79): 50–110 (full sweep range)
- Resonance (CC 80): 50–80 (high — pitched resonator effect)
- Wet (CC 86): 60–100 (Ring dominant in Mode D)

**Deform color** (Mode D-specific):
- Drive (CC 95): 40–90
- Crush (CC 98): **0 or 80–127** (binary: clean OR vaporwave-bit-crushed)

**Vast space** (Mode D-specific):
- Delay Time (CC 113): 1/4D or 1/2 (long delays)
- Reverb Decay (CC 119): 70–120 (long tail)
- Reverb Size (CC 115): 80–127 (cathedral)

### §5.5 Chain order — critical decision

Two viable chain orders. **Operator must test both.**

**Chain A (recommended baseline): vinyl → Evil Pet → Torso S-4 → broadcast.**
- Evil Pet performs the first granular re-synthesis. Position spray scrambles time-domain order; grain size kills source spectrum.
- Torso S-4's Mosaic re-granulates the *already-granulated* signal. Pitch quantisation re-imposes musical structure; Ring resonator adds tonal coherence; Vast space adds depth.
- **Result:** maximally defeat-strong (two independent re-synthesis stages), maximally aesthetically processed.
- **Risk:** the second granular stage may "smooth over" some of the first stage's defeat properties — if Mosaic re-extracts coherent peaks from the Evil Pet output, the fingerprint may partially re-attach. Quarterly pre-flight test (parent doc §9.1) is required.

**Chain B (alternative): vinyl → Torso S-4 → Evil Pet → broadcast.**
- Torso S-4 performs the first granular pass with musical pitch quantisation.
- Evil Pet performs the second pass with high spray and short grains, scrambling the now-musically-quantised output.
- **Result:** the second granular stage destroys the musical coherence imposed by S-4 — the output is "musically conceived but textural in execution."
- **Risk:** less aesthetically intentional — feels like "S-4 did interesting work and Evil Pet smudged it."

**Recommendation:** Chain A as default. Chain B as a deliberate aesthetic mode-shift for "deep cloud" passages where the operator wants OPN-grade illegibility.

A third option — **parallel rather than serial** (vinyl split, both processors run independently, summed at the L6) — is unsupported by the current physical signal path (Evil Pet does not have a thru/dry-out separate from its main out, and the operator's L6 channels are already allocated per voice-chain doc §6). If the operator later adds a second L6 input, parallel becomes possible and would offer the strongest fingerprinting defeat (two independent constellations summed, neither of which matches the source).

### §5.6 Latency

The S-4 is a digital device with internal DSP buffering. Public specifications do not document a precise latency figure; community reports place the round-trip at **~5–15 ms** for line-in-to-line-out at 48 kHz. For Mode D this is acceptable — the operator is not playing the granulated output as a beat-grid voice; minor latency shifts the broadcast by a few milliseconds, which is inaudible.

For **Chain A** (Evil Pet → S-4), the *cumulative* latency is the sum of both devices, plus cable propagation (negligible). Estimate **15–30 ms total**, well under the 50–100 ms threshold where livestream lip-sync (if there is video) becomes problematic. For audio-only or studio-camera-driven video, this is invisible.

---

## §6 Live workflow: engaging Mode D mid-set

### §6.1 The transition problem

Mode D is the deepest transformation in the operator's mode taxonomy. Switching from Mode A (selector) or Mode B (turntablist) to Mode D involves:

1. Engaging Evil Pet's granular engine (Grains volume CC 11: 0 → 110)
2. Pushing Evil Pet's wet/dry mix (Mix CC 40: 50 → 100)
3. Engaging Torso S-4's Mosaic (granular slot active, granular wet ≥60)
4. Optionally pushing Vast space to long reverb / long delay

Done abruptly, this is a **sonic cliff**: the audience perceives the transformation as an effect-on / effect-off rather than a gradual aesthetic shift. The MIDI Dispatch macro (parent doc §7.1) can flip these in one press, but the operator should consider *staged* transitions for aesthetic continuity:

### §6.2 Staged transition protocol

A 4-step transition over 10–30 seconds:

1. **Pre-arm** (T-0): Mode D parameters loaded but `Grains volume` and `Mix` still at MODE B values. No audible change yet.
2. **Engage granular** (T+0 to T+3s): ramp `Grains volume` 0 → 110 over 3 seconds. Audience hears granular wash *layered on top of* the dry vinyl. **Both signals coexist.**
3. **Suppress dry** (T+3 to T+8s): ramp `Mix` 50 → 100 over 5 seconds. The dry vinyl *fades out* under the now-dominant granular wash. **Audience perceives a transition into texture.**
4. **Deepen space** (T+8 to T+15s): optional ramp on Vast `Reverb Decay` and `Reverb Size` — pushes the granular wash into deeper space, signalling "Mode D is the destination, not a way-point."

Reverse for de-engagement (Mode D → Mode B): suppress space first, then re-introduce dry, then disengage granular. The audience perceives "the signal is returning to source" rather than "the effect is being turned off."

The MIDI Dispatch macro layer can be configured with **two macro slots**: instant-engage (single press, abrupt — for emergency) and staged-engage (multi-press over a configurable interval — for performative transitions). The current command-registry surface (`hapax-council` `lib/commands/`) supports timed sequences via the `sequences.ts` system (see CLAUDE.md § Command Registry); a `mode_d.engage_staged` sequence is the natural integration point.

### §6.3 Layering — keep some raw vinyl underneath

The parent doc §5.4 notes that *parallel transformations defeat fingerprinting more reliably than series transformations*. For Mode D, this suggests the operator should consider **not fully suppressing the dry vinyl** — keeping a low-level dry channel (~-12 to -18 dB) underneath the granular wash:

- **Defeat property:** the dry signal contributes some peaks at the original source's constellation, but they are dominated by the granular wash's peaks. The fingerprinter sees a constellation that is mostly granular + a small fraction of source — likely below match threshold.
- **Aesthetic property:** the audience hears the original vinyl "through" the granular wash, like seeing a photograph through frosted glass. This is the *Burial smear* aesthetic — vinyl crackle and hint-of-source as the bed underneath the foreground texture.

**Operative recommendation:** Mode D-default keeps Evil Pet `Mix` at ~85% (slight dry leak); Mode D-deep pushes `Mix` to 100% (full wash). The operator can flip between the two via a sub-mode toggle.

### §6.4 Recovery — dropping back to Mode A/B

When Mode D has done its DMCA-defeat job (e.g., a passage of high-recognition material has been transformed), the operator can return to Mode B (turntablist) for a higher-energy section. The reverse staged transition (§6.2) takes 10–30 seconds. During this transition the Content-ID exposure is *partial* — the dry signal is being re-introduced. **The operator should ensure the next vinyl on the platter is one of the lower-Content-ID-risk records** (per parent doc §8.1 pre-flight tests) when transitioning out of Mode D, since Mode D was probably engaged because the previous record was high-risk.

### §6.5 Programme integration

The Programme primitive (commit `f6cc0b42b`, `shared/programme.py`) is the runtime hook for Mode D as a **structured creative practice** rather than an ad-hoc effect. A `mode_d_session` Programme would:

- `role: livestream_director`
- `monetization_opt_ins: ["mode_d_granular_wash"]` (so MonetizationRiskGate permits the medium-risk capability)
- `capability_bias_positive: {vinyl_source.spray: 0.8, vinyl_source.cloud: 0.7, vinyl_source.refraction: 0.6}` (soft priors that bias the affordance pipeline toward Mode D dimensions)
- `narrative_beats: ["pre_arm", "engage_granular", "suppress_dry", "deepen_space"]` (the §6.2 staged transition as a programme structure)
- `success_criteria: {content_id_warnings: 0, audience_retention: ">90%"}` (defeat strength + aesthetic acceptability)

The Programme is the *envelope* — soft priors that make Mode D *more likely to be recruited* during impingements that suggest "high-risk vinyl playing now." Mode D itself remains a recruited capability, not an imposed mode.

---

## §7 MIDI CC mapping proposal: vinyl-source dimensions → CCs

### §7.1 Design principle: nine vinyl-source dimensions, modelled on the vocal-chain pattern

The existing `agents/hapax_daimonion/vocal_chain.py` (commit `6d1ced049`) maps nine vocal dimensions to Evil Pet + S-4 CCs via piecewise-linear breakpoints with one-CC-per-(device,dimension) collision-avoidance. **The same pattern applies to Mode D** with vinyl-specific dimensions.

The operator's request asked for 6–9 dimensions; **9 is the right number** — it matches the vocal-chain cardinality (operator-fluent), it covers the full granular parameter space without over-collapsing axes, and it leaves room for future expansion without restructuring.

### §7.2 The nine vinyl-source dimensions

| Dim | Description | Aesthetic vocabulary | Defeat-axis weight |
|---|---|---|---|
| `vinyl_source.position_drift` | Where in the buffer the grains are read from. Sweeps Position slowly (LFO-like) or jumps (sample-and-hold). At low values, grains follow vinyl in real-time; at high values, grains drift or jump backward. | "Distance" / "Memory" | medium (changes time-domain order) |
| `vinyl_source.spray` | Position randomisation per grain. Primary defeat axis: scrambles which moments of vinyl source each grain came from. | "Cloud" / "Smear" | **high (primary defeat axis)** |
| `vinyl_source.grain_size` | Length of each grain. Inverted: dim=0 → long grains (~500 ms, source-recognisable); dim=1 → short grains (~10 ms, microsound region). | "Stutter" (high) / "Sustain" (low) | **high (small grains = best defeat)** |
| `vinyl_source.density` | Grains per second. Low = sparse stutter; high = continuous wash. | "Cloud" (high) / "Stutter" (low) | medium |
| `vinyl_source.pitch_displacement` | Per-grain pitch jitter / detune. Even small jitter (±2%) defeats fingerprinting per-grain. | "Refraction" / "Iridescence" | **high (per-grain pitch scrambling)** |
| `vinyl_source.harmonic_richness` | Saturation, bit-crush, drive on the post-granular signal. Adds harmonic content not in source. | "Decay" (slow build) / "Burn" (fast) | low (additive noise, but Smitelli ≥45% threshold) |
| `vinyl_source.spectral_skew` | Filter sweep + Ring resonator pitch. Shifts spectral center. | "Tilt" / "Bloom" | low |
| `vinyl_source.stereo_width` | Spread + delay-spread. Stereo phase scrambling defeats Smitelli's mono-collapsing fingerprint. | "Width" / "Surround" | medium (Smitelli notes phase-inversion always defeats) |
| `vinyl_source.decay_tail` | Reverb amount + decay + size. Long tails place granular wash in deep space. | "Cathedral" / "Memory" | low |

### §7.3 CC mapping (per device, per dimension)

Following the `vocal_chain.py` pattern: one CC per (device, dimension), no within-device collisions. Some dimensions touch only one device.

**Evil Pet (channel 0):**

| Dim | CC# | Param | Range | Curve | Notes |
|---|---|---|---|---|---|
| position_drift | (Position CC, verify) | Position | 0–127 | linear, slow LFO-modulated | center = real-time follow, high = sweep |
| spray | (Spread CC SHIFT+Position, verify) | Position spray | 0–127 | linear | **0 = no defeat, 127 = max defeat** |
| grain_size | (Size CC, verify) | Grain size | 127→0 (inverted) | linear | dim=0 → CC=127 (long); dim=1 → CC=0 (short) |
| density | (Cloud CC SHIFT+Size, verify) | Cloud / density | 0–127 | log | log curve: small dim moves much, large dim plateaus |
| pitch_displacement | 44 (`/Detune` per grain) | Per-grain detune | center 64 ± 30 | linear | symmetric around no-detune |
| harmonic_richness | 39 (Saturator amount) | Saturator | 0–110 | linear | **also used by `vocal_chain.intensity` — Mode D writes only when active** |
| spectral_skew | 70 (Filter freq) | Filter freq | 0–127 | linear | **also used by `vocal_chain.tension` — Mode D writes only when active** |
| stereo_width | (Spread / panning CC, verify) | Pan spread | 0–127 | linear | wide at high values |
| decay_tail | 91 (Reverb amount) + 93 (Reverb tail) | Reverb amount + tail | 0–110 | linear | composite — single dim drives two CCs |

**Torso S-4 (channel 1, Track 1):**

| Dim | CC# | Param | Range | Curve | Notes |
|---|---|---|---|---|---|
| position_drift | (Mosaic Position CC, verify) | Mosaic position | 0–127 | linear | independent from Evil Pet position — second granular stage has its own buffer |
| spray | (Mosaic Spray CC, verify) | Mosaic spray | 0–127 | linear | second-stage spray; multiplies defeat with Evil Pet spray |
| grain_size | (Mosaic Length CC, verify) | Mosaic grain length | 127→0 (inverted) | linear | Mosaic min length is ~5 ms |
| density | (Mosaic Rate CC, verify) | Mosaic rate | 0–127 | log | grains/sec |
| pitch_displacement | 82 (Ring pitch) + Mosaic pitch | Ring pitch + Mosaic per-grain pitch | center 64 ± 24 | linear | composite — single dim drives Ring + Mosaic |
| harmonic_richness | 95 (Deform drive) + 98 (Deform crush) | Drive + Crush | 0–127 | linear (drive), step (crush at dim=0.7+) | composite |
| spectral_skew | 79 (Ring cutoff) + 80 (Ring resonance) | Ring cutoff + reso | 0–127 | linear | composite — sweep + resonance bloom |
| stereo_width | 117 (Delay spread) | Delay spread | 0–127 | linear | ping-pong delay at high width |
| decay_tail | 114 (Reverb amount) + 119 (Reverb decay) + 115 (Reverb size) | Reverb composite | 0–127 | log | composite — single dim drives three CCs |

### §7.4 Starter patch (Mode D default)

Initial dimension levels for first Mode D engagement, per §6.2 staged-engage protocol final state:

```yaml
vinyl_source:
  position_drift: 0.3      # slight drift, mostly real-time
  spray: 0.7               # high spray — primary defeat
  grain_size: 0.8          # short grains (~20 ms) — defeat region
  density: 0.7             # dense wash, not sparse stutter
  pitch_displacement: 0.4  # moderate detune — adds refraction
  harmonic_richness: 0.5   # moderate drive, no bit-crush yet
  spectral_skew: 0.5       # mid-spectrum focus
  stereo_width: 0.6        # wide stereo image
  decay_tail: 0.5          # medium reverb, not cathedral yet
```

For "Stutter" sub-aesthetic: `grain_size: 0.5, density: 0.3, decay_tail: 0.2`
For "Cloud" sub-aesthetic: `grain_size: 0.9, density: 0.95, decay_tail: 0.85`
For "Refraction" sub-aesthetic: `pitch_displacement: 0.85, spectral_skew: 0.8`
For "Distance" sub-aesthetic: `position_drift: 0.7, decay_tail: 0.9, density: 0.6`
For "Decay" sub-aesthetic: `decay_tail: 0.95, density: 0.4, harmonic_richness: 0.7`

### §7.5 Programme YAML — what a Mode D programme looks like

Conforming to `shared/programme.py` (commit `f6cc0b42b`):

```yaml
id: mode_d_granular_wash_default
role: livestream_director
status: active
monetization_opt_ins: [mode_d_granular_wash, vinyl_source_chain]
capability_bias_positive:
  vinyl_source.spray: 0.7
  vinyl_source.grain_size: 0.6   # bias toward short grains
  vinyl_source.density: 0.5
  vinyl_source.pitch_displacement: 0.4
capability_bias_negative:
  vinyl_source.dry_passthrough: 0.9   # heavily bias against dry — Mode D defining
constraint_envelope:
  spray_prior: 0.7
  grain_size_prior: 0.8       # short grains preferred
  density_prior: 0.6
  pitch_displacement_prior: 0.4
  decay_tail_prior: 0.5
narrative_beats:
  - pre_arm                  # parameters loaded, no audible change
  - engage_granular          # ramp Grains 0→110 over 3s
  - suppress_dry             # ramp Mix 50→100 over 5s
  - deepen_space             # optional ramp on Vast
success_criteria:
  content_id_warnings: 0
  staged_transition_completed: true
  duration_min_seconds: 30   # don't drop out of Mode D in <30s
  duration_max_seconds: 600  # cap to avoid 10+ min mono-mode
ritual:
  on_enter: "engage_staged"
  on_exit: "disengage_staged"
```

The `monetization_opt_ins: [mode_d_granular_wash]` is what makes `MonetizationRiskGate` permit Mode D. Without this opt-in, Mode D as a `monetization_risk: medium` capability would be filtered out (per `shared/governance/monetization_safety.py`, commit `0886d37ab`). The opt-in is a **deliberate, programme-scoped governance act** — the operator has consciously chosen to engage Mode D for this session, and the system can audit that choice.

### §7.6 Rate limiting

Per voice-chain doc §5.3: both devices glitch above ~50 Hz CC update rate. Mode D's 9 dims × 2 devices = 18 CC channels; at 20 Hz cap each, that's 360 msg/s — well within DIN MIDI's ~1000 msg/s ceiling. Same debounce as voice-chain.

**Note:** Mode D and voice-chain share some CCs on the Evil Pet (CC 39 saturator amount, CC 70 filter freq, CC 91 reverb amount, CC 93 reverb tail). The runtime must enforce **mutual exclusion** — only one of {`vocal_chain`, `vinyl_source`} writes to a shared CC at any instant. This can be modelled as a Programme-level lock: when `mode_d_granular_wash` is active, the `vocal_chain` capability's bid for shared CCs is gated to 0 weight. The affordance pipeline already handles capability-level mutex via the `priority_floor` + `activation_cost` competition mechanism.

---

## §8 Aesthetic vocabulary + reference listening

### §8.1 The five Mode D sub-aesthetics

The operator should think in **five mode-D sub-aesthetics**, each a region of the 9-dimension space:

| Sub-aesthetic | Description | Lineage | CC region (high values) |
|---|---|---|---|
| **Distance** | Vinyl placed at perceptual distance — recognisable but far. Source identifiable as *"some 70s soul record"* but not *"this specific record."* | Burial's vocal-sample submersion; Boards of Canada's faded memory | position_drift, decay_tail, density (medium) |
| **Decay** | Single moment of vinyl turned into slow exponential settling. The hit hits, then keeps decaying for 8+ seconds. | Vaporwave PaulStretch tradition; OPN's *Replica* | decay_tail (max), density (low), harmonic_richness |
| **Stutter** | Short grains, sparse density. Source becomes a percussive figure, recognisable phrase fragments retrigger. | Madlib micro-chops; Iglooghost retrigger; J Dilla MPC-fluence | grain_size (max — short), density (low), spray (medium) |
| **Cloud** | Density approaches noise-mass. Source becomes texture; no individual grain is audible. | OPN's *Replica*; Tim Hecker's *Ravedeath, 1972*; Curtis Roads' microsound compositions | density (max), grain_size (max — short), decay_tail (high) |
| **Refraction** | Pitch-spray as iridescence. Source becomes a shimmering pitched cloud, like a chord that won't resolve. | Brainfeeder shimmer; Knxwledge's pitched re-pitches; OPN's *R Plus Seven* | pitch_displacement (max), spectral_skew (high), density (medium) |

### §8.2 Reference listening — 20 tracks/albums for Mode D

The operator should listen with the question: *what mode-D sub-aesthetic does this exemplify?* Cross-reference to §8.1:

**Constitutive granular (the source IS the music):**
1. **Curtis Roads — *Eleventh Vortex*** (2001) — the academic foundation, microsound demonstration. Cloud.
2. **Oneohtrix Point Never — *Replica*** (2011) — TV-ad samples granulated into ambient compositions. Distance + Cloud. ([Wikipedia](https://en.wikipedia.org/wiki/Replica_(Oneohtrix_Point_Never_album)))
3. **Tim Hecker — *Ravedeath, 1972*** (2011) — pipe-organ source granulated into massive textures. Cloud.
4. **Daniel Lopatin / OPN — *R Plus Seven*** (2013) — vocal-sample granulation, refraction-heavy. Refraction.

**Vaporwave / hypnogogic:**
5. **Macintosh Plus — *Floral Shoppe*** (2011) — chopped-and-screwed lounge-jazz, the canonical vaporwave artifact. Decay + Distance.
6. **Vektroid — *New Dreams Ltd. — Initiation Tape: Isle of Avalon Edition*** (2011) — slowed/screwed mall-music, vinyl-source-into-cloud. Distance.
7. **Chuck Person's Eccojams Vol. 1*** (2010, OPN's vaporwave proto-thesis) — looped, slowed pop fragments. Stutter + Decay.

**Hip-hop micro-chop:**
8. **Madvillain — *Madvillainy*** (2004) — Madlib's sample stitch-craft, especially "Fancy Clown" (Zeze Hill micro-chop). Stutter. ([Loop Kitchen](https://loopkitchen.co.uk/blogs/loop-kitchen-blog/madlib-madvillainy-sampling-techniques))
9. **Quasimoto — *The Unseen*** (2000) — Madlib's pitched-up vocals + warped jazz loops. Refraction. ([Wikipedia: Quasimoto](https://en.wikipedia.org/wiki/Quasimoto))
10. **Knxwledge — *Hud Dreems*** (2015) — beat tape of micro-chopped soul. Stutter + Distance. ([XLR8R interview](https://xlr8r.com/features/rapper-proof-how-hardworking-la-beatmaker-knxwledge-became-the-most-known-unknown-producer-in-the-game/))
11. **Mndsgn — *Body Wash*** (2016) — Stones Throw, sampled-drum-+-keyboard fusion with chopped fragments. Distance. ([Stones Throw](https://www.stonesthrow.com/news/mndsgn-body-wash/))
12. **Flying Lotus — *Cosmogramma*** (2010) — granular-adjacent texturing of jazz-fusion sources. Cloud + Refraction.
13. **J Dilla — *Donuts*** (2006) — micro-chops, retriggered loops, the foundational MPC-as-granular-instrument album. Stutter.
14. **Dibiase — *PROgressions*** (2010) — boom-bap meets footwork chop density. Stutter.

**Burial / vinyl-as-texture:**
15. **Burial — *Untrue*** (2007) — R&B vocal samples submerged in vinyl crackle and tape dropout. Distance + Decay. ([FACT 2016](https://www.factmag.com/2016/05/15/burial-turns-10-music-movie-video-game-roots/))
16. **Burial — *Subtemple*** (2017) — long-form vinyl-crackle-as-bed compositions. Cloud.

**Plunderphonics / academic:**
17. **John Oswald — *Plunderphonics 69/96*** (2001 reissue of 1985–96 work) — the foundational vinyl-manipulation-as-composition document. Stutter + Distance. ([Plunderphonics 69/96](https://electrocd.com/en/album/4148-plunderphonics-69-96))
18. **Negativland — *Escape from Noise*** (1987) — sample collage meets political/cultural commentary. Distance.

**Hyperpop / forward-looking:**
19. **Iglooghost — *Neō Wax Bloom*** (2017) — hyper-density granular-adjacent micro-events. Cloud + Refraction. ([DJ Mag](https://djmag.com/pointblank/watch-iglooghost-share-secrets-behind-his-production-techniques-point-blank))
20. **SOPHIE — *OIL OF EVERY PEARL'S UN-INSIDES*** (2018) — synth-source granular processing, forward-looking. Refraction + Cloud.

**Live sets / streams** specifically showcasing granular processing of vinyl are rarer in published form. Worth searching for: contemporary Boiler Room sets by Iglooghost, Mark Pritchard, or Daniel Avery; live Stones Throw label nights with Madlib in his "Beat Konducta" mode.

### §8.3 The vocabulary the operator should think in

When the operator reaches for Mode D, they should be reaching for *one of the five sub-aesthetics*, not for "the Mode D button":

- **"This needs Distance — the source is too present, push it backward"** → position_drift up, decay_tail up
- **"This needs Decay — let this one moment ring out"** → density down, decay_tail max, grain_size max-short
- **"This needs Stutter — make it percussive, retrigger the hook"** → grain_size short, density low-medium, position_drift via pattern
- **"This needs Cloud — make it texture, no individual events"** → density max, grain_size short, spray max
- **"This needs Refraction — make it shimmer, pitched-iridescent"** → pitch_displacement max, density medium, spectral_skew via Ring resonator

Each sub-aesthetic is a *direction in 9-dim space*, not a discrete preset. The operator can interpolate between them mid-set: from Distance toward Cloud is a continuous gesture (raise density, raise spray); from Stutter toward Refraction is a continuous gesture (raise pitch_displacement, raise density slightly).

### §8.4 Aesthetic vs defeat — when they diverge

The five sub-aesthetics differ in their fingerprint-defeat strength:

- **Strong defeat:** Cloud (high density + short grains + high spray), Refraction (pitch jitter scrambles per-grain peaks)
- **Medium defeat:** Distance (position drift + spray), Stutter (short grains, but low density preserves some peaks)
- **Weak defeat:** Decay (long single-grain tail can preserve source peaks)

**Operative consequence:** Decay is the sub-aesthetic where the operator should be most careful about fingerprint exposure. Mode D in pure Decay configuration may not defeat fingerprinting; the post-encoder ≥6% pitch/time VST stage (parent doc §7) is essential when in Decay. The other four sub-aesthetics carry their own defeat properties.

---

## §9 Open questions — chain-order experiments operator should run

1. **Chain A vs Chain B fingerprint test.** Take a known-Content-ID-flagged vinyl track. Process through Chain A (Evil Pet → S-4) and through Chain B (S-4 → Evil Pet) at identical Mode D settings. Upload both as unlisted YouTube videos. Compare Content-ID outcomes. Hypothesis: Chain A defeats more reliably because S-4's musical pitch quantisation at the end re-introduces some spectral coherence; if confirmed, Chain B becomes the "deep defeat" mode and Chain A becomes the "musical Mode D." If both pass, Chain A is preferred for the second granular stage's musical structure.

2. **Single-stage vs two-stage defeat strength.** Process the same vinyl track through Evil Pet alone (Mode D-Evil-Pet-only) vs the full Mode D chain. Upload both. Hypothesis: two-stage is required for reliable defeat; if single-stage already passes, the second stage is purely aesthetic.

3. **Grain size sweep.** Same vinyl track, processed at grain sizes 5 ms, 15 ms, 30 ms, 100 ms, 300 ms. Upload all five. Hypothesis: ≤30 ms reliably defeats; 30–100 ms intermittently defeats; ≥100 ms requires additional defeat layers (≥6% pitch via post-encoder VST).

4. **Spray sensitivity.** Same vinyl track, Mode D at spray = 20%, 40%, 60%, 80%, 100%. Upload all five. Hypothesis: spray is the second-most-important defeat axis after grain size; ≥40% reliably defeats.

5. **Dry-leak threshold.** Mode D at `Mix` = 100% (full wash), 90% (slight dry leak), 80%, 70%, 60% (Burial-smear). Upload all five. Hypothesis: `Mix` ≥85% defeats; below that, the dry signal contributes enough peaks for the fingerprint to attach. **This experiment determines the lower bound on `Mix` for the Burial-smear aesthetic to be defeat-safe.**

6. **Pitch-displacement contribution.** Mode D at base (no pitch displacement) vs Mode D + pitch_displacement = 0.5, 1.0. Hypothesis: pitch displacement is independent defeat — even at low values it scrambles per-grain peaks and adds margin.

7. **Vocal-chain CC mutex.** While Mode D is engaged, send vocal-chain impingements. Confirm that the runtime mutex (§7.6) prevents shared CCs from being clobbered. Programme-level priority should hold.

8. **Live-stream Content ID vs VOD Content ID.** Run a Mode D test as a live stream and as an unlisted VOD upload of the same audio. Confirm parent doc §3.2 hypothesis (live is slightly less sensitive than VOD due to compute constraints).

9. **PaulStretch comparison.** Process same vinyl through PaulStretch (the canonical vaporwave granular tool) and through Evil Pet at matched parameters. A/B for both fingerprint defeat and aesthetic outcome. Determines whether the hardware is competitive with the gold-standard vaporwave software for this use case.

10. **Mode D + post-encoder VST belt-and-suspenders test.** Mode D alone vs Mode D + ≥6% post-encoder pitch shift. Hypothesis: combined is bullet-proof; Mode D alone is "probable but not guaranteed" defeat. Determines whether the post-encoder VST stage is mandatory or optional in Mode D.

Each experiment is a single A/B with a known reference track. Schedule one per week as part of the parent doc §9.1 quarterly recalibration. Results land in `~/hapax-state/benchmarks/mode-d-fingerprint/` with the same shape as the prompt-compression benchmark output.

---

## §10 Sources

### Primary — manufacturer documentation

- [Endorphin.es — Evil Pet product page](https://www.endorphin.es/modules/p/evil-pet)
- [Endorphin.es Evil Pet user manual (manuals.plus)](https://manuals.plus/m/068472d380f335f9e901241a8c81ed421e1fc3973820446abe12e8e5eaeb4335)
- [Endorphin.es Evil Pet MIDI CCs and NRPNs (midi.guide)](https://midi.guide/d/endorphines/evil-pet/)
- [Torso Electronics — S-4 product page](https://torsoelectronics.com/products/s-4)
- [Torso Electronics — S-4 product page (alt)](https://torsoelectronics.com/pages/s-4)
- [Torso S-4 OS 1.0.4 manual (PDF)](https://downloads.torsoelectronics.com/s-4/manual/The%20S-4%20Manual%201v0v4a.pdf)

### Primary — academic / theoretical foundation

- Curtis Roads, *Microsound* (MIT Press, 2001) — the academic codification of granular synthesis from 1ms grains to multi-second clouds. Cited via [SFU Truax granular synthesis page](https://www.sfu.ca/~truax/gran.html) and [Roads software page](https://www.curtisroads.net/software).
- [Curtis Roads on Granular Synthesis (Unidentified Sound Object)](https://usoproject.blogspot.com/2009/05/curtis-roads-on-granular-synthesis.html)
- John Oswald, *Plunderphonics, or Audio Piracy as a Compositional Prerogative* (1985 essay) — [eContact mirror](https://econtact.ca/16_4/oswald_plunderphonics.html); the foundational text for sample manipulation as compositional act.
- [Wikipedia — Granular synthesis](https://en.wikipedia.org/wiki/Granular_synthesis)
- [Wikipedia — Plunderphonics](https://en.wikipedia.org/wiki/Plunderphonics)
- [Wikipedia — Acoustic fingerprint](https://en.wikipedia.org/wiki/Acoustic_fingerprint)
- [Wikipedia — Vaporwave](https://en.wikipedia.org/wiki/Vaporwave)
- [Wikipedia — Madlib](https://en.wikipedia.org/wiki/Madlib)
- [Wikipedia — Madvillainy](https://en.wikipedia.org/wiki/Madvillainy)
- [Wikipedia — Quasimoto](https://en.wikipedia.org/wiki/Quasimoto)
- [Wikipedia — Replica (OPN album)](https://en.wikipedia.org/wiki/Replica_(Oneohtrix_Point_Never_album))
- [Wikipedia — Burial (musician)](https://en.wikipedia.org/wiki/Burial_(musician))
- [Wikipedia — John Oswald (composer)](https://en.wikipedia.org/wiki/John_Oswald_(composer))

### Primary — empirical (Content ID thresholds)

- [Scott Smitelli, *Fun with YouTube's Audio Content ID System* (2020)](https://www.scottsmitelli.com/articles/youtube-audio-content-id/) — the canonical empirical decomposition; ≥6% pitch / ≥6% time / ≥4–5% resampling thresholds.
- [Wang algorithm — How Shazam Works (Cameron MacLeod)](https://www.cameronmacleod.com/blog/how-does-shazam-work) — spectral-peak-constellation explanation
- [Towards Data Science — The Five-Second Fingerprint](https://towardsdatascience.com/the-five-second-fingerprint-inside-shazams-instant-song-id/) — Shazam algorithm walk-through
- [AudioLabs Erlangen — Audio Identification](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C7/C7S1_AudioIdentification.html) — academic reference for fingerprinting
- [Selim-Sheta Audio-Identifier (GitHub)](https://github.com/Selim-Sheta/Audio-Identifier) — open-source reimplementation of Shazam constellation-map technique

### Practitioner — Evil Pet reviews and demonstrations

- [Perfect Circuit — Feed After Midnight: Endorphin.es Evil Pet Overview](https://www.perfectcircuit.com/signal/endorphines-evil-pet-review)
- [Perfect Circuit — Endorphin.es Evil Pet product listing](https://www.perfectcircuit.com/endorphines-evil-pet.html)
- [Synth Anatomy — Endorphin.es EVIL PET MPE polyphonic granular synth](https://synthanatomy.com/2025/10/endorphin-es-evil-pet-an-mpe-polyphonic-granular-synthesizer.html)
- [YouTube — Review: EVIL PET by Endorphin.es // Live granular techniques explored](https://www.youtube.com/watch?v=tXQzW5pEhNY)
- [Blip — Endorphin.es Evil Pet 8-Voice Polyphonic Granular Workstation](https://weareblip.com/products/endorphin-es-evil-pet)
- [Gearnews — Endorphin.es Evil Pet Goes Against the Grain](https://www.gearnews.com/endorphin-es-evil-pet-synth/)
- [Schneidersladen — Evil Pet listing](https://schneidersladen.de/en/endorphin.es-evil-pet)
- [ModWiggler — Endorphines Evil Pet thread](https://www.modwiggler.com/forum/viewtopic.php?t=296887)
- [KMR Audio — Evil Pet listing](https://kmraudio.com/products/endorphin-es-evil-pet)
- [Gearspace — Endorphin.es Evil Pet thread](https://gearspace.com/board/electronic-music-instruments-and-electronic-music-production/1457103-endorphin-es-evil-pet.html)

### Practitioner — Torso S-4 reviews

- [Sound on Sound — Torso Electronics S-4 review](https://www.soundonsound.com/reviews/torso-electronics-s-4)
- [MusicTech — Torso Electronics S-4 review](https://musictech.com/reviews/hardware-instruments/torso-electronics-s-4-review/)
- [MusicRadar — Torso Electronics S-4 review](https://www.musicradar.com/music-tech/samplers/torso-electronics-s-4-review)
- [Perfect Circuit — Torso S4 Sculpting Sampler](https://www.perfectcircuit.com/torso-s-4.html)
- [MORDIO — The Torso S4 2.0 Update](https://mordiomusic.com/blog/the-torso-s4-20-update-finally-this-little-box-is-complete)
- [Gearspace — Torso S4 Sampler thread](https://gearspace.com/board/electronic-music-instruments-and-electronic-music-production/1417498-torso-s4-sampler.html)

### Practitioner — hip-hop production technique

- [Loop Kitchen — How Madlib Made Madvillainy: Sampling Lessons for Producers](https://loopkitchen.co.uk/blogs/loop-kitchen-blog/madlib-madvillainy-sampling-techniques)
- [Micro-Chop / Gino Sorcinelli — *I Don't Remember the Samples I Use. Hell No.*](https://medium.com/micro-chop/i-dont-remember-the-samples-i-use-hell-no-the-story-of-madvillainy-e6b378d4689c)
- [Micro-Chop — Micro-Chopping Madlib](https://medium.com/micro-chop/micro-chopping-madlib-5d77b91a5ea5)
- [Mike D'Errico — Boom Bap ex Machina: Hip-Hop Aesthetics and the Akai MPC (PhD thesis)](https://www.cs.tufts.edu/~jacob/250hcm/MikeDErricoMAthesis.pdf)
- [WavHeaven — How to Sample like Madlib](https://wavheaven.com/how-to-sample-like-madlib/)
- [Happy Mag — Engineering the Sound: Madvillain's Madvillainy](https://happymag.tv/engineering-the-sound-madvillains-madvillainy/)
- [The FADER — Beat Construction: Knxwledge](https://www.thefader.com/2015/05/19/beat-construction-knxwledge)
- [XLR8R — Rapper Proof: Knxwledge profile](https://xlr8r.com/features/rapper-proof-how-hardworking-la-beatmaker-knxwledge-became-the-most-known-unknown-producer-in-the-game/)
- [Stones Throw — Mndsgn / Body Wash](https://www.stonesthrow.com/news/mndsgn-body-wash/)
- [Micro-Chop substack — Psychedelic Suds and Transformative Love (Mndsgn)](https://microchop.substack.com/p/psychedelic-suds-and-transformative)
- [Micro-Chop — *I Do it as a Test*: Boom-Bap, Footwork, and the Making of Dibia\$e's PROgressions](https://medium.com/micro-chop/i-do-it-as-a-test-boom-bap-footwork-and-the-making-of-dibia-es-progressions-7f55f6fe254b)

### Practitioner — granular and hyperpop

- [Point Blank — Track Breakdown: Iglooghost Production Techniques](https://www.pointblankmusicschool.com/blog/track-breakdown-iglooghost-shares-the-secrets-behind-his-production-techniques/)
- [DJ Mag — Iglooghost Shares Secrets Behind His Production](https://djmag.com/pointblank/watch-iglooghost-share-secrets-behind-his-production-techniques-point-blank)
- [Splice — Iglooghost Sample Pack](https://splice.com/sounds/packs/splice/iglooghost-sample-pack)
- [LANDR — Granular Synthesis: The 6 Best Plugins For Futuristic Sound](https://blog.landr.com/granular-synthesis/)
- [Native Instruments Blog — Granular synthesis: a beginner's guide](https://blog.native-instruments.com/granular-synthesis/)
- [Output — Granular Synthesis: How It Works and When to Use It](https://output.com/blog/granular-synthesis)

### Practitioner — Burial / vinyl-as-texture

- [FACT Mag — Burial 10 years on: The roots of a dubstep masterpiece](https://www.factmag.com/2016/05/15/burial-turns-10-music-movie-video-game-roots/)
- [Igloo Mag — Burial: Truant (Hyperdub)](https://igloomag.com/reviews/burial-truant-hyperdub)
- [Hyperdub — Burial artist page](https://hyperdub.net/en-us/collections/burial)
- [Liveschool — Sound Design: Enriching digital sounds with noise, textures and vinyl crackle](https://blog.liveschool.net/making-digital-sound-analog-layering-noise-textures-vinyl-crackle/)

### Practitioner — vaporwave / hypnogogic / OPN

- [Plugg Supply — Vaporwave History, Sound & Production Guide 2026](https://www.plugg-supply.net/forum/news/vaporwave-history-sound-production-guide-2026-the-complete-breakdown)
- [Aesthetics Wiki — Vaporwave](https://aesthetics.fandom.com/wiki/Vaporwave)
- [Aesthetics Wiki — Seapunk](https://aesthetics.fandom.com/wiki/Seapunk)
- [Vaporwave Wiki — Subgenres](https://vaporwave.fandom.com/wiki/Subgenres)
- [Melodigging — Seapunk](https://www.melodigging.com/genre/seapunk)
- [OPN bandcamp — Replica](https://oneohtrixpointnever.bandcamp.com/album/replica)
- [Discogs — Replica master release](https://www.discogs.com/master/383751-Oneohtrix-Point-Never-Replica)
- [Sunbleach — Oneohtrix Point Never Replica](https://sunbleach.net/2017/04/16/oneohtrix-point-never-replica/)

### Practitioner — plunderphonics

- [eContact 16.4 — Plunderphonics, or Audio Piracy as a Compositional Prerogative (Oswald 1985)](https://econtact.ca/16_4/oswald_plunderphonics.html)
- [Springer — Sampling and Society: Intellectual Infringement and Digital Folk Music in John Oswald's Plunderphonics](https://link.springer.com/chapter/10.1007/978-1-349-62374-7_7)
- [De Seipel — A Deep Dive into Plunderphonics, Signalwave, and Broken Transmission](https://www.deseipel.com/2025/05/a-deep-dive-into-plunderphonics.html)
- [Electric Eclectics Festival — John Oswald and the Irreverent Art of Plunderphonics](https://electric-eclectics.com/john-oswald-and-the-irreverent-art-of-plunderphonics/)
- [electrocd — Plunderphonics 69/96](https://electrocd.com/en/album/4148-plunderphonics-69-96)
- [Bryan Sutherland — Plunderphonics, or; Shit, They Can Make Music Out of Anything](https://bryanjcsutherland.com/plunderphonics-or-shit-they-can-make-music-out-of-anything/)

### Practitioner — DJ-on-YouTube / Content ID workflow (parent-doc context)

- [Digital DJ Tips — 3 Vital Steps for DJing on YouTube Without Copyright Hassle](https://www.digitaldjtips.com/3-vital-steps-for-djing-on-youtube-without-copyright-hassle/)
- [DJ TechTools — Cutman's Ultimate DJ Streaming Guide](https://djtechtools.com/amp/2018/04/30/cutmans-ultimate-dj-streaming-guide/)
- [Spectral DJ — granular + spectral DJ software](https://www.spectraldj.com/p/spectral-dj.html)
- [DJ TechTools — Vinyl Synthesis with Ableton Live 11](https://djtechtools.com/2021/04/20/vinyl-synthesis-play-sequence-records-as-synths-with-ableton-live-11/)
- [Wikipedia — Turntablism](https://en.wikipedia.org/wiki/Turntablism)
