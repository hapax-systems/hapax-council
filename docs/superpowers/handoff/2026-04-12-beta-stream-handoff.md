# Session Handoff — 2026-04-12 (beta stream)

**Previous handoff:** `docs/superpowers/handoff/2026-04-12-session-handoff.md` (alpha-led compositor unification epic closure)
**Scope of this session:** Stream B of the 2026-04-12 work-stream split — reverie surface + voice pipeline.
**Session role:** beta
**Branch at end:** beta worktree on `beta-standby` (reset to `origin/main`), clean working tree. Main at `67a0222b7` after all PRs merged.
**Work-stream split reference:** `~/.cache/hapax/relay/context/2026-04-12-work-stream-split.md`

---

## What was shipped

All four PRs merged to `main`.

| PR | Item | Title | Result |
|----|------|-------|--------|
| [#678](https://github.com/ryanklee/hapax-council/pull/678) | B1 | `fix(reverie)`: reload vocabulary preset on `GraphValidationError` | `SatelliteManager.maybe_rebuild()` now reloads the in-memory `_core_vocab` from disk when graph validation fails, bounding the 18h-frozen-plan outage mode to one frame recovery. Resilience only; root cause of the original corruption remains undiagnosed. 1 new unit test. |
| [#680](https://github.com/ryanklee/hapax-council/pull/680) | B7 | `docs(research)`: KVzip + ExLlamaV2/V3 compatibility assessment | Doc-only. `docs/research/2026-04-12-kvzip-exllamav3-compatibility.md`. Conclusion: no direct integration path — KVzip is HuggingFace-transformers-bound with custom CUDA kernel monkey-patching, ExLlamaV2/V3 uses proprietary C++ attention kernels with hardcoded cache classes. Phase 2 benchmark should stick with native ExLlamaV3 Q8 cache quantization as already specified in the Hermes 3 70B migration plan. |
| [#681](https://github.com/ryanklee/hapax-council/pull/681) | B3 | `feat(voice)`: `HAPAX_TTS_TARGET` wires daimonion TTS into voice FX chain | `conversation_pipeline._open_audio_output()` now reads `HAPAX_TTS_TARGET` and forwards it to `pw-cat --target`. Also ships a second preset (`config/pipewire/voice-fx-radio.conf` — telephone/AM-radio bandpass) alongside the existing studio preset, under a shared sink name so swapping presets does not require restarting daimonion. New `config/pipewire/README.md` covering install, preset swap, env-var wiring, troubleshooting. 3 new unit tests. |
| [#683](https://github.com/ryanklee/hapax-council/pull/683) | B4 (plan) | `docs(plan)`: B4 `TransientTexturePool` wiring into `DynamicPipeline` | Plan only. `docs/superpowers/plans/2026-04-12-b4-transient-pool-wiring.md`. Executable by any Rust-comfortable session — covers struct changes, pool key derivation, allocator rewrite, call-site migration (18 sites), test plan, risk notes, and explicit out-of-scope items (per-frame `begin_frame` recycling, Python-side `pool_key` emission, temporal-texture pooling). Estimated 120–180 lines of Rust + 80 lines of tests. |

### Documentation written or updated

- `docs/research/2026-04-12-kvzip-exllamav3-compatibility.md` (B7)
- `config/pipewire/README.md` (B3)
- `docs/superpowers/plans/2026-04-12-b4-transient-pool-wiring.md` (B4 plan)
- `CLAUDE.md` — updated "Reverie Vocabulary Integrity" section to describe the defensive auto-reload; new "Voice FX Chain" section documenting the `HAPAX_TTS_TARGET` flow (this handoff PR)
- `docs/superpowers/handoff/2026-04-12-beta-stream-handoff.md` — this file

### Convergence sightings logged

- `~/.cache/hapax/relay/convergence.log` — `A1 (#679)` and `B1 (#678)` classified COMPLEMENTARY: both are resilience fixes born from the 2026-04-12 incident. A1 prevents the 13h blank-corners YouTube cold-start outage; B1 prevents the 18h frozen `plan.json` vocab-corruption outage. Same pattern: runtime state loss should auto-recover without operator intervention. Alpha independently logged the same sighting.

---

## Delta from the 2026-04-12 (alpha) handoff

The prior handoff listed pending items after the compositor epic closed. For Stream B items:

| Item from the prior handoff | Status now |
|---|---|
| **Defensive mitigation for vocab corruption** (the 18h frozen `plan.json`) — "could re-load the preset if a rebuild ever fails with `GraphValidationError`." | **Shipped** as PR #678 (B1). The suggested ~1 line + 1 test scoping was accurate. |
| **VST Effects on Hapax Voice** — "No work started — architectural path is clear." | **Shipped** as PR #681 (B3). The filter-chain preset already existed in-repo at `config/pipewire/voice-fx-chain.conf`; the missing piece was daimonion-side env-var wiring, a second preset for "user-configurable," and install docs. Not a new Python module. |
| **Prompt compression Phase 2 benchmarking** | **Not touched** — explicitly hardware-gated on Hermes 3 70B (conditions C/D in §4.2 of the research plan). Current hardware only supports conditions A/B (old vs compressed on Qwen3.5-9B). Deferred; see "Open for next session" below. |
| **Hermes 3 70B migration execution** (B5) | **Not touched** — hardware-gated. Design spec + migration plan already in repo; execution waits on hardware. |
| **Phase 4c transient-pool wiring** (B4) | **Planned but not implemented** — see PR #683. Plan is concrete enough that any Rust-comfortable session can execute. |
| **KVzip compatibility eval** (B7) | **Shipped** as PR #680 (doc). |
| **PR #637 CI monitor** (listed as B2 in the work-stream split) | **Moot** — #637 was closed on 2026-04-10 after being superseded by PR #638, which is the actual Phase 1 compression that merged. No action needed; the work is already in `main`. |

---

## Decisions made this session

1. **B1 catches `GraphValidationError` specifically, not all exceptions.** Non-validation failures (e.g. wgpu-side compile errors) still fall through to the original "keep previous graph" path without a reload. Only validation errors — the specific symptom of vocab corruption — trigger the reload. This keeps the behavior change narrow.

2. **B3 wires the env var at `_open_audio_output` time, not in `PwAudioOutput.__init__`.** Keeps `PwAudioOutput` target-agnostic (as it was) so one-shot `play_pcm` callers (chimes, SFX, tts_executor announcements) continue to bypass the FX chain. Only the persistent conversation-pipeline TTS stream honors the env var.

3. **B3 ships two presets with the same sink name.** `voice-fx-chain.conf` (studio vocal chain) and `voice-fx-radio.conf` (telephone / AM-radio bandpass). Shared sink name means swapping presets is a file swap + pipewire restart — daimonion does not need to restart and the env var does not change.

4. **B4 plan uses a single pool key on the Rust side** derived from `(width, height, format)` until the Python compile phase catches up and emits per-stage `pool_key` values. All intermediates in the current executor share one descriptor, so one bucket suffices.

5. **B4 plan defers per-frame `begin_frame()` recycling.** The pool was designed for per-frame recycling, but the current executor allocates textures per-plan-load, not per-frame. Restructuring when textures are acquired is a separate refactor; the initial wiring simply migrates allocation ownership from `HashMap<String, PoolTexture>` to the pool's slot map.

6. **B4 plan leaves temporal `@accum_*` textures unpooled.** Explicit non-goal — they have different lifetime semantics (persist across frames + clear, not recycle).

7. **B6 (Phase 2 benchmark) is only partially executable on current hardware.** The benchmark plan's §4.2 specifies four conditions (old vs compressed, Qwen vs Hermes 3 70B). Without the 70B hardware, only A vs B are measurable. A partial A/B run still has value (verifies the ~700 tok/turn Phase 1 savings match estimates), but the full result set requires B5 to land first.

8. **B2 is resolved-by-supersede, not deferred.** The work-stream split inherited "monitor PR #637" from a prior beta session's status file; in reality #637 was closed and its content re-landed as #638 before the split was written. No action was ever needed.

---

## Open for next session

### Implementation-ready

- **B4 implementation.** Plan is at `docs/superpowers/plans/2026-04-12-b4-transient-pool-wiring.md`. ~120–180 lines of Rust in `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs` plus ~80 lines of new tests. No Python changes. Risk notes in §6 of the plan. Picked up by whichever session (alpha or beta) has the Rust bandwidth next.

### Hardware-gated

- **B5** — Hermes 3 70B migration execution. Design spec + plan already merged (`docs/superpowers/specs/2026-04-10-hermes3-70b-voice-architecture-design.md`, `docs/superpowers/plans/2026-04-10-hermes3-70b-migration.md`). Waits on hardware.
- **B6 (full)** — Phase 2 prompt compression benchmarking against the 70B model. Conditions C/D in §4.2 of the research plan. Interleaves with B5 task 1 (inference validation).

### Executable-but-partial now

- **B6 (partial)** — Conditions A/B of the Phase 2 benchmark run on current hardware (Qwen3.5-9B EXL3 5.0bpw). Measures whether the ~700 tok/turn Phase 1 savings match estimates, independent of the 70B migration. Can land as a "Phase 2 A/B preliminary" result.

### Still-open cross-cutting items (not owned)

- **CC1 — stream-as-affordance.** Beta-side registration of `go_live` capability in DMN affordance pipeline is a prerequisite for alpha's compositor-side RTMP trigger (A7/A8 range). Not yet started.
- **CC2 — `OutputRouter.validate_against_plan`.** Explicit defer from the 2026-04-12 audit; blocked on the first real consumer.

### Known collision watch

- **`agents/effect_graph/` overlap.** Alpha may touch `wgsl_compiler.py` and preset switching for A5; beta may touch the same area for B4 follow-ups (per-frame recycling, Python-side `pool_key` emission). Coordinate via status files before editing.

### Open questions

- **Root cause of the original reverie vocab corruption** is still unknown. B1 is resilience, not diagnosis. If the pattern recurs post-merge, re-investigate — `hapax-reverie` log will now contain `Graph validation failed — reloading vocabulary preset` entries with timestamps that pinpoint when the in-memory state went bad.
- **B3 runtime verification.** I did not restart `hapax-daimonion.service` with `HAPAX_TTS_TARGET` exported inside this session — the env var path is unit-tested but not exercised against a live daemon. Operator should do one end-to-end sanity check: `set -Ux HAPAX_TTS_TARGET hapax-voice-fx-capture`, `systemctl --user restart hapax-daimonion`, speak a prompt, confirm the audio is audibly filter-chained vs. the unset baseline.

---

## State of the worktrees

- `hapax-council/` (alpha) — on `main`, owned by the alpha session.
- `hapax-council--beta/` (beta, this session) — on `beta-standby` reset to `origin/main` at `67a0222b7` to leave the worktree in a clean, up-to-date idle state. No uncommitted changes. No open local branches. No open PRs owned by beta.
- `hapax-council--a2-profiler-resilience/` — alpha's temporary worktree for A2 (appears to still exist locally; alpha's cleanup responsibility).

---

## Status file

`~/.cache/hapax/relay/beta.yaml` is up-to-date with everything above. `~/.cache/hapax/relay/convergence.log` has the A1/B1 COMPLEMENTARY sighting.
