---
date: 2026-04-20
author: cascade research subagent (delta dispatch)
audience: alpha (executes the catalog), beta (livestream perf side), operator (governance owner)
register: scientific, neutral, design-doc
status: research catalog — enumerates audit classes; does not itself execute audits
related:
  - docs/research/2026-04-20-wiring-audit-alpha.md
  - docs/research/2026-04-20-ward-full-audit-alpha.md
  - docs/research/2026-04-20-finding-v-deploy-status.md
  - docs/research/2026-04-19-blinding-defaults-audit.md
  - docs/research/2026-04-19-expert-system-blinding-audit.md
  - docs/governance/consent-safe-gate-retirement.md
  - docs/superpowers/specs/2026-04-18-facial-obscuring-hard-req-design.md
  - docs/logos-design-language.md
  - systemd/README.md
operator-directive-load-bearing: |
  "research EVERY type of audit that should be runnable against the
  hapax-council livestream system to verify everything is where it
  ought to be." Comprehensive catalog usable as a go-live checklist
  and as an ongoing governance surface.
incident-of-record: |
  2026-04-20 — Hapax TTS narrated commentary on a rap-analysis YouTube
  track and emitted the N-word. `shared/speech_safety.py` caught one
  instance but did not catch all. Demonstrated that single-gate
  pre-TTS redaction is necessary but not sufficient; multi-modal,
  multi-stage content-safety auditing is required across every text
  surface that reaches broadcast.
---

# Livestream Audit Catalog — Comprehensive Reference

## §0. Document scope and use

This catalog enumerates every class of audit applicable to the
hapax-council livestream system. For each class it records: what is
audited, why it matters, the pass criterion, automation feasibility,
and intended cadence. The catalog is deliberately broader than any
single existing audit — `2026-04-20-wiring-audit-alpha.md` (414
items) and `2026-04-20-ward-full-audit-alpha.md` (532 items) cover
points (2) and (3) below in fine detail; the present document sits
above them and names the full audit surface.

Two intended uses:

1. **Go-live checklist.** Before each livestream session, the
   operator (or alpha on behalf of the operator) walks the
   *pre-live* and *per-stream* rows and confirms green. The
   "Top-priority pre-stream gate" subset (§17) is the irreducible
   minimum — no stream begins without it green.
2. **Ongoing governance surface.** Continuous and incident-driven
   classes form an always-on instrument that must be reviewed at
   each scheduled retrospective. The catalog provides the index
   against which Prometheus alerts, ntfy notifications, and weekly
   reviews are mapped.

Cadence vocabulary used throughout:

- **pre-live** — runs once, immediately before stream start; gates
  egress.
- **per-stream** — sampled at session boundaries (start, mid, end);
  produces a per-stream record.
- **continuous** — runs in the running system on a fixed cadence
  (timer or always-on daemon); failure surfaces via ntfy/Prom alert.
- **incident-driven** — triggered by an event (slur leak, face
  detection failure, OOM, USB bus-kick); produces a structured
  postmortem record.
- **periodic** — runs on a longer schedule (daily, weekly, monthly)
  and feeds the broader governance loop.

Automation vocabulary:

- **fully automated** — runs without operator action; pass/fail
  determined by code; on failure, takes a defined action (block,
  alert, degrade).
- **semi-automated** — code emits a checklist or report; operator
  signs off.
- **manual only** — currently only verifiable by human inspection
  (pixel sample, audible review, dignity judgment).

---

## §1. Content-safety audits (text surfaces reaching broadcast)

The 2026-04-20 incident demonstrated that any text path that can
reach broadcast — through speech synthesis, on-screen rendering, or
system metadata baked into the stream metadata — is a content-safety
surface. Each path needs its own audit because the failure modes
differ: TTS slur leaks are aural and irreversible once spoken; chat
overlay PII is visual but persistent in archive; the YouTube
description is metadata that travels with the recording forever.

### 1.1 TTS output gate

- **Audits.** Every string passed to `TTSManager.synthesize`
  (`agents/hapax_daimonion/...`) before it reaches Kokoro. Coverage
  must include CPAL impingement-driven speech, narrative-director
  spoken lines, briefings, notification narration, copilot
  responses.
- **Why.** Pre-TTS redaction (`shared/speech_safety.py`) is the
  fail-closed line of defence. The 2026-04-20 leak suggests the
  gate is wired into one path but not all; an audit must enumerate
  every call site that can reach `synthesize()` and verify the gate
  is upstream of every one.
- **Pass.** Every code path that calls `synthesize()` is preceded
  by a `speech_safety.censor()` call (or by a wrapper that routes
  through the censor). A static-analysis test enumerates the call
  sites; a runtime test injects the slur token at every entry
  point and asserts the slur never reaches Kokoro. Prom counter
  `hapax_speech_safety_redactions_total` increments on every test
  injection.
- **Automation.** Fully automated. Add a `tests/test_tts_call_site_coverage.py`
  that walks the AST for all `synthesize` callers and asserts each
  is guarded.
- **Cadence.** pre-live (smoke test against a synthetic slur
  injection); continuous (Prom counter monitored, alert on hit).
- **False-positive tolerance.** The allow-list in
  `shared/speech_safety.py:_ALLOWLIST_SUFFIXES` must be exercised
  by tests; the audit confirms that words like "Niagara",
  "niggard", "snigger" pass through unmodified. Operator may need
  to extend the allow-list for proper nouns encountered in
  programme content (e.g., "Niger", "Nigerian").
- **Failure action.** Block stream start if the test injection is
  not redacted. In running stream, every redaction emits a ntfy
  notification with redaction rate and call site so the operator
  can decide whether to swap to a more conservative voice mode.

### 1.2 Chat overlay redaction

- **Audits.** The chat overlay (`stream_overlay`, `chat_ambient`,
  `chat_attack_log`) renders Twitch chat content into the
  broadcast. Audit must confirm: author handle is redacted by
  default; message body is filtered for slurs, doxxing,
  copyrighted lyrics; cooldown / rate-limit prevents flood
  attacks.
- **Why.** Chat is hostile-by-default. A coordinated raid can drop
  slurs into the overlay even if the operator never speaks them.
- **Pass.** No author handle appears in any rendered overlay
  (caplog test enforced for `chat_reactor.py`; extend to overlay
  renderers). Slur regex applied to chat body before render.
  Per-author message rate limited.
- **Automation.** Fully automated for slur regex and author
  redaction; semi-automated for novel attack patterns (operator
  reviews a sampled chat-overlay capture each session).
- **Cadence.** pre-live (smoke render of synthetic hostile chat);
  continuous (sampling from `~/hapax-state/chat-archive/` with
  daily roll-up).
- **Known false-positives.** Kebab-case song titles, proper
  artist names overlapping the slur regex (handled via
  `_ALLOWLIST_SUFFIXES`).
- **Failure action.** Drop the offending message from the overlay
  queue, log to `chat_attack_log`, alert via ntfy.

### 1.3 Captions / subtitle strip

- **Audits.** `agents/studio_compositor/captions_source.py`
  receives daimonion STT + TTS captions. Captions reach broadcast
  even when the audio gate succeeds (the *spoken* form was
  redacted but the *transcribed* form may still carry the original
  slur if STT runs upstream of redaction).
- **Why.** Caption text is independently extractable from the
  video by YouTube ASR and by viewer screenshots. A caption strip
  that displays a slur is as monetization-hostile as a spoken
  one.
- **Pass.** Caption rendering applies the same `speech_safety.censor()`
  pass as TTS, plus an additional check for visual-only hazards
  (URLs to disallowed domains, person names without consent).
- **Automation.** Fully automated. Add a parallel test file mirror
  of `test_speech_safety.py` that drives `CaptionsCairoSource`.
- **Cadence.** pre-live (smoke render with synthetic slur in
  caption queue); continuous (Prom metric on caption-redaction
  count, alert on first hit).

### 1.4 Director narrative + impingement cascade

- **Audits.** The director-loop writes `intent_family` strings and
  free-text narrative into `~/hapax-state/stream-experiment/director-intent.jsonl`.
  The `impingement_cascade` ward renders impingements live. Both
  carry LLM-generated text that can land on screen.
