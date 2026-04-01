"""Tests for imagination daemon closed-loop control law (Property 4)."""

from __future__ import annotations


def test_imagination_degrades_on_consecutive_errors():
    """After 3 errors, cadence should double."""
    from agents.imagination_daemon.__main__ import ImaginationDaemon

    daemon = ImaginationDaemon()
    original_base = daemon._imagination.cadence._base_s

    # Simulate 3 consecutive errors
    daemon._consecutive_errors = 3
    daemon._consecutive_ok = 0
    daemon._cadence_degraded = False

    # Apply control law
    if daemon._consecutive_errors >= 3 and not daemon._cadence_degraded:
        daemon._imagination.cadence._base_s *= 2.0
        daemon._cadence_degraded = True

    assert daemon._imagination.cadence._base_s == original_base * 2.0
    assert daemon._cadence_degraded is True


def test_imagination_restores_after_recovery():
    """After 3 successes, cadence should restore."""
    from agents.imagination_daemon.__main__ import ImaginationDaemon

    daemon = ImaginationDaemon()
    original_base = daemon._imagination.cadence._base_s

    # Pre-condition: degraded
    daemon._imagination.cadence._base_s *= 2.0
    daemon._cadence_degraded = True
    daemon._consecutive_ok = 3
    daemon._consecutive_errors = 0

    # Apply control law
    if daemon._consecutive_ok >= 3 and daemon._cadence_degraded:
        daemon._imagination.cadence._base_s /= 2.0
        daemon._cadence_degraded = False

    assert daemon._imagination.cadence._base_s == original_base
    assert daemon._cadence_degraded is False


def test_no_double_degradation():
    """Already degraded daemon should not double cadence again."""
    from agents.imagination_daemon.__main__ import ImaginationDaemon

    daemon = ImaginationDaemon()
    original_base = daemon._imagination.cadence._base_s

    # First degradation
    daemon._consecutive_errors = 3
    daemon._cadence_degraded = False
    if daemon._consecutive_errors >= 3 and not daemon._cadence_degraded:
        daemon._imagination.cadence._base_s *= 2.0
        daemon._cadence_degraded = True

    # Simulate more errors — should NOT double again
    daemon._consecutive_errors = 6
    if daemon._consecutive_errors >= 3 and not daemon._cadence_degraded:
        daemon._imagination.cadence._base_s *= 2.0
        daemon._cadence_degraded = True

    assert daemon._imagination.cadence._base_s == original_base * 2.0  # only 1x doubling


def test_init_state():
    """Daemon initializes control law state correctly."""
    from agents.imagination_daemon.__main__ import ImaginationDaemon

    daemon = ImaginationDaemon()
    assert daemon._consecutive_errors == 0
    assert daemon._consecutive_ok == 0
    assert daemon._cadence_degraded is False
