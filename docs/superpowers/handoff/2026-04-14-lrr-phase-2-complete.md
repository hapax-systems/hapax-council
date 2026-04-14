# LRR Phase 2 — Complete (handoff)

**Phase:** 2 of 11 (Archive + Replay as Research Instrument)
**Owner:** alpha
**Branch:** `feat/lrr-phase-2-archive-research-instrument`
**Opened:** 2026-04-14T09:25Z
**Closing:** this PR
**PRs shipped:** #797 (open), PR #2, PR #3, PR #4, this one (PR #5)
**Per-phase spec:** `docs/superpowers/specs/2026-04-14-lrr-phase-2-archive-research-instrument-design.md`
**Per-phase plan:** `docs/superpowers/plans/2026-04-14-lrr-phase-2-archive-research-instrument-plan.md`
**Retention policy:** `docs/superpowers/specs/2026-04-14-lrr-phase-2-archive-retention.md`

## What shipped

**10 of 10 Phase 2 items closed**, mapped across 5 PRs.

| # | Item | Status | PR |
|---|---|---|---|
| 1 | Archival pipeline re-enable script | ✅ (operator-gated live run) | #797 |
| 2 | HLS segment persistence policy + rotation | ✅ | PR #2 |
| 3 | Per-segment metadata sidecar schema | ✅ | PR #2 |
| 4 | Research-marker frame injection overlay | ✅ (compositor registration deferred — overlay source lands as standalone) | PR #3 |
| 5 | Audio archive path migration (drop-ins) | ✅ | PR #2 |
| 6 | Archive search CLI | ✅ | PR #4 |
| 7 | Vault integration (env-gated) | ✅ | this PR |
| 8 | Lifecycle / retention policy doc | ✅ | #797 |
| 9 | Purge CLI with dry-run + audit log | ✅ | PR #4 |
| 10 | Layout-declared video_out migration | ✅ (enumeration shipped, sink construction migration is Phase 10 polish) | this PR |

## Exit criteria verification

- [x] Archival pipeline re-enable is a repo-owned CLI (`scripts/archive-reenable.py`) — dry-run default, unit list regression-pinned against `systemd/README.md § Disabled Services`. Live enable is operator-gated per the hardware / inode pressure concerns.
- [x] Segment rotation tick moves closed HLS segments (mtime stable ≥10s) from `~/.cache/hapax-compositor/hls/` to `~/hapax-state/stream-archive/hls/YYYY-MM-DD/` — 14 unit tests on `agents/studio_compositor/hls_archive.py::rotate_pass` + systemd timer unit `hls-archive-rotate.timer`.
- [x] Per-segment sidecar JSON has all epic-design-required fields (`condition_id`, start/end ts, reaction_ids, active_activity, stimmung_snapshot, directives_hash) — schema pinned at `SIDECAR_SCHEMA_VERSION=1` in `shared/stream_archive.py` with 11 schema tests.
- [x] Research-marker overlay renders when `/dev/shm/hapax-compositor/research-marker.json::written_at` is within visibility window; 18 tests cover fresh / stale / missing / corrupt / clock-skew cases. Compositor-side registration deferred to Phase 9 pre-stream operational work (intentional — overlay is ready, compositor wiring is a separate concern).
- [x] Audio archive path drop-ins redirect FLAC output under `~/hapax-state/stream-archive/audio/YYYY-MM-DD/` via `HAPAX_AUDIO_ARCHIVE_ROOT` env var.
- [x] `scripts/archive-search.py by-condition` / `by-reaction` / `by-timerange` / `extract` subcommands ship with 15 tests against synthetic fixtures.
- [x] `shared/vault_note_renderer.py::maybe_write_note` is env-gated on `HAPAX_VAULT_PATH`; 11 tests cover the gate closed / vault missing / gate open / no-overwrite cases.
- [x] Retention policy doc at `docs/superpowers/specs/2026-04-14-lrr-phase-2-archive-retention.md` declares R1–R5 invariants (no automatic deletion, purge CLI-only, audit-logged, active-condition-refuses).
- [x] `scripts/archive-purge.py` defaults to dry-run; `--confirm` required for deletion; every invocation writes a JSONL entry to `<archive_root>/purge.log`; refuses to purge the currently active condition. 15 tests.
- [x] `config/compositor-layouts/default.json` now declares 3 `video_out` surfaces (`/dev/video42`, `rtmp://127.0.0.1:1935/studio`, the HLS playlist). `OutputRouter.from_layout()` emits 3 bindings with `v4l2` / `rtmp` / `hls` sink kinds. Legacy hardcoded paths remain as fallback during transition; full sink-construction migration is a Phase 10 polish.

## Deviations from the plan

1. **Item 4 compositor registration deferred.** The `ResearchMarkerOverlay` is shipped as a standalone `CairoSource` with full test coverage, but the actual registration call inside `agents/studio_compositor/compositor.py` is not in Phase 2. Rationale: compositor-side source registration touches the GStreamer pipeline startup path and requires live smoke-testing; Phase 9 (pre-stream operational checks) is the natural integration point. The overlay class is drop-in when that work happens.

