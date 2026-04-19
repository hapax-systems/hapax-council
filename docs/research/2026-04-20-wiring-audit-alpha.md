# Full Wiring Audit Checklist — Alpha Execution

**Author:** cascade session (research subagent, 2026-04-19)
**Assignee:** alpha
**Directive (operator, 2026-04-19):**
> "do a full audit of all wiring and make sure every single thing that should be wired is wired, assign to alpha, should be very very granular"

**Scope:** every wiring link the running livestream depends on — visual ward render paths, audio routing end-to-end, impingement ⇄ pipeline flow, director intent_family → consumer dispatch, observability emit sites, systemd lifecycle, `/dev/shm` state-file freshness, consent + governance gates, and the four anchor smoking-gun symptoms currently visible on the stream.

**Constraint:** this doc is TO-VERIFY only. Alpha executes the live-check commands, ticks boxes, and files ❌ findings as individual hotfix PRs. Do not bundle fixes. Do not skip sections — a dormant wiring link is still a finding (⚠️).

---

## §0. How to use this doc

Alpha reads this top to bottom. For each item:

- Run the **live-check** command exactly as written.
- Mark the box:
  - `[x] ✅ wired-and-flowing` — the link produces the expected signal under current conditions
  - `[x] ⚠️ wired-but-dormant` — the code path is correctly wired but not firing (e.g. gating condition not currently satisfied). Record the gating condition in the inline note so we know what would have to change for it to fire
  - `[x] ❌ broken` — the link is either mis-wired, wired-but-unreachable, or produces the wrong signal. Open its own PR (branch name `wiring-fix/<topic>`)
- Commit incremental findings to `docs/research/2026-04-20-wiring-audit-findings.md` as each section completes. Do not wait until the whole audit is done.
- **Stop immediately** if any finding affects livestream integrity: live-egress, consent, face-obscure, demonetization risk, or operator audio drop. Ping operator, do not silently continue.
- Every ❌ finding gets its own commit + PR with a descriptive branch name. Do not cluster multiple findings in one fix.
- Budget: expect the audit to take one full alpha session. ~180 items, ~2-3 minutes per verify on average.

Notation:

- `SHM` = `/dev/shm/hapax-compositor/` unless qualified
- `STATE` = `~/hapax-state/`
- `INTENT` = `~/hapax-state/stream-experiment/director-intent.jsonl`
- Wards are enumerated from `config/compositor-layouts/default.json` (authoritative).

---

## §1. Visual surface wiring (ward render paths)

Every cairo source + external_rgba surface registered in `config/compositor-layouts/default.json`. Sources listed in the order they appear in the layout file. Each entry enumerates: class, layout binding, data inputs, render path, acceptance signal.

For each ward below, verify:

- (a) The `id` in `sources[]` has a matching `assignments[].source` entry
- (b) The `class_name` resolves via `agents/studio_compositor/cairo_sources/__init__.py::get_cairo_source_class`
- (c) The source appears in `SourceRegistry` at runtime (`curl -s http://localhost:9482/metrics | grep hapax_source_registry_registered`)
- (d) The CairoSourceRunner thread is alive (`ps -T -p $(pgrep -f studio-compositor) | grep -i <source_id>`)
- (e) The cached output surface mtime is fresh (`stat -c '%Y' /dev/shm/hapax-sources/<source_id>.rgba` if that publication path applies, else inspect the producer-specific SHM inputs listed below)
- (f) The ward writes a `ward-fx-events.jsonl` row on any draw-visible event (`tail -1 /dev/shm/hapax-compositor/ward-fx-events.jsonl | jq`)

### §1.1 `token_pole` (Vitruvian / token pole, 300×300)

- [ ] Class `TokenPoleCairoSource` resolves (grep `class TokenPoleCairoSource` in `agents/studio_compositor/token_pole.py`)
- [ ] Assignment binds `token_pole → pip-ul` in default layout
- [ ] Reads `SHM/token-ledger.json` (producer: `agents/token_ledger.py` or cost tracker — verify mtime < 60 s)
- [ ] Reads `SHM/homage-active-artefact.json` for package-accent colour selection
- [ ] Draws Vitruvian figure on every tick; arc length ↔ token budget remaining
- [ ] Acceptance signal: pixel at canvas centre (150,150) non-background on every tick
- [ ] `hapax_ward_fx_events_total{ward="token_pole"}` is monotonically increasing over a 5 min window

### §1.2 `album` (album cover + splattribution, 400×520)