- **Why.** Even if TTS doesn't speak it, the impingement cascade
  ward shows the text. A model-generated slur visible on the
  cascade is a leak.
- **Pass.** Render-time censor applied at the cascade source
  (`hothouse_sources.py:229`). Audit enumerates every text-bearing
  field rendered by ward consumers.
- **Automation.** Fully automated; add `test_impingement_cascade_redaction.py`.
- **Cadence.** pre-live + continuous.

### 1.5 HARDM cell labels and ward chrome

- **Audits.** `hardm_source.py` renders cell labels and emphasis
  text. Every ward that prints user-visible strings (token-pole
  status row, pressure-gauge labels, recruitment-candidate names,
  whos-here label, activity-header) is a potential surface.
- **Why.** Many of these strings come from configuration
  (`config/hardm-map.yaml`, `axioms/registry.yaml`,
  `axioms/persona/...`) and from runtime affordance metadata.
  Configuration drift or affordance-metadata pollution can put
  surprising strings on screen.
- **Pass.** All ward-rendered strings are sourced from a finite,
  reviewed vocabulary (config files + axiom-registry persona
  pool). Static check confirms no f-string interpolation of
  unbounded user content reaches a Pango / Cairo `show_text` call.
- **Automation.** Semi-automated. Static analysis can flag
  candidate sites; manual review is required for vocabulary
  approval.
- **Cadence.** per-stream (config diff against last reviewed
  vocabulary); periodic (monthly vocabulary review).

### 1.6 Overlay zones and pango markdown

- **Audits.** `agents/studio_compositor/overlay_zones.py` and
  `overlay.py` render markdown / ANSI files from the Obsidian vault
  and from runtime overlays. Vault content can include personal
  notes, person names, project codenames, in-jokes — all of which
  may be appropriate in the vault but not on broadcast.
- **Why.** The vault is a personal surface. The broadcast is
  public. A naive cycling of vault notes onto the overlay zone is
  a privacy risk.
- **Pass.** Only files explicitly tagged `broadcast: true` (or
  resident in a designated `broadcast/` subtree) are eligible for
  overlay rendering. The renderer enforces this; static analysis
  confirms there is no path that ignores the tag.
- **Automation.** Fully automated for the tag check; semi-automated
  for tag assignment (operator owns the broadcast vocabulary).
- **Cadence.** pre-live (enumerate currently-eligible files;
  operator confirms list); continuous (alert on any unwhitelisted
  file rendered).

### 1.7 Notifications + ntfy + briefings

- **Audits.** `shared/notify.py::send_notification` is called from
  many places. If a notification reaches the live overlay (some
  overlays do mirror notifications) the same content-safety rules
  apply.
- **Why.** Notifications include error text, command output,
  agent narration. A traceback or system message rendered on
  broadcast reveals operator infrastructure detail.
- **Pass.** Notifications routed to broadcast surfaces are filtered
  through a separate broadcast-safety layer that strips paths,
  hostnames, traceback fragments, and applies the slur regex.
- **Automation.** Fully automated.
- **Cadence.** pre-live + continuous.

### 1.8 YouTube description / title / tags / chapter markers

- **Audits.** `agents/studio_compositor/youtube_description.py`
  + `youtube_description_syncer.py` write video metadata. Tags +
  description travel with the recording into the YouTube archive
  forever and are indexed by YouTube search.
- **Why.** A monetization-flagged keyword in the description
  carries past the live event. Recovery is harder than redacting
  a single TTS line.
- **Pass.** Generated description / title / tags pass through the
  same content-safety pipeline as TTS, plus a YouTube-specific
  policy check (no banned keywords, no clickbait patterns flagged
  by the policy team).
- **Automation.** Fully automated for slur + banned-keyword
  check; semi-automated for tone (operator reviews on first
  publish).
- **Cadence.** pre-live (description preview render and review);
  per-stream (post-publish diff against approved template).

### 1.9 Trademark and copyrighted-lyric audit

- **Audits.** Any text path that can carry brand names (Apple,
  Google, vendor names) or song lyrics. The 2026-04-20 leak was
  triggered by commentary on a rap track; lyric quotation is a
  natural pattern for a music-analysis stream and a content-safety
  hazard if quoted verbatim.
- **Why.** YouTube's copyright system recognises lyric quotes;
  trademark misuse can attract takedowns and demonetization.
- **Pass.** A configurable "do not quote" list — including known
  lyrics and competitor brand names the operator does not want
  associated — applied at the same gate as the slur check.
- **Automation.** Fully automated for the list check; semi-automated
  for list curation.
- **Cadence.** pre-live + continuous.

### 1.10 Personally-identifying information (PII)

- **Audits.** Person names, addresses, phone numbers, real names of
  collaborators or family members. Distinct from consent-gate
  audits (§5) — this audit covers *unintentional* PII leakage,
  e.g., the agent surfaces the operator's full legal name from a
  vault note.
- **Why.** Operator dignity, collaborator privacy, and stalking
  risk.
- **Pass.** PII regex (`hooks/scripts/pii-guard.sh` extended to
  broadcast text) applied at every text-to-broadcast surface. A
  configured allow-list of names that are public (operator's
  stage name, public collaborators) lets through approved
  references.
- **Automation.** Fully automated for regex; semi-automated for
  allow-list curation.
- **Cadence.** pre-live + continuous.

### 1.11 Political flashpoints

- **Audits.** Lexicon of politically charged terms that the
  operator does not want associated with the channel. Independent
  of slur regex.
- **Why.** YouTube applies advertiser-friendliness penalties to
  political content; the operator's research is artistic, not
  political, and should not be misclassified.
- **Pass.** Configurable list filtered at the same gates as slurs;
  optionally the renderer skips the segment rather than redacting
  (operator preference).
- **Automation.** Fully automated.
- **Cadence.** pre-live + continuous.

---

## §2. Signal-flow audits (producer ⇄ SHM ⇄ consumer wiring)

The 2026-04-20 wiring audit (alpha) enumerated 414 items across SHM
files, JSONL streams, state directories, and inter-service signals.
This catalog class names the *audit surface* — the wiring audit
itself is the executor.

### 2.1 SHM producer freshness

- **Audits.** Every file under `/dev/shm/hapax-compositor/`,
  `/dev/shm/hapax-stimmung/`, `/dev/shm/hapax-dmn/`,
  `/dev/shm/hapax-imagination/`, `/dev/shm/hapax-sources/`,
  `/dev/shm/hapax-visual/`, `/dev/shm/hapax-exploration/`. Each
  has a known producer with a known cadence; the audit checks
  `mtime` against expected freshness.
- **Why.** A stale SHM file is the most common silent failure
  mode — the consumer reads the file successfully but the data is
  hours old, producing convincing-looking but wrong output on
  broadcast.
- **Pass.** Every tracked file's mtime within 3× expected
  cadence. Producers expose a Prom freshness gauge
  (`hapax_<surface>_freshness_seconds`).
- **Automation.** Fully automated. Extend
  `scripts/freshness-check.sh` to cover the full SHM enumeration
  produced by the wiring audit, not just binaries and services.
- **Cadence.** pre-live (one-shot); continuous (timer every 60 s).
- **Failure action.** ntfy with the stale producer name; if the
  surface is broadcast-affecting, set `degraded_mode` so the
  consumer knows to render "no signal" rather than the stale value.

### 2.2 Consumer subscription liveness

- **Audits.** For every SHM producer, the audit confirms that the
  declared consumer process is reading. Methods: cursor-file
  advance for jsonl tails (`*-cursor-*.txt`); inotify subscription
  count via lsof or fanotify; per-consumer Prom counter
  `hapax_<consumer>_<source>_reads_total` advancing.
- **Why.** Producer green and consumer dead means broadcast looks
  normal but one ward is silently frozen. Worse, the imagination
  bridge is cursored; if the consumer cursor is wedged the
  consumer keeps replaying old impingements.
- **Pass.** All declared consumers advance their cursor or counter
  within 3× expected cadence.
