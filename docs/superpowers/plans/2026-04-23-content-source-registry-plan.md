---
date: 2026-04-23
author: alpha (Claude Opus 4.7)
audience: delta (execution dispatcher) + operator
register: scientific, neutral
status: dispatchable plan — sequenced phases, each one PR
research_doc: docs/superpowers/research/2026-04-23-content-source-registry-research.md
operator-directive-load-bearing: |
  "I never want to get one of these warnings again."
  (2026-04-23, after YouTube ContentID warning on vinyl playback)
---

# Content Source Registry — Implementation Plan

Eight phases. Phase 0 is blocking-must-ship-before-next-stream. Phases
1-7 land in dependency order; Phase 8 is optional polish. Each phase is
one PR; each leaves the live system in a coherent state.

## Phase 0 — Vinyl L-12 carve-out (BLOCKING)

**Branch:** `fix/vinyl-off-l12`
**Estimated:** 1 PR, ~50 LoC + 1 test
**Blocks:** the next stream. Ship before any further work.

- [ ] Audit current vinyl audio routing in
  `~/.config/pipewire/pipewire.conf.d/hapax-vinyl-to-stream.conf` and
  related WirePlumber rules. Identify every node linking vinyl input
  into the L-12 broadcast bus or downstream broadcast graph.
- [ ] Re-route vinyl source nodes to a monitor-only sink
  (`hapax-vinyl-monitor`, not joined to the broadcast graph).
  Operator can still hear vinyl during studio work; it cannot reach
  RTMP/HLS.
- [ ] Add `tests/audio/test_vinyl_not_in_broadcast_graph.py` —
  parses live `pw-link -l` output, asserts no vinyl-source node
  links into any broadcast-bus node. Skip when PipeWire unavailable
  (CI safe).
- [ ] Live verify: `pw-link -l | grep vinyl` shows monitor-only links;
  start a local stream test, play vinyl, confirm broadcast tap
  silent for vinyl audio.
- [ ] PR + admin-merge + restart pipewire user units +
  rebuild-services cascade.

## Phase 1 — `content_risk` taxonomy + Ring 1 capability filter extension

**Branch:** `feat/content-risk-taxonomy`
**Depends on:** Phase 0 merged.

- [ ] Add `ContentRisk` enum to `shared/affordance.py`
  (`TIER_0_OWNED`, `TIER_1_PLATFORM_CLEARED`, `TIER_2_PROVENANCE_KNOWN`,
  `TIER_3_UNCERTAIN`, `TIER_4_RISKY`).
- [ ] Add `OperationalProperties.content_risk: ContentRisk` (default
  TIER_0 for generated capabilities; existing audio capabilities
  default TIER_4 until tagged).
- [ ] Extend `MonetizationRiskGate.candidate_filter()` (or sibling
  `ContentRiskGate`) per the policy in §6.1 of the research doc:
  TIER 4 unconditional reject; TIER 3 require operator session
  unlock (env or `/dev/shm/hapax-control/content-unlock.json`); TIER 2
  require `Programme.content_opt_ins` membership; TIER 0+1 pass.
- [ ] Add `Programme.content_opt_ins: frozenset[ContentRisk]`
  (default `{TIER_0_OWNED, TIER_1_PLATFORM_CLEARED}`).
- [ ] Tag every existing capability in
  `shared/compositional_affordances.py` with appropriate
  `content_risk`. Audit each.
- [ ] Tests:
  `tests/shared/test_content_risk_gate.py` — unit tests per tier policy.
  `tests/shared/test_capability_content_risk_tagged.py` — every
  capability has explicit content_risk (no defaults to TIER_4 in prod).
- [ ] PR + admin-merge.

## Phase 2 — SafeMusicRepository directory layout + ingestion + per-track YAML

**Branch:** `feat/safe-music-repository`
**Depends on:** Phase 1.
**Updates:** the existing local-music-repo design, since the prior
directory layout (`cc-by/`, `cc-by-sa/`, `cc0/`) is no longer
broadcast-safe per the research.

- [ ] New repo layout under `~/music/hapax-pool/`:
  ```
  ~/music/hapax-pool/
  ├── README.md
  ├── index.json                    # cached
  ├── operator-owned/                # TIER 0 — oudepode catalog
  ├── epidemic/                       # TIER 1 — Epidemic downloads
  │   ├── recordings/                  # full tracks
  │   ├── stems/                        # downloaded stems
  │   └── edits/                        # EditRecording loopable beds
  ├── streambeats/                   # TIER 1 — Streambeats fallback
  ├── youtube-audio-library/         # TIER 1 — YT AL
  ├── freesound-cc0/                 # TIER 2 — manual CC0 textures
  ├── bandcamp-direct/               # TIER 3 — per-release confirmed
  └── sample-source-only/            # NEVER broadcast — DAW input
      ├── cc-by/                       # raw CC for sampling into oudepode
      ├── cc0/
      └── splice-loops/
  ```
