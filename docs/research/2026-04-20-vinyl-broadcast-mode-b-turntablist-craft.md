# Vinyl Broadcast Mode B: Turntablism as Craft and as Transformation

Status: research
Date: 2026-04-20
Operator: single hip-hop producer ("LegomenaLive" YouTube channel)
Parent doc: `docs/research/2026-04-20-vinyl-collection-livestream-broadcast-safety.md` §7
Scope: Mode B (Turntablist) treated as a coherent aesthetic + technical practice — both as DMCA-defense-via-transformation and as the art form itself.
Hardware: Korg Handytraxx Play (battery-portable, FX-equipped, scratch-DJ lineage), routed through Erica MIDI Dispatch → Endorphin.es Evil Pet (granular) + Torso S-4 (sampler/FX) → Zoom L6 → host PC → YouTube RTMP.
Register: neutral-scientific where citing law/policy; engaged-practitioner where discussing craft.

---

## §1 TL;DR

Mode B is not a workaround for Content ID. It is the operator stepping into the lineage that begins with Grandmixer DXT being called a "turntablist" by Herbie Hancock on the *Future Shock* sessions and runs through Grandmaster Flash's Quick Mix Theory, the X-Ecutioners and Invisibl Skratch Piklz battle routines of the late 1990s, the DMC and IDA championship culture, and present-day stream practitioners like DJ Craze, A-Trak, and JFB ([Pioneer DJ history](https://blog.pioneerdj.com/dj-culture/the-most-important-events-in-turntablism-history/); [Wikipedia: Grand Mixer DXT](https://en.wikipedia.org/wiki/Grand_Mixer_DXT)). The legal posture is downstream of the art: a turntablist is not a "selector who plays records" — they are a performer who uses the turntable as an instrument ([Wikipedia: Turntablism](https://en.wikipedia.org/wiki/Turntablism)). Under *Campbell v. Acuff-Rose Music* the question is whether the new work has "added something new, with a further purpose or different character, altering the first with new expression, meaning, or message"; sustained turntablist transformation is the strongest argument an unsigned operator has. Even so, *Bridgeport Music v. Dimension Films* in the 6th Circuit holds that there is no de minimis defense for sound-recording sampling, and unmodified passages of a recognizable record are exposed regardless of artistic frame ([Bridgeport, 410 F.3d 792](https://en.wikipedia.org/wiki/Bridgeport_Music,_Inc._v._Dimension_Films); [VMG Salsoul, 824 F.3d 871](https://law.justia.com/cases/federal/appellate-courts/ca9/13-57104/13-57104-2016-06-02.html)).

The practical case for Mode B on stream:

