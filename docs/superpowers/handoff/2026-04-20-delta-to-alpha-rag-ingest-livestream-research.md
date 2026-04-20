# delta → alpha: rag-ingest livestream-compatible redesign research

**created:** 2026-04-20T15:05Z (mid-VRAM-emergency)
**revised:** 2026-04-20T15:50Z (handoff doc backfilled by alpha after audit `d33be1a6e` flagged the missing reference in `8816040eb`)

**Status:** RESEARCH-DISPATCH — alpha to scope, not implement
**Priority:** HIGH (gate-3-livestream-affecting, recurring failure mode)

## Context

`rag-ingest.service` (Python module `agents.ingest`, runs in `.venv-ingest/` to isolate docling + pydantic-ai dep tree from the main `.venv`) ran for 2+ days at the time of the operator's 2026-04-20 ~15:00Z VRAM emergency. The service holds 2-4 GB on the 3090 intermittently for docling document conversion + embedding generation, contending with TabbyAPI (Command-R 32B EXL3, ~17 GB on 3090) for both VRAM and SM. Over 2-day uptime the contention compounded enough to hang the desktop at TTY-fallback.

Delta's emergency response (commit `8816040eb`):
- Stopped `rag-ingest.service`.
- Disabled + deleted `rag-ingest.timer` from `~/.config/systemd/user/` so it would not auto-restart on reboot (NOTE: per audit, timer is still `enabled` in systemd state — repo-vs-systemd state divergence; alpha investigation item).
- Wrote a stub drop-in proposal for `Environment=CUDA_VISIBLE_DEVICES=""` to force CPU-only inference + embedding (proposal not applied — operator-decision pending).
- Asked operator: *"Want me to apply the drop-in now?"* — context died before answer.

## What needs research (alpha, not implementation)

The drop-in is a band-aid (CPU embedding will work but slow down ingest 5-20×). The right answer is a livestream-compatible redesign of the ingest pipeline that:

1. **Yields VRAM during operator-active livestream windows** — read `/dev/shm/hapax-compositor/director-active.flag` (or equivalent), pause embedding when set, resume when clear. Cite `agents/studio_compositor/state.py` for analogous flag-watcher patterns.

2. **Pre-allocates a hard VRAM budget** that cannot exceed N MB on cuda:0. ExllamaV2 / sentence-transformers both support explicit device + memory caps. Find the right knobs.

3. **Schedules heavy docling batches off-stream** — operator's stream windows are visible via `~/.cache/hapax/working-mode` (research/rnd) + sprint timer. Defer batch ingest to research-mode + non-stream hours.

4. **Documents the dependency surface** — why `.venv-ingest` exists at all (docling pulls heavy + pydantic-ai version pin conflicts with main .venv per `rag-ingest.service:14` comment). Is the isolation still load-bearing in 2026-04-20 or can it merge?

## Scope NOT in this dispatch

- The actual systemctl-vs-repo enabled-state divergence (separate audit item, alpha-zone)
- The opencv-no-CUDA chronic-fallback that was discovered earlier (separate from rag-ingest)
- The TabbyAPI tensor-parallel split rebalancing (already shipped 2026-04-20, ref `tabbyAPI/config.yml` `gpu_split: [16, 10]`)

## Acceptance for the alpha research

A research doc at `docs/research/2026-04-20-rag-ingest-livestream-coexistence.md` covering:
- Inventory of what `agents.ingest` actually does (read the code)
- VRAM peak measurement during a typical batch
- 3 design options ranked by livestream-safety + implementation effort
- Recommended ship plan (likely Phase 1 = VRAM cap + flag-yielding, Phase 2 = scheduling)
- Decision on whether `.venv-ingest` isolation is still load-bearing

## Sources

- `8816040eb` — VRAM emergency commit (rag-ingest stop + timer delete)
- `d33be1a6e` — 6h audit doc that flagged this handoff's absence
- `systemd/units/rag-ingest.service` — the unit and its 2-day-old comments
- `~/.cache/hapax/relay/delta-to-alpha-rag-ingest-livestream-optimization-20260420.md` — original delta dispatch (if it exists; otherwise this doc IS the dispatch)
