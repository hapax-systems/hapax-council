# Session Handoff — 2026-04-12

**Previous handoff:** `docs/superpowers/handoff/2026-04-11-session-handoff.md`
**Scope of this session:** compositor unification epic follow-ups 1–3, audit, audit action items round 2, live debugging (YouTube player, Reverie vocabulary corruption)
**Session role:** beta
**Branch:** main at `45ce584d3` — clean working tree, all PRs merged, worktrees = [alpha=main, beta=beta-standby]

---

## What was shipped

### Merged PRs (chronological)

| PR | Title | What it did |
|----|-------|-------------|
| #670 | `feat(f1)`: Rust transient texture pool allocator | Followup F1 — Rust-side `TransientTexturePool<T>` with bucketed `acquire_tracked` + `get` + reuse-ratio telemetry. Standalone; not yet wired into the executor. |
| #671 | `feat(f2)`: per-frame layout budgets in BudgetTracker | Followup F2 — `total_last_frame_ms`, `total_avg_frame_ms`, `over_layout_budget`, `headroom_ms` so the frame planner can reason about the whole layout's cost, not just per-source. |
| #672 | `feat(f3)`: compositor degraded-signal publisher | Followup F3 — `build_degraded_signal` + `publish_degraded_signal` write `~/hapax-state/dev-shm/hapax-compositor/degraded.json` so VLA/stimmung can consume compositor degradation as a signal. Wall-clock + monotonic timestamps, worst-source summary, per-source skip counts. |
| #673 | `audit`: compositor unification epic — multi-phase audit + critical fixes | 6-batch parallel Explore-subagent audit covering Phases 2–7 + 5b + followups. Report at `docs/superpowers/audits/2026-04-12-compositor-unification-audit.md`. Fixed two critical findings (dynamic_pipeline hardcoded `"final"` fallback; missing `test_clock_source_renders_into_canvas`) and two quality findings (`transient_pool::fresh<T>` unused; `reuse_ratio` docstring/impl mismatch) in the same PR. |
| #674 | `feat`: Layout convenience helpers (audit follow-up) | HIGH-severity audit item. Added `source_by_id`, `surface_by_id`, `assignments_for_source`, `assignments_for_surface`, `render_targets` on `Layout`. 10 new tests against the garage-door canonical layout. |
| #675 | `feat(3b)`: finish Cairo class migrations to CairoSource | HIGH-severity audit item. Migrated `AlbumOverlay`, `OverlayZoneManager`, `TokenPole` from direct-render Cairo to the `CairoSource` protocol (background thread + cached output surface). After this PR there is NO Cairo rendering on the GStreamer streaming thread — every source feeds through a `CairoSourceRunner`. New module `agents/studio_compositor/album_overlay.py`. 7 new tests. |
| #676 | `feat`: audit polish round (observability, validation, cleanup) | MEDIUM+LOW audit items bundled: `publish_costs` payload envelope (`schema_version`, `timestamp_ms`, `wall_clock`, `sources`), `publish_degraded_signal` wall-clock, shared `atomic_write_json` helper, 3 silent-failure log level promotions (LayoutStore OSError, CairoSource publish failure, `dynamic_pipeline.rs` unknown-backend), `SourceSchema.rate_hz` `gt=0.0` + Field descriptions, `UpdateCadence` per-value docstrings, difflib "did you mean" hints in `Layout._validate_references`, removed vestigial `transient_pool.rs::acquire` method. |

**Net result:** the compositor unification epic is formally complete. Every audit action item classified HIGH/MEDIUM/LOW has been shipped or has an explicit defer note.

### Documentation written

- `docs/superpowers/audits/2026-04-12-compositor-unification-audit.md` — 47 findings across 6 batches, severity-ranked action table
- `docs/research/2026-04-12-brio-usb-robustness.md` — hardware investigation note (see "Camera robustness" below)
- `CLAUDE.md` — added **Studio Compositor** and **Reverie Vocabulary Integrity** sections
- (this file) — `docs/superpowers/handoff/2026-04-12-session-handoff.md`

---

## Live debugging this session

These are NOT code changes, just things I did manually that the next session should know about:

### 1. YouTube player was stalled (~13 hours)

`youtube-player.service` was "active" but had been frozen since `Apr 12 00:37` (yt-dlp URL extraction timeout killed the auto-advance loop). Effect: no `yt-frame-*.jpg` files in SHM, Sierpinski corners blank.

**Fix applied:** `systemctl --user restart youtube-player` + manually POSTed three `/slot/{0,1,2}/play` requests with random playlist picks. Frames started flowing within seconds.

**Bootstrap gap (still open, not fixed):** `agents/studio_compositor/director_loop.py` advances slots via the `yt-finished-N` marker mechanism but has NO cold-start path. After any `youtube-player.service` restart, the Sierpinski corners stay empty until a human manually bootstraps. Defensive PR deferred to future work (see "Pending" below).