- [ ] Per-track YAML frontmatter schema (`<track>.yaml` sidecar):
  ```yaml
  attribution:
    artist: "Dusty Decks"
    title: "Direct Drive"
    epidemic_id: "146b162e-fad2-4da3-871e-e894cd81db9b"
    cover_art_url: "https://cdn.epidemicsound.com/..."
  license:
    spdx: "epidemic-sound-personal"
    attribution_required: false
  content_risk: TIER_1_PLATFORM_CLEARED
  source: epidemic
  broadcast_safe: true
  bpm: 92
  musical_key: "f-minor"
  duration_seconds: 151
  mood_tags: [dreamy, laid back]
  taxonomy_tags: [boom-bap, "old school hip hop"]
  vocals: false
  stems_available: [DRUMS, MELODY, BASS, INSTRUMENTS]
  waveform_url: "https://audiocdn.epidemicsound.com/waveform/..."
  ```
- [ ] Migrate `shared/music_repo.py::LocalMusicRepository.select_next()`
  to enforce `broadcast_safe == true` AND
  `content_risk <= active_programme.max_content_risk`.
- [ ] Anything in `sample-source-only/` is hard-rejected by the
  selector but still indexed (so the operator's DAW workflow can
  query it).
- [ ] Tests:
  `tests/shared/test_safe_music_repo_filters.py` — selector never
  surfaces `broadcast_safe: false`.
  `tests/shared/test_safe_music_repo_yaml_schema.py` — every
  ingested track has all required fields; missing-field tracks
  excluded with log warning.
- [ ] PR + admin-merge.

## Phase 3 — Epidemic Sound adapter (search + download + edit)

**Branch:** `feat/epidemic-adapter`
**Depends on:** Phase 2.

- [ ] New `agents/epidemic_adapter/` module structured like
  `agents/soundcloud_adapter/`. Three responsibilities:
  1. **Search proxy** — wraps the Epidemic MCP `SearchRecordings` /
     `SearchSoundEffects` / `SearchSimilarToRecording` /
     `SearchExternalReferences` tools so council services can query
     the catalog without the MCP being a hard dependency.
  2. **Ingestion** — `epidemic-ingest <recording_id>` CLI: pulls
     metadata + downloads MP3/WAV + writes per-track YAML to
     `~/music/hapax-pool/epidemic/recordings/`.
  3. **Bed-music edit pipeline** — `epidemic-bed <recording_id>
     --duration-ms 240000 --loopable` invokes `EditRecording` with
     `loopable: true`, polls until COMPLETED, downloads result,
     writes to `~/music/hapax-pool/epidemic/edits/`.
- [ ] Stem download: `epidemic-stems <recording_id>` pulls all 4-6
  stems for a recording into a flat layout
  `~/music/hapax-pool/epidemic/stems/<recording_id>/{drums,bass,melody,instruments,clean_vocals,vocals}.wav`.
  Each gets a YAML sidecar tagging `parent_recording_id` and `stem_type`.
- [ ] Auth: reuses the user-scope MCP server (no separate API key
  surface). Direct GraphQL calls fall back to `pass:epidemic/mcp-key`
  via `Authorization: Bearer` header for non-MCP contexts.
- [ ] Tests: mock the GraphQL responses; test the YAML-write
  integrity, not the live API.
- [ ] PR + admin-merge.

## Phase 4 — Oudepode rate-limit gate + chat-request impingement path

**Branch:** `feat/oudepode-rate-gate`
**Depends on:** Phase 1, Phase 2.

- [ ] Rolling-play-window: `~/hapax-state/playback-window.json`,
  the last 30 plays across all sources, written by
  `LocalMusicRepository.mark_played()`.
- [ ] `OudepodeRateGate` adjacent to `ContentRiskGate` in
  `AffordancePipeline.select()`:
  - If recruit-trigger is `auto` AND oudepode appears anywhere in
    the last-30 window → filter out oudepode candidates.
  - If recruit-trigger is `chat_request` → bypass rate gate; let
    candidate compete normally.
- [ ] Chat-request impingement: extend the existing `play <n>` sidechat
  command in `music_candidate_surfacer.py` to emit an
  `oudepode.request` impingement (or `music.request` with source-tag)
  rather than direct dispatch. The recruitment loop then volitionally
  honors based on programme/stimmung/ongoing-track.
