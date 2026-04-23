---
date: 2026-04-23
author: alpha (Claude Opus 4.7)
audience: operator + delta
register: scientific, neutral
status: research synthesis — input to plan doc
trigger: |
  Operator received a YouTube copyright warning during vinyl playback through
  a moderate-modulation filter chain on 2026-04-23. Decision: vinyl is
  permanently retired from broadcast. Operator wants a comprehensive content
  source registry covering all audio AND visual content reaching the stream,
  mapped to use cases, with risk tiers and an axiom-gate enforcement layer.
related:
  - docs/superpowers/specs/2026-04-18-local-music-repository-design.md
  - docs/superpowers/specs/2026-04-18-soundcloud-integration-design.md
  - docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md
  - docs/superpowers/plans/2026-04-20-youtube-broadcast-bundle-plan.md
  - docs/research/2026-04-19-content-programming-layer-design.md
  - docs/research/2026-04-19-demonetization-safety-design.md
plan_doc: docs/superpowers/plans/2026-04-23-content-source-registry-plan.md
---

# Content Source Registry — Research Synthesis

## §1 Executive summary

1. **Vinyl is permanently off-broadcast.** Modern Content ID (Neural Audio
   Fingerprinting via Music Foundation Models — MuQ, MERT) defeats every
   musically-usable transformation: pitch shift, time stretch, EQ, reverb,
   layering, vinyl artifacts. There is no "modulation that works without
   destroying the music." The threshold at which detection fails is the
   threshold at which the audio is unlistenable.
2. **"Royalty-free" ≠ "ContentID-free."** CC, public domain, NCS, Mixkit,
   Pixabay, FMA, ccMixter, Splice loops, Beatstars type-beats — all are
   false-positive minefields because third parties register matching
   audio/loops via TuneCore/DistroKid. Only platforms with API-level
   YouTube channel-whitelist agreements are mechanically safe.
3. **Epidemic Sound is the load-bearing licensed source.** MCP server is
   live (`epidemic-sound` at user scope, hosted at
   `https://www.epidemicsound.com/a/mcp-service/mcp`). Catalog smoke-tested
   confirms: 500+ matches for "dusty soul instrumental boom-bap 80-95
   BPM, no vocals", every track exposes 6-stem split (DRUMS, BASS, MELODY,
   INSTRUMENTS, CLEAN_VOCALS, VOCALS), server-side editing supports
   loopable bed-music generation up to 5 minutes, Spotify-track external
   reference search bridges commercial taste references to safe analogs.
4. **The 5-tier risk taxonomy** (TIER 0 own/generated → TIER 4
   vinyl/commercial) extends the existing
   `OperationalProperties.monetization_risk` flag. TIER 0 + TIER 1 may
   auto-recruit; TIER 2 requires programme opt-in; TIER 3 requires
   operator session unlock; TIER 4 is air-gapped from broadcast.
5. **The Sierpinski ward's YouTube frame ingestion is a structural
   ToS+ContentID violation** independent of the audio path. Replacing it
   with a local T0/T1 video pool is a precondition for safe operation.
6. **CBIP (album overlay) needs a complete rework** — the current
   "blit album scan into corner" model is no longer aesthetically
   load-bearing once vinyl is gone. The new design becomes a
   signal-density representation of whatever is playing, derived from
   the source's own metadata (waveform, stems, BPM, mood tags).
7. **Three-ring axiom-gate extension**: the existing Ring 1 capability
   filter needs `content_risk` added; the existing Ring 3 egress audit
   needs to upgrade from output-buffer inspection to a
   provenance-token manifest enforced before the encoder.

## §2 The risk landscape

### §2.1 What modern Content ID actually does

YouTube Content ID and Twitch Audible Magic both transitioned 2025-2026
from constellation-map peak hashing to neural fingerprinting trained
adversarially on every common transformation. Detection survives:

