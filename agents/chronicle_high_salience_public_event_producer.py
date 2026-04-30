"""Produce canonical public events from chronicle high-salience observations.

This producer tails the chronicle stream with its own byte-offset cursor. It
does not share the thumbnail rotator cursor, does not publish to public
surfaces, and does not grant public/live/monetization authority. It writes
policy-bearing ``ResearchVehiclePublicEvent`` JSONL records for downstream
adapters to evaluate.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.livestream_egress_state import (
    LivestreamEgressState,
    resolve_livestream_egress_state,
)
from shared.research_vehicle_public_event import ResearchVehiclePublicEvent
from shared.research_vehicle_public_event_chronicle import (
    ChroniclePublicEventPolicyConfig,
    build_chronicle_public_event,
    is_chronicle_public_event_candidate,
)

log = logging.getLogger(__name__)

CHRONICLE_EVENTS_PATH = Path(
    os.environ.get("HAPAX_CHRONICLE_EVENTS_PATH", "/dev/shm/hapax-chronicle/events.jsonl")
)
PUBLIC_EVENT_PATH = Path(
    os.environ.get(
        "HAPAX_RESEARCH_VEHICLE_PUBLIC_EVENT_PATH",
        "/dev/shm/hapax-public-events/events.jsonl",
    )
)
CURSOR_PATH = Path(
    os.environ.get(
        "HAPAX_CHRONICLE_PUBLIC_EVENT_CURSOR",
        str(Path.home() / ".cache/hapax/chronicle-high-salience-public-event-cursor.txt"),
    )
)
DEFAULT_TICK_S = float(os.environ.get("HAPAX_CHRONICLE_PUBLIC_EVENT_TICK_S", "30"))

EgressResolver = Callable[[], LivestreamEgressState]
TimeFn = Callable[[], float]


@dataclass(frozen=True)
class _TailRecord:
    byte_start: int
    byte_after: int
    event: dict[str, Any] | None
    error: str | None = None


class ChronicleJsonlTailer:
    """Byte-offset chronicle JSONL tailer with truncation recovery."""

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
            log.warning("chronicle event file shrank from cursor %d to %d bytes", cursor, size)
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
            log.warning("chronicle read failed at %s", self._path, exc_info=True)


class ChronicleHighSaliencePublicEventProducer:
    """Tail chronicle observations and emit canonical RVPE rows."""

    def __init__(
        self,
        *,
        chronicle_event_path: Path = CHRONICLE_EVENTS_PATH,
        public_event_path: Path = PUBLIC_EVENT_PATH,
        cursor_path: Path = CURSOR_PATH,
        policy: ChroniclePublicEventPolicyConfig | None = None,
        egress_resolver: EgressResolver | None = None,
        time_fn: TimeFn = time.time,
    ) -> None:
        self._chronicle_event_path = chronicle_event_path
        self._public_event_path = public_event_path
        self._policy = policy or ChroniclePublicEventPolicyConfig()
        self._egress_resolver = egress_resolver or resolve_livestream_egress_state
        self._time = time_fn
        self._tailer = ChronicleJsonlTailer(chronicle_event_path, cursor_path)
        self._known_event_ids: set[str] | None = None

    def run_once(self) -> int:
        """Process one chronicle batch and return written public-event count."""

        written = 0
        for record in self._tailer.iter_new():
            if record.event is None:
                if record.error:
                    log.warning(
                        "skipping malformed chronicle event at byte %d: %s",
                        record.byte_start,
                        record.error,
                    )
                self._tailer.write_cursor(record.byte_after)
                continue

            if not is_chronicle_public_event_candidate(record.event, policy=self._policy):
                self._tailer.write_cursor(record.byte_after)
                continue

            decision = build_chronicle_public_event(
                record.event,
                evidence_ref=f"{self._chronicle_event_path}#byte={record.byte_start}",
                egress_state=self._egress_resolver(),
                generated_at=_iso_from_epoch(self._time()),
                now=self._time(),
                policy=self._policy,
            )
            event = decision.public_event
            if event is None:
                self._tailer.write_cursor(record.byte_after)
                continue
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
        if isinstance(item, Mapping) and isinstance(item.get("event_id"), str):
            ids.add(item["event_id"])
    return ids


def _iso_from_epoch(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat().replace("+00:00", "Z")


def _run_forever(producer: ChronicleHighSaliencePublicEventProducer, tick_s: float) -> None:
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
    parser.add_argument("--chronicle-event-path", type=Path, default=CHRONICLE_EVENTS_PATH)
    parser.add_argument("--public-event-path", type=Path, default=PUBLIC_EVENT_PATH)
    parser.add_argument("--cursor-path", type=Path, default=CURSOR_PATH)
    parser.add_argument("--tick-s", type=float, default=DEFAULT_TICK_S)
    args = parser.parse_args(argv)

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    producer = ChronicleHighSaliencePublicEventProducer(
        chronicle_event_path=args.chronicle_event_path,
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
    "CHRONICLE_EVENTS_PATH",
    "CURSOR_PATH",
    "PUBLIC_EVENT_PATH",
    "ChronicleHighSaliencePublicEventProducer",
    "ChronicleJsonlTailer",
    "main",
]
