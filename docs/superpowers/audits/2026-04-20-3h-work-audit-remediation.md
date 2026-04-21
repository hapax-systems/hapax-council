# 3-Hour Work Audit Remediation Plan
**Audit window:** 2026-04-20 14:00–17:30 CDT
**Filed:** 2026-04-20 by delta
**Scope:** 30 commits across Programme/D-28, YT bundle, audio pathways #134, audio normalization PR-1/2/3, Evil Pet S-4 Phase 1-4, unified-audio Phase 5, HOMAGE umbrella Phase 1+2, CBIP fix

## Ownership split rationale

Fixes are assigned to the session that shipped the originating code (context advantage) except where:
- **Delta wrote it → delta fixes** (drift configs, HOMAGE umbrella, CBIP)
- **Alpha wrote it → alpha fixes** (programme epic, YT bundle, #134 audio pathways, unified-audio Phase 5)
- **Joint bundles** are flagged when the fix crosses session boundaries (Evil Pet routing spans delta spec + alpha implementation; pin-check wiring spans alpha CLI + delta heal script)
- **Operator decisions** are flagged where the fix requires an architectural or product call

This preserves the principle that "whoever holds the implementation head-state fixes the bug," and avoids cross-session context-swapping cost.

## Sequencing — what ships first and why

Priority is set by (a) livestream-readiness impact and (b) pre-requisite depth. Items that block a feature from actually functioning end-to-end come first; items that merely add hardening come last.

| Order | Bundle | Owner | Rationale |
|-------|--------|-------|-----------|
| 1 | **B4** Drift catch-up PR | delta | Ready now, zero arch risk, closes a documented gap |
| 2 | **B1** Voice-gate wire | alpha | 5-line fix; unblocks the ONLY claimed purpose of #134 Phase 3 |
| 3 | **B2** YT description backflow | alpha | 50-line fix; completes a shipped feature that's 90% done |
| 4 | **B5** Pin-check systemd wiring | joint (delta-lead) | Closes unified-audio Phase 5; heal script is mine, CLI is alpha's |
| 5 | **B7** HOMAGE umbrella hardening | delta | Gates Phase 3; needs ward-count decision from operator |
| 6 | **B8** S-4 loopback runtime test | delta | Small hardening; prevents silent boot regression |
| 7 | **B3** Programme epic completion | alpha | Larger arch work (ProgrammeManager + JSONL + abort predicates) |
| 8 | **B6** Evil Pet broadcast routing | operator + joint | Needs product call on filter-chain vs main-mix-tap |
| 9 | **B10** CBIP follow-ups | delta | Small hygiene; queued behind higher-ROI work |
| 10 | **B9** Observability polish | alpha | Backlog — Grafana panels for Evil Pet counters |

## Interleaving into current workstream

### Delta's active slots (while alpha is offline)
1. **Now**: Ship B4 (drift catch-up). Close the drift gap before alpha returns; they shouldn't inherit it.
2. **On PR #1112 merge**: Start B7 (HOMAGE umbrella hardening), pausing at the ward-count decision gate if operator hasn't clarified.
3. **After B4 merges**: B5 (pin-check systemd) — requires minimal alpha context, just references alpha's CLI.
4. **Backlog**: B8 (S-4 runtime test), B10 (CBIP follow-ups).

### Alpha's queue (for their next session)
1. **Priority-pull**: B1 (voice-gate wire). 5-line change; high livestream impact.
2. **Priority-pull**: B2 (YT description backflow). ~50 lines across syncer + wire-in.
3. **Epic-pull**: B3 (programme completion). Needs multi-phase planning; not urgent per livestream readiness but critical for D-28 honesty.
4. **Side-lanes**: B9 (observability polish) when time permits.

### Operator decisions needed (blocking)
- **OQ-1**: Ward count 14 vs 15 — is the spec title aspirational, did a ward merge, or is one missing? Blocks B7.
- **OQ-2**: Evil Pet broadcast routing — software filter-chain (CH3→tap) OR main-mix-tap (AUX10/11, current shipped) as the permanent answer? Blocks B6.
- **OQ-3**: CBIP deterministic-tint is now static-album→static-tint. Acceptable or a visual regression? Blocks B10 confirmation.

## Bundle catalog

### Bundle 1 — Phantom-VAD completion (alpha)
**Closes:** Critical #1
**Work:** Wire `voice_gate.evaluate_and_emit()` into `agents/hapax_daimonion/vad_state_publisher.py:59` before `publish_vad_state(True)`. Add fallback mode warning when `operator_voice.npy` missing. Add integration test: synthetic YT audio + real VAD → gate suppresses phantom duck.

### Bundle 2 — YT bundle closeout (alpha)
**Closes:** Critical #2, High #13, Low #27
**Work:**
- Wire `AttributionFileWriter.read_all_entries()` into `agents/studio_compositor/youtube_description_syncer.py::_snapshot_state()` → `assemble_description()`
- Add `module-loudnorm` (`-16 LUFS / -1.5 dBTP`) upstream of YT→24c ducker per spec §3.4
- Extend URL extractor regex tests to cover livestream/shorts/youtu.be/obfuscated

### Bundle 3 — Programme epic completion (alpha)
**Closes:** Critical #3 (abort predicates), Critical #4 (Prometheus lifecycle), Critical #5 (JSONL log), Medium #18 (soft-prior math clamping)
**Work:**
- Implement 5 named abort predicates with live perception/IR/STT hookups (Phase 10 work)
- Add `ProgrammeManager` lifecycle hooks that fire `programme_start_total`, `programme_end_total`, `programme_active` gauge, duration gauges
- Ship JSONL outcome log writer with rotation (5 MiB / keep 3) at `~/hapax-state/programmes/<show>/<programme-id>.jsonl`
- Add clamping validators on bias multipliers `(0.0, 5.0]`

### Bundle 4 — Audio-infra drift catch-up PR (delta, READY)
**Closes:** Medium #15 (quantum/L6/heal drift), Medium #16 (echo_cancel topology gap), Medium #17 (monitor-bus undocumented)
**Work:**
- `config/pipewire/99-hapax-quantum.conf` (quantum 1024 / min 512 / max 2048)
- `config/pipewire/hapax-l6-evilpet-capture.conf` (v5 per-channel pre-fader, Evil-Pet↔Rode swap, hotplug-tolerant)
- `systemd/units/hapax-ryzen-codec-heal.service` + `scripts/hapax-ryzen-codec-heal.sh` (moved from distro-work)
- `config/audio-topology.yaml`: add `echo_cancel_capture` virtual source; add monitor-bus clarification note (hardware-only)
- `config/pipewire/README.md`: document load order

### Bundle 5 — Ryzen pin-check systemd wiring (joint; delta-lead)
**Closes:** Critical #6
**Work:**
- Create `/etc/systemd/user/hapax-pin-check.timer` (120s cadence; configurable)
- Create `/etc/systemd/user/hapax-pin-check.service` calling `scripts/hapax-audio-topology pin-check --auto-fix --state-file /dev/shm/hapax-pin-glitch-state.json`
- Move state file off tmpfs OR restart-hook to preserve last-known-good across reboots
- Add regression test: cold-boot → pipewire restart → pin-check detects → auto-fix
- Alpha-coordination: confirm pin-check CLI exit codes match systemd service expectations

### Bundle 6 — Evil Pet broadcast routing (joint; needs operator call)
**Closes:** Critical #7
**Options:**
- **(A) Software filter-chain**: ship `hapax-evilpet-ch3-capture.conf` pulling L6 AUX2 → livestream-tap; TTS flows through Evil Pet processor on broadcast
- **(B) Main-mix-tap stays final**: update audio-topology.yaml to declare AUX10+11 as canonical; Evil Pet remains operator's optional monitor-side chain only
Current state (A's topology doc, B's shipped code) is ambiguous. Needs operator decision.

### Bundle 7 — HOMAGE umbrella hardening (delta)
**Closes:** Critical #8 (ward count), High #9 (OQ-02 gates), High #10 (recognizability_tests binding), High #11 (kuwahara latency), High #14 (Phase 2 labeling), Medium #20 (vault-outline invariant), Medium #21 (JSON↔GLSL param test), Medium #22 (smoke-test named assertion)
**Work (gated on OQ-1):**
- Implement `tests/studio_compositor/homage/test_oq02_bounds_per_ward.py` (governance gate)
- Bind `recognizability_tests` YAML strings to callable test registry; error on unresolved names at profile load
- Add kuwahara latency regression pin `<300ms @720p`
- Update plan phase-table to label Tasks 3+4 within Phase 2
- Strengthen vault-outline test: assert planner code doesn't `import` or call `scan_vault()` / `frontmatter.parse()`
- Add JSON↔GLSL uniform name validator across all shader nodes
- Rewrite smoke test to assert `"kuwahara" in registry and "palette_extract" in registry`, not just count

### Bundle 8 — S-4 loopback runtime integration test (delta)
**Closes:** High #12
**Work:**
- Add `tests/pipewire/test_s4_loopback_runtime.py`: spin up pipewire with conf loaded, verify node appears in graph via `pw-dump` JSON, sanity-check audio.format and channel map
- Wire into CI under `pipewire` test collection
- Document fallback path if S-4 absent

### Bundle 9 — Observability polish (alpha)
**Closes:** Low #24
**Work:**
- Add Grafana panel for `hapax_evilpet_preset_recalls_total` heatmap
- Add to studio dashboard under "Audio hardware interactions"

### Bundle 10 — CBIP follow-ups (delta)
**Closes:** Medium #23 (tint regression), Low #28 (threshold config surface), Low #29 (acceptance_test_harness validation), Low #30 (halftone technique), Low #31 (cvs_bindings enforcement)
**Work (gated on OQ-3):**
- Confirm deterministic-tint acceptability; if regression, add operator-override channel
- Externalize `CBIP_HASH_THRESHOLD` (env + config)
- Add halftone technique to TechniqueTaxonomy (Phase 3 annex)
- Add startup check: `WardEnhancementProfileRegistry.load_from_yaml()` asserts all `acceptance_test_harness` paths exist
- Wire `cvs_bindings` into CI as Pydantic validator against axiom registry

## Governance / ungated remediations (non-bundle)

- **Abort-predicate deferral is acknowledged, not violated** — Bundle 3 covers.
- **Ritual impingement recruitment proof** (Medium #19) — roll into Bundle 3 E2E tests.
- **SoundCloud secret orphan** (Low #26) — will resolve when soundcloud_adapter Phase 3 lands (not scheduled yet; file a reminder).
- **Preset-variety Phase 1 isolation** (Low #32) — accept as-is; re-visit when programme/preset coupling is designed.

## Verification — all 32 audit findings accounted for

| Finding | Bundle | Owner |
|---|---|---|
| C#1 voice_gate not called | B1 | alpha |
| C#2 YT backflow missing | B2 | alpha |
| C#3 abort predicates no-op | B3 | alpha |
| C#4 Phase 9 Prometheus partial | B3 | alpha |
| C#5 JSONL outcome log absent | B3 | alpha |
| C#6 pin-check no systemd | B5 | joint |
| C#7 Evil Pet broadcast routing | B6 | operator+joint |
| C#8 ward count 14 vs 15 | B7 | delta+operator |
| H#9 OQ-02 gates | B7 | delta |
| H#10 recognizability_tests | B7 | delta |
| H#11 kuwahara latency | B7 | delta |
| H#12 S-4 runtime test | B8 | delta |
| H#13 YT loudnorm | B2 | alpha |
| H#14 Phase 2 labeling | B7 | delta |
| M#15 quantum/L6/heal drift | B4 | delta |
| M#16 echo_cancel topology | B4 | delta |
| M#17 monitor-bus documentation | B4 | delta |
| M#18 soft-prior math clamping | B3 | alpha |
| M#19 ritual recruitment test | B3 | alpha |
| M#20 vault-outline invariant | B7 | delta |
| M#21 JSON↔GLSL param test | B7 | delta |
| M#22 smoke-test named assertion | B7 | delta |
| M#23 CBIP tint regression | B10 | delta+operator |
| L#24 Evil Pet Grafana panel | B9 | alpha |
| L#25 pipewire-restart e2e test | — | backlog |
| L#26 SoundCloud orphan | — | backlog (reminder) |
| L#27 YT URL extractor edges | B2 | alpha |
| L#28 CBIP threshold config | B10 | delta |
| L#29 acceptance_test_harness paths | B10 | delta |
| L#30 halftone technique | B10 | delta |
| L#31 cvs_bindings enforcement | B10 | delta |
| L#32 preset-variety isolation | — | accept |

**Coverage:** 29 of 32 findings mapped to a concrete bundle; 3 accepted-as-backlog (L#25, L#26, L#32) with clear trigger conditions for re-visit.

## Success criteria

This remediation is complete when:
1. B1–B3 shipped (alpha) → phantom-VAD + YT description + programme honesty all actually work end-to-end
2. B4–B5 shipped (delta) → infra drift closed, pin-check auto-heal live
3. B6 answered by operator → ambiguity resolved
4. B7 shipped (delta) → HOMAGE Phase 3+ unblocked with OQ-02 gates active
5. B8 + B9 + B10 → hygiene complete
6. LRR regression watch runs for 24h with zero audit-derived regressions

## Closure log

- **2026-04-20 ~17:45 CDT** — Alpha shipped B1 (voice_gate wire-in, commit `6721fb863`), B2 (YT description backflow + URL extractor edges, commits `2c1820454` + `d350e74bf`), B3 (programme completion: 5 abort predicates registered, JSONL outcome log, bias clamp — commits `72dd2cfae` + `77098802c` + `3843e1806`), B9 (Evil Pet Grafana panel, `3572ce7f7`), plus a CI fix (`88c5f3e53 fix(tests): unblock main CI — choreographer tests pollute via /dev/shm leak`). Delta audit task #221 #222 #223 #228 → completed.
- **2026-04-20 ~18:25 CDT** — Delta opened PR #1113 for B4 (drift catch-up: quantum 1024 + L6 v5 `multichannel-input` target fix + Ryzen heal unit). Includes the critical `target.object: multitrack → multichannel-input` fix surfaced live when operator's OBS went silent — without it in repo, fresh clones reproduce the silence. Task #220 → in_progress, pending CI green.
- **2026-04-20 ~18:30 CDT** — Delta wrote B8 test module (`tests/pipewire/test_s4_loopback_runtime_safety.py`) adding 5 runtime-safety pins to the S-4 loopback conf: `audio.format` against PipeWire's accepted vocabulary, channel-position token validity, position-list internal consistency, rate sanity, module-name correctness. Stashed pending B4 merge (no-stale-branches blocks parallel branches).

## Verification of B3 scope

Alpha's B3 commits cover:
- ✅ Critical #3 — 5 abort predicates registered (`72dd2cfae`). **Note**: commit says "registered" which may indicate stubs pending live-system hookups; audit this on next session if predicates need real perception/IR/STT integration.
- ✅ Critical #5 — JSONL outcome log writer + ProgrammeManager wire-in (`77098802c`)
- ✅ Medium #18 — bias multiplier clamp ≤ 5.0 (`3843e1806`)
- ⚠️ Critical #4 — ProgrammeManager lifecycle Prometheus hooks: partial. `77098802c` mentions "manager wire-in" so likely includes lifecycle, but not explicitly called out in a separate commit. Verify the four counters (`programme_start_total`, `programme_end_total`, `programme_active` gauge, duration gauges) actually emit on next run.
- ⚠️ Medium #19 — ritual impingement recruitment E2E: not confirmed shipped.