| Transformation | Defeats fingerprint? | Notes |
|---|---|---|
| Pitch shift ±5-10% (DJ varispeed) | No | Caught instantly |
| Pitch shift ±20-30% | Begins to fail | Audio becomes "chipmunk" / unlistenable |
| Time-stretch / tempo change | No | Tempo-invariant hashes via SIFT on log-frequency spectrograms |
| EQ / high-pass / low-pass / isolator | No | Hashes index peaks across full spectrum; system matches on bands you didn't filter |
| Reverb / delay / spatial | No | Adds noise; doesn't remove dry anchor peaks |
| Vinyl artifacts (rumble, crackle, wow/flutter) | No | Algorithm is medium-agnostic; treats artifacts as filterable broadband noise |
| Layering / mashup | No | Internal stem-splitting isolates copyrighted vocal/melody |
| All combined within musical usability | No | "If it sounds like the song, the math will flag it." |

Operational realities:
- **Live = real-time scan.** YouTube Live mutes / replaces with static / terminates streams when a match persists.
- **VOD retro-scan.** Anything that slips past live is caught when the archive is processed against the larger VOD database.
- **Multi-modal.** Visible album cover or vinyl on camera can confirm an audio match the system would otherwise let pass.
- **Willful infringement penalty.** Deliberate modulation-to-evade is legally classified as willful → up to $150k/work statutory damages.
- **Three strikes.** Repeat warnings on YouTube Live escalate fast to channel termination.

### §2.2 The false-positive trap

Even legally-clean sources fail when third parties register matching
audio. The trap is structural to ContentID: the algorithm matches
audio, not licenses. If a popular CC0 rain sample appears in a
"sleep music" album someone uploaded to Spotify with ContentID enabled,
your stream gets claimed for using the same CC0 rain.

Sources with NO whitelist defense (high false-positive risk on YouTube):
- NCS (NoCopyrightSounds) — many 2014 tracks now claimed
- Mixkit, Pixabay — community uploads, often re-registered
- Free Music Archive (FMA), ccMixter, Jamendo — CC content frequently re-registered
- Splice / Loopcloud loops played raw — guaranteed strike (thousands of producers used same loop)
- Beatstars / Airbit type-beats — non-exclusive leases; every licensee strikes you
- Bandcamp direct license — only safe with explicit per-release ContentID-disabled confirmation from the artist

