# Context-Void Sweep Research Dossier

**Date:** 2026-04-18
**Scope:** 19 research threads (tasks #140–#158) dispatched to expand the context-void-sweep recoveries into spec-ready findings.
**Status:** ✅ COMPLETE — all 19 agents returned 2026-04-18.
**Operator policy:** "Provisionally approve every research result as it comes in." Synergy pass **deferred to last** (spans both dossiers).

---

## 1. Dispatch Manifest

19 research agents dispatched 2026-04-18, one per CVS item. Output files `/tmp/cvs-research-<task_id>.md`. Background dispatch; notifications trigger this dossier's appends.

| Task | Title | Agent ID | Status |
|---|---|---|---|
| #140 | Stream Deck control surface | abe4b556e905a5edb | ✅ returned |
| #141 | KDEConnect bridge | ae49816b120853543 | ✅ returned |
| #142 | Vinyl half-speed toggle | a5ba6178210548f70 | ✅ returned |
| #143 | ARCloud integration | a1a2a133d3bef7c12 | ✅ returned (REJECTED by operator — real ask is cadence) |
| #144 | YT description auto-update | a21fd9b4c35a559b1 | ✅ returned |
| #145 | 24c YT ducking coverage | a3ecfd803826dbc42 | ✅ returned |
| #146 | Token pole reward mechanic | a66613f83a4e8d604 | ✅ returned |
| #147 | Token pole qualifier research | ae24f4255f0622fd9 | ✅ returned |
| #148 | Reactivity sync gap | a64a30040100da85f | ✅ returned (PARTIALLY RESOLVED — sync gap remains) |
| #149 | 24c reactivity contract | acb19e5bab91903e9 | ✅ returned (surfaces stale channel-doc bug) |
| #150 | Image classification underuse | aa374fcabdd2929af | ✅ returned (1-of-17 signals consumed) |
| #151 | Cross-agent audit posture | aaff495c5cacd8cfc | ✅ returned (dormant policy doc, not global CLAUDE.md) |
| #152 | Session naming enforcement | a472695135cb5f3fc | ✅ returned (root cause + 10-line fix) |
| #153 | Worktree cap investigation | a14ba4b978134ce53 | ✅ returned (no active overflow; doc drift) |
| #154 | Hookify glob noise fix | a85b3118b5f9ff8de | ⛔ DROPPED per operator 2026-04-18 (already resolved) |
| #155 | Anti-personification audit | af28276a1fb02f0e1 | ✅ returned (2 live violations) |
| #156 | Role derivation methodology | aca133b35f101f413 | ✅ returned (methodological gap — new spec) |
| #157 | Non-destructive overlay layer | a531f83ac1762f556 | ✅ returned |
| #158 | Director "do nothing" regression | ab43302ac0f59bd03 | ✅ returned (INVARIANT VIOLATED 25% LIVE) |

---

## 2. Findings (as they return)

### Task #141 — KDEConnect Bridge (interim control)

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-141.md`

**Key findings:**
- KDEConnect is live + paired (Pixel 10, id `aecd697f91434f7797836db631b36e3b`). Already used by `agents/hapax_daimonion/backends/phone_awareness.py` for battery/connectivity telemetry.
- **Right surface:** `kdeconnect_runcommand` module — supported but not yet configured (empty `~/.config/kdeconnect/<id>/kdeconnect_runcommand/`).
- **No new systemd unit needed.** KDEConnect daemon inherits user session. Runcommand entries invoke `scripts/hapax-ctl <cmd>` → one-shot WebSocket to `ws://127.0.0.1:8052/ws/commands` (same endpoint Stream Deck adapter uses).
- **Auth = pairing.** mTLS per-device certs + 127.0.0.1-only relay + single-operator axiom → no additional tokens.
- **hapax-phone is NOT redundant.** Phone is passive telemetry producer (health + context → logos-api:8051). KDEConnect is bidirectional control channel. They coexist cleanly.
- **Relation to CVS #1 Stream Deck:** both feed same command registry. KDEConnect is strict interim; Stream Deck supersedes on delivery. No cleanup churn.

**Recommended action:**
Single 1–2 day PR — `scripts/hapax-ctl` + `config/kdeconnect-runcommand.json` (parity with `config/streamdeck.yaml`) + idempotent installer script + runbook + one test. Zero systemd, zero logos-api, zero Rust.

**Provisional approval:** ✅
**Spec stub:** _pending_
**Dependencies:** Depends on Stream Deck command registry (reused). Blocks no downstream work.

---

### Task #144 — YouTube Description Auto-Update

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-144.md`

**Key findings:**
- **Infrastructure is ~90% shipped, 0% verified live.** Two implementations exist:
  - `scripts/youtube-player.py::LivestreamDescriptionUpdater` — raw urllib, reads `attribution-log.md`, auto-discovers broadcast via `liveBroadcasts.list`, writes via `videos.update`.
  - `agents/studio_compositor/youtube_description.py` + `youtube_description_syncer.py` — hardened quota-aware path, google-api-python-client, idempotent hash-dedup, `assemble_description()` for condition/objective state.
- **Single blocker:** OAuth consent for `youtube.force-ssl` scope. Code logs warning and silent-skips until operator runs `scripts/youtube-auth.py`.
- **Quota math:** 50u per `videos.update`, 2000u/day cap, 5 updates/stream → max ~39 description updates/day within budget.
- **The actual missing wire:** `scripts/chat-monitor.py` has zero URL extraction. Operator's flagged path — chat links → attribution → description — is not yet connected. Three additions needed: URL extractor, kind classifier, typed `AttributionSource` protocol.
- **"Powerful reusable" framing:** The pattern generalizes. An `AttributionSource` protocol lets SPLATTRIBUTION (#127), homage artefacts, chat-ward DOI research (#123), vinyl detection, condition/objective state, and yt-react content all backflow into description sections via one syncer. **THIS is what the operator meant.**
- **`liveChatId` sidecar** is orthogonal — post ephemeral citation acknowledgments into chat itself via `liveChatMessages.insert` (same 50u cost, different semantics).

**Recommended action:**
(1) Operator runs `scripts/youtube-auth.py` once (unblocks path). (2) New PR: chat URL extractor + classifier + `AttributionSource` protocol + wire into `youtube_description_syncer`. (3) Document the pattern as reusable attribution backflow.

**Provisional approval:** ✅
**Spec stub:** _pending_
**Dependencies:** Blocked on OAuth consent (operator action). Synergizes with #127 SPLATTRIBUTION, #123 chat ward.

---

### Task #145 — 24c Mix Ducking (YT/React direction)

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-145.md`

**Verdict:** KEEP OPEN — PARTIAL COVERAGE. New spec needed.

**Key findings:**
- Three ducking paths shipped, all in the SAME direction (operator/TTS → YouTube):
  - PR #778 — TTS envelope on the 3 YT slot volumes
  - PR #943 — operator VAD → same envelope
  - PR #1000 — LADSPA sidechain on `hapax-ytube-ducked` sink, keyed by operator mic
- **The direction the operator asked for is the REVERSE:** YouTube/React plays → 24c hardware mix ducks. **Zero wiring.**
- Spec #134 (audio pathways) refines the operator→YT direction only; does not address the reverse.
- **YT-side normalization is absent.** No loudnorm/LUFS/replaygain hits in `config/pipewire/` or compositor code.
- The GDO handoff (`docs/streaming/2026-04-09-garage-door-open-handoff.md` §6.5) is the verbatim two-direction brief — both directions were committed, only one shipped.

**Recommended action:**
Mirror of PR #1000 shape — `hapax-24c-ducked` sink + `sc4m_1916` sidechain keyed on YT output, ~6 dB / 2:1 / slow release to match "not A LOT". Plus YT normalization (~−16 LUFS loudnorm on YT sink). Plus a three-way interaction test matrix extending R19 from LRR Phase 9 spec.

**Provisional approval:** ✅
**Spec stub:** _pending_
**Dependencies:** Extends #134 audio pathways spec. Blocks nothing. Synergy with #149 24c reactivity contract (different direction, same source).

---

### Task #140 — Stream Deck Control Surface

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-140.md`

**Key findings:**
- **UNEXPECTED:** Stream Deck MK.2 hardware already plugged in (USB `0fd9:0080`). ~80% of adapter code already written and tested (LRR Phase 8 item 6, coded but never deployed).
- **4 gaps keeping it off the air:**
  1. Systemd unit `hapax-streamdeck-adapter.service` not installed.
  2. `config/streamdeck.yaml` binds 12 keys to commands that DON'T EXIST in command registry (`studio.camera_profile.set`, `studio.stream_mode.toggle`, `research.condition.{open,close}`, etc.).
  3. `streamdeck` python package not in `pyproject.toml`.
  4. No udev rule at `/etc/udev/rules.d/60-streamdeck.rules` → hidraw permission denied.
- Library choice (`python-elgato-streamdeck`), dispatch path (WS relay at `:8052`), degraded behavior, config shape, and systemd posture all correct. No open design questions.
- **Architectural flag:** `:8052` relay is in-process with Tauri → Stream Deck dies if Logos app closes. Recommend backend commands POST directly to `logos-api :8051` rather than through Tauri.
- **Relation to CVS #2 KDEConnect:** supersede, not "do first" — Stream Deck adapter + hardware both exist; KDEConnect would duplicate effort.

**Recommended action:**
Two PRs. **PR A:** 7 command-registry registrations (~150 LOC frontend + minor backend). **PR B:** 1-2 hour deployment chore (`uv add streamdeck` + udev rule + systemd enable).

**Provisional approval:** ✅
**Spec stub:** _pending_ (tight — mostly PR-writing, not design work)
**Dependencies:** Blocks CVS #3 (vinyl rate keys), CVS #142 (rate control surface).

---

### Task #142 — Vinyl Half-Speed Correction + Toggle

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-142.md`

**Key findings — ACTIVE CORRECTNESS BUG SURFACED:**
- **Handytraxx Play has no continuous half-speed fader.** Operator is almost certainly playing 45 RPM records on the 33⅓ setting → **0.741x** (~74%), not literally 0.5x. Pitch knob is ±10% fine-tune.
- Other achievable "half-speed-ish" presets: 0.427x (78-on-33), 0.577x (78-on-45). **The signal must be a float rate, not a boolean.**
- **Partial infra exists (boolean-only):** `logos/api/routes/studio.py:463-481` `POST /studio/vinyl-mode/toggle` → writes `/dev/shm/hapax-compositor/vinyl-mode.txt`; polled by `agents/studio_compositor/state.py:476-490`; gates `audio_capture.py:152-153` and `fx_chain.py:150-152`.
- **🚨 HIDDEN LANDMINE (BUG):** `scripts/album-identifier.py:295-346` **hardcodes a 2× ffmpeg restore** (`asetrate=88200,aresample=44100`) unconditionally. Gemini prompts (L404, L532) lie: "played at reduced speed, sped back up." This is wrong at 0.741× — ACRCloud receives a 1.48× track and can't match. **Primary correctness failure to fix.**
- **BPM gap:** `shared/beat_tracker.py::estimate_bpm` has no rate compensation. At 0.74× a 120 BPM track reports 89 BPM; director's music framing + MIDI/reactivity consumers see wrong tempo.
- **Contact-mic scratch detection is safe** (keys on 2–16 Hz arm motion, independent of platter RPM).

**Recommended action (3-PR breakdown):**
- **PR A:** Core signal `vinyl_playback_rate: float` via `/dev/shm/hapax-compositor/vinyl-playback-rate.txt` (1.0 = off). Legacy `vinyl-mode.txt` becomes shim mapping `"true"` → `0.741`. Fix album-identifier rate correction. Fix BPM nominalization.
- **PR B:** Reactivity/director parameterization on rate float.
- **PR C:** Control surfaces — Stream Deck (#140) `studio.vinyl_rate.set` keys for {1.0, 0.741, 0.577, 0.5}, KDEConnect (#141) POSTs the same endpoint, Logos UI command-registry entry.

**Open question:** Confirm with operator which preset is actually in use (45-on-33 vs literal 0.5× via external DSP).

**Provisional approval:** ✅
**Spec stub:** _pending_
**Dependencies:** Prerequisite for #143 (cadence tuning moot until rate is parameterized). Orthogonal to #127 SPLATTRIBUTION (which only detects `vinyl_playing: bool`). #140/#141 ride on #142's endpoint.

---

### Task #143 — ARCloud / IR Feed Cadence

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-143.md`. **ACRCloud already rejected by operator; scope narrowed to IR cadence control.**

**Key findings:**
- **ARCloud = ACRCloud, dead end already ratified.** Credentials exist at `pass acrcloud/*`, but the only live reference in code is a **stale docstring** in `scripts/album-identifier.py` lying about the ID path — actual winning pipeline is Gemini Flash multimodal (IR image + 2×-restored audio). ACRCloud + AcoustID confirmed-failed for underground hip-hop catalog (`docs/streaming/2026-04-09-garage-door-open-handoff.md` §1.3, §7.9). **Recommend NOT integrating**, fix the stale docstring.
- **"Better control over fresh feed from the IR" is the real ask.** Three cadence layers are all hardcoded:
  - Layer A: `scripts/album-identifier.py` polls Pi-6 at 5s with 15–30s cooldown ← operator's target
  - Layer B: `pi-edge/hapax_ir_edge.py` captures at 5fps, posts every 2s, motion-gated skip
  - Layer C: `agents/content_resolver/` is misnamed (watches imagination fragments, unrelated)
- **Clean surface fit:** 3 new `logos-api` routes + `/dev/shm/hapax-compositor/album-cadence.json` file-bus state = entire implementation.

**Recommended action:**
Two small PRs. (1) Delete/fix ACRCloud docstring. (2) Cadence control endpoint + Stream Deck/KDEConnect bindings (fast/normal/slow/pause).

**Provisional approval:** ✅ (scope: cadence only, not ACRCloud)
**Spec stub:** _pending_
**Dependencies:** Synergizes with #127 SPLATTRIBUTION (fold ACRCloud rejection as a closed-exploration footnote). Uses #140 Stream Deck surfaces.

---

### Task #147 — Token-Pole Qualifier Research (Governance)

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-147.md`

**Key findings:**
- **Load-bearing axioms identified:** `interpersonal_transparency` + T0 `it-consent-001`, `it-irreversible-broadcast`, `management_governance`, precedent `sp-hsea-mg-001` (draft-as-content). All three qualifier risks stack here.
- **Inheritable precedent:** `agents/studio_compositor/chat_reactor.py` already has the consent-safe template — "no per-author state, no persistence, no author in logs" with a caplog test enforcing it. The qualifier code MUST inherit this exact pattern.
- **Operational line participatory ↔ exploitative:** Could the mechanic run with author + text stripped? Token-pole under proposed rubric: YES. Tiered emote systems: NO.
- **Critical design choice — none of the three qualifiers requires the LLM to *like* the message.**
  - **Contributive** = novelty (embedding distance + reference token)
  - **Interesting** = Shannon-surprise
  - **Positive** = absence-of-disqualifier (negative-defined)
  - Deliberately avoids training viewers to please a flattery classifier — the core parasocial exploitation pattern.
- **Deterministic payout** is the #1 anti-addiction move from attention-economy literature (Schüll 2012 / Griffiths 2018). Token climb must be visible + predictable; variable-ratio spew timing is the exact addiction vector to avoid.
- **Ledger schema constraint:** `{window_start, c_count, i_count, total_contribution}` — counter dict, no text, no author, verdicts as enums never rendered on-stream. Stays inside `it-irreversible-broadcast`.

**Recommended action:**
Rubric in §7–8 of `/tmp/cvs-research-147.md` is ready for CVS #146 (token pole reward mechanic) to import verbatim. Three open operator questions flagged (positive signal shape, verdict auditability, opt-out gesture) — operator review before mechanic codes.

**Provisional approval:** ✅
**Spec stub:** _pending_
**Dependencies:** Blocks CVS #146 (rubric is the input constraint).

---

### Task #148 — Reactivity Sync/Granularity Gap

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-148.md`. **Verdict: PARTIALLY RESOLVED.**

**Key findings:**
- **Bloom compounding — RESOLVED** (2026-04-05, commit `1ffb1a30d`). bloom.alpha scale cut 2.0 → 1.0. `agents/effect_graph/pipeline.py:268-277` enforces additive-with-clamp. Bloom node declares `alpha max=1.5`. Amplitude runaway structurally prevented.
- **Sync gap — NOT RESOLVED.** DSP runs at 93 fps (10.7 ms chunks in `audio_capture.py`), but `fx_tick_callback` polls at **30 fps** via `GLib.timeout_add(33, ...)` in `lifecycle.py:191`. Onsets between render ticks wait 0–33 ms (mean ~16.5 ms) — produces operator's "own pulse" perception.
- Filed as Sprint-3 backlog items 179–181, zero fix commits as of HEAD (`8c86a1bef`).
- **A+ livestream (#74–#78)** was CPU/GPU/encoder perf; never touched `audio_capture.py`, `fx_tick.py`, or modulator. **Director sim (#91)** is compositional cadence (LLM, 8–150 s), orthogonal.

**Recommended action:**
**Simple fix (~2 hr):** wall-clock peak-hold in `audio_capture.py::get_signals`. Fallback: `fx_tick` cadence 30 → 60 Hz (~half day, doubles per-tick work).

**Provisional approval:** ✅
**Spec stub:** _pending_ (small — fits a fix PR more than a spec)
**Dependencies:** Blocks #149 (sync fix multiplies across every registered reactivity source; do it first).

---

### Task #149 — 24c Global Reactivity Contract

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-149.md`. **SURFACES STALE DOC BUG.**

**Key findings:**
- **🚨 Channel assignments are WRONG in specs.** Live PipeWire config (`~/.config/pipewire/pipewire.conf.d/10-contact-mic.conf`) has **Cortado on LEFT (FL / Input 1)** and `mixer_master` on RIGHT (FR / Input 2). 2026-03-25 contact-mic spec and `docs/hardware/cable-inventory.md` both say the **opposite**. Fold correction into #134 audio pathways.
- **Reactivity asymmetry is the real directive.** Today only `mixer_master` (right) drives shader modulation — 13 bindings in `presets/_default_modulations.json` read its 18+ signals. Cortado on left has its own DSP but signals go to perception + twitch_director, NOT the shader uniform bridge. Inputs 3-8 have no loopback.
- **Contract shape:** `AudioReactivitySource` Protocol `(name, pw_target, channel_role, rate, chunk)` + namespaced signal keys (`mixer.energy`, `desk.onset_rate`, etc.) + `AudioReactivityRegistry` that `fx_tick` reads each frame. Legacy unprefixed names become aliases — cleans up Sprint 3 F2 dead-alias debt (`audio_rms`, `audio_beat`).
- **Sequencing:** #134 (channel ground truth + topology) → **#148 first** (sync fix) → #149 Phase A (extract `MelFFTReactivitySource`, no behavior change) → Phase B (desk as second reactive source) → Phase C (auto-discover 24c channels) → Phase D (dedupe daimonion's duplicate FFT DSP).
- **Right-channel content:** no explicit doc, inferred from vocal-chain + contact-mic-wired memories — Input 2 carries operator's external mixer bus (Evil Pet / S-4 / turntable / MPC).

**Recommended action:**
Four-phase PR sequence after #148 ships. Phase A first (refactor without behavior change), Phase B adds desk-as-reactive-source.

**Provisional approval:** ✅
**Spec stub:** _pending_ (MULTI-PHASE — plan needed, not just spec)
**Dependencies:** Blocks on #148 (sync fix); extends #134; closes daimonion duplicate-DSP debt.

---

### Task #151 — Cross-Agent Audit Preparedness

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-151.md`. **Verdict: DORMANT POLICY DOC (option c).**

**Key findings:**
- **All audit tooling already exists.** pr-review-toolkit (6 specialized agents incl. silent-failure-hunter, code-reviewer), superpowers requesting/receiving-code-review, axiom-check/sweep, beagle-python/react/ai reviewers, built-in `security-review` and `deploy-check`.
- **Hook-level gates already agent-agnostic.** 12 PreToolUse/BeforeTool hooks have parity between Claude and Gemini settings; `hooks/scripts/gemini-tool-adapter.sh` translates Gemini JSON → Claude format.
- **Gemini dormant.** Handoff doc confirms Gemini collapsed 2026-04-15T22:31Z. No `relay/` directory, no `gemini.yaml`, no heterogeneous agent active.
- **Missing piece is policy wrapper, not tooling.** Nothing currently distinguishes "Claude-authored PR" from "Gemini-authored PR."

**Recommended action:**
Ship `docs/policies/heterogeneous-agent-audit-policy.md` — five-surface checklist (commits, plans, research, hooks/settings, axioms) + single advisory hook at `hooks/scripts/heterogeneous-agent-detect.sh` nudging reviewers when non-Claude author detected on `gh pr create`. Combined under 200 LOC. **Do NOT add to global CLAUDE.md** (no payload, permanent noise). **Activation trigger:** operator announces new Gemini session → flip hook advisory-to-blocking, create `relay/gemini.yaml`.

**Provisional approval:** ✅
**Spec stub:** _pending_ (small — policy doc + advisory hook)
**Dependencies:** None.

---

### Task #152 — Session Naming Enforcement

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-152.md`. **Root cause + minimal fix identified.**

**Key findings:**
- **Two identity systems exist; wrong one is wired.** `~/.local/bin/hapax-whoami` is the authoritative identity utility (walks /proc up to foot terminal, reads Hyprland window title). **Operator convention = window title IS identity.** But `hapax-whoami` has **zero grep hits** in `hooks/scripts/` — never called at SessionStart.
- **Bug:** `session-context.sh:405-421` uses **mtime-staleness heuristic** comparing `alpha.yaml` / `beta.yaml` mtimes. Delta + epsilon not in branching table.
- **Failure reconstruction:** Pre-reboot writes left `alpha.yaml` (mtime 2026-04-15 14:53) and `beta.yaml` (mtime 2026-04-16 13:38) with large skew. On reboot, the session in `hapax-council--beta/` ran the hook, picked `ROLE=alpha` from staleness math without checking cwd or window title.
- **Onboarding docs assume cwd-as-identity** (alpha=`hapax-council/`, beta=`hapax-council--beta/`) but nothing enforces it. Only `onboarding-delta.md` cites `hapax-whoami` as authoritative.
- **Repo copy of `hapax-whoami` is stale** — missing the `gemini` token the installed copy has.

**Recommended action:**
10-line rewrite of `session-context.sh:405-421`: call `hapax-whoami` first, fall back to cwd mapping (covers delta/epsilon), **drop the staleness heuristic entirely**. Add cwd-vs-whoami cross-check assertion. Sync repo script to installed version. No new persistent state file needed.

**Provisional approval:** ✅
**Spec stub:** _not needed_ (this is a 10-line fix, go straight to PR)
**Dependencies:** None.

---

### Task #153 — Worktree Cap Workflow (Investigation)

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-153.md`. **Verdict: NO ACTIVE OVERFLOW — doc drift only.**

**Key findings:**
- **No active overflow.** `git worktree list` shows 4 entries: alpha (main), beta (`beta-phase-4-bootstrap`), q310-deps, and rebuild-scratch infra. Within current 4-session cap.
- **Hook already hardened 2026-04-12** after the incident. `hooks/scripts/no-stale-branches.sh:143-159` caps at 4 session worktrees (alpha + beta + delta first-class + 1 spontaneous) and **excludes `/.cache/` paths** so rebuild-scratch no longer fights delta for the spontaneous slot.
- **Workspace CLAUDE.md is STALE.** `~/projects/CLAUDE.md` (symlink → `~/dotfiles/workspace-CLAUDE.md`) still says "three worktree slots, strictly enforced." Hook enforces four. Doc/behavior contradiction.
- **No cleanup automation.** No timer, no post-merge hook, no PR-merge callback removes worktrees. Manual cleanup only. Likely drift mechanism.
- **3 stale local branches** (`beta-backlog-merge`, `queue-241-rifts-labeler-cherry-pick`, `research/q310-pyproject-deps-drift`) exist without worktrees but block new branch creation.

**Recommended action:**
(1) Update dotfiles CLAUDE.md (3 → 4 slots, add delta). (2) Add post-`gh pr merge` worktree cleanup hook. (3) Run `/branch-audit` for the 3 orphan branches. Keep 4-slot model; don't tighten back to 3.

**Provisional approval:** ✅
**Spec stub:** _not needed_ (small fix set — doc + hook + audit run)
**Dependencies:** None.

---

### Task #156 — Role Derivation Methodology

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-156.md`. **Verdict: METHODOLOGICAL GAP — NEW SPEC.**

**Key findings:**
- **Gap is methodological, not code.** The 8 Phase-7 roles in `axioms/roles/registry.yaml` were authored top-down from the 2026-04-16 reframe. Framework-level citations exist (ANT, Clark, Gibson) but per-role per-function derivation does not. Only 2 of 8 roles (partner-in-conversation, addressee-facing) carry literature anchors through to function mechanics.
- **"General case" hole.** Phase 7 reframe dissolved the functional layer intentionally (activities-not-roles), pushing per-cadence function catalogs into "activities carried out by the role" — **never catalogued**. Registry has outputs (`answers_for`) without process (decision cadence). This is what operator meant by "effects should be active directorial decisions" — no per-cadence decision schedule.
- **Hapax-specific adjustment column missing.** The "strange tools/constraints/goals" column (livestream-IS-research-instrument, affordance pipeline, continuous DMN/CPAL, 6-camera + reverie, corporate_boundary, OSF pre-reg, no session boundaries) shapes each role away from its general-case baseline but is not recorded anywhere.

**Recommended action:**
Three-phase methodology:
- **Phase A:** general-case literature + cadence table per role
- **Phase B:** Hapax adjustment 4-column table (role · general-case · Hapax-adjusted · evidence)
- **Phase C:** operationalization in registry with grep targets + research-doc refs

Ship: `docs/superpowers/templates/role-derivation-template.md` + `hooks/scripts/role-derivation-gate.sh` + retroactive backfill starting with **livestream-host** (urgency from #155 anti-personification) then **partner-in-conversation** (smallest lift, Clark anchors exist). Template + one worked example first; schema extension + CI gate in follow-up PR.

**Provisional approval:** ✅
**Spec stub:** _pending_ → `docs/superpowers/specs/2026-04-XX-role-derivation-research-template-design.md`
**Dependencies:** Reinforces #155 anti-personification. Bounded per-cadence functions cannot slide into identity.

---

### Task #146 — Token Pole Reward Mechanic

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-146.md`

**Key findings:**
- **🚨 Current pole is LLM-token-spend-driven, NOT chat-contribution.** `TokenPoleCairoSource` reads `/dev/shm/hapax-compositor/token-ledger.json`; writers are `director_loop.py`, `album-identifier.py`, `chat-monitor.py`. Superchat = $1→500 tokens, membership = 1000 tokens flat. Threshold = `5000 * log2(1 + log2(1 + active_viewers))`. **Fundamental redesign for chat-contribution.**
- **Ethical foundation already codified** — 7 principles from `docs/streaming/2026-04-09-garage-door-open-handoff.md §3.1`: thermometer-not-scoreboard, measure-structure-not-quality, fixed-transparent-relationship, sub-logarithmic scaling, never-loss-frame, recursion-is-the-feature, don't-reward-sentiment. Absorbed as constitutional foundations in Phase 7 persona spec.
- **Natural input:** Chat classifier T0-T6 in `chat_classifier.py`. T4=1, T5=3, T6=8, sub=20, donation capped. Multiplied by `audience_engagement` from `chat_signals.py`. **No sentiment axis.**
- **Two-band ledger proposed:** additive incoming (pole position, one-way) + spendable `reward_credits` (consumed at explosion for credits-sized glyph spew). Vampire-survivor scaling: `n_particles = clamp(20, 400, sqrt(credits)*3)`.
- **Glyphs, not emoji.** Px437 IBM VGA 8×16 (already in BitchX homage + legibility_sources), block/math/arrow unicode, Gruvbox Hard Dark palette. Consistent with design language + HOMAGE.
- **Difficulty curve** from session-start timestamp. Sub-linear escalation to ~5× over 4 h, published to `/dev/shm` for transparency.
- **Twitch NOT wired.** `twitch_director.py` is "twitch-speed" moves, not Twitch.tv. Only YouTube Live via `chat-downloader` library. Twitch EventSub is orthogonal follow-on.
- **#147 integration:** current T5 rule (any research keyword bumps tier) is a credit-farming surface. Qualifier v2 should require structural linkage to active research condition. **Don't block v1 on this.**

**Recommended action:**
Two-phase: (1) Redirect pole input from LLM-token to chat-contribution using #147 rubric. (2) Add spendable reward_credits band + glyph particle system. Preserve existing 7 ethical principles as constitutional constraints.

**Provisional approval:** ✅
**Spec stub:** _pending_
**Dependencies:** Consumes #147 qualifier rubric. Extends existing `token_pole.py` + `chat_classifier.py`.

---

### Task #150 — Image Classification Underuse

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-150.md`. **Massive capability gap.**

**Key findings:**
- **Capability inventory:** YOLO-World + YOLO11m + YOLO11m-pose + SCRFD + HSEmotion + MediaPipe FaceMesh + MediaPipe Hands + Places365 + SigLIP-2 + ByteTrack + CrossCameraStitcher + persistent `SceneInventory`. All write to `perception-state.json` every second.
- **🚨 Current consumption is almost nothing.** Livestream director path reads **ONE** RGB-vision signal: `visual.detected_action == "away"` in `twitch_director.py`. Narrative director prompt serializes `PerceptualField` including vision, but no deterministic rule binding scene/object/gesture signals to compositional moves. "Hero mode" is `objective_hero_switcher.py` routing on vault-objective activity — ignores vision entirely. VLA consumes gaze/emotion/posture for stimmung, but stimmung doesn't reach compositor's compositional decisions.
- **16 unused signals:** `per_camera_scenes`, `scene_type`, `top_emotion`, `hand_gesture` (RGB), `gaze_direction` (RGB), `posture` (RGB), `overhead_hand_zones` (IR version used, RGB version not), `per_camera_person_count`, `ambient_brightness`, `color_temperature`, `operator_confirmed`, `emotion_valence/arousal`, `scene_state_clip`, `detected_objects`, `frustration_score`, `gesture_intent`. Plus entire `SceneInventory` API.
- **Missing plumbing:** `dispatch_preset_bias` accepts `fx.family.<family>` but no scene → family mapping exists. Ward families exist but nothing emits them from vision.

**Top-3 priority integrations (highest impact per effort):**
1. **Scene → preset-family bias** via new `scene_family_router.py` + operator-editable `config/scene-family-map.yaml`.
2. **Object-presence → ward triggers** (zero new inference; pure `SceneInventory` reads).
3. **`per_camera_person_count` hero-gate** (one-line fix in `dispatch_camera_hero`, kills "hero is empty room" bug flagged in 2026-04-18 viewer-experience audit).

**Adjacencies:** depends on #135 stable camera roles; supplies 96 of HARDM's 256 cells (#121); #150 and #136 share YOLO track layer (scene routing vs person following).

**Provisional approval:** ✅
**Spec stub:** _pending_ (multi-phase — 3 priority integrations per PR)
**Dependencies:** Depends on #135 camera naming. Feeds #121 HARDM and #136 follow-mode.

---

### Task #157 — Non-Destructive Overlay Effects Layer

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-157.md`

**Key findings:**
- **Two senses of "overlay" exist:**
  - **Cairo overlay zones** (`overlay_zones.py`) — post-shader, pure chrome. NOT the subject.
  - **`content_layer` WGSL node** — content slots composited INSIDE the shader graph. **IS the subject.** Operator's concern is destructive effects running *upstream* of `content_layer` so its base `tex` is already mangled.
- **Current preset topology is uniform** across all 28 presets: `@live → [effects] → content_layer → postprocess → out`. **No separation between "effects applied to video" and "effects applied to overlay."**
- **Shader classification (56 WGSL nodes):** ~23 non-destructive, ~24 destructive, ~5 borderline (parameter-dependent: `chromatic_aberration`, `threshold`, `transform`, `particle_system`, `edge_detect`).
- **Tag mechanism:** add `tags: list[str]` to `EffectGraph` pydantic model + `destructive` flag on `LoadedShaderDef` in `ShaderRegistry`. Preset author claims `non_destructive_overlay` tag; loader verifies against a new `agents/effect_graph/destructive_taxonomy.json` whitelist.
- **Enforcement surfaces (3 places apply presets):** `effects.py::try_graph_preset`, `chat_reactor.py`, `twitch_director.py` + `compositional_consumer.py::dispatch_overlay_emphasis`. All need tag-gated rejection when zone is overlay/content_layer.
- **SSIM ≥ 0.6 test** + temporal-stability assertion `SSIM(first_frame, last_frame) ≥ 0.3` to catch feedback/trail drift (temporally additive aggression).

**Recommended action:**
Paired naturally with #128 preset variety expansion. Implement tag mechanism + enforcement + test, then #128 populates the `non_destructive_overlay` pool.

**Provisional approval:** ✅
**Spec stub:** _pending_
**Dependencies:** Pairs with #128 preset variety.

---

### Task #158 — Director "Do Nothing" Invariant Regression Test

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-158.md`. **🚨 INVARIANT IS LIVE-VIOLATED AT 25% TODAY.**

**Key findings:**
- **Invariant live-violated at 25.03%** — trailing 735 `director-intent.jsonl` entries contain 184 with `compositional_impingements: []`. **Most-recent tail line is a bare no-op emitted moments ago.** Working regression-pin fixture, no fabrication needed.
- **Invariant already partially codified in code comments** — `_emit_micromove_fallback` (director_loop.py:1061-1144) was added today (2026-04-18) citing sim-1 audit operator directive. **Three vacuum paths plugged:** LLM empty, narrative repeat, silence-or-empty. **A fourth remains open:** parser-error fallbacks in `_parse_intent_from_llm` construct `DirectorIntent` with `compositional_impingements=[]` without going through the fallback.
- **Schema endorses the bug (!!):** `shared/director_intent.py:173` docstring reads *"Zero impingements means the director chose to reinforce the prior state."* **Directly contradicts operator directive.** Must tighten (`min_length=1`).
- **Contradictory prompt:** `ACTIVITY_CAPABILITIES` (director_loop.py:638) tells LLM "silence is a legal option" then demands "EVEN IN SILENCE: emit at least one compositional_impingement." Non-deterministic compliance.
- **Test design:** (1) fixture-based (10-min canned, cadence forced to 10 s) + (2) historical-replay on trailing 2000 records — fails today → regression pin.
- **"Interesting" deliberately reduced to "non-empty"** — interestingness is a warning metric (family-entropy over a window); gating invariant is deterministic compositional-impingement presence.
- **Effect definition maps cleanly to `IntentFamily` enum** (19 members) — preset swap, ward transition, HOMAGE intent, camera hero swap, overlay update are all first-class impingement families.

**Recommended action:**
Fix-PR (small): (1) close parser-error vacuum path, (2) tighten `DirectorIntent` schema to `min_length=1`, (3) remove "silence is legal" contradiction from `ACTIVITY_CAPABILITIES` prompt, (4) update schema docstring. Pair with a TEST-PR (regression fixture + historical replay). **URGENT — operator's explicit invariant actively violated.**

**Provisional approval:** ✅ — **PROMOTE TO HIGHEST PRIORITY**
**Spec stub:** _not needed_ (fix is mechanical; test needs fixture doc)
**Dependencies:** None. Pair with #150 image classification — one reason director punts is because perception signals aren't reaching it.

---

### Task #154 — Hookify Glob Noise + Write-Hook Errors

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-154.md`

**Key findings — two root causes:**
- **Text glob root cause:** `hookify.plugin-suggestions.local.md` authored in multi-rule format (9 rules separated by `---`). Hookify's `config_loader.py::extract_frontmatter` only splits on the FIRST `---...---` pair — **entire remainder (8 more rule definitions with visible frontmatter) becomes the `message` of the single parsed rule `suggest-pr-review`.** Every `gh pr create | git push.*origin` Bash call injects 2 KB dump as `systemMessage`. Rule files renamed `.disabled` in 3 locations but bug recurs on next `/hookify` invocation.
- **Write-hook error root cause:** `hooks/scripts/work-resolution-gate.sh` exit-2-blocks every Edit/Write while PR #227 (`fix/compositor-perf`) has failing CI. **Fired 14× in one session** because the hook has no per-turn dedup — each Edit call re-emits the blocking stderr. Script is correct; needs throttling.
- **Hook inventory:** 24 hooks total; load-bearing vs noise rating in deliverable.

**Recommended action:**
- **Immediate:** disable `hookify@claude-plugins-official` plugin — council's own hook stack covers load-bearing enforcement (axioms, branch, pip, PII) without the parser bug.
- **P0 fixes:** per-turn dedup marker on `work-resolution-gate.sh` (sketch in deliverable); patch hookify `config_loader.py` to split multi-rule files.
- **P1:** update `/hookify` skill's writing-rules template to emit ONE file per rule with `hookify.<rule-name>.local.md` naming.
- **Upstream:** file bug against `claude-plugins-official`.

**Provisional approval:** ✅
**Spec stub:** _not needed_ (fix-PR + disable)
**Dependencies:** None.

---

### Task #155 — Anti-Personification Audit (Governance-Critical)

**Status:** ✅ Returned. Raw file: `/tmp/cvs-research-155.md`. **Tender/fragile subject per operator — high fidelity report.**

**Key findings:**
- **Phase 7 redesign spec (2026-04-16) is authoritative and anti-personification is baked in at every layer.** Explicit supersession of the 2026-04-15 YAML schema precisely because its vocabulary (facets, bearing/temperament/pacing, personality.attention/aesthetic) was personification.
- **Frozen persona artifacts are CLEAN.** `hapax-description-of-being.md`, its compressed `.prompt.md`, and `posture-vocabulary.md` all reject inner-life claims; carry grep-target enforcement tests (`tests/axioms/test_persona_description.py`, `tests/studio_compositor/test_posture_vocabulary_hygiene.py`).
- **First-person anthropic sweep: zero violations in Phase 7 artifacts themselves.** Only hits are docs citing forbidden patterns AS rejections.
- **🚨 Two LIVE PERSONIFICATION VIOLATIONS downstream of the clean composer:**
  1. **`agents/hapax_daimonion/conversational_policy.py:45-83`** — `_OPERATOR_STYLE` string ("You have personality: dry wit, genuine curiosity, intellectual honesty... Socrates × Hodgman × Carroll") is concatenated onto the clean persona fragment via `policy_block`. **LARGEST ACTIVE VIOLATION.**
  2. **`agents/hapax_daimonion/conversation_pipeline.py:337-342, 1006-1011`** — LOCAL-tier prompts bypass the composer entirely with "warm, brief, casual" / "Just enough personality to not be generic" framing.
- **Posture is derived, not mandated** — architectural-state tuple → observer-applied name, enforced by AST-walk hygiene test against any posture literal in director code.
- **Role registry gap: no `is_not:` fields.** Scope is implicit in `description:` prose and `answers_for:` enumeration. Recommended amendment + matching test.
- **Director loop clean** — uses `compose_persona_prompt(role_id="livestream-host")`, action-oriented role block, no "be yourself" framing.
- **Text repository (#126) not designed yet** — pre-design obligation to gate on the linter.

**Recommended action:**
**Staged linter rollout:**
1. Land **warn-only** linter first (surfaces the 2 existing violations).
2. Refactor `conversational_policy._OPERATOR_STYLE` to remove personality framing.
3. Refactor `conversation_pipeline` LOCAL prompts to route through composer.
4. Add `is_not:` fields to role registry + matching test.
5. Flip linter to **fail-loud** only after refactors ship.

Deny-list patterns + allow-list carve-outs specified in §8.1 of deliverable.

**Provisional approval:** ✅ — **GOVERNANCE-CRITICAL, HIGH PRIORITY**
**Spec stub:** _pending_ (linter design + refactor plan)
**Dependencies:** Blocks #126 Pango text repository. Reinforces #156 role-derivation methodology.

---

## 3. Synergy Pass: DEFERRED

Per operator directive: synergy analysis saved for last, spans both the 16-item HOMAGE follow-on dossier AND this 19-item CVS dossier.

**Preconditions:**
- All 19 agents returned and summarized in §2.
- Individual spec stubs exist for each provisionally-approved item.
- HOMAGE epic Phase 12 complete or near-complete.

**Target document:** `docs/superpowers/research/2026-04-XX-full-synergy-analysis.md` spanning 35 research items (16 HOMAGE + 19 CVS).

---

## 4. Top-Priority Action Items Surfaced (for next tick)

Items that are **actively broken or misconfigured TODAY** (fix-PR first, spec-stub only if needed):

| # | Issue | Severity | Fix scope |
|---|---|---|---|
| **#158** | Director no-op invariant violated 25% live; schema docstring endorses bug | ACTIVE REGRESSION | Fix-PR: close parser-error vacuum, `min_length=1`, remove contradictory prompt |
| **#142** | `album-identifier.py` hardcodes 2× audio restore but operator plays 45-on-33 = 0.741× | ACTIVE BUG | Fix-PR: float rate signal, fix album-identifier, fix BPM nominalization |
| **#155** | 2 live anti-personification violations downstream of clean Phase 7 composer | GOVERNANCE | Refactor: `conversational_policy._OPERATOR_STYLE` + `conversation_pipeline` LOCAL prompts |
| **#152** | Session naming mtime-heuristic picked wrong ROLE after reboot | INFRA BUG | 10-line fix to `session-context.sh` |
| ~~#154~~ | ~~Hookify plugin parser bug~~ | DROPPED 2026-04-18 | Operator confirmed already resolved |
| **#148** | Reactivity sync gap — DSP 93fps vs fx_tick 30fps → 0-33ms onset latency | QUALITY CEILING | 2-hr wall-clock peak-hold fix |

Items that are **large-scope redesigns** (spec-first, staged PRs):

| # | Title | Scope |
|---|---|---|
| #146 | Token pole reward mechanic (redirect from LLM-token to chat-contribution) | 2-phase |
| #149 | 24c global reactivity contract (surfaces stale channel docs) | 4-phase |
| #150 | Image classification integration (1-of-17 signals consumed) | 3 priority integrations |
| #156 | Role derivation methodology template | Template + retroactive backfill |
| #157 | Non-destructive overlay effects layer | Tag mechanism + 56-node taxonomy |

Items that are **clean ship-the-rest-of-the-owl** (no new design):

| # | Title | Shape |
|---|---|---|
| #140 | Stream Deck — 80% shipped, 4 gaps | 2 PRs (command registrations + deployment chore) |
| #141 | KDEConnect bridge | 1-2 day PR |
| #143 | IR feed cadence (ACRCloud rejected; scope narrowed) | 2 small PRs |
| #144 | YT description auto-update — OAuth consent + chat URL extractor | 1 PR (after auth) |
| #145 | 24c ducking YT → 24c direction (mirror PR #1000) | 1 PR + norm |
| #147 | Token-pole qualifier rubric (imported into #146) | No standalone PR |
| #151 | Cross-agent audit dormant policy doc | 1 small PR |
| #153 | Worktree cap doc drift (3 → 4 slots + post-merge cleanup) | 1 PR |

---

## 5. Change Log

- **2026-04-18 (early)** — Dossier created. 19 agents dispatched in parallel (background).
- **2026-04-18 (middle)** — 6 returns: #140, #141, #142, #143, #144, #145, #147.
- **2026-04-18 (late)** — 11 more returns: #146, #148, #149, #150, #151, #152, #153, #154, #155, #156, #157, #158.
- **2026-04-18 (complete)** — All 19 agents returned. §4 top-priority banding added. Ready for cascade to spec stubs + fix-PRs.
