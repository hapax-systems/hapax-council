"""Systemd entrypoint + ``--once`` CLI for live cuepoint emission.

Two modes:

* **Daemon (default):** ``Type=notify`` long-running; tails the broadcast
  events jsonl and emits cuepoints at segment boundaries.
* **One-shot (``--once``):** manual single-cuepoint emission for beta's
  empirical verification (spec §R3 + ytb-004 impl notes). Either
  ``--broadcast-id <id>`` explicitly, or omit to pick the most recent
  rotation from the events file.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading

from shared.youtube_api_client import WRITE_SCOPES, YouTubeApiClient
from shared.youtube_rate_limiter import QuotaBucket

from .api import emit_cuepoint
from .consumer import CuepointConsumer, iter_events

log = logging.getLogger("agents.live_cuepoints")

TICK_S = int(os.environ.get("HAPAX_CUEPOINT_TICK_S", "15"))
METRICS_PORT = int(os.environ.get("HAPAX_CUEPOINT_METRICS_PORT", "9494"))
ENABLED = os.environ.get("HAPAX_LIVE_CUEPOINTS_ENABLED", "0") == "1"


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def _sd_notify(state: str) -> None:
    try:
        from sdnotify import SystemdNotifier

        SystemdNotifier().notify(state)
    except Exception:
        log.debug("sd_notify(%s) skipped", state)


def _start_metrics_server() -> None:
    try:
        from prometheus_client import start_http_server

        start_http_server(METRICS_PORT, addr="127.0.0.1")
        log.info("prometheus metrics on 127.0.0.1:%d", METRICS_PORT)
    except Exception:
        log.debug("metrics server not started", exc_info=True)


def _run_once(args: argparse.Namespace) -> int:
    """Single-cuepoint CLI. Returns exit code."""
    _setup_logging()
    client = YouTubeApiClient(scopes=WRITE_SCOPES)
    if not client.enabled:
        log.error("client disabled — no OAuth token. Run scripts/mint-google-token.py first.")
        return 2

    broadcast_id = args.broadcast_id
    if not broadcast_id:
        latest = None
        for event in iter_events():
            if event.get("event_type") == "broadcast_rotated":
                latest = event
        if latest is None:
            log.error(
                "no broadcast_rotated events found at %s; supply --broadcast-id",
                os.environ.get(
                    "HAPAX_BROADCAST_EVENT_PATH", "/dev/shm/hapax-broadcast/events.jsonl"
                ),
            )
            return 3
        broadcast_id = latest.get("incoming_broadcast_id")
        log.info("using most-recent rotation's incoming broadcast: %s", broadcast_id)

    if not broadcast_id:
        log.error("no broadcast id resolved")
        return 3

    resp = emit_cuepoint(
        client,
        broadcast_id=broadcast_id,
        duration_secs=args.duration,
        cue_type=args.cue_type,
    )
    if resp is None:
        log.error("cuepoint emit returned None (skipped or silent-fail)")
        return 4
    log.info("cuepoint emit ok: %s", resp)
    return 0


def _run_daemon() -> int:
    _setup_logging()

    if not ENABLED:
        log.warning(
            "HAPAX_LIVE_CUEPOINTS_ENABLED=0 — running in idle mode "
            "(sd_notify READY, no API calls). Set =1 after empirical verify "
            "passes, then restart."
        )
        _start_metrics_server()
        _sd_notify("READY=1")
        _idle_until_signal()
        return 0

    _start_metrics_server()
    bucket = QuotaBucket.default()
    client = YouTubeApiClient(scopes=WRITE_SCOPES, rate_limiter=bucket)
    consumer = CuepointConsumer(client)

    _sd_notify("READY=1")
    log.info("live-cuepoints daemon armed: tick=%ds metrics=:%d", TICK_S, METRICS_PORT)

    stop = threading.Event()

    def _shutdown(signum: int, _frame: object) -> None:
        log.info("signal %d received; stopping", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while not stop.is_set():
        try:
            emitted = consumer.poll_once()
            if emitted:
                log.info("tick: %d cuepoints emitted", emitted)
        except Exception:
            log.exception("cuepoint consumer tick failed")
        _sd_notify("WATCHDOG=1")
        stop.wait(TICK_S)

    _sd_notify("STOPPING=1")
    return 0


def _idle_until_signal() -> None:
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        _sd_notify("WATCHDOG=1")
        stop.wait(60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agents.live_cuepoints",
        description="Live cuepoint chapter markers (ytb-004)",
    )
    parser.add_argument("--once", action="store_true", help="single-cuepoint CLI mode")
    parser.add_argument(
        "--broadcast-id",
        help="broadcast id for --once mode; defaults to latest rotation",
    )
    parser.add_argument("--duration", type=int, default=0, help="cuepoint duration seconds")
    parser.add_argument(
        "--cue-type",
        default="cueTypeAd",
        help="cueType field (cueTypeAd is documented; cueTypeBreak is the fallback)",
    )
    args = parser.parse_args(argv)

    if args.once:
        return _run_once(args)
    return _run_daemon()


if __name__ == "__main__":
    sys.exit(main())
