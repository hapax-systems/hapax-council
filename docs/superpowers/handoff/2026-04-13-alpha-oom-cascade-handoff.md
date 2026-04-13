# Session Handoff — 2026-04-13 alpha OOM cascade containment

**Previous handoff:** `docs/superpowers/handoff/2026-04-13-alpha-camera-247-epic-handoff.md` (camera 24/7 resilience epic retirement).
**Session role:** alpha.
**Branch at end:** alpha on `main` at `639e7c721`, clean. PR #731 merged.

## The problem

At 03:06:37 CDT on 2026-04-13, the workstation went through a 19-second OOM kill cascade that took down Hyprland, minio, clickhouse, litellm, qdrant, grafana, redis, next-server, and four other services. The system booted at 02:38; the cascade happened ~30 minutes later while the operator was idle.

**Observable symptoms (from the affected operator session):**

- Hyprland auto-restarted in `--safe-mode` (no config, no plugins). The desktop looked "weird."
- `xdg-desktop-portal-hyprland` segfaulted on Wayland reconnect.
- Load average climbed to 55 / 57 / 47 on a ~32-thread machine; memory PSI `avg300 = 15.3%`.
- Three fresh ffmpeg YouTube streamers were consuming ~50% CPU each; studio-compositor was at 668% CPU in a tight post-restart warmup loop.

## Root cause

**Unambiguously: a 43 GB anonymous memory leak in the hapax-logos WebKit content process.**

Confirmed from the kernel OOM dump at 03:06:37 (current boot journal, now in `~/.cache/hapax/…` — grep `WebKitWebProces pid=9870`): a single `WebKitWebProcess` (PID 9870) held **43,986 MB of swap entries** with only 282 MB of anon RSS. All other processes combined held <12 GB swap. WebKit's 44 GB was 95% of the 45 GB `zspages` in Node 0 Normal zone at that moment.

The leak source: `hapax-logos/src/pages/FlowPage.tsx`, the flow-event SSE subscription effect. Its deps array was `[edges, flowState, p]` — and the poll effect above it refreshed `flowState` every 3 seconds, which cascaded into new `edges` and palette identities every 3 seconds, which retriggered the subscription effect every 3 seconds. Each retrigger:

1. Called `invoke("subscribe_flow_events")`, which spawned a fresh `tokio::spawn` task in `hapax-logos/src-tauri/src/commands/streaming.rs` holding a new HTTP SSE connection to `/api/events/stream`. No idempotency guard.
2. Scheduled `listen<string>("flow-event", …)` inside a `.then()` chain that resolved **after** the effect's cleanup captured `unlisten = null`, orphaning the listener with closures over the full `edges` array and `flowState` tree.

After ~30 minutes: roughly 600 orphan Rust SSE tasks and 600 orphan JS listeners. N² event delivery (every Rust task broadcast to every JS listener) plus growing retained closures generated anonymous allocations faster than the kernel could compact them. Pages got pushed to zram, zram grew to consume almost all of physical RAM, the kernel ran out of uncompressed pages to satisfy page-ins, and the global OOM killer fired in a cascade across every unprotected cgroup.

## Accelerant: zram sized at 100 % of RAM

`zram0` was sized at 62.7 GiB — the full physical RAM — via the distro default `zram-size = ram` in `/usr/lib/systemd/zram-generator.conf`. When zram is that large, a single leaking process can fill it, at which point the kernel has almost no uncompressed RAM left and any new allocation triggers OOM-killing. This took a WebKit bug from "one service crashes" to "ten services crash in 19 seconds."

## What shipped

