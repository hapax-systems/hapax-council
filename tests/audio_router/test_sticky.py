"""Phase C2 — utterance-boundary sticky tracker tests (spec §6.5).

Verifies the 10 s stick window, operator sticky override, and correct
precedence between sticky state and automatic tier flows.
"""

from __future__ import annotations

from agents.audio_router import DEFAULT_STICK_WINDOW_S, StickyTracker


def test_fresh_tracker_returns_none() -> None:
    t = StickyTracker()
    assert t.active_tier_at(now=0.0) is None


def test_emission_sets_active_tier() -> None:
    t = StickyTracker()
    t.on_tts_emission(tier=3, now=0.0)
    assert t.active_tier_at(now=0.0) == 3


def test_active_emission_holds_across_time_without_silence() -> None:
    """While no silence has been signaled, the emission tier persists
    indefinitely (caller is expected to call on_tts_silence_start)."""
    t = StickyTracker()
    t.on_tts_emission(tier=2, now=0.0)
    assert t.active_tier_at(now=100.0) == 2


def test_silence_within_window_holds_tier() -> None:
    """After silence_start, tier sticks through the window."""
    t = StickyTracker()
    t.on_tts_emission(tier=3, now=0.0)
    t.on_tts_silence_start(now=0.0)
    assert t.active_tier_at(now=5.0) == 3
    assert t.is_in_silence_window(now=5.0) is True


def test_silence_past_window_returns_none() -> None:
    """10 s stick window: at t=10.1 after silence_start, tracker
    releases and returns None (caller → stance default)."""
    t = StickyTracker()
    t.on_tts_emission(tier=3, now=0.0)
    t.on_tts_silence_start(now=0.0)
    assert t.active_tier_at(now=10.1) is None
    assert t.is_in_silence_window(now=10.1) is False


def test_silence_exactly_at_window_edge_still_holds() -> None:
    """At t=10.0 exactly, boundary is inclusive."""
    t = StickyTracker()
    t.on_tts_emission(tier=3, now=0.0)
    t.on_tts_silence_start(now=0.0)
    assert t.active_tier_at(now=10.0) == 3


def test_new_emission_resets_silence_window() -> None:
    """New utterance starts — silence timer resets so next silence gets
    a fresh 10 s window."""
    t = StickyTracker()
    t.on_tts_emission(tier=3, now=0.0)
    t.on_tts_silence_start(now=1.0)
    # Within window, still tier 3
    assert t.active_tier_at(now=5.0) == 3
    # New emission at t=6.0 with different tier
    t.on_tts_emission(tier=5, now=6.0)
    assert t.active_tier_at(now=6.0) == 5
    # Silence again at t=10.0 — window starts fresh
    t.on_tts_silence_start(now=10.0)
    # At t=19.0 (well past the original 10s window), still within NEW 10s window
    assert t.active_tier_at(now=19.0) == 5
    # At t=20.1 — past window
    assert t.active_tier_at(now=20.1) is None


def test_operator_override_persists_indefinitely() -> None:
    """Operator sticky override wins for arbitrary long times."""
    t = StickyTracker()
    t.operator_override(tier=4, now=0.0, sticky=True)
    t.on_tts_silence_start(now=0.0)
    # Way past the normal 10 s window
    assert t.active_tier_at(now=500.0) == 4
    assert t.is_operator_overridden() is True


def test_operator_release_resumes_automatic_behavior() -> None:
    """After release, active_tier_at returns None (no ongoing emission)."""
    t = StickyTracker()
    t.operator_override(tier=4, now=0.0, sticky=True)
    assert t.active_tier_at(now=5.0) == 4
    t.operator_release(now=6.0)
    assert t.active_tier_at(now=7.0) is None
    assert t.is_operator_overridden() is False


def test_operator_release_after_prior_emission_reveals_silence_state() -> None:
    """When operator releases a sticky override but there's a lingering
    emission tier, the silence-window rules take over from that point."""
    t = StickyTracker()
    t.on_tts_emission(tier=2, now=0.0)
    t.on_tts_silence_start(now=1.0)
    t.operator_override(tier=5, now=2.0, sticky=True)
    # Override wins
    assert t.active_tier_at(now=3.0) == 5
    # Release: silence window was started at t=1.0; we're at t=4.0, within 10 s
    t.operator_release(now=4.0)
    assert t.active_tier_at(now=4.0) == 2  # emission tier re-surfaces


def test_non_sticky_operator_override_behaves_like_emission() -> None:
    """Operator override without sticky flag captures as an emission."""
    t = StickyTracker()
    t.operator_override(tier=1, now=0.0, sticky=False)
    # Emission — tier 1 active
    assert t.active_tier_at(now=1.0) == 1
    assert t.is_operator_overridden() is False
    # Silence starts, 10 s window
    t.on_tts_silence_start(now=2.0)
    assert t.active_tier_at(now=11.9) == 1
    assert t.active_tier_at(now=12.1) is None


def test_custom_stick_window_respected() -> None:
    """stick_window_s can be overridden via constructor (env-configurable)."""
    t = StickyTracker(stick_window_s=5.0)
    t.on_tts_emission(tier=3, now=0.0)
    t.on_tts_silence_start(now=0.0)
    assert t.active_tier_at(now=4.9) == 3
    assert t.active_tier_at(now=5.1) is None


def test_default_stick_window_is_10s() -> None:
    """Spec §6.5 mandates default 10 s."""
    assert DEFAULT_STICK_WINDOW_S == 10.0
    t = StickyTracker()
    assert t.stick_window_s == 10.0


def test_transitions_logged_for_langfuse_correlation() -> None:
    """Transition history available for Langfuse event correlation."""
    t = StickyTracker()
    t.on_tts_emission(tier=2, now=0.0)
    t.on_tts_silence_start(now=1.0)
    t.operator_override(tier=4, now=2.0, sticky=True)
    t.operator_release(now=3.0)
    # Four events logged
    assert len(t._transitions) == 4
    # Transitions are (timestamp, description) tuples in chronological order
    assert t._transitions[0] == (0.0, "emission tier=2")
    assert t._transitions[1] == (1.0, "silence_start")
    assert "operator_override_sticky" in t._transitions[2][1]
    assert t._transitions[3] == (3.0, "operator_release")