- **Automation.** Fully automated.
- **Cadence.** continuous; pre-live snapshot.

### 2.3 FINDING-V producer/consumer coverage refresh

- **Audits.** The 2026-04-20 wiring audit predates the full
  FINDING-V producer rollout. The catalog must be re-enumerated
  after each FINDING-V drop to confirm the new producers are
  scoped.
- **Why.** Coverage decays — a producer added after the audit is
  invisible to the audit.
- **Pass.** Diff between `wiring-audit-alpha.md` enumeration and
  the live SHM tree returns zero unexplained surfaces.
- **Automation.** Semi-automated. Code emits the diff; operator
  reconciles.
- **Cadence.** per-stream (drop-week); periodic (monthly otherwise).

### 2.4 JSONL append-vs-tail discipline

- **Audits.** All `*.jsonl` streams must be appended atomically
  (single-write, newline-terminated, no partial flush). Consumers
  must skip partial lines without crashing.
- **Why.** A torn write looks like a parse error; some consumers
  crash on parse errors and silently die.
- **Pass.** Test fixture writes a torn line and asserts every
  consumer skips it without raising.
- **Automation.** Fully automated.
- **Cadence.** continuous (CI); per-stream confirmation.

### 2.5 Cursor-file integrity

- **Audits.** Every cursor file (`impingement-cursor-*.txt`,
  `*-tail-cursor.txt`) is written via tmp+rename (atomic). On
  consumer restart the cursor must point to a still-existing
  offset (not past the end of a rotated file).
- **Why.** Cursor wedged at a stale offset replays old data;
  cursor past EOF can cause infinite-loop reads.
- **Pass.** Rotation-aware cursor that detects truncation and
  resets to start (with logged note).
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 2.6 Cross-system signal mapping

- **Audits.** For every cross-system signal mapped in the 2026-03-29
  hapax data audit (Qdrant 2 dead collections, stimmung GQI never
  flowing, voice reference architecture, 10 cross-system wiring
  gaps, 41 sync agents), confirm current state — has the gap
  closed, persisted, or worsened?
- **Why.** Audit drift: gaps named in March 2026 may or may not
  still be present.
- **Pass.** Each prior gap has either an explicit "closed" record
  or a current-state row.
- **Automation.** Semi-automated.
- **Cadence.** monthly.

---

## §3. Visual-regression audits (per-ward render correctness)

Ward audit (`2026-04-20-ward-full-audit-alpha.md`, 532 items, 16
wards × 6 dimensions: appearance, placement, behaviors,
functionality, director-loop recruitment, content-programming
recruitment) is the depth instrument here. The catalog class names
the dimensions.

### 3.1 Pixel-level appearance vs golden image

- **Audits.** Each ward has a golden image at
  `tests/studio_compositor/golden_images/wards/`. Live render
  sampled from `/dev/video42` (or `fx-snapshot.jpg`) compared to
  golden within tolerance.
- **Pass.** Per-ward Δ < tolerance (typically 5% of pixels >
  threshold delta, configurable per ward).
- **Automation.** Fully automated. Existing `regenerate-homage-goldens.sh`
  + golden tests.
- **Cadence.** pre-live (smoke); continuous (compositor-running
  watchdog comparing samples every 5 min).

### 3.2 Layout placement and z-order non-overlap

- **Audits.** `default.json` surface coordinates rescaled to live
  output (1280×720); confirm no two non-`fx_chain_input` surfaces
  overlap, every assignment binds an existing source, every
  surface has at least one assignment.
- **Pass.** `tests/studio_compositor/test_layout_invariants.py`
  green; the audit script enumerates the runtime registry and
  reconciles against `default.json`.
- **Automation.** Fully automated.
- **Cadence.** pre-live + continuous (on layout swap).

### 3.3 Accent-colour compliance

- **Audits.** Per-ward accent colour matches active homage
  package; design-language rules in `docs/logos-design-language.md`
  prohibit hardcoded hex outside detection overlays.
- **Pass.** No hardcoded hex in compositor renderers (excepting
  documented detection-overlay set); accent colour sampled from
  rendered ward equals package's `_domain_accent("<ward>")`.
- **Automation.** Fully automated for static check; semi-automated
  for sampled compliance (pixel sample requires compositor
  running).
- **Cadence.** continuous (CI for static); pre-live (sampled).

### 3.4 Package-swap correctness

- **Audits.** When `homage-active-artefact.json` changes
  (`HomagePackage` swap), every ward picks up the new accent /
  font / vocabulary within one tick.
- **Pass.** Forced swap fixture observes propagation within 200 ms.
- **Automation.** Fully automated.
- **Cadence.** per-stream (smoke); continuous.

### 3.5 Transition FSM coverage

- **Audits.** Every ward derived from `HomageTransitionalSource`
  has the FSM exercised: `ABSENT → ENTERING → HOLD → EXITING`.
  Pre-B3 hotfix means most wards start in HOLD; the audit must
  record current FSM state for each ward and confirm it matches
  the spec's expected state at this phase.
- **Pass.** State distribution matches plan; B3 deferral noted.
- **Automation.** Fully automated for state read; semi-automated
  for plan-conformance judgment.
- **Cadence.** per-stream.

### 3.6 Emphasis envelope

- **Audits.** When a ward is emphasised
  (`set_ward_properties("<ward>", {glow_radius_px, border_pulse_hz, scale_bump_pct, alpha}, ttl_s)`),
  the visual change appears within 200 ms. TTL expires correctly.
- **Pass.** Emphasis fixture forced via synthetic structural
  intent; pixel sample confirms change; second sample after TTL
  confirms rollback.
- **Automation.** Fully automated.
- **Cadence.** per-stream.

### 3.7 Safe-area respect

- **Audits.** No ward writes outside the YouTube safe area
  (typically inset 5% from each edge); no ward renders over the
  YouTube watermark zone.
- **Pass.** Layout invariant test asserts.
- **Automation.** Fully automated.
- **Cadence.** pre-live + on layout edit.

### 3.8 Background non-overlap with content

- **Audits.** Content (album cover, captions, recruitment panel)
  is not occluded by background fills, scrims, or fx-chain
  output.
- **Pass.** Sampled pixel inside content region matches expected
  content palette, not background.
- **Automation.** Semi-automated (pixel sample programmatic;
  expected palette per-ward derived from golden).
- **Cadence.** per-stream.

### 3.9 Reverie substrate continuity

- **Audits.** `reverie.rgba` SHM updates at producer cadence
  (1 s); pixel variance over 10 s window > 0; the 7-pass pipeline
  is healthy (`uniforms.json` ≥44 keys; `material_id` valid).
  Independent of the ward audit because Reverie is a structural
  peer, not a ward.
- **Pass.** Variance and key-count green.
- **Automation.** Fully automated.
- **Cadence.** continuous.

---

## §4. Audio-pipeline audits (PipeWire graph + 24c mixer)

The 2026-04-14 audio path baseline (`docs/research/2026-04-14-audio-path-baseline.md`)
maps the system; this audit class re-validates each session.

### 4.1 Operator microphone routing

- **Audits.** Rode Wireless Pro reaches `hapax-livestream` sink at
  full level; reaches `hapax-daimonion` STT input; does NOT reach
  the operator's monitor headphones (avoids feedback loop).
- **Pass.** PipeWire graph dump (`pw-link --links`) matches
  declared topology in `config/pipewire/README.md`.
- **Automation.** Fully automated. Extend `scripts/audio-topology-check.sh`.
- **Cadence.** pre-live (gate); continuous (5-min cadence).
- **Failure action.** Block stream start if operator mic is not
  reaching the broadcast sink.

### 4.2 Contact mic routing

- **Audits.** Cortado MKIII at PreSonus 24c Input 2 reaches
  `contact_mic_ir.py` DSP; does NOT route to broadcast unless the
  operator explicitly enables a contact-mic-on-air mode.
- **Why.** Contact mic carries fingernail-on-keyboard, vinyl
  scratch, room rumble — useful for perception, hostile to
  audience.
- **Pass.** Default routing has contact mic going to perception
  only.
