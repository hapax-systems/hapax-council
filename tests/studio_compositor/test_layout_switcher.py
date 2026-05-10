"""R9 dynamic-layout-switching tests (effect+cam orchestration audit, 2026-05-02)."""

from __future__ import annotations

import pytest

from agents.studio_compositor.layout_switcher import (
    DEFAULT_COOLDOWN_S,
    KNOWN_LAYOUTS,
    MIN_COOLDOWN_S,
    LayoutSelection,
    LayoutSwitcher,
    select_layout,
)

# ── select_layout (pure-logic policy) ───────────────────────────────


def test_consent_safe_dominates_every_other_signal() -> None:
    selection = select_layout(
        consent_safe_active=True,
        vinyl_playing=True,
        director_activity="vinyl",
        stream_mode="deep",
    )
    assert selection.layout_name == "consent-safe"
    assert selection.trigger == "consent_safe"


def test_vinyl_playing_stays_on_default_with_observable_trigger() -> None:
    selection = select_layout(vinyl_playing=True)
    assert selection.layout_name == "default"
    assert selection.trigger == "vinyl_playing_default"


def test_vinyl_playing_outranks_director_activity_and_stream_mode() -> None:
    selection = select_layout(vinyl_playing=True, director_activity="study", stream_mode="deep")
    assert selection.layout_name == "default"
    assert selection.trigger == "vinyl_playing_default"


def test_director_activity_vinyl_stays_on_default_with_observable_trigger() -> None:
    selection = select_layout(director_activity="vinyl")
    assert selection.layout_name == "default"
    assert selection.trigger == "director_activity_vinyl_default"


def test_director_activity_react_stays_on_default_with_observable_trigger() -> None:
    selection = select_layout(director_activity="react")
    assert selection.layout_name == "default"
    assert selection.trigger == "director_activity_react_default"


def test_director_activity_other_does_not_change_default_trigger() -> None:
    for activity in ("study", "chat", "observe", "silence"):
        selection = select_layout(director_activity=activity)
        assert selection.layout_name == "default", activity
        assert selection.trigger == "default_fallback"


def test_stream_mode_deep_stays_on_default_with_observable_trigger() -> None:
    selection = select_layout(stream_mode="deep")
    assert selection.layout_name == "default"
    assert selection.trigger == "stream_mode_deep_default"


def test_default_fallback_when_no_signals() -> None:
    selection = select_layout()
    assert selection.layout_name == "default"
    assert selection.trigger == "default_fallback"


def test_known_layouts_match_returned_names() -> None:
    """Every layout name the policy can return must be in KNOWN_LAYOUTS."""
    selections = [
        select_layout(consent_safe_active=True),
        select_layout(vinyl_playing=True),
        select_layout(director_activity="vinyl"),
        select_layout(director_activity="react"),
        select_layout(stream_mode="deep"),
        select_layout(),
    ]
    for s in selections:
        assert s.layout_name in KNOWN_LAYOUTS, s


# ── LayoutSwitcher (cooldown wrapper) ───────────────────────────────


def test_should_switch_false_for_same_layout() -> None:
    sw = LayoutSwitcher(initial_layout="default")
    selection = LayoutSelection("default", "default_fallback")
    assert sw.should_switch(selection) is False


def test_should_switch_true_when_no_prior_switch() -> None:
    sw = LayoutSwitcher(initial_layout="garage-door")
    selection = LayoutSelection("default", "vinyl_playing_default")
    assert sw.should_switch(selection) is True


def test_cooldown_blocks_consecutive_switches() -> None:
    clock = [1000.0]
    sw = LayoutSwitcher(initial_layout="default", clock=lambda: clock[0])
    first = LayoutSelection("consent-safe", "consent_safe")
    sw.record_switch(first)
    assert sw.should_switch(LayoutSelection("default", "default_fallback")) is False
    clock[0] += DEFAULT_COOLDOWN_S - 1
    assert sw.should_switch(LayoutSelection("default", "default_fallback")) is False
    clock[0] += 2  # now well past cooldown
    assert sw.should_switch(LayoutSelection("default", "default_fallback")) is True


