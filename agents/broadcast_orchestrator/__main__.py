"""Systemd entrypoint for the broadcast boundary orchestrator.

Type=notify daemon with a 5-minute internal tick. Watchdog kicks every
tick. Default DISABLED via ``HAPAX_BROADCAST_ORCHESTRATOR_ENABLED`` so
the unit can ship and remain dormant until the operator mints OAuth +
captures the stream id.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading

from shared.youtube_api_client import WRITE_SCOPES, YouTubeApiClient
from shared.youtube_rate_limiter import QuotaBucket

from .orchestrator import Orchestrator

log = logging.getLogger("agents.broadcast_orchestrator")

TICK_S = int(os.environ.get("HAPAX_BROADCAST_TICK_S", "300"))
METRICS_PORT = int(os.environ.get("HAPAX_BROADCAST_METRICS_PORT", "9488"))
ENABLED = os.environ.get("HAPAX_BROADCAST_ORCHESTRATOR_ENABLED", "0") == "1"


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def _sd_notify(state: str) -> None:
    """Best-effort sd_notify."""
    try:
        from sdnotify import SystemdNotifier

        SystemdNotifier().notify(state)
    except Exception:
        log.debug("sd_notify(%s) skipped", state)


def main() -> int:
    _setup_logging()

    if not ENABLED:
        log.warning(
            "HAPAX_BROADCAST_ORCHESTRATOR_ENABLED=0 — running in idle mode "
            "(sd_notify READY, no API calls). Set =1 + restart to activate."
        )
        _start_metrics_server()
        _sd_notify("READY=1")
        _idle_until_signal()
        return 0

    try:
        from prometheus_client import start_http_server

        start_http_server(METRICS_PORT, addr="127.0.0.1")
        log.info("prometheus metrics on 127.0.0.1:%d", METRICS_PORT)
    except Exception:
        log.warning("prometheus_client unavailable; metrics disabled", exc_info=True)

    bucket = QuotaBucket.default()
    client = YouTubeApiClient(scopes=WRITE_SCOPES, rate_limiter=bucket)
    orch = Orchestrator(client=client)

    _sd_notify("READY=1")
    log.info(
        "orchestrator armed: tick=%ds rotation=%ds privacy=%s stream_id_env=%s",
        TICK_S,
        orch._rotation_s,
        orch._privacy_status,
        os.environ.get("HAPAX_BROADCAST_STREAM_ID", ""),
    )

    stop = threading.Event()

    def _shutdown(signum: int, _frame: object) -> None:
        log.info("signal %d received; stopping after current tick", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while not stop.is_set():
        try:
            orch.run_once()
        except Exception:
            log.exception("orchestrator tick failed")
        _sd_notify("WATCHDOG=1")
        stop.wait(TICK_S)

    _sd_notify("STOPPING=1")
    log.info("orchestrator stopped")
    return 0


def _start_metrics_server() -> None:
    """Start the metrics HTTP server even in idle mode so observers can scrape."""
    try:
        from prometheus_client import start_http_server

        start_http_server(METRICS_PORT, addr="127.0.0.1")
    except Exception:
        log.debug("metrics server not started in idle mode", exc_info=True)


def _idle_until_signal() -> None:
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        _sd_notify("WATCHDOG=1")
        stop.wait(60)


if __name__ == "__main__":
    sys.exit(main())