- **Automation.** Fully automated.
- **Cadence.** pre-live + continuous.

### 4.3 TTS routing

- **Audits.** Kokoro TTS reaches `hapax-livestream` sink with the
  configured voice-fx chain applied (per `config/pipewire/voice-fx-*.conf`);
  does not reach the operator's headphones at full level (causes
  echo into the operator mic).
- **Pass.** Graph dump matches.
- **Automation.** Fully automated.
- **Cadence.** pre-live + continuous.

### 4.4 YouTube mixer / source audio

- **Audits.** When a YouTube track plays through the mixer it
  reaches the broadcast (so audience hears what is being
  analysed) but is ducked under operator + TTS speech via
  `voice-over-ytube-duck.conf`.
- **Pass.** Ducking confirmed by RMS sample during a synthetic
  voice + YouTube overlap; operator + TTS audible above the
  ducked source.
- **Automation.** Semi-automated (RMS sample programmatic;
  intelligibility judgment manual).
- **Cadence.** pre-live.

### 4.5 Vinyl / turntable

- **Audits.** Turntable RIAA preamp output reaches broadcast at
  appropriate level; does not feed the contact mic via
  mechanical coupling beyond the DSP threshold.
- **Pass.** Levels match operator preset.
- **Automation.** Semi-automated.
- **Cadence.** pre-live.

### 4.6 Chime / notification audio

- **Audits.** Hapax-system chimes (notification SFX, alert tones)
  do not reach broadcast — this is operator-private feedback.
- **Pass.** Chime sink not in broadcast graph.
- **Automation.** Fully automated.
- **Cadence.** pre-live + continuous.

### 4.7 PipeWire graph state checksum

- **Audits.** Full graph diffed against the last
  operator-confirmed configuration; flag any unexpected node /
  link addition (e.g., a Discord call adding itself).
- **Pass.** Diff empty or operator-acknowledged.
- **Automation.** Fully automated.
- **Cadence.** pre-live (one-shot); continuous (5-min).

### 4.8 24c physical mixer state

- **Audits.** PreSonus Studio 24c hardware mixer state (gain
  trims, phantom power on Input 2 only, monitor mix, USB return
  routing) matches operator preset. The 24c does not expose its
  state via API; the audit can only confirm via the operator's
  visual confirmation OR via a test signal injection across each
  channel.
- **Pass.** Test signal at -18 dBFS injected per channel produces
  expected meter readings on the broadcast capture.
- **Automation.** Manual only for the visible knobs; semi-automated
  for the test-signal injection.
- **Cadence.** pre-live (operator confirms with photo or visual
  check); periodic.

### 4.9 Audio ducking FSM

- **Audits.** `vad_ducking.py` and `audio_ducking.py` reduce
  source audio when operator or TTS is speaking; release with
  configured tail. Audit confirms the FSM holds across many
  rapid voice events without leaking unducked audio.
- **Pass.** Synthetic VAD test sequence; broadcast capture shows
  ducking applied and released within spec.
- **Automation.** Fully automated.
- **Cadence.** continuous (CI); per-stream.

---

## §5. Consent-gate audits

Axiom `interpersonal_transparency` (weight 88) governs every
interaction with non-operator persons. After the 2026-04-18 retire,
visual face-obscure is enforced at the studio_compositor pipeline
layer (`face_obscure_integration.py`); the consent gate now governs
non-visual capabilities only.

### 5.1 Face-obscure pipeline

- **Audits.** Every camera tee passes through
  `face_obscure_integration.py` before any RTMP / HLS / V4L2
  egress. Pixelation is irreversible (solid mask + 20% bbox
  expansion); fail-CLOSED on detector failure (no frames egressed
  if the obscure stage cannot load).
- **Pass.** Synthetic test camera feed with a known face fixture;
  rendered output shows pixelation; detector-failure mode
  exercised; output drops to a placeholder rather than
  passthrough.
- **Automation.** Fully automated.
- **Cadence.** pre-live (gate; absolute non-negotiable);
  continuous (every camera frame).
- **Failure action.** Stop stream egress immediately. ntfy with
  PRIORITY=urgent. Operator must confirm before resume.

### 5.2 Person-detection fail-closed

- **Audits.** When YOLO / SCRFD detection fails (model not
  loaded, GPU OOM, exception), every dependent capability
  short-circuits to fail-closed.
- **Pass.** Forced detector failure; downstream wards (whos_here,
  activity_header) render "detector unavailable" rather than
  stale state.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 5.3 Chat-author redaction (no per-author state)

- **Audits.** `chat_reactor.py` enforces no per-author state, no
  persistence, no author in logs (caplog test pinned). Extend the
  audit to overlay renderers, attack log, signals.
- **Pass.** Static analysis confirms no `author` field reaches
  `log` calls or persistent storage; runtime test confirms.
- **Automation.** Fully automated.
- **Cadence.** continuous (CI).

### 5.4 Guest contract enforcement

- **Audits.** `axioms/contracts/contract-*.yaml` defines active
  consent contracts. When a guest is on stream (operator
  declares), only the capabilities authorised by the contract are
  available; off-contract capabilities are gated.
- **Pass.** Contract activation fixture; capability that lacks
  contract scope is filtered out.
- **Automation.** Fully automated for the gate; semi-automated
  for contract authorship.
- **Cadence.** pre-live (operator declares guest presence and
  selects active contract); continuous (gate enforced).

### 5.5 Qdrant write redaction

- **Audits.** Any write to person-identified Qdrant collections
  (operator-episodes, people facts) traceable to an active
  contract or to the operator's own dimension.
- **Pass.** Static analysis on Qdrant write call sites; runtime
  test confirms a guest impingement is not persisted past the
  contract TTL.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 5.6 Recording / archival of person-identified data

- **Audits.** Per CLAUDE.md `systemd/README.md § Disabled Services`,
  archival is disabled. Audit confirms no service is secretly
  writing camera frames, audio, or transcripts to disk.
- **Pass.** `inotify` watch on `~/hapax-state/` and `/dev/shm/`
  enumerates all writers; cross-reference against the disabled
  list.
- **Automation.** Fully automated.
- **Cadence.** continuous; pre-live.

---

## §6. Latency and cadence audits

Per the freshness contract, every publisher declares an expected
cadence; consumers expect within 3× tolerance.

### 6.1 Publisher cadence conformance

- **Audits.** Each publisher has a Prom freshness gauge
  (e.g., `hapax_imagination_freshness_seconds`) showing seconds
  since last publish. Audit asserts all gauges < 3× expected.
- **Expected cadences (canonical):**
  - imagination — 10 Hz (100 ms)
  - compositor — 30 Hz (33 ms)
  - stimmung — 1 Hz
  - HARDM — 0.5 Hz (2 s)
  - impingements — 0.5 Hz (2 s)
  - chat signals — 0.033 Hz (30 s)
  - homage artefact — 1 Hz
  - reverie.rgba — 1 Hz
- **Pass.** All gauges within 3× expected interval.
- **Automation.** Fully automated.
- **Cadence.** continuous (1 min); pre-live.

### 6.2 End-to-end latency budgets

- **Audits.** Operator speech → caption render: target < 1.5 s.
  Operator speech → impingement → recruitment → ward emphasis:
  target < 3 s. Chat keyword → preset activation: target < 30 s
  (cooldown).
- **Pass.** Synthetic injection at each entry; measured latency
  via correlation IDs in jsonl streams.
- **Automation.** Fully automated.
- **Cadence.** per-stream (smoke); continuous (sampled).

### 6.3 Frame-budget violations

- **Audits.** `BudgetTracker` reports per-frame ward render
  duration p50 / p95 / p99; budget violations published to VLA
  via `budget_signal.py`.
- **Pass.** p99 < frame interval (33 ms at 30 Hz); budget signal
  not in degraded state.
- **Automation.** Fully automated.
- **Cadence.** continuous.

---

## §7. Observability audits

For every alert-worthy condition, four wiring points must hold:
(1) Prom metric emits, (2) Prom scrapes, (3) Grafana dashboard
shows, (4) Grafana alerts fire to ntfy.