| PR | Commit | Title | Scope |
|----|--------|-------|-------|
| [#731](https://github.com/ryanklee/hapax-council/pull/731) | `639e7c721` | `fix(logos): idempotent flow-event subscription + WebKit cleanup` | 6 files, +136/-20 |

### Fix A — `hapax-logos` (the actual leak)

- **`src-tauri/src/commands/streaming.rs`** — `subscribe_flow_events` is now gated on an `AtomicBool` in `StreamRegistry`. Only the first call spawns the SSE task; subsequent calls no-op. Idempotent under React `StrictMode` double-invoke and any future effect re-runs.
- **`src/pages/FlowPage.tsx`** — the flow-event subscription effect now has an empty deps array and runs exactly once for the component lifetime. The event handler reads `edges` / `flowState` / `palette` via `useRef` so it always sees current state without retriggering the effect. `listen()` is awaited inside an async IIFE with a `disposed` flag so late-resolving listeners still clean up.
- **`src/lib/commandBridge.ts`** — new `track()` helper called from `.then()`. If the bridge was disposed before a `listen()` promise resolved, `track` calls `unlisten` immediately instead of pushing into a discarded array. Same async-listen race pattern as FlowPage, much lower severity because `connectCommandBridge` is only called once per provider mount.
- **`src/hooks/useSSE.ts`** — retained `lines` capped at `MAX_LINES = 2000` via a ring buffer (`appendBounded`). The previous unbounded `setLines((prev) => [...prev, next])` was a secondary pin on the WebKit anonymous heap for any session using `AgentRunProvider`.
- **`src/components/hapax/AmbientShader.tsx`** — unmount cleanup now deletes the WebGL program, vertex + fragment shaders, vertex buffer, and force-calls `WEBGL_lose_context.loseContext()` so remounts do not leak GPU contexts. Bounded (WebKit caps at ~16 contexts) but worth fixing.

Explicitly not touched: `src/hooks/useHapaxIntrospection.ts`. An earlier audit flagged it as a candidate, but re-reading showed it already uses the correct disposed-flag race-handling pattern via `let disposed = false;` + `if (disposed) { unlisten(); }`. Not a leak.

### Fix B — `hapax-daimonion.service` cgroup tightening

`systemd/units/hapax-daimonion.service` (in PR #731):

- `MemoryMax 8G -> 12G` + new `MemoryHigh=10G` soft ceiling.
- `OTEL_BSP_MAX_QUEUE_SIZE=256`, `MAX_EXPORT_BATCH_SIZE=64`, `EXPORT_TIMEOUT=2000`, `SCHEDULE_DELAY=1000`.

The daimonion working set (STT distil-large-v3 + Kokoro + seven lazy-loaded vision models under `backends/vision.py` + libtorch + cudnn) plateaus at ~5 GB after warmup but spikes to ~7.8 GB during the first-camera-pass vision lazy-load ramp — I confirmed this by observing `MemoryPeak = 7.86 GB` on the fresh daimonion PID immediately after I restarted it. The old 8 GB hard wall had no margin; a Langfuse-outage span burst or a pressure tick could knock us into cgroup OOM. `MemoryHigh` gives the kernel a soft ceiling to reclaim against before `MemoryMax` turns into a kill.

OTel's defaults (2048 queue, 30 s export timeout, 5 s schedule delay) meant every Langfuse outage backed up spans in the Python heap and hung `httpx` for 30 s on retries. Langfuse was unresponsive right before the cascade — ClickHouse was hitting its 8-query limit, see `2026-04-13T08:06:26` langfuse-worker logs. Capping the BSP queue and timeout contains both problems.

A drop-in override at `~/.config/systemd/user/hapax-daimonion.service.d/override.conf` restates the same values. It exists as belt-and-suspenders: the symlinked main unit file could get reverted by the rebuild-logos timer detaching the alpha worktree, and the running systemd cache could get reloaded into the reverted state. The drop-in survives all of that and harmlessly restates what PR #731 already put in the main unit file.

### Fix C — zram sizing

`/etc/systemd/zram-generator.conf` (root-owned, not in any repo):

```ini
[zram0]
compression-algorithm = zstd
zram-size = min(ram / 2, 32768)
swap-priority = 100
fs-type = swap
```

Caps zram at the lesser of half-RAM or 32 GiB. With this in place, the kernel always has at least half of physical RAM for uncompressed working set, no matter how much a leaky process allocates. A single runaway process can no longer saturate the whole system.

`systemd-analyze cat-config systemd/zram-generator.conf` confirms the override is in the effective config chain. Immediate apply was **deferred** — `swapoff /dev/zram0` returned `ENOMEM` on the live system (it needed to drain 7.8 GiB of compressed swap back into contiguous RAM, and the post-cascade machine was too fragmented). The new size applies at next reboot automatically when zram-generator rebuilds the device from the config.

## What's verified, what isn't

**Verified on the live system:**

- TypeScript + cargo both compile clean under the fix (`pnpm tsc --noEmit` exit 0, `cargo check` exit 0 — run on the feature worktree before the PR was opened).
- All nine PR #731 CI checks passed (`freeze-check`, `lint`, `secrets-scan`, `security`, `test`, `typecheck`, `vscode-build`, `web-build`, plus the skipped dependabot auto-merge).
- Daimonion running at `MemoryMax=12G`, `MemoryHigh=10G`, OTel envs set (`systemctl --user show hapax-daimonion`).
- `/etc/systemd/zram-generator.conf` in place and read by `systemd-analyze cat-config`.
- PR #731 merged and primary worktree synced to `639e7c721`.

**Not yet verified:**

- Production binary at `~/.local/bin/hapax-logos` updated. `hapax-rebuild-logos.timer` picked up the new `origin/main` at 11:47 CDT and was still mid-cargo-build at handoff write time. Once cargo finishes, `just install` drops the new binary and `rebuild-logos.sh` auto-restarts `hapax-logos.service` because the binary mtime exceeds the service's `ActiveEnterTimestamp`.
- The 43 GB anonymous-page plateau in WebKit actually held flat over 30 minutes. Can be checked post-restart with `awk '/VmRSS|VmSwap/{print}' /proc/$(pgrep WebKitWebProcess)/status` sampled every few minutes.

## Reboot checklist

After the rebuild-logos timer installs the new binary and restarts `hapax-logos.service`, all three fixes are persistent across reboot:

1. **Fix A** — in `origin/main` at `639e7c721`. Next boot will launch the rebuilt `~/.local/bin/hapax-logos`, which has the idempotent SSE subscription.
2. **Fix B** — in `systemd/units/hapax-daimonion.service` (symlinked from `~/.config/systemd/user/`) AND in the drop-in at `~/.config/systemd/user/hapax-daimonion.service.d/override.conf`. Survives any rebuild-logos detach.
3. **Fix C** — applies at boot via `systemd-zram-setup@zram0.service` reading `/etc/systemd/zram-generator.conf`.

The operator can reboot whenever convenient. No in-progress work at handoff time.

## Open follow-ups (not addressed in this session)

- **Langfuse + ClickHouse bottleneck** under load. ClickHouse's 8-concurrent-query limit is the proximate cause of the langfuse-worker backlog that was visible right before the cascade. This is pre-existing and unrelated to the WebKit leak — it just showed up in the same journal window. Worth raising the limit or adding queue-depth alerting.
- **Rebuild-logos timer cadence vs cargo build time.** The timer fires every 5 minutes, but a cold Tauri release rebuild takes 2–5 minutes. Under normal conditions the incremental cache stays warm. Worth watching whether the timer ever overlaps in practice (the `flock -n` guard is already in place from FU-6 / PR #703).
- **Dropping the drop-in override once the unit file is stable.** The drop-in at `~/.config/systemd/user/hapax-daimonion.service.d/override.conf` can be deleted once it's clear no rebuild cycle is going to revert the symlinked unit file. Low priority; it just restates values.
- **Alpha worktree as deploy target.** The underlying tension flagged in the 2026-04-12 FU-6 handoff ("alpha's worktree doubles as dev branch and production deploy target") is still there. This session rediscovered part of that when `git restore` on the primary worktree silently reverted the symlinked daimonion unit file mid-session. The drop-in workaround is the small fix; the real fix is to stop using alpha as a deploy source.