- [ ] Honored chat requests still update the rate-limit window so
  subsequent auto-recruitment respects the cap.
- [ ] Tests:
  `tests/shared/test_oudepode_rate_gate.py` — auto-recruit filters
  oudepode when window contains it; chat-request bypasses; honored
  chat request updates window.
- [ ] PR + admin-merge.

## Phase 5 — CBIP rework: signal-density "what's playing" ward

**Branch:** `feat/cbip-signal-density`
**Depends on:** Phase 2 (so cover-art-url + waveform-url metadata is
available); Phase 3 (so live tracks have it).

- [ ] Replace `agents/studio_compositor/album_overlay.py` (or
  rewrite alongside) with a multi-layer Cairo + numpy renderer that
  composes:
  1. Cover-art texture base — k-means quantize to HOMAGE palette,
     low-opacity tile background.
  2. Waveform layer — render Epidemic-provided waveform JSON or
     locally-computed waveform for oudepode tracks; live position
     marker.
  3. Stem-activity layer — four lanes (drums/bass/melody/instruments),
     each pulsing at the stem's amplitude envelope (read from the
     mixer's per-stem-channel level meter).
  4. BPM-locked motion grid — particles or grid lines pulse at the
     track's BPM, locked to the mixer transport.
  5. Tag/mood text overlay (Px437, optional, attribution-driven).
- [ ] Smooth crossfade between tracks (200-600ms; no hard cuts; no
  alpha-beat-modulation flashing per
  `feedback_no_blinking_homage_wards`).
- [ ] IR-modulation hook (per §5.5 of research): contact-mic + IR-hand
  signals modulate stem-layer brightness when operator's hands are
  active on the corresponding hardware (MPC pads → drums layer
  brightens; etc.). Optional polish, can defer.
- [ ] Deprecate the dead `/dev/shm/hapax-compositor/album-cover.png`
  producer chain — cover URL flows through metadata directly, no SHM
  file producer needed. Closes the deferred Gemini-audit follow-up
  item `cbip-album-cover-dead`.
- [ ] Tests:
  `tests/studio_compositor/test_cbip_signal_density.py` — render
  golden frames per known-track input (oudepode + Epidemic).
- [ ] PR + admin-merge.

## Phase 6 — Sierpinski YouTube-frame retirement → local visual pool

**Branch:** `feat/local-visual-pool`
**Depends on:** Phase 1 (content_risk tagging).

- [ ] New visual pool layout under `~/hapax-pool/visual/`:
  ```
  ~/hapax-pool/visual/
  ├── operator-cuts/           # TIER 0 — operator's own footage
  ├── storyblocks/              # TIER 1 — paid stock (subscription pending operator decision)
  ├── internet-archive/         # TIER 2 — Prelinger raw PD uploads
  └── sample-source/             # NEVER broadcast — DAW input
  ```
- [ ] `agents/visual_pool/` ingestion CLI similar to
  `epidemic_adapter`. Per-clip YAML sidecar:
  `content_risk`, `source`, `broadcast_safe`, `aesthetic_tags`,
  `motion_density`, `color_palette`, `duration_seconds`.
- [ ] Refactor `agents/studio_compositor/sierpinski_loader.py` to
  read from `~/hapax-pool/visual/<tier>/` selected by aesthetic tag
  instead of `yt-dlp` extraction. Reuse the existing wgpu texture
  pool.
- [ ] Delete `scripts/youtube-player.py` 0.5x-rate hack code path
  (already on the retirement docket as task #66; this is the trigger
  to actually do it).
- [ ] Add regression test
  `tests/studio_compositor/test_sierpinski_no_yt_extraction.py`
  asserting no `yt-dlp` import or invocation in the Sierpinski code
  path.
- [ ] PR + admin-merge.

## Phase 7 — Provenance-token manifest + Ring 3 egress kill-switch

**Branch:** `feat/provenance-manifest-egress-gate`
**Depends on:** Phases 1-3.

- [ ] Every asset loaded into the audio mixer or visual compositor
  must carry a `provenance_token` (Epidemic recording UUID, oudepode
  SC track ID, sha256 of T0 shader source, etc.). Add the field to
  the audio pipeline's track-load path and the compositor's source-
  load path.
- [ ] Per-tick **broadcast manifest** assembled by the compositor +
  audio mixer. Written to `/dev/shm/hapax-broadcast-manifest.json`
  every tick. Schema: `{tick_id, ts, audio_assets: [{token, tier,
  source}], visual_assets: [{token, tier, source}]}`.