### 7.1 Metric registration coverage

- **Audits.** Every emitter declared in
  `2026-04-15-prometheus-metrics-registry-audit.md` is registered
  at runtime; no metric defined but never incremented (dead
  emitter).
- **Pass.** Diff between declared registry and live `:9482/metrics`
  output.
- **Automation.** Fully automated.
- **Cadence.** per-stream; continuous.

### 7.2 Scrape coverage

- **Audits.** Prometheus targets list matches the running
  service inventory.
- **Pass.** Each service exposing metrics has a corresponding
  Prom target; `up{}` for each is 1.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 7.3 Dashboard render

- **Audits.** Each Grafana dashboard renders without panel
  errors; queries return data within timeout.
- **Pass.** Grafana API confirms each panel returned a non-empty
  series.
- **Automation.** Fully automated.
- **Cadence.** per-stream; periodic.

### 7.4 Alert routing

- **Audits.** Each declared alert rule is routed to ntfy
  (operator-visible) and persisted to a record (Postgres /
  Loki).
- **Pass.** Synthetic alert injected; confirmation arrives via
  ntfy + persists in record store.
- **Automation.** Fully automated.
- **Cadence.** per-stream (smoke); continuous.

### 7.5 Langfuse trace coverage

- **Audits.** Every LLM call routes through LiteLLM and emits a
  Langfuse trace; trace coverage ratio (calls with traces / total
  calls) close to 1.0.
- **Pass.** Coverage > 0.99.
- **Automation.** Fully automated.
- **Cadence.** per-stream.

---

## §8. Governance drift audits

### 8.1 Axiom registry checksum

- **Audits.** `axioms/registry.yaml` and constitutive rules
  unchanged unless via reviewed PR; runtime `shared/axiom_registry.py`
  matches checked-in registry.
- **Pass.** Hash equals expected.
- **Automation.** Fully automated.
- **Cadence.** continuous (CI); pre-live.

### 8.2 Anti-personification compliance

- **Audits.** `agents/.../personification_lint` (per
  `lint_personification.py`) produces clean run; allowlist current.
- **Pass.** Lint clean.
- **Automation.** Fully automated.
- **Cadence.** continuous (CI).

### 8.3 Frozen-files policy

- **Audits.** `scripts/check-frozen-files.py` confirms no
  frozen-file edits without active deviation.
- **Pass.** Exit 0.
- **Automation.** Fully automated.
- **Cadence.** pre-commit; pre-live.

### 8.4 Working-mode propagation

- **Audits.** `~/.cache/hapax/working-mode` content propagates to
  every consumer (logos, officium, daimonion, reverie). The
  legacy cycle_mode (dev/prod) is dead per workspace CLAUDE.md.
- **Pass.** Each consumer reports the same mode; flip-and-verify
  fixture exercises propagation.
- **Automation.** Fully automated.
- **Cadence.** continuous; pre-live.

### 8.5 Stream-mode dispatch

- **Audits.** `hapax-stream-mode` script + DEGRADED-STREAM
  toggling functions correctly. Per the HOMAGE go-live
  directive, degraded-stream is the default iteration vehicle.
- **Pass.** Mode flip exercised; downstream consumers (compositor
  routing, narrative restraint) respect mode.
- **Automation.** Fully automated.
- **Cadence.** pre-live; per-mode-flip.

### 8.6 Research condition currency

- **Audits.** Active research condition's frozen file list and
  protocol deviations recorded; no out-of-date references.
- **Pass.** `lrr-state.py` reports green.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 8.7 Expert-system blinding currency

- **Audits.** Per `2026-04-19-expert-system-blinding-audit.md` and
  `2026-04-19-blinding-defaults-audit.md`, no hardcoded threshold
  / cadence gates regressed in.
- **Pass.** Static-analysis pattern set returns no hits beyond
  declared exceptions.
- **Automation.** Fully automated.
- **Cadence.** continuous (CI); per-stream.

---

## §9. Hardware health audits

### 9.1 GPU headroom

- **Audits.** `nvidia-smi` reports VRAM free > working budget;
  utilization not pinned at 100%.
- **Pass.** Free > 4 GiB; utilization < 90% sustained.
- **Automation.** Fully automated. `gpu-audit` skill.
- **Cadence.** pre-live; continuous (30 s VRAM watchdog).
- **Failure action.** Refuse to start stream; recommend swap of
  models or restart of leakers.

### 9.2 Pi fleet heartbeat

- **Audits.** All 5 Pis (1, 2, 4, 5, 6) heartbeat within 60 s.
- **Pass.** `check_pi_fleet()` green.
- **Automation.** Fully automated.
- **Cadence.** continuous; pre-live.

### 9.3 USB camera stability

- **Audits.** All 6 cameras (3 BRIO + 3 C920) report fresh
  frames; no `device descriptor read/64, error -71` events in
  the last 10 min.
- **Pass.** Per-camera FPS within tolerance; recovery FSM in
  steady state.
- **Automation.** Fully automated.
- **Cadence.** pre-live; continuous.

### 9.4 SSD / disk free space

- **Audits.** Root, home, `/var/lib/docker`, MinIO blob store all
  > 10% free.
- **Pass.** All green.
- **Automation.** Fully automated. `scripts/disk-space-check.sh`.
- **Cadence.** pre-live; continuous (15 min).

### 9.5 CPU load and memory pressure

- **Audits.** Sustained load average < CPU count; memory
  pressure (PSI) below threshold.
- **Pass.** Green.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 9.6 Thermal

- **Audits.** GPU < 80 °C, CPU package < 85 °C, Pi cores < 70 °C.
- **Pass.** Green.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 9.7 Power supply

- **Audits.** PSU stable; `psu-stress-test.sh` periodically
  validates.
- **Pass.** No undervolt events in journal.
- **Automation.** Fully automated.
- **Cadence.** periodic; pre-live.

---

## §10. Network and OAuth audits

### 10.1 Google OAuth token scopes

- **Audits.** Each Google scope (Calendar, Drive, Gmail, YouTube
  Data, YouTube Live Streaming) holds; refresh tokens valid;
  expiry not imminent.
- **Pass.** Token introspection green for each scope.
- **Automation.** Fully automated.
- **Cadence.** pre-live (gate); continuous (24 h).

### 10.2 LiteLLM keys

- **Audits.** Anthropic + Gemini + any other provider keys
  authenticated; rate-limit headroom.
- **Pass.** Health check on each key returns 200.
- **Automation.** Fully automated.
- **Cadence.** pre-live; continuous.

### 10.3 Tailscale reachability

- **Audits.** All declared peers reachable; Pi fleet, phone,
  watch all green.
- **Pass.** `tailscale status --json` matches expected.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 10.4 DHCP / LAN stability

- **Audits.** Pi fleet IPs stable; no DHCP renewal failures
  observed (per the Pi-edge bug history).
- **Pass.** No DHCP transitions in last 24 h.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 10.5 RTMP push health

- **Audits.** MediaMTX RTMP relay (`127.0.0.1:1935`) up; YouTube
  ingest endpoint reachable; round-trip latency < 200 ms;
  reconnect FSM healthy.
- **Pass.** Synthetic stream pushed pre-live; YouTube confirms
  ingest.
- **Automation.** Fully automated.
- **Cadence.** pre-live (gate); continuous.

### 10.6 LAN firewall posture

- **Audits.** Logos API on `:8051` reachable from LAN
  (`192.168.68.0/22`) and Tailscale (`100.64.0.0/10`); not
  reachable from public internet.
- **Pass.** Probe from each side.
- **Automation.** Fully automated.
- **Cadence.** periodic.

---

## §11. Compositor regression audits

### 11.1 Per-ward render duration

- **Audits.** p50 and p99 per ward in expected range; outliers
  identified.
- **Pass.** Within budget.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 11.2 Transient texture pool reuse ratio

- **Audits.** `DynamicPipeline::pool_metrics()` reports reuse
  ratio > 0.9 sustained; allocations not climbing linearly.
- **Pass.** Green.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 11.3 Per-frame budget violation rate