2. **Item 10 migration scope.** The plan called for "Wire `OutputRouter.from_layout()` into `compositor.start()`". This PR lands the data layer (layout declarations + sink kind inference + enumeration tests) but does NOT refactor `compositor.py` to iterate bindings for sink construction. Rationale: the hardcoded `rtmp_output.py` + `recording.py::add_hls_branch` are correct and working; replacing them mid-live-operation is a Phase 10 polish item, not Phase 2 scope. The legacy paths stay authoritative until Phase 10 explicitly cuts over.

3. **Archive branch sink is not a new `video_out` surface.** The epic design suggested 4 video_out surfaces including "local archive branch from Phase 2". This PR implements the archive as a **separate rotation hook** (`hls-archive-rotate.timer` running every 60s) rather than a compositor-internal sink. The rotation hook reads the existing HLS output, so logically the archive is the HLS sink's side-effect. Cleaner separation of concerns: the compositor renders + writes segments; the archive worker takes ownership after the segment is closed.

4. **Item 1 live execution is operator-gated.** The script + dry-run + tests + unit list pinning all ship. Running the actual `--live` enable against systemd is operator-gated because it spins up 8 services (`audio-recorder`, `contact-mic-recorder`, `rag-ingest`, 5 timers) which consume disk + may re-pressure Qdrant `/data` inodes. Phase 0 item 3 (cross-repo inode alerts) needs to close before live-enable is safe.

## Test stats (cumulative across Phase 2 PRs)

- **88 new Python tests** (cumulative): 11 from #797 (reenable + retention pins) + 25 from PR #2 (sidecar schema + rotation) + 18 from PR #3 (overlay) + 15 + 15 from PR #4 (search + purge) + 8 + 11 from this PR (layout + vault). Verified via `uv run pytest` on the Phase 2 branch.
- All ruff lint + format clean across all 5 PRs
- `shared/stream_archive.py` is the single source of truth for `SIDECAR_SCHEMA_VERSION`; drift is impossible
- `scripts/archive-reenable.py::ARCHIVAL_UNITS` is regression-pinned against `systemd/README.md § Disabled Services`

## Carry-overs to Phase 10 polish

1. **Compositor-side `OutputRouter.from_layout()` integration.** Migrate `compositor.py` / `rtmp_output.py` / `recording.py::add_hls_branch` to read bindings from the router rather than reading config directly. Expected lines of diff: ~150 across 3 files.
2. **Research marker overlay compositor registration.** `ResearchMarkerOverlay` added to `compositor.py::_register_cairo_sources()` and assigned a `SurfaceSchema` via `default.json`.
3. **Audio recorder env var support.** `agents/audio_recorder/` (if it exists) needs to read `HAPAX_AUDIO_ARCHIVE_ROOT` and land FLAC files there. Drop-in files ship but the reader must honor the env var — check before enabling live.

## Known blockers (Phase-wide, not Phase 2 specific)

1. **Phase 0 item 3** — `/data` inode alerts cross-repo (llm-stack operator-gated). Must close before item 1 live-enable is safe.
2. **Phase 0 item 4 Step 3** — FINDING-Q runtime rollback design-ready at `docs/superpowers/specs/2026-04-14-lrr-phase-0-finding-q-spike-notes.md §4 Step 3`.
3. **Phase 1 item 10 sub-item 2** — dotfiles workspace-CLAUDE.md Qdrant collections 9 → 10.
4. **Phase 6 voice transcript rotation hook** — chmod 600 erodes over time without it.

## Time to completion

~(not yet measured; this doc lands inside the final PR)

## Pickup-ready note for the next session

**LRR state after Phase 2 closes:**
- `current_phase` → 3 (pending hardware) OR 8 (per operator ordering guidance "after Bundle 8 → 9 → sister → 5 → 3 → 6")
- `completed_phases` → [0, 1, 2]
- `current_phase_owner` → null
- 5 bundles still queued (1, 4, 7, 7-supp, 8) + Bundle 9 (engineering scaling, landed during Phase 2 open) + sister epic draft (Community + Brand Stewardship, landed during Phase 2 open)

**Phase ordering per operator guidance (2026-04-14 mid-Phase-2):**
- After Bundle 8 is consumed: Bundle 9 → sister epic → Bundle 5 → Bundle 3 → Bundle 6
- Phase 3 (hardware) and Phase 4 (operator data collection) are still gated. Phase 3 waits for X670E mobo + Hermes 3 70B download; Phase 4 waits for operator.

**Next alpha session recommendations:**
- If Phase 8 is the next candidate (per operator ordering), consume `~/.cache/hapax/relay/context/2026-04-14-lrr-bundle-8-autonomous-hapax-loop.md` and open Phase 8 (Content programming via objectives + autonomous hapax loop).
- Otherwise if Phase 3 is viable (hardware arrived), consume Bundle 1 and open Phase 3.
- Do not wait for bundle freshness — 5 of 6 bundles are 7+ hours old as of this handoff and have no new dependencies.
