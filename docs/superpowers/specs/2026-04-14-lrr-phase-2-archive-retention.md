# LRR Phase 2 — Archive Retention Policy

**Phase:** 2 (Archive + Replay as Research Instrument)
**Status:** authoritative (this document governs the archive lifecycle)
**Referenced from:** `docs/superpowers/specs/2026-04-14-lrr-phase-2-archive-research-instrument-design.md` §Item 8

## Principle

**No automatic deletion.** Archive retention is an explicit operator decision, not a silent sweep. This document freezes that invariant.

## Rules

### R1 — Active condition data is retained indefinitely

Segments whose `condition_id` matches the currently active condition (`scripts/research-registry.py current`) are **never** auto-deleted. Losing Condition A data while Condition A' is still collecting collapses the control arm and invalidates the claim.

### R2 — Closed condition data is retained until claim analyzed + report authored

A condition is "closed" when `research-registry.py close <id>` has been run AND the per-phase handoff doc for the phase that analyzed it is merged. Until then, the data is read-only but live.

Retention terminates (i.e. becomes eligible for purge) when:
1. The claim's report is in the repo (`docs/research/claims/<claim-id>-report.md` or equivalent), AND
2. The operator runs `scripts/archive-purge.py --condition <id> --confirm`.

No automatic trigger. Operator action only.

### R3 — All condition data is revocable per consent contract

If an active consent contract is revoked, the associated condition's archive data can be purged via the same `archive-purge.py` CLI. This satisfies the `interpersonal_transparency` axiom by giving the operator a clean deletion path.

Revocation does NOT auto-trigger deletion; the operator must run the purge CLI explicitly. Revocation only unlocks the purge-without-report-authored path.

### R4 — Purge writes an audit log entry

Every purge run (dry-run or confirmed) appends a JSONL entry to `~/hapax-state/stream-archive/purge.log`:

```json
{
  "ts": "2026-04-15T12:34:56Z",
  "condition_id": "cond-phase-a-baseline-qwen-001",
  "mode": "dry_run" | "confirmed",
  "operator": "hapax",
  "segments_affected": 1234,
  "bytes_affected": 75000000000,
  "reason": "claim analyzed + report authored" | "consent revocation" | "operator explicit"
}
```

Audit log is append-only and never rotated — it's a legal record.

### R5 — No silent background purge

No systemd timer, no cron, no compositor-internal sweep. Purging is **only** via the explicit CLI. This rule exists to prevent "fell out of cache before I analyzed it" data loss.

**Explicit exception:** `video-retention.timer` (one of the 8 disabled units) MAY be re-enabled in a future phase if the operator accepts an explicit time-based cap — but its current target is `~/.cache/hapax-compositor/hls/` (the pre-rotation path), not `~/hapax-state/stream-archive/`. Phase 2 leaves that timer as-is; if it runs against the pre-rotation cache, it does not touch the archive.

## Disk pressure triage

At 24/7 streaming:
- Video: ~6000 kbps → ~70 GB/day
- Audio (Blue Yeti + Cortado FLAC, 48 kHz 16-bit mono): ~17 GB/day combined

Total: **~87 GB/day**.

Current `/home` free: 763 GB.

Projected fill rate: **~9 days until `/home` hits 90% usage**, **~11 days until total fill**.

### Triage thresholds

| `/home` usage | Action |
|---|---|
| <70% | Normal. No action. |
| 70-85% | Nudge operator via ntfy ("archive approaching 85%, consider triage"). |
| 85-95% | Alert operator via ntfy + email ("archive at 85%, operator triage needed"). Do NOT auto-purge. |
| >95% | Hard alert via ntfy + email + desktop notification. Still do NOT auto-purge — operator decides whether to purge closed conditions, move to external disk, or accept archive pause. |

### Operator triage options when full

1. **Purge closed conditions** whose report is authored (normal path).
2. **Move archive root** to a separate disk / external volume (`ARCHIVE_ROOT` env var or symlink).
3. **Pause archival** (`systemctl --user stop audio-recorder contact-mic-recorder video-recorder` — loses data during pause, explicit operator choice).
4. **Accept data loss** on a specific closed condition via `archive-purge.py --condition <id> --confirm --reason "disk pressure"`.

## Separate-disk future path (not Phase 2 scope)

If sustained 24/7 streaming is the norm, the archive should move to a dedicated disk. Phase 2 does not provision this. If provisioned:

- `ARCHIVE_ROOT=/mnt/archive/hapax-state/stream-archive` as an env var
- All archival paths relative to `ARCHIVE_ROOT`
- Rotation hook respects `ARCHIVE_ROOT` if set, falls back to `~/hapax-state/stream-archive/` otherwise

This migration is filed as a future Phase 10 polish item, not Phase 2.

## Invariants a future refactor must preserve

1. No code path deletes archive data without going through `archive-purge.py`.
2. `archive-purge.py` always requires `--confirm` to actually delete. Default is dry-run.
3. Every purge writes an audit log entry.
4. Active condition data can never be purged (the CLI refuses).
5. Retention policy changes require an explicit edit to this document.
