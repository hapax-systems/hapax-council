# Wiring Audit Findings — Alpha Execution

**Author:** alpha session, 2026-04-19
**Reference audits:** `docs/research/2026-04-20-wiring-audit-alpha.md` (#171),
`docs/research/2026-04-20-ward-full-audit-alpha.md` (#172)
**Snapshot:** main `3bd0cf9f7` + cascade unmerged audit drops; live system as observed
during execution. All metric/SHM/log paths verified at audit time and noted with
their evidence command.

Findings are recorded here incrementally as the audit progresses. Each ❌ gets
its own future PR (one fix per branch). Each ⚠️ is recorded with the gating
condition that would have to change for it to fire.

---

## §1.1 token_pole

| # | Item | Verdict | Evidence |
|---|------|---------|----------|
| (a) | `class TokenPoleCairoSource` resolves | ✅ | `agents/studio_compositor/token_pole.py:289` |
| (b) | `token_pole → pip-ul` assignment | ✅ | `jq '.assignments[] \| select(.source=="token_pole")' default.json` |
| (c) | Source registered at runtime | ✅ | `studio_compositor_source_render_duration_ms_count{source_id="token_pole"}` non-zero |
| (d) | Runner thread alive | ✅ | render-duration histogram bucket counts increment (>233k frames) |
| (e) | `SHM/token-ledger.json` fresh | ✅ | mtime within 60 s; producer `scripts/token_ledger.py` writes via `chat-monitor.py` |
| 1.1.4 | Reads `SHM/homage-active-artefact.json` for accent | ⚠️→❌ | File present but mtime 2026-04-19T02:29 (8.25 h stale). See FINDING-B. |
| 1.1.5 | Draws Vitruvian on every tick | ✅ | render-duration histogram |
| 1.1.6 | Pixel acceptance signal | ⏳ | `/dev/video42` busy (OBS); `fx-snapshot.jpg` mtime 10:41 — needs sample |
| 1.1.7 | `hapax_ward_fx_events_total{ward_id="token_pole"}` monotonic 5 min | ❌ | No `ward_id="token_pole"` row exists. See FINDING-A. |

---

## Aggregated systemic findings (so far)

### ⚠️ FINDING-A — `hapax_ward_fx_events_total` ward-side bus rows require capability dispatch — RE-SCOPED 2026-04-21

- **Severity:** low (no code bug; observability gap surfaces only when no homage capability is active)
- **Where:** `shared/ward_fx_bus.py:230` (publish_fx hardcodes ward_id=""),
  `agents/studio_compositor/homage/choreographer.py:431` (`_publish_ward_events`),
  `agents/studio_compositor/compositional_consumer.py:930` (`_append_pending_transition`)
- **Re-scoping (post-FINDING-B-fix verification 2026-04-21T09:48Z):**
  - `direction="fx"` rows legitimately hardcode `ward_id=""` (line 230). FX events are
    global preset/chain mutations, not ward-scoped — empty ward_id is correct, not a bug.
  - `direction="ward"` rows DO carry `ward_id=plan.source_id` (choreographer line 464),
    so the labelling pipeline is correct.
  - The remaining gap is producer-side: `_publish_ward_events` only fires when the
    choreographer's `planned` list is non-empty, which only happens when
    `_append_pending_transition` has written into `homage-pending-transitions.json`,
    which only happens when a `homage.*` capability is recruited and dispatched. In
    quiescent state (no IRC traffic, no recruitment events) the file legitimately
    stays absent and no ward rows emit.
- **Audit-doc claim re-scoping:** §1.1.7 / §1.2.x … §1.16.x's "monotonic ward_id rows
  per ward" assertion requires synthetic stimulation; deferred to the per-ward
  synthetic-stimulus harness already on the queue. Quiescent absence is not a bug.
- **Remaining real work:** none. Closing as a producer-quiescence observation, not a
  defect. If ward-rows still missing AFTER a recruitment dispatch occurs, re-open with
  the dispatched-capability + missing-row evidence.

### ✅ FINDING-B — HOMAGE choreographer reconcile stalled ≥ 8 h — RESOLVED 2026-04-21

- **Resolution:** commit `54e2d36d6 fix(homage): import correct class name — Choreographer
  not HomageChoreographer` together with the wiring block in
  `agents/studio_compositor/lifecycle.py` (lines 373–407) instantiates `Choreographer`
  and schedules `reconcile()` on a 1 Hz `GLib.timeout_add`. Root cause was cause-list
  item #1: the loop never ran — the class was never instantiated at all
  (`grep -r 'Choreographer('` returned zero call sites prior to the fix).
- **Verification (2026-04-21T09:48Z):** compositor restarted 09:46:41 CDT; three of four
  homage SHM files refreshing within seconds:
  ```
  /dev/shm/hapax-compositor/homage-active-artefact.json     09:47   {"package":"bitchx",...}
  /dev/shm/hapax-compositor/homage-substrate-package.json   09:46   {"package":"bitchx",...}
  /dev/shm/hapax-compositor/homage-voice-register.json      09:48   {"register":"textmode",...}
  ```
  `homage-pending-transitions.json` legitimately absent — that file is
  dispatcher-written and choreographer-drained, so no `homage.*` capability
  recruitment ⇒ empty queue ⇒ no file. See `_append_pending_transition` in
  `agents/studio_compositor/compositional_consumer.py:930`.
- **Cascade-resolved metrics** (curl `127.0.0.1:9482/metrics`):
  - `hapax_homage_package_active{package="bitchx"} 1.0`
  - `hapax_homage_signature_artefact_emitted_total{form="join-banner",...}` ≥ 1
  - `hapax_homage_signature_artefact_emitted_total{form="quit-quip",...}` ≥ 2
  - `hapax_homage_emphasis_applied_total{intent_family="structural.emphasis",ward=...}`
    flowing for `thinking_indicator` + `stance_indicator`
  - `hapax_homage_render_cadence_hz{ward=...}` for 17 wards (full coverage incl. `gem`)
  - `hapax_homage_rotation_mode{mode="weighted_by_salience"} 1.0`
  - `hapax_homage_substrate_saturation_target 1.0`
- **Note for FINDING-A re-scope:** `direction="fx"` legitimately hardcodes `ward_id=""`
  in `shared/ward_fx_bus.py:230` (FX events are global, not ward-scoped). Ward-bearing
  rows require `direction="ward"`, which only fires when the choreographer's `planned`
  list is non-empty — which in turn requires `homage.*` capability dispatch through
  `_append_pending_transition`. See updated FINDING-A.

---

## §1 progress (visual surface wiring)

All 17 cairo+external sources from `default.json` confirmed REGISTERED + RENDERING per
`studio_compositor_source_render_duration_ms_count{source_id=…}` ≥ 48k frames each over
the compositor's ~9 h uptime. Per-source counts:

| source_id | render-count | implied cadence (Hz) | classification |
|-----------|--------------|----------------------|----------------|
| token_pole, album, sierpinski, sierpinski-lines | 239 815–239 919 | ~7.4 | high-cadence |
| overlay-zones | 225 933 | ~6.9 | high-cadence |
| thinking_indicator | 144 003 | ~4.4 | mid |
| captions | 120 016 | ~3.7 | mid |
| hardm_dot_matrix | 96 019 | ~2.96 | mid |
| activity_header, stance_indicator, chat_ambient, grounding_provenance_ticker, captions, impingement_cascade, recruitment_candidate_panel, pressure_gauge, activity_variety_log, whos_here, stream_overlay | 48 019–48 020 | ~1.48 | low (rate_hz: 1.5) |

Reverie SHM `/dev/shm/hapax-sources/reverie.rgba` confirmed 921600 bytes (640×360×4),
mtime within 1 s — wgpu writer ALIVE.

§1 verdicts (a)-(d) for each ward all ✅ except where blocked by FINDING-A (ward_id
labeling) or by OBS holding /dev/video42 for pixel acceptance probes. The visual
surface is wired and rendering. The two systemic failures (A: ward_id="" everywhere
and B: choreographer reconcile stalled) suppress observability + artefact rotation
but do not block the ward render path.

### Ward-specific notes

- **§1.2 album** — vinyl_playing currently False (turntable idle); ward source firing
  but conditional content path dormant. Acceptance signal ("smoking gun #1") cannot
  be verified without active vinyl. No ❌ for this ward currently.
- **§1.4 sierpinski** — registered + firing (239k frames) but NOT in `assignments[]` of
  default.json. Audit doc §1.4 anticipated this; render is via `fx_chain.pip_draw_from_layout`
  callback path, not the assignment dispatcher. ⚠️ wired-via-non-assignment (intentional).
- **§1.5 reverie** — full ✅ (external_rgba, mtime fresh, all bytes present).

§1 — closed for now (deferred: pixel acceptance probes once /dev/video42 is freed).

---

## §2 audio routing (SMOKING GUN cluster)

### ✅ FINDING-C — `set_yt_audio_active` defined but NEVER called — RESOLVED 2026-04-20 (Task #183)

- **Resolution:** `scripts/youtube-player.py:771` (`_publish_yt_audio_active`) is an
  inline mirror of `agents.studio_compositor.audio_ducking.set_yt_audio_active`,
  duplicated to avoid the agents/ import path under system Python. Writes on EVERY
  tick (idempotent tmp+rename) so consumers can use mtime as a liveness signal —
  Task #183 fix from 2026-04-20.
- **Verification (2026-04-21T09:55Z):**
  ```
  /dev/shm/hapax-compositor/yt-audio-state.json {"yt_audio_active": true}
  hapax_audio_ducking_state{state="yt_active"} 1.0
  hapax_audio_ducking_state{state="normal"}    0.0
  ```
  Ducker is no longer stuck at `normal=1` — state machine flipping correctly.
- **Note:** fix path was variant of (b) (slot-side liveness heuristic from the producer
  rather than consumer-side level monitor) — pragmatic given Python-import constraints
  in the player script.

### ✅ FINDING-D — `youtube_turn_taking.read_gate_state` is dead code — RESOLVED 2026-04-21

- **Resolution:** `agents/studio_compositor/audio_control.py:188` (`start_gate_poll`)
  defaults `gate_reader` to `youtube_turn_taking.read_gate_state` (line 212). Wired
  into the audio path via `director_loop.py:1155`
  (`self._audio_control.start_gate_poll()`).
- **Verification (2026-04-21T09:46:41Z journal):**
  ```
  studio-compositor[3638066]: SlotAudioControl gate-poll started (interval=2.0s)
  ```
  Polls every 2.0s, force-refreshes node cache each call (line 180), so respawned
  ffmpegs get fresh node IDs.

### ✅ FINDING-E — `SlotAudioControl.mute_all_except` only fires at startup + restore — RESOLVED 2026-04-21

- **Resolution:** same `start_gate_poll` thread (audio_control.py:221) re-applies
  the gate state every 2.0s via `apply_gate_state` → `mute_all_except(active_slot)`.
  Each iteration force-refreshes the node cache (line 180) so newly-spawned
  ffmpeg sink-inputs are caught within a 2s window.
- **Verification:** see FINDING-D — same poll thread satisfies both findings.
- **Architectural note:** chose fix-path #1 (periodic re-mute) rather than the
  PipeWire sink-input-added watcher (#2) — single thread, no inotify/dbus
  subscription, naturally bounded latency.

### ✅ FINDING-F — `/dev/shm/hapax-compositor/voice-state.json` ABSENT — RESOLVED 2026-04-21 (PR #1129)

- **Resolution:** PR #1129 (`fix(daimonion): publish voice-state.json baseline at
  startup`) adds a `publish_vad_state(False)` call in `agents/hapax_daimonion/run_inner.py`
  near startup so the SHM file exists with a known baseline from boot. Real
  `VadStatePublisher` events overwrite as they arrive.
- **Root cause was cause-list item #1:** `vad_state_publisher` was wired into the
  conversation pipeline, but only spawned after `UserStartedSpeakingFrame` — a
  quiet-operator startup left the file missing for the daemon's entire lifetime.
- **Verification (2026-04-21T09:56Z, after rebuild-services.timer pulled merged main):**
  ```
  /dev/shm/hapax-compositor/voice-state.json  09:56  {"operator_speech_active": false}
  ```
  Test pin: `tests/hapax_daimonion/test_voice_state_baseline.py`.

### §2 progress (post-resolution sweep)

- §2.1 daimonion TTS routing — pending (need PipeWire link inspection)
- §2.2 daimonion-stt — pending
- §2.3 vinyl-on-stream routing (smoking gun #2) — pending (currently dormant since vinyl_playing=False, will check link existence regardless)
- §2.4 YT 3 slots — ✅ FINDING-E resolved
- §2.5 contact mic — pending
- §2.6 audio ducking — ✅ FINDING-C + ✅ FINDING-F resolved
- §2.7 audio observability — ducking metric flowing (`yt_active=1`, no longer stuck `normal`)

---

## §3 impingement ⇄ pipeline wiring

§3 producers and consumers verified, with several audit-doc PATH ERRORS detected.
The actual paths are noted; these don't change the audit verdicts but the audit doc
itself needs corrections (called out as meta-findings below).

### Producer verdicts

| Producer | Path (actual) | Verdict | Evidence |
|----------|---------------|---------|----------|
| DMN impingements | `/dev/shm/hapax-dmn/impingements.jsonl` | ✅ | mtime fresh (10:49), 26 MB jsonl |
| DMN current state | `/dev/shm/hapax-imagination/current.json` (NOT `hapax-dmn/current.json` as audit) | ✅ | mtime fresh (10:48); `agents/dmn/sensor.py:30` confirms path |
| VLA visual frame | `/dev/shm/hapax-visual/frame.{jpg,rgba}` | ✅ | mtime fresh (10:49) |
| VLA stimmung | `/dev/shm/hapax-stimmung/state.json` (NOT `current.json` as audit) | ✅ | mtime fresh; 14 dimension keys present |
| Director INTENT | `~/hapax-state/stream-experiment/director-intent.jsonl` | ✅ | mtime fresh (10:48) |
| IR Pi NoIR fleet | `~/hapax-state/pi-noir/{desk,overhead,room}.json` (NOT `{ir-*}.json` as audit) | ✅ | All refreshing ~3s cadence (verified 2026-04-21T09:58Z). FINDING-G resolved. |
| Daimonion impingement cursors | `~/.cache/hapax/impingement-cursor-daimonion-{cpal,affordance}.txt` (NOT `/dev/shm/hapax-daimonion/` as audit) | ✅ | both present mtime fresh; `run_inner.py:398` + `run_loops_aux.py:326` confirm |

### ✅ FINDING-G — IR Pi NoIR fleet dark for ~2 days — RESOLVED 2026-04-21

- **Severity (re-rated):** LOW (fleet was dark when audit ran; data has since recovered
  — likely transient daemon stall + restart, or Pi network blip during the audit window)
- **Verification (2026-04-21T09:58Z):** all three IR-bearing pi-noir files refreshing
  every ~3s (audit cadence per `IR Perception` in CLAUDE.md):
  ```
  ~/hapax-state/pi-noir/desk.json      09:58  hapax-pi1 desk     {persons:[],hands:4,...}
  ~/hapax-state/pi-noir/overhead.json  09:58  hapax-pi6 overhead
  ~/hapax-state/pi-noir/room.json      09:58  hapax-pi2 room
  ```
- **Daemon liveness check (Pi-1 + Pi-2 ssh):** `hapax-ir-edge.service` is a SYSTEM
  unit (not `--user`), running since 01:37 today on both Pi-1 and Pi-2. Pi-6 SSH
  refusing connections currently (port 22 likely fronted by a different sshd config),
  but its `overhead.json` is still updating — the IR daemon is running and POSTing.
- **Audit-doc paths corrected:** `systemctl --user status hapax-ir-edge` was the wrong
  invocation — daemon runs under SYSTEM systemd. Use `systemctl status hapax-ir-edge`.
- **Cause-list disposition:** likely cause #1 (transient daemon crash); auto-recovery
  came from manual restart or a downstream watchdog. No code-level intervention required
  beyond updating health-monitor docs to use the correct systemctl scope.

### Meta-finding M-1 — audit doc §3 has 3 path errors (worth fixing)

The audit doc names paths that don't match the running system. Concrete:
1. `~/hapax-state/pi-noir/{ir-desk, ir-room, ir-overhead}.json` should be `{desk,room,overhead}.json` (no `ir-` prefix)
2. `/dev/shm/hapax-daimonion/impingement-cursor-*.txt` should be `~/.cache/hapax/impingement-cursor-*.txt`
3. `/dev/shm/hapax-stimmung/current.json` should be `state.json`
4. `/dev/shm/hapax-dmn/current.json` doesn't exist; the equivalent is `/dev/shm/hapax-imagination/current.json`

These are not livestream issues but they prevent future verifiers from running the audit-doc commands as written. Recommend delta refresh the audit doc once these audit-pass findings are processed.

### §3.3 affordance pipeline

- ✅ Qdrant `affordances` collection: status `green`, 235 points (`curl -s http://localhost:6333/collections/affordances`)

---

## §6 systemd lifecycle (rapid sweep)

All 12 hapax services confirmed `active`:

```
hapax-secrets             active (since 2026-04-17 13:43:11)
logos-api                 active (since 2026-04-19 04:02:43)
studio-compositor         active (since 2026-04-19 04:06:01)
hapax-daimonion           active (since 2026-04-19 10:48:28) ← restarted recently
hapax-dmn                 active (since 2026-04-19 04:05:29)
visual-layer-aggregator   active (since 2026-04-19 10:48:18) ← restarted recently
hapax-imagination         active (since 2026-04-19 04:02:43)
hapax-imagination-loop    active (since 2026-04-19 04:07:17)
hapax-content-resolver    active (since 2026-04-19 04:06:02)
hapax-watch-receiver      active (since 2026-04-19 04:06:03)
hapax-logos               active (since 2026-04-19 07:57:34)
hapax-reverie             active (since 2026-04-19 04:06:04)
```

Ports listening:
- `:8051` logos-api (FastAPI)
- `:8052` hapax-logos command relay (Tauri Rust WS)
- `:8053` hapax-logos JPEG frame server (Tauri Rust HTTP)
- `:9482` studio-compositor Prometheus metrics

Timers all firing on cadence (verified `systemctl --user list-timers`); rebuild
timers (rebuild-services.timer @ 5 min, rebuild-logos.timer @ 5 min) recent.

§6 — ✅ NO FINDINGS at the lifecycle level. Service shells are all up. The actual
breaks are inside the running processes (not the lifecycle), which is what FINDINGs
A through G capture.

---

## Health endpoint correlation

`curl :8051/api/health` summary:
- overall_status = `failed`
- 110 checks total, 101 healthy, 7 degraded, 2 failed
- Failing/degraded checks: `exploration_salience_router`, `exploration_apperception`,
  `exploration_voice_state`, `backup.restic_freshness`, `connectivity.pi.hapax-pi4`,
  `connectivity.pi.hapax-pi5`, `gpu.vram`, `gpu.temperature`, `systemd.drift`

The `exploration_*` failures and `connectivity.pi.*` failures align with FINDING-G
(IR fleet dark) and the missing `voice-state.json` in FINDING-F. `gpu.vram` /
`gpu.temperature` / `systemd.drift` are likely independent ops issues worth
cross-referencing later.

---

## In-flight delta fixes (overlap with findings)

PR #1108 (delta, branch `hotfix/fallback-layout-assignment`) bundles:
- The two audit docs (#171 wiring + #172 ward) — landing on main when #1108 merges
- Commit `84e68d682 fix(yt): wire yt-audio-state.json producer in youtube-player`
  — directly resolves **FINDING-C** by adding the missing `set_yt_audio_active` call site
  in `scripts/youtube-player.py`

So FINDING-C is in-flight; verification will reduce to "after #1108 merge + redeploy,
confirm `/dev/shm/hapax-compositor/yt-audio-state.json` appears with mtime advancing
and `hapax_audio_ducking_state{state="yt_active"}` toggles non-zero on YT playback".

The remaining HIGH-severity items NOT covered by #1108 as of audit time:
- **B** — choreographer reconcile stall (no fix on any open PR)
- **D** — youtube_turn_taking dead in audio path
- **E** — mute_all_except not periodic (operator workaround in place; permanent fix needed)
- **G** — IR Pi NoIR fleet ~2 d stale (likely needs Pi-side investigation)

---

## §5 observability (rapid sweep)

29 distinct `hapax_*` metric families defined at `:9482`. All are present in HELP/TYPE
output. Of these, **18 emit ZERO rows** (defined but no instance ever incremented).
Triaged below.

### ✅ FINDING-K — 10 of 11 HOMAGE metrics empty — RESOLVED 2026-04-21 (cascade of FINDING-B fix)

- **Resolution:** cascade-resolved by FINDING-B fix (commit `54e2d36d6`). Compositor
  restarted 2026-04-21T09:46Z; metrics surface verified at T09:48Z.
- **Verification (`curl 127.0.0.1:9482/metrics`):** all observability emitters now flowing:
  - `hapax_homage_active_package{package="bitchx"} 1.0`
  - `hapax_homage_package_active{package="bitchx"} 1.0`
  - `hapax_homage_render_cadence_hz` — 17 wards covered (overlay-zones, token_pole,
    sierpinski, album, hardm_dot_matrix, gem, captions, thinking_indicator,
    stance_indicator, activity_header, chat_ambient, grounding_provenance_ticker,
    whos_here, pressure_gauge, recruitment_candidate_panel, activity_variety_log,
    impingement_cascade, sierpinski-lines, stream_overlay)
  - `hapax_homage_rotation_mode{mode="weighted_by_salience"} 1.0`
  - `hapax_homage_emphasis_applied_total` — 2 ward rows (thinking_indicator, stance_indicator)
  - `hapax_homage_signature_artefact_emitted_total` — 2 forms (join-banner, quit-quip)
  - `hapax_homage_substrate_saturation_target 1.0`
- **Remaining empty (expected):** `hapax_homage_choreographer_rejection_total`,
  `hapax_homage_choreographer_substrate_skip_total`, `hapax_homage_violation_total`,
  `hapax_homage_transition_total`. These only emit on rejection/violation/transition
  events; quiescent absence is correct behavior, matching FINDING-A re-scoping.

### ⚠️ FINDING-L — 7 other compositor/director metrics empty

`hapax_imagination_shader_rollback_total`, `hapax_face_obscure_errors_total`,
`hapax_follow_mode_cuts_total`, `hapax_director_degraded_holds_total`,
`hapax_ward_fx_latency_seconds`, `hapax_degraded_mode_active`,
`hapax_degraded_holds_total`.

- Several of these (`*_errors_total`, `degraded_*`, `shader_rollback`) are EXPECTED
  to be empty in nominal operation (they only emit on failures). ✅ for those.
- `hapax_ward_fx_latency_seconds` empty cascades from FINDING-A (no ward events,
  so no latency samples).
- `hapax_follow_mode_cuts_total` empty is suspicious if follow-mode is enabled —
  needs cross-reference with config (deferred).

---

## §4 director intent_family wiring

`shared/director_intent.py::IntentFamily` enumerates **22 families** (lines 68-94):
- 4 control-surface: `camera.hero`, `preset.bias`, `overlay.emphasis`, `youtube.direction`
- 1 attentional: `attention.winner`
- 1 mode: `stream_mode.transition`
- 7 ward-property: `ward.{size,position,staging,highlight,appearance,cadence,choreography}`
- 6 homage: `homage.{rotation,emergence,swap,cycle,recede,expand}`

`compositional_consumer.py` defines `dispatch_*` functions for ALL 22, so the consumer
side is wired. But on the EMITTER side — `grep -rhn 'intent_family\s*=\s*"' agents/`
returns only 4 string literals: `camera.hero`, `overlay.emphasis`, `preset.bias`,
`youtube.direction`. The other 18 families have no string-literal emit site in `agents/`.

### ❌ FINDING-N — 18 of 22 IntentFamily values have no emitter (dead taxonomy)

- **Severity:** MEDIUM-HIGH (18 dispatch endpoints with no producer; the recruitment
  pipeline can in principle still reach them via dynamic capability registration but
  the static-string path is dark)
- **Audit-doc relevance:** §4.7 (per-ward families), §4.8 (homage families) — both
  are listed but no emitter trace exists for either
- **Possible mitigation already in place:** the `dispatch_*` routing in
  `compositional_consumer.py` may be reachable via affordance-pipeline recruitment
  (capability metadata sets `intent_family`, then the consumer dispatches by family
  rather than string-equality). Need to verify the live recruitment path emits these
  18 families OR confirm they are dead-code that should be retired
- **Investigation step:** enumerate live `INTENT` JSONL for last 24h, count
  `intent_family` distribution: `jq -r '.compositional_impingements[]?.intent_family' INTENT | sort | uniq -c`

### ❌ FINDING-D (re-confirmed at §4.4) — `youtube_turn_taking` not in `director_loop.py`

`grep -n 'youtube_turn_taking\|read_gate_state' agents/studio_compositor/director_loop.py`
returns ZERO lines. The D2 read-only gate is dead in the audio path. Already
captured as FINDING-D.

---

## §7-§10 — deferred (lower priority given current finding density)

Audit doc §7 (`/dev/shm` freshness sweep), §8 (consent governance), §9 (smoking-gun
deep-dive), §10 (cross-system invariants) remain. Several of these are already
covered indirectly by the §1-§6 findings above (e.g. SHM freshness was sampled per
ward + per producer).

---

## #172 ward deep-dive — NOT YET STARTED

532 items in the per-ward × 6-dimension matrix. Recommend running this AFTER the
HIGH-severity findings (B, C, D, E, G) are addressed, since several of the 6 dimensions
(behaviors, functionality, recruitment) depend on the choreographer reconciling and the
ward-fx bus actually carrying events.

---

## #172 Ward Deep-Dive — visual silent-blit cluster

OBS released `/dev/video42`; sampled fresh `ffmpeg -f v4l2 -i /dev/video42 -frames:v 1`
captures (1280×720). For each of 16 ward surfaces, cropped the expected 1280-scale
geometry and analysed mean luminance + standard deviation, then visually inspected
each crop.

### Visual-presence verdicts (live, t=2026-04-19T16:01Z)

| Ward | Region | Mean lum | Std | Visual verdict |
|------|--------|----------|-----|----------------|
| token_pole | pip-ul | 0.32 | 0.16 | ✅ Vitruvian + Bachelard spiral + `[TOKEN \| 3273927/5000]` row |
| pressure_gauge | pressure-gauge-ul | 0.28 | 0.15 | ✅ `[PRESSURE \| 22/100%]` + 22-active row |
| activity_header | activity-header-top | 0.48 | 0.24 | ✅ `[SILENCE \| Silence hold: …]` strip |
| activity_variety_log | activity-variety-log-mid | 0.77 | 0.22 | ✅ `[ACTIVITY] music silence music silence music silence` |
| captions_strip | captions_strip | 0.50 | 0.35 | ✅ scientific-register caption text |
| pip_ur (reverie) | pip-ur | 0.78 | 0.23 | ✅ wgpu chromatic FX (glfeedback alive) |
| hardm_dot_matrix | hardm-dot-matrix-ur | 0.76 | 0.22 | ❌ NOT rendering — only FX bleed + text bleed visible, no 16×16 grid |
| stance_indicator | stance-indicator-tr | 0.40 | 0.07 | ❌ NOT rendering — uniform dark gray, no SEEKING/CAUTIOUS indicator |
| thinking_indicator | thinking-indicator-tr | 0.49 | 0.14 | ❌ NOT rendering — text bleed only |
| whos_here | whos-here-tr | 0.54 | 0.16 | ⚠️ unverifiable from crop; no clear presence indicator visible |
| recruitment_candidate | recruitment-candidate-top | 0.63 | 0.29 | ❌ NOT rendering — FX bleed only, no candidate panel |
| chat_ambient | chat-legend-right | 0.34 | 0.36 | ❌ NOT rendering — FX bleed only |
| impingement_cascade | impingement-cascade-midright | 0.62 | 0.31 | ❌ NOT rendering — chromatic kaleidoscope only, no cascade entries |
| pip_ll album | pip-ll | 0.82 | 0.23 | ❌ NOT rendering — no domain-accent border, no scanlines, no cover (vinyl_playing=False is expected dormant state for cover but border + scanlines should still render per spec §5.1) |
| pip_lr stream_overlay | pip-lr | 0.37 | 0.25 | ❌ NOT rendering — FX bleed only, no chat stats |
| grounding_provenance_ticker | grounding-ticker-bl | 0.92 | 0.04 | ❌ NOT rendering — uniform white/light, no provenance text (std=0.035 ≈ totally uniform, smoking gun) |

### ❌ FINDING-R — Silent-blit cluster: 9 of 16 wards have ZERO visible content despite render-duration histograms incrementing

- **Severity:** HIGH (this is the dominant livestream aesthetic/legibility issue right now)
- **Wards affected:** `hardm_dot_matrix`, `stance_indicator`, `thinking_indicator`,
  `recruitment_candidate`, `chat_ambient`, `impingement_cascade`,
  `pip_ll album` (border + scanlines), `pip_lr stream_overlay`,
  `grounding_provenance_ticker`. Plus `whos_here` unverifiable.
- **Wards rendering correctly:** `token_pole`, `pressure_gauge`, `activity_header`,
  `activity_variety_log`, `captions_strip`, `pip_ur reverie` (6 of 16).
- **Symptom:** runner threads execute (`studio_compositor_source_render_duration_ms_count`
  for these wards is 48k–96k), but the cairo output never appears in the v4l2 output
  frame at the assigned surface coordinates. Background FX (glfeedback chromatic
  stripe) bleeds through.
- **Geographic pattern:** the wards that DON'T render are clustered on the right
  side of the frame and the bottom-left ticker — every chrome strip / panel /
  upper-right cell is dark. Wards that DO render are scattered (upper-left, mid-left,
  top-center, mid-center, bottom-strip, upper-right reverie).
- **Hypothesis (matches v3-deep finding from prior session):** `fx_chain.pip_draw_from_layout`
  silently skips blits when `source.get_current_surface()` returns None — and 9
  of 16 wards' get_current_surface returns None at blit time. PR #1096 was the
  first attempt at this (HomageTransitionalSource initial state ABSENT→HOLD)
  and partially fixed it; this finding re-confirms the symptom persists for
  more than half the surfaces.
- **Live-fix path candidates:**
  1. Audit `get_current_surface()` overrides in each non-rendering ward; track which
     specifically returns None and why (e.g., partial init, missing input file,
     dimension-zero surface).
  2. Make `pip_draw_from_layout` ALWAYS log skip events (per-source counter) so
     the silent-skip becomes observable. Add `hapax_compositor_blit_skipped_total{source_id=…}`.
  3. Add a safety-fallback paint (e.g., border + ward_id text) when get_current_surface
     returns None, so dormant wards are LEGIBLE-MISSING rather than INVISIBLE.
- **Cross-ref:** matches the v3-deep E2E summary in alpha-e2e-verification-20260419-v3.yaml.

### #172 Audit progress

- §3 token_pole — visual ✅; FSM in HOLD per pre-B3 hotfix; recruitment + programme dimensions deferred
- §4 hardm_dot_matrix — ❌ FINDING-R
- §5 album — ❌ FINDING-R (border missing)
- §6 captions — visual ✅
- §7 chat_ambient — ❌ FINDING-R
- §8-§14 (right-side chrome) — ❌ FINDING-R for stance, thinking, whos_here, recruitment, impingement, pressure (✅ pressure rendering)
- §15 stream_overlay — ❌ FINDING-R
- §16 research_marker — conditional/dormant (no LRR condition active, expected absent)
- §17 grounding_provenance_ticker — ❌ FINDING-R

The remaining 6 dimensions per ward (Behaviors FSM, Functionality data inputs, Director-loop
recruitment, Content-programme recruitment) for the non-rendering wards are LARGELY
moot until FINDING-R is resolved — those dimensions only become meaningful once the
visual surface itself is reliably present. After R is fixed, recommend re-running
#172 §3.x-§17.x deeper checks.

For the 6 wards that DO render, the deeper dimensions are mostly already covered by
#171 audit findings (cadence, FSM defaults, prom metrics).

---

## Systematic Root-Cause Investigation (operator-directed, 2026-04-19T16:18Z)

Operator confirmed FINDING-B at code level (`HomageChoreographer` class has zero
instantiation callers anywhere). Investigation extended to map B → R cascade.

### B-1 — HomageChoreographer never wired

| Search | Result |
|--------|--------|
| `grep -rn 'HomageChoreographer(' --include='*.py'` (excl. tests) | **0 hits** |
| `grep -rn 'HomageChoreographer\b' --include='*.py'` (excl. tests) | 1 hit (docstring reference in `legibility_sources.py:157`) |
| `grep -rn 'choreographer\.\(reconcile\|start\|tick\|run\)'` (excl. tests) | **0 hits** |
| `lifecycle.py homage references` | only font-warmup probe (`warn_if_missing_homage_fonts`); no instantiation |
| Tests instantiate it? | YES — `tests/studio_compositor/homage/test_choreographer_invariants.py` constructs `Choreographer(...)` |

**Conclusion:** The class is shipped, tested in isolation, and **never wired into
the running compositor**. PR #1051 (Phase 3) added the file; PRs #1052…#1107 each
extended it; **none added an instantiation/tick call site**.

### B-2 — Cascade impact

The choreographer is the WRITER for these 4 SHM files (all observed frozen at
2026-04-19T02:29Z, ≥8.5 h stale at audit time):
- `homage-active-artefact.json` (artefact rotation)
- `homage-pending-transitions.json` (entry/exit/modify dispatches)
- `homage-substrate-package.json` (palette + substrate context for reverie + cairo)
- `homage-voice-register.json` (TTS register)

Without the writer running, the files retain whatever value the LAST writer left
(likely a one-off seed during early development or a one-shot test). This explains:

- **FINDING-A** (ward_id="" empty): `_publish_ward_events` is only called from
  `choreographer.reconcile`. No reconcile → no ward events → no per-ward labels
  on `hapax_ward_fx_events_total`.
- **FINDING-K** (10/11 homage metrics empty): all are emitted from inside
  reconcile() / writers. No reconcile → no emit.
- **Half of FINDING-R**: many wards' `render_content()` reads the stale homage
  artefact / substrate package for accent colour, content text, transition phase.
  Stale data → stale visuals; no rotation → static identical output (which
  happens to be muted/dim for most chrome wards in the current dormant signal state).

### R-1 — Per-ward investigation: why HARDM appears blank

Detailed walk-through of the silent-blit chain for `hardm_dot_matrix`:

1. `cairo_source.py:580` — `ward_render_scope("hardm_dot_matrix", …)`
   - Resolves ward-properties via 200 ms cache; `visible=true alpha=1.0` → yields props (NOT short-circuited)
2. `cairo_source.py:589` — `self._source.render(...)` called
3. `transitional_source.py:render` — feature flag default ON, state=HOLD → calls `render_content`
4. `hardm_source.py:638 render_content`:
   - `pkg = get_active_package()` returns `HomagePackage(name='bitchx', …)` (verified live)
   - `signals = _read_signals()` → returns `{midi_active: false, vad_speech: false, watch_hr: null, …, homage_package: null}` — **EVERY signal is falsy/None**
   - `_classify_cell(name, None|False)` → returns `("muted", 1.0)` for all 256 cells
   - `pkg.resolve_colour("muted")` → `(0.39, 0.39, 0.39, 1.0)` (gray)
   - All 256 cells render with shimmer-modulated gray over `_GRUVBOX_BG0` (near-black)
5. Cairo surface: 256×256 raster of gray dots on near-black ground
6. Compositor blits this surface to `hardm-dot-matrix-ur` at (1066, 13) scaled 170×170

**Why HARDM appears INVISIBLE in the v4l2 frame:**
- Render cadence metric confirms 4.06 Hz successful renders (not skipped)
- The actual rendered surface IS muted gray on near-black — by spec, all signals
  null/false IS the dormant visual state
- Combined with the bright chromatic glfeedback FX behind it, low-contrast
  muted gray dots are visually swamped
- The cells WOULD appear when signals fire (vad_speech=true → speaking
  brightness mult 1.x, role bumps to accent_*); right now nothing fires

**Verdict for HARDM:** NOT a silent-blit bug. It's an INPUT-DEPRIVATION bug:
the cell-signals payload is all-null because the upstream signal publisher
(presumably the daimonion VAD writer + various SHM signal sources) isn't
populating the fields HARDM expects. HARDM renders correctly given the (empty)
input it sees.

### R-2 — How FINDING-B contributes to FINDING-R

The same input-deprivation pattern likely explains other "invisible" wards:

| Ward | Likely missing input |
|------|----------------------|
| chat_ambient | chat keyword aggregates (need to verify SHM source) |
| stance_indicator | reads stimmung; stimmung IS fresh — needs separate dig |
| thinking_indicator | director-thinking SHM (needs verify) |
| recruitment_candidate | recent-recruitments / candidate panel SHM |
| impingement_cascade | recent impingements with intent_family hints |
| pip_lr stream_overlay | chat-stats / viewer-count (unverified) |
| grounding_provenance_ticker | grounding-provenance entries |

For each: the visual emptiness reflects an EMPTY data source, not a render
failure. The wards are doing their job; what's missing is the upstream
signal flow.

### Synthesis — order of operations for delta

1. **HIGHEST LEVERAGE: wire HomageChoreographer.** A ~30-line addition to
   `lifecycle.py`: instantiate at compositor start, schedule `reconcile()`
   on a periodic timer (e.g. 1 Hz or per the existing tick infrastructure),
   pass the SourceRegistry handle. This single fix:
   - Closes FINDING-B
   - Closes FINDING-K (10 homage metrics)
   - Re-populates FINDING-A (ward_fx ward_id labels)
   - Activates per-ward emphasis dispatch → many of the "blank" wards begin
     to receive emphasis envelopes from director recruitments
2. **NEXT: wire signal publishers feeding HARDM and the other "muted" wards.**
   `_read_signals()` in `hardm_source.py` reads `hardm-cell-signals.json` —
   identify the publisher and confirm it's running and writing real data.
   Same investigation per blank ward.
3. **THEN: fix FINDING-C (set_yt_audio_active producer)** — already in flight
   on PR #1108 commit 84e68d682; once merged this self-resolves.
4. **THEN: fix FINDING-D (youtube_turn_taking dead in audio path)** —
   ~10-line integration into `director_loop._loop` per audit doc §4.4.
5. **THEN: fix FINDING-E (mute_all_except not periodic)** — periodic
   re-mute in director tick OR sink-input-added watcher.
6. **THEN: investigate FINDING-G (Pi NoIR fleet stale 2 d)** — Pi-side
   ssh + service status check; likely Pi-side fleet recovery needed.

These 6 steps, in order, walk down the priority list I proposed and
address every HIGH-severity finding.

---

## Per-Ward Signal-Publisher Investigation (2026-04-19T16:22Z)

Per operator priority list, hunted publishers for the 9 "blank" wards.

### SHM input freshness sweep

| File | Status | Consumer ward |
|------|--------|---------------|
| `chat-state.json` | **MISSING** | stream_overlay |
| `youtube-viewer-count.txt` | **MISSING** | hothouse_sources (whos_here) |
| `grounding-provenance.jsonl` | **MISSING** | grounding_provenance_ticker |
| `recent-impingements.json` | **MISSING** | impingement_cascade |
| `chat-keyword-aggregate.json` | **MISSING** | chat_ambient |
| `chat-tier-aggregates.json` | **MISSING** | chat_ambient |
| `recent-recruitment.json` | ✅ 4s fresh, 1273 b | recruitment_candidate_panel |
| `narrative-state.json` | ✅ 19s fresh | legibility_sources |
| `llm-in-flight.json` | ✅ 3s fresh | thinking_indicator |
| `hardm-cell-signals.json` | ✅ ≤2s fresh (HARDM publisher running) | hardm_dot_matrix |
| `fx-current.txt` | ⚠️ 14 min stale, 5 b | stream_overlay (preset name display) |

### ❌ FINDING-V — 4 ward inputs have NO PRODUCER ANYWHERE in the repo

- **Severity:** HIGH (4 wards literally cannot render content because no upstream code writes their data)
- **Confirmed via** `grep -rln '<filename>' . --include='*.py' --include='*.rs' --include='*.sh'`
  returning ZERO write sites for:
  - `recent-impingements.json` (impingement_cascade ward)
  - `chat-keyword-aggregate.json` (chat_ambient ward, half its inputs)
  - `chat-tier-aggregates.json` (chat_ambient ward, other half)
  - `youtube-viewer-count.txt` (hothouse / whos_here)
- **For `chat-state.json`:** the only writer in the repo is `scripts/mock-chat.py`
  (a dev-time mock); no production producer; the ward stays empty unless someone
  manually runs the mock script
- **For `grounding-provenance.jsonl`:** the only references in agent code are
  prompt-text strings inside `director_loop.py` (e.g. "Fade the grounding-provenance
  ticker back up to full"); NO file write
- **Implication:** these 5 wards (impingement_cascade, chat_ambient, whos_here-via-yt-count,
  stream_overlay-via-chat-state, grounding_provenance_ticker) were SHIPPED with their
  consumer side but their data source was never built. They will stay blank until
  the publishers are written.
- **Fix path:** for each, decide what the publisher should look like. Some are
  obvious (chat-keyword-aggregate from the chat IRC stream; grounding-provenance
  from director's grounding_provenance arrays in INTENT JSONL; recent-impingements
  from a tail-N filter on the existing impingements.jsonl). Others may want
  to be RETIRED rather than implemented if the operator no longer wants them
  on screen.

### ✅ FINDING-V-corollary — HARDM publisher IS running

- `hapax-hardm-publisher.timer` active, fires every 2 s
- Each invocation writes `/dev/shm/hapax-compositor/hardm-cell-signals.json`
  (verified via `journalctl --user -u hapax-hardm-publisher.service`)
- BUT all 16 signals come back null/false because the publisher's UPSTREAM
  perception sources (`perception.get("midi_active")`, `("vad_speech")`,
  `("watch_hr_bpm")`, etc.) are themselves empty
- HARDM is therefore in CORRECT dormant-rendering state (gray dots on near-black);
  it would brighten when any signal lands

This is a separate cascade chain: HARDM publisher → perception sources, where
the perception sources need their own signal flow audit. Likely overlap with
FINDING-G (Pi NoIR fleet stale) and FINDING-F (voice-state.json absent).

### Per-ward verdicts (final, this audit)

| Ward | Cause | Fix path |
|------|-------|----------|
| token_pole | rendering ✅ | none |
| pressure_gauge | rendering ✅ | none |
| activity_header | rendering ✅ | none |
| activity_variety_log | rendering ✅ | none |
| captions_strip | rendering ✅ | none |
| pip_ur reverie | rendering ✅ | none |
| **hardm_dot_matrix** | input-deprivation (publisher runs but perception sources empty) | wire perception sources (overlaps F+G) |
| **stance_indicator** | unknown (stimmung IS present); needs deeper look at render path | per-ward investigation TBD |
| **thinking_indicator** | llm-in-flight present and fresh; render path needs trace | per-ward investigation TBD |
| **recruitment_candidate_panel** | recent-recruitment IS present; render path needs trace | per-ward investigation TBD |
| **chat_ambient** | NO PRODUCER for chat-keyword-aggregate.json or chat-tier-aggregates.json | author publishers (or retire ward) — FINDING-V |
| **impingement_cascade** | NO PRODUCER for recent-impingements.json | author publisher — FINDING-V |
| **pip_ll album** | vinyl_playing=False (cover dormant by design); border render path needs trace for missing-border issue | per-ward investigation TBD |
| **pip_lr stream_overlay** | chat-state.json MISSING (only mock-chat.py writes it); FX preset name 14 min stale | author production chat-state writer — FINDING-V |
| **grounding_provenance_ticker** | NO PRODUCER for grounding-provenance.jsonl | author publisher — FINDING-V |
| research_marker | conditional, no LRR active, expected absent | none |

### Updated priority list (replaces "recommended_fix_order_for_delta")

The priority list shifts based on this finding:

1. **HIGHEST: Wire HomageChoreographer (FINDING-B)** — still the single highest-leverage fix
2. **NEXT: Author the missing publishers (FINDING-V)** — 5 wards that are shipped but have no upstream producer:
   - chat-keyword-aggregate.json + chat-tier-aggregates.json (chat_ambient)
   - recent-impingements.json (impingement_cascade)
   - grounding-provenance.jsonl (grounding_provenance_ticker)
   - youtube-viewer-count.txt (whos_here / hothouse)
   - chat-state.json production producer (stream_overlay)
3. Wire perception sources feeding HARDM publisher (overlap with FINDING-F voice-state.json + FINDING-G Pi NoIR)
4. Per-ward render-path tracing for stance_indicator, thinking_indicator, recruitment_candidate_panel, pip_ll album border (data IS present, render path silently consuming-but-not-painting)
5. Verify FINDING-C resolves once #1108 merges
6. Fix FINDING-D (youtube_turn_taking dead in audio path)
7. Fix FINDING-E (mute_all_except not periodic)
8. Investigate FINDING-G (Pi NoIR fleet stale 2 d)

---

## TBD-Ward Render-Path Trace (2026-04-19T16:24Z) — REVEALS COMPOSITION-ORDER BUG

Traced render code for stance_indicator, thinking_indicator, recruitment_candidate_panel,
pip_ll album. All four `render_content()` impls DO paint content — backgrounds,
scanlines, accent bars, text. The cairo surfaces are NOT transparent. So the
wards' silent-skip hypothesis fails for these 4.

Magnified 4× crops of the live `/dev/video42` frame at the expected ward
positions reveal a SHADER PATTERN — bright halftone-dot textures (red/yellow/
black diamond grid for `recruitment_candidate`; chromatic stripes + magenta/red
banding for `stance` and `thinking`; album region similarly washed). The pattern
matches the glfeedback / halftone shader signature, NOT cairo ward output.

### ❌ FINDING-W — Pipeline composition order: base cairo overlays are OVERWRITTEN by the post-shader chain

- **Severity:** HIGH (architectural; the dominant cause of "missing chrome" in livestream output)
- **Where:** `agents/studio_compositor/fx_chain.py:248-389` — pipeline structure
  documented in the build_inline_fx_chain docstring:

  ```
  input-selector (camera) → queue → cairooverlay (BASE WARDS) → glupload → glcolorconvert ─→ glvideomixer sink_0
  pre_fx_tee (live flash)  → queue →                             glupload → glcolorconvert ─→ glvideomixer sink_1
                                                                                                  ↓
                                                                                         [12 glfeedback slots = SHADER CHAIN]
                                                                                                  ↓
                                                                                         glcolorconvert → gldownload → output_tee
  ```

  Then a POST-FX cairooverlay (line 392, `pip-overlay`) sits AFTER `output_tee`,
  but only composites YouTube PiP (sierpinski). All other wards live on the
  BASE cairooverlay BEFORE the shader chain.

- **Symptom:** the 12-slot glfeedback shader chain produces dense colored output
  (chromatic glitch stripes + halftone-dot textures visible in /dev/video42).
  This output OVERWRITES the cairo content underneath. Wards whose pixels are
  bright/contrasty enough (token_pole's Vitruvian outline + spiral, captions
  with high-contrast text on solid background, pressure_gauge with bright bars,
  activity_header's solid label, activity_variety_log's text-on-near-black)
  partially survive. Wards with subtle/sparse content (HARDM's muted gray dots,
  stance_indicator's small text, thinking_indicator's pulsing dot, album's
  scanline-and-border treatment) get visually destroyed by the shader output.

- **Root-cause assignment for FINDING-R:** this is the dominant explanation for
  the 4 "TBD" wards (stance, thinking, recruitment_candidate, album-border).
  It also likely contributes to HARDM (FINDING-V's HARDM-publisher-running-but-
  null-signals theory and FINDING-W shader-overwrite are NOT mutually exclusive
  — both compound).

- **Fix path candidates** (operator + delta to choose architectural direction):
  1. **Move chrome/info wards to the post-FX cairooverlay** so they composite
     ON TOP of the shader chain. Currently only YouTube PiP is post-FX; the
     refactor adds the 16 other wards to that layer (or a parallel cairooverlay).
  2. **Make the shader chain alpha-aware** — preserve the transparency of the
     base overlay through `glupload`/`glcolorconvert`/glfeedback so wards survive.
     Each glfeedback slot would need to handle an alpha channel and not destroy it.
  3. **Add a third cairooverlay layer** strictly for chrome wards, sitting
     between `gldownload` and `output_tee`. Cleanest separation of concerns.
  4. **Increase ward contrast/opacity** so they survive the shader pass.
     Cheapest fix; cosmetically visible (every ward becomes "louder").

  Operator preference unknown; recommend (1) as the cleanest match to the
  semantic distinction (substrate FX vs UI chrome).

- **Reframes per-ward attribution from earlier findings:**
  - The "blank" wards previously triaged as "TBD render-path" are actually
    **NOT broken at the render level** — they paint correctly but get
    overwritten by the shader chain.
  - FINDING-V (no producer) wards are STILL data-deprived; even moving them
    to post-FX won't help if their input file is empty/missing.
  - FINDING-V and FINDING-W are independent failure modes that compound:
    chat_ambient is BOTH no-producer AND would be obscured by shaders even
    if it had data.

---

## FINDING-X (NEW, 2026-04-19T16:29Z) — `grounding_provenance: []` empty in 99.5% of compositional impingements

- **Severity:** MEDIUM-HIGH (constitutional axiom violation; the "every impingement is grounded" invariant is silently broken)
- **Where:** `~/hapax-state/stream-experiment/director-intent.jsonl` recent 200 entries
- **Distribution:**
  ```
  grounding_provenance length 0: 428 impingements (99.5%)
  grounding_provenance length 1:   1 impingement
  grounding_provenance length 2:   1 impingement
  ```
- **Audit-doc reference:** §4.9 "Cross-family invariants" — "Every emitted CompositionalImpingement
  has a non-empty grounding_provenance OR an UNGROUNDED audit warning logged"
- **Audit warnings present?** `journalctl -u studio-compositor --since "1 hour ago" | grep -ci ungrounded` returns **0**.
- **Implication:** the invariant is violated 428 times silently per ~200-row INTENT slice; the
  warning system that would catch this is NOT firing. Either the empty-provenance branch
  short-circuits past the warning, or the warning-emit code never wired up.
- **Cross-link to FINDING-N:** ward.highlight DOES fire empirically (508 hits in earlier
  empirical INTENT distribution, vs 0 string-literal grep hits). So families ARE routed via
  table/lookup not literal — partial retraction of FINDING-N. The 18→15 of "no string-emitter"
  families that don't fire in INTENT are likely dispatched via the recruitment pipeline,
  not a static string at emit time.

---

## Consolidated findings index (final this push)

| ID | Severity | Topic | Status |
|----|----------|-------|--------|
| B  | HIGH     | HOMAGE choreographer reconcile stalled ≥ 8 h | open |
| C  | HIGH     | `set_yt_audio_active` defined but never called | **in-flight: PR #1108 commit `84e68d682`** |
| D  | HIGH     | `youtube_turn_taking.read_gate_state` dead in audio path | open |
| E  | HIGH     | `mute_all_except` not periodic; respawned ffmpegs come up audible | open (operator workaround active) |
| G  | HIGH     | IR Pi NoIR fleet ~2 d stale | open |
| K  | HIGH     | 10 of 11 HOMAGE metrics empty | cascades from B |
| N  | MEDIUM-HIGH | 18 of 22 IntentFamily values have no string-literal emitter | open |
| A  | MEDIUM   | `hapax_ward_fx_events_total{ward_id="…"}` empty across all wards | cascades from B |
| F  | MEDIUM   | `/dev/shm/hapax-compositor/voice-state.json` absent (vad publisher) | open |
| L  | LOW      | 7 other compositor/director metrics empty (mostly expected nominal-zero) | informational |
| M-1 | LOW     | Audit doc §3 has 4 path/filename errors | informational |
| **R** | **HIGH** | **9 of 16 wards visually absent despite render-duration metrics non-zero (silent-blit cluster)** | **open — root-caused: 5 attributable to FINDING-V (no producer), 1 to HARDM publisher input deprivation, 4 still TBD** |
| **V** | **HIGH** | **4-5 ward inputs have NO PRODUCER ANYWHERE in repo (recent-impingements.json, chat-keyword-aggregate.json, chat-tier-aggregates.json, grounding-provenance.jsonl, youtube-viewer-count.txt; chat-state.json has only dev-mock writer)** | **open — wards shipped without their data sources** |
| **W** | **HIGH** | **Composition order: 16 wards on BASE cairooverlay run BEFORE 12-slot glfeedback shader chain → shader OVERWRITES wards. Only YouTube PiP is post-FX. Architectural fix needed.** | **open — DOMINANT explanation for "blank chrome" ward symptom** |
| **X** | **MED-HIGH** | **`grounding_provenance: []` empty in 428 of 430 (99.5%) recent compositional impingements; constitutional invariant silently violated; UNGROUNDED warnings never emit.** | **open — discovered post-systematic-investigation** |

§4 (director intent_family consumers, 60+ items) and the full §172 ward deep-dive
(532 items) remain. They are continuation work; the present findings cover all
HIGH-severity smoking-gun items the audit anchored on.

---

## Findings index (by severity)

| ID | Severity | Topic |
|----|----------|-------|
| B  | HIGH     | HOMAGE choreographer reconcile stalled ≥ 8 h |
| C  | HIGH     | `set_yt_audio_active` defined but never called (ducker stuck NORMAL) |
| D  | HIGH     | `youtube_turn_taking.read_gate_state` dead in audio path (D2 gate) |
| E  | HIGH     | `mute_all_except` not periodic; respawned ffmpegs come up audible |
| G  | HIGH     | IR Pi NoIR fleet ~2 d stale (presence detection degraded) |
| A  | MEDIUM   | `hapax_ward_fx_events_total{ward_id="…"}` empty across all wards |
| F  | MEDIUM   | `/dev/shm/hapax-compositor/voice-state.json` absent (vad publisher) |
| M-1 | LOW     | Audit doc §3 has 4 path/filename errors |
