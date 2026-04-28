# Vinyl-Collection Livestream Broadcast Safety: Legal, Platform, and Ethical Boundaries

Status: research
Date: 2026-04-20
Operator: single hip-hop producer ("LegomenaLive" YouTube channel)
Stack: Handytraxx Play turntable (onboard FX) → Erica Synths MIDI Dispatch → Endorphin.es Evil Pet (granular) + Torso S-4 (sampler/FX) → Zoom L6 USB mixer → host PC (PipeWire/JACK + VST chain) → YouTube Live RTMP
Register: neutral, scientific. Distinguishes settled law, industry practice, and platform discretion.

---

## §1 TL;DR

For US copyright law, an unlicensed live broadcast of unmodified commercial sound recordings to YouTube infringes at least two distinct rights — the public-performance / digital-audio-transmission right in the **sound recording** (17 U.S.C. §106(6), §114) and the public-performance right in the underlying **musical composition** (§106(4)). YouTube as a platform has its own blanket licenses with PROs and the MLC for cleared compositions, but those licenses do **not** flow through to a creator's account; the creator is independently exposed. There is no individual statutory or compulsory license that lets a single operator livestream commercial vinyl to YouTube. The §115 mechanical compulsory license does not cover public performance; the §114 statutory webcasting license does not cover interactive services like YouTube; PRO retail licenses cover venues and businesses, not individual creator broadcasts.

What is *risky but commonly done*: playing vinyl through heavy turntablist transformation (chopping, juggling, layering, granular reprocessing, time-stretch ≥ ~6%, pitch-shift ≥ ~6%, and effects-wash) and live-DJing on YouTube. Empirical findings (Smitelli 2020, DJ-community reports) suggest YouTube's Content ID fingerprint is defeated by ~6% pitch or tempo deviation, ~4–5% resampling, full reversal, or out-of-phase / center-extracted manipulations — but Content ID is updated regularly and any threshold reported empirically should be treated as approximate and time-decaying. Even when Content ID is defeated, a human-filed DMCA §512(c) takedown remains possible. YouTube's three-strike system (90-day rolling window) terminates the channel on the third strike (YouTube Help "Understand copyright strikes"), which is the catastrophic risk.

What is *recommended* for this operator: (a) treat YouTube as the wrong venue for unmodified vinyl playback, with **Mixcloud Live** as the legally-cleared mirror for any "selector"-mode programming; (b) on YouTube, restrict vinyl to **transformation-heavy turntablist mode** with the Handytraxx onboard FX, Evil Pet granular, and at minimum two VST stages (pitch/time + reverb/wash) inserted before encoder hand-off; (c) run the Digital DJ Tips "test upload" pre-flight against every set — upload a private/unlisted recording first and check the rights panel; (d) maintain an on-screen now-playing overlay with artist + label + Bandcamp link as ethical floor (the standard for "good faith" attribution); (e) keep a deterministic mid-stream fallback (mute → swap to safe-bed → resume) wired to a single MIDI Dispatch macro. The catastrophic risk is the third strike, not any individual claim — design routing and reaction protocols around protecting the channel, not around defeating any single match.

---

## §2 Legal landscape (US copyright + DMCA)

### §2.1 Two copyrights in every commercial recording

Every commercially-released track carries **two distinct copyrights**, each with separate rights and licensing pipelines:

