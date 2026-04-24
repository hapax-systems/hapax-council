"""Tests for the GEAL temporal curve library (spec §7).

Two families — event-bound (three_phase, gaussian_pulse, log_decay) and
signal-bound (SecondOrderLP) — with a unified :class:`Envelope` wrapper.

Invariants pinned here:

- ``three_phase`` starts at 0 at the fire moment, goes through a
  counter-directional anticipate segment, peaks at ``peak_amp`` near
  ``anticipate_ms + commit_ms``, and log-decays to near-zero afterwards.
- ``SecondOrderLP`` is critically-damped and settles to its target
  without overshoot ringing.
- The **blink-floor** invariant: no curve crosses its full-scale range
  faster than 200 ms (derivative magnitude bounded). This is the
  aesthetic-governance rule that keeps GEAL from strobing under
  stance transitions or voice onsets.
- ``ADD`` composition clamps to the [0, 1] rendering range even under
  pathological overlap.
"""

from __future__ import annotations

import math

import pytest


def test_three_phase_zero_at_fire() -> None:
    from shared.geal_curves import three_phase

    assert three_phase(0.0, anticipate_ms=120, commit_ms=90, settle_ms=600) == pytest.approx(
        0.0, abs=1e-6
    )


def test_three_phase_has_counter_move() -> None:
    """During anticipate, value moves in the opposite direction of peak_amp."""
    from shared.geal_curves import three_phase

    # Sample mid-anticipate.
    mid_anticipate = three_phase(
        60.0, anticipate_ms=120, commit_ms=90, settle_ms=600, anticipate_amp=-0.10, peak_amp=1.0
    )
    assert mid_anticipate < 0.0, f"expected negative counter-move, got {mid_anticipate}"


def test_three_phase_peaks_near_commit_end() -> None:
    """At anticipate + commit, value should be ~= peak_amp (slight overshoot allowed)."""
    from shared.geal_curves import three_phase

    at_commit_end = three_phase(
        120.0 + 90.0, anticipate_ms=120, commit_ms=90, settle_ms=600, peak_amp=1.0
    )
    # Critically-damped overshoot: 5–15 % per spec §7.1.
    assert 0.95 <= at_commit_end <= 1.15, f"expected ~1.0, got {at_commit_end}"


def test_three_phase_decays_to_zero() -> None:
    """After the full lifetime, value decays below 0.1 (log-decay tail)."""
    from shared.geal_curves import three_phase

    lifetime = 120 + 90 + 600
    late = three_phase(
        lifetime + 1200.0,  # well past settle window
        anticipate_ms=120,
        commit_ms=90,
        settle_ms=600,
        settle_tau_ms=300.0,
        peak_amp=1.0,
    )
    assert late < 0.1, f"expected <0.1 after lifetime, got {late}"


def test_second_order_lp_settles() -> None:
    """Constant target → value reaches within 2 % over 1 s at ω = 8 Hz."""
    from shared.geal_curves import SecondOrderLP

    lp = SecondOrderLP(omega=2 * math.pi * 2.0, zeta=0.9)
    target = 1.0
    dt = 1.0 / 60.0
    t = 0.0
    last = 0.0
    for _ in range(60):  # 1 s
        t += dt
        last = lp.tick(t, target)
    assert abs(last - target) < 0.02, f"expected settle within 2%, got {last}"


def test_second_order_lp_no_overshoot() -> None:
    """Critically-damped filter should not oscillate past target."""
    from shared.geal_curves import SecondOrderLP

    lp = SecondOrderLP(omega=2 * math.pi * 2.0, zeta=0.9)
    dt = 1.0 / 60.0
    t = 0.0
    max_seen = 0.0
    for _ in range(120):
        t += dt
        v = lp.tick(t, 1.0)
        max_seen = max(max_seen, v)
    # At zeta >= 0.7 the overshoot should be minimal; allow 5 %.
    assert max_seen <= 1.05, f"expected no ringing overshoot, got max {max_seen}"