### 2. Reverie vocabulary in-memory corruption

The reverie mixer's `SatelliteManager._core_vocab` (cached at mixer `__init__` via `load_vocabulary()`) was holding a mutated vocabulary with `content: sierpinski_content` and an extra `lines: sierpinski_lines` node. The on-disk preset `presets/reverie_vocabulary.json` is pristine (md5 matches git HEAD, `content: content_layer`).

No code path in current `main` writes `sierpinski_*` into the core vocab. First `GraphValidationError: Unknown node type 'sierpinski_content'` appeared in `hapax-reverie` logs at `Apr 11 20:11:00` — four minutes before the user observed the corruption in the Reverie visual surface. From that moment every rebuild hit `keeping previous graph` and `plan.json` in SHM froze in the stale sierpinski state for ~18 hours.

**Fix applied:** `systemctl --user restart hapax-reverie.service`. Mixer re-read the pristine preset, wrote a fresh 8-pass vocabulary plan. Reverie also upgraded from v1 → v2 plan format as a side effect.

**Root cause not determined.** Either the old mixer code mutated the dict (no such code in main), or a since-deleted/edited helper did, or the preset file was different when the process booted at 19:28:39 (preset mtime is 19:50 which is suspicious but git reflog shows no checkout at that time). Could not reproduce.

**Defensive mitigation (not shipped):** `SatelliteManager.maybe_rebuild()` could re-load the preset if a rebuild ever fails with `GraphValidationError`, preventing the 18-hour freeze. Filed as pending.

### 3. BRIO USB cameras — hardware issue

Two of three BRIOs (brio-operator serial 5342C819, brio-room serial 43B0576A) were disconnected from the USB bus at `Apr 12 13:41:21` as part of a 4-device cascade (`5-1, 6-2, 5-3, 6-4` all dropped in the same second). The compositor's `try_reconnect_camera` has been retrying every 10s but cannot fix it because the devices are physically absent from `/dev/v4l/by-id/`. Only `brio-synths` (9726C031, on bus 8 Renesas xhci) stayed connected.

Kernel logs showed 15 USB disconnect events over the prior 19 hours, some with `device descriptor read/64, error -71` (EPROTO — USB signal integrity error). This is a hardware problem, not software. Full details + investigation plan in `docs/research/2026-04-12-brio-usb-robustness.md`.

**Fix applied:** none possible from software. Reboot clears it.

### 4. Unrelated failed services (noted but not touched)

- `hapax-rebuild-services.service` — FAILED with `hapax-daimonion.service restart failed` (unrelated voice daemon issue)
- `hapax-build-reload.service` — FAILED
- `llm-cost-alert.service` — inherited from previous handoff, still failing
- `vault-context-writer.service` — inherited from previous handoff, still failing

---

## Delta from the 2026-04-11 handoff

The prior handoff listed a few open items. Here's the status now:

