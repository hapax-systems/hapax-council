"""Tests for u4/u5 daemon drivers + counter registry placement.

cc-tasks: u4-micromove-advance-tick-consumer, u5-verb-prometheus-counter-and-consumer.

Verifies:
- U4/U5 counters are registered on the compositor REGISTRY (not the
  default registry) so :9482 scrape exposes them.
- The U4 micromove driver advances the cycle and increments the counter
  per tick.
- The U5 verb driver maps director activity → verb and increments the
  counter on activity change.
- Env-flag gates honor disable.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest  # noqa: TC002 — used at runtime via monkeypatch.MonkeyPatch annotation

from agents.studio_compositor import metrics, u_series_drivers
from agents.studio_compositor.micromove_consumer import (
    MicromoveAdvanceConsumer,
    hapax_micromove_advance_total,
)
from agents.studio_compositor.semantic_verb_consumer import (
    SemanticVerbConsumer,
    hapax_semantic_verb_consumed_total,
)
from agents.studio_compositor.u_series_drivers import (
    ACTIVITY_TO_VERB,
    DEFAULT_U4_TICK_S,
    DEFAULT_U5_INITIAL_DELAY_S,
    _u4_tick_loop,
    _u5_tick_loop,
    _u_series_tick_loop,
    start_u4_driver,
    start_u5_driver,
)

# ── env-flag gates ─────────────────────────────────────────────────


def test_u4_disabled_env_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(u_series_drivers.ENV_DISABLE_U4, "1")

    class _Stub:
        pass

    assert start_u4_driver(_Stub()) is None


def test_u5_disabled_env_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(u_series_drivers.ENV_DISABLE_U5, "1")

    class _Stub:
        pass

    assert start_u5_driver(_Stub()) is None


# ── U4 driver ──────────────────────────────────────────────────────


def test_u4_tick_loop_advances_per_iteration(tmp_path: Path) -> None:
    """Each iteration calls advance() exactly once."""
    consumer = MicromoveAdvanceConsumer(state_path=tmp_path / "micromove-advance.json")
    initial_slot = consumer.cycle.current_slot()
    iter_count = _u4_tick_loop(
        consumer,
        interval_s=0.0,
        sleep_fn=lambda _s: None,
        iterations=3,
    )
    assert iter_count == 3
    # Cycle advanced 3 slots.
    expected = (initial_slot + 3) % 8
    assert consumer.cycle.current_slot() == expected


def _counter_total(counter: Any, suffix: str = "_total") -> float:
    """Sum samples whose name matches the counter base name + suffix.

    prometheus_client emits counter samples as base name + ``_total``
    (e.g., ``hapax_micromove_advance_total``) and base name +
    ``_created`` (creation timestamp). We sum only the ``_total``
    samples for monotonic-counter semantics.
    """
    total = 0.0
    for metric_family in counter.collect():
        for sample in metric_family.samples:
            if sample.name.endswith(suffix):
                total += sample.value
    return total


def test_u4_counter_increments_per_advance(tmp_path: Path) -> None:
    """The counter must increment for each tick."""
    consumer = MicromoveAdvanceConsumer(state_path=tmp_path / "micromove-advance.json")
    initial = _counter_total(hapax_micromove_advance_total)
    _u4_tick_loop(
        consumer,
        interval_s=0.0,
        sleep_fn=lambda _s: None,
        iterations=4,
    )
    final = _counter_total(hapax_micromove_advance_total)
    assert final - initial == 4


def test_u4_state_file_emitted(tmp_path: Path) -> None:
    """Compositor reads micromove-advance.json on next render — verify it lands."""
    state_path = tmp_path / "micromove-advance.json"
    consumer = MicromoveAdvanceConsumer(state_path=state_path)
    _u4_tick_loop(
        consumer,
        interval_s=0.0,
        sleep_fn=lambda _s: None,
        iterations=1,
    )
    payload = json.loads(state_path.read_text())
    assert "slot" in payload
    assert "hint" in payload


# ── U5 driver ──────────────────────────────────────────────────────


def test_u5_consumes_on_activity_change() -> None:
    """Activity change → mapped verb dispatched."""
    activities = ["react", "react", "vinyl", "react"]
    activity_iter = iter(activities)

    def _provider() -> str | None:
        try:
            return next(activity_iter)
        except StopIteration:
            return None

    consumer = SemanticVerbConsumer()
    initial_total = _counter_total(hapax_semantic_verb_consumed_total)
    iter_count = _u5_tick_loop(
        consumer,
        interval_s=0.0,
        activity_provider=_provider,
        sleep_fn=lambda _s: None,
        iterations=4,
    )
    assert iter_count == 4
    final_total = _counter_total(hapax_semantic_verb_consumed_total)
    # 4 activities, 3 are change-points (react,vinyl,react) — 3 dispatches.
    assert final_total - initial_total == 3


def test_u5_skips_unknown_activity() -> None:
    """Activities not in ACTIVITY_TO_VERB are skipped silently."""
    consumer = SemanticVerbConsumer()
    initial_total = _counter_total(hapax_semantic_verb_consumed_total)
    _u5_tick_loop(
        consumer,
        interval_s=0.0,
        activity_provider=lambda: "totally-unknown-activity",
        sleep_fn=lambda _s: None,
        iterations=3,
    )
    final_total = _counter_total(hapax_semantic_verb_consumed_total)
    assert final_total == initial_total


def test_u5_no_activity_skips_silently() -> None:
    """activity_provider returning None → no consume()."""
    consumer = SemanticVerbConsumer()
    initial_total = _counter_total(hapax_semantic_verb_consumed_total)
    _u5_tick_loop(
        consumer,
        interval_s=0.0,
        activity_provider=lambda: None,
        sleep_fn=lambda _s: None,
        iterations=3,
    )
    final_total = _counter_total(hapax_semantic_verb_consumed_total)
    assert final_total == initial_total


def test_u5_activity_to_verb_table_complete() -> None:
    """ACTIVITY_TO_VERB only maps to verbs in the canonical vocabulary."""
    from shared.director_semantic_verbs import SEMANTIC_VERBS

    for activity, verb in ACTIVITY_TO_VERB.items():
        assert verb in SEMANTIC_VERBS, f"activity {activity!r} maps to unknown verb {verb!r}"


# ── combined phased driver ─────────────────────────────────────────


def test_combined_u_series_loop_does_not_fire_immediately() -> None:
    """The production combined loop phases work off compositor startup."""

    class _U4:
        def __init__(self) -> None:
            self.count = 0

        def advance(self) -> None:
            self.count += 1

    class _U5:
        def __init__(self) -> None:
            self.verbs: list[str] = []

        def consume(self, verb: str) -> None:
            self.verbs.append(verb)

    u4 = _U4()
    u5 = _U5()
    sleeps: list[float] = []
    iterations = _u_series_tick_loop(
        u4,
        u5,
        u4_enabled=True,
        u5_enabled=True,
        iterations=1,
        sleep_fn=sleeps.append,
        clock=lambda: 0.0,
        activity_provider=lambda: "music",
    )
    assert iterations == 1
    assert u4.count == 0
    assert u5.verbs == []
    assert DEFAULT_U5_INITIAL_DELAY_S > DEFAULT_U4_TICK_S


def test_combined_u_series_loop_phases_u4_and_u5() -> None:
    """U4 and U5 fire from one scheduler but at different deadlines."""

    class _Clock:
        def __init__(self) -> None:
            self.now = 0.0

        def __call__(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.now += seconds

    class _U4:
        def __init__(self) -> None:
            self.fired_at: list[float] = []

        def advance(self) -> None:
            self.fired_at.append(clock.now)

    class _U5:
        def __init__(self) -> None:
            self.fired_at: list[tuple[float, str]] = []

        def consume(self, verb: str) -> None:
            self.fired_at.append((clock.now, verb))

    clock = _Clock()
    u4 = _U4()
    u5 = _U5()
    iterations = _u_series_tick_loop(
        u4,
        u5,
        u4_enabled=True,
        u5_enabled=True,
        u4_interval_s=0.10,
        u5_interval_s=0.20,
        u5_initial_delay_s=0.15,
        activity_provider=lambda: "music",
        sleep_fn=clock.sleep,
        clock=clock,
        iterations=5,
    )
    assert iterations == 5
    assert u4.fired_at == pytest.approx([0.10, 0.20, 0.30])
    assert len(u5.fired_at) == 1
    assert u5.fired_at[0][0] == pytest.approx(0.15)
    assert u5.fired_at[0][1] == ACTIVITY_TO_VERB["music"]


# ── stop event semantics ───────────────────────────────────────────


def test_u4_stop_event_breaks_loop(tmp_path: Path) -> None:
    consumer = MicromoveAdvanceConsumer(state_path=tmp_path / "micromove-advance.json")
    stop = threading.Event()
    stop.set()
    iter_count = _u4_tick_loop(
        consumer,
        interval_s=0.0,
        sleep_fn=lambda _s: None,
        stop_event=stop,
    )
    assert iter_count == 0


def test_u5_stop_event_breaks_loop() -> None:
    consumer = SemanticVerbConsumer()
    stop = threading.Event()
    stop.set()
    iter_count = _u5_tick_loop(
        consumer,
        interval_s=0.0,
        activity_provider=lambda: "react",
        sleep_fn=lambda _s: None,
        stop_event=stop,
    )
    assert iter_count == 0


# ── Counter registry placement ─────────────────────────────────────


def test_u4_counter_on_compositor_registry() -> None:
    """U4 counter must reach :9482 — confirms _init_metrics re-registered it."""
    metrics._init_metrics()
    assert metrics.REGISTRY is not None
    found = False
    for collector in metrics.REGISTRY._collector_to_names:  # type: ignore[attr-defined]
        for name in metrics.REGISTRY._collector_to_names[collector]:  # type: ignore[attr-defined]
            if name == "hapax_micromove_advance_total":
                found = True
                break
    assert found, "u4 counter not on compositor REGISTRY → :9482 won't expose it"


def test_u5_counter_on_compositor_registry() -> None:
    """U5 counter must reach :9482."""
    metrics._init_metrics()
    assert metrics.REGISTRY is not None
    found = False
    for collector in metrics.REGISTRY._collector_to_names:  # type: ignore[attr-defined]
        for name in metrics.REGISTRY._collector_to_names[collector]:  # type: ignore[attr-defined]
            if name == "hapax_semantic_verb_consumed_total":
                found = True
                break
    assert found, "u5 counter not on compositor REGISTRY → :9482 won't expose it"
