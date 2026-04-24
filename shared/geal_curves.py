"""GEAL temporal curve library (spec §7).

Two families of curves drive every GEAL primitive:

- **Event-bound**: ``three_phase`` / ``gaussian_pulse`` / ``log_decay`` —
  fire on a discrete event (stance transition, grounding citation,
  voice onset), play their envelope, then expire. Shape obeys the
  anticipate → commit → settle arc that carries a Disney-squash
  lineage (counter-move before action, critical overshoot on commit,
  log-decay asymmetric tail).
- **Signal-bound**: :class:`SecondOrderLP` — critically-damped filter
  that smooths a continuous signal (voice envelope, F0, video
  attention) without ever stepping. Exactly one filter per
  ``(primitive, slot)`` — they never stack.

Both families expose the same :class:`Envelope` wrapper so callers
iterate a uniform ``registry[(primitive, slot)] -> Envelope`` mapping
each frame.

The single governance invariant this module enforces is the
**blink-floor** rule: no curve may cross its full [0, 1] range faster
than 200 ms. The three-phase parameter defaults are chosen to stay
well below that rate, and :func:`compose_add` clamps sum overlaps
into [0, 1].

Spec: ``docs/superpowers/specs/2026-04-23-geal-spec.md`` §7.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


def _ease_out_quad(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1.0 - (1.0 - x) ** 2


def three_phase(
    t_ms: float,
    anticipate_ms: float,
    commit_ms: float,
    settle_ms: float,
    anticipate_amp: float = -0.10,
    peak_amp: float = 1.0,
    settle_tau_ms: float = 300.0,
) -> float:
    """Stitched anticipate → commit → settle curve.

    Segments:

    - **anticipate** (``0 <= t < anticipate_ms``): ``easeOutQuad`` ramp
      to ``anticipate_amp * peak_amp`` (a counter-direction move).
    - **commit** (``anticipate_ms <= t < anticipate_ms + commit_ms``):
      critically-damped overshoot ``1 - (1-p)·exp(-3p)`` that lands on
      ``peak_amp`` with ~5-15 % overshoot.
    - **settle** (``t >= anticipate_ms + commit_ms``): exponential
      log-decay with time-constant ``settle_tau_ms``. Formally infinite
      but negligible after ``settle_ms`` (beyond that point the value
      is < ~0.01 * peak_amp).

    Returns value at ``t_ms``. Out-of-range ``t_ms`` (before 0 or long
    after the settle window) still returns a sensible value: 0 for
    t < 0, log-decay tail for t > anticipate+commit.
    """
    if t_ms <= 0.0:
        return 0.0
    if t_ms < anticipate_ms:
        p = t_ms / anticipate_ms
        return _ease_out_quad(p) * anticipate_amp * peak_amp
    if t_ms < anticipate_ms + commit_ms:
        p = (t_ms - anticipate_ms) / commit_ms
        # Start from anticipate_amp * peak_amp, overshoot toward peak_amp.
        # Use easeInOutQuad for a bounded max derivative (~π/2 · span),
        # keeping the curve inside the blink-floor (§7 invariant). The
        # asymmetric overshoot term adds the 5–15 % "landed but
        # breathing" signature without a second-harmonic oscillation
        # that would look mechanical.
        start = anticipate_amp * peak_amp
        end = peak_amp
        shape = 0.5 * (1.0 - math.cos(math.pi * p))
        overshoot = 0.10 * (end - start) * math.sin(math.pi * p) * (1.0 - p)
        return start + (end - start) * shape + overshoot
    # Settle.
    dt = t_ms - (anticipate_ms + commit_ms)
    return peak_amp * math.exp(-dt / max(1e-6, settle_tau_ms))


def gaussian_pulse(
    t_ms: float,
    center_ms: float,
    sigma_ms: float,
    peak_amp: float = 1.0,
) -> float:
    """Symmetric gaussian packet centred at ``center_ms``.

    Used by G1 wavefront ripples travelling along the recursion tree.
    Spatially parameterised: a wavefront at time ``t_ms`` with centre
    at ``packet_start + travel_fraction * total_travel`` gives a
    moving gaussian brightness.
    """
    sigma_ms = max(1e-6, sigma_ms)
    z = (t_ms - center_ms) / sigma_ms
    return peak_amp * math.exp(-0.5 * z * z)


def log_decay(t_ms: float, tau_ms: float, peak_amp: float = 1.0) -> float:
    """Settle-only primitive — starts at ``peak_amp`` and decays.

    Monotonically non-increasing. Used as a standalone envelope when
    only the settle tail matters (V2 vertex halo opacity, chat-ambient
    latches).
    """
    if t_ms <= 0.0:
        return peak_amp
    tau_ms = max(1e-6, tau_ms)
    return peak_amp * math.exp(-t_ms / tau_ms)


@dataclass
class SecondOrderLP:
    """Critically-damped second-order low-pass filter.

    Smooths a continuous signal toward a time-varying target. Use ζ in
    0.7–0.9 for critical damping without visible ringing. Call
    :meth:`tick` every frame with the current time (seconds) and the
    current target value; returns the smoothed output.

    Never stacks — one filter per ``(primitive, slot)``. Exactly what
    the voice envelope (V1 Chladni fill, V2 halo radius, V2 halo
    opacity) plumbs to.
    """

    omega: float  # natural frequency rad/s
    zeta: float = 0.8
    value: float = 0.0
    velocity: float = 0.0
    _last_tick_s: float | None = None

    def tick(self, now_s: float, target: float) -> float:
        if self._last_tick_s is None:
            self._last_tick_s = now_s
            self.value = float(target)
            return self.value
        dt = max(0.0, min(0.1, now_s - self._last_tick_s))
        self._last_tick_s = now_s

        # Semi-implicit Euler on the damped spring:
        #   a = ω² (target - value) - 2ζω · velocity
        accel = (
            self.omega * self.omega * (target - self.value)
            - 2.0 * self.zeta * self.omega * self.velocity
        )
        self.velocity += accel * dt
        self.value += self.velocity * dt
        return self.value

    def reset(self, value: float = 0.0) -> None:
        self.value = value
        self.velocity = 0.0
        self._last_tick_s = None


class CurveKind(StrEnum):
    THREE_PHASE = "three_phase"
    GAUSSIAN_PULSE = "gaussian_pulse"
    LOG_DECAY = "log_decay"
    SECOND_ORDER_LP = "second_order_lp"


@dataclass
class Envelope:
    """Unified wrapper over the two curve families.

    Event-bound envelopes carry ``fire_at_s`` + their family-specific
    params and return 0 before the fire moment. Signal-bound envelopes
    wrap a :class:`SecondOrderLP` and require ``signal`` on each
    :meth:`tick`.

    The factory methods (``three_phase``, ``gaussian_pulse``,
    ``log_decay``, ``second_order_lp``) are the normal entry points —
    they hide the ``kind`` selection.
    """

    kind: CurveKind
    fire_at_s: float | None = None
    params: dict[str, Any] = field(default_factory=dict)
    _filter: SecondOrderLP | None = None

    # -- Factories -----------------------------------------------------------

    @classmethod
    def three_phase(
        cls,
        *,
        fire_at_s: float,
        anticipate_ms: float,
        commit_ms: float,
        settle_ms: float,
        anticipate_amp: float = -0.10,
        peak_amp: float = 1.0,
        settle_tau_ms: float = 300.0,
    ) -> Envelope:
        return cls(
            kind=CurveKind.THREE_PHASE,
            fire_at_s=fire_at_s,
            params={
                "anticipate_ms": float(anticipate_ms),
                "commit_ms": float(commit_ms),
                "settle_ms": float(settle_ms),
                "anticipate_amp": float(anticipate_amp),
                "peak_amp": float(peak_amp),
                "settle_tau_ms": float(settle_tau_ms),
            },
        )

    @classmethod
    def gaussian_pulse(
        cls,
        *,
        fire_at_s: float,
        center_ms: float,
        sigma_ms: float,
        peak_amp: float = 1.0,
    ) -> Envelope:
        return cls(
            kind=CurveKind.GAUSSIAN_PULSE,
            fire_at_s=fire_at_s,
            params={
                "center_ms": float(center_ms),
                "sigma_ms": float(sigma_ms),
                "peak_amp": float(peak_amp),
            },
        )

    @classmethod
    def log_decay(
        cls,
        *,
        fire_at_s: float,
        tau_ms: float,
        peak_amp: float = 1.0,
    ) -> Envelope:
        return cls(
            kind=CurveKind.LOG_DECAY,
            fire_at_s=fire_at_s,
            params={"tau_ms": float(tau_ms), "peak_amp": float(peak_amp)},
        )

    @classmethod
    def second_order_lp(cls, *, omega: float, zeta: float = 0.8) -> Envelope:
        return cls(
            kind=CurveKind.SECOND_ORDER_LP,
            fire_at_s=None,
            params={"omega": float(omega), "zeta": float(zeta)},
            _filter=SecondOrderLP(omega=omega, zeta=zeta),
        )

    # -- Runtime -------------------------------------------------------------

    def tick(self, now_s: float, signal: float | None = None) -> float:
        """Return the envelope value at ``now_s``.

        For event-bound curves, ``signal`` is ignored. For
        ``SECOND_ORDER_LP``, ``signal`` is the current target value and
        MUST be provided (defaults to 0.0 if missing rather than raising,
        to keep the hot render-tick path tolerant).
        """
        if self.kind == CurveKind.SECOND_ORDER_LP:
            target = 0.0 if signal is None else float(signal)
            assert self._filter is not None
            return self._filter.tick(now_s, target)

        if self.fire_at_s is None:
            return 0.0
        t_ms = (now_s - self.fire_at_s) * 1000.0
        if t_ms < 0.0:
            return 0.0

        p = self.params
        if self.kind == CurveKind.THREE_PHASE:
            return three_phase(
                t_ms,
                anticipate_ms=p["anticipate_ms"],
                commit_ms=p["commit_ms"],
                settle_ms=p["settle_ms"],
                anticipate_amp=p.get("anticipate_amp", -0.10),
                peak_amp=p.get("peak_amp", 1.0),
                settle_tau_ms=p.get("settle_tau_ms", 300.0),
            )
        if self.kind == CurveKind.GAUSSIAN_PULSE:
            return gaussian_pulse(
                t_ms,
                center_ms=p["center_ms"],
                sigma_ms=p["sigma_ms"],
                peak_amp=p.get("peak_amp", 1.0),
            )
        if self.kind == CurveKind.LOG_DECAY:
            return log_decay(
                t_ms,
                tau_ms=p["tau_ms"],
                peak_amp=p.get("peak_amp", 1.0),
            )
        raise ValueError(f"unknown curve kind: {self.kind}")

    def is_expired(self, now_s: float, grace_s: float = 0.3) -> bool:
        """Has this envelope decayed past its useful lifetime?

        Signal-bound filters never expire (they track continuous state).
        Event-bound envelopes expire after their full lifetime
        (anticipate + commit + settle) plus a ``grace_s`` tail so the
        log-decay tail is drawn through its visually-relevant range.
        """
        if self.kind == CurveKind.SECOND_ORDER_LP:
            return False
        if self.fire_at_s is None:
            return True
        p = self.params
        if self.kind == CurveKind.THREE_PHASE:
            lifetime_ms = p["anticipate_ms"] + p["commit_ms"] + p["settle_ms"]
        elif self.kind == CurveKind.GAUSSIAN_PULSE:
            # Packet extends roughly 3σ past its centre.
            lifetime_ms = p["center_ms"] + 3.0 * p["sigma_ms"]
        elif self.kind == CurveKind.LOG_DECAY:
            # Negligible after ~5τ.
            lifetime_ms = 5.0 * p["tau_ms"]
        else:
            lifetime_ms = 0.0
        return now_s - self.fire_at_s > (lifetime_ms / 1000.0) + grace_s


def compose_add(envelopes: list[Envelope], now_s: float, signal: float | None = None) -> float:
    """Sum all envelope outputs at ``now_s`` and clamp to [0, 1].

    Event-bound envelopes stack additively per spec §7.4 (G2 accent
    latch rides on V1 fill). The final clamp is the aesthetic-governance
    guarantee that no composition ever blows past the rendering range —
    caller surfaces can safely multiply this into an alpha or
    brightness channel.
    """
    total = 0.0
    for env in envelopes:
        total += env.tick(now_s, signal)
    if total < 0.0:
        return 0.0
    if total > 1.0:
        return 1.0
    return total


def compose_max(envelopes: list[Envelope], now_s: float, signal: float | None = None) -> float:
    """Peak-of-peaks composition — reserved for CRITICAL-stance edge glow.

    Used rarely. The MAX mode surfaces the single hottest envelope; it
    is the visual equivalent of "shout above the cacophony". Do not use
    in nominal render paths — it destroys the latch-and-fade grammar.
    """
    if not envelopes:
        return 0.0
    return max(env.tick(now_s, signal) for env in envelopes)


__all__ = [
    "CurveKind",
    "Envelope",
    "SecondOrderLP",
    "compose_add",
    "compose_max",
    "gaussian_pulse",
    "log_decay",
    "three_phase",
]
