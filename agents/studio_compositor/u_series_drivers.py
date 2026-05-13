"""U-series consumer drivers (cc-task u4-micromove-advance-tick-consumer
+ u5-verb-prometheus-counter Phase 1 wiring).

The U4 (micromove) and U5 (semantic verb) consumers shipped with their
Prometheus counters in PRs #2368/#2371, but no driver invokes them in
production — so the counters never increment, and the
``director-moves`` Grafana panel shows zero. This module wires the
minimal drivers required to make the counters move.

Design constraints:

* **U4** — the ``MicromoveAdvanceConsumer`` is stateful (carries the
  cycle's current slot). One thread, 15s tick, advances once per tick.
  Idempotent: if the compositor restarts, the cycle restarts at slot 0
  (acceptable; the consumer is exploring slot space, not maintaining
  long-term context).
* **U5** — the ``SemanticVerbConsumer`` is stateless; calls are driven
  by a verb stream. We tap the director-intent.jsonl tail and map the
  intent's ``activity`` to a representative verb. This is intentionally
  loose-coupled — when the director emits structured verbs natively
  (a future PR), we can swap the activity → verb map for direct emit
  without changing the consumer side.

Per ``feedback_no_presets_use_parametric_modulation``: both consumers
already modulate parameters (envelope nudges, slot hints). This driver
adds nothing on top of that contract.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# u4 cadence — 15s gives ≥6 of 8 slots in a 5-min window with margin.
DEFAULT_U4_TICK_S: float = 15.0

# u5 cadence — 30s; the director itself ticks at 70-110s so 30s catches
# every fresh intent without re-firing on stale tails.
DEFAULT_U5_TICK_S: float = 30.0
DEFAULT_U5_INITIAL_DELAY_S: float = DEFAULT_U4_TICK_S * 1.5
"""Phase U5 between U4 ticks when both drivers are live in one process."""

# Env-flag gates for reversibility.
ENV_DISABLE_U4 = "HAPAX_U4_MICROMOVE_DISABLED"
ENV_DISABLE_U5 = "HAPAX_U5_VERB_DISABLED"

# Director intent tail — same as layout_tick_driver but duplicated to
# keep the drivers independent.
DIRECTOR_INTENT_JSONL: Path = Path(
    os.path.expanduser("~/hapax-state/stream-experiment/director-intent.jsonl")
)
DIRECTOR_INTENT_STALE_S: float = 180.0

# Activity → verb map. Preserves ``feedback_no_expert_system_rules``:
# this is a declarative routing table on the existing director vocabulary,
# NOT a hardcoded threshold. Each director activity maps to the verb
# whose axis best matches it. Activities not in this table are skipped
# (the consumer is stateless; missing-mapping is a no-op, not an error).
ACTIVITY_TO_VERB: dict[str, str] = {
    "music": "dwell",  # temporal — sustained presence during music
    "observe": "linger",  # temporal — extended contemplative dwell
    "react": "rupture",  # phenomenological — sudden shift on react cue
    "vinyl": "dwell",  # temporal — sustained presence on vinyl
    "narrate": "linger",  # temporal — extended dwell during narration
    "transition": "accelerate",  # temporal — speed up across boundaries
    "settle": "linger",  # temporal — calm down after intensity
    "warm-up": "ascend",  # temporal — push energy up entering arc
    "wind-down": "linger",  # temporal — sustained low after arc
    "explore": "drift",  # structural — loosen alignment
    "focus": "gather",  # spatial — focus center
    "ambient": "disperse",  # spatial — peripheral spread
    "warm": "warm",  # chromatic — palette warm
    "cool": "cool",  # chromatic — palette cool
    "align": "align",  # structural — snap
    "drift": "drift",  # structural — loosen
}


def _is_u4_disabled() -> bool:
    return os.environ.get(ENV_DISABLE_U4, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_u5_disabled() -> bool:
    return os.environ.get(ENV_DISABLE_U5, "").strip().lower() in {"1", "true", "yes", "on"}


def _read_last_director_activity() -> str | None:
    """Tail the last activity from director-intent.jsonl (None on stale)."""
    try:
        if not DIRECTOR_INTENT_JSONL.exists():
            return None
        age = time.time() - DIRECTOR_INTENT_JSONL.stat().st_mtime
        if age > DIRECTOR_INTENT_STALE_S:
            return None
        with DIRECTOR_INTENT_JSONL.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            offset = max(0, size - 4096)
            f.seek(offset)
            tail = f.read().decode("utf-8", errors="replace")
        last_line = ""
        for line in tail.splitlines():
            stripped = line.strip()
            if stripped:
                last_line = stripped
        if not last_line:
            return None
        rec = json.loads(last_line)
        activity = rec.get("activity")
        if isinstance(activity, str) and activity:
            return activity
    except Exception:
        log.debug("u5 director-activity read failed", exc_info=True)
    return None


def _u4_tick_loop(
    consumer: Any,
    *,
    interval_s: float = DEFAULT_U4_TICK_S,
    stop_event: threading.Event | None = None,
    iterations: int | None = None,
    sleep_fn: Any = time.sleep,
) -> int:
    """Run the U4 micromove consumer at ``interval_s`` cadence."""
    iter_count = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        if iterations is not None and iter_count >= iterations:
            break
        try:
            consumer.advance()
        except Exception:
            log.warning("u4 advance() raised; loop continues", exc_info=True)
        iter_count += 1
        sleep_fn(interval_s)
    return iter_count


def _u5_tick_loop(
    consumer: Any,
    *,
    interval_s: float = DEFAULT_U5_TICK_S,
    activity_provider: Any = None,
    stop_event: threading.Event | None = None,
    iterations: int | None = None,
    sleep_fn: Any = time.sleep,
) -> int:
    """Run the U5 semantic-verb consumer driven by director-activity tail.

    activity_provider is a zero-arg callable returning the latest
    activity string or None. The default reads director-intent.jsonl.
    Each tick: read activity → map to verb → consume(). Activities
    not in ``ACTIVITY_TO_VERB`` are skipped silently.
    """
    if activity_provider is None:
        activity_provider = _read_last_director_activity
    last_consumed_activity: str | None = None
    iter_count = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        if iterations is not None and iter_count >= iterations:
            break
        try:
            activity = activity_provider()
            # Only consume on activity CHANGE so we don't re-fire on
            # stale tails. This keeps the verb stream reflecting actual
            # director moves, not file-tail polling.
            if activity is not None and activity != last_consumed_activity:
                verb = ACTIVITY_TO_VERB.get(activity)
                if verb is not None:
                    consumer.consume(verb)
                    last_consumed_activity = activity
        except Exception:
            log.warning("u5 verb consume tick raised; loop continues", exc_info=True)
        iter_count += 1
        sleep_fn(interval_s)
    return iter_count


def _advance_deadline(previous: float, interval_s: float, now: float) -> float:
    if interval_s <= 0:
        return now
    next_deadline = previous + interval_s
    while next_deadline <= now:
        next_deadline += interval_s
    return next_deadline


def _u_series_tick_loop(
    u4_consumer: Any | None,
    u5_consumer: Any | None,
    *,
    u4_enabled: bool,
    u5_enabled: bool,
    u4_interval_s: float = DEFAULT_U4_TICK_S,
    u5_interval_s: float = DEFAULT_U5_TICK_S,
    u5_initial_delay_s: float = DEFAULT_U5_INITIAL_DELAY_S,
    activity_provider: Any = None,
    stop_event: threading.Event | None = None,
    iterations: int | None = None,
    sleep_fn: Any = time.sleep,
    clock: Any = time.monotonic,
) -> int:
    """Run U4 and U5 from one phased scheduler thread.

    The first U4/U5 emissions are delayed and staggered. The previous
    production wiring started two independent daemon loops that both fired
    immediately at compositor startup; live canaries showed the combined
    state alone could pull v4l2 egress below the frame floor even though
    each driver was fine in isolation. One scheduler thread keeps the
    substrates active without adding simultaneous GIL wakeups on the
    compositor process.
    """
    if activity_provider is None:
        activity_provider = _read_last_director_activity
    now = float(clock())
    next_u4 = now + max(u4_interval_s, 0.0)
    next_u5 = now + max(u5_initial_delay_s, 0.0)
    last_consumed_activity: str | None = None
    iter_count = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        if iterations is not None and iter_count >= iterations:
            break
        now = float(clock())
        if u4_enabled and u4_consumer is not None and now >= next_u4:
            try:
                u4_consumer.advance()
            except Exception:
                log.warning("u4 advance() raised; loop continues", exc_info=True)
            next_u4 = _advance_deadline(next_u4, u4_interval_s, now)
        if u5_enabled and u5_consumer is not None and now >= next_u5:
            try:
                activity = activity_provider()
                if activity is not None and activity != last_consumed_activity:
                    verb = ACTIVITY_TO_VERB.get(activity)
                    if verb is not None:
                        u5_consumer.consume(verb)
                        last_consumed_activity = activity
            except Exception:
                log.warning("u5 verb consume tick raised; loop continues", exc_info=True)
            next_u5 = _advance_deadline(next_u5, u5_interval_s, now)
        iter_count += 1
        if iterations is not None and iter_count >= iterations:
            continue
        next_due = min(
            next_u4 if u4_enabled else float("inf"),
            next_u5 if u5_enabled else float("inf"),
        )
        delay_s = max(0.0, min(1.0, next_due - float(clock())))
        sleep_fn(delay_s)
    return iter_count


def start_u4_driver(compositor: Any) -> threading.Thread | None:
    """Start the U4 micromove-advance daemon thread."""
    if _is_u4_disabled():
        log.info("u4 micromove driver disabled via %s", ENV_DISABLE_U4)
        return None
    from agents.studio_compositor.micromove_consumer import (
        MicromoveAdvanceConsumer,
    )

    consumer = MicromoveAdvanceConsumer()
    compositor._u4_micromove_consumer = consumer  # type: ignore[attr-defined]

    def _target() -> None:
        log.info("u4 micromove driver started (interval=%.1fs)", DEFAULT_U4_TICK_S)
        _u4_tick_loop(consumer, interval_s=DEFAULT_U4_TICK_S)

    thread = threading.Thread(target=_target, daemon=True, name="u4-micromove-driver")
    thread.start()
    compositor._u4_micromove_thread = thread  # type: ignore[attr-defined]
    return thread


def start_u5_driver(compositor: Any) -> threading.Thread | None:
    """Start the U5 semantic-verb daemon thread."""
    if _is_u5_disabled():
        log.info("u5 verb driver disabled via %s", ENV_DISABLE_U5)
        return None
    from agents.studio_compositor.semantic_verb_consumer import (
        SemanticVerbConsumer,
    )

    consumer = SemanticVerbConsumer()
    compositor._u5_verb_consumer = consumer  # type: ignore[attr-defined]

    def _target() -> None:
        log.info("u5 verb driver started (interval=%.1fs)", DEFAULT_U5_TICK_S)
        _u5_tick_loop(consumer, interval_s=DEFAULT_U5_TICK_S)

    thread = threading.Thread(target=_target, daemon=True, name="u5-verb-driver")
    thread.start()
    compositor._u5_verb_thread = thread  # type: ignore[attr-defined]
    return thread


def start_u_series_drivers(compositor: Any) -> None:
    """Start U4 + U5 from one phased daemon driver; non-fatal on failure."""
    u4_enabled = not _is_u4_disabled()
    u5_enabled = not _is_u5_disabled()
    if not u4_enabled and not u5_enabled:
        log.info("u4/u5 drivers disabled via env")
        return

    u4_consumer = None
    u5_consumer = None
    if u4_enabled:
        from agents.studio_compositor.micromove_consumer import (
            MicromoveAdvanceConsumer,
        )

        u4_consumer = MicromoveAdvanceConsumer()
        compositor._u4_micromove_consumer = u4_consumer  # type: ignore[attr-defined]
    if u5_enabled:
        from agents.studio_compositor.semantic_verb_consumer import (
            SemanticVerbConsumer,
        )

        u5_consumer = SemanticVerbConsumer()
        compositor._u5_verb_consumer = u5_consumer  # type: ignore[attr-defined]

    def _target() -> None:
        log.info(
            "u-series driver started (u4=%s interval=%.1fs; u5=%s interval=%.1fs phase=%.1fs)",
            u4_enabled,
            DEFAULT_U4_TICK_S,
            u5_enabled,
            DEFAULT_U5_TICK_S,
            DEFAULT_U5_INITIAL_DELAY_S,
        )
        _u_series_tick_loop(
            u4_consumer,
            u5_consumer,
            u4_enabled=u4_enabled,
            u5_enabled=u5_enabled,
            u4_interval_s=DEFAULT_U4_TICK_S,
            u5_interval_s=DEFAULT_U5_TICK_S,
            u5_initial_delay_s=DEFAULT_U5_INITIAL_DELAY_S,
        )

    thread = threading.Thread(target=_target, daemon=True, name="u-series-driver")
    thread.start()
    compositor._u_series_thread = thread  # type: ignore[attr-defined]


__all__ = [
    "ACTIVITY_TO_VERB",
    "DEFAULT_U4_TICK_S",
    "DEFAULT_U5_INITIAL_DELAY_S",
    "DEFAULT_U5_TICK_S",
    "DIRECTOR_INTENT_JSONL",
    "ENV_DISABLE_U4",
    "ENV_DISABLE_U5",
    "_u_series_tick_loop",
    "_u4_tick_loop",
    "_u5_tick_loop",
    "start_u4_driver",
    "start_u5_driver",
    "start_u_series_drivers",
]
