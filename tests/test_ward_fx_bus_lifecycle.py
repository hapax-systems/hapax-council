"""R-6 pin: lifecycle + introspection on ``WardFxBus``.

Audit 2026-04-26 row R-6 noted that ``unsubscribe_ward``,
``unsubscribe_fx``, ``ward_subscriber_count`` and ``fx_subscriber_count``
were defined on :class:`WardFxBus` but had zero callers and zero
tests — leaving the API documented but unverified.

These tests pin the four functions to the same behavioural contract a
reader would infer from the docstrings: counts reflect the subscriber
list, unsubscribe is idempotent, and unknown callbacks are silently
ignored (the same surface the publisher loop assumes).
"""

from __future__ import annotations

from shared.ward_fx_bus import (
    FXEvent,
    WardEvent,
    WardFxBus,
)


def _bus() -> WardFxBus:
    return WardFxBus(jsonl_path=None)


class TestFXEventStrengthClampInvariant:
    """Pin: ``FXEvent.strength`` is the single canonical [0,1] attenuation site.

    Producers and consumers depend on the invariant being enforced at
    construction (gap #9 — double-attenuation collapse). If this contract
    breaks, multi-clamping creeps back in elsewhere.
    """

    def test_above_one_clamps_to_one(self) -> None:
        ev = FXEvent(kind="audio_kick_onset", strength=2.5)
        assert ev.strength == 1.0

    def test_below_zero_clamps_to_zero(self) -> None:
        ev = FXEvent(kind="audio_kick_onset", strength=-0.4)
        assert ev.strength == 0.0

    def test_in_range_passthrough(self) -> None:
        ev = FXEvent(kind="audio_kick_onset", strength=0.42)
        assert ev.strength == 0.42

    def test_default_full_strength(self) -> None:
        ev = FXEvent(kind="audio_kick_onset")
        assert ev.strength == 1.0


class TestSubscriberCounts:
    def test_empty_bus_reports_zero(self) -> None:
        bus = _bus()
        assert bus.ward_subscriber_count() == 0
        assert bus.fx_subscriber_count() == 0

    def test_subscribe_increments_count(self) -> None:
        bus = _bus()
        bus.subscribe_ward(lambda _e: None)
        bus.subscribe_ward(lambda _e: None)
        bus.subscribe_fx(lambda _e: None)
        assert bus.ward_subscriber_count() == 2
        assert bus.fx_subscriber_count() == 1

    def test_counts_are_independent(self) -> None:
        bus = _bus()
        bus.subscribe_ward(lambda _e: None)
        assert bus.fx_subscriber_count() == 0
        bus.subscribe_fx(lambda _e: None)
        assert bus.ward_subscriber_count() == 1


class TestUnsubscribe:
    def test_unsubscribe_removes_ward_subscriber(self) -> None:
        bus = _bus()

        def cb(_e: WardEvent) -> None:
            return None

        bus.subscribe_ward(cb)
        assert bus.ward_subscriber_count() == 1
        bus.unsubscribe_ward(cb)
        assert bus.ward_subscriber_count() == 0

    def test_unsubscribe_removes_fx_subscriber(self) -> None:
        bus = _bus()

        def cb(_e: FXEvent) -> None:
            return None

        bus.subscribe_fx(cb)
        assert bus.fx_subscriber_count() == 1
        bus.unsubscribe_fx(cb)
        assert bus.fx_subscriber_count() == 0

    def test_unsubscribe_unknown_callback_is_silent(self) -> None:
        bus = _bus()

        def never_subscribed(_e: WardEvent) -> None:
            return None

        # Must not raise — protects callers that defensively unsubscribe
        # without tracking whether they actually subscribed.
        bus.unsubscribe_ward(never_subscribed)
        bus.unsubscribe_fx(never_subscribed)  # type: ignore[arg-type]

    def test_unsubscribe_only_removes_one_instance(self) -> None:
        bus = _bus()

        def cb(_e: WardEvent) -> None:
            return None

        bus.subscribe_ward(cb)
        bus.subscribe_ward(cb)
        bus.unsubscribe_ward(cb)
        # list.remove() drops the first match; a duplicate registration
        # leaves one copy still attached.
        assert bus.ward_subscriber_count() == 1


class TestUnsubscribeStopsDispatch:
    def test_unsubscribed_ward_callback_no_longer_fires(self) -> None:
        bus = _bus()
        seen: list[WardEvent] = []
        cb = seen.append
        bus.subscribe_ward(cb)
        bus.publish_ward(WardEvent(transition="entering", ward_id="w1", domain="cognition"))
        assert len(seen) == 1
        bus.unsubscribe_ward(cb)
        bus.publish_ward(WardEvent(transition="entering", ward_id="w2", domain="cognition"))
        assert len(seen) == 1  # second publish must not reach unsubscribed cb

    def test_unsubscribed_fx_callback_no_longer_fires(self) -> None:
        bus = _bus()
        seen: list[FXEvent] = []
        cb = seen.append
        bus.subscribe_fx(cb)
        bus.publish_fx(FXEvent(kind="chain_swap", preset_family="audio-reactive"))
        assert len(seen) == 1
        bus.unsubscribe_fx(cb)
        bus.publish_fx(FXEvent(kind="chain_swap", preset_family="audio-reactive"))
        assert len(seen) == 1