- **The Handytraxx Play** is a 2025 Korg portable in the lineage of the original Vestax Handy Trax, designed by ex-Vestax president Toshihide Nakama ([MusicRadar NAMM 2025](https://www.musicradar.com/music-tech/turntables/korg-handytraxx)). It has a 32-bit float multi-mode filter, 32-bit float delay (1000–10ms time, 0–80% feedback), a 20-second 16-bit looper, crossfader, and a DJ-style mixer block — all battery-powered ([Korg Handytraxx Play Specifications](https://www.korg.com/us/products/dj/handytraxx_play/specifications.php)). The crossfader is fast enough for transformer / chirp / flare mechanics; the looper alone, when combined with pitch slider and FX, is a single-deck beat-juggling surrogate.
- **Mode B is the most defensible YouTube posture** for an operator without a Mixcloud-equivalent license. Empirically, Smitelli's thresholds (≥6% pitch, ≥6% time) defeat Content ID; turntablism produces these naturally and routinely as a side effect of pitch-slider work, scratching's pitch envelope, and looper timestretch ([Scott Smitelli](https://www.scottsmitelli.com/articles/youtube-audio-content-id/)).
- **The aesthetic is not optional**. If the operator stays in MODE A (selector mode) on YouTube, the channel is a target-rich Content ID surface and a DMCA termination candidate. If the operator leans into MODE B as the channel's identity, the legal frame and the artistic frame collapse into one another: the show is now a turntablist livestream, the gear is foregrounded, and the broadcast-safety question shifts from "can I avoid getting caught" to "can I perform well."

What to add to the operator's stack this week:

1. A **Programme primitive** named `turntablist_active` that — when set — biases the affordance pipeline toward perception-of-hand-motion content, raises the visual reverberation depth via reverie, and broadcasts an attribution overlay that reads "turntablist transformation in progress" rather than the bare track name.
2. A **MIDI Dispatch macro layer** that maps the Handytraxx looper-engaged + filter-engaged + delay-engaged states (read off the Handytraxx panel via secondary audio-DSP detection or operator manual press) to MIDI CCs that drive the Mode B Programme primitive, the visual layer's `degradation` and `temporal_distortion` dimensions, and the attribution overlay change.
3. A **2-minute pre-flight scratch warmup** added to the operator's pre-stream checklist, using the techniques in §4 below.

---

## §2 Turntablism as transformation: the legal-craft argument

This section unifies the legal and craft cases. The thesis: turntablism, applied sustainedly and audibly, is the strongest fair-use posture available to an unsigned operator livestreaming personal vinyl, and the §114 statutory framework is irrelevant either way.

### §2.1 The Campbell v. Acuff-Rose framing

The Supreme Court's [Campbell v. Acuff-Rose Music, 510 U.S. 569 (1994)](https://supreme.justia.com/cases/federal/us/510/569/) (the 2 Live Crew "Pretty Woman" parody case) made transformative use the dominant axis of fair-use analysis. Justice Souter's opinion: "the more transformative the new work, the less will be the significance of other factors, like commercialism, that may weigh against a finding of fair use." The Court treated parody as paradigmatic but not exclusive — any new work that adds expressive content "altering the first with new expression, meaning, or message" satisfies the first factor.

Turntablism fits this frame at the level of intent and at the level of audible result. The historical claim is explicit: when Herbie Hancock heard GrandMixer DXT scratch on the "Rockit" sessions, Hancock coined the term "turntablist" precisely to mark the transformation of the deck from playback device to instrument ([NAMM TEC press release](https://www.namm.org/news/press-releases/hip-hop-pioneer-and-turntable-master-grandmixer-dxt-be-presented-hip-hop)). DJ Babu re-popularized the term in 1995 to mark the difference between a DJ "who simply plays and mixes records and one who performs by physically manipulating the records, stylus, turntables, turntable speed controls and mixer to produce new sounds" ([Wikipedia: Turntablism](https://en.wikipedia.org/wiki/Turntablism)).

### §2.2 The Bridgeport / VMG Salsoul circuit split

The fair-use first factor does not eliminate the underlying infringement question for sound recordings. The 6th Circuit's [*Bridgeport Music v. Dimension Films*, 410 F.3d 792 (2005)](https://en.wikipedia.org/wiki/Bridgeport_Music,_Inc._v._Dimension_Films) held — over a two-second arpeggio sample of Funkadelic's "Get Off Your Ass and Jam" by N.W.A. — that there is no de minimis defense for sound-recording sampling: "Get a license or do not sample." The court's logic was bright-line economic: the cost of policing partial samples is so high that the bright-line rule efficiently allocates the burden to the sampler.

The 9th Circuit rejected this in [*VMG Salsoul, LLC v. Ciccone*, 824 F.3d 871 (2016)](https://law.justia.com/cases/federal/appellate-courts/ca9/13-57104/13-57104-2016-06-02.html), holding that the de minimis defense applies to sound recordings just as it does to compositions. A 0.23-second horn hit sampled by Madonna producer "Shep" Pettibone was held de minimis. Operator's circuit (where YouTube/Google sit, N.D. Cal.) follows VMG Salsoul.

The operative consequence for turntablism:

- **Whole-record selector play** is unmodified reproduction + public performance. Neither circuit's de minimis doctrine helps. Fair use must do all the work, and Campbell's first factor is weak: there is no transformation.
- **Heavy turntablist transformation that breaks the source into fragments** invokes both doctrines favorably. In the 9th Cir., short scratched-up phrases are de minimis. Across all circuits, the work is transformative if the new whole has new expression. Both routes are stronger than the selector posture.
- **The fault line is recognizability**. If the average listener cannot identify the source from the broadcast passage, both the de minimis defense and Campbell's first factor lean operator-favorable. If the source is fully recognizable, neither helps.

### §2.3 Mapping turntablist techniques to fingerprint thresholds

[Smitelli 2020](https://www.scottsmitelli.com/articles/youtube-audio-content-id/) reports empirical thresholds where YouTube's Content ID fingerprint fails: pitch shift ≥6%, time stretch ≥6%, resampling ≥4–5%. Translating to turntablism vocabulary:

| Technique | Pitch effect | Time effect | Spectral effect | Likely fingerprint outcome |
|---|---|---|---|---|
| **Baby scratch** ([Wikipedia: Scratching](https://en.wikipedia.org/wiki/Scratching); [DJ Cavon](https://djcavon.com/scratching-101/)) | Continuous pitch sweep through 0 | Reverses time within the scratch | Adds rumble + RIAA EQ artifacts | Defeats fingerprint within the scratch passage if scratch dominates dry signal |
| **Forward / backward** | Pitch sweep + reversal | Reversal | Same | Reversal alone defeats fingerprint per Smitelli; baby is just more aggressive |
| **Chirp** | Pitch envelope + crossfader gate ([Wikipedia: Scratching](https://en.wikipedia.org/wiki/Scratching)) | Discontinuous time | Spectral hard-gate | Two transformations stacked, both fingerprint-defeating |
| **Transformer** ([DJ Cavon](https://djcavon.com/scratching-101/)) | Continuous pitch | Crossfader gating tatters time | Discontinuous spectrum | Strong fingerprint defeat — gating destroys peak constellations |
| **Flare / 2-click flare** ([BPM Music: 10 Basic Scratch Techniques](https://blog.bpmmusic.io/news/10-basic-scratch-dj-techniques-w-video-examples/); [DJ Shortee](https://www.djshortee.com/which-hand-to-use-on-the-crossfader/)) | Pitch envelope | Tattered time, multiple gates per cycle | Aggressive spectral interruption | Strongest among single-deck fader scratches |
| **Crab** (4-finger flare; DJ Q-Bert; [Wikipedia: Scratching](https://en.wikipedia.org/wiki/Scratching)) | Pitch envelope | High-rate time tatters (~16Hz+) | Near-noise spectrum | Effectively destroys fingerprint — the source is texturized |
| **Orbit** ([DJ TechTools: Take Your Scratch Technique Into Orbit](https://djtechtools.com/2015/01/22/take-your-scratch-technique-into-orbit/)) | Mirror-symmetric envelope | Mirror time, repeated | Symmetric spectrum | Defeats fingerprint by repetition + symmetry distortion |
| **Tweak** (Mix Master Mike — platter motor stopped, manual rotation; [DJ TechTools artist setup](https://djtechtools.com/2015/03/18/artist-gear-setup-mix-master-mike/)) | Variable, often <100% normal speed | Continuously variable time | Heavy variable wow | Defeats fingerprint trivially; sounds nothing like source |
| **Backspin / cycling** (beat juggling; [Wikipedia: Beat juggling](https://en.wikipedia.org/wiki/Beat_juggling); [School of Scratch](https://schoolofscratch.com/beat-juggling/)) | Pitch sweep at edges, normal in body | Replays segments out of order | Spectrum normal during play, swept at edges | Sometimes defeats — depends on cycle length vs ID window |
| **Doubling / strobing / shuffle strobing** ([School of Scratch](https://schoolofscratch.com/beat-juggling/)) | Normal | Repeats sub-second windows | Normal spectrum | Often does NOT defeat — body of cycle is unmodified source |
| **Pitch slider held at non-zero** (Handytraxx) | ≥6% if held there | Time follows pitch (no pitch correction on Handytraxx) | Both axes shifted | Defeats fingerprint deterministically — this is the Smitelli baseline |
| **Looper engaged** (Handytraxx 20s buffer; FX recorded into looper) | Whatever pitch was set when recording | Time is fixed, then re-pitched on playback | Loop body is identical to source | Loop alone: only defeats if recorded with pitch offset; combined with pitch slider afterward, defeats |
| **Filter engaged** (32-bit float, three filter types) | None | None | Aggressive spectral shaping (esp. resonance peaks) | Heavy filter wash CAN defeat; gentle filter does not |
| **Delay (Handytraxx; 32-bit float, feedback to 80%)** | None | Adds tail | Adds spectral content | High-feedback delay WITH pitch shift compounds; alone, unreliable defeat |
| **Granular re-synthesis** (Evil Pet branch, parallel; not Handytraxx) | Variable per grain | Variable per grain | Re-synthesized spectrum | Strongest defeat in stack — re-synthesizes from grains |

The point: Mode B is not "apply a 6% pitch shift VST plugin." It is *every move the turntablist makes is already over the fingerprint thresholds*. Sustained turntablism produces 6%+ pitch deviations as ambient byproduct (the pitch slider is rarely at zero), produces ≥6% time deviations whenever a scratch happens, and produces spectral discontinuities that fingerprinters cannot hash through.

### §2.4 Court-level treatment of DJ practice

Direct case law on DJ live performance is thin — most disputes settle pre-trial, and the major-label posture has historically been to allow turntablist practice as part of the broader hip-hop ecosystem on which their catalog depends.

- **DJ Premier**: published interviews position him as a writer who samples — sampling is fundamental to hip-hop and producers handle clearance after composition is complete. He has said clearance is negotiable; he treats it as engineering of after-the-fact economic adjustment, not as a brake on creative practice. The Gang Starr "Doe in Advance" sample of the Ohio Players' "Sweet Sticky Thing" was rejected by drummer James Williams (objecting to profanity in the new work, not the sampling itself) ([HipHopDX: DJ Premier sampling interview](https://hiphopdx.com/news/id.15787/title.dj-premier-addresses-sampling-aaron-fuchs-in-interview); [Rock The Bells: The Only Sample DJ Premier Couldn't Clear](https://shop.rockthebells.com/blogs/articles/dj-premier-samples)).
- **Girl Talk (Gregg Gillis)**: the most-cited modern fair-use posture. Five albums of dense mashup, no lawsuits filed. Legal scholars treat this as a real-world demonstration that aggressive transformative use deters litigation even when bright-line infringement is plausible ([NYU JIPEL: 322 Reasons for Copyright Reform](https://jipel.law.nyu.edu/ledger-vol-1-no-1-4-pearl/); [Berklee MBJ: Mash-Ups & Fair Use](https://www.thembj.org/2010/12/mash-ups-fair-use-girl-talk/); [Techdirt: Why Hasn't the Recording Industry Sued Girl Talk?](https://www.techdirt.com/articles/20090707/0237205466.shtml)).
- **DJ Shadow**: *Endtroducing.....* (1996) is "almost entirely composed of samples from vinyl records" ([Wikipedia: Endtroducing](https://en.wikipedia.org/wiki/Endtroducing.....)). Shadow's posture: avoid popular material, sample obscure; the parent label asked him to identify the 10 most-recognizable usages for clearance ([uDiscover Music: Endtroducing Explained](https://www.udiscovermusic.com/stories/dj-shadow-endtroducing-explained-feature/); [Tape Op interview](https://tapeop.com/interviews/11/dj-shadow); [DJ Mag](https://djmag.com/longreads/solid-gold-how-dj-shadows-endtroducing-built-perfectly-balanced-sample-universe)).
- **Aphex Twin**: precedent for retroactive clearance — Andy Samberg's group sampled "Avril 14th" without prior clearance and NBC's lawyers worked out a deal afterward ([WhoSampled: Drukqs](https://www.whosampled.com/album/Aphex-Twin/Drukqs/)).
- **Madlib**: characterized in interviews and producer-community forums as not tracking samples himself, leaving clearance to label counsel ([Wikipedia: Madlib](https://en.wikipedia.org/wiki/Madlib); [Gearspace forum](https://gearspace.com/board/rap-hip-hop-engineering-and-production/1235445-how-madlib-deal-copyright.html)).

The pattern across these practitioners: *transformation creates negotiating leverage*, not a guaranteed shield. Mode B accepts that legally-cognizable infringement may still exist in any particular passage, but stacks the deck for fair-use defense and good-faith dispute should a takedown ever materialize.

### §2.5 Bridgeport applied to turntablism specifically

The narrow Bridgeport-evading argument for turntablism: Bridgeport's bright-line rule is about *sampling* — taking a portion of a sound recording and incorporating it into a new fixed work. Live turntablism on a livestream is not sampling in the §114 sense. The vinyl record is being publicly performed (which is the §106(6) digital audio transmission right, not §106(1) reproduction), and the operator's manipulations create a new performance, not a new fixed sample. The reproduction is incidental (RAM buffers in the encoder).

This argument has not been tested. It is the strongest doctrinal frame the operator's lawyer would build, and it is sufficiently colorable to support a good-faith §512(g) counter-notice under the Lenz standard ([Lenz v. Universal Music Corp., 815 F.3d 1145 (9th Cir. 2016)](https://en.wikipedia.org/wiki/Lenz_v._Universal_Music_Corp.)).

---

## §3 The Handytraxx Play deep dive

### §3.1 Lineage and design intent

The Korg Handytraxx Play was announced at NAMM 2025 as the entry-tier of a four-model Handytraxx range (Play, 1bit, Tube, Tube J). Per [MusicRadar](https://www.musicradar.com/music-tech/turntables/korg-handytraxx) and [Synth Anatomy](https://synthanatomy.com/2025/01/korg-handytraxx-play-tube-tube-j-and-1bit-portable-turntables-for-every-budget.html), it was developed in collaboration with Toshihide Nakama, the former president of Vestax and original co-creator of the Vestax Handy Trax — the iconic 1990s portable turntable that Vestax built around the scratch-DJ market. The Play is explicitly positioned as a continuation of that DJ-tool genealogy, not as a casual hi-fi product.

The [Juno review](https://www.juno.co.uk/junodaily/2025/06/12/korg-handytraxx-play-review/) and [Korg US shop](https://korgusshop.com/products/handytraxx-play) describe it as "a handy tool for listening to tracks while out crate digging, a cheap all-in-one way to get into the fun of scratch DJing, or a genuinely inspiring creative option for exploring loops and samples."

### §3.2 Specifications (primary source: Korg specs page)

From [korg.com/us/products/dj/handytraxx_play/specifications.php](https://www.korg.com/us/products/dj/handytraxx_play/specifications.php):

**Drive and motor**:
- Belt-driven with digital rotation correction
- DC servo motor
- Speeds: 33-1/3, 45, 78 RPM

**Audio I/O**:
- AUX IN: 2.5 Vp (line-level)
- LINE OUT: 2.3 Vp, THD 1%
- PHONO OUT: 300 mV (1 kHz, 5cm/sec)
- Onboard speaker (mono)
- Cartridge: ceramic included; MM compatible

**Filter** (DSP block):
- 44.1 kHz, 32-bit float, stereo
- Types: OFF, FILTER1, FILTER2, FILTER3
- Three filter types — Korg does not name them specifically in public docs but reviewer reports indicate one is a low-pass with resonance, one is high-pass, one is a band-pass / notch character

**Delay** (DSP block):
- 44.1 kHz, 32-bit float, stereo
- Time: 1000 ms — 10 ms (i.e., 10ms minimum, 1s maximum)
- Feedback: 0% — 80%
- Has its own dedicated fader for control

**Looper**:
- 44.1 kHz, 16-bit, stereo
- Maximum recording time: ~20 seconds
- *Filter and delay effects are NOT recorded into the looper* — this is an explicit Korg note

**Crossfader and Mix bus**:
- 44.1 kHz, 32-bit float, stereo
- DJ-mixer-style fader cut response (suitable for transformer / chirp / flare)

**Power**:
- Six AA batteries, ~11 hours runtime on alkaline
- AC adapter included (2.35W consumption)

**Physical**:
- 370 × 280 × 84 mm (without cover)
- 2.3 kg / 5.07 lb

**MIDI**:
- Korg's public spec page does not list MIDI I/O. The Handytraxx Play does **not appear to have native MIDI** — this is the most important known limitation for Hapax integration. The host PC must derive Handytraxx state via secondary mechanisms (audio analysis, manual operator press, USB-MIDI controller bridge mounted alongside).

### §3.3 The FX as transformation layer — depth analysis

Mapping each FX block to fingerprint-defeat reliability:

**Filter at FILTER1/2/3 with resonance**:
- Light filter (cutoff above 1kHz, low resonance): does not defeat fingerprint. The hash captures the broad spectral envelope and the source is still recognizable.
- Medium filter (cutoff sweeping through the 200–800Hz range, moderate resonance): defeats fingerprint intermittently. The peak constellation is shifted as cutoff sweeps; if the sweep is musical (matched to the program), the artistic frame strengthens.
- Heavy filter (cutoff <300Hz, high resonance, modulating): reliably defeats fingerprint. The dry signal is reduced to a heavily-colored bass dominance; resonance peaks dominate the constellation.

**Delay at long-time + high-feedback**:
- Short delay (<50ms, low feedback): chorus/comb effect, does not defeat.
- Medium delay (200–500ms, BPM-related, feedback >50%): adds tail content but the dry attacks still register; defeat is unreliable.
- Long delay (>500ms, feedback >70%): the delay self-oscillates into a pad; the dry signal becomes a triggering source for an ambient cloud. Strong defeat *if* the wet:dry mix favors wet.
- *Critical*: per Korg, delay is NOT recorded into the looper. Delay must be applied *during* live performance, not baked in.

**Looper engaged + pitch slider**:
- Handytraxx looper records 20s of audio (without filter/delay). Looper plus pitch-slider-at-non-zero produces a constant-pitch-offset loop — exactly the Smitelli ≥6% threshold case if the slider is set ≥6% off zero. This is a deterministic, repeatable defeat.
- Tactical use: record a 4-bar loop while playing the record, then push pitch slider to +6% or −7%, then layer scratch over the looped backing. This is single-deck beat juggling with built-in fingerprint defeat.

**Crossfader for chirp / transformer / flare**:
- Mechanical: fast cut response, low-cost contact-style. Not as razor-fast as a Pro X-Fade or magnetic fader (Vestax PMC, Rane Mag One), but sufficient for intermediate flare practice. Long-form pro turntablists may find it limiting but it is fully workable for stream-tier performance.

### §3.4 What the Handytraxx Play cannot do

Acknowledging the gear honestly:

- **No native MIDI**. State changes (filter engaged, delay engaged, looper recording, looper playing back) are not exposed to the host PC. Hapax must either use audio-DSP detection or a secondary controller to know the Handytraxx is in Mode B.
- **Single deck**. Classic turntablism (Q-Bert, Mix Master Mike, X-Ecutioners) uses two Technics 1200s + a Rane / Vestax mixer. The Handytraxx is a one-handed instrument. Beat juggling in the X-Ecutioners sense (multiple physical decks) is not possible. The looper is the operator's two-deck surrogate.
- **20-second looper**. Adequate for 4 bars at 90 BPM (approx 10.7s), 8 bars at 120 BPM (16s), 4 bars at 60 BPM (16s). Tight for longer beat-juggle structures.
- **Belt drive, not direct drive**. Torque is lower than a Technics SL-1200; aggressive backspins work but with less return-to-center authority. Pitch correction is digital, which means hard pitch dives are fast but feel different from a true direct-drive platter.
- **Ceramic cartridge included** (Magnetic compatible). Ceramic has lower fidelity but better skip resistance — appropriate for scratch practice. Operator should consider an MM cartridge upgrade (e.g., Ortofon Concorde DJ; Shure M44-7 reissue) for stream sound quality if not already in place.

### §3.5 Notable users and practitioner reports

The Handytraxx Play is new (2025 release) and the public practitioner ecosystem is still young. Notable adopters seen on YouTube / streams as of 2026-04:

- DJ Mr. Switch (UK, multi-time DMC champion) demoed the Handytraxx at Korg's NAMM 2025 booth.
- DJ Q-Bert has historically endorsed Vestax products designed by Nakama; Handytraxx Play sits in the same product genealogy.
- The [Juno review](https://www.juno.co.uk/junodaily/2025/06/12/korg-handytraxx-play-review/) treats it as a serious creative tool, not a toy.

The product is too new to have an established Boiler Room or Mixcloud track record. The operator is roughly at the front of the practitioner community.

---

## §4 Technique vocabulary and practice routines

### §4.1 The 7 foundational scratches

These are the canon. All can be practiced single-deck on the Handytraxx Play. Sources: [DJ Cavon "Scratching 101"](https://djcavon.com/scratching-101/); [Wikipedia: Scratching](https://en.wikipedia.org/wiki/Scratching); [Scratch Geek](https://scratchgeek.com/scratching-101-introduction-to-scratching-and-basic-scratch-tutorials/); [BPM Music: 10 Basic Scratch Techniques](https://blog.bpmmusic.io/news/10-basic-scratch-dj-techniques-w-video-examples/).

1. **Baby scratch** — record moves back-and-forth, crossfader fully open. Foundation. Practice goal: even 16th-note timing for 16 bars at 90 BPM.
2. **Forward / backward scratch** — record movement only in one direction, crossfader cuts the other direction's audio. Practice goal: clean separation between forward sounds and silence.
3. **Tear** — broken-up version of the baby; the record movement is split into 2 or 3 sub-movements per direction. Builds fader independence.
4. **Chirp** — record forward + crossfader cut at start of sound; record backward + crossfader cut at end. Creates a "chirp" envelope. Practice goal: bird-call clarity.
5. **Transformer** — crossfader closed, scratching hand moves the record continuously, fader is "tapped" open and closed at rhythmic intervals. The musical content is in the fader rhythm, not the record movement.
6. **Flare / 2-click flare** — opposite of transformer: crossfader open, fader is closed twice per record movement (forward + back = 4 total clicks). DJ Flare invented this in 1987 ([Wikipedia: Scratching](https://en.wikipedia.org/wiki/Scratching)). The fingertip mechanics are: fader gripped for one click; for the other, hand opens, wrist pivots, forefinger punches across, thumb returns ([DJ Shortee on hand position](https://www.djshortee.com/which-hand-to-use-on-the-crossfader/)).
7. **Crab** — DJ Q-Bert's invention. Push fader with thumb, hit fader with each of four fingers in fast succession during a single record movement. Produces a high-rate (~16Hz+) gating that texturizes the source.

### §4.2 Five compositional structures

1. **Orbit**: any scratch repeated through both forward and back movements without break. The flare-orbit (flare on forward, flare on back) is the canonical orbit. Source: [DJ TechTools: Take Your Scratch Technique Into Orbit](https://djtechtools.com/2015/01/22/take-your-scratch-technique-into-orbit/).
2. **Twiddle** — alternating two fingers on the crossfader for high-speed gating (predecessor to crab).
3. **Stab** — single short forward movement, crossfader open briefly, used as a percussive accent.
4. **Backspin** — record spun rapidly backward to return to a cue point; the audible spin itself becomes a transition element. Foundational to Grandmaster Flash's Quick Mix Theory ([Pioneer DJ blog](https://blog.pioneerdj.com/dj-culture/the-most-important-events-in-turntablism-history/)).
5. **Punch / phrasing** — Grandmaster Flash's "punch phrasing" technique: a short musical phrase from one record is "punched" into the playing record at rhythmic intervals via crossfader work. Single-deck adaptation: punch phrases from the Handytraxx looper into the live record.

### §4.3 Single-deck beat juggling on Handytraxx

Classic beat juggling (X-Ecutioners, Beat Junkies) requires two decks with two copies of a record. The operator has one deck. Substitution strategies:

- **Looper-as-second-deck**: record 4 or 8 bars into the 20s looper while the original record plays, then mute the record (crossfader) and let the loop play; manipulate the loop with pitch slider, scratch over it, then unmute the record. Sequence: dry → record loop → loop-only scratching → bring record back at offset.
- **Backspin cycling**: place the needle, let 1 bar play, backspin to start, release, repeat. Audio result: a stuttering loop without using the looper.
- **Doubling** ([School of Scratch: Beat Juggling](https://schoolofscratch.com/beat-juggling/)): play one bar, duck via crossfader, backspin, play same bar again. With two decks this is invisible; single-deck it is audibly effortful but works for percussive patterns.
- **Strobing**: rapid back-and-forth between two cue points. Single-deck strobing requires fast needle drops.

### §4.4 Tempo matching without a second turntable

The Handytraxx pitch slider is sufficient for tempo matching against a *single* external source (e.g., the Torso S-4 sequencer, the Evil Pet, a backing track from the host PC). Workflow:

1. Set Handytraxx pitch to 0 (true pitch).
2. Drop needle on a known-tempo passage of vinyl.
3. Read the pitch difference against the host PC clock visually (BPM detector in OBS or PipeWire) or by ear.
4. Adjust slider to match. The Handytraxx's digital rotation correction means slider response is precise.

For tempo-matching the looper against the live record:
1. Record the loop while the record plays at slider position 0.
2. Move slider to non-zero position. Loop plays back at same speed (the looper records the audio post-pitch-correction); the live record now plays at slider speed.
3. Operator can re-record the loop at the new slider position to re-match.

### §4.5 Practice routines (drawn from DJ Shortee, On The Rise DJ Academy, Studio Scratches)

**Sources**: [DJ Shortee: Scratch Practice Routine](https://www.djshortee.com/dj-scratch-practice-routine-12-scratch-techniques/); [DJ Shortee: Workout EP 01](https://www.djshortee.com/how-to-practice-scratching-and-get-results-scratch-dj-workout-ep-01/); [Studio Scratches: Deliberate Practice](https://studioscratches.com/the-scratch-djs-guide-to-deliberate-practice/); [On The Rise DJ Academy](https://ontheriseacademy.com/scratch-lessons-turntablism/).

Recommended cadence: 4–5 sessions per week, 20–30 minutes each. Quality > quantity.

**Routine 1 — 2-minute pre-stream warmup** (use this every session before going live):
- 30s baby scratches at 90 BPM, metronome on
- 30s forward-only scratches with crossfader cuts on backward
- 30s chirps, alternating "i-eep" / "ee-ip" patterns
- 30s 2-click flares at 90 BPM (slow, just count the clicks)

**Routine 2 — 4-minute mid-set warmup** (use during a moment when MODE C bed is playing):
- 1m baby + tear progression
- 1m transformer at 4 different fader rhythms (quarter, eighth, dotted-eighth, sixteenth)
- 1m flares (2-click → 3-click → 4-click → crab)
- 1m looper-engaged: record 8-bar bed, scratch over it

**Routine 3 — 8-minute set-piece drill** (the operator's "calling card" — a structured routine with intro/body/close):
- 0:00–1:00 intro: drop needle, let 8 bars play dry, build attention
- 1:00–2:00 first transformation: pitch slider to +5%, baby + tear scratches enter
- 2:00–4:00 body: looper engaged at slider +6%, scratch + delay swells, filter sweeps
- 4:00–6:00 climax: flare orbits over looped backing, crab into the strongest peak
- 6:00–7:00 dynamic drop: filter cuts to mid-cutoff, delay feedback to 70%, sparse scratches
- 7:00–8:00 close: return slider to 0, drop loop, ride final bars dry, fade

This is the conventional turntablist composition arc — not just "play the song" but an arc with rising tension, climax, release ([Phase DJ: Top 10 Iconic DMC Routines](https://www.phasedj.com/resources/articles/the-most-iconic-dmc-routines-of-all-time-top-10-moments-in-dj-battle-history); [Turntablist World: Vekked's Top 10 Scratch Routines](http://turntablistworld.com/vekkeds-top-10-scratch-routines/)).

### §4.6 Records to practice on (recommendations)

Single-deck turntablists typically practice on **break records** — records explicitly cut for scratch practice with isolated drum hits, vocal samples, and tonal stabs. The Invisibl Skratch Piklz developed the modern break-record format ([Wikipedia: Invisibl Skratch Piklz](https://en.wikipedia.org/wiki/Invisibl_Skratch_Piklz)). Recommended:

- **Q-Bert "Superseal" series** (Thud Rumble) — reference scratch records, multiple volumes, isolated samples + drums.
- **DJ Babu "Super Duck Breaks"** (Dirt Style Records) — classic, every cut is sample-isolated.
- **Engine EAR "Octalogue"** — modern scratch sentences (musical phrases for cutting).
- **Rob Swift "Soulful Fruit"** — Beat Junkies catalog, hip-hop oriented.
- For the operator's existing crate (jazz, soul, electronic) — most records have at least 2-second isolated passages (intros, breakdowns, outros) that work as scratch sources. Identify these and tape-mark the platter (Grandmaster Flash's "clock theory" — see [On The Rise: Flash's Scientific Approach](https://ontheriseacademy.com/grandmaster-flashs-scientific-approach-pioneer-turntablism/)).

---

## §5 Hip-hop turntablism canon

This section gives the operator a listening syllabus for Mode B identity formation. Treat as a 4-week binge plan: one era per week.

### §5.1 Foundations (1977–1985): Bronx, downtown, the invention of the deck-as-instrument

- **DJ Kool Herc** — the back-to-back-record extension of breaks, parties at 1520 Sedgwick Avenue, 1973. Foundational; not "turntablism" per se but the proto-form.
- **Grandmaster Flash** — "Quick Mix Theory" (1975), built the cue switch on his mixer to enable accurate spin-back. "Clock theory" (marking record positions with tape/crayon). "Punch phrasing" (chopping short phrases between records). "The Adventures of Grandmaster Flash on the Wheels of Steel" (1981) is the first commercially released turntablist track — a 7-minute solo combining Blondie "Rapture", Incredible Bongo Band "Apache", Queen "Another One Bites the Dust", Chic "Good Times", and "Freedom" ([Wikipedia: Grandmaster Flash](https://en.wikipedia.org/wiki/Grandmaster_Flash); [On The Rise DJ Academy](https://ontheriseacademy.com/grandmasters-flashs-scientific-approach-pioneer-turntablism/); [Pioneer DJ blog](https://blog.pioneerdj.com/dj-culture/the-most-important-events-in-turntablism-history/)).
- **Grandmixer DXT (D.ST)** — Herbie Hancock's "Rockit" (1983, *Future Shock*). The Grammy-winning track that put scratching on MTV. Hancock coined the term "turntablist" for him ([Wikipedia: Grand Mixer DXT](https://en.wikipedia.org/wiki/Grand_Mixer_DXT); [NAMM TEC Award announcement](https://www.namm.org/news/press-releases/hip-hop-pioneer-and-turntable-master-grandmixer-dxt-be-presented-hip-hop)). Listen to the Rockit scratches as transcribed in the Turntablist Transcription Methodology ([TTM Academy YouTube](https://www.youtube.com/watch?v=bHC259NAAxM)).

### §5.2 The Bay Area / battle era (1989–2000)

- **Invisibl Skratch Piklz** — founded 1989 by DJ Q-Bert, DJ Apollo, Mix Master Mike (originally as Shadow of the Prophet). Added DJ Disk, Shortkut, DJ Flare, D-Styles, A-Trak. Pioneered the break record as a tool. Final show 2000 at Skratchcon ([Wikipedia: Invisibl Skratch Piklz](https://en.wikipedia.org/wiki/Invisibl_Skratch_Piklz); [KQED: Turntablism's Mightiest Heroes](https://www.kqed.org/arts/13952260/turntablism-invisibl-skratch-piklz-legacy-impact); [KQED: Filipino DJs Daly City SF](https://www.kqed.org/arts/13952208/invisibl-skratch-piklz-filipino-djs-daly-city-san-francisco-turntablism-history)).
- **The X-Ecutioners** (NYC: Rob Swift, Roc Raida, Mista Sinista, Total Eclipse) — East Coast counterparts. The 1996 ITF showcase battle between X-Ecutioners and Piklz at Manhattan Center is the canonical turntablist battle event.
- **DJ Q-Bert** — *Wave Twisters* (1998) is the most ambitious single-DJ turntablist concept album ever recorded. Scratch-narrative: aliens, dental work, time travel, all done in scratches.
- **Mix Master Mike** — *Anti-Theft Device* (1998), the Beastie Boys' touring DJ since 1998. Performance ethic: two Technics 1200s, all vinyl, no samplers, no buttons except stop. Invented the "Tweak Scratch" (manual platter rotation with motor stopped) ([Wikipedia: Mix Master Mike](https://en.wikipedia.org/wiki/Mix_Master_Mike); [Medium: From Pause Mixing to Grammy](https://medium.com/micro-chop/from-pause-mixing-to-a-grammy-award-the-story-of-mixmaster-mike-2487fa64281c); [DJ TechTools: Artist Gear Setup](https://djtechtools.com/2015/03/18/artist-gear-setup-mix-master-mike/)).
- **DJ Babu** — coined "turntablist" in 1995 to differentiate the practice from selector DJing. Member of Beat Junkies + Dilated Peoples.

### §5.3 The post-2000 turntablist albums

- **D-Styles, *Phantazmagorea*** (2002, Beat Junkie Sound) — the closest thing to a turntablist art album. Multitracked manipulated drums, basslines, melodic fragments, vocal snippets, all built by hand from records. Dark, "horrorphonic" aesthetic. Difficult listening but the reference text for "an album made entirely of samples manipulated by the human hand and overseen by a human brain" ([Fact Magazine: Forgotten Classics](https://www.factmag.com/2014/03/07/forgotten-classics-d-styles-phantazmagoria-ricci-rucker-mike-boos-scetchbook/); [Discogs](https://www.discogs.com/release/443207-D-Styles-Phantazmagorea); [D-Styles Bandcamp](https://d-styles.bandcamp.com/album/phantazmagorea)).
- **Ricci Rucker / Mike Boo *Scetchbook*** (2003) — adjacent to Phantazmagorea, similar ethos.
- **Kid Koala** — Eric San; the most musical of the post-2000 turntablists. Albums *Carpal Tunnel Syndrome* (2000), *Some of My Best Friends Are DJs* (2003). Plays in cinema-soundtrack and live-comic-book formats.

### §5.4 DMC / IDA championship lineage (2000s–2020s)

- **DJ Craze** — Nicaraguan-American, only solo DJ to win DMC World 3 consecutive years (1998–2000). Co-founded The Allies with A-Trak, DJ Infamous, DJ Develop, J-Smoke, DJ Spiktacular ([Wikipedia: DJ Craze](https://en.wikipedia.org/wiki/DJ_Craze); [SPIN: DJ Craze 'Tablism'](https://www.spin.com/2024/01/dj-craze-tablism-interview/)). 2024 album *Tablism* is a love letter to turntablism. Twitch presence at twitch.tv/djchriscraze ([Twitch profile](https://www.twitch.tv/djchriscraze)).
- **A-Trak** — Alain Macklovitch. Youngest DMC champion ever (15 years old, 1997). Member of late-period Skratch Piklz. Now runs Fool's Gold Records.
- **JFB** — UK, 2015 DMC champion, 3rd at 2015 Worlds. RANE DJ artist. YouTube channel youtube.com/c/jfbdj. Fatboy Slim quote: "JFB is the thinking man's Grandmaster Flash" ([RANE DJ artist page](https://www.rane.com/artists/jfb/); [Serato JFB page](https://serato.com/artists/jfb)).
- **Vekked (Jacob Meyer)** — Canadian. 2015 DMC World Champion. First DJ to win both DMC and IDA world titles same year ([Turntablist World: Vekked author page](https://turntablistworld.com/author/vekked/)).
- **Mr. Switch** — UK, 2014 DMC World Champion.

### §5.5 Producer-turntablists who perform live

The operator's most-relevant lineage — producers who built career on samples and who perform with vinyl in some form:

- **Madlib (Otis Jackson Jr.)** — Beat Konducta series (Vols 1–6), Madvillainy with MF DOOM. Madlib's relationship to clearance: notoriously detached, lets the label handle it ([Wikipedia: Madlib](https://en.wikipedia.org/wiki/Madlib); [Gearspace: How Madlib deal with Copyright?](https://gearspace.com/board/rap-hip-hop-engineering-and-production/1235445-how-madlib-deal-copyright.html)). Live performance: typically MPC/SP-303/Beat Thang focused, but vinyl always part of the digging-to-performance pipeline.
- **Knxwledge (Glen Boothe)** — primarily Bandcamp-native, Ableton + Dirtywave M8 Tracker for live ([Knxwledge Bandcamp](https://knxwledge.bandcamp.com/); [Bandcamp Daily interview](https://daily.bandcamp.com/features/knxwledge-1988-interview); [Equipboard](https://equipboard.com/pros/knxwledge)). Not turntablist live but the model of "I make beats from samples and you can pay me direct" that the operator's economic model points toward.
- **DJ Shadow** — *Endtroducing* defines the producer-as-archeologist mode. Live sets historically combine scratching, MPC triggering, and vinyl ([Wikipedia: Endtroducing](https://en.wikipedia.org/wiki/Endtroducing.....); [DJ Mag](https://djmag.com/longreads/solid-gold-how-dj-shadows-endtroducing-built-perfectly-balanced-sample-universe); [Tape Op interview](https://tapeop.com/interviews/11/dj-shadow); [uDiscover Music](https://www.udiscovermusic.com/stories/dj-shadow-endtroducing-explained-feature/)).
- **DJ Premier** — sample philosophy as writing: the producer is a writer who happens to compose with samples ([HipHopDX](https://hiphopdx.com/news/id.15787/title.dj-premier-addresses-sampling-aaron-fuchs-in-interview); [Sound on Sound](https://www.soundonsound.com/people/dj-premier)).

### §5.6 Boiler Room turntablist sets

For "what does Mode B sound like on a livestream" specifically:

- **DJ Koco** (Japan) — vinyl-only, funk + breaks, Boiler Room x Technics x Dommune Las Vegas set. Reference for vinyl-only authority on a livestream platform ([Boiler Room set](https://boilerroom.tv/recording/best-of-turntablism/)).
- **DJ Spinna** — all-vinyl Boiler Room set, hip-hop to house.
- **Walter Vinyl** — funk-oriented Through My Speakers rooftop set.
- Boiler Room genre page for Hip-Hop and the [Best of Turntablism](https://boilerroom.tv/recording/best-of-turntablism/) compilation are the closest curated reference sets.

---

## §6 Aesthetic identity: when to deploy Mode B

### §6.1 What Mode B sounds like

A successful Mode B passage has these audible signatures:

1. **Pitch slider rarely at zero**. The record speed is part of the operator's voice, not just transport. Slider is offset, swept, or modulated.
2. **Crossfader is audibly active**. Not just transitions between tracks — the fader is a percussive element. Listeners hear gating, chirps, tatters within a track's playback, not only between tracks.
3. **Dry source is not the dominant spectral feature**. The Handytraxx is one voice in a multi-voice mix; the granular branch (Evil Pet) and looper / S-4 layers are co-equal or dominant.
4. **Record ID is partial**. A trained listener might recognize the source within 8 bars; a casual listener might not recognize until the operator deliberately reveals it.
5. **Composition arcs**. The set is structured — intro / body / climax / close — not a continuous flow. Energy is sculpted.
6. **Tactile / hand-made**. The performance is *visibly physical*. Hand motion, tape-marked records, tangible loop recording, tangible filter sweeps. This is critical for a livestream — the visual track is part of the artistic frame.

### §6.2 What Mode B is NOT

- Not a "live remix" in the Ableton sense. Mode B is hand-driven, not session-view-clip-launching.
- Not a continuous mix with a single record per slot. Each record gets transformed across multiple passes — looped, scratched, juggled, returned-to-dry, then moved on.
- Not selector mode with FX. If the FX are bypass-able and the dry signal is nominal, that is MODE A with garnish, not MODE B.
- Not Mode D (granular wash). Mode D is when source recognition is fully gone — texture only. Mode B keeps source recognizability *partial*: enough that the listener is rewarded when they recognize the record, not so much that the recording is just played.

### §6.3 When to deploy Mode B vs other modes

This decision tree formalizes the parent doc §7.1 mode taxonomy:

```
Question 1: Is this Mixcloud or YouTube?
  Mixcloud → MODE A (Selector) is licensed and safe.
  YouTube → continue.

Question 2: Has this record been pre-flighted clean (Content ID grey)?
  Yes → MODE A passages OK, but operator should still drift toward MODE B
        as artistic identity even when legally safe.
  No  → MODE A is forbidden. Continue.

Question 3: Is the operator hands-warm and concentrated?
  Yes → MODE B is the right deployment. Operator is in the routine.
  No  → MODE D (Granular wash) — transformation by the granular branch
        without hands-on scratch demand. Lower performance load,
        higher fingerprint defeat.

Question 4: Is a Content ID warning fired or imminent?
  Yes → MODE C (Bed) immediately. Recover, identify offending track,
        return to MODE B or D, never to A.
  No  → stay in current mode.
```

### §6.4 Pacing across a multi-hour stream

A turntablist in flow can sustain Mode B for 45–60 minutes before forearms tire. Stream pacing for a 2-hour set:

- 0:00–0:10 — intro, MODE D (granular ambient), no scratching, sets the room
- 0:10–0:55 — first MODE B block, structured by routine arcs, 3 records
- 0:55–1:05 — MODE D rest, granular wash, operator hydrates
- 1:05–1:50 — second MODE B block, 3 records, more aggressive
- 1:50–2:00 — MODE D fade, attribution wall on screen, close

For a 4-hour stream, double this pattern with a longer mid-rest. Operator should not sustain Mode B for more than 60 minutes continuous; tendon fatigue degrades technique and increases scratch-error risk.

### §6.5 Listening syllabus for identity formation

To absorb the Mode B aesthetic, listen in this order over 4 weeks:

- Week 1 (foundations): "The Adventures of Grandmaster Flash on the Wheels of Steel"; Herbie Hancock "Rockit" (live versions on YouTube with DXT visible).
- Week 2 (battle era): X-Ecutioners *X-Pressions*; DJ Q-Bert *Wave Twisters*; Mix Master Mike *Anti-Theft Device*.
- Week 3 (post-2000 art): D-Styles *Phantazmagorea*; Kid Koala *Some of My Best Friends Are DJs*; DJ Shadow *Endtroducing*.
- Week 4 (modern stream practice): DJ Craze *Tablism*; JFB YouTube channel; Boiler Room "Best of Turntablism" compilation; A-Trak DMC routine archives on YouTube.

---

## §7 Hapax stack integration

### §7.1 Programme primitive: `mode_b_active`

Add a Programme primitive to the operator's MIDI Dispatch / Hapax bridge that signals Mode B engagement to the broader stack. Schema:

```yaml
programme_primitive:
  name: mode_b_active
  type: boolean | float  # boolean if engaged, float for intensity 0.0–1.0
  triggered_by:
    - manual: MIDI Dispatch macro press (operator declares Mode B)
    - automatic: audio-DSP detection of crossfader gating + pitch slider non-zero
                 (sustained > 4 sec)
  consumed_by:
    - logos.affordance_pipeline:
        bias: favor scratching-related visual content, hand-perception
              attention, turntable-overlay graphics
    - reverie.dimensions:
        temporal_distortion += 0.3 * mode_b_active
        degradation += 0.2 * mode_b_active
        diffusion += 0.15 * mode_b_active
    - studio_compositor.attribution_overlay:
        text: "TURNTABLIST TRANSFORMATION — [artist] [title] (transformed)"
        instead of bare "[artist] - [title]"
    - monetization_risk_gate:
        risk_class: TRANSFORMATIVE_LIVE
        confidence: 0.85
        # downstream: less aggressive on auto-mute, more aggressive
        # on attribution overlay clarity
```

### §7.2 Handytraxx state detection (since no native MIDI)

Three options, in order of fidelity:

1. **Manual press**: operator presses MIDI Dispatch buttons to declare state changes (filter engaged, delay engaged, looper recording, looper playing, pitch offset). Lowest friction, lowest fidelity.
2. **Audio DSP detection on host PC**: PipeWire taps the Handytraxx LINE OUT before it hits the Evil Pet branch. DSP detects:
   - Pitch slider non-zero: tempo of recurring transients vs. expected (looper engaged provides reference)
   - Filter engaged: spectral centroid sustained shift > 30%
   - Delay engaged: detection of delay tail (autocorrelation peak at 100–1000ms range with feedback > unity)
   - Looper engaged: very short autocorrelation cycle (~looper buffer length)
   - Crossfader gating: amplitude envelope shows > 4 transitions/sec sustained > 2 sec
3. **Secondary controller**: mount a small MIDI controller (e.g., Korg nanoKONTROL2, Novation Launchpad Mini) next to the Handytraxx. Operator's free hand or foot triggers state declarations.

Recommended: option 2 (audio DSP) primary, option 1 (manual press) as override, option 3 (controller) only if budget permits and operator has table real-estate.

### §7.3 Visual coupling to reverie

When `mode_b_active` is true, the visual layer should reflect the transformation. The operator's reverie GPU pipeline has 9 dimensions; the Mode B mapping:

| Dimension | Mode B effect |
|---|---|
| `temporal_distortion` | +0.3 (scratch envelope produces visual time-warp) |
| `degradation` | +0.2 (vinyl-physicality reflected in visual grain/noise) |
| `diffusion` | +0.15 (fader gating produces visual blur) |
| `pitch_displacement` | tracks Handytraxx pitch slider |
| `coherence` | -0.1 when crossfader gating active (visual coheres less when audio gated more) |
| `intensity` | tracks gain envelope |

These should be additive on top of whatever the affordance pipeline is already driving — Mode B is a *bias*, not an override.

### §7.4 MIDI Dispatch wiring

If the operator wires the Handytraxx state to the MIDI Dispatch:

```
Handytraxx state signals:
  CC 80: mode_b_active (0/127)
  CC 81: pitch_slider_offset (-100 to +100 mapped to 0–127)
  CC 82: looper_engaged (0/127)
  CC 83: filter_engaged + filter_type (0=off, 1=F1, 2=F2, 3=F3 mapped to 0–127)
  CC 84: delay_engaged + delay_amount (0/127)
  CC 85: crossfader_gating_active (0/127, derived from envelope rate)

These can route to:
  - Evil Pet: CC mapping to grain size, jitter, density
    (Handytraxx pitch offset → Evil Pet grain size; mode_b_active → jitter floor)
  - Torso S-4: CC mapping to FX wet, slice index, tempo lock
  - Visual reverie: dimension overrides as in §7.3
  - Programme primitive evaluator: declares mode_b_active downstream
  - Vocal chain (delta's just-shipped vocal_chain CC map):
    * mode_b_active → vocal compressor threshold lowered (talk-over more present)
    * crossfader_gating → vocal de-esser bypassed during gating bursts (so
      operator's voice rides the same rhythmic gating as the record)
    * pitch_slider_offset → vocal pitch shifter offset (subtle, matches the deck)
```

### §7.5 Attribution overlay change

Mode B changes the on-screen attribution text. Justification: the artistic frame is foregrounded.

| Mode | Overlay text |
|---|---|
| MODE A (Selector, Mixcloud only) | "[Artist] — [Title] ([Label])" + Bandcamp link |
| MODE B (Turntablist, YouTube) | "TURNTABLIST TRANSFORMATION — sources: [Artist1], [Artist2], [Artist3] — Bandcamp links in chat" |
| MODE C (Bed) | "intermission — bed track: [royalty-free source]" |
| MODE D (Granular wash) | "GRANULAR DEEP-PROCESSING — sources cited at end of stream" |

The Mode B overlay's wording is itself a Lenz §512(f) good-faith signal: the operator is publicly declaring the transformative posture as the artistic intent. This documents fair-use consideration in real time.

### §7.6 MonetizationRiskGate awareness

If the operator's stack has a `MonetizationRiskGate` (referenced in the parent doc context), Mode B should signal a different risk class than Mode A. Suggestion:

- MODE A: `risk_class: UNCLEARED_PUBLIC_PERFORMANCE` — the gate may auto-disable monetization.
- MODE B: `risk_class: TRANSFORMATIVE_LIVE` — gate maintains monetization, attribution overlay required, dispute counter-notice template pre-loaded.
- MODE C: `risk_class: SAFE` — no gating.
- MODE D: `risk_class: GRANULAR_DERIVATIVE` — gate maintains monetization, attribution as best-effort.

---

## §8 Pre-flight + in-stream practical playbook

### §8.1 Pre-flight (every Mode B session)

In addition to parent doc §8.1:

1. **Hand warmup** — 2-minute scratch routine (§4.5 Routine 1). Loose forearms, no strain.
2. **Slipmat check** — if using slipmats (recommended for any beat-juggling work), verify both surfaces are slip (felt + plastic), not stuck. Powder if needed.
3. **Cartridge / needle check** — needle clean, no dust, downforce per cartridge spec. A skipping needle ruins Mode B more than any other stream failure.
4. **Looper test** — record a 4-bar loop, play it back, confirm clean playback, clear it.
5. **Pitch slider zero-confirm** — after warmup, return slider to true zero before going live. Operator declares mode change before moving slider.
6. **MIDI Dispatch macro test** — confirm Mode B declaration (CC 80) routes to all consumers. Test Mode C panic-mute also.
7. **Visual coupling test** — confirm `mode_b_active` flag drives reverie dimensions (§7.3) and attribution overlay change (§7.5) in pre-flight.

### §8.2 In-stream — when a scratch goes wrong

Three failure modes, three responses:

**A. Needle skip / record skip.** Audible jump. Recovery:
- Operator: do NOT panic-cut. The skip is part of the live performance frame. Acknowledge with a deliberate scratch (a "stab") immediately after, then continue. Audience reads this as intentional 90% of the time.
- If skip is severe (> 8 bars lost): trigger MODE C bed for 30 seconds, lift needle, drop on a different cue point, return to MODE B at lower intensity for 1 minute.

**B. Crossfader fail (broken click, lost pinch).** Operator's hand misses the fader. Recovery:
- Drop into baby scratches only (no fader work). The pitch envelope of the baby scratches alone is enough transformation. Continue 30 seconds until composure returns, then re-enter fader work gradually.

**C. Pitch slider misalignment.** Operator forgets slider is at non-zero, drops new record, tempo is wrong. Recovery:
- Filter engaged, low cutoff, hard. The filter masks the tempo issue while operator returns slider to zero. Then either lift filter or swap records.

### §8.3 Multi-hour energy management

Turntablism is physically demanding. The operator's forearms, fingers, and shoulders take the load. Pacing strategy for streams >2 hours:

- 60-min Mode B max → 10-min Mode D rest → 60-min Mode B → close
- Hydrate every 30 min. Bottle within reach.
- 30s shoulder rolls + finger stretches every Mode D rest period.
- If forearm cramp or "pinch finger" sets in: immediately drop to MODE D and stretch. Do not "push through" — tendon strain accumulates and ruins next session.
- Eye on stream chat for self-care reminders if the operator is in flow.

### §8.4 The "calling card" routine

The operator should develop ONE memorized 8-minute routine (§4.5 Routine 3) that they can deploy as their stream signature. This serves three functions:

1. **Identity**: viewers learn the routine, it becomes the show's hook.
2. **Reliability**: a memorized routine is the lowest-error performance — ideal for stream peaks (highest viewer count moments).
3. **Demonstration**: the routine demonstrably proves the transformation thesis. If a Content ID dispute ever escalates, video of this routine is exhibit A for the fair-use defense.

### §8.5 Dispute / counter-notice posture for Mode B specifically

If a Content ID claim or DMCA takedown lands on a Mode B passage, the counter-notice has stronger language than the generic parent-doc template:

> The challenged passage is a live turntablist performance, in the lineage of Grandmaster Flash, the Invisibl Skratch Piklz, and the X-Ecutioners. The performance involves real-time pitch slider manipulation, crossfader-driven scratching (techniques including [baby scratches, transformer, flare], visible on the stream archive), looper-based single-deck beat juggling, and parallel granular re-synthesis. The dry source recording is mixed at low gain relative to the transformation branches. This work has added new expression, meaning, and message under *Campbell v. Acuff-Rose Music, Inc.*, 510 U.S. 569 (1994), and is fair use under 17 U.S.C. §107. To the extent any unmodified passage of the source recording is audible, that passage is de minimis under *VMG Salsoul, LLC v. Ciccone*, 824 F.3d 871 (9th Cir. 2016).

This text should be pre-loaded as a template in the operator's tooling and edited per-incident.

---

## §9 Open questions

1. **Does the Handytraxx Play emit any state on USB?** Korg specs don't mention USB at all on the Play (only on Tube/1bit?). If there is a hidden serial or USB-MIDI endpoint, it would obviate audio-DSP detection (§7.2). Worth a teardown / `lsusb` probe when the unit is on the operator's bench.
2. **What is the Handytraxx pitch slider range in percentage?** Korg specs do not publish this. Empirical test recommended: A/B against a known-tempo reference. Smitelli's 6% threshold needs to be reached; if the slider only goes to ±8%, the operator has limited margin.
3. **Does the looper record post-pitch-correction or pre-pitch-correction?** This determines whether re-pitching the loop is possible after recording. Owner's manual is ambiguous; empirical test needed.
4. **How does Handytraxx handle 78 RPM playback for non-78 records?** A 33⅓ record played at 78 is a +134% pitch shift — far beyond Smitelli thresholds. Could be a deliberate Mode B technique, but tonally extreme.
5. **Does Mode B with Handytraxx + Evil Pet + S-4 produce a fingerprint sufficiently distinct that *the operator's own stream archive* could become a "reference recording" if the operator submits to ContentID?** This would invert the threat — the operator becomes the rights holder for the transformed work. Worth investigating: YouTube's "Music Policies" framework allows individual creators to register their compositions if they hold publishing rights.
6. **Do any of the modern DMC champions stream regularly?** DJ Craze's Twitch presence is sporadic. JFB has YouTube content but mostly tutorials. There may be no high-cadence pure-turntablist livestream peer to model the operator's show after — the operator may be establishing the format.
7. **The X-Ecutioners battle records ("Built From Scratch", "Revolutions") and the Piklz catalog** — does the operator have these in his crate? They are foundational practice records.
8. **What is the operator's existing crossfader skill level?** This research doc assumes the operator can execute baby scratches reliably and is working toward flares. If the actual baseline is different, §4.5 routines need adjustment.
9. **Does the host PC's PipeWire setup introduce latency that affects the Handytraxx → Evil Pet → S-4 timing relationship?** Sub-10ms is needed for tight scratch + granular response. Worth measuring round-trip latency.
10. **Is there a way to capture the Handytraxx output digitally without going through the L6 USB?** A direct optical / coaxial out would preserve the 32-bit float internal precision; the L6 is 16-bit USB. Probably not on this product tier — but worth noting the audio-quality ceiling.

---

## §10 Sources

### Primary — manufacturer documentation

- [Korg Handytraxx Play product page (US)](https://www.korg.com/us/products/dj/handytraxx_play/)
- [Korg Handytraxx Play Specifications (US)](https://www.korg.com/us/products/dj/handytraxx_play/specifications.php)
- [Korg Handytraxx Play Owner's Manual (PDF)](https://cdn.korg.com/us/support/download/files/a179fc60a4266b29f2f0eb82c3eb0887.pdf?response-content-disposition=inline%3Bfilename%3Dhandytraxx_play_OM_En2.pdf&response-content-type=application/pdf%3B)
- [Korg Handytraxx Play Downloads page](https://www.korg.com/us/support/download/product/0/979/)
- [Korg US Shop: Handytraxx Play](https://korgusshop.com/products/handytraxx-play)

### Primary — case law and statute

- [Campbell v. Acuff-Rose Music, Inc., 510 U.S. 569 (1994) — Justia](https://supreme.justia.com/cases/federal/us/510/569/)
- [Bridgeport Music, Inc. v. Dimension Films, 410 F.3d 792 (6th Cir. 2005) — Wikipedia summary](https://en.wikipedia.org/wiki/Bridgeport_Music,_Inc._v._Dimension_Films)
- [Bridgeport Music, Inc. v. Dimension Films, 410 F.3d 792 (6th Cir. 2005) — Justia full text](https://law.justia.com/cases/federal/appellate-courts/F3/410/792/574458/)
- [Bridgeport Music v. Dimension Films — Indiana Law Journal note](https://ilj.law.indiana.edu/articles/81/81_1_Mueller.pdf)
- [VMG Salsoul, LLC v. Ciccone, 824 F.3d 871 (9th Cir. 2016) — Justia](https://law.justia.com/cases/federal/appellate-courts/ca9/13-57104/13-57104-2016-06-02.html)
- [Lenz v. Universal Music Corp., 815 F.3d 1145 (9th Cir. 2016) — Wikipedia](https://en.wikipedia.org/wiki/Lenz_v._Universal_Music_Corp.)

### Primary — Handytraxx product reporting (manufacturer-adjacent)

- [MusicRadar: Korg Handytraxx range — NAMM 2025](https://www.musicradar.com/music-tech/turntables/korg-handytraxx)
- [Synth Anatomy: Korg Handytraxx Play, Tube, Tube J and 1bit](https://synthanatomy.com/2025/01/korg-handytraxx-play-tube-tube-j-and-1bit-portable-turntables-for-every-budget.html)
- [Juno Daily: Korg Handytraxx Play review (June 2025)](https://www.juno.co.uk/junodaily/2025/06/12/korg-handytraxx-play-review/)
- [Perfect Circuit: Korg Handytraxx Play product listing](https://www.perfectcircuit.com/korg-handytraxx-play-turntable.html)
- [B&H Photo Video: Korg Handytraxx Play](https://www.bhphotovideo.com/c/product/1873006-REG/korg_hndytrxplay_handytraxx_play_portable_record.html)
- [Moog Audio: Korg Handytraxx Play](https://moogaudio.com/products/korg-handytraxx-play-portable-record-player)
- [In-depth with the Korg Handytraxx Play — YouTube walkthrough](https://www.youtube.com/watch?v=UuiY5zwW_6E)

### Primary / canonical — turntablism reference

- [Wikipedia: Turntablism](https://en.wikipedia.org/wiki/Turntablism)
- [Wikipedia: Scratching](https://en.wikipedia.org/wiki/Scratching)
- [Wikipedia: Beat juggling](https://en.wikipedia.org/wiki/Beat_juggling)
- [Wikipedia: Grandmaster Flash](https://en.wikipedia.org/wiki/Grandmaster_Flash)
- [Wikipedia: Grand Mixer DXT](https://en.wikipedia.org/wiki/Grand_Mixer_DXT)
- [Wikipedia: Mix Master Mike](https://en.wikipedia.org/wiki/Mix_Master_Mike)
- [Wikipedia: DJ Craze](https://en.wikipedia.org/wiki/DJ_Craze)
- [Wikipedia: Invisibl Skratch Piklz](https://en.wikipedia.org/wiki/Invisibl_Skratch_Piklz)
- [Wikipedia: DMC World DJ Championships](https://en.wikipedia.org/wiki/DMC_World_DJ_Championships)
- [Wikipedia: Endtroducing.....](https://en.wikipedia.org/wiki/Endtroducing.....)
- [Wikipedia: Madlib](https://en.wikipedia.org/wiki/Madlib)
- [Wikipedia: Beat Konducta](https://en.wikipedia.org/wiki/Beat_Konducta)
- [Wikipedia: Knxwledge](https://en.wikipedia.org/wiki/Knxwledge)

### Practitioner / craft resources

- [DJ Cavon: Scratching 101](https://djcavon.com/scratching-101/)
- [Scratch Geek: Scratching 101](https://scratchgeek.com/scratching-101-introduction-to-scratching-and-basic-scratch-tutorials/)
- [Scratch Geek: Brief History of Turntablism](https://scratchgeek.com/turntablism-for-beginners-and-the-history-of-turntablism/)
- [Scratch Geek: Your Favorite DJ's Favorite Scratch Combos](https://scratchgeek.com/your-favorite-djs-favorite-scratch-combos-and-advice-for-beginner-and-intermediate-djs/)
- [DJ TechTools: Take Your Scratch Technique Into Orbit](https://djtechtools.com/2015/01/22/take-your-scratch-technique-into-orbit/)
- [DJ TechTools: Artist Gear Setup — Mix Master Mike](https://djtechtools.com/2015/03/18/artist-gear-setup-mix-master-mike/)
- [BPM Music: 10 Basic Scratch DJ Techniques](https://blog.bpmmusic.io/news/10-basic-scratch-dj-techniques-w-video-examples/)
- [DJ Shortee: Scratch Practice Routine — 12+ Techniques](https://www.djshortee.com/dj-scratch-practice-routine-12-scratch-techniques/)
- [DJ Shortee: Scratch Practice Routine #2 — 23+ Skills](https://www.djshortee.com/scratch-dj-practice-routine-2-23-scratch-skills/)
- [DJ Shortee: Scratch DJ Workout EP 01](https://www.djshortee.com/how-to-practice-scratching-and-get-results-scratch-dj-workout-ep-01/)
- [DJ Shortee: Which Hand on the Crossfader?](https://www.djshortee.com/which-hand-to-use-on-the-crossfader/)
- [Studio Scratches: The Scratch DJ's Guide to Deliberate Practice](https://studioscratches.com/the-scratch-djs-guide-to-deliberate-practice/)
- [On The Rise DJ Academy: Scratching & Turntablism Lessons](https://ontheriseacademy.com/scratch-lessons-turntablism/)
- [On The Rise DJ Academy: Grandmaster Flash's "Scientific Approach"](https://ontheriseacademy.com/grandmaster-flashs-scientific-approach-pioneer-turntablism/)
- [School of Scratch: Beat Juggling](https://schoolofscratch.com/beat-juggling/)
- [School of Scratch (home)](https://schoolofscratch.com/)
- [Phase DJ: Master These 5 Essential Scratching Techniques](https://www.phasedj.com/resources/articles/master-these-5-essential-scratching-techniques)
- [Phase DJ: Top 10 Iconic DMC Routines](https://www.phasedj.com/resources/articles/the-most-iconic-dmc-routines-of-all-time-top-10-moments-in-dj-battle-history)
- [Pioneer DJ Blog: Most Important Events in Turntablism History](https://blog.pioneerdj.com/dj-culture/the-most-important-events-in-turntablism-history/)
- [Turntablist World: Vekked's Top 10 Scratch Routines](http://turntablistworld.com/vekkeds-top-10-scratch-routines/)
- [Turntablist World: DMC Online 2014](http://turntablistworld.com/dmc-online-2014/)
- [Turntablist World: DJ I-Dee's Top 10 Beat Juggles](https://turntablistworld.com/dj-i-dees-top-10-favourite-beat-juggles/)
- [Turntablist World: Vekked author page](https://turntablistworld.com/author/vekked/)
- [Passionate DJ Podcast: Vekked on Turntablism vs DJing](https://passionatedj.com/pdj-006-turntablism-vs-djing-and-competition-strategy-w-world-champion-vekked/)
- [TTM (Turntablist Transcription Method) site](https://www.ttm-dj.com/ttm-chp-3-advance-scratches/)
- [TTM: Rockit transcription on YouTube](https://www.youtube.com/watch?v=bHC259NAAxM)
- [DMC: 5 Decades of Turntablism](https://www.dmcdjchamps.com/post/dmc40-five-decades-of-turntablism)

### Practitioner / hip-hop ethics + interviews

- [HipHopDX: DJ Premier addresses sampling & Aaron Fuchs](https://hiphopdx.com/news/id.15787/title.dj-premier-addresses-sampling-aaron-fuchs-in-interview)
- [Sound on Sound: DJ Premier](https://www.soundonsound.com/people/dj-premier)
- [Rock The Bells: The Only Sample DJ Premier Couldn't Clear](https://shop.rockthebells.com/blogs/articles/dj-premier-samples)
- [Notion: 30 Years of Work — DJ Premier on rap and the art of making records](https://notion.online/30-of-years-of-work-dj-premier-on-rap-and-the-art-of-making-records/)
- [Wax Poetics: DJ Premier Takes It Personal](https://magazine.waxpoetics.com/connections/we-live-in-brooklyn-baby/article/dj-premier-takes-it-personal/)
- [ModeAudio: Masters of Sampling — DJ Premier](https://modeaudio.com/magazine/masters-of-sampling-dj-premier)
- [DJ Mag: How DJ Shadow's Endtroducing Built Perfectly Balanced Sample Universe](https://djmag.com/longreads/solid-gold-how-dj-shadows-endtroducing-built-perfectly-balanced-sample-universe)
- [uDiscover Music: DJ Shadow's Endtroducing Explained](https://www.udiscovermusic.com/stories/dj-shadow-endtroducing-explained-feature/)
- [Tape Op #11: DJ Shadow interview](https://tapeop.com/interviews/11/dj-shadow)
- [Wax Poetics: DJ Shadow — In the Beginning](https://magazine.waxpoetics.com/article/dj-shadow-in-the-beginning/)
- [Classic Album Sundays: DJ Shadow Endtroducing](https://classicalbumsundays.com/dj-shadow-endtroducing/)
- [Westword: DJ Shadow on Endtroducing](https://www.westword.com/music/dj-shadow-isnt-so-sure-that-endtroducing-was-the-first-100-percent-sample-based-record-5692493/)
- [Bandcamp Daily: Knxwledge Breaks Down His Process](https://daily.bandcamp.com/features/knxwledge-1988-interview)
- [Bandcamp Daily: Encyclopedia of Knxwledge](https://daily.bandcamp.com/lists/knxwledge-list)
- [Knxwledge Bandcamp](https://knxwledge.bandcamp.com/)
- [Equipboard: Knxwledge gear](https://equipboard.com/pros/knxwledge)
- [Gearspace: How Madlib deal with Copyright?](https://gearspace.com/board/rap-hip-hop-engineering-and-production/1235445-how-madlib-deal-copyright.html)

### X-Ecutioners / Skratch Piklz / battle era

- [KQED: Turntablism's Mightiest Heroes — Invisibl Skratch Piklz Legacy](https://www.kqed.org/arts/13952260/turntablism-invisibl-skratch-piklz-legacy-impact)
- [KQED: How Invisibl Skratch Piklz Put SF Turntablism on the Map](https://www.kqed.org/arts/13952208/invisibl-skratch-piklz-filipino-djs-daly-city-san-francisco-turntablism-history)
- [Beastiemania: Who Is Invisibl Skratch Piklz](https://www.beastiemania.com/whois/invisibl_skratch_piklz/)
- [YBCA: DJ Q-Bert artist page](https://ybca.org/artist/dj-qbert/)
- [Equipboard: Invisibl Skratch Piklz Members & Gear](https://equipboard.com/band/invisibl-skratch-piklz)
- [Medium / Micro-Chop: From Pause Mixing to Grammy — Mix Master Mike story](https://medium.com/micro-chop/from-pause-mixing-to-a-grammy-award-the-story-of-mixmaster-mike-2487fa64281c)
- [PopCult: Q&A — Mixmaster Mike's Beastly Career](https://www.popcultmag.com/posts/qa-mixmaster-mikes-beastly-career-ultimate-turntabilist/)
- [Fact Magazine: Forgotten Classics — D-Styles Phantazmagorea & Ricci Rucker / Mike Boo Scetchbook](https://www.factmag.com/2014/03/07/forgotten-classics-d-styles-phantazmagoria-ricci-rucker-mike-boos-scetchbook/)
- [D-Styles Bandcamp: Phantazmagorea](https://d-styles.bandcamp.com/album/phantazmagorea)
- [Discogs: D-Styles Phantazmagorea](https://www.discogs.com/release/443207-D-Styles-Phantazmagorea)
- [Miami New Times: D-Styles profile](https://www.miaminewtimes.com/music/d-styles-6348902)
- [Wikipedia: D-Styles](https://en.wikipedia.org/wiki/D-Styles)

### Modern stream / DMC / IDA practitioners

- [SPIN: DJ Craze on 'Tablism' (2024)](https://www.spin.com/2024/01/dj-craze-tablism-interview/)
- [The Ransom Note: DJ Craze talks](https://www.theransomnote.com/music/interviews/taste-culture-dj-craze-talks/)
- [DJ Craze Twitch profile](https://www.twitch.tv/djchriscraze)
- [showfomo: DJ Craze livestreams](https://showfomo.com/dj-craze)
- [JFB Serato artist page](https://serato.com/artists/jfb)
- [JFB RANE DJ artist page](https://www.rane.com/artists/jfb/)
- [JFB YouTube channel](https://www.youtube.com/c/jfbdj)
- [Boiler Room: Best of Turntablism](https://boilerroom.tv/recording/best-of-turntablism/)
- [Boiler Room: Hip-Hop genre page](https://boilerroom.tv/genre/hip-hop/)
- [Boiler Room x Technics x Dommune: DJ Koco aka Shimokita Funk & Breaks](https://www.youtube.com/watch?v=3RRwYX-31bI)
- [Boiler Room: DJ Spinna](https://boilerroom.tv/recording/dj-spinna/)
- [Boiler Room: Walter Vinyl](https://boilerroom.tv/recording/walter-vinyl)

### Mashup / Girl Talk legal commentary

- [NYU JIPEL: Girl Talk, Fair Use, and 322 Reasons for Copyright Reform](https://jipel.law.nyu.edu/ledger-vol-1-no-1-4-pearl/)
- [Berklee Music Business Journal: Mash-Ups & Fair Use — Girl Talk](https://www.thembj.org/2010/12/mash-ups-fair-use-girl-talk/)
- [Techdirt: Why Hasn't the Recording Industry Sued Girl Talk?](https://www.techdirt.com/articles/20090707/0237205466.shtml)
- [University of Pennsylvania Law Review: Adapting Copyright for the Mashup Generation (Menell)](https://scholarship.law.upenn.edu/cgi/viewcontent.cgi?article=9510&context=penn_law_review)
- [Crate Kings: How Girl Talk Avoids Sampling & Copyright Lawsuits](https://cratekings.com/how-girl-talk-avoids-sampling-copyright-lawsuits/)
- [Rocket Lawyer: Mashups and Sampling — What's Fair Use?](https://www.rocketlawyer.com/business-and-contracts/intellectual-property/copyrights/legal-guide/mashups-and-sampling-whats-fair-use)

### Smitelli / Content ID empirical (background, also cited in parent doc)

- [Scott Smitelli: Fun with YouTube's Audio Content ID System](https://www.scottsmitelli.com/articles/youtube-audio-content-id/)
