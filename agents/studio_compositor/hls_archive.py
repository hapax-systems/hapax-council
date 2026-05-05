"""HLS segment rotation from the compositor cache to the research archive.

LRR Phase 2 item 2 + item 3. Walks ``~/.cache/hapax-compositor/hls/`` for
closed segments (``*.ts``), moves them to
``~/hapax-state/stream-archive/hls/YYYY-MM-DD/`` with a per-segment
sidecar JSON. Invoked periodically (systemd timer or operator CLI).

"Closed" = a segment whose mtime has been stable for at least
``STABLE_MTIME_WINDOW_SECONDS`` (default 10 s). This avoids racing the
``hlssink2`` writer — the element rotates segments every
``target-duration`` seconds (``HlsConfig.target_duration`` default 2 s),
so the 10 s window gives a 5× safety margin.

**Segment wall-clock semantics.** ``hlssink2`` writes segment contents
incrementally and finalizes each file on close, so ``segment_path.stat().
st_mtime`` is the segment's CLOSE (end) time. The rotator derives the
START time by subtracting ``target_duration_seconds`` from the close
time — the same ``#EXT-X-TARGETDURATION`` value the playlist
advertises. This is the Phase 1 audit H4 fix: before this change,
``rotate_segment`` set ``segment_start_ts = mtime`` (the END time)
and ``segment_end_ts = now`` (the rotator's run time, which is
close_time + stable_window ≈ 10-15s late), inverting both fields.
``archive-search.py by-timerange`` queries consequently missed every
segment whose actual start fell inside the query window but whose
sidecar-reported start was several seconds later.

Metadata is assembled from:
- ``~/hapax-state/research-registry/current.txt`` → active condition_id
- ``/dev/shm/hapax-compositor/research-marker.json`` → Phase 1 research marker
- ``/dev/shm/hapax-daimonion/current.json`` → stimmung snapshot (best effort)
- ``~/hapax-state/stream-reactions-*.jsonl`` → reaction IDs in the segment window (best effort)
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shared.stream_archive import (
    SegmentSidecar,
    atomic_write_json,
    hls_archive_dir,
    sidecar_path_for,
)

log = logging.getLogger(__name__)

DEFAULT_STABLE_MTIME_WINDOW_SECONDS = 10.0
"""Minimum mtime-stable age before a segment is considered closed + rotatable."""

DEFAULT_TARGET_DURATION_SECONDS = 2.0
"""Assumed segment duration used to derive ``segment_start_ts`` from the
close-time mtime. Matches ``shared.compositor_model.HlsConfig.target_duration``
default (2 s). Call sites with access to the live config should pass the
actual value through ``rotate_segment`` / ``rotate_pass``."""

DEFAULT_HLS_SOURCE_DIR = Path.home() / ".cache" / "hapax-compositor" / "hls"
"""Compositor HLS output directory — matches ``hls_cfg.output_dir`` default."""

DEFAULT_STIMMUNG_PATH = Path("/dev/shm/hapax-daimonion/current.json")
"""Best-effort stimmung snapshot source. Absent → empty dict."""

DEFAULT_CONDITION_POINTER = Path.home() / "hapax-state" / "research-registry" / "current.txt"
"""Research registry active condition pointer (Phase 1 item 8)."""


@dataclass(frozen=True)
class RotationResult:
    """Summary of a single rotation pass. Used for logging + tests."""

    scanned: int
    rotated: int
    skipped_unstable: int
    skipped_already_rotated: int
    errors: list[str]


def _load_condition_id(pointer_path: Path = DEFAULT_CONDITION_POINTER) -> str | None:
    """Read the active condition_id. None if unset or registry is not initialized."""
    if not pointer_path.exists():
        return None
    try:
        value = pointer_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _load_stimmung_snapshot(
    stimmung_path: Path = DEFAULT_STIMMUNG_PATH,
) -> dict[str, Any]:
    """Best-effort stimmung snapshot. Returns {} if unavailable.

    Enriched with a ``camera_salience`` key carrying the broker's WCS
    projection (``None`` when the broker is unavailable). The salience
    projection is *used* as part of the per-segment sidecar payload —
    archive readers can correlate a segment's stimmung with which
    apertures were salient at rotation time.
    """
    salience = _query_camera_salience_for_archive()
    if not stimmung_path.exists():
        return {"camera_salience": salience}
    try:
        payload = json.loads(stimmung_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"camera_salience": salience}
    if not isinstance(payload, dict):
        return {"camera_salience": salience}
    return {
        "stance": payload.get("stance"),
        "dimensions": payload.get("dimensions"),
        "snapshotted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "camera_salience": salience,
    }


def _query_camera_salience_for_archive() -> dict[str, Any] | None:
    """Query the broker for the per-segment archive sidecar context.

    Mirrors the inline pattern used by ``director_loop`` and
    ``affordance_pipeline``. Fails closed (returns ``None``) so a
    broker outage never blocks segment rotation — archive integrity is
    the higher-priority invariant.
    """
    try:
        from shared.camera_salience_singleton import broker as _camera_broker

        bundle = _camera_broker().query(
            consumer="archive",
            decision_context="hls_segment_rotation",
            candidate_action="archive_segment",
        )
        if bundle is None:
            return None
        return bundle.to_wcs_projection_payload()
    except Exception:
        log.debug("camera salience archive query failed", exc_info=True)
        return None


def is_segment_stable(
    segment_path: Path,
    *,
    now_ts: float,
    window_seconds: float = DEFAULT_STABLE_MTIME_WINDOW_SECONDS,
) -> bool:
    """Return True if the segment's mtime is stable enough to rotate."""
    try:
        mtime = segment_path.stat().st_mtime
    except OSError:
        return False
    return (now_ts - mtime) >= window_seconds


