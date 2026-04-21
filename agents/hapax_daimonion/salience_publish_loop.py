"""Periodic salience-router exploration-signal republish.

The SalienceRouter publishes its exploration signal only when ``route()``
fires — i.e., per operator utterance. During quiet operator periods
(no speech for hours), the writer goes silent and the health monitor
flags ``exploration_salience_router`` as ``Writer dead`` indefinitely.
Live regression observed 2026-04-21: writer last fresh at 23:33 the
prior day, dead for 13+ hours.

Same shape as the apperception writer fix (PR #1118): add a periodic
republish so the writer stays alive even with no inputs. The
republish carries the LAST KNOWN state — semantically "router is
alive, here's its current view" rather than fresh data. That's what
the health monitor's `Writer fresh (Ns)` semantics actually want.

Cadence: 30 s. Faster wastes work; slower lets the health monitor's
120 s STALE_THRESHOLD_S trip during a single missed publish.

When SalienceRouter isn't initialized (heuristic-routing fallback per
``init_audio.py``), the loop quietly waits — there's nothing to
republish but the loop itself stays alive, ready for hot-init.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger(__name__)

SALIENCE_PUBLISH_INTERVAL_S = 30.0


async def salience_publish_loop(daemon: VoiceDaemon) -> None:
    """Republish salience-router exploration signal at SALIENCE_PUBLISH_INTERVAL_S
    cadence. Skips when the router isn't initialized.

    Errors are logged at debug and never propagate — a publish failure
    must not take the daemon down.
    """
    log.info(
        "salience_publish_loop starting (interval %.1fs)",
        SALIENCE_PUBLISH_INTERVAL_S,
    )
    while daemon._running:
        router = getattr(daemon, "_salience_router", None)
        if router is not None:
            tracker = getattr(router, "_exploration", None)
            if tracker is not None:
                try:
                    tracker.compute_and_publish()
                except Exception:
                    log.debug(
                        "salience_router exploration publish failed",
                        exc_info=True,
                    )
        await asyncio.sleep(SALIENCE_PUBLISH_INTERVAL_S)


__all__ = [
    "SALIENCE_PUBLISH_INTERVAL_S",
    "salience_publish_loop",
]
