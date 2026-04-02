"""Content resolver daemon — resolves slow imagination content references.

Watches /dev/shm/hapax-imagination/current.json for new fragments.
Resolves slow content types (text, qdrant_query, url) to JPEG files.
Writes resolved content to /dev/shm/hapax-imagination/content/active/.

Usage:
    uv run python -m agents.content_resolver
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from pathlib import Path

from agents.imagination import CURRENT_PATH, ImaginationFragment
from agents.imagination_resolver import CONTENT_DIR
from shared.control_signal import ControlSignal, publish_health

log = logging.getLogger("content-resolver")

POLL_INTERVAL_S = 0.5
MAX_FAILURES_PER_FRAGMENT = 5
SKIP_DURATION_S = 60.0


def check_for_new_fragment(
    last_id: str, *, path: Path = CURRENT_PATH
) -> tuple[str | None, dict | None]:
    """Check for a new imagination fragment. Returns (id, data) or (None, None)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        frag_id = data.get("id", "")
        if frag_id and frag_id != last_id:
            return frag_id, data
        return None, None
    except (OSError, json.JSONDecodeError):
        return None, None


class ContentResolverDaemon:
    """Watches for new imagination fragments and resolves slow content."""

    def __init__(self) -> None:
        self._running = True
        self._failures: dict[str, int] = {}
        self._skip_until: dict[str, float] = {}
        self._last_fragment_id = ""
        # Control law state
        self._cl_errors = 0
        self._cl_ok = 0
        self._cl_degraded = False
        self._cl_original_poll = POLL_INTERVAL_S
        # Exploration tracking (spec §8: kappa=0.010, T_patience=300s)
        from shared.exploration_tracker import ExplorationTrackerBundle

        self._exploration = ExplorationTrackerBundle(
            component="content_resolver",
            edges=["fragment_novelty", "resolution_success"],
            traces=["fragment_stream", "failure_rate"],
            neighbors=["imagination", "stimmung"],
            kappa=0.010,
            t_patience=300.0,
            sigma_explore=0.08,
        )
        self._prev_fragment_hash: float = 0.0

    async def run(self) -> None:
        log.info("Content resolver daemon starting")
        CONTENT_DIR.mkdir(parents=True, exist_ok=True)

        while self._running:
            try:
                frag_id, data = check_for_new_fragment(self._last_fragment_id)
                if frag_id is not None and data is not None:
                    skip_until = self._skip_until.get(frag_id)
                    if skip_until and time.time() < skip_until:
                        pass
                    else:
                        if skip_until:
                            del self._skip_until[frag_id]
                        self._last_fragment_id = frag_id
                        try:
                            ImaginationFragment.model_validate(data)
                            # ImaginationFragment no longer carries content_references.
                            # The resolver only acts when external refs are provided;
                            # skip resolution and just publish health.
                            self._failures.pop(frag_id, None)
                            log.debug("Fragment %s has no content to resolve, skipping", frag_id)
                            publish_health(
                                ControlSignal(
                                    component="content_resolver", reference=1.0, perception=1.0
                                )
                            )
                            # Control law: success
                            self._cl_errors = 0
                            self._cl_ok += 1
                        except Exception:
                            count = self._failures.get(frag_id, 0) + 1
                            self._failures[frag_id] = count
                            if count >= MAX_FAILURES_PER_FRAGMENT:
                                self._skip_until[frag_id] = time.time() + SKIP_DURATION_S
                                log.warning(
                                    "Skipping fragment %s after %d failures", frag_id, count
                                )
                            else:
                                log.debug(
                                    "Resolver failed for %s (%d/%d)",
                                    frag_id,
                                    count,
                                    MAX_FAILURES_PER_FRAGMENT,
                                )
                            publish_health(
                                ControlSignal(
                                    component="content_resolver", reference=1.0, perception=0.0
                                )
                            )
                            # Control law: error drives behavior
                            self._cl_errors += 1
                            self._cl_ok = 0
            except Exception:
                log.warning("Resolver tick failed", exc_info=True)

            # Control law: degrade/recover polling interval
            if self._cl_errors >= 3 and not self._cl_degraded:
                global POLL_INTERVAL_S
                self._cl_original_poll = POLL_INTERVAL_S
                POLL_INTERVAL_S = POLL_INTERVAL_S * 2.0
                self._cl_degraded = True
                log.warning("Control law [content_resolver]: degrading — doubling poll interval")

            if self._cl_ok >= 5 and self._cl_degraded:
                POLL_INTERVAL_S = self._cl_original_poll
                self._cl_degraded = False
                log.info("Control law [content_resolver]: recovered")

            # Exploration signal
            frag_hash = hash(self._last_fragment_id) % 100 / 100.0
            self._exploration.feed_habituation(
                "fragment_novelty", frag_hash, self._prev_fragment_hash, 0.3
            )
            success = 1.0 if self._cl_ok > 0 else 0.0
            self._exploration.feed_habituation("resolution_success", success, 0.0, 0.3)
            self._exploration.feed_interest("fragment_stream", frag_hash, 0.3)
            fail_rate = len(self._failures) / max(1, len(self._failures) + self._cl_ok)
            self._exploration.feed_interest("failure_rate", fail_rate, 0.2)
            self._exploration.feed_error(fail_rate)
            self._exploration.compute_and_publish()
            self._prev_fragment_hash = frag_hash

            await asyncio.sleep(POLL_INTERVAL_S)

        log.info("Content resolver daemon stopped")

    def stop(self) -> None:
        self._running = False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    daemon = ContentResolverDaemon()

    loop = asyncio.new_event_loop()

    def _handle_signal(sig: int, frame: object) -> None:
        daemon.stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        loop.run_until_complete(daemon.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
