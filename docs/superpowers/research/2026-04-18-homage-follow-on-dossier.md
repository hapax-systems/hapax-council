# HOMAGE Follow-On Research Dossier

**Date:** 2026-04-18
**Scope:** 16 research findings (tasks #121–#136) from parallel agent dispatch during HOMAGE Phase 1–11b execution window.
**Operator policy:** "All research suggestions approved. Provisionally approve every result as it comes in. Don't wait."
**Organizing principle:** Subsystem-first grouping; synergy analysis **deferred to last** per operator directive.

---

## 1. Executive Posture

Sixteen parallel research threads landed during the HOMAGE epic sweep. They split cleanly into six subsystems that together compose the post-HOMAGE livestream surface:

| Subsystem | Tasks | Gravity |
|---|---|---|
| **Rendering / compositor wards** | #121, #122, #123, #124, #125, #126, #128 | Aesthetic + governance backbone |
| **Perception → representation** | #129 (HARD), #135, #136 | Privacy floor + operator-presence fabric |
| **Audio I/O + mic** | #133, #134 | Operator-always-voice-wired infrastructure |
| **Music + content sources** | #127, #130, #131 | Vinyl-adjacent content pathways |
| **Operator ↔ Hapax sidechannel** | #132 | Private ambient comms |
| **Governance signal (derived)** | #122 (DEGRADED), #129 (face-obscure) | Fail-safe + privacy invariants |

All 16 carry **provisional approval** as of 2026-04-18. Fifteen are spec-ready; #126 needs one more iteration pass on axiom-compliance gating before a spec draft.

**Synergy analysis is explicitly deferred.** Each item gets an individual spec stub first; cross-cutting integration is the final pass, performed after all 16 stubs exist.

---

## 2. Research Findings

### Rendering / Compositor Wards

#### #121 — HARDM (Hapax Avatar Representational Dot-Matrix)

**Scope:** New 256×256 px compositor source rendering 16×16 grid of 32 px cells bound to real-time signals. Upper-right quadrant (x=1600, y=20), above Reverie surface in the current 1280×720 output region.

**Key findings:**
- 8+ signal sources already exist and are underused: `vad_speech` (Silero VAD), `midi_active` (OXI One clock), `room_occupancy` (YOLO aggregate), `ir_person_detected` (Pi NoIR), watch HR, BT phone, KDE Connect, ambient sound.
- Cell-to-signal mapping is the novel decision; color mapping to mIRC-16 comes from the BitchX `HomagePackage`.
- TTS waveform capture: Kokoro emits per-phoneme envelopes — 16-band condensation fits cell count exactly.

**Recommended action:** Ship as a first-class `HomageTransitionalSource` subclass with `hardm.*` intent family. Cell colors pull from active package palette; grid geometry is package-invariant.

**Open design questions:**
1. Hardcode cell-to-signal or externalize to `hardm-config.json`? Recommendation: JSON (cheap to iterate).
2. Phoneme fidelity for TTS waveform — full phoneme (60+ phones) vs 16-band? Recommendation: 16-band (matches grid).

**Provisional approval:** ✅ (2026-04-18)
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md`

---

#### #122 — DEGRADED-STREAM Mode (Safe Compositor Fallback)

**Scope:** Compositor visual state shown during live code deploys / rebuild-service cycles to prevent mid-update glitches reaching viewers.

**Key findings:**
- Rebuild timer (`hapax-rebuild-services.timer`, 5-min cadence) restarts services per path-changed detection; restart happens silently, wards may flicker.
- Existing stream-mode governance (`stream_mode_intent.py`) does not surface a "degraded" state.
- Signalling: systemd unit `ExecStartPre`/`ExecStartPost` can `touch /dev/shm/hapax-compositor/degraded.flag`; compositor's main loop reads flag per frame.
- Visual grammar: BitchX netsplit aesthetic — all wards recede to `absent`, single centered text ward reads `*** hapax rebuilding • #hapax :+v operator` in mIRC-grey, with IRC-style activity bar.

**Recommended action:** Ward named `degraded_stream_ward`, activated by flag presence, overrides all other wards. Fades in over 300ms, fades out when flag removed. State exposed as Prometheus metric `hapax_compositor_degraded_active{reason}`.

**Provisional approval:** ✅
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-degraded-stream-design.md`

---

#### #123 — Livestream Chat as HOMAGE Ward

**Scope:** Chat-as-ambient-signal surface (not chat-as-text-scroll); aggregate-only, no author names or bodies.

**Key findings:**
- Chat tiering already exists in `chat_classifier.py`: T0/T1 throwaway, T2/T3 structural, T4 on-topic, T5 research-keyword, T6 citation/DOI.
- Aggregations to visualize: T4+ rate, unique author count, T5/T6 reveal rate.
- BitchX grammar fit: IRC channel userlist `[Users(#hapax:1/N)]` reads T4+ count; `+H` flag ladder reads research-relevance.
- Surface: single row of 4–6 cells in the lower-content-band, each cell a rolling-window aggregate.

**Recommended action:** `ChatAmbientWard` replacing the static `ChatKeywordLegendCairoSource`. Redaction policy: no names ever touch pixels; only counters.

**Provisional approval:** ✅
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-chat-ambient-ward-design.md`

---

#### #124 — Reverie Preservation Under Ward System

**Scope:** Reverie is an always-on generative substrate. HOMAGE Phase 11c would impose `HomageTransitionalSource` FSM on it. Tension: substrate must never recede.

**Key findings:**
- Four integration patterns evaluated: (a) stay-in-HOLD, (b) exempt-from-choreography, (c) inherit FSM + override, (d) use custom[4] shader-coupling slot.
- Reverie publishes `publish_health(ControlSignal(component="reverie", reference=1.0, perception=1.0))` unconditionally — substrate invariant is load-bearing.
- External_rgba integration: ShmRgbaReader → compositor → shader layer. Latency <1 frame.

**Recommended action:** Pattern (b) — **exempt Reverie from HOMAGE choreography**, but add a new marker trait `HomageSubstrateSource` to make the exemption explicit and auditable. No FSM calls; direct blit. Package decisions still *tint* Reverie via palette hints in the custom[4] slot (pattern d addition), but choreography doesn't gate the blit.

**Provisional approval:** ✅
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-reverie-substrate-preservation-design.md`

---

#### #125 — Token Pole (Vitruvian Man) Calibration

**Scope:** Audit `token_pole.py` 300×300 source for layout rescale fidelity, navel anchor, BitchX-grammar fit.

**Key findings:**
- Layout rescale applied correctly; navel geometry intact.
- Grammar is currently SVG-esque; BitchX grammar would strip to monochrome Px437 rendering + mIRC-grey skeleton + bright identity accents on limbs.
- Behavior: pole currently animates on director intent; should be gated through `homage.*` intent families like any other ward.

**Recommended action:** Refactor into `HomageTransitionalSource` subclass. Preserve geometry. Replace fill strategy with package-sourced palette. Wire through compositional_consumer.

**Provisional approval:** ✅
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-token-pole-homage-design.md`

---

#### #126 — Pango Text Repository Rework

**Scope:** Centralized text content pool for overlay zones. Currently scattered; needs Hapax-managed, axiom-compliant surface.

**Key findings:**
- Three overlay zones on 1920×1080: `upper`, `mid`, `lower`, each 200 px tall, persistent.
- Content categories vary in axiom-compliance: author quotes (safe all modes), operator personal notes (safe private/fortress only), management-adjacent notes (safe private only).
- Keyword-scan gate needed: block `feedback|coaching|performance|improvement area` for `public_research` mode.

**Recommended action:** `TextRepository` with per-item frontmatter `{mode_allowlist: [...], axiom_tags: [...]}`. Repository is a directory of `.md` files; scanner runs at compositor startup and on file-change. Director selects one item per zone per rotation interval.

**Spec-readiness:** ⚠️ Requires one iteration pass — axiom-compliance gating is the blocking design decision. Spec stub should start with the gate, not the repository structure.

**Provisional approval:** ✅ (with note that spec will sharpen the gate first)
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-pango-text-repository-design.md`

---

#### #128 — Preset + Composite Variety Expansion

**Scope:** Current preset system has ~30 presets across 56 WGSL nodes; shader layer has high expressive capacity but curation layer is bottleneck.

**Key findings:**
- Constraint: exactly 1 output node per graph (Phase 5a multi-target adds targets, still single-output each).
- No hardcoded pass limit; Reverie uses 8 permanent passes; user presets 6–9 nodes.
- 4 content slots (`content_slot_0..3`) underused: only `content_layer` + `sierpinski_content` currently consume them.
- 3–5× variety reachable via: (1) multi-family stance mapping, (2) parametric mutation of existing presets, (3) temporal modulation knobs, (4) content-slot cross-fades.

**Recommended action:** Phase 1 — parametric mutation pass (apply jitter to stance→preset mapping with 15% variance). Phase 2 — temporal-modulation knobs exposed via director intent. Phase 3 — multi-family stance fan-out. No new shaders required for Phase 1.

**Provisional approval:** ✅
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-preset-variety-expansion-design.md`

---

### Perception → Representation

#### #129 — Facial Feature Obscuring (HARD Privacy Requirement)

**Scope:** Per `it-irreversible-broadcast` T0, no identifiable non-operator broadcast. Operator extends to self-identifiability.

**Key findings:**
- 6 egress paths: main compositor, RTMP tee, HLS, recording, per-camera JPEG snapshots (`/dev/shm`), director multimodal LLM calls.
- **Live leak today:** `content_injector` feeds raw camera JPEGs into Reverie which re-enters compositor at `pip-ur`. No face-obscure stage.
- SCRFD face bboxes + YOLO11n person bboxes exist in perception layer, unused for masking.
- Face-obscure is **additive** to consent-safe swap: swap = governance-visible coarse action; obscure = pixel-level floor during transitions and non-swap egress.
- Technique: solid Gruvbox-dark rect + large-block pixelation/halftone veneer (BitchX-authentic; reversibility-hardened).
- Apply point: **per-camera at capture** (covers all downstream tees including OBS V4L2 loopback).
- Cadence: 5 Hz SCRFD + Kalman bbox carry-forward at 30 fps = ~10–15% of one GPU lane.

**Open questions (operator input needed):**
1. Does operator's own face obscure on **every** egress including local OBS V4L2 loopback? Research recommends yes.
2. SCRFD dropout fallback: fail-closed rect over full frame vs last-known bbox? Research recommends fail-closed for broadcast tees, last-known for local preview.
3. Apply to archival recordings too, or only live broadcast?

**Provisional approval:** ✅ (with operator questions queued)
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-facial-obscuring-hard-req-design.md`

**Priority:** HIGHEST — hard privacy requirement + live leak.

---

#### #135 — Camera Naming + Classification Metadata

**Scope:** 6 cameras currently identified by USB path. Needs Hapax-actionable names + class tags + scene labels.

**Key findings:**
- Per-camera scene labels exist (`per_camera_scenes`) but only global aggregates feed twitch narrative director.
- SigLIP-2 label set is hardcoded at `vision.py:886–899`; replaceable with operator-curated vocabulary.
- Proposed labels include: "operator typing at keyboard", "hands on turntable", "hands on MPC pads", "hands on mixer", "operator sleeping or resting".
- Per-camera gating opens hero-mode selection and follow-mode to per-camera context (see #136).

**Recommended action:** (1) Replace SigLIP-2 label list with operator-authored `camera_scene_labels.yaml`. (2) Wire per-camera scene labels into twitch narrative director + hero-mode selection. (3) Camera naming schema: `{role}-{position}-{class}` (e.g. `desk-left-hw`, `overhead-ceiling-room`, `pi-shelf-ir`).

**Provisional approval:** ✅
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-camera-naming-classification-design.md`

---

#### #136 — Follow-Mode (Operator-Tracking)

**Scope:** Creative shot selection: camera highlight follows operator's physical location + activity.

**Key findings:**
- Perception stack already in place: YOLO11n (multi-cam), SCRFD + 512-d ReID embeddings, MediaPipe Face Mesh (gaze), MediaPipe Hands (8 gestures), Places365 (scene).
- Hero-mode selector has `_CAMERA_VARIETY_WINDOW = 3` (reject last 3 picks), `_CAMERA_ROLE_HISTORY` (600s, max 20), dwell minimum ~12 s (cinematic floor).
- Follow-mode = hero-mode gated by "operator-present-here" boolean per camera + activity tag.

**Recommended action:** New stance `follow_operator` that, when active, constrains hero-mode selection to cameras with `operator_detected=True` in the last 2 s. Tie-break by activity tag priority (hardware-contact > gaze-at-screen > room-presence). Variety window still enforced; dwell floor preserved.

**Open question:** Operator feedback UX — context sidebar in logos showing "currently following: desk-left-hw (hands on MPC)" — useful or distracting?

**Provisional approval:** ✅
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-follow-mode-design.md`

---

### Audio I/O + Mic

#### #133 — Rode Wireless Pro Integration

**Scope:** Rode Wireless Pro enumerates as UAC class-compliant USB audio. Goal: operator always voice-wired even when roaming.

**Key findings:**
- PipeWire 1.4.x (Arch default 2026) enumerates device as `alsa_input.usb-RODE_...`.
- Current hapax-daimonion config: `audio_input_source` consumed at `daemon.py:92`, default Yeti pattern in `config.py:71-80`.
- Multi-mic discovery helper already exists: `multi_mic.py:57-97` (`discover_pipewire_sources`).
- Rode Central Mobile (Android) is needed only for firmware; basic audio works driver-free.
- Occasional Lavalier II / GO lav-mic swap possible.

**Recommended action:** Extend `audio_input_source` config to accept an ordered list `[rode_primary, yeti_fallback, noise_ref]`. Daimonion picks first available source. Discovery helper returns ranked candidates. Runtime swap: systemd path-unit on `/run/udev/data` triggers daimonion reload.

**Provisional approval:** ✅
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-rode-wireless-integration-design.md`

---

#### #134 — Audio Pathways Complete Audit

**Scope:** Full I/O topology, mixer routes, competing sources, ducking infrastructure.

**Key findings:**
- Sources: Blue Yeti (operator primary), PreSonus Studio 24c (Cortado contact mic), YouTube audio sink, ambient noise analysis (AmbientAudioBackend).
- Ducking: YouTube audio separate sink (`hapax-ytube-ducked`).
- **Echo cancellation gap:** `echo_cancel_capture` is the wireplumber node name but no explicit cancellation pass. Operator Yeti picks up YouTube from room speaker crossfeed — VAD + STT both contaminated.
- Unintended consequence: VAD sees YouTube as "speech active" → ducking cycles on phantom operator speech.

**Recommended action:** (1) Enable proper AEC via `module-echo-cancel` (PipeWire module equivalent). (2) Audit ducking trigger — gate on VAD + operator-voice-embedding match, not VAD alone. (3) Document topology as `docs/runbooks/audio-topology.md`.

**Provisional approval:** ✅
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-audio-pathways-audit-design.md`

**Ties tightly to:** #133 (Rode integration extends source list).

---

### Music + Content Sources

#### #127 — SPLATTRIBUTION: No-Vinyl State Detection

**Scope:** Detect when no vinyl is playing to gate non-attribution behaviors (track identification, album overlay, etc.).

**Key findings:**
- Primary signal: `transport_state: Literal["PLAYING", "STOPPED", "PAUSED"]` sourced from OXI One MIDI (start/stop/continue messages at `midi_clock_backend.py:111-122`).
- Write chain: MidiClockBackend.contribute() → perception_state.json → `perceptual_field.audio.midi.transport_state`.
- Latency <20 ms (callback-driven, authoritative).
- Secondary signal: `tendency.beat_position_rate` (beats/sec) — non-zero implies active playback.

**Recommended action:** Add derived signal `vinyl_playing: bool` = `transport_state == "PLAYING" AND beat_position_rate > 0`. Gate album-overlay, track-ID, attribution-emission on this boolean. When false, enable Hapax-music-repo path (#130).

**Provisional approval:** ✅
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-splattribution-no-vinyl-design.md`

**Ties tightly to:** #130 (opens the Hapax-drawn music pool when vinyl is absent).

---

#### #130 — Local Music Repository for Hapax

**Scope:** Curated local library Hapax can draw from when `vinyl_playing == False`.

**Key findings:**
- Existing attribution pathways already distinguish owned/local vs vinyl sources.
- Playback rate default should remain 1.0; environment variable `HAPAX_LOCAL_MUSIC_PLAYBACK_RATE` allows 0.5 override for artistic reasons.
- Repository format: directory tree with per-track YAML frontmatter `{attribution, license, mood_tags, bpm, key}`.

**Recommended action:** `LocalMusicRepository` class; selection gated by `vinyl_playing == False` + current stimmung + BPM/key match to last-played vinyl. DMCA safety: all tracks pre-licensed (operator-owned or CC-licensed).

**Provisional approval:** ✅
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-local-music-repository-design.md`

---

#### #131 — SoundCloud Integration (Operator Account)

**Scope:** Stream Hapax-selected tracks from operator's SoundCloud account during vinyl-absent windows.

**Key findings:**
- SoundCloud Public API open in 2026 but friction-laden: registration via conversational AI agent on developers.soundcloud.com, human review for credential issuance.
- Historical issues `#47`, `#127`, `#219` on `soundcloud/api` document churn.
- Playlist source: `GET /me/tracks?access=playable` filtered to operator's user_id.
- Half-speed DMCA shield: applies to both YouTube and SoundCloud if playback rate override active.

**Recommended action:** Implement after SoundCloud credentials granted. Fallback to #130 if API unavailable. Rate override inherits from `HAPAX_LOCAL_MUSIC_PLAYBACK_RATE`.

**Provisional approval:** ✅ (implementation contingent on credential issuance)
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-soundcloud-integration-design.md`

---

### Operator ↔ Hapax Sidechannel

#### #132 — Direct Comms / Side-Chat During Livestream

**Scope:** Private channel for operator ↔ Hapax communication that is never broadcast.

**Key findings:**
- CPAL runner (`cpal/runner.py`) operates at ~150 ms cognitive intervals, primary voice channel.
- New sidebar component `hapax-logos/src/components/sidebar/OperatorSideChatPanel.tsx` — responses appear ONLY here, never in public overlays.
- Studio compositor's Reverie mixer does NOT recruit side-chat impingements.
- Affordance pipeline filter: `intent_family="operator_private_sidechat"` gates recruitment.
- New command: `ui.sidechat.show_response`.

**Open questions:**
1. Side-chat responses must not persist state about non-operator persons (e.g. "what did I miss during the meeting with Sarah?" cannot store inferences about Sarah). Boundary axiom enforcement needed.
2. Does the narrative director see operator side-chat as context that influences next public narrative, or stay completely silent about it?

**Recommended action:** Ship with `intent_family="operator_private_sidechat"` + corporate_boundary-compliant redaction. Default narrative director: silent (no leak from private to public). Operator can opt-in to "consider side-chat as context" via flag.

**Provisional approval:** ✅
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-18-operator-sidechat-design.md`

---

## 3. Spec Stub Queue

One spec stub per research finding. Order reflects dependency + priority.

| # | Task | Priority | Depends on | Blocks |
|---|---|---|---|---|
| 1 | #129 Facial obscuring | HIGHEST | — | safe broadcast |
| 2 | #134 Audio pathways audit | HIGH | — | #133 |
| 3 | #133 Rode Wireless Pro | HIGH | #134 | #132 mic path |
| 4 | #124 Reverie preservation | HIGH | HOMAGE Phase 11c | Phase 12 |
| 5 | #122 DEGRADED-STREAM | HIGH | — | live-safe deploys |
| 6 | #121 HARDM | MED | #136 signals | — |
| 7 | #136 Follow-mode | MED | #135 | — |
| 8 | #135 Camera naming | MED | — | #136 |
| 9 | #127 SPLATTRIBUTION | MED | — | #130 |
| 10 | #130 Local music repo | MED | #127 | #131 |
| 11 | #131 SoundCloud | LOW | #130 | — |
| 12 | #132 Operator sidechat | MED | #133 | — |
| 13 | #123 Chat ambient ward | MED | — | — |
| 14 | #128 Preset variety | MED | — | — |
| 15 | #125 Token pole HOMAGE | LOW | HOMAGE Phase 11c | — |
| 16 | #126 Pango text repo | MED (iteration) | axiom gate | — |

---

## 4. Synergy Analysis: DEFERRED

Per operator directive (2026-04-18): "At the very end we will look for synergies across the board (save for last)."

**Preconditions for synergy pass:**
- All 16 individual spec stubs exist.
- Each stub has operator-visible status (approved / needs-iteration).
- HOMAGE epic Phase 12 complete or near-complete (so synergy pass reasons about final HOMAGE surface, not mid-flight).

**Placeholder:** `docs/superpowers/research/2026-04-XX-homage-follow-on-synergy-analysis.md` — to be created after last spec stub lands.

Do **not** prematurely weave cross-cutting abstractions between items. Each subsystem first earns its own spec; synergies emerge from the collision of completed shapes.

---

## 5. Status

- **Dossier:** complete (this file, 2026-04-18).
- **Provisional approval:** all 16 items stamped.
- **Spec stubs:** 0 / 16 written.
- **Synergy pass:** not started (by design).

**Next action:** Cascade items 1–5 (priority HIGH) to spec stubs in parallel with HOMAGE Phase 6 implementation.
