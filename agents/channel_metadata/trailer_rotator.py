"""Channel trailer rotator (ytb-011 Phase 1).

Subscribes to ``broadcast_rotated`` events on the broadcast-orchestrator
JSONL bus and calls
``channels.update(brandingSettings.channel.unsubscribedTrailer = incoming_broadcast_id)``
once per rotation. Walks
``axioms/contracts/publication/channel-trailer.yaml`` allowlist before
each API call (default DENY; contract already exists).

## Cadence

Per VOD boundary (~11 hours). Rate limit per the contract: 2/hour,
6/day — the orchestrator's ~11h cadence is well within these.

## Cursor

Persistent cursor at
``$XDG_CACHE_HOME/hapax/channel-trailer-cursor.txt`` so a daemon
restart resumes from the last-applied event rather than re-applying
the rotation that already happened.

## Failure mode

API failures (quota / network / disabled client) increment the
``error`` counter and emit a Prometheus warning. The loop never
raises; the next event will retry the trailer update on the next
rotation. We do NOT retry mid-rotation: at most one trailer update
per ``broadcast_rotated`` event.

## Dry-run

Default ``--dry-run`` mode prints what would be POSTed without
calling the API. ``--once`` consumes one event then exits (test +
operator-debugging). The systemd unit runs without flags →
production-mode subscriber loop.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal as _signal
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

from prometheus_client import REGISTRY, CollectorRegistry, Counter, start_http_server

from shared.governance.publication_allowlist import check as allowlist_check

log = logging.getLogger(__name__)

EVENT_PATH = Path(
    os.environ.get("HAPAX_BROADCAST_EVENT_PATH", "/dev/shm/hapax-broadcast/events.jsonl")
)
DEFAULT_CURSOR_PATH = Path(
    os.environ.get(
        "HAPAX_CHANNEL_TRAILER_CURSOR",
        str(Path.home() / ".cache/hapax/channel-trailer-cursor.txt"),
    )
)
METRICS_PORT: int = int(os.environ.get("HAPAX_CHANNEL_TRAILER_METRICS_PORT", "9499"))
DEFAULT_TICK_S: float = float(os.environ.get("HAPAX_CHANNEL_TRAILER_TICK_S", "30"))

ALLOWLIST_SURFACE = "channel-trailer"
ALLOWLIST_STATE_KIND = "broadcast.current_live_url"
EVENT_TYPE = "broadcast_rotated"
QUOTA_COST_HINT = 50  # channels.update part=brandingSettings


class TrailerRotator:
    """Tail the broadcast-events bus and update the channel trailer."""

    def __init__(
        self,
        *,
        client,
        event_path: Path = EVENT_PATH,
        cursor_path: Path = DEFAULT_CURSOR_PATH,
        registry: CollectorRegistry = REGISTRY,
        tick_s: float = DEFAULT_TICK_S,
        dry_run: bool = False,
    ) -> None:
        self._client = client
        self._event_path = event_path
        self._cursor_path = cursor_path
        self._tick_s = max(1.0, tick_s)
        self._dry_run = dry_run
        self._stop_evt = threading.Event()

        self.rotations_total = Counter(
            "hapax_broadcast_channel_trailer_rotations_total",
            "Channel trailer rotations attempted, broken down by outcome.",
            ["result"],
            registry=registry,
        )

    # ── Public API ────────────────────────────────────────────────────

    def run_once(self) -> int:
        """Process all pending events at the cursor; return count handled."""
        cursor = self._read_cursor()
        handled = 0
        for event, byte_after in self._tail_from(cursor):
            if event.get("event_type") != EVENT_TYPE:
                cursor = byte_after
                continue
            self._apply(event)
            cursor = byte_after
            handled += 1
        if handled:
            self._write_cursor(cursor)
        return handled

    def run_forever(self) -> None:
        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, lambda *_: self._stop_evt.set())
            except ValueError:
                pass

        log.info(
            "channel trailer rotator starting, port=%d tick=%.1fs dry_run=%s",
            METRICS_PORT,
            self._tick_s,
            self._dry_run,
        )
        while not self._stop_evt.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("trailer tick failed; continuing on next cadence")
            self._stop_evt.wait(self._tick_s)

    def stop(self) -> None:
        self._stop_evt.set()

    # ── Cursor + tail ─────────────────────────────────────────────────

    def _read_cursor(self) -> int:
        try:
            return int(self._cursor_path.read_text().strip())
        except (FileNotFoundError, ValueError):
            return 0

    def _write_cursor(self, byte_offset: int) -> None:
        try:
            self._cursor_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cursor_path.with_suffix(".tmp")
            tmp.write_text(str(byte_offset))
            tmp.replace(self._cursor_path)
        except OSError:
            log.warning("cursor write failed at %s", self._cursor_path, exc_info=True)

    def _tail_from(self, byte_offset: int) -> Iterator[tuple[dict, int]]:
        """Yield (event_dict, byte_after) for each line past byte_offset."""
        if not self._event_path.exists():
            return
        try:
            with self._event_path.open("rb") as fh:
                fh.seek(byte_offset)
                while True:
                    line = fh.readline()
                    if not line:
                        return
                    new_offset = fh.tell()
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    try:
                        event = json.loads(text)
                    except json.JSONDecodeError:
                        log.warning("malformed event line at offset %d", byte_offset)
                        continue
                    yield event, new_offset
                    byte_offset = new_offset
        except OSError:
            log.warning("event file read failed at %s", self._event_path, exc_info=True)

    # ── Per-event apply ───────────────────────────────────────────────

    def _apply(self, event: dict) -> None:
        incoming = event.get("incoming_broadcast_id")
        if not incoming:
            log.info("broadcast_rotated missing incoming_broadcast_id; skipping")
            self.rotations_total.labels(result="skipped").inc()
            return

        verdict = allowlist_check(
            ALLOWLIST_SURFACE,
            ALLOWLIST_STATE_KIND,
            {"broadcast_id": incoming},
        )
        if verdict.decision == "deny":
            log.warning("allowlist DENY for trailer rotation: %s", verdict.reason)
            self.rotations_total.labels(result="denied").inc()
            return

        if self._dry_run:
            log.info("DRY RUN — would set channel trailer to broadcast_id=%s", incoming)
            self.rotations_total.labels(result="dry_run").inc()
            return

        result = self._call_channels_update(incoming)
        self.rotations_total.labels(result=result).inc()

    def _call_channels_update(self, broadcast_id: str) -> str:
        """Build + execute the channels.update request. Returns result label."""
        if not getattr(self._client, "enabled", True):
            log.warning("youtube client disabled; skipping channels.update")
            return "client_disabled"

        try:
            request = self._client.yt.channels().update(
                part="brandingSettings",
                body={
                    "id": _channel_id_from_env(),
                    "brandingSettings": {"channel": {"unsubscribedTrailer": broadcast_id}},
                },
            )
            response = self._client.execute(
                request,
                endpoint="channels.update.brandingSettings",
                quota_cost_hint=QUOTA_COST_HINT,
            )
        except Exception:  # noqa: BLE001
            log.exception("channels.update failed for broadcast_id=%s", broadcast_id)
            return "error"
        if response is None:
            return "error"
        log.info("channel trailer set to broadcast_id=%s", broadcast_id)
        return "ok"


def _channel_id_from_env() -> str:
    cid = os.environ.get("YOUTUBE_CHANNEL_ID", "").strip()
    if not cid:
        raise RuntimeError(
            "YOUTUBE_CHANNEL_ID not set — hapax-secrets must export it before "
            "hapax-channel-trailer.service starts"
        )
    return cid


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agents.channel_metadata.trailer_rotator",
        description="Tail broadcast events and rotate channel trailer.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="log what would be sent without calling the API",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="process pending events then exit (default: daemon loop)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv)

    from shared.youtube_api_client import WRITE_SCOPES, YouTubeApiClient

    # `channels.update brandingSettings.channel.unsubscribedTrailer` requires
    # the youtube.force-ssl scope — see shared/youtube_api_client.py + the
    # bootstrap recipe in systemd/units/hapax-channel-trailer.service.
    # YouTubeApiClient.__init__ logs "client DISABLED" + sets _yt=None when
    # credentials are absent (credential_blocked operating mode), which the
    # rotator's _call_channels_update gates on via getattr(client, 'enabled').
    client = YouTubeApiClient(scopes=WRITE_SCOPES)
    rotator = TrailerRotator(client=client, dry_run=args.dry_run)

    if args.once:
        handled = rotator.run_once()
        log.info("processed %d event(s)", handled)
        return 0

    start_http_server(METRICS_PORT, addr="127.0.0.1")
    rotator.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