- **Audits.** `budget_signal.py` not in degraded state for > 5%
  of last hour.
- **Pass.** Green.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 11.4 Degraded-signal published correctly

- **Audits.** When degraded, the signal reaches the VLA and the
  VLA degrades downstream.
- **Pass.** Forced degraded state confirms downstream propagation.
- **Automation.** Fully automated.
- **Cadence.** per-stream.

### 11.5 Shader chain compile health

- **Audits.** All WGSL presets compile clean at startup; no
  `GraphValidationError` events in the journal.
- **Pass.** Green.
- **Automation.** Fully automated.
- **Cadence.** pre-live; continuous.

### 11.6 Effect graph node inventory

- **Audits.** 56 WGSL nodes loaded; 30 presets resolvable;
  glfeedback Rust plugin loaded.
- **Pass.** Counts match.
- **Automation.** Fully automated.
- **Cadence.** pre-live.

---

## §12. Content-programming audits

### 12.1 Director-loop intent grounding

- **Audits.** Recent `intent_family` entries trace to a
  ground-truth source (vault note, sensor event, prior
  impingement). No hallucinated intents.
- **Pass.** Sampled audit confirms grounding provenance.
- **Automation.** Semi-automated; sample of 50 intents reviewed.
- **Cadence.** per-stream.

### 12.2 Objective visibility overlay firing

- **Audits.** When the operator sets an objective, the
  objective overlay (`objectives_overlay.py`) renders and the
  hero camera switcher (`objective_hero_switcher.py`) responds.
- **Pass.** Synthetic objective fires; overlay + camera
  observed.
- **Automation.** Fully automated.
- **Cadence.** per-stream.

### 12.3 Affordance-pipeline recruitment flow

- **Audits.** Impingements lead to recruitments at expected
  rate; recruitment_candidate_panel ward shows top-3 candidates
  cycling.
- **Pass.** Recruitment Prom counter increases; ward updates.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 12.4 Director loop dispatching compositional intents

- **Audits.** `compositional_consumer.dispatch` invocations
  > 0 / minute; routes resolve to wards.
- **Pass.** Counter increments; resolution rate > 0.95.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 12.5 Thompson priors sensible

- **Audits.** Thompson sampling priors per capability not
  collapsed to an extreme; learning is happening.
- **Pass.** Posterior diversity above floor.
- **Automation.** Fully automated.
- **Cadence.** periodic.

### 12.6 Programme expansion not pre-determination

- **Audits.** Per memory, programmes EXPAND affordance space,
  not replace it. Audit confirms no programme writes a hard
  capability gate.
- **Pass.** Static analysis on programme code confirms; runtime
  fixture confirms unmentioned capabilities still recruitable.
- **Automation.** Fully automated.
- **Cadence.** continuous (CI).

---

## §13. Anti-demonetization audits (multi-modal)

This class is the cross-modal fold of §1 (text), §3 (visual), §4
(audio). It exists separately because the YouTube monetization
policy is multi-modal — a stream can be flagged on aural OR visual
OR text OR overlay content. Per YouTube advertiser-friendly content
guidelines, the policy applies to "all portions of your content
including video, Short, or live stream, thumbnail, title,
description, and tags."

### 13.1 Aural surfaces

- **Audits.** Operator audio + TTS + source audio + chimes — all
  filtered for slurs, hate speech, copyrighted music
  (ContentID risk), trademark mentions.
- **Pass.** Per-modality gate confirmed; aggregated risk score
  below threshold.
- **Automation.** Fully automated for slur / keyword; ContentID
  risk semi-automated (operator reviews track list).
- **Cadence.** pre-live + continuous.

### 13.2 Visual surfaces

- **Audits.** Camera feeds + reverie + ward chrome + overlays —
  no graphic content, no nudity, no flash/strobe, no
  copyrighted image (album art with ContentID risk), no political
  imagery.
- **Pass.** Per-surface filter; sampled review.
- **Automation.** Fully automated for technical filters; manual
  for judgment calls (graphic content threshold).
- **Cadence.** pre-live + continuous.

### 13.3 Text surfaces

- **Audits.** Per §1 — all text gates green.
- **Pass.** §1 green.
- **Automation.** Fully automated.
- **Cadence.** pre-live + continuous.

### 13.4 Metadata surfaces

- **Audits.** YouTube title, description, tags, thumbnail; chat
  archive metadata; HLS manifest tags.
- **Pass.** All filtered.
- **Automation.** Fully automated.
- **Cadence.** pre-live + continuous.

### 13.5 Aggregated risk classifier

- **Audits.** A composite classifier produces a single
  monetization-risk score per minute of stream; spikes above
  threshold trigger an operator alert (not an automatic action).
- **Pass.** Classifier emits; alert routing healthy.
- **Automation.** Fully automated for emit; semi-automated for
  threshold tuning.
- **Cadence.** continuous.

---

## §14. Recording / archival audits

Per CLAUDE.md `systemd/README.md § Disabled Services`, the
archival pipeline is disabled. This audit class confirms the
disable is real and persistent.

### 14.1 No camera-frame writes

- **Audits.** No process writing JPEG/PNG to `~/hapax-state/` or
  `~/hapax-state/recordings/` or `/var/lib/...`.
- **Pass.** `inotify` enumeration finds no writers.
- **Automation.** Fully automated.
- **Cadence.** continuous; pre-live.

### 14.2 No audio capture writes

- **Audits.** No `.wav` / `.flac` / `.opus` writes from
  broadcast-adjacent audio.
- **Pass.** As above.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 14.3 No transcript persistence

- **Audits.** Daimonion STT transcripts not written to disk
  beyond the configured live cursor.
- **Pass.** No persistent transcript files outside declared
  research-condition recording windows.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 14.4 HLS archive rotation

- **Audits.** `hls-archive-rotate.py` rotates HLS segments;
  no infinite growth.
- **Pass.** Rotation enforced; oldest segment within window.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 14.5 MinIO blob store lifecycle

- **Audits.** 14-day lifecycle on `events/` prefix per workspace
  CLAUDE.md; inode count not climbing.
- **Pass.** Lifecycle enforced; inode count steady.
- **Automation.** Fully automated.
- **Cadence.** periodic (weekly).

---

## §15. Configuration drift audits

### 15.1 default.json layout

- **Audits.** `config/compositor-layouts/default.json` matches
  the version in main; runtime modifications committed back or
  reverted before stream.
- **Pass.** Diff empty.
- **Automation.** Fully automated.
- **Cadence.** pre-live.

### 15.2 Axiom registry checksum

- **Audits.** Per §8.1.
- **Pass.** Hash matches.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 15.3 Shader presets compile

- **Audits.** Per §11.5.
- **Pass.** All compile.
- **Automation.** Fully automated.
- **Cadence.** pre-live.

### 15.4 Prom targets list

- **Audits.** Per §7.2.
- **Pass.** Matches.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 15.5 LiteLLM config

- **Audits.** Routes match audit baseline (per
  `2026-04-15-litellm-config-drift-audit.md`); no fallback
  chains to Ollama for inference.
- **Pass.** Diff empty.
- **Automation.** Fully automated.
- **Cadence.** pre-live; continuous.

### 15.6 PipeWire config

- **Audits.** Active config matches operator baseline; no
  unexpected node additions per §4.7.
- **Pass.** Diff empty.
- **Automation.** Fully automated.
- **Cadence.** pre-live.

### 15.7 Streamdeck mapping

- **Audits.** `config/streamdeck.yaml` mappings active;
  `stream-deck-probe.py` confirms each button bound.
- **Pass.** All buttons resolve.
- **Automation.** Fully automated.
- **Cadence.** pre-live.

---

## §16. Cross-cutting audits

### 16.1 Time synchronisation

- **Audits.** All hosts (workstation + Pi fleet) NTP-synced
  within 100 ms of each other; mtime correlation across SHM
  freshness checks valid.
- **Pass.** `chronyc tracking` green on all hosts.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 16.2 Service dependency graph integrity

- **Audits.** Per `systemd/README.md` boot sequence, every
  declared `After=` / `Requires=` resolves; no degenerate state
  where a dependent runs while its dependency is dead.