- [ ] Class `AlbumOverlayCairoSource` resolves (`agents/studio_compositor/album_overlay.py::AlbumOverlayCairoSource`)
- [ ] Assignment binds `album → pip-ll` in default layout
- [ ] Reads `SHM/album-cover.png` (producer: hapax music-attribution flow — verify present and non-empty)
- [ ] Reads `SHM/music-attribution.txt` (same producer)
- [ ] `_vinyl_playing()` → `build_perceptual_field().vinyl_playing` returns True while turntable playing
- [ ] `_refresh_cover()` actually loads the PNG into `self._surface` on mtime change (add transient log or run the image loader standalone)
- [ ] `render_content()` composites cover + attribution + BitchX header + `_pip_fx_package` border on every tick
- [ ] `_pip_fx_package(cr, SIZE, SIZE, pkg)` renders scanlines, shadow, 2-px accent border without raising
- [ ] Acceptance signal (anchor #1 — the smoking gun): pixel sample at (canvas_x + 150, canvas_y + 430) (centre of cover) matches the cover colour palette, NOT transparent/black; border pixel at (canvas_x + 1, canvas_y + 151) matches `_domain_accent("album_overlay")` RGBA
- [ ] If acceptance fails, trace whether the PNG-loader returned None (log "Album cover load failed"), whether `_pip_fx_package` masked the cover to fully-transparent, or whether `pip-ll` surface geometry collapsed under layout scaling

### §1.3 `stream_overlay` (chat stats, 400×200)

- [ ] Class `StreamOverlayCairoSource` resolves
- [ ] Assignment binds `stream_overlay → pip-lr`
- [ ] Reads chat-metadata (producer: `agents/studio_compositor/chat_reactor.py` + Twitch IRC relay — verify JSON file / SHM fresh)
- [ ] Renders viewer count + keyword list at 2 Hz (`update_cadence: "rate"`, `rate_hz: 2.0`)
- [ ] Acceptance signal: SHM mtime on the cached rgba advances ≥1×/second

### §1.4 `sierpinski` (YouTube triangle, 640×640)

- [ ] Class `SierpinskiCairoSource` resolves (`agents/studio_compositor/sierpinski_renderer.py`)
- [ ] Layout binds `sierpinski → ` (NOT in current `assignments[]` — currently absent; verify by grep)
- [ ] IF unbound: is this intentional (the triangle renders via `fx_chain` pip_draw_from_layout path) or a layout regression? Note gating
- [ ] Reads `SHM/yt-frame-0.jpg`, `yt-frame-1.jpg`, `yt-frame-2.jpg` (producer: `scripts/youtube-player.py` ffmpeg -f image2 output)
- [ ] Reads `youtube_turn_taking.read_gate_state()` → skips non-active slots when `enabled=False`
- [ ] Acceptance signal: yt-frame-0.jpg mtime < 5 s when active slot = 0; yt-frame-1/2 mtime may be arbitrarily stale depending on turn-taking

### §1.5 `reverie` (wgpu render, 640×360, external_rgba)

- [ ] Kind = `external_rgba`, backend = `shm_rgba`, `shm_path: /dev/shm/hapax-sources/reverie.rgba`
- [ ] Assignment binds `reverie → pip-ur`
- [ ] Producer: `hapax-imagination.service` wgpu dynamic pipeline writes RGBA to the SHM
- [ ] Verify SHM file exists, size = 640×360×4 = 921600 bytes, mtime < 1 s (`stat -c '%Y %s' /dev/shm/hapax-sources/reverie.rgba`)
- [ ] External-rgba reader in compositor reads without tearing (spot-check: no partial-update artefacts in `SHM/fx-snapshot.jpg`)
- [ ] Acceptance signal: pixel variance across 10 s > 0 (reverie is temporal — if frozen, the wgpu writer is dead)

### §1.6 `activity_header` (activity header strip, 800×56, 2 Hz)

- [ ] Class `ActivityHeaderCairoSource` resolves (`legibility_sources.py::ActivityHeaderCairoSource`)
- [ ] Assignment binds `activity_header → activity-header-top`
- [ ] Reads activity classification (producer: `person_detector.py` or `contact_mic_ir.py`)
- [ ] Renders activity name + confidence at 2 Hz
- [ ] Acceptance: `hapax_ward_fx_events_total{ward="activity_header"}` advances

### §1.7 `stance_indicator` (stance badge, 100×40, 2 Hz)

- [ ] Class `StanceIndicatorCairoSource` resolves (`legibility_sources.py`)
- [ ] Assignment binds `stance_indicator → stance-indicator-tr`
- [ ] Reads `SHM/hapax-stimmung/current.json` → stance field
- [ ] Acceptance: stance name text changes when `hapax-working-mode` flips or when stance transitions (e.g. SEEKING, RESTING)
- [ ] Known accent colour: while `stance=seeking`, background fill matches `accent_yellow` of active package

### §1.8 `chat_ambient` (560×40, 2 Hz)

- [ ] Class `ChatAmbientWard` resolves (`chat_ambient_ward.py`)
- [ ] Assignment binds `chat_ambient → chat-legend-right`
- [ ] Reads Twitch chat tail via `chat_reactor.py`
- [ ] Acceptance: recent keyword cycles through in 30 s when chat is active

### §1.9 `grounding_provenance_ticker` (480×40, 2 Hz)

- [ ] Class `GroundingProvenanceTickerCairoSource` resolves (`legibility_sources.py`)
- [ ] Assignment binds `grounding_provenance_ticker → grounding-ticker-bl`
- [ ] Reads `INTENT` tail — specifically `grounding_provenance` field on last N compositional impingements
- [ ] Acceptance: text ticker scrolls keys like `audio.midi.beat_position`, `ir.ir_hand_zone.*`

### §1.10 `captions` (caption strip, 1920×120, 5 Hz)

- [ ] Class `CaptionsCairoSource` resolves (`captions_source.py`)
- [ ] Assignment binds `captions → captions_strip`
- [ ] Reads daimonion STT + TTS captions (producer: `hapax-daimonion.service` — check caption SHM)
- [ ] Acceptance: caption text present when operator speaks; alpha=0.9 per layout

### §1.11 `impingement_cascade` (480×360, 2 Hz, hothouse tag)

- [ ] Class `ImpingementCascadeCairoSource` resolves (`hothouse_sources.py:229`)
- [ ] Assignment binds `impingement_cascade → impingement-cascade-midright`
- [ ] Reads `/dev/shm/hapax-dmn/impingements.jsonl` tail
- [ ] Acceptance: rows stack visible during SEEKING / high-impingement pressure

### §1.12 `recruitment_candidate_panel` (800×60, 2 Hz, hothouse)

- [ ] Class `RecruitmentCandidatePanelCairoSource` resolves (`hothouse_sources.py:377`)
- [ ] Assignment binds `recruitment_candidate_panel → recruitment-candidate-top`
- [ ] Reads `SHM/recent-recruitment.json`
- [ ] Acceptance: top-3 recruited capabilities with score bars update within 10 s of a recruitment event

### §1.13 `thinking_indicator` (170×44, 6 Hz, hothouse)

- [ ] Class `ThinkingIndicatorCairoSource` resolves (`hothouse_sources.py:518`)
- [ ] Assignment binds `thinking_indicator → thinking-indicator-tr`
- [ ] Reads CPAL / daimonion "thinking" signal (SHM path — find in source)
- [ ] Acceptance: breathing dot pulses during LLM inference; freezes between

### §1.14 `pressure_gauge` (300×52, 2 Hz, hothouse)

- [ ] Class `PressureGaugeCairoSource` resolves (`hothouse_sources.py:608`)
- [ ] Assignment binds `pressure_gauge → pressure-gauge-ul`
- [ ] Reads stimmung pressure / stimulus-saturation signal
- [ ] Acceptance: 32-cell CP437 half-block bar fills 0 → 32 cells; cell count advances with stimmung impingement rate

### §1.15 `activity_variety_log` (400×140, 2 Hz, hothouse)

- [ ] Class `ActivityVarietyLogCairoSource` resolves (`hothouse_sources.py:732`)
- [ ] Assignment binds `activity_variety_log → activity-variety-log-mid`
- [ ] Reads recent activity classification history
- [ ] Acceptance: 6 emissive cells showing activity type cycling

### §1.16 `whos_here` (230×46, 2 Hz, hothouse)

- [ ] Class `WhosHereCairoSource` resolves (`hothouse_sources.py:872`)
- [ ] Assignment binds `whos_here → whos-here-tr`
- [ ] Reads `SHM/person-detection.json` → operator-count
- [ ] Acceptance: `[hapax:1/1]` when operator present; `[hapax:1/0]` when absent

### §1.17 `hardm_dot_matrix` (size TBV, 2 Hz, hothouse)

- [ ] Class `HardmDotMatrixCairoSource` resolves (`hardm_source.py:636`)
- [ ] Assignment binds `hardm_dot_matrix → hardm-dot-matrix-ur`
- [ ] Reads `SHM/hardm-cell-signals.json` + `SHM/hardm-emphasis.json`
- [ ] Acceptance: dot matrix cells illuminate from hardm emphasis cells

### §1.18 Cross-source checks

- [ ] No source_id collision — `jq '.sources[].id' config/compositor-layouts/default.json | sort | uniq -d` returns empty
- [ ] No surface_id collision — `jq '.surfaces[].id'` returns unique list (requires surfaces[] block — confirm present)
- [ ] Every `assignments[].source` matches an existing `sources[].id`
- [ ] Every `assignments[].surface` matches an existing `surfaces[].id` (layout file defines them in a block we did not cat here — verify)
- [ ] `SourceRegistry.registered_count` metric matches the `sources[]` array length
- [ ] No cairooverlay callback renders on the GStreamer streaming thread — verify via stack sampling `py-spy dump --pid $(pgrep -f studio-compositor) | grep -i cairo`

---

## §2. Audio routing wiring (end-to-end)

Walk every audio channel that enters or leaves the livestream. Names follow `config/pipewire/README.md` + `config/pipewire/*.conf`. The `hapax-livestream` sink is the broadcast egress — OBS captures it.

### §2.1 Operator voice — Rode Wireless Pro → livestream

- [ ] Rode Wireless Pro receiver USB-enumerated (`lsusb | grep -i rode`)
- [ ] Appears as PipeWire source named `hapax-operator-mic` (or similar — verify: `pactl list short sources | grep -i rode`)
- [ ] Routed into Studio 24c input X (verify `pw-dump | jq '.[] | select(.info.props["media.class"] == "Audio/Source")'`)
- [ ] 24c input X has +48V phantom if the mic needs it (confirm hardware switch)
- [ ] Voice-fx filter-chain installed (`ls ~/.config/pipewire/pipewire.conf.d/voice-fx-*.conf`)
- [ ] Filter-chain sink `hapax-voice-fx-capture` present (`pactl list short sinks | grep hapax-voice-fx`)
- [ ] `HAPAX_TTS_TARGET` env on `hapax-daimonion.service` = `hapax-voice-fx-capture` (`systemctl --user cat hapax-daimonion.service | grep HAPAX_TTS_TARGET`)
- [ ] Voice-fx monitor routes to `hapax-livestream` (verify loopback module or wireplumber policy)
- [ ] `hapax-livestream` sink exists (`pactl list short sinks | grep hapax-livestream`)
- [ ] OBS PipeWire capture bound to `hapax-livestream.monitor` (inspect OBS scene collection JSON)
- [ ] RTMP egress active — MediaMTX relay on `127.0.0.1:1935` (`ss -ltnp | grep 1935`)
- [ ] End-to-end test: operator speaks → VU meter on OBS capture moves → RTMP stream contains audio (`ffprobe -loglevel error -show_streams rtmp://127.0.0.1/live`)

### §2.2 Hapax TTS (Kokoro CPU) → livestream

- [ ] `hapax-daimonion.service` running (`systemctl --user is-active hapax-daimonion`)
- [ ] TTS invocation target resolves via `HAPAX_TTS_TARGET` env
- [ ] Kokoro process reads CPU only (`nvidia-smi --query-compute-apps=pid,process_name --format=csv | grep -v kokoro` — kokoro must NOT appear)
- [ ] TTS audio lands on `hapax-voice-fx-capture` sink
- [ ] Downstream monitor routes to `hapax-livestream` (same path as §2.1 operator voice)
- [ ] End-to-end test: trigger spontaneous utterance (e.g. `curl -X POST http://localhost:8051/api/daimonion/speak -d '{"text":"wiring-audit"}'`) and confirm audio on RTMP

### §2.3 Vinyl (turntable line-out) → livestream (SMOKING GUN #2)

- [ ] Turntable line-out physically connected to Studio 24c input Y
- [ ] 24c input Y gain staged appropriately (no +48V on a line-input)
- [ ] 24c default sink is `alsa_output.usb-PreSonus_Studio_24c...` (`pactl info | grep 'Default Sink'`)
- [ ] Vinyl mixes into 24c OUTPUT mix via the hardware mixer settings on the 24c (verify via UC Surface or 24c switches — USB return balance)
- [ ] **Verification per `config/pipewire/README.md` §"Vinyl-on-stream routing":** while vinyl plays, capture `@DEFAULT_MONITOR@` for 3 s → `ffprobe` reports non-silent RMS
- [ ] OBS PipeWire capture source ALSO reads the 24c output monitor — confirm OBS Audio Mixer shows meters moving on the 24c capture channel
- [ ] Find the actual routing: since `hapax-livestream` is the egress sink but the vinyl path described is "24c output mix → default sink", check whether `hapax-livestream` IS the default sink or whether OBS captures from BOTH `@DEFAULT_MONITOR@` and `hapax-livestream.monitor`
- [ ] Check `yt-over-24c-duck.conf` — if installed, vinyl must route through `hapax-24c-ducked` sink to receive duck gain changes; if not installed, confirm that is acceptable for the current session
- [ ] **Root cause trace for "vinyl playing but not audible on stream":** for each hop above, find the first one that fails. Most likely breakage points in order: (1) OBS scene not capturing the 24c monitor, (2) `hapax-livestream` sink has no loopback from default-sink monitor, (3) 24c USB return balance inverted, (4) vinyl strip not routed to 24c output mix at the hardware mixer.

### §2.4 YouTube audio (3 slots) → livestream (SMOKING GUN #3)

- [ ] `scripts/youtube-player.py` spawns 3 `VideoSlot` ffmpegs (`pgrep -af 'ffmpeg.*youtube\|ffmpeg.*yt-' | wc -l` == 3)
- [ ] Each slot creates a Pulse sink-input named `youtube-audio-{0,1,2}` (`pactl list short sink-inputs | grep youtube-audio`)
- [ ] Each sink-input routes to... where exactly? Trace via `pw-dump | jq '.[] | select(.info.props."media.name" | startswith("youtube-audio-"))'` → find parent sink
- [ ] If parent sink = default sink (24c) → YT audio enters 24c output mix → competes with vinyl for the 24c monitor feed
- [ ] If parent sink = `hapax-ytube-ducked` → subject to `AudioDuckingController` gain (CVS #145)
- [ ] `SlotAudioControl.mute_all_except(active_slot)` called once at `director_loop.start()` line 919 against the slots present at startup
- [ ] **Root cause trace for "three YouTube ffmpegs simultaneously audible":** on fresh ffmpeg restart (e.g. slot 1 finishes a video, spawns a new ffmpeg), the new sink-input ID comes up at volume=1.0 — but `mute_all_except` was already called before it existed. `discover_node` uses `pw-dump` cache that is invalidated on `wpctl` failure, not on new-node-appear. Verify: kill slot 1 ffmpeg, `pactl list sink-inputs | grep youtube-audio-1 | awk '{print $2}'` → volume should be 0.0 after re-spawn if wiring works; likely shows 1.0 (broken)
- [ ] Confirm `youtube_turn_taking.read_gate_state()` is called at every director tick (grep `read_gate_state` in `director_loop.py`) — if it is ONLY referenced in `sierpinski_renderer` but not in the audio path, the D2 gate never affects audio
- [ ] Confirm `SlotAudioControl.mute_all_except` is called on EVERY tick (not once at startup) OR there is a sink-input-added watcher that re-mutes new inputs
- [ ] Check `director_loop._loop` for a periodic `self._audio_control.mute_all_except(self._active_slot)` call — if absent, that is the wiring gap

### §2.5 Contact mic (Cortado MKIII) — perception-only

- [ ] Cortado MKIII wired to Studio 24c input 2 with +48V
- [ ] PipeWire source named "Contact Microphone" (`pactl list short sources | grep -i Contact`)
- [ ] `agents/hapax_daimonion/backends/contact_mic.py` opens `pw-cat --record --target "Contact Microphone"` subprocess
- [ ] Raw audio NOT routed to any sink that flows to `hapax-livestream` (invariant — verify `pw-dump` shows no link from Contact Mic to 24c output mix, `hapax-livestream`, or any loopback sink that merges into egress)
- [ ] DSP output writes to `SHM/hapax-contact_mic/` for VLA consumption (list SHM to confirm files present)
- [ ] `contact_mic_ir.py::_classify_activity_with_ir()` consumes DSP output + IR hand zone
- [ ] Classified activity writes to `presence_engine.py::PresenceEngine` as `desk_active` / `desk_activity`
- [ ] Regression guard: audio of a finger tap on the contact mic MUST NOT appear in the RTMP stream (tap + `ffprobe` capture → no high-frequency tap visible in RMS envelope)

### §2.6 Audio ducking (AudioDuckingController) (SMOKING GUN #4)

- [ ] `AudioDuckingController` instantiated at `lifecycle.py:163` — `compositor._audio_ducking = AudioDuckingController()`
- [ ] `.start()` called at `lifecycle.py:164` — daemon thread `AudioDuckingController` running (`ps -T | grep AudioDucking`)
- [ ] VAD reader `vad_ducking._read_vad_state` returns a bool when `VOICE_STATE_FILE` (`SHM/voice-state.json`) exists
- [ ] `publish_vad_state` called from `agents/hapax_daimonion/vad_state_publisher.py` at 30 ms cadence while daimonion is running — confirm `stat -c '%Y.%N' /dev/shm/hapax-compositor/voice-state.json` advances when operator speaks
- [ ] YT audio reader `read_yt_audio_active` checks `SHM/yt-audio-state.json`
- [ ] **Who writes `yt-audio-state.json`?** The in-tree `set_yt_audio_active` is only defined, never called (verified via grep: `set_yt_audio_active` appears only in `audio_ducking.py`). There is NO producer. The ducker's YT signal is permanently None → `yt_active` permanently False → state permanently NORMAL. This is the root cause of "ducking metric stuck at normal=1".
- [ ] Fix path: either (a) add a level-monitor thread on the `hapax-ytube-ducked` sink that calls `set_yt_audio_active(level > threshold)` at ~10 Hz, OR (b) swap the YT reader to "is ffmpeg alive on any slot" heuristic, OR (c) hook `SlotAudioControl.discover_node` to publish state when at least one slot sink-input has non-zero volume
- [ ] `HAPAX_AUDIO_DUCKING_ACTIVE=1` env set on the compositor unit (`systemctl --user show studio-compositor -p Environment | grep HAPAX_AUDIO_DUCKING_ACTIVE`). If unset, even correct state transitions produce no gain changes.
- [ ] `hapax-ytube-ducked` and `hapax-24c-ducked` sinks exist (`pactl list short sinks | grep -E 'hapax-(ytube|24c)-ducked'`) — if the configs were never `cp`ed into `~/.config/pipewire/pipewire.conf.d/` and PipeWire restarted, the sinks do not exist and the dispatcher silently no-ops
- [ ] `wpctl set-volume @hapax-ytube-ducked@ 0.5` succeeds at the shell (dry-run check — restore 1.0 after)
- [ ] `metrics.set_audio_ducking_state(state)` emits the gauge on transition — confirm Prometheus scrape: `curl -s localhost:9482/metrics | grep hapax_audio_ducking_state`
- [ ] End-to-end test once the producer is wired: start YT, observe `yt_active=1`, start speaking, observe `both_active=1`

### §2.7 Audio observability

- [ ] `hapax_audio_ducking_state{state="normal"}`, `{state="voice_active"}`, `{state="yt_active"}`, `{state="both_active"}` all exist as time series in Prometheus (query `hapax_audio_ducking_state`)
- [ ] Transitions over a 1 min window: during normal operation the series should toggle, not stick at 1 for `normal`
- [ ] `hapax_slot_audio_volume{slot="0"|"1"|"2"}` metric — if SlotAudioControl publishes it (verify via grep), confirm all 3 series are emitted and obey `mute_all_except(active)`

---

## §3. Impingement ⇄ pipeline wiring

Every producer of impingements + every consumer + the cursor wiring for each.

### §3.1 Impingement producers

- [ ] **DMN** writes to `/dev/shm/hapax-dmn/impingements.jsonl` — verify mtime < 5 s when DMN active
- [ ] **VLA (visual-layer-aggregator)** writes to `/dev/shm/hapax-visual/` with perception/stimmung signals — verify
- [ ] **Contact mic** writes classified activity via `contact_mic_ir.py` → fed into presence engine; confirm `SHM/hapax-contact_mic/` content
- [ ] **IR perception (3 Pi)** writes to `~/hapax-state/pi-noir/{role}.json` (ir-desk, ir-room, ir-overhead) — verify all three exist, mtime < 10 s per `check_pi_fleet()`
- [ ] **Daimonion** emits impingements via CPAL loop → `/dev/shm/hapax-dmn/impingements.jsonl`
- [ ] **CPAL** — CpalRunner.process_impingement writes back via daimonion aux loop
- [ ] **Director (compositional)** — writes `INTENT` as `DirectorIntent` with `compositional_impingements[]` carrying `intent_family` tags
- [ ] Verify no second, ghost JSONL path — should be exactly one canonical `/dev/shm/hapax-dmn/impingements.jsonl` + one `INTENT`

### §3.2 Impingement consumer cursors

- [ ] Daimonion CPAL consumer cursor at `impingement-cursor-daimonion-cpal.txt` (find exact path; likely `/dev/shm/hapax-daimonion/`)
- [ ] Daimonion affordance consumer cursor at `impingement-cursor-daimonion-affordance.txt`
- [ ] Reverie consumer uses `start_at_end=True` (stale visuals meaningless) — verify via `shared/impingement_consumer.py`
- [ ] Fortress consumer has cursor_path set (missing cursor = correctness bug per CLAUDE.md)
- [ ] Cursor files advance — `stat -c '%Y' <cursor_file>` should update under load

### §3.3 Affordance pipeline surfaces

- [ ] Qdrant `affordances` collection exists (`curl -s http://localhost:6333/collections/affordances | jq`)
- [ ] Every capability in `shared/compositional_affordances.py` has a row in the `affordances` collection (count via `curl -s http://localhost:6333/collections/affordances/points/count | jq`)
- [ ] Each row has `embedding` (1024-dim nomic-embed output)
- [ ] Each row has `base_level` (0.0–1.0)
- [ ] Each row has `thompson_posterior` (Beta(α, β) parameters)
- [ ] Activation state persisted — `~/hapax-state/affordance-activation-state.json` exists (find exact filename), mtime advances within 60 s windows
- [ ] Consent-required capabilities filtered out of `AffordancePipeline.select()` when no active contract (verify via `shared/governance/consent_gate.py::check`)

### §3.4 Recruitment outputs by modality

- [ ] **auditory** — daimonion speaks capability; trace from recruited capability → CPAL speech queue
- [ ] **visual** — ward-property write; trace from recruited capability → `SHM/ward-properties.json` delta
- [ ] **textual** — caption / overlay text; trace from recruited capability → `captions_source` or `overlay_zones`
- [ ] **notification** — ntfy push; trace from recruited capability → `shared/notify.py::send_notification`
- [ ] **studio-control** — studio-compositor state mutation (camera.hero, preset.bias, youtube.direction); trace via `compositional_consumer.py`

### §3.5 Anti-personification gate

- [ ] `scripts/lint_personification.py` exists and is runnable (`uv run python scripts/lint_personification.py --help`)
- [ ] Gate is wired into CI (`.github/workflows/*.yml` contains a step that runs it)
- [ ] Gate is wired into a pre-commit hook OR a claude-code Edit hook (`hooks/scripts/` or `.git/hooks/pre-commit`)
- [ ] Running the linter over the current tree reports zero violations

---

## §4. Director intent_family → consumer wiring

`IntentFamily` literal from `shared/director_intent.py:68` enumerates every valid family. For each, confirm emitter → consumer → observable effect.

### §4.1 `camera.hero` → `CameraHeroConsumer`

- [ ] Emitter: `director_loop.py` narrative director emits `CompositionalImpingement(intent_family="camera.hero", narrative=..., grounding_provenance=[...])`
- [ ] Consumer: `compositional_consumer.py` dispatches to hero-camera override writing `SHM/hero-camera-override.json`
- [ ] Effect: main-layer camera input switches within 1 tick
- [ ] Verification: `tail -n 1 INTENT | jq '.compositional_impingements[] | select(.intent_family == "camera.hero")'` after a hero move; `cat /dev/shm/hapax-compositor/hero-camera-override.json` shows new camera id
- [ ] Metric: `hapax_director_compositional_impingement_total{family="camera.hero"}` increments

### §4.2 `preset.bias`

- [ ] Emitter: director_loop (structural tick) + chat_reactor (viewer keyword)
- [ ] Consumer: `PresetReactor` reads + writes `graph-mutation.json` with 30 s cooldown
- [ ] Effect: reverie mixer reads graph-mutation on next rebuild tick
- [ ] Acceptance: preset name change visible in `SHM/fx-current.txt` (currently shows the active preset — verify)

### §4.3 `overlay.emphasis`

- [ ] Emitter: director_loop `intent_family="overlay.emphasis"` (`director_loop.py:46`)
- [ ] Consumer: `compositional_consumer.py` maps target → ward_id via `_OVERLAY_TARGET_TO_WARD_ID` (line 311)
- [ ] Effect: `SHM/ward-properties.json` gains an entry `{ward_id: {emphasis: true, until: ts}}`
- [ ] Acceptance: ward renders with emphasis treatment (brighter accent, border, or packagedefined effect)

### §4.4 `youtube.direction`

- [ ] Emitter: director_loop compositional tick
- [ ] Consumer TWO paths:
  - (a) `director_loop._honor_youtube_direction()` reads `SHM/youtube-direction.json` and rotates slot / pauses
  - (b) `youtube_turn_taking.read_gate_state()` independent read-only tail-scan of `INTENT`
- [ ] Effect: slot rotation + slot audio mute + sierpinski per-corner opacity
- [ ] **Wiring gap (D2, read-only):** `youtube_turn_taking` is NOT actually called from the audio path. Verify: `grep -n youtube_turn_taking agents/studio_compositor/director_loop.py`. If 0 hits, the gate is dead code in the audio path.
- [ ] Metric: `hapax_director_compositional_impingement_total{family="youtube.direction"}`

### §4.5 `attention.winner`

- [ ] Emitter: biased-competition salience resolver
- [ ] Consumer: stance / ward emphasis dispatcher
- [ ] Effect: TBD — trace end-to-end

### §4.6 `stream_mode.transition`

- [ ] Emitter: operator command or structural director
- [ ] Consumer: `SHM/stream-mode-intent.json` writer → compositor state machine
- [ ] Effect: livestream mode switches (research / rnd / fortress)

### §4.7 `ward.size` / `ward.position` / `ward.staging` / `ward.highlight` / `ward.appearance` / `ward.cadence` / `ward.choreography`

For each `ward.*` family:

- [ ] Emitter in director_loop / structural_director
- [ ] Consumer maps ward_id (must match `shared/director_intent.py::WardId` literal) → ward-properties write or animation_engine entry
- [ ] Effect on that specific ward's render (size scaling, position delta, staged appearance, highlight accent, appearance filter, cadence rate_hz change, choreography transition)
- [ ] Unknown ward_id → dispatched to nothing (defensive); verify no KeyError raised
- [ ] `hapax_ward_fx_events_total{ward=<id>, intent_family=<family>}` increments on dispatch

### §4.8 HOMAGE framework families

For each of `homage.rotation`, `homage.emergence`, `homage.swap`, `homage.cycle`, `homage.recede`, `homage.expand`:

- [ ] Emitter in narrative director
- [ ] Consumer: `agents/studio_compositor/homage/choreographer.py` reads `SHM/homage-pending-transitions.json`
- [ ] Effect: package active flip (BitchX → consent-safe or vice-versa), active-artefact swap, or substrate-package change
- [ ] `hapax_homage_transition_total{kind=<family>}` increments
- [ ] `hapax_homage_choreographer_rejection_total{reason=<X>}` remains low (concurrency collisions only)

### §4.9 Cross-family invariants

- [ ] Every emitted `CompositionalImpingement` has a non-empty `grounding_provenance` OR an UNGROUNDED audit warning logged
- [ ] `hapax_director_intent_parse_failure_total` stays at 0 during live operation
- [ ] `hapax_director_vacuum_prevented_total` increments when the director would have emitted nothing
- [ ] Every `intent_family` string used in the codebase is a member of the `IntentFamily` literal (grep+comparison):
  `grep -rhn 'intent_family\s*=\s*"' agents/ | grep -oE '"[a-z.]+"' | sort -u`
  vs the Literal members in `shared/director_intent.py:68-94`

---

## §5. Observability wiring

Every `hapax_*` metric. Definition site → emit site(s) → scrape freshness.

### §5.1 Director observability (`shared/director_observability.py`)

For each metric, verify: defined, emitted at least once in the last hour, label cardinality bounded.

- [ ] `hapax_director_intent_total` (Counter)
- [ ] `hapax_director_grounding_signal_used_total` (Counter, label: signal key)
- [ ] `hapax_director_compositional_impingement_total` (Counter, label: intent_family)
- [ ] `hapax_director_twitch_move_total` (Counter)
- [ ] `hapax_director_structural_intent_total` (Counter)
- [ ] `hapax_director_llm_latency_seconds` (Histogram)
- [ ] `hapax_director_intent_parse_failure_total` (Counter) — must stay 0 under normal ops
- [ ] `hapax_director_vacuum_prevented_total` (Counter)
- [ ] `hapax_random_mode_pick_total` (Counter)

### §5.2 HOMAGE observability

- [ ] `hapax_homage_package_active` (Gauge, label: package name)
- [ ] `hapax_homage_transition_total` (Counter, label: kind)
- [ ] `hapax_homage_choreographer_rejection_total` (Counter, label: reason)
- [ ] `hapax_homage_choreographer_substrate_skip_total` (Counter)
- [ ] `hapax_homage_violation_total` (Counter, label: violation-kind) — must stay 0
- [ ] `hapax_homage_signature_artefact_emitted_total` (Counter)
- [ ] `hapax_homage_emphasis_applied_total` (Counter, label: ward, intent_family)
- [ ] `hapax_homage_render_cadence_hz` (Gauge, label: ward)
- [ ] `hapax_homage_rotation_mode` (Gauge, enum)
- [ ] `hapax_homage_active_package` (Gauge, label: name)
- [ ] `hapax_homage_substrate_saturation_target` (Gauge)

### §5.3 Compositor observability

- [ ] `hapax_audio_ducking_state` (Gauge, label: state) — SMOKING GUN #4; currently stuck `normal=1`
- [ ] `hapax_imagination_shader_rollback_total` (Counter)
- [ ] `hapax_face_obscure_frame_total` (Counter, label: camera_role, has_faces)
- [ ] `hapax_face_obscure_errors_total` (Counter, label: camera_role, exception_class)
- [ ] `hapax_compositor_nondestructive_clamps_total` (Counter)
- [ ] `hapax_follow_mode_cuts_total` (Counter)
- [ ] `hapax_director_degraded_holds_total` (Counter)
- [ ] `hapax_ward_fx_events_total` (Counter, label: ward, intent_family)
- [ ] `hapax_ward_fx_latency_seconds` (Histogram, label: ward)

### §5.4 HARDM observability

- [ ] `hapax_hardm_salience_bias` (Gauge)
- [ ] `hapax_hardm_emphasis_state` (Gauge)
- [ ] `hapax_hardm_operator_cue_total` (Counter)

### §5.5 Audit dispatcher

- [ ] `hapax_audit_enqueued_total` (Counter)
- [ ] `hapax_audit_completed_total` (Counter)
- [ ] `hapax_audit_dropped_total` (Counter, label: reason — backpressure should be rare)

### §5.6 Scrape surface

- [ ] Prometheus scrape endpoint `127.0.0.1:9482/metrics` responds (`curl -s localhost:9482/metrics | head -5`)
- [ ] Grafana dashboard "reverie-predictions" loads at `localhost:3001/d/reverie-predictions/`
- [ ] Label cardinality under 10k per metric (Prometheus cardinality check)
- [ ] No metrics with free-form operator text / transcript content (privacy axiom)

---

## §6. systemd service lifecycle wiring

For each user unit, verify dependency chain + restart + env + healthcheck.

### §6.1 `hapax-secrets.service` (oneshot, foundation)

- [ ] `Type=oneshot`
- [ ] `RemainAfterExit=yes`
- [ ] Loads credentials into environment files under `~/.cache/hapax/secrets.env` (or similar)
- [ ] All downstream services declare `Requires=hapax-secrets.service` + `After=hapax-secrets.service`

### §6.2 `logos-api.service` (FastAPI :8051)

- [ ] `Requires=hapax-secrets.service`
- [ ] Listens on `:8051` (`ss -ltnp | grep 8051`)
- [ ] `curl -s localhost:8051/api/health` returns 200
- [ ] `Restart=always` + `RestartSec=<small>`

### §6.3 `studio-compositor.service`

- [ ] `Type=notify`
- [ ] `WatchdogSec=60s`
- [ ] `Restart=always`
- [ ] Dependencies: hapax-secrets, PipeWire user session
- [ ] `EnvironmentFile=` includes `HAPAX_AUDIO_DUCKING_ACTIVE` setting (verify — if missing, the ducker silently runs in dry-mode per §2.6)
- [ ] `HAPAX_TTS_TARGET` not needed here (that's for daimonion)
- [ ] Prometheus endpoint on `127.0.0.1:9482`
- [ ] Responds to systemd watchdog sdnotify within 60 s
- [ ] `rebuild-service.sh --watch` paths include `agents/studio_compositor/**` + `shared/compositor_model.py` + `shared/director_intent.py`

### §6.4 `hapax-daimonion.service`

- [ ] `Requires=hapax-secrets.service`
- [ ] `HAPAX_TTS_TARGET=hapax-voice-fx-capture` in Environment
- [ ] Kokoro TTS pinned to CPU (`CUDA_VISIBLE_DEVICES=""` in the unit OR Kokoro config pins to CPU)
- [ ] STT on GPU — verify via `nvidia-smi --query-compute-apps=process_name --format=csv` shows daimonion/whisper
- [ ] Publishes VAD state to `SHM/voice-state.json` via `vad_state_publisher`
- [ ] `rebuild-service.sh --watch` paths include `agents/hapax_daimonion/**`

### §6.5 `hapax-dmn.service`

- [ ] Running (`systemctl --user is-active`)
- [ ] Writes `/dev/shm/hapax-dmn/impingements.jsonl` and `current.json` continuously
- [ ] Publishes to the 9-dim uniform slots via `current.json` → `StateReader.imagination.dimensions`

### §6.6 `visual-layer-aggregator.service`

- [ ] Running
- [ ] Reads perception signals + stimmung + DMN
- [ ] Writes to `/dev/shm/hapax-visual/` and `/dev/shm/hapax-stimmung/current.json`
- [ ] Exploration signal fed from `/dev/shm/hapax-exploration/`

### §6.7 `hapax-imagination.service`

- [ ] Running
- [ ] Writes `/dev/shm/hapax-sources/reverie.rgba` (640×360×4 bytes)
- [ ] Reads `/dev/shm/hapax-imagination/uniforms.json` (≥44 keys per CLAUDE.md invariant)
- [ ] Reads `/dev/shm/hapax-imagination/pipeline/*.json` for hot-reload
- [ ] `hapax-imagination-loop.service` also running (continuous imagination generator)

### §6.8 `hapax-content-resolver.service`

- [ ] Running
- [ ] Resolves content recruitments from affordance pipeline
- [ ] Writes content SHM outputs (identify which files)

### §6.9 `hapax-watch-receiver.service`

- [ ] Running
- [ ] Endpoint on logos API (`/api/biometrics` or similar) accepts Wear OS POSTs
- [ ] Receives biometric data from watch (verify recent timestamp on latest batch)

### §6.10 `hapax-logos.service`

- [ ] Running (Tauri app — systemd unit for auto-start)
- [ ] `__NV_DISABLE_EXPLICIT_SYNC=1` in Environment (webkit2gtk Wayland bug workaround)
- [ ] Command registry reachable at `ws://localhost:8052/ws/commands`
- [ ] Frame server on `:8053` serves JPEG frames for `VisualSurface`

### §6.11 Timers

- [ ] `hapax-rebuild-services.timer` firing every 5 min
- [ ] `hapax-rebuild-logos.timer` firing (detaches worktree per CLAUDE.md caveat)
- [ ] `hapax-sprint-tracker.timer` (5 min)
- [ ] `hapax-backup-local.timer` + `hapax-backup-remote.timer`
- [ ] `hapax-queue-gc.timer`
- [ ] `hapax-reverie-monitor.timer`
- [ ] `hapax-vision-observer.timer`
- [ ] `hapax-hardm-publisher.timer`
- [ ] Every timer's last-trigger time within its expected cadence (`systemctl --user list-timers`)

### §6.12 Rebuild discipline

- [ ] `rebuild-service.sh` refuses to deploy from a feature branch (per CLAUDE.md)
- [ ] `flock -n` on `$STATE_DIR/lock` prevents concurrent runs — verify lockfile exists at expected path
- [ ] Rebuild completion ntfy published to `ntfy.hapax-rebuild` topic

---

## §7. `/dev/shm` state-file freshness audit

Every file in `SHM`. Producer + consumer + expected freshness + current state.

For each file below, run `stat -c '%Y %s %n' <path>` and assess against expected freshness:

### §7.1 Producer-cadence SHM files (should be fresh within seconds)

- [ ] `SHM/album-cover.png` — produced by music-attribution flow; fresh when vinyl playing
- [ ] `SHM/album-state.json` — same producer
- [ ] `SHM/music-attribution.txt` — same
- [ ] `SHM/brio-operator.jpg` / `brio-room.jpg` / `brio-synths.jpg` — 3 BRIO camera snapshots; producer: `studio-person-detector.service` or camera-pipeline (expected < 1 s)
- [ ] `SHM/c920-desk.jpg` / `c920-overhead.jpg` / `c920-room.jpg` — 3 C920 camera snapshots
- [ ] `SHM/snapshot.jpg` + `smooth-snapshot.jpg` — compositor main output snapshots (< 1 s)
- [ ] `SHM/fx-snapshot.jpg` — post-fx snapshot (< 1 s)
- [ ] `SHM/fx-current.txt` — active preset name (changes on preset.bias)
- [ ] `SHM/ward-properties.json` — ward state (updates on any overlay.emphasis dispatch)
- [ ] `SHM/ward-animation-state.json` — animation engine state (< 5 s)
- [ ] `SHM/ward-fx-events.jsonl` — event log, tails behind ward-properties updates
- [ ] `SHM/yt-frame-0.jpg` / `yt-frame-1.jpg` / `yt-frame-2.jpg` — YT snapshots per slot
- [ ] `SHM/yt-attribution-0.txt` / `1.txt` / `2.txt` — per-slot attribution
- [ ] `SHM/homage-active-artefact.json` — active artefact; updates on homage transitions
- [ ] `SHM/homage-substrate-package.json` — active package (BitchX vs consent-safe)
- [ ] `SHM/homage-pending-transitions.json` — choreographer queue
- [ ] `SHM/homage-voice-register.json` — TTS voice register for package
- [ ] `SHM/hapax-dmn/impingements.jsonl` — DMN impingement stream (should advance during SEEKING)
- [ ] `SHM/hapax-dmn/current.json` — 9-dim state (< 1 s)
- [ ] `SHM/hapax-stimmung/current.json` — stimmung snapshot (< 1 s)
- [ ] `SHM/hapax-visual/frame.jpg` — wgpu frame for VisualSurface (< 0.1 s at 10 fps)
- [ ] `SHM/hapax-sources/reverie.rgba` — reverie RGBA for external_rgba source (< 0.1 s at 30 fps)
- [ ] `SHM/hapax-imagination/uniforms.json` — GPU uniforms (≥44 keys; updates on visual-chain tick)
- [ ] `SHM/hapax-exploration/*.json` — 13 components publishing boredom/curiosity
- [ ] `SHM/voice-state.json` (at `SHM/voice-state.json` → `hapax-compositor/voice-state.json` exact path per `vad_ducking.VOICE_STATE_FILE`) — VAD state (30 ms cadence while daimonion active)
- [ ] `SHM/yt-audio-state.json` — YT audio activity (SMOKING GUN #4; currently absent, no producer — verify `ls SHM/yt-audio-state.json` fails)
- [ ] `SHM/consent-state.txt` — active consent contract set

### §7.2 Slow-cadence SHM files (> 1 min acceptable)

- [ ] `SHM/camera-classifications.json` — person-detector output
- [ ] `SHM/color-resonance.json` — visual chain resonance
- [ ] `SHM/costs.json` — LLM cost ledger
- [ ] `SHM/degraded.json` — degraded signal for budget tracker
- [ ] `SHM/follow-mode-recommendation.json` — follow-mode state
- [ ] `SHM/hardm-cell-signals.json` / `hardm-emphasis.json` — HARDM publisher timer output (cadence per timer)
- [ ] `SHM/health.json` — health monitor output
- [ ] `SHM/hero-camera-override.json` — camera.hero dispatch target
- [ ] `SHM/hls-analysis.json` — HLS analyzer
- [ ] `SHM/last-ntfy-<cam>.txt` — ntfy dedup for brio/c920 cameras
- [ ] `SHM/memory-snapshot.json` — director memory snapshot
- [ ] `SHM/narrative-structural-intent.json` — structural director output
- [ ] `SHM/operator-sidechat.jsonl` — operator chat log
- [ ] `SHM/overlay-alpha-overrides.json` — per-ward alpha override
- [ ] `SHM/person-detection.json` — person detector output
- [ ] `SHM/playlist.json` — YT playlist cache
- [ ] `SHM/recent-recruitment.json` — last recruitment result
- [ ] `SHM/research-marker.json` — research marker state
- [ ] `SHM/stream-mode-intent.json` — stream_mode.transition dispatch target
- [ ] `SHM/token-ledger.json` — token budget ledger
- [ ] `SHM/unified-reactivity.json` — reactivity engine state
- [ ] `SHM/visual-layer-state.json` — VLA state snapshot
- [ ] `SHM/watershed-events.json` — watershed event log
- [ ] `SHM/correction-question.json` — operator correction state

### §7.3 Staleness triage rule

For each stale file (mtime older than 2× its expected cadence):

- [ ] Is the producer service running? (`systemctl --user status <unit>`)
- [ ] Did the producer recently crash? (`journalctl --user -u <unit> --since '1 hour ago' | grep -iE 'error|exception|crash'`)
- [ ] Is the consumer silently tolerating the staleness or hard-failing?
- [ ] Record finding as ⚠️ (dormant) or ❌ (broken)

---

## §8. Consent + governance wiring

### §8.1 Consent gate (non-visual capabilities)

- [ ] `shared/governance/consent_gate.py::check` fires when capability has `consent_required=True`
- [ ] Active contracts live in `axioms/contracts/` — list `ls axioms/contracts/*.yaml`
- [ ] `ConsentRegistry.load()` reads all contracts at import
- [ ] `AffordancePipeline.select()` calls the gate BEFORE returning capabilities (verify order)
- [ ] Cache TTL 60 s — if expired contract removed, capability gated within 60 s
- [ ] Every capability declaring `consent_required=True` in `shared/compositional_affordances.py` has a cross-check here

### §8.2 Face-obscure (visual privacy, #129)

- [ ] `FACE_OBSCURE_ENABLED` env set (`systemctl --user show studio-compositor -p Environment | grep FACE_OBSCURE`) — expected `1` during live stream
- [ ] `FACE_OBSCURE_POLICY` env set to `ALWAYS_OBSCURE` or `OBSCURE_NON_OPERATOR`
- [ ] `obscure_frame_for_camera` called in capture path BEFORE any tee (verify via grep in `camera_pipeline.py` / `snapshots.py`)
- [ ] Fail-closed path: inject a simulated ScrfdFaceBboxSource failure → confirm full-frame Gruvbox mask, not raw frame
- [ ] `hapax_face_obscure_errors_total` counter increments when fail-closed fires
- [ ] SCRFD model file present (`ls ~/.local/share/hapax/models/scrfd*.onnx`)
- [ ] No bypass path — every pixel that reaches `/dev/video42`, RTMP, HLS, or V4L2 loopback has gone through `obscure_frame_for_camera`

### §8.3 Legacy consent-safe gate (egress layout swap, disabled by default)

- [ ] `HAPAX_CONSENT_EGRESS_GATE` unset or `0` (default — face-obscure is the canonical gate)
- [ ] IF set to `1`, `agents/studio_compositor/consent_live_egress.py` activates; verify layout swap fires on consent transition
- [ ] Otherwise, confirm the gate is DISABLED and face-obscure owns visual privacy

### §8.4 Anti-personification

- [ ] `scripts/lint_personification.py` runs in CI
- [ ] Pre-commit hook blocks commits that add personification strings (`hapax is`, `my feelings`, etc.)
- [ ] Spot-check: grep for forbidden phrases in all director prompts and overlay content

### §8.5 Axiom registry

- [ ] `axioms/registry.yaml` reflects post-2026-04-18 merge (5 axioms: 3 constitutional, 2 domain)
- [ ] `shared/axiom_*.py` modules import correctly
- [ ] `axiom-commit-scan.sh` hook blocks commit messages matching T0 violation patterns
- [ ] `/axiom-check` skill runs without errors

### §8.6 Per-author state in chat_reactor

- [ ] `PresetReactor` records no per-author state (verify: no `{author: ...}` dict anywhere in chat_reactor.py)
- [ ] No author strings in logs (`caplog` test enforced — confirm test exists)
- [ ] 30 s cooldown per-preset, not per-author

### §8.7 CODEOWNERS

- [ ] `CODEOWNERS` file covers `axioms/**`, `shared/consent*.py`, `shared/axiom_*.py`, `hooks/**`
- [ ] Branch protection on main requires CODEOWNERS review for these paths

---

## §9. Specific smoking-gun root-cause paths

Each of the four anchor symptoms gets a section: (a) the exact file:line where the break is likely occurring, (b) the dataflow as it currently exists, (c) the dataflow as it should exist, (d) minimal fix delta.

### §9.1 Anchor #1 — Album cover not rendering on stream

**Likely-break sites** (bisect):

- [ ] **`album_overlay.py:263-266`** — `self._vinyl_playing()` fails to True → `_refresh_cover()` not called. Fallback is fail-open (returns True on exception) but `build_perceptual_field()` may fail silently AND `_refresh_cover` may have been skipped from a prior tick where `_vinyl_playing` correctly returned False
- [ ] **`album_overlay.py:267`** — `self._surface is None` short-circuit returns before drawing. If `get_image_loader().load(COVER_PATH)` returns None (PIL failure, corrupt PNG, permissions), the ward renders nothing
- [ ] **`album_overlay.py:278-286`** — cover is composited at `(0, TEXT_BUFFER)` translated; if `pip-ll` surface dimensions don't match `CANVAS_W × CANVAS_H (300 × 450)`, the `cr.scale(scale, scale)` with `scale = SIZE / max(sw, sh)` may collapse
- [ ] **`album_overlay.py:293`** — `_pip_fx_package(cr, SIZE, SIZE, pkg)` renders AFTER the cover. The `_pip_fx_package` function paints scanlines + shadow + border in sequence, each `cr.save/restore`-wrapped. IF the scanline fill at α=0.18 looks transparent-but-present, and the shadow mask at α=0.22 looks dithered — but the BORDER is at full α — then we'd expect to see AT LEAST a 2-px accent border rectangle at the cover bounds. If we don't see the border either, the `cr.stroke()` call failed or the runner's output surface isn't being blit to pip-ll at all

**Dataflow as it should exist:**

```
music-attribution-flow
  → SHM/album-cover.png (producer writes fresh PNG on track change)
  → AlbumOverlayCairoSource._refresh_cover (loads via image_loader)
  → self._surface (cairo.ImageSurface)
  → render_content(cr, 300, 450)
      → _draw_attrib(cr)  # text above
      → cr.set_source_surface(self._surface) + cr.paint_with_alpha(0.85)  # cover
      → _pip_fx_package(cr, 300, 300, pkg)  # scanlines + shadow + 2-px border
  → CairoSourceRunner caches output ARGB32 surface
  → fx_chain.pip_draw_from_layout blits → pip-ll surface on main-layer fx_chain_input pad
  → GL texture → /dev/video42
```

**Dataflow as it currently exists** (hypothesis, alpha to verify):

- PNG fresh (confirmed: 253 KB, mtime 10:19)
- `_refresh_cover` may have failed silently at the PIL import or image_loader call
- `self._surface` is None → early-return at 267 → blank pip-ll

**Minimal fix delta** (DO NOT IMPLEMENT — alpha writes PR):

- Add a TRACE-level log at `_refresh_cover` start + end that always emits, including the mtime check and surface-load outcome. Temporarily promote to INFO during the repro. Confirm via `journalctl --user -u studio-compositor -f | grep album` whether `_refresh_cover` is being called and whether it succeeds.
- If `get_image_loader().load()` returns None, the fallback image loader needs to handle the PIL path (or PNG signature validation)

**Acceptance for fix PR:**

- Log line showing `_refresh_cover` succeeds
- Pixel sample at cover centre on `/dev/video42` matches the actual album art's dominant colour within 20 LAB units

### §9.2 Anchor #2 — Vinyl playing but not audible on stream

**Likely-break sites:**

- [ ] **OBS not capturing `hapax-livestream` sink monitor.** Confirm OBS scene Audio Mixer has an entry for `hapax-livestream.monitor` (NOT just the 24c monitor)
- [ ] **`hapax-livestream` sink has no loopback from 24c output.** Check `pactl list modules | grep loopback` — expected loopback: 24c_monitor → hapax-livestream
- [ ] **Vinyl not routed to 24c output mix.** 24c hardware mixer (UC Surface) — verify turntable input strip's USB-return knob is at unity and output routing sends to main output
- [ ] **`yt-over-24c-duck.conf` installed but vinyl strip not routed through `hapax-24c-ducked`** — operator silence on AudioDuckingController means gain stays at unity, but the sink exists and pulls audio AWAY from the default-sink path
- [ ] **`pactl info | grep 'Default Sink'`** must name the 24c OR `hapax-livestream` — inconsistency between default sink and egress sink breaks the route

**Dataflow as it should exist:**

```
turntable → 24c input Y (hardware) → 24c mixer → 24c output mix
  → alsa_output.usb-PreSonus_Studio_24c... (default sink)
  → (loopback module) → hapax-livestream sink
  → OBS PipeWire capture on hapax-livestream.monitor
  → RTMP egress to platform
```

**Dataflow as it currently exists** (hypothesis):

- Turntable → 24c → default sink OK (operator hears it on headphones)
- **Missing:** `hapax-livestream` sink is not loopback-fed from default-sink monitor, OR OBS is capturing the wrong sink
- A contributing cause may be the CLAUDE.md note that says audio-topology runbook is at `docs/runbooks/audio-topology.md §5` — alpha should read that runbook for the canonical matrix and compare to live state

**Minimal fix delta:**

- If loopback missing: `pactl load-module module-loopback source=@DEFAULT_MONITOR@ sink=hapax-livestream` (persist in `~/.config/pipewire/pipewire.conf.d/hapax-livestream-loopback.conf` or wireplumber policy)
- If OBS misconfigured: update OBS scene to capture `hapax-livestream.monitor` — this is a manual OBS action, not a code change

### §9.3 Anchor #3 — Three YouTube ffmpegs simultaneously audible

**Likely-break sites:**

- [ ] **`director_loop.py:919`** — `self._audio_control.mute_all_except(self._active_slot)` is called ONCE at startup. When slot 1's ffmpeg finishes a video and youtube-player spawns a new ffmpeg, the new sink-input ID comes up at volume 1.0. `mute_all_except` is NOT re-called
- [ ] **`audio_control.py:144-147`** — `mute_all_except` iterates `range(self._slot_count)` and calls `set_volume(slot_id, 1.0 or 0.0)`. This assumes the sink-input for that slot_id currently exists. If it doesn't (between ffmpeg restart), `discover_node` returns None and the call is a silent no-op
- [ ] **`audio_control.py:100`** — `discover_node` uses cached node_cache; cache is only invalidated on wpctl failure, NOT on a fresh pw-dump when a new sink-input appears. Cache stale until wpctl fails
- [ ] **`youtube_turn_taking.py` (D2 gate)** — is a read-only tail-scan; spec §29 says it was "integration-optional" but operator directive says it should be wired. Currently NOT called from the audio path — grep `youtube_turn_taking` in `director_loop.py` and `compositor.py` returns zero hits

**Dataflow as it should exist:**

```
scripts/youtube-player.py spawns 3 VideoSlots
Each slot writes to Pulse sink-input youtube-audio-{0,1,2}
Director loop periodically (e.g. every 1 s) calls
  SlotAudioControl.mute_all_except(active_slot)
ON NEW FFMPEG RESTART:
  SlotAudioControl has a sink-input-added watcher
  (e.g. pw-dump subscription or monotonic poll)
  that re-applies the mute_all_except policy immediately
  for the new node-id
YoutubeGateState (read-only) is also consulted; if gate.enabled=False,
  ALL slots muted regardless of active_slot
```

**Dataflow as it currently exists:**

- `mute_all_except` called once at startup
- No periodic re-mute
- No sink-input-added watcher
- `youtube_turn_taking.read_gate_state()` never called in audio path
- **Result:** on any ffmpeg restart mid-stream, new slot comes up audible; stays audible until next startup

**Minimal fix delta:**

- Wire `self._audio_control.mute_all_except(self._active_slot)` into `director_loop._loop` at some regular cadence (e.g. every iteration, or every 5 s), AND into the cold-start dispatcher path (`_slots_needing_cold_start` reload path)
- OR: add a `pw-dump` subscription or `pactl subscribe` event listener that re-applies policy on sink-input-new events
- OR: call `youtube_turn_taking.read_gate_state()` on every director tick and feed its `enabled`+`active_slot` into `SlotAudioControl.mute_all_except` directly (this wires D2 into the audio path in one shot)

### §9.4 Anchor #4 — No audio ducking when Hapax speaks over YT

**Root cause (confirmed during audit):**

- [ ] **`audio_ducking.py:286 set_yt_audio_active`** is defined, exported, and never called
- [ ] Grep confirms: only hits are the function definition and its `__all__` export. No producer writes `SHM/yt-audio-state.json`
- [ ] `read_yt_audio_active` returns None when the file doesn't exist
- [ ] `tick()` at `audio_ducking.py:223` sets `raw_yt = None`; `None` is falsy → `yt_active = False`; FSM stays in NORMAL unless voice is active
- [ ] **Therefore** `hapax_audio_ducking_state{state="normal"}=1` forever is CORRECT given the input signals; the wiring break is upstream — no one publishes YT-active

**Dataflow as it should exist:**

```
youtube-player.py ffmpeg process produces audio on youtube-audio-N sink-input
  → a level-monitor (pw-cat on youtube-audio-N or on hapax-ytube-ducked.monitor)
  → at ~10 Hz, computes RMS over a 100 ms window
  → calls audio_ducking.set_yt_audio_active(rms > threshold)
  → writes SHM/yt-audio-state.json atomically
AudioDuckingController.tick reads the file
  → yt_active = True when RMS > threshold
  → state transitions to YT_ACTIVE or BOTH_ACTIVE
  → dispatcher applies gain if HAPAX_AUDIO_DUCKING_ACTIVE=1
```

**Dataflow as it currently exists:**

- No level monitor exists
- `SHM/yt-audio-state.json` never created
- Controller runs, but permanently NORMAL
- Even if a producer WERE wired, `HAPAX_AUDIO_DUCKING_ACTIVE` must be `1` on the compositor unit for the dispatcher to apply gain; likely currently `0` (verify)

**Minimal fix delta:**

Two separable PRs:

1. **Producer PR:** spawn a level-monitor thread in `AudioDuckingController.start()` (or as a sibling daemon) that reads `pw-cat --record --target <sink>.monitor --format s16 --rate 48000 --channels 2 --latency 512` on either `hapax-ytube-ducked` (preferred, per README) or on each `youtube-audio-N` sink-input. Computes RMS at 10 Hz, calls `set_yt_audio_active(rms > 0.02)`.
2. **Env PR:** set `HAPAX_AUDIO_DUCKING_ACTIVE=1` in `systemd/user/studio-compositor.service` (or via EnvironmentFile). Verify `hapax-ytube-ducked` and `hapax-24c-ducked` filter-chain configs are installed in `~/.config/pipewire/pipewire.conf.d/` — if not, the dispatcher wpctl calls will fail silently.

**Acceptance for fix:**

- `hapax_audio_ducking_state{state="yt_active"}=1` during YT-only playback
- `hapax_audio_ducking_state{state="both_active"}=1` when operator speaks over YT
- `wpctl get-volume @hapax-ytube-ducked@` shows `0.25` (−12 dB) during voice over YT

---

## §10. Alpha's execution protocol

### §10.1 Workflow

- Read §0 (this doc's intro) and §9 (smoking-gun root causes) first to orient
- Work top-down from §1 through §8, one section at a time
- Mark checkboxes inline as you go — commit progress every 2-3 sections

### §10.2 Commit cadence

- Commit findings to `docs/research/2026-04-20-wiring-audit-findings.md` as each major section completes
- Do NOT commit a monolithic "here is the full audit" file at the end — incremental commits preserve work if the session is interrupted

### §10.3 Filing ❌ findings

Each ❌ finding becomes its own PR. Branch naming:

- `wiring-fix/album-cover-refresh` for §9.1
- `wiring-fix/livestream-loopback-vinyl` for §9.2
- `wiring-fix/youtube-slot-remute-on-restart` for §9.3
- `wiring-fix/audio-duck-yt-producer` for §9.4 (plus `wiring-fix/audio-duck-env-flag` as a sibling PR if env is unset)

### §10.4 Livestream integrity stop conditions

Stop the audit and ping operator immediately if any of these surfaces a ❌:

- Face-obscure bypass path found (§8.2)
- Consent gate failing open on an auditory/transcript capability (§8.1)
- Contact mic audio leaking into `hapax-livestream` (§2.5)
- Operator voice dropped entirely from egress (§2.1)
- Any axiom violation detected by the axiom-check skill

### §10.5 Completion report

When the audit is complete, hand off to delta with:

- Total items verified: <n>
- ✅ count: <n>
- ⚠️ count: <n> (list each)
- ❌ count: <n> (list each with its wiring-fix PR URL)
- Smoking-gun verdicts for §9.1 / §9.2 / §9.3 / §9.4 with live-check output attached

Delta dispatches execution-subagents for each ❌ hotfix PR per the subagent git-safety protocol (global CLAUDE.md).

### §10.6 Known constraints during this audit

- Alpha is on `main` (or a short-lived branch from main); do not create audit-specific long-lived branches. Findings PRs are short-lived and merged one-at-a-time
- The hotfix PRs should pass the `push-gate.sh` and `work-resolution-gate.sh` hooks — do not skip
- Rebase alpha after each merge so the running vite dev server + rebuild-services.timer picks up fixes

---

## §11. Item count summary

- §1 Visual surface wiring: 18 wards × ~6 checks + 6 cross-source = **~114 items**
- §2 Audio routing: ~40 items across 7 subsections
- §3 Impingement ⇄ pipeline: ~25 items
- §4 Director intent_family: ~50 items across 9 intent families
- §5 Observability: ~30 metric checks
- §6 systemd: ~30 lifecycle checks
- §7 SHM freshness: ~45 files
- §8 Consent + governance: ~20 items
- §9 Smoking-gun paths: ~30 items with root-cause paths

**Approximate total: ~380 to-verify items** — deliberately granular per operator directive.

---

## Appendix A — Enumerated canonical values

### A.1 Ward ids (from `shared/director_intent.py::WardId`, 18 members)

```
chat_ambient, activity_header, stance_indicator, grounding_provenance_ticker,
impingement_cascade, recruitment_candidate_panel, thinking_indicator,
pressure_gauge, activity_variety_log, whos_here, token_pole, album,
sierpinski, hardm_dot_matrix, stream_overlay, captions,
(research_marker_overlay, hothouse_keyword_legend — in CLAUDE.md, verify in literal)
```

### A.2 Intent families (from `shared/director_intent.py::IntentFamily`, 20 members)

```
camera.hero, preset.bias, overlay.emphasis, youtube.direction,
attention.winner, stream_mode.transition,
ward.size, ward.position, ward.staging, ward.highlight, ward.appearance,
ward.cadence, ward.choreography,
homage.rotation, homage.emergence, homage.swap, homage.cycle,
homage.recede, homage.expand
```

### A.3 Systemd units (primary, non-timer)

```
hapax-secrets.service
logos-api.service (: 8051)
studio-compositor.service
hapax-daimonion.service
hapax-dmn.service
visual-layer-aggregator.service
hapax-imagination.service
hapax-imagination-loop.service
hapax-content-resolver.service
hapax-watch-receiver.service
hapax-logos.service
hapax-reverie.service
hapax-reverie-monitor.service
hapax-vision-observer.service
studio-fx-output.service
studio-person-detector.service
```

### A.4 PipeWire sinks / sources that matter

```
sources:     hapax-operator-mic (Rode Wireless Pro), Contact Microphone (Cortado MKIII),
             alsa_input.usb-PreSonus_Studio_24c (24c capture), 3× youtube-audio-N sink-inputs
sinks:       alsa_output.usb-PreSonus_Studio_24c (24c output, default sink),
             hapax-voice-fx-capture, hapax-livestream, hapax-ytube-ducked, hapax-24c-ducked
```

### A.5 SHM subtrees (top-level under `/dev/shm/`)

```
hapax-compositor/ (77 files enumerated in §7)
hapax-apperception/  hapax-chronicle/  hapax-consent_engine/  hapax-contact_mic/
hapax-content_resolver/  hapax-conversation/  hapax-daimonion/  hapax-director/
hapax-dmn/  hapax-eigenform/  hapax-exploration/  hapax-imagination/
hapax-ir_perception/  hapax-logos/  hapax-reactive_engine/  hapax-reverie/
hapax-sensors/  hapax-sources/  hapax-sprint/  hapax-stimmung/
hapax-structural/  hapax-temporal/  hapax-temporal_bands/  hapax-vision/
hapax-visual/  hapax-voice_daemon/  hapax-voice_pipeline/
```

Each subtree has a producer and one or more consumers. Alpha verifies mtime freshness for the producer and read-cursor freshness for the consumer.

### A.6 Top 5 items most likely to be broken (cascade assessment)

Ordered by confidence that the link is broken right now:

1. **§2.6 / §9.4 YT audio ducking — no producer for `yt-audio-state.json`.** Verified during cascade audit: `set_yt_audio_active` has zero callers. The ducker is functionally dead. HIGH confidence ❌.
2. **§2.4 / §9.3 YouTube mute-all-except not re-applied after ffmpeg restart.** `mute_all_except` is called once at startup against slots present at that instant. New sink-input IDs on ffmpeg reconnect come up at unity volume. HIGH confidence ❌.
3. **§9.1 Album cover not rendering.** Verified: PNG is fresh and present. The cairo render path OR the `_pip_fx_package` post-processing is either short-circuiting or masking. Most likely: `get_image_loader().load(COVER_PATH)` returned None previously and was never retried, OR the pip-ll surface geometry is wrong so the cover is scaled to zero. MEDIUM-HIGH confidence ❌.
4. **§2.3 / §9.2 Vinyl not reaching `hapax-livestream`.** Smoking gun from operator — audible on monitor but not on stream. Most likely: OBS captures default-sink monitor but `hapax-livestream` is a separate sink with no loopback from 24c. MEDIUM confidence ❌.
5. **§4.4 `youtube_turn_taking` gate is dead code in the audio path.** The D2 module was shipped as "integration-optional" and is NOT called by any director tick or audio controller. It's read-only, so there is no direct harm — but the stated intent ("only one YouTube plays at a time") relies on active enforcement. MEDIUM confidence ⚠️ (wired-but-dormant).

---

## Appendix B — Out-of-scope (explicit non-goals)

This audit does NOT cover:

- Logos frontend component wiring (React / Tauri IPC) — covered by `/review-pr` + `beagle-react` skills
- Qdrant vector collection schema + embedding quality — covered by the RAG ingestion audit
- LiteLLM gateway routing — covered by `/gpu-audit` + `/diagnose litellm`
- Axiom implication coverage — covered by `/axiom-sweep`
- MIDI / synth / vocal chain wiring — covered by the studio memory's `project_vocal_chain.md`

Alpha should note if any item in this audit overlaps with a covered skill and defer to that skill's canonical verification pass.

---

**End of audit doc.** Alpha begins at §1.1 and works through to §10.5. Target session budget: one full alpha session. Hand off findings to delta on completion.