Sources WITH channel-whitelist defense (mechanically safe):
- Epidemic Sound — flawless; cleared even after subscription cancellation
- Streambeats by Harris Heller — bulletproof; team kills false claims
- Pretzel Rocks — "YouTube Safe" toggle; channel-link clearance
- Storyblocks / Envato Elements / Artgrid (visual) — channel-whitelist
- YouTube Audio Library — inherent (YouTube's own system)
- Operator's own work — N/A (you own it), but **distributor must whitelist your channel** to prevent self-strike

## §3 Use-case-to-source mapping

### §3.1 Audio use cases × source matrix

| Use case | Operator's own (oudepode) | Epidemic Sound | Streambeats | Pretzel | Freesound CC0 | Bandcamp direct | Vinyl / commercial |
|---|---|---|---|---|---|---|---|
| Hero / featured tracks | **PRIMARY** | No | No | No | No | Conditional | NEVER |
| Bed music during sets | Primary | **PRIMARY** (stems) | Conditional | Conditional | No | No | NEVER |
| BRB / step-away | Conditional | Primary | **PRIMARY** | Primary | No | No | NEVER |
| Drops / stings / transitions | **PRIMARY** | Primary (SFX) | No | No | **PRIMARY** | No | NEVER |
| Sample textures (under everything) | Primary | Primary (SFX) | No | No | **PRIMARY** | No | NEVER |
| Director-cued musical moves | Primary | **PRIMARY** (rich tags) | Conditional | No | No | No | NEVER |
| Programme-driven content | Primary | **PRIMARY** | Primary | Primary | Primary | Conditional | NEVER |
| Vocal samples / chops (within own production) | Primary | Primary (clean_vocals stem) | No | No | Primary (PD speech) | No | NEVER |

### §3.2 Visual use cases × source matrix

| Use case | Studio cameras + shaders | Storyblocks / Artgrid | Internet Archive (PD raw) | AI-generated (Sora/Veo) | Pexels / Pixabay video | YouTube iframe embed (allowlist) | YouTube frame extraction | Commercial film/TV |
|---|---|---|---|---|---|---|---|---|
| YouTube clips on broadcast (cleared / curated) | No | No | No | No | No | **PRIMARY** (TIER 2) | **NEVER** (ToS+ContentID violation) | NEVER |
| Album art display alongside playing track | No | Conditional | No | No | No | No | No | NEVER |
| Sample / collage images | No | **PRIMARY** | **PRIMARY** | Primary | Conditional | No | No | NEVER |
| Stock B-roll | No | **PRIMARY** | Primary (raw uploads only) | Primary (with synthetic-content label) | Conditional | No | No | NEVER |
| Generated visuals (wgpu, Sierpinski, GEM) | **PRIMARY** | No | No | No | No | No | No | No |
| Studio cameras (operator + room) | **PRIMARY** | No | No | No | No | No | No | No |
| Programme-driven visual moves | **PRIMARY** | Primary | Primary | Primary (with label) | Conditional | Conditional | No | NEVER |
| Director-cued visual swaps | **PRIMARY** | Primary | Primary | Primary (with label) | Conditional | Conditional (allowlist-bounded) | No | NEVER |

The "YouTube iframe embed" path is distinct from frame extraction:
the embed loads
`https://www.youtube.com/embed/<video_id>?autoplay=1&controls=0&modestbranding=1`
into a browser source / Tauri webview surface, served from YouTube's
CDN — counts as a view for the original creator, serves their ads,
fully ToS-compliant. Limited to an operator-curated allowlist of
cleared video IDs (`config/youtube-embed-allowlist.yaml`) — the LLM
director cannot recruit arbitrary YouTube content. See §9 Q1.

### §3.3 Oudepode rate-limit policy (operator's own catalog)

Operator constraint (2026-04-23): operator's own SoundCloud catalog
(oudepode tracks) must not auto-recruit more frequently than **once per
30 plays**. Two independent paths into the playback queue, with
distinct policy:

- **Auto-recruitment path** (director / scheduler): rolling-window
  rate cap. The recruitment scheduler maintains a deque of the last
  30 plays across all sources; if an oudepode track appears in that
  window, oudepode-source candidates are filtered out of the next
  recruitment cycle. ~3.3% maximum rotation share.
- **Chat-request path** (sidechat command, e.g. existing `play <n>`
  flow in `music_candidate_surfacer.py`): chat can explicitly request
  an oudepode track. This **bypasses the rate cap** but does NOT
  bypass the affordance pipeline — chat requests register as an
  `oudepode.request` impingement, the recruitment loop weighs it
  alongside other affordances, and Hapax volitionally honors or
  defers based on current programme / stimmung / ongoing track. The
  request is a strong soft-prior, not a hard dispatch. Honored
  requests count toward the rate-limit window for subsequent
  auto-recruitment.

Implementation surface: a new `OudepodeRateGate` that runs adjacent to
the content-risk gate in `AffordancePipeline.select()`, reading the
shared rolling-play-window state. The gate filters oudepode candidates
out of auto-recruitment when the window is "hot"; the chat-request
impingement bypasses the gate but feeds back into the window on play.

This aligns with the existing memory `project_soundcloud_bed_music_routing`
("operator does not want their own tracks showcased up-front") — the
30-play rate cap is the structural enforcement of the presentation
preference; the chat-request volition is the operator's own override
when it's the right musical moment.

### §3.4 Voiceover (Epidemic ListVoices/GenerateVoiceover) — separate use-case axis

Epidemic ships ~10+ professional voice artists × 30+ languages each
(catalog smoke-test confirmed). This is distinct from operator's
existing Kokoro 82M TTS in `hapax-daimonion`, which serves the
daimonion's first-person voice. Voiceover candidates:

- **Programme intros / outros** — "documentary narrator" framing for the
  start/end of a programme, distinct from daimonion's continuous voice.
- **Section titles** — "you are now entering the workshop block."
- **Retrospective narration** — VOD post-production overlay.
- **Multilingual captions / overlays** for international viewers.

Not for: real-time conversation (latency too high, daimonion's role).

## §4 Verified Epidemic Sound capability surface

Tools surfaced as `mcp__epidemic-sound__*`. Verified by smoke-test 2026-04-23.

### §4.1 Discovery & retrieval

- **`SearchRecordings`** — full catalog search. Filters: BPM (min/max),
  duration (ms), musical key (e.g. `c-minor`, `f-major`), mood slugs,
  taxonomy slugs (genre, decade, world-country), featured-instrument
  slugs, vocals (boolean), artist slugs, tag slugs. Sort: relevance,
  popularity, date, duration, title, BPM. Returns Recording with id,
  title, BPM, coverArtUrl (3000x3000 PNG), audioFile (lqmp3 preview +
  waveform JSON URL + duration), **stems[6]**, tags (with taxonomy
  dimension), credits (composer, main artist, featured, producer).
- **`SearchSoundEffects`** — same shape for SFX.
- **`SearchSimilarToRecording`** — given a recording UUID, find similar
  Epidemic tracks. Recursive (returns a `similarRecordings` field on each
  result).
- **`SearchSimilarToSoundEffect`** — same for SFX.
- **`SearchExternalReferences`** — text query → Spotify track IDs.
  Then those Spotify IDs feed `SearchRecordings` via the `externalID`
  query path to find Epidemic equivalents to commercial music.
  **Bridges operator's commercial taste references to safe analogs.**
- **`DownloadRecording` / `DownloadRecordingEdit` / `DownloadSoundEffect`**
  — get the actual audio files (license-cleared).

### §4.2 Server-side editing (key for bed music)

- **`EditRecording`** — async job. Inputs:
  - `targetDurationMs` (max 300000ms = 5 min)
  - `downloadAudioFormat`: MP3 or WAV
  - **`loopable: true`** — generates seamless loop for bed music.
  - `forceDuration: true` — exact duration enforcement.
  - `skipStems` — faster job if you don't need stems.
  - `requiredRegionsAtOffsets` — pin specific source regions to specific
    output offsets (intro/outro/build alignment).
  - `preferenceRegions` — bias toward/away from source regions.
  - `maxResults` — return multiple edit candidates.
  - Returns `RecordingEditJob { id, status }`. Poll via
    `PollEditRecordingJob`.
- **`PollEditRecordingJob`** — status: PENDING / IN_PROGRESS / COMPLETED / FAILED.

### §4.3 Voiceover generation

- **`ListVoices`** — paginated voice artist catalog with bios + example
  audio + characteristics + 30+ supported languages each.
- **`ListUserGeneratedVoices`** — operator-cloned voices (if any).
- **`GenerateVoiceover`** — text-to-speech with selected voice + language.
- **`PollVoiceoverGenerationStatus`** — async job poll.
- **`GetVoiceover` / `DownloadVoiceover`** — retrieve the file.

### §4.4 GraphQL backend exposure

The MCP is a thin Apollo wrapper over Epidemic's GraphQL API.
`introspect`, `execute`, `search`, `validate` tools allow direct GraphQL
exploration if needed for fields not exposed by the named tools.

## §5 CBIP / Splattribution rework

### §5.1 Current state

The existing CBIP (album overlay) ward (`agents/studio_compositor/album_overlay.py`)
blits a quantized album scan into the lower-left quadrant with a BitchX
header + Px437 splattribution text. Per the post-Gemini-cleanup state,
the alpha-beat-modulation flashing is being removed; the duplicate
scanline block is being removed; a static cover image is the current
fallback. The `album-cover.png` producer chain is currently dead
(deferred root-cause investigation per the Gemini audit remediation plan).

This design assumes a single dominant content path (vinyl → identified
album → blit cover). Once vinyl is retired and the broadcast path
becomes a multi-source registry (oudepode + Epidemic stems + Streambeats
+ textures), the "blit album scan" model loses its load-bearing role.

### §5.2 Aesthetic constraints from operator memory

- **HARDM / anti-anthropomorphization** — raw signal density on a grid;
  no faces, no eyes, no expressions.
- **No-blinking-HOMAGE-wards** — no hard on/off, no inverse-flash, no
  high-frequency strobe; smooth envelopes (ease/sine/log decay), 200-600ms
  crossfades.
- **GEM aesthetic bar = Sierpinski-caliber** — multi-layer, algorithmic,
  depth-capable; text-in-a-box is a failure state.
- **Show-don't-tell** — wards do not narrate compositor/director actions;
  the action IS the communication.
- **Wards-vs-effects taxonomy** — CBIP is a ward (not a shader effect);
  it lives in the Cairo-overlay layer.

### §5.3 New CBIP design — "now-playing as signal-density"

Rather than blit a literal album scan, CBIP becomes a **multi-layer
generative representation** of whatever is currently playing, driven by
the source's own metadata. Layers (back-to-front):

1. **Cover-art texture base.** The Epidemic / oudepode cover URL is
   pulled, downsampled, k-means-quantized to the active HOMAGE palette
   (16 colors), then used as a low-opacity background texture — not a
   blit. Dithered, tiled, possibly reaction-diffused. Cover provides
   color identity; the literal image is not the foreground.
2. **Waveform layer.** Epidemic provides a `waveformUrl` (JSON peaks per
   recording). The compositor renders the live waveform position as a
   horizontal scrub or vertical bars in the HOMAGE palette. For oudepode
   tracks, generate the waveform offline once and cache.
3. **Stem-activity layer.** When stems are playing (Epidemic
   `EditRecording` produces individual stems; the operator's mixer
   routes drums/bass/melody/instruments separately), each active stem
   gets a visual lane — e.g. four narrow horizontal grids, one per stem,
   each pulsing at the stem's amplitude envelope. This is structural
   sonification: the viewer can SEE the mix.
4. **BPM-locked motion grid.** Subtle grid lines or particles pulse at
   the track's BPM — locked, not freely-running, so the visual
   reinforces the musical pocket.
5. **Tag / mood text overlay** (if-and-only-if needed for attribution
   compliance). Px437 monospace with a slow crossfade. Text appears
   only where attribution is contractually required (Streambeats: yes;
   Epidemic: no; oudepode: optional vanity). When present, it's tag-style
   ("dusty soul · 92 bpm · F minor · Dusty Decks") rather than
   "Now Playing" framing.

The whole ward sits in the lower-left quadrant or wherever the layout
slot has been allocated; design language compliance via CSS tokens, no
hardcoded colors. Smooth crossfade between tracks (fade old layers,
fade in new); no hard cuts.

### §5.4 Why this design satisfies the constraints

- **Aesthetic alignment:** signal-density on a grid; algorithmic; multi-
  layer; no faces; reaches Sierpinski-caliber by being more than a
  texture-quad.
- **Show-don't-tell:** the visual IS the music's identity. No "now playing:"
  framing. The viewer reads the waveform + stem activity + cover-derived
  palette and KNOWS what's playing.
- **Source-agnostic:** works equally for oudepode, Epidemic, Streambeats,
  Freesound textures. No source-type special-casing in the ward.
- **Dead `album-cover.png` producer is deprecated entirely** — the
  cover URL flows through the new pipeline directly from the source
  metadata; no SHM file producer required. Closes one of the deferred
  Gemini-audit follow-up items.
- **Reuses existing infrastructure:** HOMAGE palette quantization,
  Cairo overlay, splattribution text path. Not a from-scratch ward.

### §5.5 Repurposing the camera + chessboard space

Operator note (2026-04-23): the chessboard space and IR image capture
remain available for OTHER use cases beyond vinyl identification. The
Pi NoIR fleet + chessboard calibration target now serve:

- **CBIP modulation by IR hand activity** — when operator's hands are
  active on the contact mic / MPC, CBIP's stem-activity layer can boost
  the relevant stem's brightness (e.g. drum stem brightens when MPC pad
  taps register on the contact mic).
- **Gestural intensity → particle density** in the BPM-locked motion
  grid layer.
- **Programme transitions via IR presence pattern** (operator stepping
  back from the desk = wind-down programme onset).
- These are existing IR perception signals; no new capture pipeline.

## §6 Risk taxonomy + axiom-gate extension

### §6.1 The 5-tier model

Extend `OperationalProperties.monetization_risk` to a richer
`content_risk` enum. Five tiers, with explicit gating policy per tier:

| Tier | Definition | Examples | Auto-recruit policy |
|---|---|---|---|
| **TIER 0** | Provably safe — operator-owned, generated, or hardware-captured | wgpu shaders, Sierpinski/GEM, studio cameras, oudepode catalog | Always |
| **TIER 1** | Platform-cleared, channel-whitelisted | Epidemic Sound, Storyblocks, Streambeats, Pretzel, YouTube Audio Library | Always |
| **TIER 2** | Provenance-known, manual-clear | Verified CC0 audio (Freesound, hand-checked), Internet Archive raw PD uploads | Programme opt-in only |
| **TIER 3** | Probable-safe, uncertain | Direct Bandcamp permission (per release), CC-BY (attribution required), public-domain compositions of post-1923 recordings | Operator session unlock only |
| **TIER 4** | Known-risky | Vinyl rips, commercial music, raw type-beats, stream-ripped YouTube, uncleared TV/film clips | NEVER on broadcast bus; physically air-gapped |

### §6.2 Integration with the existing 3-ring axiom-gate

The existing demonetization-safety plan
(`docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md`)
defines a 3-ring filter: Ring 1 capability filter → Ring 2 pre-render
classifier → Ring 3 egress audit. Extensions per ring:

**Ring 1 — capability filter (already shipped, extend):**
- Add `OperationalProperties.content_risk: ContentRisk` (5-tier enum).
- `MonetizationRiskGate.candidate_filter()` already removes high-risk
  capabilities; extend to enforce the per-tier policy above
  (TIER 4 → unconditional removal; TIER 3 → require operator-session
  unlock; TIER 2 → require programme opt-in via
  `Programme.content_opt_ins: frozenset[ContentRisk]`; TIER 0+1 → pass).

**Ring 2 — pre-render classifier (planned, scope clarification):**
- The classifier targets externally visible TEXT (TTS, captions,
  chronicle). It does NOT classify audio/visual content provenance —
  that is Ring 1's job. Keep ring boundaries clean.

**Ring 3 — egress audit, upgrade to provenance-token manifest:**
- Each asset loaded into the audio mixer or visual compositor must
  carry a `provenance_token` (Epidemic recording UUID, oudepode SC
  track ID, hash of T0 shader, etc.).
- The compositor + audio mixer assemble a per-tick **broadcast
  manifest**: every asset currently in any output mix.
- A new `EgressManifestGate` runs on the manifest each tick. If any
  asset is missing a provenance token OR has `content_risk >= TIER_2`
  without explicit unlock, the gate triggers a **safe failure**:
  - **Audio:** duck the compromised mix to -inf dB; fade in a TIER 1
    Epidemic emergency bed (pre-cached locally).
  - **Visual:** crossfade compositor output to a full-screen TIER 0 wgpu
    fallback shader (slow particle field tuned to current stimmung).
- This is the kill-switch. It runs BEFORE the RTMP/HLS encoder, so a
  rogue LLM recruiter cannot reach broadcast.

### §6.3 Vinyl carve-out from L-12

Independently of the registry work, the vinyl decks need to be removed
from the L-12 broadcast bus immediately. The vinyl filter chain
(`~/.config/pipewire/pipewire.conf.d/hapax-vinyl-to-stream.conf`) and
its source nodes are routed to a monitor-only sink — operator can still
hear vinyl during work; broadcast cannot reach it. Add a regression test
that asserts no vinyl source links into the broadcast graph.

This is a one-shot PipeWire/WirePlumber config change; bundle into
Phase 1 of the implementation plan.

## §7 Sierpinski YouTube-frame ingestion — replace with local pool

### §7.1 The current violation

`agents/studio_compositor/sierpinski_loader.py` and the surrounding
youtube-player infrastructure extract video frames from YouTube via
`yt-dlp`/`ffmpeg` and feed them into the Sierpinski ward as visual
content. This is:

- A YouTube ToS violation (downloading / stream-ripping).
- A ContentID risk: extracting frames and rebroadcasting them on
  YouTube subjects you to visual ContentID. Mapping the frames onto a
  Sierpinski triangle does not defeat the hash.
- The 0.5x playback rate "DMCA evasion" pattern in
  `scripts/youtube-player.py` is dead code — the audio modulation
  research applies symmetrically to video. There is no playback rate
  that defeats visual ContentID without destroying the visual.

### §7.2 The replacement

Pre-download a curated local video pool:

- **Storyblocks subscription** (paid; channel-whitelisted) for abstract
  motion, color washes, urban B-roll fitting the operator's aesthetic.
- **Internet Archive raw PD uploads** (Prelinger Archives) for vintage
  film grain, industrial footage, era-appropriate texture.
- **Operator's own cuts** — studio session footage, room time-lapse,
  recorded analog visuals.

Sierpinski reads from `~/hapax-pool/visual/<tier>/` and renders frames
from local files via the existing wgpu texture pool. Same aesthetic,
zero network latency, zero ToS / ContentID risk.

The youtube-player audio path is independently retired by the
local-music-repo + Epidemic integration — this audit closes both ends.

## §8 Director / programme integration

### §8.1 Director recruitment by abstract type

The director loop currently recruits content by abstract dimensions
("dusty soul", "tense", "70s grain"). For this to work safely against
the registry:

- **Tagging schema**: every audio asset in the local pool carries
  Epidemic-style metadata in YAML frontmatter — `bpm`, `musical_key`,
  `mood_slugs`, `taxonomy_slugs` (genre / decade / world), `vocals`
  (bool), `featured_instruments`, `tags`. For Epidemic-sourced assets,
  ingest the metadata directly from `SearchRecordings` results.
- **Vector layer**: free-text descriptors ("dreamy", "laid back",
  "boom bap") → Qdrant collection `music_assets`. Director's abstract
  query → embed → cosine similarity → candidate set.
- **Hard filters**: `content_risk <= programme.max_risk` is enforced as
  a Qdrant payload filter, so the LLM literally cannot see TIER 3+
  candidates outside the unlock window. **Oudepode rate cap** (§3.3) is
  also enforced at this layer when the recruitment trigger is auto
  (not chat-requested).
- **Soft scores**: programme priors ("tonight's theme is dusty soul")
  apply a +0.3 cosine similarity boost; they bias, not restrict.

### §8.2 Programme-content-opt-in semantics

`Programme.content_opt_ins: frozenset[ContentRisk]` works identically
to the existing `monetization_opt_ins`. A programme can declare
`{TIER_0, TIER_1, TIER_2}` to allow Freesound CC0 layered textures
during a specific block; default is `{TIER_0, TIER_1}`.

### §8.3 Safe failure when no candidate matches

If the director requests a content type and no safe candidate exists
above similarity threshold:

- **Audio:** fall back to a default Epidemic bed playlist (TIER 1).
  Always cached locally so this works offline.
- **Visual:** fall back to a wgpu procedural shader. Director can
  modulate shader uniforms (`temporal_distortion`, `noise`,
  `colorgrade`) to approximate the requested aesthetic via safe math
  rather than a media file.

This eliminates the failure mode where the director silently surfaces
an unsafe candidate because nothing safe matched.

## §9 Operator decisions (resolved 2026-04-23)

1. **Visual sources: YouTube AND Storyblocks both, with mechanism
   separation.** The prohibition is on FRAME EXTRACTION (current
   Sierpinski yt-dlp pipeline — ToS + ContentID violation). YouTube
   embeds via official iframe ARE legal (served from YouTube CDN,
   counts as a view for the creator, serves their ads). Two distinct
   visual paths going forward:
   - **Local visual pool** (Storyblocks + IA PD + operator cuts) —
     compositor reads frames from `~/hapax-pool/visual/<tier>/`.
     Used for Sierpinski texture, abstract B-roll, programme-cued
     visual moves. TIER 1 / TIER 2.
   - **YouTube iframe embed ward** — a new compositor surface that
     loads `https://www.youtube.com/embed/<video_id>?autoplay=1&controls=0&modestbranding=1`
     in a browser-source / Tauri-webview region. Operator-curated
     allowlist of cleared video IDs in
     `config/youtube-embed-allowlist.yaml`. TIER 2 (provenance-known
     via allowlist). NO LLM-driven discovery from arbitrary YouTube;
     allowlist-only.
   - Storyblocks subscription decision deferred to whenever operator
     decides the visual pool needs paid stock; meanwhile IA PD +
     operator cuts cover the floor.
2. **Distributor: not currently used, not currently necessary.**
   Oudepode lives on SoundCloud only. Live performance on the
   operator's own YouTube stream is not a distribution event; ContentID
   cannot claim against tracks not registered with ContentID via a
   distributor. Distributor becomes necessary only if/when the operator
   wants (a) streaming royalties beyond YouTube ad share, (b) defensive
   ContentID registration so others can't fraudulently claim oudepode,
   or (c) cross-platform release. **Critical future trap**: if a
   distributor IS adopted, operator MUST either opt-out of ContentID
   for tracks that play on stream OR explicitly whitelist the YouTube
   channel in the distributor dashboard. Track this as a future-state
   condition; not a current implementation requirement.
3. **No voice but Hapax.** All speech on broadcast comes from Hapax
   via daimonion / Kokoro. Epidemic voiceover capability stays latent
   in the MCP surface but is NOT wired into any production path.
   Phase 8 (programme voiceover via Epidemic) is **cancelled**.
   Programme intros / transitions / narration all use the existing
   daimonion voice pipeline. This is a constitutional principle for
   the broadcast: one voice, one identity, no third-party narration.
4. **CC0 / `sample-source-only/` directory: keep as deferred-decision
   default.** The implementation creates the directory empty with
   `broadcast_safe: false` flag enforced at the selector layer. The
   operator can populate (for DAW sampling) or delete entirely later;
   broadcast safety is not affected either way.
5. **Daimonion stays on Kokoro.** Confirmed. No routing through
   Epidemic voices.

## §10 What this research does NOT cover (deferred)

- Twitch DJ Program migration analysis (Path B from earlier research).
  Operator chose Path A — stay on YouTube, build safe repo.
- AI music generation (Suno, Udio) integration. Skipped per the
  earlier research's "alienates producer-centric audience" finding.
- Mobile-livestream-substream (separate WSJF queue item).
- Programme authoring details — the programmes layer is being designed
  separately (`docs/research/2026-04-19-content-programming-layer-design.md`).
  This doc only covers the registry's interface to programmes.
