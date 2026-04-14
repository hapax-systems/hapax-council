# Alpha Marathon Retirement — 2026-04-14

**Session role:** alpha
**Session window:** 2026-04-14 evening (pre-retirement context) through 2026-04-14 09:10 UTC
**PRs shipped:** #775 through #795 — **21 PRs in a single alpha run**
**Final state:** main @ `b7b29f6c7`, all worktrees clean, LRR epic at `current_phase: 2`
**Reason for retirement:** operator-designated natural retirement point after LRR Phase 1 close at 10/10

## What happened

This session began as a continuation of the livestream-performance-map execution and pivoted twice before retiring:

1. **Waves 1-5 of EXECUTION-PLAN.md (PRs #775-#784).** Frame histograms, VRAM gauges, audio DSP timing, postmortem capture, audio ducking envelope (replacing the `mute_all` cliff), per-camera frame-flow watchdog, Wave 4 close-out (latency histogram, MediaMTX audit, brio-synths audit), and the W5.11 compositor VRAM attribution research note.
2. **Pivot to unified 5-track roadmap (PR #785).** Operator: "Stop: instead of working through this all linearly, plan an epic multi-phased plan to work through everything." Landed as the unified execution roadmap doc reconciling livestream-perf orphans with the LRR epic, plus a chat-monitor wait-loop fix for the warn-cadence backstop found during Phase 0 prep.
3. **LRR Phase 0 — Verification & Stabilization (PRs #786-#790).** 9.5 of 10 items closed. Carry-overs: `/data` inode alerts (cross-repo, operator-gated) and FINDING-Q Step 3 runtime rollback (design-ready, implementation deferred to a parallel branch when discipline allows).
4. **LRR Phase 1 — Research Registry Foundation (PRs #791-#795).** 10/10 items closed in ~52 minutes. Registry data structure, per-segment Qdrant payload schema, research-marker SHM injection with audit log, frozen-file pre-commit enforcement, Langfuse `condition_id` tag, OSF project creation procedure, analytical-approximation BEST (Kruschke 2013) with the canonical MCMC upgrade pinned to Phase 4, research-registry.py CLI, stream-reactions backfill subcommand, and a Qdrant schema drift audit closing item 10.

## PR manifest (21)

| PR | Scope | Category |
|---|---|---|
| #775 | EXECUTION-PLAN.md (488 lines, 6-wave plan) | livestream-perf |
| #776 | FreshnessGauge metric name sanitization | livestream-perf |
| #777 | Wave 1 observability bundle | livestream-perf |
| #778 | W3.1+W3.2 audio ducking envelope | livestream-perf |
| #779 | W5 NEW per-camera frame-flow watchdog | livestream-perf |
| #780 | W3.3 voice_active + music_ducked gauges | livestream-perf |
| #781 | W4.5+W4.6+W4.7 Wave 4 close-out | livestream-perf |
| #782 | W1.8 JSON timestamp microsecond fix | livestream-perf |
| #783 | LRR epic design + plan + bootstrap CLI | LRR kickoff |
| #784 | W5.11 compositor VRAM attribution note | livestream-perf |
| #785 | Unified 5-track roadmap + chat-monitor fix | roadmap pivot |
| #786 | Phase 0 opening (WGSL parse-gate + Finding C + Claim 5/6 doc) | LRR Phase 0 |
| #787 | Phase 0 HF CLI + directory matrix | LRR Phase 0 |
| #788 | Phase 0 FINDING-Q Steps 1+2 | LRR Phase 0 |
| #789 | Phase 0 Finding A+F close | LRR Phase 0 |
| #790 | Phase 0 close + items 5/6/7/8/9 | LRR Phase 0 |
| #791 | Phase 1 registry foundation | LRR Phase 1 |
| #792 | Phase 1 marker SHM + condition_id wiring + backfill | LRR Phase 1 |
| #793 | Phase 1 frozen-files + Langfuse tag | LRR Phase 1 |
| #794 | Phase 1 stats.py BEST | LRR Phase 1 |
| #795 | Phase 1 Qdrant drift audit + close handoff | LRR Phase 1 |

Cumulative test stats: ~120 Python tests + 5 Rust unit tests, all CI green, ruff + format clean throughout.

## LRR epic state at retirement

| Field | Value |
|---|---|
| `current_phase` | 2 |
| `last_completed_phase` | 1 |
| `completed_phases` | `[0, 1]` |
| `current_phase_owner` | null (awaiting claim) |
| `current_phase_branch` | null |

Per-phase close handoffs: `docs/superpowers/handoff/2026-04-14-lrr-phase-0-complete.md`, `docs/superpowers/handoff/2026-04-14-lrr-phase-1-complete.md`.

## Known blockers carried forward

1. **Phase 0 item 3** — `/data` inode alerts require cross-repo edits in `llm-stack/alertmanager-rules.yml` + sudo. Same dance as Wave 1 W1.1 (Prometheus scrape). Not a hard blocker for Phase 2+.
2. **Phase 0 item 4 Step 3** — FINDING-Q runtime rollback (last-known-good plan snapshot + recovery on reload after panic). Validation half + counter shipped via #788/#789. Spike design ready at `docs/superpowers/specs/2026-04-14-lrr-phase-0-finding-q-spike-notes.md §4 Step 3`. Ships cleanly on a parallel `feat/lrr-phase-0-finding-q-runtime-rollback` branch when branch discipline allows.
3. **Phase 1 item 10 sub-item 2** — `dotfiles/workspace-CLAUDE.md` Qdrant collections list 9 → 10. Cross-repo. Symlink target lives in the dotfiles repo.
4. **Phase 6 voice transcript rotation hook** — daimonion daily rotation creates new voice transcript files at 644. Phase 0 item 9 backfilled chmod 600 on existing files; rotation hook itself is stream-mode firewall work. Without it the chmod 600 backfill erodes over time.

## Beta drops queued (5 remaining)

Beta operated in parallel-research mode this session and dropped 6 bundles to `~/.cache/hapax/relay/context/`. Bundle 2 was consumed live in Phase 1 (its BEST + OSF + frozen-files patterns flowed directly into alpha's implementation). 5 bundles remain queued in `lrr-state.yaml::beta_drops_queued`:

| Bundle | Phase | Notes |
|---|---|---|
| Bundle 1 | 3 + 5 | Hermes 3 70B EXL3 download + Blackwell sm_120 + TabbyAPI dual-GPU layer-split + gpu_split ordering |
| Bundle 4 | 6 | Governance drafts + axiom amendments + stream-mode state machine |
| Bundle 7 | 7 | Persona + livestream experience design |
| Bundle 7 supplement | 7 | Phase 7 supplement |
| Bundle 8 | 8 | Content programming via objectives + autonomous hapax loop |

**Phase 2 has no queued bundle.** If Phase 2 needs research beyond what the Phase 2 section of the epic design doc provides, expect to file a research probe.

## Hardware milestone pending

- **X670E motherboard install:** ~2026-04-16 (~2 days from retirement). Phase 3 PCIe link width verification should be re-run after the swap. PSU audit likewise depends on post-swap combined-load context.
- **BRIO replacement (Serial 5342C819):** confirmed hardware fault via cable-port swap test (deficit followed body across two USB ports). Cannot sustain 30 fps MJPEG@720p (27.89 fps observed). Replacement coordinated with X670E install.
- **PCIe x4 for 5060 Ti:** accepted as temporary pending X670E slot layout.

## Operator decisions recorded this session

1. **Audio ducking live verification:** deferred to closer-to-stream date. Tests cover state machine + ramp logic; not a blocker for Phase 2+.
2. **MediaMTX:** brought back with `sudo systemctl enable --now mediamtx`. Listening on 1935/8888/8889. Persistent across reboots.
3. **PCIe 5060 Ti x4:** accepted as temporary.
4. **BRIO operator deficit:** accepted; replacement with X670E install.
5. **Roadmap pivot to 5-track unified plan:** approved.
6. **operator-patterns retire-vs-reschedule:** deferred (Option C in audit) to Phase 6 / Phase 8 context.

## Recommended Phase 2 pickup procedure

1. Standard relay onboarding: read `~/.cache/hapax/relay/PROTOCOL.md` once, then `alpha.yaml` (this retirement state) + `beta.yaml` (peer state).
2. Read `~/.cache/hapax/relay/lrr-state.yaml`. Confirm `current_phase: 2`, `current_phase_owner: null`. Claim it.
3. Read this retirement handoff in full, then the Phase 1 close handoff (`docs/superpowers/handoff/2026-04-14-lrr-phase-1-complete.md`).
4. Read Phase 2 section of the LRR epic design doc: `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` (starts around line 288). Phase 2 is **Archive + Replay as Research Instrument**: re-enable the disabled archival pipeline with research-grade metadata injection, segment condition tags, and retention guarantees.
5. Read `systemd/README.md § Disabled Services` for context on why the archival pipeline was disabled and what invariants Phase 2 must restore.
6. Write per-phase spec at `docs/superpowers/specs/2026-04-14-lrr-phase-2-archive-research-instrument-design.md` and plan at `docs/superpowers/plans/2026-04-14-lrr-phase-2-archive-research-instrument-plan.md`.
7. Create worktree `hapax-council--lrr-phase-2` on `feat/lrr-phase-2-archive-research-instrument`.
8. Execute. No beta bundle is queued for Phase 2 — if a research probe is needed, file it before executing items that would benefit.

## Convergence notes

This session's tightest convergence was **Bundle 2 → Phase 1 direct consumption**. Beta's canonical BEST + frozen-files + OSF patterns arrived ~2 hours before alpha opened Phase 1. Alpha lifted the patterns directly into implementation; Phase 1 closed in ~52 minutes because the "what should this look like" step was pre-solved. This is the intended shape of the parallel-research-mode protocol.

The other notable convergence was **Phase 0 Finding C backstop** (chat-monitor warn-cadence fix) landing in the roadmap-pivot PR (#785) and then being verified live in Phase 0 opening (#786). The wait-loop was initializing `last_log_at = 0.0` causing the first warning not to fire; fixed by initializing to `float("-inf")`. Deployed live and verified `active (running)`, no more journal spam.

## What NOT to do in the next session

- **Do not start Phase 2 in the same context-continuation that reads this handoff.** Tonight was the natural retirement point precisely because context load was high. Begin Phase 2 in a fresh alpha run.
- **Do not try to wrap Phase 2 into a single PR.** Phase 2 involves re-enabling the archival pipeline, which touches multiple systemd units, a multi-stage classification+ingest+retention chain, and research metadata wiring. Plan for 3-5 PRs minimum.
- **Do not skip the disabled-services readme.** There are reasons the archival pipeline was disabled. Re-enabling it without understanding those reasons risks regressing invariants that Phase 0 and Phase 1 just stabilized.
- **Do not wait for a Phase 2 bundle from beta.** Beta's parallel-research queue has Phase 2 as a gap. If research is needed, file a probe — don't block on upstream.

## Final sanity checks completed before retirement

- `git status --porcelain` on alpha worktree: clean
- `git log --oneline -5`: shows the Phase 1 PR sequence ending at `b7b29f6c7` (#795)
- `git worktree list`: alpha + rebuild scratch only (lrr-phase-1 removed)
- `lrr-state.yaml`: `current_phase: 2`, `completed_phases: [0, 1]`, `current_phase_owner: null`
- All 9 CI checks green on #795 (typecheck was slow at ~10 min but landed cleanly)

Retiring cleanly.
