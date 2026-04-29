"""Produce canonical public events from legacy broadcast rotation events.

This is a compatibility adapter: it tails the existing
``/dev/shm/hapax-broadcast/events.jsonl`` bus and writes
``ResearchVehiclePublicEvent`` records to a separate JSONL stream. Existing
legacy consumers keep reading the original bus.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.livestream_egress_state import (
    FloorState,
    LivestreamEgressState,
    resolve_livestream_egress_state,
)
from shared.research_vehicle_public_event import (
    PrivacyClass,
    PublicEventChapterRef,
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
    RightsClass,
    Surface,
)
from shared.youtube_rate_limiter import QuotaBucket

log = logging.getLogger(__name__)

LEGACY_EVENT_PATH = Path(
    os.environ.get("HAPAX_BROADCAST_EVENT_PATH", "/dev/shm/hapax-broadcast/events.jsonl")
)
PUBLIC_EVENT_PATH = Path(
    os.environ.get(
        "HAPAX_RESEARCH_VEHICLE_PUBLIC_EVENT_PATH",
        "/dev/shm/hapax-public-events/events.jsonl",
    )
)
CURSOR_PATH = Path(
    os.environ.get(
        "HAPAX_BROADCAST_BOUNDARY_PUBLIC_EVENT_CURSOR",
        str(Path.home() / ".cache/hapax/broadcast-boundary-public-event-cursor.txt"),
    )
)
DEFAULT_TICK_S = float(os.environ.get("HAPAX_BROADCAST_BOUNDARY_PUBLIC_EVENT_TICK_S", "30"))
LEGACY_EVENT_TYPE = "broadcast_rotated"
TASK_ANCHOR = "broadcast-boundary-public-event-producer"

_PUBLIC_SAFE_RIGHTS = {"operator_original", "operator_controlled", "third_party_attributed"}
_PUBLIC_SAFE_PRIVACY = {"public_safe", "aggregate_only"}
_YOUTUBE_METADATA_COST = 50
_BROADCAST_BOUNDARY_SURFACES: tuple[Surface, ...] = (
    "youtube_description",
    "youtube_chapters",
    "omg_statuslog",
    "mastodon",
    "bluesky",
    "discord",
    "archive",
    "replay",
    "health",
)
_NON_BOUNDARY_SURFACES: tuple[Surface, ...] = (
    "youtube_cuepoints",
    "youtube_captions",
    "youtube_shorts",
    "youtube_channel_sections",
    "arena",
    "omg_weblog",
    "omg_now",
    "captions",
    "cuepoints",
    "monetization",
)


@dataclass(frozen=True)
class BroadcastBoundaryPolicyConfig:
    """Policy defaults for mapping a legacy rotation to RVPE."""

    source_substrate_id: str = "youtube_metadata"
    rights_class: RightsClass = "operator_original"
    privacy_class: PrivacyClass = "public_safe"
    rights_basis: str = "operator generated broadcast lifecycle metadata"
    task_anchor: str = TASK_ANCHOR
    freshness_ttl_s: float = 12 * 3600.0
    quota_endpoint: str = "videos.update"
    quota_min_remaining: int = _YOUTUBE_METADATA_COST
    salience: float = 0.68


@dataclass(frozen=True)
class _TailRecord:
    byte_start: int
    byte_after: int
    event: dict[str, Any] | None
    error: str | None = None


EgressResolver = Callable[[], LivestreamEgressState]
QuotaRemaining = Callable[[str], int]
TimeFn = Callable[[], float]


class ByteCursorJsonlTailer:
    """Byte-offset JSONL tailer that processes existing lines on first run.

    If the source file shrinks below the persisted cursor, the cursor resets to
    zero and the current file is processed from the beginning. That avoids the
    cross-surface failure mode where a stale cursor sits beyond a rotated or
    truncated legacy event file forever.
    """

    def __init__(self, path: Path, cursor_path: Path) -> None:
        self._path = path
        self._cursor_path = cursor_path

    def read_cursor(self) -> int:
        try:
            value = int(self._cursor_path.read_text(encoding="utf-8").strip() or "0")
        except (FileNotFoundError, ValueError, OSError):
            return 0
        return max(0, value)

    def write_cursor(self, byte_offset: int) -> None:
        self._cursor_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._cursor_path.with_suffix(".tmp")
        tmp.write_text(str(max(0, byte_offset)), encoding="utf-8")
        tmp.replace(self._cursor_path)

    def iter_new(self) -> Iterator[_TailRecord]:
        try:
            size = self._path.stat().st_size
        except OSError:
            return

        cursor = self.read_cursor()
        if cursor > size:
            log.warning("legacy event file shrank from cursor %d to %d bytes", cursor, size)
            cursor = 0
            self.write_cursor(0)

        try:
            with self._path.open("rb") as fh:
                fh.seek(cursor)
                while True:
                    byte_start = fh.tell()
                    raw = fh.readline()
                    if not raw:
                        return
                    byte_after = fh.tell()
                    text = raw.decode("utf-8", errors="replace").strip()
                    if not text:
                        yield _TailRecord(byte_start=byte_start, byte_after=byte_after, event=None)
                        continue
                    try:
                        event = json.loads(text)
                    except json.JSONDecodeError as exc:
                        yield _TailRecord(
                            byte_start=byte_start,
                            byte_after=byte_after,
                            event=None,
                            error=f"json_decode_error:{exc.msg}",
                        )
                        continue
                    if not isinstance(event, dict):
                        yield _TailRecord(
                            byte_start=byte_start,
                            byte_after=byte_after,
                            event=None,
                            error="json_not_object",
                        )
                        continue
                    yield _TailRecord(byte_start=byte_start, byte_after=byte_after, event=event)
        except OSError:
            log.warning("legacy event read failed at %s", self._path, exc_info=True)


class BroadcastBoundaryPublicEventProducer:
    """Tail legacy broadcast rotations and emit canonical RVPE records."""

    def __init__(
        self,
        *,
        legacy_event_path: Path = LEGACY_EVENT_PATH,
        public_event_path: Path = PUBLIC_EVENT_PATH,
        cursor_path: Path = CURSOR_PATH,
        policy: BroadcastBoundaryPolicyConfig | None = None,
        egress_resolver: EgressResolver | None = None,
        quota_remaining: QuotaRemaining | None = None,
        time_fn: TimeFn = time.time,
    ) -> None:
        self._legacy_event_path = legacy_event_path
        self._public_event_path = public_event_path
        self._policy = policy or BroadcastBoundaryPolicyConfig()
        self._egress_resolver = egress_resolver or resolve_livestream_egress_state
        self._quota_remaining = quota_remaining or QuotaBucket.default().remaining
        self._time = time_fn
        self._tailer = ByteCursorJsonlTailer(legacy_event_path, cursor_path)
        self._known_event_ids: set[str] | None = None

    def run_once(self) -> int:
        """Process one batch from the legacy bus.

        Returns the number of new public events written. Cursor advances for
        malformed, ignored, and already-emitted legacy lines, but stops before a
        line whose canonical write fails.
        """

        written = 0
        for record in self._tailer.iter_new():
            if record.event is None:
                if record.error:
                    log.warning(
                        "skipping malformed legacy event at byte %d: %s",
                        record.byte_start,
                        record.error,
                    )
                self._tailer.write_cursor(record.byte_after)
                continue

            if record.event.get("event_type") != LEGACY_EVENT_TYPE:
                self._tailer.write_cursor(record.byte_after)
                continue

            event = build_broadcast_boundary_public_event(
                record.event,
                evidence_ref=f"{self._legacy_event_path}#byte={record.byte_start}",
                egress_state=self._egress_resolver(),
                quota_remaining=self._quota_remaining(self._policy.quota_endpoint),
                generated_at=_iso_from_epoch(self._time()),
                now=self._time(),
                policy=self._policy,
            )
            if self._event_already_written(event.event_id):
                self._tailer.write_cursor(record.byte_after)
                continue
            if not self._append_public_event(event):
                break
            self._tailer.write_cursor(record.byte_after)
            written += 1
        return written

    def _append_public_event(self, event: ResearchVehiclePublicEvent) -> bool:
        try:
            self._public_event_path.parent.mkdir(parents=True, exist_ok=True)
            with self._public_event_path.open("a", encoding="utf-8") as fh:
                fh.write(event.to_json_line())
        except OSError:
            log.warning("public event write failed at %s", self._public_event_path, exc_info=True)
            return False
        if self._known_event_ids is not None:
            self._known_event_ids.add(event.event_id)
        return True

    def _event_already_written(self, event_id: str) -> bool:
        if self._known_event_ids is None:
            self._known_event_ids = _load_event_ids(self._public_event_path)
        return event_id in self._known_event_ids


def build_broadcast_boundary_public_event(
    legacy_event: Mapping[str, Any],
    *,
    evidence_ref: str,
    egress_state: LivestreamEgressState,
    quota_remaining: int,
    generated_at: str,
    now: float,
    policy: BroadcastBoundaryPolicyConfig | None = None,
) -> ResearchVehiclePublicEvent:
    """Map a legacy ``broadcast_rotated`` record to ``broadcast.boundary``."""

    cfg = policy or BroadcastBoundaryPolicyConfig()
    event_id = broadcast_boundary_event_id(legacy_event)
    broadcast_id = _clean_optional_str(
        legacy_event.get("incoming_broadcast_id") or legacy_event.get("active_broadcast_id")
    )
    incoming_url = _clean_optional_str(legacy_event.get("incoming_broadcast_url"))
    timestamp = _clean_optional_str(legacy_event.get("timestamp")) or generated_at
    occurred_at = _normalise_iso(timestamp) or generated_at
    source_age_s = _event_age_s(occurred_at, now)
    provenance_token = _provenance_token(legacy_event, event_id)
    blockers = _policy_blockers(
        legacy_event=legacy_event,
        egress_state=egress_state,
        quota_remaining=quota_remaining,
        provenance_token=provenance_token,
        broadcast_id=broadcast_id,
        source_age_s=source_age_s,
        policy=cfg,
    )
    surface_policy = _surface_policy(
        blockers=blockers, claim_archive=bool(legacy_event.get("outgoing_vod_url"))
    )
    chapter_label = _chapter_label(legacy_event)
    return ResearchVehiclePublicEvent(
        schema_version=1,
        event_id=event_id,
        event_type="broadcast.boundary",
        occurred_at=occurred_at,
        broadcast_id=broadcast_id,
        programme_id=None,
        condition_id=None,
        source=PublicEventSource(
            producer="agents.broadcast_boundary_public_event_producer",
            substrate_id=cfg.source_substrate_id,
            task_anchor=cfg.task_anchor,
            evidence_ref=evidence_ref,
            freshness_ref="legacy_broadcast_event.age_s",
        ),
        salience=cfg.salience,
        state_kind="live_state",
        rights_class=cfg.rights_class,
        privacy_class=cfg.privacy_class,
        provenance=PublicEventProvenance(
            token=provenance_token,
            generated_at=generated_at,
            producer="agents.broadcast_boundary_public_event_producer",
            evidence_refs=_evidence_refs(blockers),
            rights_basis=cfg.rights_basis,
            citation_refs=[],
        ),
        public_url=incoming_url if surface_policy.claim_live else None,
        frame_ref=None,
        chapter_ref=PublicEventChapterRef(
            kind="chapter",
            label=chapter_label,
            timecode="00:00",
            source_event_id=event_id,
        ),
        attribution_refs=[],
        surface_policy=surface_policy,
    )


def broadcast_boundary_event_id(legacy_event: Mapping[str, Any]) -> str:
    """Stable idempotency key for a legacy broadcast boundary."""

    timestamp = _clean_optional_str(legacy_event.get("timestamp")) or "unknown_time"
    incoming_id = (
        _clean_optional_str(legacy_event.get("incoming_broadcast_id")) or "missing_incoming"
    )
    outgoing_id = (
        _clean_optional_str(legacy_event.get("outgoing_broadcast_id")) or "missing_outgoing"
    )
    digest = _clean_optional_str(legacy_event.get("seed_description_digest")) or "missing_digest"
    raw = f"rvpe:broadcast_boundary:{timestamp}:{incoming_id}:{outgoing_id}:{digest}"
    return _sanitize_event_id(raw)


def _policy_blockers(
    *,
    legacy_event: Mapping[str, Any],
    egress_state: LivestreamEgressState,
    quota_remaining: int,
    provenance_token: str | None,
    broadcast_id: str | None,
    source_age_s: float | None,
    policy: BroadcastBoundaryPolicyConfig,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if source_age_s is None or source_age_s > policy.freshness_ttl_s:
        blockers.append("source_stale")
    if not egress_state.public_claim_allowed:
        blockers.append("egress_blocked")
    if any(item.stale for item in egress_state.evidence):
        blockers.append("stale_egress")
    active_video_id = _active_video_id(egress_state)
    if not broadcast_id or not active_video_id:
        blockers.append("missing_active_video_id")
    elif active_video_id != broadcast_id:
        blockers.append("active_video_id_mismatch")
    if quota_remaining < policy.quota_min_remaining:
        blockers.append("quota_exhausted")
    if egress_state.audio_floor is not FloorState.SATISFIED:
        blockers.append("audio_blocked")
    if provenance_token is None:
        blockers.append("missing_provenance")
    if policy.rights_class not in _PUBLIC_SAFE_RIGHTS:
        blockers.append("rights_blocked")
    if policy.privacy_class not in _PUBLIC_SAFE_PRIVACY:
        blockers.append("privacy_blocked")
    if legacy_event.get("event_type") != LEGACY_EVENT_TYPE:
        blockers.append("wrong_source_event_type")
    return tuple(dict.fromkeys(blockers))


def _surface_policy(*, blockers: tuple[str, ...], claim_archive: bool) -> PublicEventSurfacePolicy:
    if blockers:
        return PublicEventSurfacePolicy(
            allowed_surfaces=[],
            denied_surfaces=[*_BROADCAST_BOUNDARY_SURFACES, *_NON_BOUNDARY_SURFACES],
            claim_live=False,
            claim_archive=False,
            claim_monetizable=False,
            requires_egress_public_claim=True,
            requires_audio_safe=True,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key="broadcast.boundary:live_state",
            redaction_policy="operator_referent",
            fallback_action="hold",
            dry_run_reason=";".join(blockers),
        )
    return PublicEventSurfacePolicy(
        allowed_surfaces=list(_BROADCAST_BOUNDARY_SURFACES),
        denied_surfaces=list(_NON_BOUNDARY_SURFACES),
        claim_live=True,
        claim_archive=claim_archive,
        claim_monetizable=False,
        requires_egress_public_claim=True,
        requires_audio_safe=True,
        requires_provenance=True,
        requires_human_review=False,
        rate_limit_key="broadcast.boundary:live_state",
        redaction_policy="operator_referent",
        fallback_action="hold",
        dry_run_reason=None,
    )


def _evidence_refs(blockers: tuple[str, ...]) -> list[str]:
    refs = [
        "legacy.broadcast_rotated",
        "LivestreamEgressState.public_claim_allowed",
        "ContentSubstrate.youtube_metadata",
        "BroadcastAudioSafety.audio_safe_for_broadcast",
        "YouTubeQuota.videos.update",
    ]
    refs.extend(f"blocker:{blocker}" for blocker in blockers)
    return refs


def _active_video_id(egress_state: LivestreamEgressState) -> str | None:
    for item in egress_state.evidence:
        if item.source != "active_video_id":
            continue
        raw = item.observed.get("video_id")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _provenance_token(legacy_event: Mapping[str, Any], event_id: str) -> str | None:
    digest = _clean_optional_str(legacy_event.get("seed_description_digest"))
    seed_title = _clean_optional_str(legacy_event.get("seed_title"))
    if not digest or not seed_title:
        return None
    return f"broadcast_boundary:{event_id}"


def _chapter_label(legacy_event: Mapping[str, Any]) -> str:
    title = _clean_optional_str(legacy_event.get("seed_title"))
    if title:
        return title
    return "Broadcast boundary"


def _load_event_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ids
    for raw in lines:
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and isinstance(item.get("event_id"), str):
            ids.add(item["event_id"])
    return ids


def _clean_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _normalise_iso(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _event_age_s(occurred_at: str, now: float) -> float | None:
    normalised = _normalise_iso(occurred_at)
    if normalised is None:
        return None
    text = normalised[:-1] + "+00:00" if normalised.endswith("Z") else normalised
    try:
        return max(0.0, now - datetime.fromisoformat(text).timestamp())
    except ValueError:
        return None


def _iso_from_epoch(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat().replace("+00:00", "Z")


def _sanitize_event_id(value: str) -> str:
    lowered = value.lower().replace("+00:00", "z")
    cleaned = re.sub(r"[^a-z0-9_:]+", "_", lowered)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_:")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"rvpe:{cleaned}"
    return cleaned


def _run_forever(producer: BroadcastBoundaryPublicEventProducer, tick_s: float) -> None:
    stop = False

    def _stop(*_args: object) -> None:
        nonlocal stop
        stop = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except ValueError:
            pass
    while not stop:
        producer.run_once()
        time.sleep(max(1.0, tick_s))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process one batch and exit")
    parser.add_argument("--legacy-event-path", type=Path, default=LEGACY_EVENT_PATH)
    parser.add_argument("--public-event-path", type=Path, default=PUBLIC_EVENT_PATH)
    parser.add_argument("--cursor-path", type=Path, default=CURSOR_PATH)
    parser.add_argument("--tick-s", type=float, default=DEFAULT_TICK_S)
    args = parser.parse_args(argv)

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    producer = BroadcastBoundaryPublicEventProducer(
        legacy_event_path=args.legacy_event_path,
        public_event_path=args.public_event_path,
        cursor_path=args.cursor_path,
    )
    if args.once:
        return 0 if producer.run_once() >= 0 else 1
    _run_forever(producer, args.tick_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BroadcastBoundaryPolicyConfig",
    "BroadcastBoundaryPublicEventProducer",
    "ByteCursorJsonlTailer",
    "build_broadcast_boundary_public_event",
    "broadcast_boundary_event_id",
    "main",
]
