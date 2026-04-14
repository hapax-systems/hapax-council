# LRR Phase 2 — Archive + Replay as Research Instrument (design)

**Phase:** 2 of 11
**Owner:** alpha
**Branch:** `feat/lrr-phase-2-archive-research-instrument`
**Dependency:** Phase 1 complete (registry + metadata schema + research-marker SHM)
**Epic design reference:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §Phase 2 (line 288)
**Epic plan reference:** `docs/superpowers/plans/2026-04-14-livestream-research-ready-epic-plan.md`

## Goal

Re-enable the disabled archival pipeline (audio/video recording, classification, RAG ingest) with research-grade metadata injection, per-segment condition tags, and retention guarantees — so archived segments become the raw data for Condition A vs A' analysis under Option B.

## Items (10, mirroring epic design §Phase 2 scope)

1. **Re-enable archival pipeline.** 8 disabled systemd units (`audio-recorder`, `contact-mic-recorder`, `rag-ingest`, `audio-processor.timer`, `video-processor.timer`, `av-correlator.timer`, `flow-journal.timer`, `video-retention.timer`). Ship a gated enable script (dry-run + live mode) rather than raw operator sudo. Live re-enablement is operator-gated but the script + its tests are repo-owned.

2. **HLS segment persistence policy.** Current: `studio-compositor.service` `ExecStartPre=/usr/bin/find %h/.cache/hapax-compositor/hls -type f -delete`. Change: segments rotate to `~/hapax-state/stream-archive/hls/YYYY-MM-DD/` instead of deletion. Retention: indefinite during active conditions. Implementation: a new rotation hook (systemd path unit or compositor-internal rotation tick) that moves closed segments + updates the sidecar JSON.

3. **Per-segment metadata sidecar.** Each closed HLS segment gets a `.json` sidecar with: `condition_id`, `segment_start_ts`, `segment_end_ts`, `reaction_ids[]`, `active_activity`, `stimmung_snapshot`, `directives_hash`. Writer lives in the rotation hook; reads `current.json` and the research marker SHM file to stamp the segment.

4. **Research-marker frame injection.** On condition change (`research-registry.py open|close`), write a visible overlay to the HLS stream for ~3 seconds (textual "Condition: <id>" at top-right). Gives frame-accurate boundary detection. Implementation option: a new `CairoSource` that renders the overlay when the research marker SHM file has been updated in the last 3 seconds.

5. **Audio archive.** Audio already has existing `audio-recorder.service` (Blue Yeti → FLAC) and `contact-mic-recorder.service` (Cortado → FLAC). These write to their default path; Phase 2 adds a path migration so they land under `~/hapax-state/stream-archive/audio/YYYY-MM-DD/` for consistency with video archive.

6. **Archive search CLI.** `scripts/archive-search.py` with subcommands:
   - `by-condition <condition_id>` — scan sidecar JSON files, filter by `condition_id`
   - `by-reaction <reaction_id>` — scan for `reaction_ids` containing the given ID
   - `by-timerange <start_iso> <end_iso>` — filter by `segment_start_ts`
   - `extract <segment_id> <output_dir>` — copy the .ts + .json to output_dir
   Returns machine-readable list (JSON) by default, plus a human-readable `--format=table` option.

7. **Vault integration.** Optional: on segment sidecar write, render a templated note to `~/Documents/Personal/30-areas/legomena-live/archive/YYYY-MM/segment-<id>.md` (or similar). Scope this as **a standalone renderer that only runs if a vault path env var is set**, so the archival pipeline doesn't require vault presence in tests / headless runs.

8. **Lifecycle / retention policy doc.** `docs/superpowers/specs/2026-04-14-lrr-phase-2-archive-retention.md`. Rules: active condition data retained indefinitely; closed condition data retained until claim analyzed + report authored; purge-by-condition CLI; no automatic deletion without explicit policy change. Reserves the retention knob for future operator tuning.

9. **Purge CLI.** `scripts/archive-purge.py --condition <id> --confirm` — auditable deletion tied to consent revocation. Writes a purge audit log entry to `~/hapax-state/stream-archive/purge.log`. Safe defaults: without `--confirm`, prints what would be deleted (dry-run always the default).

10. **Layout-declared `video_out` surfaces migration.** Current: OutputRouter abstraction exists (`agents/studio_compositor/output_router.py`) but `config/compositor-layouts/default.json` declares zero `video_out` surfaces — actual stream output is hardcoded in `compositor.py` + `rtmp_output.py`. Migration:
    - Add `video_out` surfaces to `default.json` for each current sink: `/dev/video42` (v4l2 loopback), `rtmp://127.0.0.1:1935/studio` (MediaMTX), HLS playlist, **new local archive branch from Phase 2**
    - Wire `OutputRouter.from_layout()` into `compositor.start()` so OutputBinding enumeration drives actual sink construction
    - Legacy hardcoded paths remain as fallback during transition; deprecated in Phase 10 polish

## Exit criteria (10 items, mirror epic design)

- [x] Archival pipeline script lands (item 1) — re-enablement staged as repo-owned, live-enable is operator-gated
- [ ] Segment rotation to `~/hapax-state/stream-archive/hls/` works (item 2) — integration test or live verification
- [ ] Per-segment sidecar JSON files have all required fields (item 3) — unit tests + live smoke
- [ ] Condition change triggers frame marker overlay for ~3s (item 4) — unit test on overlay cadence + visual smoke-test deferred to operator
- [ ] Audio archive path migration lands (item 5) — systemd drop-in unit tests
- [ ] `archive-search.py by-condition cond-phase-a-baseline-qwen-001` returns segments (item 6) — unit tests + live smoke
- [ ] Vault integration optional renderer works when `HAPAX_VAULT_PATH` set (item 7) — unit test
- [ ] Retention policy doc shipped (item 8)
- [ ] Purge CLI with dry-run default + audit log (item 9) — unit tests
- [ ] Layout-declared `video_out` migration wired with fallback (item 10) — unit test on OutputRouter.from_layout + compositor integration smoke

## Non-goals

- **Physical disk provisioning.** If `/home` hits pressure, operator decides separate disk vs external. Phase 2 documents the pressure profile (~70 GB/day video) but does not provision.
- **RAG ingest re-population.** Re-enabling `rag-ingest.service` may re-populate Qdrant; Phase 2 enables the service but defers monitoring the Qdrant `/data` inode pressure to Phase 0 item 3 (already operator-gated cross-repo).
- **Claim analysis tooling.** Searching + extracting segments is Phase 2; analyzing them against Bayesian claims is Phase 4+.

## Risks

1. **Disk pressure.** 24/7 stream at 6000 kbps + audio = ~70 GB/day video alone. Currently 763 GB free on `/home` → ~11 days before pressure without rotation. Mitigation: lifecycle policy (item 8) caps retention.
2. **Vault integration coupling.** Vault schema requires operator buy-in. Mitigation: item 7 is env-gated, tests run without vault.
3. **Layout migration regresses stream output.** Mitigation: legacy hardcoded paths remain as fallback (item 10 explicit).
4. **Rotation hook races with HLS writer.** Mitigation: only rotate segments whose mtime is stable for N seconds (typical HLS segment duration).

## Frozen files under condition `cond-phase-a-baseline-qwen-001`

Phase 2 touches archival infrastructure which is NOT in the current frozen-files list (frozen paths are grounding/persona). The compositor itself is not frozen. No deviations expected.

## Deviation log

_(None so far.)_