- **Pass.** `systemctl --user list-dependencies` green for each
  livestream service.
- **Audits.** Per §9.7 also includes watchdog wiring (`Type=notify`,
  `WatchdogSec`).
- **Automation.** Fully automated.
- **Cadence.** pre-live.

### 16.3 Logs not silently growing or rotating away

- **Audits.** Journal volume per service within budget; no
  service silently emitting MB/min of warnings.
- **Pass.** Volume below threshold.
- **Automation.** Fully automated.
- **Cadence.** continuous.

### 16.4 Worktree state and branch discipline

- **Audits.** Per workspace CLAUDE.md, branch hygiene enforced;
  no stale branches across council, mcp, watch, phone repos. The
  alpha worktree on a feature branch with commits ahead would
  cause `rebuild-service.sh` to skip deploy — that condition must
  be cleared before live.
- **Pass.** All sessions on main or with active PR + green.
- **Automation.** Fully automated. `branch-audit` skill.
- **Cadence.** pre-live.

### 16.5 Build provenance

- **Audits.** `freshness-check.sh` confirms every running binary
  matches HEAD or is acceptably stale.
- **Pass.** Green.
- **Automation.** Fully automated.
- **Cadence.** pre-live; continuous.

### 16.6 Live-egress kill switch

- **Audits.** Operator has a single command (e.g., a Stream Deck
  button bound to `hapax-stream-mode private`) that takes the
  stream private within 1 s. Audit confirms the path exercised.
- **Pass.** Synthetic activation; egress confirmed cut.
- **Automation.** Fully automated.
- **Cadence.** pre-live.

---

## §17. Top-priority pre-stream gate (irreducible minimum)

The following audit subset MUST run green before any livestream
session begins. Each row is fully automated. Failure of any row
blocks stream start; operator must acknowledge before bypass (and
bypass should require explicit `--force` with a justification
logged).

| # | Class | Audit | Failure action |
|---|---|---|---|
| 1 | §1.1 | TTS slur-injection redaction smoke | block |
| 2 | §1.2 | Chat overlay slur + author redaction smoke | block |
| 3 | §1.3 | Caption strip slur smoke | block |
| 4 | §1.6 | Overlay zones broadcast-tag enforced | block |
| 5 | §1.8 | YouTube description / title / tags safety | block |
| 6 | §3.1 | Per-ward golden image diff (sampled) | warn |
| 7 | §3.7 | Safe-area respect | block |
| 8 | §4.1 | Operator mic reaches broadcast | block |
| 9 | §4.3 | TTS reaches broadcast with FX chain | block |
| 10 | §4.6 | Chime audio NOT in broadcast | block |
| 11 | §4.7 | PipeWire graph diff against baseline | warn |
| 12 | §5.1 | Face-obscure pipeline live + fail-closed verified | block (urgent) |
| 13 | §5.2 | Person-detection fail-closed | block |
| 14 | §5.6 | No archival writes | block |
| 15 | §6.1 | All publisher cadence gauges within 3× | warn |
| 16 | §7.2 | All Prom targets up | warn |
| 17 | §8.1 | Axiom registry checksum | block |
| 18 | §8.4 | Working-mode propagation | warn |
| 19 | §9.1 | GPU headroom | block |
| 20 | §9.2 | Pi fleet heartbeat | warn |
| 21 | §9.3 | All 6 cameras producing fresh frames | block |
| 22 | §9.4 | Disk free > 10% | block |
| 23 | §10.1 | Google YouTube Live token scope present and valid | block |
| 24 | §10.5 | RTMP push health (synthetic stream test) | block |
| 25 | §11.5 | Shader chain compile clean | block |
| 26 | §13.1 | Aural anti-demonetization gate | block |
| 27 | §13.2 | Visual anti-demonetization gate | warn |
| 28 | §15.1 | default.json layout matches main | warn |
| 29 | §15.5 | LiteLLM config matches baseline | warn |
| 30 | §16.6 | Live-egress kill switch tested | block |

A top-level orchestrator script (`scripts/pre-live-gate.sh`,
proposed) drives all 30 rows and produces a pass/fail per row plus
a single aggregate verdict. Operator runs it once, reads the
results, takes any remediating action, re-runs. Stream UI start
button can be hooked to require the orchestrator's last successful
verdict within the past 10 minutes.

---

## §18. Continuous-only audits (always-on instrument)

The following are not gate-shaped; they emit metrics and alerts
into the running governance loop. Listed for completeness — the
full row-by-row metric inventory lives in `2026-04-15-prometheus-metrics-registry-audit.md`.

- §2.1 SHM freshness gauges
- §2.2 Consumer cursor advance
- §2.4 JSONL torn-write detection
- §3.1 Sampled golden-image regression (5-min cadence)
- §3.4 Package-swap correctness on swap event
- §6.3 Frame-budget violation rate
- §7.4 Synthetic alert round-trip
- §7.5 Langfuse trace coverage ratio
- §8.6 Research condition currency
- §9.1–9.6 Hardware health
- §11.1–11.4 Compositor regression
- §12.3 Recruitment counter trend
- §13.5 Aggregated monetization risk score
- §16.1 Time sync
- §16.3 Log volume

---

## §19. Incident-driven audits

Incidents that should each trigger a structured audit + postmortem
record, separate from the running continuous instrument:

### 19.1 Slur leak (any modality)

- Triggered by: `hapax_speech_safety_redactions_total` increment,
  caption-render redaction event, chat-overlay redaction event,
  YouTube takedown notice.
- Audit: full call-site enumeration of the affected modality,
  reproduction of the bypass, fix dispatched as own PR, governance
  retrospective entry.

### 19.2 Face-obscure failure

- Triggered by: detector exception, frame leak past pixelation,
  consent violation on archive review.
- Audit: `face_obscure_integration.py` traceback, frame-by-frame
  audit of the bypass window, immediate stop egress + ntfy
  urgent.

### 19.3 Camera USB bus-kick

- Triggered by: `device descriptor read/64, error -71` in journal.
- Audit: per `2026-04-12-brio-usb-robustness.md`, recovery FSM
  walked; if FSM did not recover, manual remediation.

### 19.4 GPU OOM

- Triggered by: CUDA OOM, VRAM watchdog alert.
- Audit: `vram` skill; identify model that broke budget;
  remediation.

### 19.5 RTMP disconnect

- Triggered by: ingest failure beyond reconnect FSM tolerance.
- Audit: network path, YouTube ingest health, MediaMTX state.

### 19.6 Compositor stall

- Triggered by: degraded-signal sustained > 30 s.
- Audit: `studio-smoke-test.sh`, py-spy dump, frame budget
  forensics per `2026-04-14-compositor-frame-budget-forensics.md`.

### 19.7 Pre-stream gate failure

- Triggered by: any §17 row red within 60 min of stream start.
- Audit: structured failure record with operator's resolution.

---

## §20. Periodic audits (weekly / monthly)

Not gate-shaped; feed governance.

- §2.6 Cross-system signal mapping (monthly)
- §4.8 24c physical mixer state (weekly: photo)
- §8.7 Expert-system blinding currency (monthly)
- §10.6 LAN firewall posture (monthly)
- §12.5 Thompson priors sensibility (weekly)
- §14.5 MinIO lifecycle (weekly)
- §15 full configuration-drift sweep (monthly)
- CLAUDE.md rot audit per `scripts/check-claude-md-rot.sh`
  (monthly via `claude-md-audit.timer`)

---

## §21. Integration with existing audit infrastructure

Catalog rows map to existing scripts and tests where possible.
This section enumerates the mapping.

