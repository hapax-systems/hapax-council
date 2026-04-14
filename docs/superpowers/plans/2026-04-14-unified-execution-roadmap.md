# Unified Execution Roadmap

**Date:** 2026-04-14
**Author:** alpha
**Frame:** Reconciliation between the LRR epic (PR #783) and the
livestream-performance-map EXECUTION-PLAN.md (PR #775). Authoritative
forward plan for everything that remains.
**Status:** plan only — no execution started

## 0. Why this doc exists

Two plans landed within hours of each other on 2026-04-13/14:

1. **`livestream-performance-map/EXECUTION-PLAN.md`** (PR #775) — 6 waves
   covering ~56 tactical performance findings. Waves 1–4 mostly shipped
   tonight (PRs #776–#782, #784). Waves 5+ are unstarted.
2. **LRR epic** (`docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md`,
   PR #783) — 11-phase strategic arc from current state to the "substrate × medium
   × agency" end-state triad.

Tonight's alpha session worked through Waves 1–4 of the EXECUTION-PLAN
linearly, then started opening LRR Phase 0, then realized the linear
piecewise approach was missing the structural relationship between the two
plans. This roadmap is the structural answer.

**Single rule:** future alpha sessions inherit this roadmap as the authoritative
sequencer. The LRR epic remains the strategic spine; the EXECUTION-PLAN.md
Wave 5+ items are now scheduled inside LRR phases (Track D below) or filed
as orphan tracks (Track C).

## 1. State of the world at 2026-04-14T06:30Z

### 1.1 Shipped tonight (10 PRs, all merged into `main`)

| PR | Item | Wave | Status |
|---|---|---|---|
| #775 | EXECUTION-PLAN.md (488 lines, ~56 findings classified) | meta | merged |
| #776 | FreshnessGauge metric hyphen sanitization | W1 | merged |
| #777 | Wave 1 observability bundle (frame histograms + VRAM gauge + audio DSP histogram + postmortem hook) | W1 | merged |
| #778 | W3.1+W3.2 audio ducking envelope (Option B Python, replaces `mute_all` cliff) | W3 | merged |
| #779 | W5 NEW per-camera frame-flow watchdog (silent-failure containment) | W5+new | merged |
| #780 | W3.3 voice_active + music_ducked observability gauges | W3 | merged |
| #781 | W4.5 + W4.6 + W4.7 Wave 4 close-out (logos_command_latency_ms histogram + MediaMTX HLS audit + brio-synths interface audit) | W4 | merged |
| #782 | W1.8 JSON timestamp microsecond fix | W1 | merged |
| #783 | LRR epic design + plan + bootstrap CLI + kickoff handoff (parallel planning session) | epic | merged |
| #784 | W5.11 compositor VRAM 3 GB attribution research note + diagnostic script | W5 | merged |

### 1.2 Operator decisions made tonight

- **MediaMTX**: brought back via `sudo systemctl enable --now mediamtx` — listening on 1935/8888/8889
- **PCIe x4 on 5060 Ti**: accepted as temporary, X670E motherboard arrives ~2026-04-16
- **brio-operator deficit (serial 5342C819)**: accepted as hardware fault confirmed via cable-port swap test; deficit followed the body, not the port. Replacement coordinated with X670E install
- **Audio ducking live verification**: deferred until close-to-stream date

### 1.3 Hardware milestone in flight

- **X670E motherboard install ~2026-04-16** (operator-scheduled). Triggers PCIe x4→x16 re-verification, brio-operator BRIO body replacement, possible PSU re-stress, possible Hyprland/AQ_DRM re-pin if PCIe slot indices change.

### 1.4 Tonight's in-flight work being landed by the roadmap PR

- **Bug fix:** `chat-monitor.service` wait-loop (eliminates the 660+ restart spam from `sys.exit(1)` on missing `YOUTUBE_VIDEO_ID`). Originally drafted as LRR Phase 0 item 1 before this roadmap pivot. Lands here on its own merits.
- **This roadmap doc** (you are reading it).

### 1.5 Aborted in-flight work

- LRR Phase 0 spec doc + plan doc — drafted earlier this session, deleted before commit because Phase 0 is no longer "owned by alpha" under this roadmap. Future LRR session writes its own per-phase docs at phase open time.
- `~/.cache/hapax/relay/lrr-state.yaml` `current_phase_owner: alpha` claim — reverted to `null` by the roadmap PR (no Python session currently owns Phase 0).

## 2. Inventory of everything that remains

### 2.1 Wave 5+ from livestream-performance-map (11 unstarted items)

| ID | Item | Effort | Direct LRR phase? |
|---|---|---|---|
| W3-LSP | LSP `sc_compressor_stereo` PipeWire sidechain (sample-accurate ducking, deferred from PR #778's Option B) | 1 day + tuning | Phase 9 |
| W5.1 | wgpu `Query::Timestamp` per-node shader timing | 2 hours | Phase 10 |
| W5.2 | Sub-frame transient ring buffer smoother | 4 hours | Phase 9 |
| W5.3 | BPM tracking + `beat_phase` signal | 4 hours | Phase 9 |
| W5.4 | Audio feature SHM dedupe (daimonion CPU savings) | 2 hours | Phase 10 |
| W5.5 | youtube-audio `ffmpeg → GStreamer` refactor | 1-2 days | **orphan** |
| W5.6 | OBS voice/music/instruments subgroup redesign | operator decision + 1 day | **orphan** |
| W5.7 | Closed-loop audio→visual latency validation script (≤50 ms target) | 4 hours | Phase 10 |
| W5.8 | StyleTTS 2 spike on 5060 Ti (vs Kokoro) | 1-2 days | Phase 5 |
| W5.9 | Blackwell NVENC feature audit (AV1, 4:2:2, low-latency) | 2 hours | Phase 3 |
| W5.10 | Parallel encoder stress test (3 encoders + 2 decoders, 10 min) | 4 hours | Phase 3 |

**9 of 11 absorb into LRR phases. 2 orphans: W5.5, W5.6.**

### 2.2 LRR epic (11 phases, none opened)

Per `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §4. The epic estimate is 4-6 weeks of focused work end-to-end, with Phase 4 time-gated by operator availability.

| # | Phase | LRR estimate | Operator gate? |
|---|---|---|---|
| 0 | Verification & Stabilization | 1-2 sessions | no |
| 1 | Research Registry Foundation | 2 sessions | no |
| 2 | Archive + Replay as Research Instrument | 2-3 sessions | no |
| 3 | Hardware Migration Validation + Hermes 3 Preparation | 2-3 sessions | partial (hardware) |
| 4 | Phase A Completion + OSF Pre-Registration | 1-2 weeks (time-gated) | yes (data collection) |
| 5 | Hermes 3 70B Substrate Swap | 2 sessions | yes (go/no-go) |
| 6 | Governance Finalization + Stream-Mode Axis | 2-3 sessions | yes (axiom amendments) |
| 7 | Persona / Posture / Role Spec Authoring | 1-2 sessions | yes (sign-off) |
| 8 | Content Programming via Research Objectives | 3-5 sessions | partial |
| 9 | Closed-Loop Feedback + Narration + Chat | 2-3 sessions | no |
| 10 | Observability, Drills, Polish | 3-4 sessions | no |

### 2.3 Phase 0 prior-alpha-already-shipped audit

The LRR epic was authored before tonight's prior alpha session work shipped. The following Phase 0 / later-phase items are **already done** and should be removed from their phase scope:

- Dual-GPU partition Phases 1–4 (LRR Phase 3 item 1) — fully shipped, just needs Option α→γ reconciliation pre-Phase 5
- Frame histograms + VRAM + audio DSP + postmortem (LRR Phase 10) — partially done
- Audio ducking envelope (LRR Phase 9 item 8) — Option B done; Option A LSP still TODO
- voice_active + music_ducked gauges (LRR Phase 10) — done
- logos_command_latency_ms histogram (LRR Phase 10) — done (FastAPI side)
- MediaMTX HLS audit (LRR Phase 0 item 6) — done in PR #781
- brio-synths interface audit (out of LRR scope, done in PR #781)
- Compositor VRAM 3 GB attribution (LRR Phase 0 spot check) — done in PR #784, conclusion: structural, not a bug
- JSON timestamp microsecond fix (LRR Phase 0 implicit observability) — done in PR #782
- brio-operator hardware swap test (LRR Phase 3 item 11) — done; deficit confirmed hardware fault

The next LRR session must re-read its phase spec against this list and skip items already shipped.

## 3. The unified epic — 5 tracks

Not a serial sequence; a **5-track parallel program**. Tracks run concurrently where branch discipline allows. Track A is the spine; the others are slot-in.

```
Track A — LRR Backbone        ████████████████████████████  (4-6 weeks, serial)
Track B — Hardware Window     ░░██░                          (2026-04-15..18)
Track C — Performance Orphans   ░░░░  ░░░░                   (W5.5, W5.6 — opportunistic)
Track D — Wave 5 absorbed      [merged into A — no separate work]
Track E — Operator-Gated       ░ ░ ░ ░ ░  ░  ░ ░             (gates as they come)
                             tonight       +1wk +2wk +4wk
```

### Track A — LRR Backbone (serial spine)

The LRR epic Phases 0–10 as authored, with the Wave 5 items folded in (Track D below). One phase = one branch = one PR. Each phase opens with its own per-phase spec + plan, executes, closes with handoff. Per the LRR plan doc §2.

**Critical path:** Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10. Phase 4 is time-gated by operator data collection (~1-2 weeks). All others are engineering-gated and fungible across alpha sessions.

**Phase 0 owner:** unassigned at roadmap commit time. Next alpha session that opens Phase 0 claims ownership in `lrr-state.yaml` via direct edit (the `lrr-state.py` CLI gains `open` / `close` / `block` / `unblock` subcommands as the first piece of Phase 0 expansion).

### Track B — Hardware Window (sandwiched around X670E install)

Three sub-phases bracketing the operator's mainboard install:

**B-pre (1 day, before install):**
- Capture current per-process VRAM, NVENC throughput, PCIe link width, PSU stress baseline (the existing `scripts/compositor-vram-snapshot.sh` from PR #784 is a starting point — extend it to a full pre-install snapshot)
- Document the partition Option α (currently deployed) so post-install can reconcile to Option γ (LRR Phase 3 prerequisite) cleanly
- Pack the brio-operator BRIO body for replacement (operator action)

**B-install day (operator + alpha post-install verification):**
- Operator: physical motherboard swap, install new BRIO if available, reconnect cables
- Alpha post-install: re-run `nvidia-smi`, `lspci -vvs <slot>`, `compositor-vram-snapshot.sh`, AQ_DRM card index check, hyprland.conf adjustment if needed, waybar desc-based output verification (already done in dual-GPU partition work)

**B-post (2-3 days after install):**
- Re-run brio-operator fps measurement (if BRIO replaced, deficit should disappear; if same hardware re-installed, deficit persists and is now confirmed body-fault for the operator's records)
- Re-run PCIe link width verification on the 5060 Ti (should be x16 PCIe 4.0 now, not x4 PCIe 3.0)
- Update LRR Phase 3 prerequisite checklist to reflect the post-install state
- Update `~/.cache/hapax/relay/alpha.yaml::operator_decisions_2026_04_14` with hardware milestone closure

**Branch ownership:** Track B is a single branch `feat/hardware-window-2026-04-16` opened pre-install, kept open across the install day, closed post-install. Operator-blocking but alpha can do all the prep + verification work without phase-spec overhead.

### Track C — Performance Orphans (opportunistic)

Two items that have no LRR home:

**W5.5 — youtube-audio ffmpeg→GStreamer refactor.** Currently each YouTube audio slot spawns an ffmpeg subprocess that restarts on URL change, creating a ~50-200 ms gap. Refactoring to a single GStreamer pipeline per slot eliminates the gap. ~1-2 days of work. Standalone branch `refactor/youtube-audio-gstreamer`. Can ship between LRR phases when an alpha session has a quiet block.

**W5.6 — OBS voice/music/instruments subgroup redesign.** Currently a single `mixer_master` null sink takes everything; the operator can't independently control voice vs music faders in OBS. Redesign uses three null sinks + Wireplumber rules. **Operator-gated** — the operator must agree to the new sink topology because it changes how OBS scenes are configured. Standalone branch when approved.

**Track C rule:** these PRs DO NOT delay LRR backbone progress. They land when there's slack. If the LRR backbone ever stalls (e.g., waiting on operator for Phase 4), Track C is the natural backfill.

### Track D — Wave 5 items pre-folded into LRR phases

These items are **removed from any "Wave 5 backlog" frame** and become tasks inside their LRR phase. The session that opens that LRR phase is responsible for executing them as part of the phase scope. Each phase's per-phase spec must enumerate the absorbed items.

| Wave 5 item | Goes inside LRR phase | Notes |
|---|---|---|
| W3-LSP sidechain compressor | Phase 9 (closed-loop feedback + narration) | Replaces Option B Python envelope with sample-accurate filter-chain |
| W5.1 wgpu Query::Timestamp | Phase 10 (observability) | Per-shader cost attribution |
| W5.2 Transient ring buffer smoother | Phase 9 (audio reactivity polish) | Eliminates 33ms render quantization for drum hits |
| W5.3 BPM tracking + beat_phase | Phase 9 (audio→stimmung loop) | Tempo-locked effects |
| W5.4 Audio feature SHM dedupe | Phase 10 (daimonion exporters) | Daimonion reads compositor's published features |
| W5.7 Closed-loop validation script | Phase 10 (drills) | The 6-drill list in Phase 10 already includes audio→visual latency |
| W5.8 StyleTTS 2 spike | Phase 5 (Hermes 3 substrate swap) | Post-Hermes substrate eval; Kokoro baseline already captured (would be Phase 0 item 10 if Phase 0 were already open) |
| W5.9 Blackwell NVENC feature audit | Phase 3 (hardware migration) | AV1, 4:2:2, low-latency — natural fit with Hermes 3 prep |
| W5.10 Parallel encoder stress test | Phase 3 (hardware migration validation suite) | Already in Phase 3 §S7 L4 |

**No separate work.** When Phase N opens, its scope includes its absorbed Wave 5 items. The PR per phase is one PR, not phase-PR + Wave-5-PR.

### Track E — Operator-Gated Items

Items where alpha cannot proceed without an operator decision. Each one is a single moment, not a phase.

| Gate | What unblocks | When |
|---|---|---|
| LRR Phase 4 Sprint 0 G3 gate | Operator chooses option from epic Phase 4 preamble | Before Phase 4 opens |
| LRR Phase 5 Hermes 3 swap go/no-go | Operator confirms after Phase 4 closes | After Phase 4 |
| LRR Phase 6 stream-mode axis | Operator approves `it-irreversible-broadcast` axiom amendment | Before Phase 6 implementation |
| LRR Phase 7 persona spec sign-off | Operator approves the written persona doc | Phase 7 close |
| W5.6 OBS subgroup redesign approval | Operator agrees to 3-sink topology | Anytime |
| Hardware install scheduling | Operator schedules the X670E swap window | ~2026-04-16 |
| Audio ducking live verification | Operator at studio mic | Close to streaming start |

These are not blockers for *all* work — they only block their specific item. Other tracks proceed.

## 4. Sequence + dependencies

The strict serial dependencies are:

```
LRR Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10
                              ▲
                              │
                       Hardware Window B
                       (parallel, must close before Phase 5)

Track C orphans: any time, no dependencies
Track E gates: as listed
```

**Critical path** (longest chain): Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10.

**Concurrency rule:** branch discipline allows max one alpha branch at a time per session, but multiple sessions (alpha + beta + delta) can hold one branch each. Use:
- Alpha holds the LRR backbone branch for whichever phase is current
- Track C orphans run on a separate beta or delta session if available, OR slot in between alpha LRR phases when alpha has CI wait time
- Track B hardware window runs as a single alpha branch across the install day

## 5. Operator decision points (in chronological order)

1. **Now** — Approve this roadmap structure (Y/N). This document becomes authoritative if Y.
2. **Now** — Confirm chat-monitor wait-loop fix is OK to ship as part of this PR (it's a real bug fix, label-of-convenience for the roadmap PR).
3. **Anytime before LRR Phase 4** — Sprint 0 G3 gate decision.
4. **~2026-04-16** — Schedule the X670E motherboard install window.
5. **After Phase 4 data collection** — Hermes 3 swap go/no-go.
6. **Before Phase 6 axiom amendments** — Stream-mode axis approval.
7. **Phase 7 close** — Persona spec sign-off.
8. **Anytime** — W5.6 OBS subgroup redesign approval.
9. **Close to streaming start** — Audio ducking live verification at the mic.

## 6. Tonight's cleanup

This roadmap PR ships:

1. **`docs/superpowers/plans/2026-04-14-unified-execution-roadmap.md`** — this doc
2. **`scripts/chat-monitor.py`** — wait-loop fix (LRR Phase 0 item 1, lifted out of the abandoned Phase 0 framing)
3. **`tests/test_chat_monitor_wait_loop.py`** — regression pin for the wait-loop behavior
4. **`~/.cache/hapax/relay/lrr-state.yaml`** — `current_phase_owner` reverted to `null` (alpha is not currently executing Phase 0; the next session that opens Phase 0 claims ownership fresh)

`~/.cache/hapax/relay/alpha.yaml::lrr_epic_kickoff` block is preserved as informational context for the next session.

## 7. What the next alpha session does

1. Standard relay onboarding (read `onboarding-alpha.md`, `PROTOCOL.md`, peer status)
2. **Read this roadmap doc first.** It's the authoritative sequencer.
3. Read `lrr-state.yaml`. If `current_phase_owner` is `null`, you can claim it.
4. Pick one of:
    - **Track A:** Open the next LRR phase per `lrr-state.yaml::current_phase`. Follow the LRR plan doc §2 pickup procedure. Write per-phase spec + plan, execute, close.
    - **Track B:** If the X670E install is imminent or just-happened, focus on Hardware Window B work. Single branch.
    - **Track C:** If LRR is mid-phase and you're in a backfill window, pick W5.5 or W5.6 (W5.6 needs operator approval first).
    - **Track E:** If an operator decision has just arrived, action it.
5. **Do not work linearly across plans.** This roadmap is the structural answer to "what next" — pick one track at a time and stay in it for the whole session.

## 8. When this roadmap retires

This document retires when:

- All LRR Phase 0–10 are closed (Track A complete)
- Hardware Window B closed (motherboard installed and validated)
- Track C orphans (W5.5, W5.6) shipped or explicitly dropped
- All Track E gates resolved or explicitly deferred to a separate epic

At that point: the system is at the LRR end-state triad (Hermes 3 substrate × 24/7 Legomena Live medium × Hapax-as-research-programmer agency) with all tactical performance work absorbed. New work is a new epic.

## 9. Notes

- **The LRR epic remains authoritative for its own scope.** This roadmap does not edit the epic; it sequences it alongside the orphan tracks.
- **The EXECUTION-PLAN.md from PR #775 is now historical.** Wave 5 items live in Track D (LRR phases) or Track C (orphans). The plan doc itself stays in git as a record.
- **No new items are introduced.** This roadmap is reconciliation, not expansion. Anything not in the LRR epic or the EXECUTION-PLAN.md or this doc's Track B is out of scope and needs its own future plan.
