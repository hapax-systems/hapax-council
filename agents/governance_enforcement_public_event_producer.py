"""Produce canonical public events from governance enforcement records.

When axiom hooks block a commit, push, or file write, they append a record
to ``/dev/shm/hapax-governance/enforcement.jsonl``.  This producer tails
that bus and writes ``ResearchVehiclePublicEvent`` records to the shared
public-event stream so downstream consumers (health dashboards, archive)
can observe governance activity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import signal
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.research_vehicle_public_event import (
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
    Surface,
)

log = logging.getLogger(__name__)

ENFORCEMENT_EVENT_PATH = Path(
    os.environ.get(
        "HAPAX_GOVERNANCE_ENFORCEMENT_PATH",
        "/dev/shm/hapax-governance/enforcement.jsonl",
    )
)
PUBLIC_EVENT_PATH = Path(
    os.environ.get(
        "HAPAX_RESEARCH_VEHICLE_PUBLIC_EVENT_PATH",
        "/dev/shm/hapax-public-events/events.jsonl",
    )
)
CURSOR_PATH = Path(
    os.environ.get(
        "HAPAX_GOVERNANCE_ENFORCEMENT_CURSOR",
        str(Path.home() / ".cache/hapax/governance-enforcement-cursor.txt"),
    )
)
DEFAULT_TICK_S = float(os.environ.get("HAPAX_GOVERNANCE_ENFORCEMENT_TICK_S", "30"))
TASK_ANCHOR = "governance-enforcement-public-event-producer"
PRODUCER_NAME = "agents.governance_enforcement_public_event_producer"
SOURCE_EVENT_TYPE = "axiom_blocked"

_ALLOWED_SURFACES: tuple[Surface, ...] = ("health", "archive")
_DENIED_SURFACES: tuple[Surface, ...] = (
    "youtube_description",
    "youtube_chapters",
    "youtube_cuepoints",
    "youtube_captions",
    "youtube_shorts",
    "youtube_channel_sections",
    "arena",
    "omg_statuslog",
    "omg_weblog",
    "omg_now",
    "mastodon",
    "bluesky",
    "discord",
    "replay",
    "captions",
    "cuepoints",
    "monetization",
)


@dataclass(frozen=True)
class _TailRecord:
    byte_start: int
    byte_after: int
    event: dict[str, Any] | None
    error: str | None = None


class ByteCursorJsonlTailer:
    """Byte-offset JSONL tailer with cursor-reset on file shrink."""

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
            log.warning("enforcement file shrank from cursor %d to %d bytes", cursor, size)
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
            log.warning("enforcement event read failed at %s", self._path, exc_info=True)


class GovernanceEnforcementPublicEventProducer:
    """Tail governance enforcement records and emit canonical RVPE records."""

    def __init__(
        self,
        *,
        enforcement_path: Path = ENFORCEMENT_EVENT_PATH,
        public_event_path: Path = PUBLIC_EVENT_PATH,
        cursor_path: Path = CURSOR_PATH,
    ) -> None:
        self._enforcement_path = enforcement_path
        self._public_event_path = public_event_path
        self._tailer = ByteCursorJsonlTailer(enforcement_path, cursor_path)
        self._known_event_ids: set[str] | None = None

    def run_once(self) -> int:
        written = 0
        for record in self._tailer.iter_new():
            if record.event is None:
                if record.error:
                    log.warning(
                        "skipping malformed enforcement record at byte %d: %s",
                        record.byte_start,
                        record.error,
                    )
                self._tailer.write_cursor(record.byte_after)
                continue

            if record.event.get("event_type") != SOURCE_EVENT_TYPE:
                self._tailer.write_cursor(record.byte_after)
                continue

            event = build_governance_enforcement_event(
                record.event,
                evidence_ref=f"{self._enforcement_path}#byte={record.byte_start}",
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


def build_governance_enforcement_event(
    enforcement_record: dict[str, Any],
    *,
    evidence_ref: str,
) -> ResearchVehiclePublicEvent:
    """Map an axiom enforcement record to ``governance.enforcement``."""
    event_id = governance_enforcement_event_id(enforcement_record)
    timestamp = enforcement_record.get("timestamp") or _now_iso()
    occurred_at = _normalise_iso(timestamp) or _now_iso()
    generated_at = _now_iso()

    hook = enforcement_record.get("hook", "unknown")
    domain = enforcement_record.get("domain", "unknown")
    matched = enforcement_record.get("matched", "")
    file_path = enforcement_record.get("file_path", "unknown")
    tool = enforcement_record.get("tool", "unknown")

    return ResearchVehiclePublicEvent(
        schema_version=1,
        event_id=event_id,
        event_type="governance.enforcement",
        occurred_at=occurred_at,
        broadcast_id=None,
        programme_id=None,
        condition_id=None,
        source=PublicEventSource(
            producer=PRODUCER_NAME,
            substrate_id="governance_axiom",
            task_anchor=TASK_ANCHOR,
            evidence_ref=evidence_ref,
            freshness_ref=None,
        ),
        salience=0.85,
        state_kind="governance_state",
        rights_class="operator_original",
        privacy_class="public_safe",
        provenance=PublicEventProvenance(
            token=f"governance_enforcement:{event_id}",
            generated_at=generated_at,
            producer=PRODUCER_NAME,
            evidence_refs=[
                f"hook:{hook}",
                f"domain:{domain}",
                f"tool:{tool}",
                f"file:{file_path}",
                f"matched:{matched[:80]}",
            ],
            rights_basis="operator governance enforcement audit trail",
            citation_refs=[],
        ),
        public_url=None,
        frame_ref=None,
        chapter_ref=None,
        attribution_refs=[],
        surface_policy=PublicEventSurfacePolicy(
            allowed_surfaces=list(_ALLOWED_SURFACES),
            denied_surfaces=list(_DENIED_SURFACES),
            claim_live=False,
            claim_archive=True,
            claim_monetizable=False,
            requires_egress_public_claim=False,
            requires_audio_safe=False,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key="governance.enforcement:governance_state",
            redaction_policy="none",
            fallback_action="archive_only",
            dry_run_reason=None,
        ),
    )


def governance_enforcement_event_id(enforcement_record: dict[str, Any]) -> str:
    """Stable idempotency key from enforcement record content."""
    timestamp = enforcement_record.get("timestamp", "unknown_time")
    hook = enforcement_record.get("hook", "unknown")
    domain = enforcement_record.get("domain", "unknown")
    matched = enforcement_record.get("matched", "")
    digest = hashlib.sha256(matched.encode("utf-8")).hexdigest()[:12]
    raw = f"rvpe:governance_enforcement:{timestamp}:{hook}:{domain}:{digest}"
    return _sanitize_event_id(raw)


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


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


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


def _sanitize_event_id(value: str) -> str:
    lowered = value.lower().replace("+00:00", "z")
    cleaned = re.sub(r"[^a-z0-9_:]+", "_", lowered)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_:")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"rvpe:{cleaned}"
    return cleaned


def _run_forever(producer: GovernanceEnforcementPublicEventProducer, tick_s: float) -> None:
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
    parser.add_argument("--enforcement-path", type=Path, default=ENFORCEMENT_EVENT_PATH)
    parser.add_argument("--public-event-path", type=Path, default=PUBLIC_EVENT_PATH)
    parser.add_argument("--cursor-path", type=Path, default=CURSOR_PATH)
    parser.add_argument("--tick-s", type=float, default=DEFAULT_TICK_S)
    args = parser.parse_args(argv)

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    producer = GovernanceEnforcementPublicEventProducer(
        enforcement_path=args.enforcement_path,
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
    "ByteCursorJsonlTailer",
    "GovernanceEnforcementPublicEventProducer",
    "build_governance_enforcement_event",
    "governance_enforcement_event_id",
    "main",
]