def test_cooldown_does_not_block_consent_safe() -> None:
    """Safety beats aesthetics — consent-safe transitions always allowed."""
    clock = [1000.0]
    sw = LayoutSwitcher(initial_layout="default", clock=lambda: clock[0])
    sw.record_switch(LayoutSelection("default", "vinyl_playing_default"))
    # Cooldown not elapsed, but consent_safe must pass.
    consent = LayoutSelection("consent-safe", "consent_safe")
    assert sw.should_switch(consent) is True


def test_record_switch_updates_state() -> None:
    clock = [1000.0]
    sw = LayoutSwitcher(initial_layout="default", clock=lambda: clock[0])
    sw.record_switch(LayoutSelection("consent-safe", "consent_safe"))
    assert sw.current_layout == "consent-safe"


def test_cooldown_floor_rejected() -> None:
    with pytest.raises(ValueError, match=r"below floor"):
        LayoutSwitcher(cooldown_s=4.0)


def test_cooldown_minimum_accepted() -> None:
    sw = LayoutSwitcher(cooldown_s=MIN_COOLDOWN_S)
    assert sw.current_layout is None  # no initial


# ── stream_mode transition triggers within 1 tick (R9 acceptance) ───


def test_stream_mode_transition_triggers_layout_change_within_one_tick() -> None:
    """R9 acceptance: when stream_mode flips, a single select_layout +
    should_switch invocation is enough to cause a layout change (subject
    to cooldown). No multi-tick latency."""
    clock = [1000.0]
    sw = LayoutSwitcher(initial_layout="default", clock=lambda: clock[0])

    # Tick 0: stream_mode is None, default chosen.
    s0 = select_layout(stream_mode=None)
    assert s0.layout_name == "default"
    assert sw.should_switch(s0) is False  # already on default

    # Tick 1: stream_mode flips to "deep"; selector records the pressure
    # without resurrecting the purged default-legacy layout.
    s1 = select_layout(stream_mode="deep")
    assert s1.layout_name == "default"
    assert s1.trigger == "stream_mode_deep_default"
    assert sw.should_switch(s1) is False
    assert sw.current_layout == "default"


# ── counter integration ─────────────────────────────────────────────


def test_record_switch_increments_prometheus_counter() -> None:
    from agents.studio_compositor.metrics import HAPAX_COMPOSITOR_LAYOUT_SWITCH_TOTAL

    if HAPAX_COMPOSITOR_LAYOUT_SWITCH_TOTAL is None:
        pytest.skip("prometheus_client unavailable")
    label_set = {"from_layout": "default", "to_layout": "consent-safe", "trigger": "consent_safe"}
    before = HAPAX_COMPOSITOR_LAYOUT_SWITCH_TOTAL.labels(**label_set)._value.get()
    sw = LayoutSwitcher(initial_layout="default")
    sw.record_switch(LayoutSelection("consent-safe", "consent_safe"))
    after = HAPAX_COMPOSITOR_LAYOUT_SWITCH_TOTAL.labels(**label_set)._value.get()
    assert after - before == 1.0


def test_record_switch_uninitialised_layout_label() -> None:
    """When no initial_layout is set, the counter records ``uninitialised``
    as the from_layout — so the first-ever switch is observable."""
    from agents.studio_compositor.metrics import HAPAX_COMPOSITOR_LAYOUT_SWITCH_TOTAL

    if HAPAX_COMPOSITOR_LAYOUT_SWITCH_TOTAL is None:
        pytest.skip("prometheus_client unavailable")
    label_set = {
        "from_layout": "uninitialised",
        "to_layout": "default",
        "trigger": "default_fallback",
    }
    before = HAPAX_COMPOSITOR_LAYOUT_SWITCH_TOTAL.labels(**label_set)._value.get()
    sw = LayoutSwitcher()
    sw.record_switch(LayoutSelection("default", "default_fallback"))
    after = HAPAX_COMPOSITOR_LAYOUT_SWITCH_TOTAL.labels(**label_set)._value.get()
    assert after - before == 1.0
