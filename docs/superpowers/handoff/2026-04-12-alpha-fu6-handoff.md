# Session Handoff — 2026-04-12 alpha FU-6 / FU-6b

**Previous handoff:** `docs/superpowers/handoff/2026-04-12-alpha-stream-handoff-2.md` (pass 2 retirement).
**Scope of this session:** picked up cold as fresh alpha, closed both facets of the "alpha worktree cannot simultaneously be a dev branch AND a deploy target" issue flagged at the end of pass 2 and reinforced by delta's in-session inflection.
**Session role:** alpha (renamed from beta at session start via `/rename alpha`).
**Branch at end:** alpha on `main`, clean. No open alpha PRs.

## What shipped

| PR | Item | Title | Result |
|----|------|-------|--------|
| [#703](https://github.com/ryanklee/hapax-council/pull/703) | FU-6 | `build(rebuild-logos)`: build in isolated scratch worktree | `scripts/rebuild-logos.sh` rewritten to build in a persistent scratch worktree at `$HOME/.cache/hapax/rebuild/worktree`. Primary worktrees are never detached mid-session. Smoke-tested both first-run (worktree create) and subsequent-run (reset --hard) paths end-to-end. Added `flock -n` on `$STATE_DIR/lock` so manual invocations cannot race a timer firing on the shared scratch tree. Merged as `059ddfe69`. |
| [#704](https://github.com/ryanklee/hapax-council/pull/704) | FU-6b | `fix(rebuild-service)`: don't silently SHA-update when off main | `scripts/rebuild-service.sh` used to silently write `CURRENT_SHA` to `SHA_FILE` whenever the target repo was on a feature branch, masking deploy failures forever. Fix: do NOT update `SHA_FILE` on skip, AND send a throttled `ntfy` (one per distinct `origin/main` SHA, via a new `$STATE_DIR/last-notified-${KEY}-sha` tracker). Smoke-tested against the voice SHA key with alpha on a feature branch. Merged as `54035f7a2`. |

## The scope split

The problem flagged at the end of pass 2 was "rebuild-logos.sh detaches alpha's worktree for the build window, reverting uncommitted edits on disk." Fixing that alone is what FU-6 was originally scoped to.

Delta's in-session inflection (2026-04-12T20:55) surfaced the larger shape: **alpha's worktree is being used as a production deploy target**, and the rebuild-* scripts handle the resulting conflict between "dev branch" and "deploy source" poorly in two different ways:

- **Compiled-binary path (logos, imagination).** Old behaviour: detach alpha → build from detached HEAD → restore branch. Symptom: disk-level revert of uncommitted edits during the build window. Fix shape: route the build through an isolated scratch worktree that the primary worktrees never touch. **Closed by FU-6 / #703.**
- **Interpreter-loaded Python path (daimonion, logos-api, dmn, reverie, officium, mcp).** Old behaviour: refuse to pull onto a feature branch, silently update the SHA tracker anyway so the same advancement does not re-trigger on subsequent cycles. Symptom: services keep running old code indefinitely after origin/main advances; operator has no visible signal unless they diff the running daemon's files against main by hand. Fix shape: do NOT advance the SHA tracker on skip, and notify loudly once per distinct advancement. **Closed by FU-6b / #704.**

Neither fix removes the root architectural tension. `scripts/rebuild-service.sh` still refuses to auto-deploy a feature branch (the loud notification is the only escalation), and the systemd units still point `ExecStart` at the alpha worktree path. The real close-out is to stop using alpha as a deploy target — see "Architectural follow-up" below.

## Decisions made this session

1. **Scratch worktree under `$STATE_DIR`, not `~/projects/`.** The three-worktree-slot discipline applies to the project root. A scratch worktree at `$HOME/.cache/hapax/rebuild/worktree` is outside that namespace and does not conflict with alpha / beta / spontaneous-slot.
2. **`just install` already isolates `CARGO_TARGET_DIR`.** The justfile sets `CARGO_TARGET_DIR=$HOME/.cache/hapax/build-target` unconditionally, so cargo builds stay incremental across runs regardless of source path. `node_modules` persists inside the scratch worktree so `pnpm install --frozen-lockfile` stays fast. No cache regression.
3. **Added `flock -n` on `$STATE_DIR/lock`.** systemd `Type=oneshot` already prevents the timer from overlapping itself, but manual invocations (e.g. smoke tests) can still race. Without the flock two concurrent runs would step on the shared scratch worktree (`git reset --hard` + `vite build dist/` writes). Observed this race live during the second smoke test — two `tsc -b` + `vite build` subprocesses in the same scratch tree. Flock closes it.
4. **Rejected extending PR #703 to cover rebuild-service.sh.** Different fix shape (not a scratch worktree — systemd units read Python directly from alpha's worktree). Clean PR separation is cheaper than coupling, especially since #703 was already in CI.
5. **Rejected auto-ff of feature branches in rebuild-service.sh.** Auto-advancing a branch that is a clean ancestor of `origin/main` would work for the common case but still risks clobbering in-progress work. A future session could add an explicit "HEAD is ancestor of origin/main" gate with operator opt-in, but the conservative default (notify, don't act) is the right behaviour for a first ship.

## Live debugging this session

### 1. The ff-merge mystery

Observed mid-session: alpha's `fu-6-rebuild-logos-worktree-isolation` branch silently fast-forwarded from `1f034fe82` to `dd6c8dcb0` between my branch creation and my commit. The reflog showed the merge but I had not issued it myself.

Root cause: delta (spontaneous `hapax-council--docs-f6` worktree, later merged as PR #702) force-merged my branch to `origin/main` to work around the `rebuild-service.sh` silent-skip bug — the running reverie daemon would not pick up `#702` until alpha's branch advanced past it, because `rebuild-service.sh` refuses to pull onto a feature branch. Delta left an inflection in `alpha.yaml` explaining this and scoping FU-6b.

The mystery is exactly the thing FU-6b fixes. The old behaviour forces the operator (or a peer session) to manually catch up branches; the new behaviour surfaces the stale state via `ntfy` so the operator can act deliberately.

### 2. Three-way rebuild-logos race during smoke test

While testing FU-6 I saw three concurrent `bash scripts/rebuild-logos.sh` processes: my manual test (20:35), a systemd-timer firing (20:29), and a second systemd-timer firing (20:39). Two of them simultaneously ran `tsc -b` + `vite build` in the shared scratch worktree. The race was benign because all three targeted the same `$CURRENT_SHA` so the outputs were identical, and cargo serialized the later stages via its file lock. But it was clearly not a design I wanted to ship — added the `flock` before committing.

Stopping the systemd timer during smoke testing (`systemctl --user stop hapax-rebuild-logos.timer`) is the cheapest way to avoid this. Re-start it after.

### 3. `git clean -fdx -e node_modules` considered and rejected

Early drafts of the script explicitly cleaned untracked files after reset, preserving only `node_modules`. I dropped this: `git reset --hard` only touches tracked files and leaves `node_modules` / `dist` alone naturally. `pnpm build` overwrites `dist` on every run, so stale `dist` is irrelevant. Less moving parts, less risk.

## What the next alpha should probably do

No item from the pending queue is an obvious next step for a fresh session. Operator steering would help.

- **FU-3** — Parallel yt-dlp invocation on cold start. Previous alpha explicitly characterised this as "harmless but wasteful." Marginal value. Skip unless you find real thrashing.
- **FU-4** — Sweep `hapax_span` callers for previously-masked silent failures. Retrospective. Value only if the sweep finds something real; you may spend an hour and find nothing.
- **A3** — BRIO USB investigation. Hardware — operator needs physical access. A code-side watcher daemon that tails `journalctl -k` for `error -71` on BRIO serials is still an option if operator prioritises observability.
- **A7** — Native GStreamer RTMP (eliminate OBS). Large feature, prerequisite for A8 / CC1. Worth reading the existing compositor pipeline shape before committing — this needs a brainstorming pass, not a "just start coding" pass.

If you want a clean one-shot item: **FU-3**. It is scoped and small even if the value is low.

If you want a real project: **A7 brainstorming**. Produce a design doc (`docs/superpowers/specs/<date>-a7-native-rtmp.md`), not an implementation. Then stop and wait for operator review.

## Architectural follow-up (not urgent)

Both rebuild-* fixes are palliative. The real close is "stop using alpha's worktree as a production deploy target":

1. Create a permanent deploy worktree outside the three-slot namespace (e.g. `$HOME/.local/state/hapax-council-main` or similar)
2. Point all systemd units' `ExecStart=` at that path
3. Update `rebuild-service.sh` to operate exclusively on the deploy worktree (no more `--repo` argument)
4. Document the new layout in root `CLAUDE.md` and the systemd/README

This moves alpha from "dev+deploy target" to "dev only" and lets the scripts just pull-and-restart without the "am I allowed to touch this tree?" question. It is a day-sized project, not a one-commit fix. Out of scope for this session.

## Current system state (as of 2026-04-12 ~21:12 CDT)

- **Git:** `main` at `54035f7a2` (FU-6b merged). Alpha worktree clean, no open alpha PRs. `hapax-rebuild-logos.timer` active and will exercise the new `rebuild-logos.sh` against current `origin/main` on its next firing (~5-min cadence).
- **Worktrees:** alpha (project root), beta (project root with `--beta` suffix, currently on `fix/impingement-cursor-persistence`). No spontaneous worktrees.
- **Compositor:** running, director loop producing reactions at ~8s cadence, 3 slots populated (observed during session).
- **Services:** `studio-compositor`, `youtube-player`, `logos-api`, `hapax-daimonion`, `hapax-imagination-loop` all active.
- **Scratch build worktree:** present at `$HOME/.cache/hapax/rebuild/worktree`, detached at `1f034fe82` (from smoke test). Next timer firing will `reset --hard` to `54035f7a2` before rebuilding.

## Notes for the archaeology

- **The silent SHA update in rebuild-service.sh existed since the script was introduced.** No one noticed until delta happened to need a Python service redeploy during the exact window when alpha was off main. The audit lesson is the usual one: *any line that writes a tracker file on a deliberate skip is a latent silent failure*.
- **Flock belongs in every shared-resource script that can be invoked manually.** systemd's `Type=oneshot` anti-overlap only covers the timer path, not manual runs. I should have added the flock from the start; the smoke-test race was avoidable.
- **Delta's inflection was high-quality relay.** Delta noticed my WIP, diagnosed the related bug, and scoped FU-6b for me with a precise pointer to the offending line. That's what the relay protocol is for. The next session should read `alpha.yaml` inflections from peers before picking up new work.