1. **The musical composition** (PA registration; the song as written) — held by the songwriter / publisher. Public performance is licensed through ASCAP, BMI, SESAC, or GMR. Mechanical reproduction (§115) is licensed via the MLC blanket or directly. ([U.S. Copyright Office, "Music Modernization"](https://www.copyright.gov/music-modernization/115/))
2. **The sound recording** (SR registration; the master recording) — held by the label / artist. Public performance by digital audio transmission is governed by §106(6) and §114. Reproduction is §106(1). There is **no general public-performance right in sound recordings** for terrestrial radio in the U.S., but digital transmissions do carry a performance right. ([17 U.S.C. §106](https://www.law.cornell.edu/uscode/text/17/106), [§114](https://www.law.cornell.edu/uscode/text/17/114))

Livestreaming a vinyl record on YouTube simultaneously implicates both copyrights and at least four §106 rights: reproduction (the encoder makes a copy), preparation of a derivative (the FX chain), public performance of the composition (§106(4)), and public performance of the sound recording by digital transmission (§106(6)).

### §2.2 §115 mechanical compulsory — does not cover livestream public performance

§115 is a compulsory license to make and distribute *phonorecords* (incl. interactive streams as "digital phonorecord deliveries" since the MMA). It is paid via the MLC blanket. It does **not** authorize public performance, which is a distinct §106(4) right. Cover-song uploads on YouTube use §115 plus PRO licensing on YouTube's side; the creator does not personally hold either license. ([17 U.S.C. §115](https://www.law.cornell.edu/uscode/text/17/115); [LII definition: "interactive stream"](https://www.law.cornell.edu/definitions/uscode.php?width=840&height=800&iframe=true&def_id=17-USC-1163380350-1518848558))

### §2.3 §114 statutory webcasting — does not apply to YouTube

The §114 statutory license (administered via SoundExchange) covers **non-interactive** webcasting that "mimics a radio broadcast" — no on-demand selection, no published playlist, limits on tracks-per-artist-per-hour. YouTube is an interactive service; §114 statutory rates do **not** apply. SoundExchange explicitly states it does not collect for YouTube/VEVO. ([SoundExchange FAQ](https://www.soundexchange.com/frequently-asked-questions/); [SoundExchange Licensing 101](https://www.soundexchange.com/service-provider/licensing-101/); [Exploration: Non-Interactive Streaming](https://exploration.io/non-interactive-streaming/))

### §2.4 §110 exemptions — not applicable

§110 exempts certain non-profit educational, religious-service, and small-business reception performances. None covers a single producer livestreaming vinyl to a personal YouTube channel. ([17 U.S.C. §110](https://www.law.cornell.edu/uscode/text/17/110))

### §2.5 Fair use four-factor test (§107) — narrow refuge

[Campbell v. Acuff-Rose Music, 510 U.S. 569 (1994)](https://supreme.justia.com/cases/federal/us/510/569/) established that **transformative use** is the dominant factor; commercial use is not dispositive; "the more transformative the new work, the less will be the significance of other factors." Parody and commentary lie at the heart of fair use. Live DJ performance that consists primarily of selection and beat-matching is not transformative under any settled doctrine; turntablist transformation (cutting, juggling, layering, FX-recontextualization) has a stronger but still untested-at-the-Supreme-Court argument.

### §2.6 Sampling case law — the operative fault line

- [Bridgeport Music, Inc. v. Dimension Films, 410 F.3d 792 (6th Cir. 2005)](https://en.wikipedia.org/wiki/Bridgeport_Music,_Inc._v._Dimension_Films): bright-line "get a license or do not sample" for sound recordings; rejected de minimis defense for sampling within the 6th Circuit.
- [VMG Salsoul, LLC v. Ciccone, 824 F.3d 871 (9th Cir. 2016)](https://law.justia.com/cases/federal/appellate-courts/ca9/13-57104/13-57104-2016-06-02.html): expressly rejected Bridgeport, restored de minimis defense for sound-recording samples in the 9th Circuit. A 0.23-second horn sample was held de minimis.

There is an **active circuit split**. Operator's circuit (likely 9th depending on residence and where defendant would be sued; YouTube/Google is headquartered in N.D. Cal., 9th Cir.) currently affords the de minimis defense for samples. This is irrelevant to a *whole-track* play — de minimis applies only to short fragments where the average listener would not recognize the source.

### §2.7 DMCA §512 takedown / counter-notification

[17 U.S.C. §512](https://www.copyright.gov/512/) provides safe harbor for online service providers (YouTube) that respond expeditiously to takedown notices. The operator's exposure runs through:

- **Notice (§512(c))**: rights holder sends YouTube a sworn notice; YouTube takes down and notifies the user.
- **Counter-notice (§512(g))**: user files a sworn counter-notice including consent to federal jurisdiction and statement under penalty of perjury that removal was a mistake or misidentification. Material is restored in **10–14 business days** unless the rights holder files suit. ([U.S. Copyright Office §512 resources](https://www.copyright.gov/512/); [YouTube counter-notification form](https://support.google.com/youtube/answer/2807684); [sample counter-notice PDF](https://www.copyright.gov/512/sample-counter-notice.pdf))
- **Misrepresentation liability (§512(f))**: knowingly false claims (in a takedown OR counter-notice) create liability. [Lenz v. Universal Music Corp., 815 F.3d 1145 (9th Cir. 2016)](https://en.wikipedia.org/wiki/Lenz_v._Universal_Music_Corp.) holds that a rights holder must consider fair use *in good faith* before sending a §512 notice. The good-faith consideration "need not be searching or intensive" but must occur. This is a sword the operator can swing back against bad-faith takedowns.

### §2.8 DMCA §1201 anti-circumvention

§1201 prohibits circumventing technological protection measures (DRM, encryption) on copyrighted works. Vinyl playback is the **analog hole**: vinyl carries no DRM, the needle reads physical grooves, and the resulting audio is then re-digitized by the L6. This is the only fully legal "decryption" path under §1201; vinyl playback is therefore not implicated by §1201. ([17 U.S.C. §1201](https://www.law.cornell.edu/uscode/text/17/1201); [DMLP: Circumventing Copyright Controls](https://www.dmlp.org/legal-guide/circumventing-copyright-controls); [EFF: DMCA](https://www.eff.org/issues/dmca))

---

## §3 YouTube policy specifics (separate from US copyright law)

### §3.1 Content ID — what it is

Content ID is YouTube's proprietary fingerprint-matching system. Rights holders supply reference files; YouTube scans every upload (and now, every live stream) against the database. ([YouTube Help: How Content ID works](https://support.google.com/youtube/answer/2797370))

Match policies the rights holder can set: **Block**, **Monetize**, **Track**. A single rights holder can apply different policies in different territories. ([YouTube Help: Upload and match policies](https://support.google.com/youtube/answer/107129))

### §3.2 Live-stream Content ID — the critical asymmetry

Per [YouTube Help: "Use Content ID matching on live streams"](https://support.google.com/youtube/answer/9896248): for **live** broadcasts, only **Block** and **Monetize** policies are available — **Track is not supported on live streams**. Settings cannot be modified after the stream is created. "No claims are created" with live matching — instead, enforcement is real-time graduated:

1. Warning to streamer.
2. Stream replaced with "static image with no sound" placeholder.
3. Stream terminated; live-streaming privileges revoked.

([YouTube Help: Copyright issues with live streams](https://support.google.com/youtube/answer/3367684))

If the streamer **archives** the live stream as a VOD, Content ID then runs against the archive at standard claim level, and normal claim/dispute behaviour applies. ("Content ID claims are only made after you complete your live streams, if you decide to archive the video.")

### §3.3 Three-strike system

Per [YouTube Help: Understand copyright strikes](https://support.google.com/youtube/answer/2814000):

- **First strike**: 1-week restriction on uploading, livestreaming, and certain features. Required to complete Copyright School.
- **Second strike**: 2-week upload/livestream restriction.
- **Third strike (within 90 days)**: **channel termination**, all videos removed, user prohibited from creating new channels.
- Strikes expire 90 days after issue (after Copyright School completion).
- Strikes are **distinct from Content ID claims**: a Content ID claim is not a strike. A claim only escalates to a strike if the rights holder files a formal §512 notice or if the user disputes a claim and the rights holder upgrades to a takedown.
- Linked-channel cross-contamination: if a channel linked to the operator's gets 3 strikes, the operator's channel is also subject to termination.

### §3.4 Dispute and appeal mechanics

Per [YouTube Help: Dispute a Content ID claim](https://support.google.com/youtube/answer/2797454): valid dispute reasons include fair use, license, or public domain. The dispute is reviewed by the **claimant** (not YouTube). If the claimant rejects the dispute, the user may appeal once. If the appeal is rejected, the claimant may release the claim, file a Schedule a Delayed Takedown, or issue a §512 takedown — which becomes a strike. Repeated bad-faith disputes can themselves trigger penalties ([YouTube blog: Content ID and Fair Use](https://blog.youtube/news-and-events/content-id-and-fair-use/)).

### §3.5 No "Premium DJ" framework

There is no current "Premium DJ" or DJ-specific licensing framework on YouTube as of 2026-04. Reports of monetization for DJ mixes consistently describe the rights holder taking the revenue via Content ID — i.e., the DJ does not earn from the stream when commercial tracks are matched. ([Quora: Can I monetize my DJ mixes on YouTube?](https://www.quora.com/Can-I-monetize-my-DJ-mixes-on-YouTube); [DJ.Studio: Monetize DJ Mixes](https://dj.studio/blog/monetize-dj-mixes); [DJ TechTools: Cutman's Ultimate DJ Streaming Guide](https://djtechtools.com/amp/2018/04/30/cutmans-ultimate-dj-streaming-guide/))

### §3.6 Allowlisting

Rights holders can **allowlist** specific channels so that future uploads from that channel are not claimed for that catalog ([YouTube Help: Exempt channels from Content ID claims](https://support.google.com/youtube/answer/6070344)). Allowlisting does **not** grant a license — it is a courtesy gate. Past claims still need manual review. For an independent operator without label relationships, allowlisting is unlikely to be obtainable from the major-label catalogs the operator's vinyl crate is most likely to draw from.

---

## §4 Licensing options that exist (and which actually apply)

| Mechanism | Who it's for | Covers YouTube live? | Operator-applicable? |
|---|---|---|---|
| §115 MLC blanket | DSPs (Spotify, Apple, YouTube as platform) | Composition mechanical only | No — platform-level, not creator-level |
| §114 SoundExchange statutory | Non-interactive webcasters (radio-style) | No | No — YouTube is interactive |
| ASCAP/BMI/SESAC/GMR retail | Venues, businesses, broadcasters | YouTube has its own deal; individual creator licenses do not flow through | No — operator cannot license their own broadcast through PROs as an individual |
| Direct master + sync license | Anyone | Yes if obtained per-track | Possible per-track but impractical for an unprogrammed vinyl set |
| Mixcloud Live | DJs streaming audio | Yes — Mixcloud holds platform-wide deals with majors, indies, PROs | **Yes — primary legally-cleared option for selector mode** |
| Twitch Soundtrack | Twitch streamers | Twitch only, audio-isolated from VOD | No (operator is on YouTube) |
| YouTube Audio Library | YouTube creators | Yes for tracks in the library | Useful only for bed/segue music, not for the operator's vinyl |
| Royalty-free libraries (Pretzel, Streambeats, etc.) | Creators | Per-license | Useful for bed/segue music, not vinyl crate |

Sources: [YouTube Help: MLC](https://support.google.com/youtube/answer/10192537); [SoundExchange Service Provider](https://www.soundexchange.com/service-provider/); [Mixcloud Live FAQ](https://help.mixcloud.com/hc/en-us/articles/360013505520-FAQ-Mixcloud-Live); [Mixcloud blog: How to Live Stream Without Copyright Issues](https://www.mixcloud.com/blog/2025/01/01/how-to-live-stream-music-without-copyright-takedown-issues/); [Twitch: Music-Related Copyright Claims](https://blog.twitch.tv/en/2020/11/11/music-related-copyright-claims-and-twitch/); [Twitch Help: Music Options for Streamers](https://help.twitch.tv/s/article/music-options-for-streamers?language=en_US); [YouTube Help: Audio Library](https://support.google.com/youtube/answer/3376882).

**Operative consequence**: if the operator's intent is "play vinyl from my crate to a small live audience," **Mixcloud Live is the legally clean venue, not YouTube.** YouTube is correct only when the practice is heavily transformative (turntablism, granular reprocessing, live remix) — and even then, only with the legal posture that any unmodified passages are subject to claim and the operator accepts the risk-management cost.

---

## §5 Transformation strategies (Content ID defeat — empirical)

This section reports observed Content ID behavior. **Treat all numeric thresholds as time-decaying.** YouTube updates the fingerprint algorithm without notice; a transformation that worked in 2020 may fail in 2026. The only durable defeat is being too short or too transformed for the average listener to recognize the source — which doubles as the fair-use third-factor defense.

### §5.1 Smitelli 2020 empirical thresholds

The most-cited empirical study of Content ID modification thresholds is Scott Smitelli's "Fun with YouTube's Audio Content ID System" ([scottsmitelli.com](https://www.scottsmitelli.com/articles/youtube-audio-content-id/)). Reported thresholds:

| Modification | Fails detection (passes uncaught) at |
|---|---|
| Pitch shift | ≥6% in either direction |
| Time stretch | ≥6% in either direction |
| Resampling (speed) | ≥4% slower, ≥5% faster |
| Reversal | Always passes (not musically useful) |
| Stereo phase inversion | Passes (fingerprinter is mono-collapsing) |
| Center-channel vocal removal | Passes (mono-collapsing) |
| Volume change | Always fails (does nothing) |
| White noise overlay | Passes only at ≥45% noise-to-signal |

This corroborates DJ-community reports that **5% changes are not enough** and **6% is the working floor**. Note: 6% pitch shift = ~1 semitone, which is musically perceptible. 6% tempo change without pitch correction is also perceptible to an attentive listener.

### §5.2 DJ community practice — pre-flight test, not transformation

[Digital DJ Tips: 3 Vital Steps for DJing on YouTube Without Copyright Hassle](https://www.digitaldjtips.com/3-vital-steps-for-djing-on-youtube-without-copyright-hassle/) recommends the **pre-flight test upload** rather than transformation thresholds: upload an unlisted recording of the planned set, observe Content ID flags (grey = safe, yellow = territorial restriction, red = block), drop any red-flagged track from the live set. Reports ~99% live-stream success across "hundreds of livestreams" using this method. The implication: the defeat strategy that works in practice is not transformation, it is **avoidance of high-enforcement catalogs** (most likely majors with worldwide block policies).

### §5.3 Analog-domain processing — does it matter?

The fingerprint is computed from spectral peak constellations (analogous to Shazam's hashing — see [Toptal: How Shazam Works](https://www.toptal.com/algorithms/shazam-it-music-processing-fingerprinting-and-recognition); [Towards Data Science: The Five-Second Fingerprint](https://towardsdatascience.com/the-five-second-fingerprint-inside-shazams-instant-song-id/)). Analog vs digital domain is invisible to the fingerprint — only the resulting spectral content matters. **Vinyl surface noise, wow/flutter, RIAA EQ, and mild Handytraxx FX do not defeat fingerprinting.** The Handytraxx onboard reverb, delay, looper, and FX wash *can* defeat fingerprinting if applied with enough wet/dry ratio that the dry signal is no longer the dominant spectral feature — but mild ambient processing is not enough.

The Evil Pet granular processor *does* materially change the spectral content when set to short-grain (1–100ms) with high disorder/jitter parameters; this is a meaningful defeat vector. Granular synthesis at extreme settings is essentially a re-synthesis from grains and produces a fingerprint distinct from the source. ([Wikipedia: Granular synthesis](https://en.wikipedia.org/wiki/Granular_synthesis))

### §5.4 Where in the chain transformation has to happen

The fingerprint runs on what arrives at the YouTube ingest. Anything that processes the audio before encoding counts. Order of operations matters only insofar as later stages can mask or undo earlier ones. **Transformations that are parallel (granular send, layered subharmonic) defeat fingerprinting more reliably than transformations that are series (reverb on dry).**

### §5.5 What is settled vs what is folk knowledge

- **Settled**: the fingerprint is mono-collapsed peak-constellation matching. Pitch ≥ ~6% and time ≥ ~6% break it (Smitelli).
- **Folk knowledge**: "heavy effects defeat Content ID" — partially true. Single-stage reverb does not. Granular re-synthesis does. Layering with two or more independent sources does (the second source's spectral peaks dominate or mask).
- **Unverifiable without trial**: what new Content ID models trained since 2020 catch. Major fingerprinting overhauls in 2023–2025 are documented in passing in industry sources but no recent equivalent of the Smitelli study has been published.

---

## §6 Ethical practices

The operator's ethical posture is independent of the legal one and should be designed to be defensible to the artist whose work is being played, not just to YouTube's enforcement system.

### §6.1 Real-time attribution ("splattribution")

The term "splattribution" appears to be operator-specific terminology, not an established industry term (no canonical sources found). The substantive practice — real-time on-screen attribution of the now-playing track — is established norm across most copyright-conscious DJ streams. Components observed in the wild:

- Now-playing overlay (artist, title, label) — typically lower-third or corner.
- Bandcamp / direct purchase link in stream chat or video description, refreshed per track.
- Periodic "support the artists you hear today" callouts and link drops.
- Post-stream tracklist published in description and in a chat-pinned message before stream ends.

Sources: [Switcher Studio: What to Know About Livestreaming Copyrighted Music](https://www.switcherstudio.com/blog/what-to-know-about-livestreaming-copyrighted-music); [Incompetech: Twitch and Livestreaming FAQ](https://incompetech.com/music/royalty-free/twitchFAQ.html); [Beatoven.ai: How to Play Music on YouTube Live Stream Without Copyright Issues](https://www.beatoven.ai/blog/how-to-play-music-in-live-stream/).

### §6.2 Direct-to-artist economic pathways

- **Bandcamp** — fan-pays-artist model, ~82% to artist, established as the preferred direct-support venue in the underground hip-hop / beat scene. Knxwledge has built his career on this model. ([DJBooth: Knxwledge Interview](https://djbooth.net/features/2015-04-22-knxwledge-producer-interview/); [Bandcamp About](https://bandcamp.com/about))
- **Patreon / subscriptions** — recurring artist support; appropriate to link in description.
- **Direct sales links** (label store, vinyl reissue distributor) — strongest signal of intent to drive purchase rather than substitute for it.

### §6.3 Hip-hop / beat-scene norms specifically

The producer community Madlib, Knxwledge, Mndsgn occupy is characterized by:

- **Sample-heavy practice without pre-clearance** — Madlib has said he often does not remember which records were sampled and lets the label deal with clearance ([Gearspace: How Madlib deal with Copyright?](https://gearspace.com/board/rap-hip-hop-engineering-and-production/1235445-how-madlib-deal-copyright.html); [Wikipedia: Madlib](https://en.wikipedia.org/wiki/Madlib)).
- **Crate-digger ethic** — selection itself is creative labor; obscure-source curation is itself an act of attribution by elevation.
- **Direct fan economy** — Bandcamp-first releases, sample-heavy uploads tolerated by the platform's permissive cultural posture.
- **Reciprocal respect** — when an artist or estate publicly objects, the work comes down. Sample packs of Madvillainy were taken down at Madlib's request ([IllMuzik thread](https://www.illmuzik.com/threads/madlib-sample-clearence.25419/)).

The operative norm for an operator inside this culture: **play with reverence, attribute audibly and visibly, drive sales to the source artist, and maintain a no-play list of artists who have publicly objected.**

### §6.4 No-play list as a positive practice

Maintain a documented "do-not-broadcast" list of artists, labels, and estates who have publicly stated they object to unlicensed broadcast or sampling. This list is short — most artists are flattered by exposure — but it exists. Maintain it manually; refresh every 6 months. The mere existence of the list (and its public visibility in the channel description) is a strong "good faith" signal in the §512(f) / Lenz sense.

---

## §7 Recommended operational routing for this operator's stack

This is concrete topology, not theory. Names are the operator's actual gear.

```
Vinyl source:
  Handytraxx Play
    └─ onboard FX: filter (light), reverb (mod-depth >40%), delay (BPM-locked, feedback >50%), looper, FX wash
    └─ analog L/R out
       │
       ▼
Erica Synths MIDI Dispatch (control plane only, no audio)
  ├─ CC routing → Endorphin.es Evil Pet (granular)
  └─ CC routing → Torso Electronics S-4 (sampler/FX)

Audio:
  Handytraxx out → Evil Pet input (FX SEND, parallel-mixed back)
  Handytraxx out → Torso S-4 input (FX SEND, parallel-mixed back)
  Mix bus → Zoom L6 channels:
    ch1: Handytraxx dry (low blend, e.g. -8 dB)
    ch2: Evil Pet wet
    ch3: Torso S-4 wet
    ch4: vocal mic / talk-over
    ch5/6: bed-music / safe stems

Zoom L6 USB → host PC (PipeWire)
  ├─ JACK graph → VST chain (rack):
  │    1. Spectral analyzer (monitor only — visual confirmation of source-vs-effect dominance)
  │    2. Pitch / time stretch (e.g. Soundtoys Crystallizer or comparable; ≥6% pitch OR time ≥6%)
  │    3. Reverb (long, plate or convolution; 60–80% wet on transformed branch)
  │    4. Multi-band compressor (glue + level)
  │    5. Brickwall limiter (-1.0 dBTP ceiling)
  └─ Encoder hand-off (OBS → YouTube RTMP)
```

### §7.1 Operating modes

Driven by a single MIDI Dispatch macro layer (operator can flip mode in one press):

- **MODE A — "Selector" (legally risky on YouTube; recommended on Mixcloud)**: Handytraxx dry dominant, Evil Pet bypassed, S-4 bypassed. Use this only for Mixcloud Live, never for YouTube unless the track has been pre-flighted and confirmed Content-ID-clear.
- **MODE B — "Turntablist" (recommended on YouTube)**: Handytraxx dry @ ~30%, Evil Pet @ ~50% (short-grain, jitter ≥40%), S-4 reslice/effect chain @ ~30%. Pitch-time VST ≥6% offset. Reverb 60–80% wet on transformed branch.
- **MODE C — "Bed" (always safe)**: Handytraxx muted, only safe-stems / YouTube Audio Library bed playing. Use during track changes, technical issues, or when a Content ID warning fires.
- **MODE D — "Granular wash" (deepest defeat)**: Handytraxx → Evil Pet only, dry channel muted, grain size ≤30ms, jitter ≥60%. Audible source-recognition is reduced to texture; fingerprint defeat is most reliable.

### §7.2 Why this routing

- The dry signal is *low* in the live mix, never dominant. The granular and effect branches are dominant. This shifts the spectral peak constellation that Content ID hashes.
- Two independent transformation branches (Evil Pet, S-4) running in parallel produce a layered output where the source's peak constellation is masked by transformation peaks.
- The post-encoder VST stage is a deterministic guarantee: even if MIDI Dispatch macros fail, ≥6% pitch/time offset is always applied at the host before encoder hand-off.

### §7.3 Channel description / "About" posture

Standard text recommended for the channel About page, posted as a fixed block:

> LegomenaLive is a turntablist livestream practice. Tracks are sourced from a personal vinyl collection and processed through real-time granular synthesis, sampling, and effects-chain recontextualization. All identifiable source recordings are attributed in the on-stream now-playing overlay and in the post-stream tracklist. We support direct artist purchase via Bandcamp links in chat. We maintain a no-play list of artists who have requested their work not be broadcast — submissions to the no-play list go to [contact]. We respond to good-faith DMCA notices within 24 hours; we counter-notice in good faith on transformations we believe constitute fair use under 17 U.S.C. §107.

This is a strong "good-faith" signal in the Lenz sense — a documented posture that the operator considered fair use, attribution, and artist intent before broadcasting.

---

## §8 Pre-stream checklist + mid-stream fallback playbook

### §8.1 Pre-stream (every session)

1. **Vinyl set list pre-flight**: upload a 5–10 min unlisted "rehearsal" video to YouTube of representative passages (one per planned record). Wait for Content ID processing (~1–10 min). Note grey/yellow/red status per [Digital DJ Tips: 3 Vital Steps](https://www.digitaldjtips.com/3-vital-steps-for-djing-on-youtube-without-copyright-hassle/).
2. **No-play list reconciliation**: cross-reference set list against the channel's no-play list.
3. **Channel-state check**: `youtube studio → channel dashboard`. Confirm 0 active strikes. If 1 or 2 strikes are within the 90-day window, **abort the stream**; the cost of a third strike is total channel loss.
4. **VST chain integrity**: confirm pitch-time stage active and ≥6% offset applied. Confirm spectral analyzer shows transformed branch dominant.
5. **Now-playing overlay test**: confirm overlay plumbing (assumed via OBS browser source or `cairooverlay`) reads from a controllable source the operator can update mid-stream.
6. **MIDI Dispatch macro test**: confirm MODE A → MODE C single-press transition (the "panic mute") works.
7. **Bed-music safe stems loaded**: at least 30 minutes of YouTube Audio Library / Pretzel / Streambeats bed loaded and ready on L6 ch5/6.

### §8.2 During-stream — Content ID warning fires

YouTube's live-stream Content ID flow is:

```
warning → static-image-no-sound replacement → stream termination + live-feature revoke
```

Operator's response on **first warning**:

1. **Immediately trigger MODE C** (panic-mute → safe-bed). This is one MIDI Dispatch press.
2. **Update now-playing overlay** to indicate "intermission / track change" (avoid signaling distress to viewers).
3. **Identify the offending track** from the warning message. Pull the record off the platter.
4. **Add the track to a session-local no-play list** (do not retry it this session).
5. **Resume in MODE B (Turntablist) or MODE D (Granular wash)**, never back to MODE A.

If a **second warning** fires in the same session: end the stream cleanly. Do not push to a third — the static-image replacement triggers viewer dropoff and the next escalation is termination.

### §8.3 Post-stream — VOD handling

If the operator archives the stream as a VOD, full Content ID runs against the archive. To minimize archive-side claims:

- Default to **not archiving** any vinyl-heavy stream.
- If archiving is desired, **pre-edit** in DaVinci Resolve or similar to (a) excise any segment that triggered a live warning, (b) export at the same VST-chain ≥6% pitch/time offset.
- Upload as **unlisted first**, observe Content ID outcomes for 24h, **then** make public if all-grey.

### §8.4 If a strike is issued

1. Read the takedown notice carefully. Confirm it identifies a specific work and a specific timestamp.
2. **Counter-notice only if good-faith fair-use belief is genuine**, per Lenz. The §512(f) penalty for false counter-notice is real.
3. Counter-notice template: U.S. Copyright Office sample at <https://www.copyright.gov/512/sample-counter-notice.pdf>.
4. Material restored in 10–14 business days unless rights holder sues.
5. Complete YouTube Copyright School. Strike expires 90 days after issuance.

---

## §9 Open questions / unknowable without trial

1. **Current Content ID fingerprint sensitivity in 2026**. Smitelli's 6% / 4–5% thresholds are 2020 vintage. YouTube has shipped fingerprint updates since. The only way to know current thresholds is trial — A/B test pitch/time offsets on unlisted uploads. Recommend running this calibration once per quarter.
2. **Whether YouTube's live Content ID and VOD Content ID share the same fingerprint version**. Documentation does not specify. Reports suggest live is slightly less sensitive than VOD (more compute-constrained) but no public benchmark exists.
3. **How aggressively major-label catalogs apply Block-worldwide vs Monetize policies in 2026**. Policies change without notice. The operator's first-stream pre-flight is the only reliable signal.
4. **Whether the operator's specific mix of granular + parallel-effect routing reliably defeats current Content ID**. The Smitelli baseline does not test parallel-bus layered transformations. Operator should run a calibration upload (single-source recorded vinyl through the full MODE B chain) and observe.
5. **Whether allowlisting is obtainable from any rights holder relevant to the operator's crate**. Almost certainly not for major-label catalog, possibly yes for indie labels (Stones Throw, Brainfeeder, Leaving Records) if approached directly. Worth a single email-outreach experiment to indie labels whose catalog is heavily represented.
6. **Mid-stream warning latency**. The interval between the warning and the static-image replacement is not publicly documented. Operator should plan for ~15–30 seconds based on community reports but treat the warning as immediate-action-required.
7. **Whether YouTube logs failed Content ID matches and feeds them into model training**. If yes, the calibration-test approach gradually erodes itself: every successful defeat trains the next-gen model. This is plausible but unconfirmed.
8. **Whether a counter-notice on a turntablist transformation would survive in court**. No reported case directly tests heavy turntablist transformation as fair use. Campbell + VMG Salsoul are favorable; Bridgeport unfavorable. The 9th Circuit posture is the most defensible.

---

## §10 Sources + citations

### Primary sources — statutes and federal regulations

- [17 U.S.C. §106 — Exclusive rights in copyrighted works](https://www.law.cornell.edu/uscode/text/17/106)
- [17 U.S.C. §107 — Fair use](https://www.law.cornell.edu/uscode/text/17/107)
- [17 U.S.C. §110 — Limitations on exclusive rights: certain performances and displays](https://www.law.cornell.edu/uscode/text/17/110)
- [17 U.S.C. §114 — Scope of exclusive rights in sound recordings](https://www.law.cornell.edu/uscode/text/17/114)
- [17 U.S.C. §115 — Mechanical compulsory license](https://www.law.cornell.edu/uscode/text/17/115)
- [17 U.S.C. §512 — Online service provider safe harbor / DMCA notice and takedown](https://www.copyright.gov/512/)
- [17 U.S.C. §1201 — Circumvention of copyright protection systems](https://www.law.cornell.edu/uscode/text/17/1201)
- [LII definition: "interactive stream" (§115(e)(13))](https://www.law.cornell.edu/definitions/uscode.php?width=840&height=800&iframe=true&def_id=17-USC-1163380350-1518848558)
- [U.S. Copyright Office: Music Modernization Act / §115 portal](https://www.copyright.gov/music-modernization/115/)
- [U.S. Copyright Office: Music Modernization FAQ](https://www.copyright.gov/music-modernization/faq.html)
- [U.S. Copyright Office: §1201 Study](https://www.copyright.gov/policy/1201/)
- [U.S. Copyright Office: §512 sample counter-notice (PDF)](https://www.copyright.gov/512/sample-counter-notice.pdf)
- [Digital Performance Right in Sound Recordings Act of 1995 (P.L. 104-39)](https://www.copyright.gov/legislation/pl104-39.html)

### Primary sources — court rulings

- [Campbell v. Acuff-Rose Music, Inc., 510 U.S. 569 (1994) — Justia](https://supreme.justia.com/cases/federal/us/510/569/) ([Cornell LII](https://www.law.cornell.edu/supct/html/92-1292.ZO.html); [Copyright Office summary](https://www.copyright.gov/fair-use/summaries/campbell-acuff-1994.pdf))
- [Bridgeport Music, Inc. v. Dimension Films, 410 F.3d 792 (6th Cir. 2005)](https://en.wikipedia.org/wiki/Bridgeport_Music,_Inc._v._Dimension_Films) (full text via [Berkeley Law mirror](https://www.law.berkeley.edu/files/Bridgeport_Music_v_Dimension_Films.pdf))
- [VMG Salsoul, LLC v. Ciccone, 824 F.3d 871 (9th Cir. 2016) — Justia](https://law.justia.com/cases/federal/appellate-courts/ca9/13-57104/13-57104-2016-06-02.html)
- [Lenz v. Universal Music Corp., 815 F.3d 1145 (9th Cir. 2016) — Justia](https://law.justia.com/cases/federal/appellate-courts/ca9/13-16106/13-16106-2015-09-14.html) ([EFF case page](https://www.eff.org/cases/lenz-v-universal); [Wikipedia summary](https://en.wikipedia.org/wiki/Lenz_v._Universal_Music_Corp.))

### Primary sources — YouTube / Google official policy

- [YouTube Help: How Content ID works](https://support.google.com/youtube/answer/2797370)
- [YouTube Help: Upload and match policies](https://support.google.com/youtube/answer/107129)
- [YouTube Help: Use Content ID matching on live streams](https://support.google.com/youtube/answer/9896248)
- [YouTube Help: Copyright issues with live streams](https://support.google.com/youtube/answer/3367684)
- [YouTube Help: Avoid restrictions on YouTube live streaming](https://support.google.com/youtube/answer/2853834)
- [YouTube Help: Understand copyright strikes](https://support.google.com/youtube/answer/2814000)
- [YouTube Help: Community Guidelines strike basics](https://support.google.com/youtube/answer/2802032)
- [YouTube Help: Submit a copyright counter notification](https://support.google.com/youtube/answer/2807684)
- [YouTube Help: Submit a copyright removal request](https://support.google.com/youtube/answer/2807622)
- [YouTube Help: Dispute a Content ID claim](https://support.google.com/youtube/answer/2797454)
- [YouTube Help: Learn about Content ID claims](https://support.google.com/youtube/answer/6013276)
- [YouTube Help: Restrictions on claimed music](https://support.google.com/youtube/answer/6364458)
- [YouTube Help: Exempt channels from Content ID claims (allowlist)](https://support.google.com/youtube/answer/6070344)
- [YouTube Help: Fair use on YouTube](https://support.google.com/youtube/answer/9783148)
- [YouTube Help: License types on YouTube](https://support.google.com/youtube/answer/2797468)
- [YouTube Help: Use music from the Audio Library](https://support.google.com/youtube/answer/3376882)
- [YouTube Help: What is the Mechanical Licensing Collective (MLC)?](https://support.google.com/youtube/answer/10192537)
- [YouTube Blog: Content ID and Fair Use](https://blog.youtube/news-and-events/content-id-and-fair-use/)
- [YouTube Transparency Report: Community Guidelines enforcement](https://transparencyreport.google.com/youtube-policy?hl=en)

### Primary sources — collecting societies / licensing bodies

- [SoundExchange: Licensing 101](https://www.soundexchange.com/service-provider/licensing-101/)
- [SoundExchange: FAQ](https://www.soundexchange.com/frequently-asked-questions/)
- [SoundExchange: Service Provider portal](https://www.soundexchange.com/service-provider/)
- [SoundExchange: Noncommercial Webcaster](https://www.soundexchange.com/service-provider/non-commercial-webcaster/)
- [Mechanical Licensing Collective (MLC) press release: full operations](https://blog.themlc.com/press-releases-beta/the-mechanical-licensing-collective-begins-full-operations-as-envisioned-by-the-music-modernization-act-of-2018-mechanical-licensing-collective)
- [ASCAP: Music Licensing FAQs](https://www.ascap.com/help/ascap-licensing)
- [Twitch Blog: Music-Related Copyright Claims and Twitch](https://blog.twitch.tv/en/2020/11/11/music-related-copyright-claims-and-twitch/)
- [Twitch Help: Music Options for Streamers](https://help.twitch.tv/s/article/music-options-for-streamers?language=en_US)
- [Mixcloud Help: FAQ — Mixcloud Live](https://help.mixcloud.com/hc/en-us/articles/360013505520-FAQ-Mixcloud-Live)
- [Mixcloud Blog: How to Live Stream Music Without Copyright Takedown Issues](https://www.mixcloud.com/blog/2025/01/01/how-to-live-stream-music-without-copyright-takedown-issues/)
- [Bandcamp: About](https://bandcamp.com/about)
- [Bandcamp Live: about livestreams](https://bandcamp.com/about_livestreams)

### Secondary — empirical / community / practitioner reporting

- [Scott Smitelli, "Fun with YouTube's Audio Content ID System" (empirical thresholds)](https://www.scottsmitelli.com/articles/youtube-audio-content-id/)
- [Digital DJ Tips: 3 Vital Steps for DJing on YouTube Without Copyright Hassle](https://www.digitaldjtips.com/3-vital-steps-for-djing-on-youtube-without-copyright-hassle/)
- [DJ TechTools: Cutman's Ultimate DJ Streaming Guide](https://djtechtools.com/amp/2018/04/30/cutmans-ultimate-dj-streaming-guide/)
- [DJ TechTools: The Basics of DJ Copyright Laws](https://djtechtools.com/2017/06/05/basics-dj-copyright-laws/)
- [DJ.Studio: The DJ's Guide to Music Licensing and Copyright](https://dj.studio/blog/dj-licence)
- [DJ.Studio: Monetize DJ Mixes](https://dj.studio/blog/monetize-dj-mixes)
- [DJ Times: Fair Use and Copyright Laws for DJs](https://www.djtimes.com/2016/12/fair-use-copyright-laws-dj-music/)
- [SW&L Attorneys: DJ Music Mixes — Blatant Copyright Infringement?](https://swlattorneys.com/dj-music-mixes-blatant-copyright-infringement/)
- [Reynolds Law Group: The Legal Lowdown on Remixes and Mashups for DJs](https://www.thomasreynoldslaw.com/blog/2024/08/the-legal-lowdown-on-remixes-and-mashups-for-djs/)
- [Brooklyn Sports & Entertainment Law Blog: Remixing Copyright Law](https://sports-entertainment.brooklaw.edu/music/remixing-copyright-law/)
- [Switcher Studio: What to Know About Livestreaming Copyrighted Music](https://www.switcherstudio.com/blog/what-to-know-about-livestreaming-copyrighted-music)
- [BrewerLong: How to Avoid Copyright Trouble When Livestreaming Your Sets](https://brewerlong.com/information/intellectual-property/livestreaming-copyright-guide/)
- [Radio.co: Music Licensing for Live Streaming DJ Sets and Events (US Edition)](https://www.radio.co/blog/music-licensing-streaming-dj-sets)
- [iMusician: Do I Need a License for My Livestream as a Musician or DJ?](https://imusician.pro/en/resources/blog/which-license-do-i-need-for-my-livestream-as-a-musician-or-dj)
- [Vondran Legal: How to Legally Post Cover Songs on YouTube, TikTok, and Instagram](https://www.vondranlegal.com/how-to-legally-post-cover-songs-on-youtube-tiktok-and-instagram)
- [Vondran Legal: The Art of the DMCA Counter-Notification for YouTube](https://www.vondranlegal.com/the-art-of-the-dmca-counter-notification-for-youtube-by-attorney-steve-vondran)
- [Exploration: What is Non-Interactive Music Streaming?](https://exploration.io/non-interactive-streaming/)
- [Exploration: What is SoundExchange?](https://exploration.io/what-is-soundexchange/)
- [Lexology / Mayer Brown: Music Modernization Act](https://www.mayerbrown.com/en/perspectives-events/publications/2018/10/the-music-modernization-act-what-licensee-services)
- [Pillsbury Law: Licensing and Royalty Requirements for Webcasters (PDF)](https://www.pillsburylaw.com/a/web/2371/689FBDFD3B40B5495649A2DD84A50374.pdf)
- [Congressional Research Service: On the Radio — Public Performance Rights in Sound Recordings (R47642)](https://www.congress.gov/crs-product/R47642)

### Secondary — fingerprinting science (background)

- [Toptal: How Does Shazam Work? Music Processing, Fingerprinting, and Recognition](https://www.toptal.com/algorithms/shazam-it-music-processing-fingerprinting-and-recognition)
- [Towards Data Science: The Five-Second Fingerprint — Inside Shazam's Instant Song ID](https://towardsdatascience.com/the-five-second-fingerprint-inside-shazams-instant-song-id/)
- [Wikipedia: Acoustic fingerprint](https://en.wikipedia.org/wiki/Acoustic_fingerprint)
- [Wikipedia: Audio time stretching and pitch scaling](https://en.wikipedia.org/wiki/Audio_time_stretching_and_pitch_scaling)
- [Wikipedia: Granular synthesis](https://en.wikipedia.org/wiki/Granular_synthesis)

### Secondary — hip-hop ethics and producer-community sources

- [DJBooth: Knxwledge Has No Idea He's One of Hip-Hop's Rising Producers](https://djbooth.net/features/2015-04-22-knxwledge-producer-interview/)
- [Wikipedia: Madlib](https://en.wikipedia.org/wiki/Madlib)
- [Gearspace: How Madlib deal with Copyright?](https://gearspace.com/board/rap-hip-hop-engineering-and-production/1235445-how-madlib-deal-copyright.html)
- [IllMuzik: Madlib sample clearance thread](https://www.illmuzik.com/threads/madlib-sample-clearence.25419/)
- [Sampleface: Knxwledge HX.PRT14_](https://sampleface.co.uk/knxwledge-hx-prt14/)
- [WhoSampled: Madlib](https://www.whosampled.com/Madlib/)

### Secondary — DMCA / EFF policy commentary

- [EFF: DMCA issues portal](https://www.eff.org/issues/dmca)
- [EFF: Lenz v. Universal case page](https://www.eff.org/cases/lenz-v-universal)
- [EFF: Unfiltered — How YouTube's Content ID Discourages Fair Use](https://www.eff.org/wp/unfiltered-how-youtubes-content-id-discourages-fair-use-and-dictates-what-we-see-online)
- [Digital Media Law Project: Responding to a DMCA Takedown Notice](http://www.dmlp.org/legal-guide/responding-dmca-takedown-notice-targeting-your-content)
- [Digital Media Law Project: Circumventing Copyright Controls](https://www.dmlp.org/legal-guide/circumventing-copyright-controls)
- [Copyright Alliance: Section 1201 Technology Protection](https://copyrightalliance.org/education/copyright-law-explained/the-digital-millennium-copyright-act-dmca/section-1201-technology-protection/)
- [New Media Rights: How the DMCA restricts circumventing technological protection measures](https://newmediarights.org/guide/legal/copyright/dmca/How_the_DMCA_restricts_circumventing_technological_protection_measures_like_DRM_and_encryption)