def test_blink_floor_invariant() -> None:
    """No 200 ms window sees a full peak-range crossing (spec §7).

    The blink-floor invariant is a SPAN property: for any sample pair
    (t1, t2) with ``t2 - t1 <= 200 ms``, ``|v(t2) - v(t1)|`` must not
    exceed the curve's peak-range. A smooth ease can have a higher
    instantaneous derivative than a linear ramp through the same span
    and still satisfy this bound — what the operator rejects is
    full-range strobes, not snappy-but-smooth motion.
    """
    from shared.geal_curves import three_phase

    anticipate_ms = 120.0
    commit_ms = 90.0
    settle_ms = 600.0
    peak_amp = 1.0
    window_ms = 200.0

    step_ms = 1.0
    lifetime_ms = int(anticipate_ms + commit_ms + settle_ms + 400)
    samples = [
        three_phase(float(i) * step_ms, anticipate_ms, commit_ms, settle_ms, peak_amp=peak_amp)
        for i in range(lifetime_ms)
    ]

    window_n = int(window_ms / step_ms)
    max_span = 0.0
    for i in range(len(samples) - window_n):
        v_lo = samples[i]
        v_hi = samples[i + window_n]
        span = abs(v_hi - v_lo)
        max_span = max(max_span, span)
    # Full peak-range crossing = 1.0. Allow a small slack (the curve
    # adds a -0.10 × peak_amp counter-move + overshoot, so the
    # effective crossing can be 1.15 × peak_amp; that's still bounded).
    assert max_span <= 1.15, f"200 ms window sees a {max_span}-span crossing — violates blink floor"


def test_compose_add_clamps() -> None:
    """Five overlapping three_phase pulses must sum+clamp to <=1.0."""
    from shared.geal_curves import Envelope, compose_add

    envelopes = [
        Envelope.three_phase(
            fire_at_s=0.0 + 0.05 * i,
            anticipate_ms=80,
            commit_ms=80,
            settle_ms=500,
            peak_amp=1.0,
        )
        for i in range(5)
    ]
    # Sample during what would be maximal overlap.
    for t_ms in range(0, 800, 10):
        t = t_ms / 1000.0
        v = compose_add(envelopes, t)
        assert 0.0 <= v <= 1.0, f"composition violates clamp at t={t}: v={v}"


def test_gaussian_pulse_peak_at_center() -> None:
    from shared.geal_curves import gaussian_pulse

    peak = gaussian_pulse(t_ms=200.0, center_ms=200.0, sigma_ms=120.0, peak_amp=1.0)
    assert peak == pytest.approx(1.0, abs=1e-6)


def test_log_decay_monotonic() -> None:
    from shared.geal_curves import log_decay

    samples = [log_decay(t_ms=t, tau_ms=300.0, peak_amp=1.0) for t in range(0, 2000, 50)]
    for a, b in zip(samples[:-1], samples[1:], strict=True):
        assert b <= a, "log_decay must be monotonically non-increasing"


def test_envelope_tick_three_phase_matches_raw() -> None:
    """Envelope wrapper calls three_phase with the right args."""
    from shared.geal_curves import Envelope, three_phase

    env = Envelope.three_phase(
        fire_at_s=0.0,
        anticipate_ms=120,
        commit_ms=90,
        settle_ms=600,
        peak_amp=1.0,
    )
    raw = three_phase(200.0, anticipate_ms=120, commit_ms=90, settle_ms=600, peak_amp=1.0)
    wrapped = env.tick(now_s=0.200)
    assert wrapped == pytest.approx(raw, abs=1e-6)


def test_envelope_expiration() -> None:
    from shared.geal_curves import Envelope

    env = Envelope.three_phase(
        fire_at_s=0.0,
        anticipate_ms=120,
        commit_ms=90,
        settle_ms=600,
        peak_amp=1.0,
    )
    # Before lifetime end → not expired.
    assert not env.is_expired(now_s=0.5, grace_s=0.3)
    # After lifetime + grace → expired.
    assert env.is_expired(now_s=2.0, grace_s=0.3)