| Item from 2026-04-11 handoff | Status 2026-04-12 |
|------------------------------|--------------------|
| **Clean up PR #644** (Sierpinski visual layout, 12 commits on stale branch) | N/A — superseded. Sierpinski is now the live `SierpinskiRenderer` + `SierpinskiCairoSource` in `agents/studio_compositor/sierpinski_renderer.py` via the CairoSource protocol (background thread at 10fps). Merged as part of Phase 3b. |
| **Solve the Sierpinski CPU problem** | Solved by Phase 3b: background-thread render + cached output surface. The streaming-thread blit is sub-millisecond. |
| **Dynamic camera resolution** | Not started. Still a recommended future spec. |
| **Stream research infrastructure** (Qdrant persistence + Langfuse scoring) | Not worked on. Director loop writes reaction history to Qdrant already (per 04-11 handoff); scoring not verified this session. |
| **Fix failed services** (`llm-cost-alert`, `vault-context-writer`) | Still failing, not touched this session. |
| **Stale branch `feat/sierpinski-visual-layout` (PR #644)** | Presumably closed when the content was absorbed into main — needs verification. |

No regressions from the prior handoff's "what's working" section.

---

## Current system state (as of 2026-04-12 14:30 CDT)

**Git:** main at `45ce584d3`. Working tree clean. Worktrees: alpha at main, beta at beta-standby. No local stale branches. 10 open dependabot PRs (not reviewed this session).

**Compositor:** running, outputting frames at ~30fps to `/dev/video42`. All four `CairoSourceRunner` background threads confirmed started:

- `overlay-zones` @ 10fps canvas 1920×1080
- `album-overlay` @ 10fps canvas 300×450
- `token-pole` @ 30fps canvas 1920×1080
- `sierpinski-lines` @ 10fps canvas 1920×1080

**Reverie:** restarted this session, plan.json is the canonical 8-pass vocabulary (`noise → rd → color → drift → breath → fb → content(content_layer) → post`), version 2 format, no sierpinski nodes in core.

**Cameras:** 4 of 6 active. `brio-operator` and `brio-room` offline (hardware). Reboot will likely restore them.

**YouTube player:** running, 3 slots bootstrapped. Director loop is watching for `yt-finished-N` markers to auto-advance. Playlist has ~100 items.

**Infrastructure:** 13 Docker containers running (LiteLLM, Qdrant, Postgres, Langfuse, Prom/Graf, Redis, ClickHouse, MinIO, n8n, ntfy, OpenWebUI, etc.). 3 failed systemd user units (`hapax-rebuild-services`, `hapax-build-reload`, `chat-monitor` activating).

---

## Pending / open items

**Audit punch list:** all HIGH/MEDIUM/LOW items shipped. One explicit defer:

- `OutputRouter.validate_against_plan` — scheduled for when the first real consumer lands; no work today.

**Deferred-by-me this session:**

- **Defensive reload in `SatelliteManager`.** After 18 hours of frozen `plan.json` due to in-memory vocab corruption, it's clear the mixer should re-load the preset on `GraphValidationError`. One-line fix with one test. Worth shipping.
- **Director loop cold-start for YT slots.** After any `youtube-player.service` restart, the Sierpinski corners stay blank because nothing cold-starts the slots. Needs `_start_director` to push an initial `/slot/N/play` if `yt-frame-N.jpg` doesn't exist within N seconds. Small PR.

**From 2026-04-11 handoff, still open:**

- Dynamic camera resolution/framerate system (research complete, no spec written)
- VST effects on Hapax voice (PipeWire filter-chain path clear, no code)
- Simulcast (Twitch/Kick via Restream.io)
- Chat-reactive effects (YouTube Live chat → preset switching)
- Stream overlay in compositor (viewer count, chat, preset name)
- Native GStreamer RTMP (eliminate OBS)
- TikTok clip pipeline
- Stream as affordance (DMN decides when to go live)
- Failed services: `llm-cost-alert`, `vault-context-writer`

**New from this session:**

- **BRIO USB robustness investigation.** Full note at `docs/research/2026-04-12-brio-usb-robustness.md`. Cheapest fix to try first: swap offline BRIOs to the bus-8 Renesas port that `brio-synths` uses today and see if they stay up. Expensive-but-likely-fix: replace the TS4 USB3.2 Gen2 hub with a known-good industrial hub ($60).
- **Phase 4c transient-pool wiring.** The F1 Rust allocator is landed but not consumed. The executor still allocates intermediate textures inline. Wiring is the next logical step for memory reduction.

---

## How to continue in a fresh session

1. **Pull main and verify clean state:**
   - `git pull --ff-only origin main`
   - `git status` — expect clean
   - `git worktree list` — expect alpha + beta only

2. **Read this handoff + the audit report:**
   - `docs/superpowers/handoff/2026-04-12-session-handoff.md` (this file)
   - `docs/superpowers/audits/2026-04-12-compositor-unification-audit.md`

3. **Verify the compositor stack is up:**
   - `systemctl --user is-active studio-compositor hapax-reverie hapax-imagination youtube-player`
   - Inspect `~/.cache/hapax-compositor/status.json`
   - Confirm `plan.json` in the SHM imagination pipeline directory has zero occurrences of "sierpinski"

4. **If YT frames are missing:** restart `youtube-player.service` and bootstrap the three slots manually (see "Live debugging" §1 above). This will keep happening until the director-loop cold-start PR lands.

5. **If Reverie shows unexpected shader nodes:** `systemctl --user restart hapax-reverie.service` and confirm `plan.json` no longer contains the stale node type.

6. **If BRIO cameras are missing:** the issue is physical. See `docs/research/2026-04-12-brio-usb-robustness.md` for the diagnostic ladder.

7. **For the next productive work:** the two small defensive PRs (Reverie vocab reload on error, Director loop cold-start) are the highest-leverage unfinished items. Both are <30 lines of code. After those, the Phase 4c transient-pool wiring is the largest remaining unclosed loop from the epic.

---

## Handoff note: parallel Claude sessions incoming

The operator plans to reboot after this handoff and run two Claude Code sessions in parallel (alpha + beta) on separate worktrees. Coordination rules already documented in:

- Workspace `CLAUDE.md` → "Git Workflow" → three-worktree-slot rule
- Global operator `CLAUDE.md` → "Subagent Git Safety"

Beta is working out of the `--beta` worktree. Alpha is the primary worktree. A third "spontaneous" slot is allowed; it must be cleaned up before starting new work. Hooks in `hooks/scripts/` enforce branch discipline and block destructive commands on commits-ahead-of-main branches.
