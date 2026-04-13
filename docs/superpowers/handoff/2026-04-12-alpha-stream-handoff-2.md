# Session Handoff — 2026-04-12 pass 2 (alpha stream)

**Previous handoff:** `docs/superpowers/handoff/2026-04-12-alpha-stream-handoff.md` (pass 1 — A1/A2/A10/A11 + FU-1 prediction).
**Scope of this session:** pass 2 of Stream A (studio livestream surface). Picked up cold from the pass-1 retirement, peeled the full silent-failure onion that pass 1 predicted, fixed two net-new bugs discovered along the way, and shipped the first two new features on the suggested-order list (A4 + A5).
**Session role:** alpha
**Branch at end:** alpha worktree on `main`, clean working tree. No open alpha PRs.

---

## What was shipped

All six PRs merged to `main`.

| PR | Item | Title | Result |
|----|------|-------|--------|
| [#690](https://github.com/ryanklee/hapax-council/pull/690) | FU-1 (probe) + FU-2 | `fix(director_loop)`: FU-1 probe — log LLM response + FU-2 metadata slot cast | Three log lines inside `_call_activity_llm` (`raw_content` length/prefix on receipt, parsed `react` length/prefix before return, empty-content WARNING with `finish_reason`) that collapsed the "what branch is firing?" question from unknown to one-tick-of-observation. Also wrapped `self._active_slot` in `str()` inside the `hapax_span` metadata so langfuse stops dropping the slot attribution on every tick (FU-2). |
| [#692](https://github.com/ryanklee/hapax-council/pull/692) | FU-1 (fix) | `fix(director_loop)`: raise `max_tokens` 300→2048 | Root cause of the 47+ min director silence post-A10 restart: Claude Opus was returning `finish_reason=length` with an empty content field on **every** perception tick. 300 tokens was not enough budget for Opus to emit any preamble + the JSON reaction. Bumped to 2048. One tick after deploy produced `Parsed react (462 chars)` and the first `REACT [react]:` log since the restart. |
| [#693](https://github.com/ryanklee/hapax-council/pull/693) | A12 (new) | `fix(yt-player)`: recover from yt-dlp URL extraction failures | Net-new item filed this session after observing the failure mode during FU-1 diagnosis. Slots 1 and 2 went dead at 16:19/16:20 when yt-dlp `--print` and `-g` both hit the 15-second timeout for two specific video IDs. `VideoSlot.play()` caught the exception, logged it, and silently returned — the slot sat wedged until service restart because `auto_advance_loop` only notices ffmpeg-level exits. Two fixes: raise each yt-dlp subprocess timeout 15s → 45s, AND write a `yt-finished-N` marker with sentinel `rc=-1` on extraction failure so the compositor's `VideoSlotStub.check_finished` re-dispatches `_reload_slot_from_playlist` with a *different* random video. Self-healing via re-roll. 4 new tests. |
| [#694](https://github.com/ryanklee/hapax-council/pull/694) | FU-5 (new) | `fix(director_loop)`: reject 0-byte frame files in cold-start + LLM gather | Cascading consequence of A12 deploy: a yt-player restart left stale 0-byte yt-frame-N.jpg files behind. Two sites in `director_loop` that only used `Path.exists()` (no size check) both broke. `_slots_needing_cold_start` thought every slot was healthy and never dispatched the cold-start. `_gather_images` sent the 0-byte JPEGs to Claude as `image_url` content, Claude responded HTTP 400, and every tick dropped into the `log.exception("Activity LLM call failed")` branch with a big stack trace. Both sites now also check `.stat().st_size > 0` under an OSError guard. 3 new tests. |
| [#695](https://github.com/ryanklee/hapax-council/pull/695) | A4 | `feat(compositor)`: stream status overlay CairoSource | Ninth `CairoSource` in the unified compositor pipeline. A compact three-line status strip composited in the bottom-right corner showing the current FX preset (from `fx-current.txt`), active viewer count (from `token-ledger.json`), and chat activity (from `chat-state.json`). Each row degrades gracefully when its SHM source is missing or malformed. Pattern mirrors `TokenPole` / `AlbumOverlay` verbatim. Runs at 2 fps — file-polling cadence. 21 new tests. Visually verified on-stream: crop of the bottom-right of `fx-snapshot.jpg` shows the three lines rendering exactly as designed (`FX: chain` / `● 1 viewer` / `░ chat idle`). |
| [#698](https://github.com/ryanklee/hapax-council/pull/698) | A5 | `feat(compositor)`: chat-reactive preset switching via keyword match | Viewers can request an effect preset by typing its name in the live chat. A4's overlay shows the current preset, so the feedback loop is closed. New `PresetReactor` class in `agents/studio_compositor/chat_reactor.py`: word-boundary regex match, case-insensitive, longest-wins for `datamosh_heavy` vs `datamosh`, 30s cooldown, no-op on current preset does NOT consume the cooldown, writes the loaded preset graph to `graph-mutation.json`. Integrated via one hook in `scripts/chat-monitor.py._process_message`. Axiom guardrail (interpersonal_transparency): no per-author state, no message persistence, no author name in logs — enforced by a caplog assertion in the test suite. 19 new tests. Probe-verified on the real `presets/` directory: indexed 27 presets, matched `"please use halftone"` → `halftone_preset`, `"NEON plz"` → `neon`, `"datamosh go"` → `datamosh`. |

### Convergence sightings logged

- **2026-04-12T21:26Z | CAUSAL** — FU-1 root cause (`finish_reason=length` on `max_tokens=300`), beta shipped CC1 stream-as-affordance (#691), director loop producing output post-fix.
- **2026-04-12T21:30Z | SYSTEMIC** — A12 is the third instance of the runtime-state-loss-without-auto-recovery pattern alongside A1 (#679, cold-start blank corners) and B1 (#678, frozen plan.json). Worth a retrospective sweep; see "Pattern alert" below.
- **2026-04-12T20:02Z | COMPLEMENTARY** — A4 + A5 form a closed feedback loop: A4 shows the current preset on the stream, A5 accepts chat requests for new presets. Visible state is a precondition for interactive state — worth noting as a pattern.

---

## The 5-layer silent-failure onion

Pass 1's prediction was exactly right. Every layer had to be fixed before the next became visible.

| Layer | Symptom | Fix | Session |
|---|---|---|---|
| 1 | `hapax_span` yielded after throw → `RuntimeError: generator didn't stop after throw()` masking every caller exception | `ExitStack`-based span manager with separate paths for setup vs yield-block failures | pass 1 (#685) |
| 2 | `_load_playlist()` deleted in PR #644 alongside `spirograph_reactor.py` without consumer migration | Restore the helper in `director_loop.py`; hardened against TimeoutExpired and FileNotFoundError | pass 1 (#686) |
| 3 | `studio-compositor.service` missing `EnvironmentFile=` — `LITELLM_API_KEY` / `LANGFUSE_PUBLIC_KEY` never loaded | Add `EnvironmentFile=$XDG_RUNTIME_DIR/hapax-secrets.env` matching peer services | pass 1 (#686) |
| 4 | `max_tokens=300` — Claude Opus returning `finish_reason=length` with empty content on every tick | Raise to 2048; keep the empty-content WARNING from the probe (#690) | **pass 2 (#692)** |
| 5 | `_slots_needing_cold_start` + `_gather_images` only check `.exists()`, not file size — 0-byte stale frames slip through | Add `.stat().st_size > 0` check with OSError guard at both sites | **pass 2 (#694)** |

The lesson from pass 1 ("cross-file helper deletions need explicit consumer audit; the `hapax_span` bug is a footgun; silent failure onion is a real pattern") compounds with pass 2's lesson: **file existence is not file validity**. Every `.exists()` check in a data pipeline is a latent 0-byte bug unless the file is written atomically AND the writer is known to always produce non-empty output.

---

## Pattern alert — "runtime state loss without auto-recovery"

Three instances now, all of them real production outages:

1. **A1 (#679)** — YouTube player restart leaves Sierpinski corners blank because nothing triggers a cold-start dispatch on the compositor side.
2. **B1 (#678)** — Reverie satellite manager caches the vocabulary preset in-memory at startup; a runtime `GraphValidationError` leaves a stale `plan.json` for 18+ hours with no auto-reload.
3. **A12 (#693)** — yt-player catches a yt-dlp timeout, logs it, and silently returns. Slot sits wedged until service restart because `auto_advance_loop` only notices ffmpeg-level exits.

All three share the same anti-pattern: a file-based or subprocess-based state transition goes wrong at the boundary, the consuming side has no way to observe the failure, and the system needs an operator to notice and restart.

**Recommended for a future session (not urgent):** retrospective sweep of the studio pipeline for other one-shot loaders / one-shot consumers that lack a retry mechanism. Candidates worth checking:

- Contact mic capture (pw-cat subprocess)
- Pi NoIR edge daemon HTTP POST path
- Reverie mixer `load_preset` (partially fixed by B1, but other code paths?)
- Any `subprocess.run` with a `timeout=` and a broad `except Exception`

---

## Delta from the pass-1 handoff

| Item from pass 1 | Status now |
|---|---|
| **FU-1** — `_speak_activity` logs not firing post-restart, first probe recommended | **Shipped** as #690 (probe) + #692 (fix). Root cause: `max_tokens=300` + `finish_reason=length` loop. Post-fix director produces reactions at ~8s cadence. |
| **FU-2** — `metadata.slot` type warning (one-line cast to str) | **Shipped** bundled with #690. |
| **FU-3** — Parallel yt-dlp invocation on cold start (module-level lock / sequential dispatch) | **Not touched.** Still three cold-start threads racing on the same extractor. Harmless but wasteful. Small follow-up for any session. |
| **FU-4** — Sweep `hapax_span` callers for previously-masked silent failures | **Not touched.** Deferred — nothing was visibly broken this session but the sweep is still worth doing as a retrospective. |
| **A3** — BRIO USB investigation (hardware + possible diagnostic watcher daemon) | **Not touched.** Primarily hardware. Operator needs to physically swap cables / move to the Renesas port. Code-side watcher daemon is an option for a future session if operator prioritises observability. Research note `docs/research/2026-04-12-brio-usb-robustness.md` unchanged. |
| **A4** — Stream overlay compositor source | **Shipped** as #695. |
| **A5** — Chat-reactive effects | **Shipped** as #698 — keyword-triggered preset switching with cooldown. |
| **A6** — Dynamic camera resolution | Not touched. Spec only. |
| **A7** — Native GStreamer RTMP | Not touched. Prerequisite for A8 and CC1. |
| **A8 / A9 / CC1 / CC2** | Not touched. |

### Items NET-NEW from this session

- **A12 (#693)** — yt-player extraction-failure resilience. **Shipped.** New. Filed and closed in the same session after observing slots 1/2 wedge mid-FU-1 diagnosis.
- **FU-5 (#694)** — 0-byte frame file rejection. **Shipped.** New. Filed and closed after observing Claude HTTP 400 on 0-byte images during A12 deploy.
- **FU-6 (candidate)** — `scripts/rebuild-logos.sh` uses `git worktree add` for builds instead of mutating the alpha worktree. **Not shipped.** See "Blockers / friction" below.

---

## Decisions made this session

1. **FU-1 probe before fix.** Added three log lines inside `_call_activity_llm` (raw_content prefix + length, parsed react prefix + length, empty-content WARNING with finish_reason) and deployed them first. Got the branch identification from one tick of production traffic. Fixed the real bug in a separate narrow PR (#692). The probe WARNING stays in place as observability for future regressions.

2. **`max_tokens` 300 → 2048.** Opus needs headroom for preamble + the JSON response. 2048 is generous; at ~8s cadence the cost is bounded. The empty-content WARNING (#690) stays in case 2048 is *also* insufficient for some prompt length.

3. **A12 fix strategy: marker + timeout raise, no retry-with-backoff.** The clean recovery path is to re-dispatch a DIFFERENT random video via the existing `_reload_slot_from_playlist` path. Re-trying the same URL would loop forever on a fundamentally broken video. Re-rolling leverages the 105-video playlist's size — with ~95% good videos, expected time to recovery is one tick.

4. **FU-5 two-site fix in one PR.** Both `_slots_needing_cold_start` and `_gather_images` had the same latent bug (`.exists()` only). Fixing one without the other would have left half the cascade — cold-start dispatch would recover, but `_gather_images` would still send 0-byte images to Claude until the recovered frame overwrote them. Fixing both atomically is the right scope.

5. **A4 scope: three lines, fixed position, 2 fps.** Resisted building a general-purpose status-strip framework. Kept the module small (~170 lines) and the bindings to source files hard-coded because that's the only layout the stream actually shows. Follows the existing `TokenPole` / `AlbumOverlay` pattern exactly.

6. **A5 scope: keyword match, not LLM classification.** Simplest meaningful interaction is "type the preset name to switch to it". Discoverable because A4 shows the current preset name on-stream. Viewers can read the overlay and type any *other* preset name they remember or experiment with. Word-boundary regex + longest-wins resolves `datamosh_heavy` vs `datamosh` correctly. Cooldown (30s) prevents thrash; no-op-on-current-preset does NOT arm the cooldown so chat spam can't lock out legitimate switches.

7. **A5 axiom guardrail via test, not convention.** Rather than "try not to log author names", added a `caplog` assertion that the log line contains neither author names nor message content. Enforcement via test is durable; convention decays.

---

## Live debugging this session

### 1. The `fx-snapshot.jpg` is post-PiP — A4 visual verification works

A4 text wasn't initially visible in my first visual check because I was reading a scaled-down version. Confirmed the pipeline order: `fx_convert → pip_overlay (cairooverlay) → output_tee → add_fx_snapshot_branch (scale 1280x720)`. The pip_overlay is where `_pip_draw` runs and my `StreamOverlay.draw(cr)` is called. The fx-snapshot captures AFTER the pip_overlay, scaled to 720p. A crop of the bottom-right (640x360 quadrant) clearly shows the three-line strip rendering at the expected coordinates.

### 2. The CI test environment has no GI Pango/PangoCairo typelibs

CI failed the first A4 submission because the three `render_tick_*` tests tried to lay out text via `text_render.render_text()`, which imports `gi.repository.PangoCairo` lazily. CI containers ship without GTK. Fix: same skip pattern as `tests/test_text_render.py` — define `_pango_available()` + `requires_pango` marker, decorate the three render tests. The 18 formatter / file-read tests still run unconditionally in CI. Re-deployed, passed on the second run.

### 3. `chat-monitor.service` in an activation-failure restart loop

Pre-existing state — the service needs `YOUTUBE_VIDEO_ID` or `/dev/shm/hapax-compositor/youtube-video-id.txt` to connect to chat, and the stream wasn't live during this session. Restart counter at 32+ by session end. **Not an A5 issue.** Verified A5 end-to-end via a direct Python probe against the real `presets/` directory: `PresetReactor()` indexed 27 presets, matched `"please use halftone"` → `halftone_preset`, `"NEON plz"` → `neon`, `"datamosh go"` → `datamosh`, rejected `"something random"`. The A5 integration point in `chat-monitor.py._process_message` is wrapped in a try/except so when chat-monitor eventually stabilises it will either work or fall through silently.

### 4. `scripts/rebuild-logos.sh` detaches alpha's worktree

`hapax-rebuild-logos.timer` fires every 5 min. When it sees `origin/main` has advanced AND the alpha worktree is on a feature branch, it runs `git checkout --detach origin/main` for the duration of the build (`just install`, ~60–300s), then restores with `git checkout <branch-name>`. During the build window, alpha's working tree appears reverted to main — feature-branch edits to files that also exist on main (like `director_loop.py`) vanish from disk until the restoration checkout.

**This hit me 4+ times this session.** Each incident required a cherry-pick recovery dance: commit on the detached HEAD, switch back to the branch, cherry-pick the detached commit onto it, push. Commits on the branch are NEVER at risk (the branch ref isn't touched), but uncommitted edits ARE at risk during the build window.

**Filed as FU-6 candidate.** A small follow-up PR could change rebuild-logos.sh to use `git worktree add` for an isolated scratch tree: no mutation of the user-facing worktree, no race condition, no recovery dance. ~15 lines of shell.

**Also saved to auto-memory** at `~/.claude/projects/-home-hapax-projects/memory/feedback_rebuild_logos_worktree_detach.md` so the next alpha session recognises the symptom without wasting time.

---

## Current system state (as of 2026-04-12 ~20:07 CDT)

- **Git:** `main` at `c01a0f09c` (A5 merged). Alpha worktree clean, no uncommitted changes. `git fetch --prune origin` run at session close — all alpha branches pruned locally. `beta-standby` and `fix/reverie-audit-followup` are beta's local branches; don't touch.
- **Worktrees:** alpha (`~/projects/hapax-council/`), beta (`~/projects/hapax-council--beta/`), spontaneous beta reverie-audit-followup worktree (`~/projects/hapax-council--audit-followup/`) with uncommitted beta edits — **do not disturb**.
- **Compositor:** running, director loop producing reactions at ~8s cadence. All 3 Sierpinski slots populated. `REACT [react]:` log lines firing. A4 stream-overlay thread alive at 2 fps. A5 code present but chat-reactor not yet exercised end-to-end (chat-monitor service awaiting YOUTUBE_VIDEO_ID).
- **Services:** `studio-compositor`, `youtube-player`, `logos-api`, `hapax-daimonion` all active. `chat-monitor` activating (pre-existing — awaits YOUTUBE_VIDEO_ID).
- **Stream output:** all 3 Sierpinski corners populated, ffmpeg PIDs stable, HLS playlist writing normally, token pole cycling, A4 overlay visible bottom-right.
- **Beta state:** mid-session. PR #697 merged (audit follow-ups). PR #699 open (beta pass-2 retirement handoff, not yet merged). `~/projects/hapax-council--audit-followup/` has uncommitted reverie edits — that's beta's in-flight work.

---

## Pending / open items (for the next alpha session)

### Stream A items not touched

- **A3** — BRIO USB investigation. Hardware — operator needs to:
  1. Record `lsusb -t` and physical port-to-camera mapping immediately after reboot
  2. Swap the two offline BRIOs to the bus-8 Renesas port that `brio-synths` uses today (confirms whether the problem is the camera or the hub branch — cheapest test)
  3. Check TS4 hub is on a dedicated 2.4A+ power supply
  4. Feel TS4 hub housing after 30 min of streaming (thermal check)

  Code-side deliverable option: a USB event watcher daemon tailing `journalctl -k` for `error -71` on Logitech VID `046d` + known BRIO serials (`5342C819`, `43B0576A`, `9726C031`), writing structured events to `/dev/shm/hapax-compositor/camera-events.jsonl` and firing an ntfy alert on disconnect. Small, scoped, observability-only. The hardware still needs operator intervention.

- **A6** — Dynamic camera resolution/framerate spec + implementation. Still spec-only.
- **A7** — Native GStreamer RTMP (eliminate OBS). Prerequisite for A8 / CC1.
- **A8** — Simulcast (Twitch/Kick via tee or Restream.io). Depends on A7.
- **A9** — TikTok clip pipeline.

### Follow-ups still open

- **FU-3** — Parallel yt-dlp invocation on cold start. Module-level lock or sequential dispatch. Small fix.
- **FU-4** — Sweep `hapax_span` callers for previously-masked silent failures. Retrospective.
- **FU-6** (new candidate) — `scripts/rebuild-logos.sh` uses `git worktree add` for builds instead of mutating alpha's worktree. See "Live debugging §4".

### Cross-cutting

- **CC1** — Stream as affordance. Beta shipped the beta-side in #691 (`studio.toggle_livestream` affordance registered). Alpha owes the compositor-side RTMP trigger — blocked on A7.
- **CC2** — `OutputRouter.validate_against_plan`. Deferred until first real consumer lands (explicit from the 2026-04-12 audit).

---

## How to continue in a fresh alpha session

1. **Verify clean state:**
   - `cd ~/projects/hapax-council && git pull --ff-only origin main`
   - `git status` — expect clean
   - `git worktree list` — expect alpha + beta (+ possibly `hapax-council--audit-followup` if beta's still mid-work; don't touch)

2. **Read this handoff + pass-1 handoff + beta's current handoff:**
   - `docs/superpowers/handoff/2026-04-12-alpha-stream-handoff-2.md` (this file)
   - `docs/superpowers/handoff/2026-04-12-alpha-stream-handoff.md` (pass 1)
   - `docs/superpowers/handoff/2026-04-12-beta-stream-handoff.md` (beta pass 1)
   - `~/.cache/hapax/relay/beta.yaml` (beta's current state)
   - `~/.cache/hapax/relay/convergence.log` (structural similarities logged across streams)

3. **Read the auto-memory entry on rebuild-logos detach:**
   - `~/.claude/projects/-home-hapax-projects/memory/feedback_rebuild_logos_worktree_detach.md`
   - This explains why files may appear to revert mid-edit and the recovery pattern. Don't panic, don't re-edit, just `git checkout <branch>` + `git cherry-pick <detached-sha>`.

4. **Verify the compositor is still behaving:**
   - `systemctl --user is-active studio-compositor` — expect `active`
   - `ls -la /dev/shm/hapax-compositor/yt-frame-*.jpg` — expect 3 files, fresh mtimes, **non-zero size**
   - `journalctl --user -u studio-compositor -n 50 | grep -E 'REACT|reloaded|StreamOverlay'` — expect recent `REACT [react]:` logs + `StreamOverlay background thread started` on restart
   - `cat /dev/shm/hapax-compositor/fx-current.txt` — expect a preset name like `chain` / `halftone_preset`

5. **Pick the next item.** Suggested order:

   a. **If operator is available for hardware work:** A3 (BRIO USB investigation) — the cheap physical tests unlock real diagnostic data. Don't ship code until the hardware hypothesis narrows.

   b. **If operator is not available for hardware:** FU-6 (rebuild-logos worktree isolation). Small, unblocks every future alpha session from the cherry-pick recovery dance. ~15 lines of shell. Zero risk.

   c. **If neither feels right:** A7 (native GStreamer RTMP). Large feature, prerequisite for A8 + CC1. Worth exploring the existing pipeline shape before committing.

   d. **Not recommended without operator steering:** A6 (dynamic camera resolution — spec only, needs design), A8 / A9 (depend on A7), FU-4 (retrospective; value unclear without a specific trigger).

6. **Watch for beta merges.** Beta's PR #699 (retirement handoff) is likely to merge early next session. If beta ships reverie changes from `~/projects/hapax-council--audit-followup/`, rebase alpha onto `main` so the dev server picks up the changes. (The workspace CLAUDE.md rule still holds: "Rebase alpha after beta merges.")

---

## Notes for the archaeology

- Pass 1 predicted layer 4 (max_tokens / finish_reason=length) as "FU-1" and was right about the location, wrong about which branch of `_call_activity_llm`/`_parse_llm_response` was dropping the tick. The probe (#690) collapsed the question in one production tick — a reminder that **cheap observability before cheap fixes** is the right default when the failure mode is ambiguous.

- Layer 5 (FU-5 / 0-byte frames) emerged from the A12 deploy, not from FU-1 diagnosis. Shipping A12 broke the happy path *one level deeper* than expected — the same anti-pattern (existence-only file check) that bit FU-1 also bit `_gather_images`. **Every `.exists()` in a compositor data pipeline is a latent 0-byte bug.** Worth a retrospective grep for other sites.

- A4 → A5 is a "visible state unlocks interactive state" arc. A4 renders the current preset on the stream; A5 accepts chat requests for *other* presets. Neither would work without the other (without A4 viewers wouldn't know what keywords are valid; without A5 the overlay would be purely informational). Worth remembering when planning future viewer-facing features: **expose state before you accept input on it**.

- The `rebuild-logos.sh` / worktree detach issue is the kind of foundational tooling problem that's very easy to work around (cherry-pick) and very hard to notice you should fix. It struck me 4+ times this session before I added the diagnostic note. Future sessions should recognise the symptom from auto-memory and either fix the tool (FU-6) or pace edits outside the 5-min build window. Cost of not fixing: ~5 min recovery per incident × however many incidents. Cost of fixing: one small shell PR.
