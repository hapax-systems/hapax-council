"""Imagination daemon — independent stigmergic imagination loop.

Reads observations and sensor snapshot from /dev/shm traces published
by the DMN pulse daemon. Generates ImaginationFragment objects and
publishes them to /dev/shm/hapax-imagination/current.json.

Emits impingements for high-salience fragments to the cross-daemon
JSONL transport.

Usage:
    uv run python -m agents.imagination_daemon
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from pathlib import Path

from agents.imagination_loop import (
    ImaginationLoop,
    observations_are_fresh,
    should_accelerate_from_engagement,
)
from shared.control_signal import ControlSignal, publish_health
from shared.governance.consent_label import ConsentLabel
from shared.impingement import Impingement
from shared.labeled_trace import serialize_label

log = logging.getLogger("imagination-daemon")

OBSERVATIONS_PATH = Path("/dev/shm/hapax-dmn/observations.json")
SNAPSHOT_PATH = Path("/dev/shm/hapax-sensors/snapshot.json")
STIMMUNG_PATH = Path("/dev/shm/hapax-stimmung/state.json")
IMPINGEMENTS_FILE = Path("/dev/shm/hapax-dmn/impingements.jsonl")

OBSERVATION_STALE_S = 30.0
SNAPSHOT_STALE_S = 30.0


def read_observations(
    *, path: Path = OBSERVATIONS_PATH, stale_s: float = OBSERVATION_STALE_S
) -> list[str] | None:
    """Read observations from DMN pulse trace. Returns None if stale or missing."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        published_at = data.get("published_at", 0)
        if time.time() - published_at > stale_s:
            return None
        return data.get("observations", [])
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def read_snapshot(*, path: Path = SNAPSHOT_PATH, stale_s: float = SNAPSHOT_STALE_S) -> dict | None:
    """Read sensor snapshot from /dev/shm. Returns None if stale or missing."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        published_at = data.get("published_at", 0)
        if time.time() - published_at > stale_s:
            return None
        return data
    except (OSError, json.JSONDecodeError):
        return None


def _read_stimmung_stance() -> str:
    """Read current stimmung stance for cadence modulation."""
    try:
        data = json.loads(STIMMUNG_PATH.read_text(encoding="utf-8"))
        return data.get("stance", "nominal")
    except (OSError, json.JSONDecodeError):
        return "nominal"


def _emit_impingements(impingements: list[Impingement]) -> None:
    """Append impingements to cross-daemon JSONL transport."""
    if not impingements:
        return
    try:
        IMPINGEMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _consent_val = serialize_label(ConsentLabel.bottom())
        with IMPINGEMENTS_FILE.open("a", encoding="utf-8") as f:
            for imp in impingements:
                line_data = imp.model_dump()
                line_data.setdefault("context", {})["_consent"] = _consent_val
                f.write(json.dumps(line_data) + "\n")
    except OSError:
        log.warning("Failed to write impingements", exc_info=True)


class ImaginationDaemon:
    """Independent imagination loop daemon reading from /dev/shm traces."""

    def __init__(self) -> None:
        self._imagination = ImaginationLoop()
        self._running = True
        # Control law state (Property 4: closed-loop error → cadence)
        self._consecutive_errors: int = 0
        self._consecutive_ok: int = 0
        self._cadence_degraded: bool = False
        # Exploration signal tracking (spec §8, kappa=0.015, T_patience=240s)
        from shared.exploration_tracker import ExplorationTrackerBundle

        self._exploration = ExplorationTrackerBundle(
            component="dmn_imagination",
            edges=["observations", "stimmung_stance"],
            traces=["observation_content", "snapshot_activity"],
            neighbors=["dmn_pulse", "stimmung"],
            kappa=0.015,
            t_patience=240.0,
            sigma_explore=0.20,
        )
        self._prev_obs_count: int = 0
        self._prev_stance: str = "nominal"

    async def run(self) -> None:
        log.info("Imagination daemon starting")

        while self._running:
            try:
                observations = read_observations()
                snapshot = read_snapshot()

                if observations is not None and snapshot is not None:
                    # Skip tick if observations are stale relative to imagination cadence
                    try:
                        obs_raw = json.loads(OBSERVATIONS_PATH.read_text(encoding="utf-8"))
                        published_at = obs_raw.get("published_at", 0)
                        interval = self._imagination.cadence.current_interval()
                        if not observations_are_fresh(
                            published_at=published_at, cadence_s=interval
                        ):
                            log.debug("Skipping tick — observations stale relative to cadence")
                            publish_health(
                                ControlSignal(
                                    component="imagination", reference=1.0, perception=0.0
                                )
                            )
                            await asyncio.sleep(interval)
                            continue
                    except (OSError, json.JSONDecodeError):
                        pass

                    await self._imagination.tick(observations, snapshot)
                    publish_health(
                        ControlSignal(component="imagination", reference=1.0, perception=1.0)
                    )

                    # Positive feedback: high engagement → faster imagination
                    snapshot_perception = snapshot.get("perception", {})
                    if should_accelerate_from_engagement(snapshot_perception):
                        self._imagination.cadence._accelerated = True

                    # Exploration signal computation
                    obs_count = len(observations) if observations else 0
                    self._exploration.feed_habituation(
                        "observations", float(obs_count), float(self._prev_obs_count), 1.0
                    )
                    cur_stance = snapshot.get("stimmung", {}).get("overall_stance", "nominal")
                    self._exploration.feed_habituation(
                        "stimmung_stance",
                        float(cur_stance != self._prev_stance),
                        0.0,
                        0.5,
                    )
                    self._exploration.feed_interest("observation_content", float(obs_count), 1.0)
                    activity = snapshot.get("perception", {}).get("activity", "idle")
                    self._exploration.feed_interest(
                        "snapshot_activity", hash(activity) % 100 / 100.0, 0.3
                    )
                    self._exploration.feed_error(0.0 if observations else 1.0)
                    sig = self._exploration.compute_and_publish()
                    self._prev_obs_count = obs_count
                    self._prev_stance = cur_stance

                    # 15th control law: apply exploration action
                    action = self._exploration.evaluate_action(sig, sigma_explore=0.20)
                    if action.mode != "none":
                        log.debug(
                            "Exploration action: %s (boost=%s ×%.1f)",
                            action.mode,
                            action.gain_boost_edge,
                            action.gain_boost_factor,
                        )
                    # Tick rate modulation: directed exploration → faster cadence
                    if action.tick_rate_factor < 1.0:
                        self._imagination.cadence.force_accelerated(True)

                    # Drain and emit impingements
                    impingements = self._imagination.drain_impingements()
                    _emit_impingements(impingements)
                else:
                    log.debug(
                        "Skipping tick — observations=%s snapshot=%s",
                        "fresh" if observations is not None else "stale/missing",
                        "fresh" if snapshot is not None else "stale/missing",
                    )
                    publish_health(
                        ControlSignal(component="imagination", reference=1.0, perception=0.0)
                    )
            except Exception:
                log.warning("Imagination tick failed", exc_info=True)

            # Control law (Property 4): error drives cadence
            if observations is None or snapshot is None:
                self._consecutive_errors += 1
                self._consecutive_ok = 0
            else:
                self._consecutive_errors = 0
                self._consecutive_ok += 1

            if self._consecutive_errors >= 3 and not self._cadence_degraded:
                self._imagination.cadence._base_s *= 2.0
                self._cadence_degraded = True
                log.warning("Control law: degrading cadence after 3 consecutive errors")

            if self._consecutive_ok >= 3 and self._cadence_degraded:
                self._imagination.cadence._base_s /= 2.0
                self._cadence_degraded = False
                log.info("Control law: restoring cadence after 3 consecutive successes")

            interval = self._imagination.cadence.current_interval()

            # Stimmung modulation: double cadence when degraded, pause when critical
            stance = _read_stimmung_stance()
            self._imagination.cadence.set_seeking(stance == "seeking")
            if stance == "critical":
                interval = 60.0  # effectively pause
            elif stance == "degraded":
                interval *= 2.0

            await asyncio.sleep(interval)

        log.info("Imagination daemon stopped")

    def stop(self) -> None:
        self._running = False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    daemon = ImaginationDaemon()

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
