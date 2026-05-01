"""CLI entry: ``uv run python -m agents.broadcast_audio_health_producer``.

Configured routes come from ``BROADCAST_AUDIO_HEALTH_ROUTES`` per
:func:`load_routes_from_env`. The systemd unit sets that env var.
Exits non-zero (1) if no routes are configured so a misconfigured
deploy fails loudly rather than silently no-op'ing.
"""

from __future__ import annotations

import logging
import sys

from .producer import BroadcastAudioHealthProducer, load_routes_from_env

log = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    routes = load_routes_from_env()
    if not routes:
        log.error("no routes configured; set BROADCAST_AUDIO_HEALTH_ROUTES")
        return 1
    producer = BroadcastAudioHealthProducer(routes=routes)
    results = producer.run_once()
    for r in results:
        log.info("route=%s outcome=%s", r.name, r.outcome.value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