- [ ] `EgressManifestGate` reads the manifest each tick. If any asset
  has tier > current programme `max_content_risk` OR is missing a
  provenance token → trigger safe failure:
  - **Audio:** duck compromised mix to -inf dB, fade in pre-cached
    TIER 1 Epidemic emergency bed (`~/music/hapax-pool/epidemic/edits/emergency-bed.mp3`).
  - **Visual:** crossfade compositor output to a full-screen TIER 0
    wgpu fallback shader.
  - Emit `egress.kill_switch_fired` impingement so the affordance
    pipeline learns and avoids the offending capability next tick.
- [ ] Operator notification via ntfy: priority=high, body includes
  the offending asset's token + tier + source.
- [ ] Tests:
  `tests/governance/test_egress_manifest_gate.py` — manifest with
  TIER 4 asset triggers safe failure; missing-token asset triggers
  safe failure; clean manifest passes through.
- [ ] PR + admin-merge.

## Phase 6.5 — YouTube iframe embed ward (allowlist-bounded)

**Branch:** `feat/youtube-iframe-ward`
**Depends on:** Phase 1 (content_risk tagging), Phase 6 (visual pool
infrastructure).
**Distinct from Phase 6's `local-visual-pool`** — Phase 6 retires the
illegal frame-extraction path; this phase adds a NEW legal path for
embedding cleared YouTube videos.

- [ ] `config/youtube-embed-allowlist.yaml` — operator-curated list of
  video IDs cleared for embedding. Schema:
  ```yaml
  - video_id: dQw4w9WgXcQ
    title: "Track name"
    creator: "Channel name"
    cleared_by: operator
    cleared_at: 2026-04-23
    use_case: "music video for currently-playing track"
    content_risk: TIER_2_PROVENANCE_KNOWN
  ```
- [ ] New compositor surface `youtube-embed-ward` — a browser source
  (OBS) or Tauri webview region that loads
  `https://www.youtube.com/embed/<video_id>?autoplay=1&controls=0&modestbranding=1`.
  Width/height per layout JSON.
- [ ] Affordance capability `visual.youtube-embed.<allowlist-id>` —
  one capability per allowlisted video. LLM director can recruit by
  matching the use_case tag, but only from the allowlist.
- [ ] Unit test: `tests/studio_compositor/test_youtube_embed_allowlist.py`
  — capability registration walks the allowlist; no capability ever
  emits a video_id outside the allowlist.
- [ ] Live verify: cued embed loads, plays, and the YouTube creator
  view-counter increments (confirms the embed is recognized as a
  legitimate view).
- [ ] PR + admin-merge.

## ~~Phase 8 — Voiceover integration~~ — CANCELLED 2026-04-23

Operator decision: no voice but Hapax. All speech on broadcast comes
from daimonion via Kokoro. Epidemic voiceover capability stays latent
in the MCP surface but is NOT wired into any production path. This is
a constitutional principle, not just a phase deferral.

## Sequencing summary

| Phase | Branch | Blocking? | Est. PRs |
|---|---|---|---|
| 0 | `fix/vinyl-off-l12` | YES — before next stream | 1 |
| 1 | `feat/content-risk-taxonomy` | unblocks 2-7 | 1 |
| 2 | `feat/safe-music-repository` | unblocks 3-5 | 1 |
| 3 | `feat/epidemic-adapter` | unblocks 5 | 1 |
| 4 | `feat/oudepode-rate-gate` | independent of 5-7 | 1 |
| 5 | `feat/cbip-signal-density` | independent of 6-7 | 1 |
| 6 | `feat/local-visual-pool` | independent of 5, 7 | 1 |
| 6.5 | `feat/youtube-iframe-ward` | independent of 7 | 1 |
| 7 | `feat/provenance-manifest-egress-gate` | last load-bearing | 1 |
| ~~8~~ | ~~programme-voiceover~~ | CANCELLED — Hapax-only voice | 0 |

After Phase 7, the operator's standing directive
(*"I never want to get one of these warnings again"*) is structurally
enforced — broadcast cannot reach a state where TIER 3+ content is
encoded without explicit operator unlock.

## Out of scope (separate tickets)

- Twitch DJ Program migration (operator chose YouTube path).
- AI music generation integration.
- Mobile-livestream-substream (separate WSJF queue item).
- Programme authoring layer (`docs/research/2026-04-19-content-programming-layer-design.md`).
- `pi-ir-cam-not-writing` (separate Gemini-audit deferred ticket).

## Rollback

Each phase is a standalone PR. `git revert <merge-sha>` is always a
clean rollback. Phase 7 (egress gate) is the largest blast-radius
change — its rollback path is documented in the PR description.
