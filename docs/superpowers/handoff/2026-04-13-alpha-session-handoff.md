# Session Handoff — 2026-04-13 alpha retirement

**Previous handoffs this session date:**
- `2026-04-13-alpha-camera-247-epic-handoff.md` (early-morning retirement of the camera 24/7 epic — opened this session's priority queue)
- `2026-04-13-alpha-oom-cascade-handoff.md` (mid-morning alpha pass that shipped PR #731's WebKit leak fix + daimonion memory containment, between the camera-epic retirement and this session)

**Session role:** alpha.
**Branch at end:** alpha on `main`.
**Duration:** full-day retirement-handoff backlog sweep + a second round at operator direction.

## What shipped

Seven PRs merged green, all pre-commit + CI clean. Commit SHAs reference `origin/main` at the time of merge.

| PR | Commit | Title | Purpose |
|----|--------|-------|---------|
| [#730](https://github.com/ryanklee/hapax-council/pull/730) | `c70209e1d` | `feat(affordance): wire studio.toggle_livestream to compositor.toggle_livestream` | Closes P2 from the camera-epic retirement. Daimonion → compositor IPC via `/dev/shm/hapax-compositor/livestream-control.json` mailbox, atomic tmp+rename write, GLib.idle_add dispatch, status JSON artifact. 9 new tests incl. a `_drive_one_iteration` lockstep guard update. |
| [#733](https://github.com/ryanklee/hapax-council/pull/733) | `f109902b5` | `fix(scripts): resolve USB bus/dev via sysfs parent walk in disconnect sim` | Unblocks P1 on real hardware. Two latent bugs in `studio-simulate-usb-disconnect.sh`: (a) `udevadm --query=property --name=/dev/videoN` doesn't expose BUSNUM/DEVNUM on v4l nodes, (b) `/dev/bus/usb/` uses zero-padded 3-digit paths. Walk sysfs parents for the USB device, `printf "%03d/%03d"` for the devfs path. |
| [#734](https://github.com/ryanklee/hapax-council/pull/734) | `6edf39b60` | `docs(research): BRIO USB topology live survey — brio-room on USB 2.0-only port` | Closes P3 cheap-tier. Live topology survey via lsusb + sysfs walk on all six cameras. **brio-room is architecturally on `usb5/5-4` — a USB 2.0-only root port (version 2.10, speed 480). Not a signal downgrade; the port has no SuperSpeed lane.** Bus 2 has 4 empty 10 Gb SS+ ports — the recommended relocation target. TS4 hub still bus-present but dormant on the camera path. Bundled a smoke-test papercut (`grep -c \| \| echo 0` → `awk '/re/ {n++} END {print n+0}'`). |
| [#735](https://github.com/ryanklee/hapax-council/pull/735) | `dc7e4559a` | `feat(compositor): wire LayoutState + SourceRegistry into StudioCompositor.start()` | Phase D task 14 of the source-registry epic. `StudioCompositor.__init__` gains `layout_path` kwarg, new public attrs `layout_state` / `source_registry`, new `start_layout_only()` helper called from `start()` before lifecycle. Idempotent + fault-tolerant per source. Unblocks the completion epic's Phase 3+ render-path work (PR #739 flipped the render path to consume this wiring within 90 min of merge). |
| [#737](https://github.com/ryanklee/hapax-council/pull/737) | `cd0795afa` | `feat(monitor): P9 imagination-loop freshness watchdog` | Closes BETA-FINDING-2026-04-13-A silent-failure class at the consumer layer. P9 watches `/dev/shm/hapax-imagination/current.json` mtime, 300 s warn / 600 s crit, structurally parallel to P7. Regression pin on the `_P9 > _P7` threshold relationship. Positioned at PR-time as interim coverage before PR #746's producer-side `FreshnessGauge` (Task 8.1) landed; now complementary — see § "Live verification" below. |
| [#740](https://github.com/ryanklee/hapax-council/pull/740) | `e4b7e4826` | `fix(gmail_sync): idempotent write + targeted unlink` | Root-cause fix for BETA-FINDING-2026-04-13-B logos-api starvation. `_write_recent_emails` previously wiped `rag-sources/gmail/*.md` at the top and rewrote from scratch every 6 h, generating ~12 000 inotify events per cycle through `RAG_SOURCE_RULE`. Now snapshots existing files, content-diffs per email, skips unchanged writes, and unlinks only aged-out files. Critical regression pin: `test_second_run_with_identical_state_writes_zero_files` asserts zero `mtime_ns` changes across 20 files across two consecutive sync calls. |
| [#741](https://github.com/ryanklee/hapax-council/pull/741) | `ec33b9d37` | `fix(compositor): raise MemoryMax 4→6G, add MemoryHigh 5G, cap OTel BSP` | Mirrors PR #731's daimonion OOM-containment pattern. Old 4 G hard ceiling left ~100 MB headroom over steady state. `MemoryMax 4G→6G`, new `MemoryHigh=5G` soft ceiling, OTel BSP queue/batch/timeout caps. See **Finding 1** below for critical follow-up: this is **partial containment on a service with a real anonymous-memory leak**, not a full fix. |

**Net:** ~1 100 lines across agent code, scripts, systemd, tests, and research. All pre-commit hooks green. Every merged PR's CI run passed all of `freeze-check`, `lint`, `secrets-scan`, `security`, `test`, `typecheck`, `vscode-build`, `web-build`.

**Plus**, at session start (07:45): a mystery orphan staged revert of 32 files (PRs #723 + #725 + #726–729) was present in alpha's worktree index at onboarding. Origin unknown — reflog was clean of any reset/rm/commit. Saved the 4 135-line diff to `~/.cache/hapax/relay/forensics/2026-04-13-orphan-staged-revert.patch` for posterity, then restored the worktree via `git restore --source=HEAD --staged --worktree .`. No code lost — everything being reverted was already in `main`. See alpha.yaml history for the full forensic write-up.

## Live verification (as of 14:27 CDT at handoff write time)

All seven PRs verified active except one pending timer:

- **PR #730**: `agents/studio_compositor/state.py::process_livestream_control` present at line 20, called from `state_reader_loop` at line 324. Live compositor executing this code since 13:40 restart. Not yet exercised by an operator-initiated livestream (no voice start since merge).
- **PR #733**: full 5-state FSM recovery loop exercised on brio-synths via real USBDEVFS_RESET. `healthy → degraded → offline → (swap_to_fallback) → recovering → (pipeline rebuild) → healthy → (swap_to_primary)` in ~2 s. Camera re-enumerated on a different `/dev/videoN` node (video13 → video14) and the sysfs walk still resolved correctly.
- **PR #734**: smoke test output confirmed no phantom trailing `0`. Research doc updated with five empirical findings and a specific relocation recommendation (bus 5 → bus 2).
- **PR #735**: journal line `"layout loaded: name=default sources=4 registered=4"` at both the 13:20:52 rebuild-timer automatic restart AND my 13:39:59 manual restart (see § "Reporting honesty" below). Live compositor has `layout_state` + `source_registry` populated.
- **PR #737**: **end-to-end verified on a live outage.** Between audit-start and handoff-write, the imagination loop went stale due to TabbyAPI unloading the `reasoning` model + LiteLLM having no fallback for `model_group=reasoning`. `current.json` mtime age: 3 312 s at audit, and the `hapax-reverie-monitor.timer` fired P9 every minute without interruption:
  ```
  ntfy @ hapax-reverie: 9 consecutive P9 critical alerts in the last 10 min
  journal: ALERT P9_imagination_freshness: current.json age 3312s ≥ 600s critical
  predictions.json: alert_count=1 with the full P9 payload
  ```
  **P9 is currently the only external alerting path for this failure.** See Finding 2.
- **PR #740**: tests pass on main, code in place. **Not yet exercised.** Next `gmail-sync.timer` fire is 18:27 CDT (~4 h from handoff write). Verification command for the next session:
  ```bash
  journalctl --user -u gmail-sync.service --since '18:25' | grep 'Gmail RAG sync'
  # Expected: rewritten=0 unchanged=~6400 removed=0 on a steady mailbox
  ```
- **PR #741**: `systemctl --user show studio-compositor.service -p MemoryMax -p MemoryHigh --value` returns `6442450944` + `5368709120` (6 G + 5 G). Applied live.

## Critical findings from the retirement-handoff audit

**Finding 1 — Compositor has a real anonymous-memory leak; PR #741 is containment, not a fix.**

1 h 10 min post-restart the compositor process shows:

```
VmRSS        5.48 GB   (up from 2.3 GB at restart baseline — ~50 MB/min growth)
VmHWM        5.70 GB   (peak)
VmSwap       1.42 GB   (kernel already reclaiming to swap due to MemoryHigh=5G)
Pss_Anon     4.64 GB   (anonymous, unreclaimable except to swap)
Pss_File     0.42 GB   (file-backed, reclaimable)
```

Projected OOM at the observed leak rate: **~10–15 min from the audit timestamp**, because the hard ceiling is 6 G. PR #741's raise bought ~25 extra minutes over the old 4 G cap. The root cause is not known and is out of retirement-handoff scope, but load-bearing enough to call out.

Candidate next-session investigations (ordered by blast radius):
1. Profile the compositor via `memray`, `scalene`, or `py-spy dump` during steady state. Start point: 5–15 min post-fresh-restart vs 60 min post-restart snapshot.
2. Narrow down whether the leak is Python-object or native (GStreamer/NVENC/cairo) via `tracemalloc` snapshot diff.
3. If the leak is bounded to a specific subsystem (e.g. director_loop LLM span accumulation), fix at source; otherwise add a `RuntimeMaxSec` periodic-restart guardrail with extra camera recovery tolerance.
4. Add `process_resident_memory_bytes` to the compositor's existing Prometheus exporter on `:9482` so operators can see the growth trend without `/proc/<pid>/status`.

**Finding 2 — Imagination loop is DEAD right now and the Qwen XML parser bug beta documented is NOT the current root cause.**

Current failure mode per tick traceback:

```
openai.InternalServerError: Error code: 503 — litellm.ServiceUnavailableError:
  OpenAIException - Error code: 503 - {'detail': 'Chat completion X aborted.
  Maybe the model was unloaded? Please check the server console.'}
No fallback model group found for original model_group=reasoning.
Fallbacks=[{'claude-opus':...}, {'claude-sonnet':...}, {'claude-haiku':...},
          {'gemini-pro':...}, {'gemini-flash':...}, {'balanced':...}, {'fast':...}]
```

Two actionable findings:

1. **TabbyAPI's model auto-unload cascades to tick failures** because LiteLLM's `router_settings.fallbacks` dict has no entry for `reasoning`. Every other `model_group` has fallbacks. Adding `{'reasoning': ['claude-sonnet', 'claude-opus']}` to the fallback list would auto-recover these 503s by routing to a cloud reasoning model when the local one is cold. One-line config change in `docker/litellm/config.yaml` (or wherever the LiteLLM router config lives).
2. **P9 is the reason this is even visible.** Without PR #737, this would be another 36 h silent outage matching beta's BETA-FINDING-A symptom. P9 + PR #746's producer-side `FreshnessGauge` together make this failure class observable from both sides.

**Finding 3 — PR #740 verification gap.**

Unit tests prove the algorithm. The live flood-suppression effect is unverified until the 18:27 CDT timer fire. **Regression risk is bounded** because the new code is strictly more conservative than the old wipe-and-rewrite, but the first real-world cycle after merge is the confirmation gate. Next session should grep `journalctl --user -u gmail-sync.service --since '18:25'` for the `Gmail RAG sync: in_window=X rewritten=Y unchanged=Z removed=W` log line and verify `rewritten` drops from ~6 400 to ≤20 for a typical steady mailbox.

**Finding 4 (lower priority) — PR #735 layout_path default is CWD-relative and fragile.**

`_DEFAULT_LAYOUT_PATH = Path("config/compositor-layouts/default.json")` resolves relative to CWD. Works in production because the systemd unit sets `WorkingDirectory=%h/projects/hapax-council`, but any caller that invokes `StudioCompositor` from a different CWD silently falls through to `_FALLBACK_LAYOUT` without alerting. The `test_default_layout_path_is_repo_relative` test checks string equality, not actual file resolution.

**Fixed in this PR** — see the companion commit that makes `_DEFAULT_LAYOUT_PATH` absolute via `Path(__file__).resolve().parents[2] / "config/compositor-layouts/default.json"`, updates the test to assert real resolution, and keeps the `layout_path` kwarg override path unchanged.

## Reporting honesty

One small correction to what I told the operator earlier today. My `do 1-3` restart claim of "single cam interruption" was slightly wrong. There were actually **two** compositor restarts in the window:

- 13:20:52 CDT — automatic, `hapax-rebuild-service.timer` picking up PR #735 on main before my manual step ran
- 13:39:59 CDT — my manual restart that picked up PR #735 (already loaded from the auto-restart) + PR #739 (Phase 3 render path) + PR #741 (memory ceiling)

The operator experienced two short cam interruptions, not one. Functionally harmless but worth correcting.

## Relay state at retirement

- **alpha**: this session, now retired. `alpha.yaml` updated with the full arc and convergence notes.
- **beta**: last updated 2026-04-13T03:03 (the discovery sweep that surfaced findings A–C). Not seen since. Beta-standby worktree at `~/projects/hapax-council--beta` still on `bb247cf25` from early morning. Stale, not mine to clean up.
- **delta**: retired 2026-04-13T07:25 after shipping PRs #723/#725/#717. Has since (probably via a new delta session or beta covering the work) shipped Phases 1–8 of the source-registry completion epic (PRs #736–#746 land in sequence over the afternoon). The `~/projects/hapax-council--phase-8-observability` worktree is active with uncommitted work — not mine, respect it.
- **Convergence log** will get an entry for the P9 ↔ FreshnessGauge pair.
- **Inflections directory** gets a final session-summary inflection addressed to `both`.

## Next session pickup

Ordered by urgency:

1. **Fix the LiteLLM `reasoning` fallback gap** — one-line config change, eliminates the class of imagination-loop tick failures currently flooding P9 alerts.
2. **Investigate the compositor memory leak** — see Finding 1's candidate investigations. The cgroup ceiling will save the service from OOM-killing in the short term but the leak rate implies a full recycle every ~2 h.
3. **Verify PR #740 at 18:27 CDT** — check gmail-sync service logs for the first post-merge run.
4. **Consider the PR #735 fragility fix carried in this PR** (if it hasn't merged yet when the next session onboards) — the handoff PR bundles it as a non-docs CI gate companion AND a real audit finding.
5. **The `beta-standby` worktree** is 11+ hours stale. Probably safe to sync after confirming beta isn't using it.

## References

- Today's PRs: #730, #733, #734, #735, #737, #740, #741 (mine) + #731, #732, #736, #738, #739, #742, #743, #744, #745, #746 (intervening beta/delta work)
- Camera 24/7 retirement handoff: `docs/superpowers/handoff/2026-04-13-alpha-camera-247-epic-handoff.md`
- OOM cascade handoff: `docs/superpowers/handoff/2026-04-13-alpha-oom-cascade-handoff.md`
- Source-registry completion epic plan: `docs/superpowers/plans/2026-04-13-reverie-source-registry-completion-plan.md`
- BRIO hardware research: `docs/research/2026-04-12-brio-usb-robustness.md` (now carries the live topology survey from PR #734)
- Relay files: `~/.cache/hapax/relay/{alpha,beta,delta}.yaml`
- Orphan revert forensics: `~/.cache/hapax/relay/forensics/2026-04-13-orphan-staged-revert.patch`