| Catalog row | Existing infrastructure |
|---|---|
| §1.1 TTS gate | `tests/test_speech_safety.py`, `shared/speech_safety.py` |
| §1.2 chat overlay | `tests/test_chat_reactor*.py`, `agents/studio_compositor/chat_reactor.py` (caplog pin) |
| §2.x wiring | `docs/research/2026-04-20-wiring-audit-alpha.md` (414 items), `scripts/freshness-check.sh` |
| §3.x ward visual | `docs/research/2026-04-20-ward-full-audit-alpha.md` (532 items), goldens at `tests/studio_compositor/golden_images/` |
| §4.x audio | `scripts/audio-topology-check.sh`, `docs/research/2026-04-14-audio-path-baseline.md` |
| §5.1 face obscure | `agents/studio_compositor/face_obscure*.py`, spec at `docs/superpowers/specs/2026-04-18-facial-obscuring-hard-req-design.md` |
| §5.x consent | `tests/test_consent*.py` (15+ files), `tests/test_axiom_audit.py`, `agents/consent_audit.py`, `scripts/drill-consent-revocation.py` |
| §6.x latency | Prom metrics inventory; freshness gauges per surface |
| §7.x observability | `docs/research/2026-04-15-prometheus-metrics-registry-audit.md`, Grafana provisioning |
| §8.x governance | `tests/test_axiom_audit.py`, `scripts/check-frozen-files.py`, `lint_personification.py`, `scripts/lrr-state.py` |
| §9.x hardware | `scripts/disk-space-check.sh`, `gpu-audit` skill, health monitor `agents/health_monitor/` |
| §10.x network | `tailscale status`, OAuth token introspection |
| §11.x compositor | `scripts/studio-smoke-test.sh`, `agents/studio_compositor/budget*.py` |
| §12.x content programming | `agents/studio_compositor/director_loop.py`, `compositional_consumer.py`, affordance pipeline |
| §13.x demonetization | composite gate (proposed); orchestrator |
| §14.x archival | `inotify` watch (proposed); journal scan |
| §15.x config drift | `2026-04-15-litellm-config-drift-audit.md`, `2026-04-14-tabbyapi-config-audit.md`, `2026-04-15-docker-compose-containers-audit.md`, `2026-04-15-systemd-user-unit-health-audit.md` |
| §16.x cross-cutting | `branch-audit` skill, `freshness-check.sh`, `audit` skill umbrella |
| §17 pre-live gate | `scripts/pre-live-gate.sh` (proposed) |
| §19 incidents | `scripts/drill-consent-revocation.py` (consent rehearsal); other rehearsals proposed |

Where the mapping shows "(proposed)", the audit class is identified
but the executor does not yet exist.

---

## §22. Governance hierarchy — who acts on failures

| Failure class | Actor | Response time |
|---|---|---|
| Content-safety gate (§1, §13) | Hapax (block) → operator (review) | block immediate, review same session |
| Wiring stale (§2) | systemd watchdog → ntfy → operator | restart auto, review within 1 h |
| Visual regression (§3) | operator (judgment) | review within 24 h |
| Audio routing (§4) | operator (judgment) | block stream, review immediate |
| Consent (§5) | Hapax (fail-closed) → operator (urgent) → governance retrospective | immediate stop, full audit |
| Latency (§6) | systemd watchdog → degraded mode → operator | degrade auto, review within 1 h |
| Observability (§7) | systemd → operator (advisory) | review within 24 h |
| Governance drift (§8) | CI block → operator | review immediate |
| Hardware (§9) | systemd watchdog → operator | depends on severity |
| Network / OAuth (§10) | systemd → operator | depends on severity |
| Compositor (§11) | budget signal → degraded → operator | degrade auto, review within 1 h |
| Programming (§12) | operator (judgment) | review within 24 h |
| Demonetization aggregate (§13.5) | operator | review within session |
| Archival (§14) | Hapax (fail-closed) | block immediate |
| Config drift (§15) | CI block → operator | review immediate |

---

## §23. Comparison to broadcast precedent

The FCC self-inspection checklist for broadcast stations
provides a useful precedent. Categories from the FCC checklists
that map to this catalog:

- **Antenna / Tower / Power.** Maps to §9 hardware health and
  §10 network — physical signal egress integrity.
- **Station logs.** Maps to §7 observability + §14 archival —
  the FCC requires logs of transmitter on/off, outages,
  EAS tests; the Hapax analogue is Prom metrics + journal
  + Langfuse traces.
- **EAS tests.** No direct analogue (no public-safety
  obligation), but the live-egress kill switch test (§16.6) is
  conceptually similar — a periodic confirmation that an
  emergency action path works.
- **Main studio requirements.** Maps to §16 cross-cutting and
  §15 config drift — the studio is configured as declared.
- **Political file.** No analogue (no political broadcasting),
  but §1.11 political flashpoints lexicon is the protective
  inverse.

The YouTube Partner Program advertiser-friendly content guidelines
provide the demonetization-prevention precedent. Categories that
map to §13:

- **Profanity, hate, harassment.** §13.1, §13.2, §13.3.
- **Inappropriate language / inappropriate use of family
  characters / sensational content.** §1.1, §1.10, §1.11.
- **Inauthentic content (renamed July 2025).** Less applicable
  for live performance — this Hapax stream is genuinely
  performative, not template-mass-produced.
- **Copyright.** §1.9, §13.1 (ContentID risk on source music
  played through the mixer).
- **Thumbnail / title / description / tags.** §1.8.

The catalog therefore adopts the multi-modal stance from YouTube
(every modality is a policy surface) and the systematic
self-inspection stance from FCC (every category gets a checklist
that runs before the broadcaster can vouch for the operation).

---

## §24. Open questions to operator

These five questions guide the prioritisation of audit
implementation work and select among design tradeoffs.

1. **Block-vs-warn calibration on the pre-live gate (§17).**
   The proposed table marks 22 of 30 rows as "block" and 8 as
   "warn". Block-heavy calibration favours operator dignity at
   the cost of stream-start friction. Warn-heavy favours
   readiness at the cost of leak risk. Where on the spectrum
   does the operator want the default, and which specific rows
   should swap calibration?
2. **Allow-list authorship for content-safety gates (§1).**
   The catalog proposes per-domain allow-lists (proper nouns,
   approved trademarks, public collaborator names). Should
   allow-list authorship be operator-only, or can Hapax
   propose additions through a normal review path? The
   trade is operator load vs autonomous capture of new safe
   vocabulary.
3. **Aggregate monetization-risk score (§13.5) — alert vs
   action.** The catalog stops at "operator alert" rather than
   automatic stream pause / private toggle. Should crossing a
   high threshold trigger an automatic stream-private (with
   notification), or stay advisory?
4. **24c hardware mixer (§4.8) — investment in test signal
   injection.** The mixer's state cannot be read; the
   catalog proposes a test-signal injection rig pre-live.
   Implementation cost is non-trivial. Is the value worth the
   build, or does an operator photo of the front panel suffice
   as the pre-live audit?
5. **Periodicity of the full sweep.** The catalog distinguishes
   pre-live, per-stream, continuous, periodic, and
   incident-driven cadences. Periodic is currently scoped
   monthly. Given the LRR pace and the rate of system change,
   should periodic be weekly during R&D periods and monthly
   during steady-state?

---

## Sources cited

In addition to the local research docs and CLAUDE.md files
referenced inline:

- [YouTube Advertiser-friendly content guidelines](https://support.google.com/youtube/answer/6162278)
- [YouTube channel monetization policies](https://support.google.com/youtube/answer/1311392)
- [YouTube Partner Program 2026 Requirements](https://shortvids.co/youtube-partner-program-requirements/)
- [FCC FM Broadcast Station Self-Inspection Checklist](https://www.fcc.gov/document/fm-broadcast-station-self-inspection-checklist)
- [FCC TV Broadcast Station Self-Inspection Checklist](https://www.fcc.gov/document/tv-broadcast-station-self-inspection-checklist)
- [FCC Operating and Maintenance Logs for Broadcast Stations](https://www.fcc.gov/document/operating-and-maintenance-logs-broadcast-and-broadcast-auxiliary)
- [FCC Logging Requirements for Broadcast Stations](https://www.fcc.gov/document/logging-requirements-broadcast-stations-docket-14187)
- [EAS Self-Inspection Checklist for Broadcasters (Colorado Broadcasters Association)](https://www.coloradobroadcasters.org/eas/fcc/eas-self-inspection-checklist-for-broadcasters/)