def build_sidecar(
    *,
    segment_path: Path,
    segment_start_ts: datetime,
    segment_end_ts: datetime,
    condition_id: str | None,
    stimmung: dict[str, Any],
    reaction_ids: list[str] | None = None,
    active_activity: str | None = None,
    directives_hash: str | None = None,
) -> SegmentSidecar:
    """Construct the sidecar for a single HLS segment."""
    return SegmentSidecar.new(
        segment_id=segment_path.stem,
        segment_path=segment_path,
        condition_id=condition_id,
        segment_start_ts=segment_start_ts,
        segment_end_ts=segment_end_ts,
        reaction_ids=reaction_ids,
        active_activity=active_activity,
        stimmung_snapshot=stimmung,
        directives_hash=directives_hash,
        archive_kind="hls",
    )


def rotate_segment(
    segment_path: Path,
    *,
    target_dir: Path,
    condition_id: str | None,
    stimmung: dict[str, Any],
    now: datetime | None = None,
    target_duration_seconds: float = DEFAULT_TARGET_DURATION_SECONDS,
    dest_filename: str | None = None,
) -> Path:
    """Move a single segment to the archive + write its sidecar.

    Returns the new segment path. Sidecar path is derived via
    ``sidecar_path_for(new_path)``. The move is atomic enough for our
    purposes (same filesystem) — ``shutil.move`` uses ``os.rename`` when
    possible and falls back to copy+unlink across filesystems.

    Phase 1 audit H4 fix: ``hlssink2`` finalizes segments on close, so
    ``segment_path.stat().st_mtime`` is the segment's END time. The
    sidecar's ``segment_end_ts`` is therefore the mtime; the
    ``segment_start_ts`` is ``mtime - target_duration_seconds``. The
    rotator's own run time (``now``) is retained only as a fallback
    when the stat call fails. ``archive-search.py by-timerange``
    queries against segments produced before this fix shipped will
    still see the old (inverted) timestamps — the rewrite is a
    separate backfill job.

    Phase 2 filename-collision handling: ``dest_filename`` optionally
    overrides the target filename so the rotate_pass caller can
    resolve collisions from compositor-restart segment-counter resets
    (e.g., a new ``segment00000.ts`` from after a restart going to
    ``segment00000.ts.1``). When ``None``, the original filename is
    preserved (backwards-compatible default).
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    new_path = target_dir / (dest_filename or segment_path.name)
    if new_path.exists():
        raise FileExistsError(f"archive destination already occupied: {new_path}")

    fallback_now = now or datetime.now(UTC)
    try:
        mtime_utc = datetime.fromtimestamp(segment_path.stat().st_mtime, tz=UTC)
    except OSError:
        # Best-effort fallback: stat failed (unlinked mid-rotation?),
        # use the rotator's run time for both ends, duration-zero. The
        # subsequent shutil.move will also fail and raise, so this path
        # is only observable in races.
        mtime_utc = fallback_now

    segment_end = mtime_utc
    segment_start = mtime_utc - timedelta(seconds=target_duration_seconds)

    shutil.move(str(segment_path), str(new_path))

    sidecar = build_sidecar(
        segment_path=new_path,
        segment_start_ts=segment_start,
        segment_end_ts=segment_end,
        condition_id=condition_id,
        stimmung=stimmung,
    )
    atomic_write_json(sidecar_path_for(new_path), sidecar.to_json())
    return new_path


def rotate_pass(
    *,
    source_dir: Path | None = None,
    now_ts: float | None = None,
    window_seconds: float = DEFAULT_STABLE_MTIME_WINDOW_SECONDS,
    condition_pointer: Path | None = None,
    stimmung_path: Path | None = None,
    target_duration_seconds: float = DEFAULT_TARGET_DURATION_SECONDS,
) -> RotationResult:
    """Walk the HLS source dir, rotate stable segments, return a summary.

    Caller is responsible for scheduling (systemd timer, operator CLI).
    Defaults resolve at call time so test monkeypatching against the
    module-level constants takes effect.

    ``target_duration_seconds`` is forwarded to every ``rotate_segment``
    call for the H4 sidecar-timestamp derivation. Callers that have
    access to the live ``HlsConfig`` should pass
    ``hls_cfg.target_duration`` explicitly; the default matches the
    shipping config.
    """
    import time as _time

    effective_source = source_dir if source_dir is not None else DEFAULT_HLS_SOURCE_DIR
    effective_pointer = (
        condition_pointer if condition_pointer is not None else DEFAULT_CONDITION_POINTER
    )
    effective_stimmung = stimmung_path if stimmung_path is not None else DEFAULT_STIMMUNG_PATH

    if not effective_source.exists():
        return RotationResult(
            scanned=0, rotated=0, skipped_unstable=0, skipped_already_rotated=0, errors=[]
        )

    now_ts = now_ts if now_ts is not None else _time.time()
    now_dt = datetime.fromtimestamp(now_ts, tz=UTC)
    condition_id = _load_condition_id(effective_pointer)
    stimmung = _load_stimmung_snapshot(effective_stimmung)
    target_dir = hls_archive_dir(at=now_dt)

    scanned = 0
    rotated = 0
    skipped_unstable = 0
    skipped_already_rotated = 0
    errors: list[str] = []

    for segment_path in sorted(effective_source.glob("*.ts")):
        scanned += 1
        if not is_segment_stable(segment_path, now_ts=now_ts, window_seconds=window_seconds):
            skipped_unstable += 1
            continue
        # Phase 2 filename-collision resolution.
        #
        # On compositor restart, hlssink2's segment counter resets to 0
        # and reuses names like `segment00000.ts`. The target_dir
        # already contains a file with that name from the previous
        # boot's output. The previous "exists → skip as already
        # rotated" check silently dropped every live segment after
        # restart, stalling the whole archive indefinitely.
        #
        # Fix: compare mtime between the live source and the archived
        # destination. If within 2 s, same segment (tolerates the
        # mtime-preserving shutil.move). Otherwise collision from a
        # different boot — find next available numeric suffix and
        # rotate the new segment into ``segment00000.ts.1`` etc.
        # Chronological ordering is preserved via the sidecar
        # ``segment_end_ts`` regardless of filename.
        dest_filename: str | None = None
        live_dest = target_dir / segment_path.name
        if live_dest.exists():
            try:
                src_mtime = segment_path.stat().st_mtime
                dest_mtime = live_dest.stat().st_mtime
            except OSError:
                skipped_already_rotated += 1
                continue
            if abs(src_mtime - dest_mtime) < 2.0:
                skipped_already_rotated += 1
                continue
            stem = segment_path.stem
            suffix = segment_path.suffix
            for n in range(1, 10000):
                alt_name = f"{stem}.{n}{suffix}"
                if not (target_dir / alt_name).exists():
                    dest_filename = alt_name
                    break
            if dest_filename is None:
                errors.append(
                    f"{segment_path.name}: collision suffix exhausted at 10000 — "
                    "live segment could not be archived"
                )
                continue
        try:
            rotate_segment(
                segment_path,
                target_dir=target_dir,
                condition_id=condition_id,
                stimmung=stimmung,
                now=now_dt,
                target_duration_seconds=target_duration_seconds,
                dest_filename=dest_filename,
            )
            rotated += 1
        except Exception as exc:  # pragma: no cover — defensive log-and-continue
            errors.append(f"{segment_path.name}: {type(exc).__name__}: {exc}")

    return RotationResult(
        scanned=scanned,
        rotated=rotated,
        skipped_unstable=skipped_unstable,
        skipped_already_rotated=skipped_already_rotated,
        errors=errors,
    )


__all__ = [
    "DEFAULT_STABLE_MTIME_WINDOW_SECONDS",
    "DEFAULT_TARGET_DURATION_SECONDS",
    "DEFAULT_HLS_SOURCE_DIR",
    "DEFAULT_STIMMUNG_PATH",
    "DEFAULT_CONDITION_POINTER",
    "RotationResult",
    "build_sidecar",
    "is_segment_stable",
    "rotate_pass",
    "rotate_segment",
]
