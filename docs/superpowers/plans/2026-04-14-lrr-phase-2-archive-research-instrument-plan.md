# LRR Phase 2 — Archive + Replay as Research Instrument (plan)

**Phase:** 2 of 11
**Owner:** alpha
**Spec:** `docs/superpowers/specs/2026-04-14-lrr-phase-2-archive-research-instrument-design.md`

## PR sequence (target 5 PRs, mirroring Phase 1's shape)

### PR #1 — Foundation + archival re-enable script + retention policy doc

**Items:** 1, 8

**Files:**
- `scripts/archive-reenable.py` — gated enable/disable/status CLI wrapping `systemctl --user enable|disable|status` over the 8 disabled units. Default dry-run. `--live` required to actually enable.
- `docs/superpowers/specs/2026-04-14-lrr-phase-2-archive-retention.md` — retention policy doc
- `tests/test_archive_reenable.py` — CLI tests (dry-run output, unit list pin, --live gating)

### PR #2 — Per-segment metadata sidecar + HLS rotation hook + audio path migration

**Items:** 2, 3, 5

**Files:**
- `agents/studio_compositor/hls_archive.py` — rotation tick that moves closed HLS segments from `~/.cache/hapax-compositor/hls/` to `~/hapax-state/stream-archive/hls/YYYY-MM-DD/` + writes sidecar JSON
- `shared/stream_archive.py` — sidecar schema dataclass + writer helper (reusable by audio archive path too)
- `systemd/units/audio-recorder.service.d/archive-path.conf` — drop-in to land FLAC under `~/hapax-state/stream-archive/audio/YYYY-MM-DD/`
- `systemd/units/contact-mic-recorder.service.d/archive-path.conf` — same for Cortado
- `systemd/units/studio-compositor.service.d/hls-rotate.conf` — drop-in removing the `ExecStartPre` find-delete + adding the rotation hook startup
- `tests/test_stream_archive_sidecar.py` — sidecar schema + writer tests
- `tests/test_hls_archive_rotation.py` — rotation tick tests

### PR #3 — Research-marker frame injection overlay

**Items:** 4

**Files:**
- `agents/studio_compositor/research_marker_overlay.py` — `CairoSource` that reads `/dev/shm/hapax-compositor/research-marker.json` + renders "Condition: <id>" at top-right when marker updated within last 3s
- `tests/test_research_marker_overlay.py` — render-cycle tests (active vs. inactive)
- `agents/studio_compositor/compositor.py` — registration of the new source (if not already pluggable)

### PR #4 — Archive search + purge CLIs

**Items:** 6, 9

**Files:**
- `scripts/archive-search.py` — subcommand CLI (by-condition, by-reaction, by-timerange, extract)
- `scripts/archive-purge.py` — `--condition <id> --confirm` + purge audit log
- `tests/test_archive_search.py` — subcommand tests against synthetic sidecar fixtures
- `tests/test_archive_purge.py` — dry-run, confirm, audit log entry tests

### PR #5 — Layout-declared video_out migration + vault integration + Phase 2 close handoff

**Items:** 7, 10, close

**Files:**
- `config/compositor-layouts/default.json` — add `video_out` surfaces (v4l2 loopback, MediaMTX, HLS, archive branch)
- `agents/studio_compositor/output_router.py` — `from_layout()` wiring
- `agents/studio_compositor/compositor.py` — call `OutputRouter.from_layout()` when layout declares `video_out` surfaces; fall back to hardcoded paths otherwise
- `shared/stream_archive.py` — `VaultNoteRenderer` gated on `HAPAX_VAULT_PATH` env var
- `tests/test_output_router_layout.py` — from_layout tests
- `tests/test_vault_note_renderer.py` — vault renderer tests
- `docs/superpowers/handoff/2026-04-14-lrr-phase-2-complete.md` — close handoff

## Pickup procedure

The next session opening Phase 3 (pending hardware) reads:
1. `~/.cache/hapax/relay/lrr-state.yaml` — confirms Phase 2 closed
2. `docs/superpowers/handoff/2026-04-14-lrr-phase-2-complete.md` — Phase 2 close handoff
3. Epic design doc §Phase 3 — hardware migration + Hermes 3

## Notes

- Phase 2 is code-heavy, operator-gated only for item 1 live re-enablement. Items 2-10 ship as code + tests.
- Item 4 overlay is visible in the live stream; operator will see it when a condition change fires. Visual smoke test is a stretch goal — unit test covers the cadence logic.
- Retention policy doc (item 8) locks in "no automatic deletion" as the default.
