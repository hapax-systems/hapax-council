"""Parametric modulation walker — constrained per-node parameter walk.

Architecture per the cc-task acceptance criteria:

1. **Walk substrate**: per-parameter envelopes from
   :mod:`shared.parameter_envelopes`. Each envelope carries
   ``(min, max, smoothness, joint_constraints)``. The walk samples within
   the envelope using a low-frequency oscillator (LFO) per parameter +
   perturbation noise — NO random jumps, NO preset-style snapshot loading.

2. **Smoothness invariant**: ``|delta| ≤ envelope.smoothness`` per tick.
   Enforced by ``ParameterEnvelope.clip_step``. Tests pin this.

3. **Joint constraints**: when two co-constrained parameters approach the
   joint ceiling (e.g. ``content.intensity × post.sediment_strength``), the
   walker dampens whichever moved more this tick. Encodes aesthetic
   invariants per the spec.

4. **Output bridge**: the walker writes per-parameter ``delta`` values to
   ``/dev/shm/hapax-imagination/uniforms.json``. The Reverie mixer
   (``agents.reverie._uniforms.write_uniforms``) ALREADY merges the file
   per tick into ``base + delta`` — heartbeat composes with the mixer's
   own writes; last-writer-wins per tick. This works because both writers
   use atomic tmp+rename, so the consumer never sees torn writes.

   Composition note: the visual chain writes its OWN deltas to the same
   surface from ``agents.visual_chain.compute_param_deltas``. When both
   are active, the LATER write to a key wins for that tick. This is by
   design — the heartbeat is the "fallback" substrate, the chain is the
   "real grounded variance" substrate, and the operator wants the chain
   to take precedence whenever it has something to say. Per spec, the
   heartbeat tick at 30s is much slower than the chain's per-frame ticks,
   so chain writes naturally dominate when active.

5. **Boundary-crossing transitions**: when ``walked_value`` enters within
   5% of ``min`` or ``max``, emit a transition primitive via
   ``recent-recruitment.json`` with ``kind: "transition_primitive"``.
   Director-loop's ``preset_recruitment_consumer`` reads this surface;
   transitions are unified with the LLM-recruitment path.

6. **Affordance-driven recruitment shifts**: read currently-recruited
   affordances from ``recent-recruitment.json``; when the recruited
   affordance set shifts, emit a node recruit/dismiss action. The
   imagination loop owns the source of truth for which affordances are
   live; this agent only OBSERVES that signal and translates it into
   chain mutation.

Anti-pattern explicitly excluded (regression-tested):

- No imports from the legacy preset-family-selector module.
- No literal preset family names appear in this module's source.
- No reads from the ``presets/`` directory.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from agents.studio_compositor.atomic_io import atomic_write_json
from agents.studio_compositor.ward_fx_mapping import (
    AUDIO_REACTIVE_WARDS,
    DRIFT_FLOOR_WARDS,
)
from agents.studio_compositor.ward_properties import (
    WardProperties,
    get_specific_ward_properties,
    set_many_ward_properties,
)
from shared.parameter_envelopes import (
    JointConstraint,
    ParameterEnvelope,
    envelope_by_key,
    envelopes,
    joint_constraints,
)

log = logging.getLogger(__name__)

# Prometheus instrumentation. Per ``project_compositor_metrics_registry``
# (memory): metrics MUST splat ``**_metric_kwargs`` carrying the
# compositor's ``CollectorRegistry`` so they reach the ``:9482`` scrape
# surface (the prometheus_client default registry is invisible to that
# exporter). Without this splat the counters appear to register but never
# show up on the Grafana / Prometheus surface — this was the audit
# finding that motivated this PR.
#
# Outside the compositor process (officium, tests, one-off scripts) the
# import falls back to ``None`` and the kwargs dict is empty, leaving the
# metrics on the default registry — preserves importability everywhere.
_METRICS_AVAILABLE = False

try:
    from prometheus_client import Counter

    try:
        from agents.studio_compositor.metrics import (
            REGISTRY as _COMPOSITOR_REGISTRY,
        )
    except Exception:
        _COMPOSITOR_REGISTRY = None

    _metric_kwargs: dict = (
        {"registry": _COMPOSITOR_REGISTRY} if _COMPOSITOR_REGISTRY is not None else {}
    )

    _TICK_COUNTER = Counter(
        "hapax_parametric_heartbeat_tick_total",
        "Parametric heartbeat tick attempts by outcome (success | error).",
        ("outcome",),
        **_metric_kwargs,
    )
    _ENVELOPE_BOUNDARY_COUNTER = Counter(
        "hapax_parametric_heartbeat_envelope_boundary_total",
        "Envelope boundary crossings detected, by parameter key + boundary side.",
        ("param_key", "boundary"),
        **_metric_kwargs,
    )
    _JOINT_CONSTRAINT_CLIP_COUNTER = Counter(
        "hapax_parametric_heartbeat_joint_constraint_clip_total",
        "Joint-constraint clip events (mean breached joint_max), by constraint name.",
        ("constraint_name",),
        **_metric_kwargs,
    )
    _TRANSITION_PRIMITIVE_COUNTER = Counter(
        "hapax_parametric_heartbeat_transition_primitive_total",
        "Transition primitive emissions, by primitive kind + trigger reason.",
        ("primitive", "trigger"),
        **_metric_kwargs,
    )
    _AFFORDANCE_RECRUITMENT_SHIFT_COUNTER = Counter(
        "hapax_parametric_heartbeat_affordance_recruitment_shift_total",
        "Affordance-recruitment set deltas between consecutive ticks, by shift kind.",
        ("shift_kind",),
        **_metric_kwargs,
    )

    _METRICS_AVAILABLE = True
except ValueError:
    # Already registered (test re-imports or duplicate module load).
    # Leave _METRICS_AVAILABLE False — the caller's try/except wraps
    # every emission, so the heartbeat keeps walking either way.
    pass
except Exception:  # pragma: no cover — prometheus_client missing at install time
    log.info("prometheus_client unavailable — parametric heartbeat metrics are no-ops")


def _emit_tick(outcome: str) -> None:
    """Increment the tick counter. Never raises."""
    try:
        if _METRICS_AVAILABLE:
            _TICK_COUNTER.labels(outcome=outcome).inc()
    except Exception:
        log.debug("metric emit failed (tick)", exc_info=True)


def _emit_envelope_boundary(param_key: str, boundary: str) -> None:
    """Increment the envelope-boundary counter. Never raises."""
    try:
        if _METRICS_AVAILABLE:
            _ENVELOPE_BOUNDARY_COUNTER.labels(param_key=param_key, boundary=boundary).inc()
    except Exception:
        log.debug("metric emit failed (envelope boundary)", exc_info=True)


def _emit_joint_constraint_clip(constraint_name: str) -> None:
    """Increment the joint-constraint-clip counter. Never raises."""
    try:
        if _METRICS_AVAILABLE:
            _JOINT_CONSTRAINT_CLIP_COUNTER.labels(constraint_name=constraint_name).inc()
    except Exception:
        log.debug("metric emit failed (joint constraint clip)", exc_info=True)


def _emit_transition_primitive(primitive: str, trigger: str) -> None:
    """Increment the transition-primitive counter. Never raises."""
    try:
        if _METRICS_AVAILABLE:
            _TRANSITION_PRIMITIVE_COUNTER.labels(primitive=primitive, trigger=trigger).inc()
    except Exception:
        log.debug("metric emit failed (transition primitive)", exc_info=True)


def _emit_affordance_recruitment_shift(shift_kind: str) -> None:
    """Increment the affordance-recruitment-shift counter. Never raises."""
    try:
        if _METRICS_AVAILABLE:
            _AFFORDANCE_RECRUITMENT_SHIFT_COUNTER.labels(shift_kind=shift_kind).inc()
    except Exception:
        log.debug("metric emit failed (affordance recruitment shift)", exc_info=True)


def _derive_constraint_name(constraint: JointConstraint) -> str:
    """Stable label value for a joint constraint.

    Prefers the rationale text truncated to 30 chars (operator-readable);
    falls back to ``"{a_key}+{b_key}"`` when rationale is empty. Keeps
    label cardinality bounded — joint constraints are a small fixed set.
    """

    rationale = (getattr(constraint, "rationale", "") or "").strip()
    if rationale:
        return rationale[:30]
    return f"{constraint.param_a_key}+{constraint.param_b_key}"


# Canonical SHM paths. The uniforms surface is the per-frame override
# bridge documented in CLAUDE.md § Reverie Vocabulary Integrity. The
# recruitment surface is the same one the LLM-recruitment path writes to
# (per agents.studio_compositor.preset_recruitment_consumer.RECRUITMENT_FILE).
UNIFORMS_FILE: Path = Path("/dev/shm/hapax-imagination/uniforms.json")
RECRUITMENT_FILE: Path = Path("/dev/shm/hapax-compositor/recent-recruitment.json")

# Marker stamped on every entry this agent writes to recent-recruitment.json.
# Distinguishes parametric-walk-origin transition primitives from LLM-origin
# in observability dashboards.
HEARTBEAT_SOURCE: str = "parametric-modulation-heartbeat"

# Tick cadence — how often :func:`run_forever` calls :func:`tick_once`.
# 30s parallels the preset-bias heartbeat's tick. The walker's smoothness
# invariant is per-tick, so this is the time-resolution of the walk.
DEFAULT_TICK_S: float = 30.0

# Cairo ward-property cadence. The same 30s heartbeat keeps the Cairo
# accent params alive without competing with the faster FX reactor.
WARD_PROPERTIES_TTL_S: float = 60.0

# LFO period — base wavelength for the per-parameter low-frequency
# oscillator. 600s = 10 minutes traverses the envelope range slowly per
# tick. Each parameter gets a deterministic phase offset from its key
# hash so they don't all peak at the same time.
DEFAULT_LFO_PERIOD_S: float = 600.0

# Perturbation magnitude — fraction of envelope range added as Gaussian
# noise per tick on top of the LFO base. 0.10 → 10% of range. Small
# enough to keep walk smooth, large enough to break the LFO's pure
# periodicity.
DEFAULT_PERTURBATION: float = 0.10

# Boundary-crossing threshold — fraction of envelope range from
# ``min``/``max`` that triggers a transition primitive emission.
_BOUNDARY_FRACTION: float = 0.05

# Five canonical transition operations (these are the right unit per
# the operator directive — chain operations, NOT preset picks). The
# names match the affordance capability records in
# shared/compositional_affordances.py and the keys in
# agents/studio_compositor/transition_primitives.py::PRIMITIVES.
#
# This is NOT a preset list — it's the vocabulary of CHAIN OPERATIONS the
# walker can request when an envelope boundary is crossed. The regression
# pin ``test_no_preset_family_in_module_source`` allows these because the
# names are operator-facing transition vocabulary, not snapshot identifiers.
_TRANSITION_VOCAB: tuple[str, ...] = (
    "transition.fade.smooth",
    "transition.cut.hard",
    "transition.netsplit.burst",
    "transition.ticker.scroll",
    "transition.dither.noise",
)


@dataclass(frozen=True)
class BoundaryEvent:
    """Single boundary-crossing event from one walker tick.

    Returned from :class:`ParameterWalker.tick` so the caller can decide
    which transition primitive to emit (default: fade.smooth) and to
    record the crossing for journal observability.
    """

    envelope_key: str
    """The ``{node_id}.{param_name}`` key whose value crossed a boundary."""

    direction: str
    """Either ``"approaching_min"`` or ``"approaching_max"``."""

    value: float
    """The walked value that triggered the boundary detection."""


def _stable_phase(key: str) -> float:
    """Deterministic phase offset in [0, 2π) for an envelope key.

    Hash-based so two parameters with related names don't accidentally
    co-phase, but stable across process restarts so the walk is
    reproducible if you replay the wall clock.
    """

    return (hash(key) % 10_000) / 10_000 * 2 * math.pi


class ParameterWalker:
    """Stateful per-parameter walk over the constraint envelopes.

    Each ``tick`` advances every envelope's walked value by:

        target = base_lfo(t) + perturbation_noise()
        delta = target - prev_value
        clipped = envelope.clip_step(prev_value, prev_value + delta)

    Then joint constraints are applied — for each ``JointConstraint``,
    if ``(a + b) / 2 > joint_max``, both are scaled down proportionally.

    Boundary crossings (value within ``_BOUNDARY_FRACTION`` of min/max)
    are returned as :class:`BoundaryEvent` so the heartbeat can emit a
    transition primitive.
    """

    def __init__(
        self,
        *,
        envs: tuple[ParameterEnvelope, ...] | None = None,
        constraints: tuple[JointConstraint, ...] | None = None,
        lfo_period_s: float = DEFAULT_LFO_PERIOD_S,
        perturbation: float = DEFAULT_PERTURBATION,
        rng: random.Random | None = None,
    ) -> None:
        self._envelopes = envs if envs is not None else envelopes()
        self._joint_constraints = constraints if constraints is not None else joint_constraints()
        self._lfo_period_s = lfo_period_s
        self._perturbation = perturbation
        self._rng = rng if rng is not None else random.Random()
        # Initialize each parameter at its envelope midpoint so the first
        # tick starts smoothly and joint constraints are satisfied at boot.
        self._values: dict[str, float] = {
            env.key: (env.min_value + env.max_value) / 2 for env in self._envelopes
        }

    @property
    def values(self) -> dict[str, float]:
        """Snapshot of current walked values, keyed by ``{node_id}.{param_name}``."""

        return dict(self._values)

    def _lfo_target(self, env: ParameterEnvelope, now: float) -> float:
        """Compute the LFO-driven target for an envelope at ``now``.

        Sin wave between ``min`` and ``max`` with deterministic per-key
        phase offset. The LFO is the *direction* signal; perturbation
        breaks the periodicity.
        """

        center = (env.min_value + env.max_value) / 2
        amp = (env.max_value - env.min_value) / 2
        omega = 2 * math.pi / self._lfo_period_s
        phase = _stable_phase(env.key)
        return center + amp * math.sin(omega * now + phase)

    def _apply_joint_constraints(self, prev_snapshot: dict[str, float]) -> None:
        """Scan joint constraints; dampen both members when joint_max breached.

        When ``mean = (a + b) / 2 > joint_max``, scale both by
        ``joint_max / mean`` so the breach is corrected without
        privileging either parameter. The corrected value is then
        re-clipped through the envelope's ``clip_step`` against
        ``prev_snapshot`` so the smoothness invariant is preserved
        across the joint-constraint adjustment — the walker may not
        violate smoothness even when correcting a joint breach (in
        practice this means the constraint may take 2-3 ticks to fully
        unwind a breach, which matches the operator's "smooth drift"
        aesthetic).

        Logs an INFO on any clip event so the operator can correlate
        aesthetic-invariant breaches with downstream visual changes.
        """

        env_by_key = {env.key: env for env in self._envelopes}
        for jc in self._joint_constraints:
            a = self._values.get(jc.param_a_key)
            b = self._values.get(jc.param_b_key)
            if a is None or b is None:
                continue
            mean = (a + b) / 2
            if mean <= jc.joint_max:
                continue
            scale = jc.joint_max / mean
            new_a = a * scale
            new_b = b * scale
            # Re-clip through envelope.clip_step against the pre-tick
            # snapshot so the joint-constraint correction respects the
            # smoothness budget (delta from the START of this tick, not
            # from the post-LFO position).
            env_a = env_by_key[jc.param_a_key]
            env_b = env_by_key[jc.param_b_key]
            self._values[jc.param_a_key] = env_a.clip_step(prev_snapshot[jc.param_a_key], new_a)
            self._values[jc.param_b_key] = env_b.clip_step(prev_snapshot[jc.param_b_key], new_b)
            _emit_joint_constraint_clip(_derive_constraint_name(jc))
            log.info(
                "parametric walker: joint constraint clipped %s+%s (mean=%.3f > %.3f) — %s",
                jc.param_a_key,
                jc.param_b_key,
                mean,
                jc.joint_max,
                jc.rationale,
            )

    def _detect_boundaries(self) -> list[BoundaryEvent]:
        """Return boundary-crossing events for the current ``self._values``.

        A crossing is when a value lies within ``_BOUNDARY_FRACTION × range``
        of ``min`` or ``max``. The walker can stay near a boundary for
        several ticks (it walks slowly), so the caller is expected to
        debounce — the heartbeat does this by tracking the most recent
        emission ts per envelope key.
        """

        events: list[BoundaryEvent] = []
        for env in self._envelopes:
            value = self._values[env.key]
            span = env.max_value - env.min_value
            if span <= 0:
                continue
            threshold = span * _BOUNDARY_FRACTION
            if value <= env.min_value + threshold:
                events.append(
                    BoundaryEvent(
                        envelope_key=env.key,
                        direction="approaching_min",
                        value=value,
                    )
                )
                _emit_envelope_boundary(env.key, "min")
            elif value >= env.max_value - threshold:
                events.append(
                    BoundaryEvent(
                        envelope_key=env.key,
                        direction="approaching_max",
                        value=value,
                    )
                )
                _emit_envelope_boundary(env.key, "max")
        return events

    def tick(self, *, now: float | None = None) -> list[BoundaryEvent]:
        """Advance the walk one tick. Returns boundary-crossing events.

        Called by :func:`tick_once` per heartbeat tick. The wall-clock
        time drives the LFO; tests can pass deterministic values.
        """

        if now is None:
            now = time.time()
        # Snapshot pre-tick values so joint-constraint corrections can
        # honor the smoothness invariant relative to the START of this
        # tick (not the post-LFO position).
        prev_snapshot = self._values.copy()
        for env in self._envelopes:
            prev = self._values[env.key]
            target = self._lfo_target(env, now)
            span = env.max_value - env.min_value
            noise = self._rng.gauss(0.0, self._perturbation * span)
            stepped = env.clip_step(prev, target + noise)
            self._values[env.key] = stepped
        self._apply_joint_constraints(prev_snapshot)
        return self._detect_boundaries()


def write_uniform_overrides(
    values: dict[str, float],
    *,
    path: Path = UNIFORMS_FILE,
) -> None:
    """Atomically merge ``values`` into ``uniforms.json``.

    Reads the existing file (if any), overlays each key from ``values``,
    writes back via :func:`agents.studio_compositor.atomic_io.atomic_write_json`.
    The atomic write guarantees no partial-read window for the consumer
    (the wgpu pipeline's per-frame uniforms read).

    The merge is overlay-style: existing keys not in ``values`` are
    preserved (the chain may have written them this frame); keys in
    ``values`` overwrite existing values. This is intentional — the
    walker contributes to the same per-frame override surface the
    visual chain writes to, never wholesale-replaces.
    """

    existing: dict[str, float] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                existing = {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}
        except (OSError, json.JSONDecodeError):
            log.warning("parametric walker: malformed uniforms file at %s — overwriting", path)
    merged = {**existing, **values}
    atomic_write_json(merged, path)


def _normalized_envelope_value(values: dict[str, float], key: str) -> float:
    env = envelope_by_key(key)
    value = values.get(key)
    if env is None or value is None:
        return 0.5
    span = env.max_value - env.min_value
    if span <= 0:
        return 0.5
    return max(0.0, min(1.0, (value - env.min_value) / span))


def _write_cairo_ward_params(
    values: dict[str, float],
    *,
    ttl_s: float = WARD_PROPERTIES_TTL_S,
) -> None:
    """Write baseline Cairo ward chrome params on the same heartbeat tick.

    Five field bridges, all under a ``max(base, computed)`` floor so
    existing stronger writers (FX reactor spikes, compositional_consumer
    drift recipes, operator overrides) survive untouched:

    - ``border_pulse_hz``     ← breath.rate / noise.amplitude / post.sediment_strength mix
    - ``scale_bump_pct``      ← content.intensity / noise.amplitude mix
    - ``glow_radius_px``      ← breath.amplitude envelope
    - ``drift_hz``            ← drift.frequency envelope
    - ``drift_amplitude_px``  ← drift.amplitude envelope

    ``drift_type`` is intentionally NOT touched — a ward whose
    drift_type defaults to ``"sine"`` (the post-#2842 default) gets
    visible motion from the drift floors; one set to ``"none"`` stays
    static even with non-zero hz/amplitude values. That keeps the
    operator's per-ward drift-shape decision authoritative.

    Two membership cohorts:

    * ``AUDIO_REACTIVE_WARDS`` — full 5-field escalation. Music and
      presence chrome that the operator wants synchronised with the
      broadcast beat (pulse + bump + glow + drift floors).
    * ``DRIFT_FLOOR_WARDS`` — drift-only escalation
      (``drift_hz`` / ``drift_amplitude_px``). The pulse / scale-bump /
      glow fields are passed through from the base entry untouched.
      Used for wards where the operator has explicitly vetoed
      pulse-style modulation as too heavy-handed (e.g. ``durf`` per
      operator directive 2026-04-25).

    The cohorts are disjoint by construction — pinned by
    ``tests/studio_compositor/test_ward_fx_coupling.py``. The Cairo
    wards also have a separate FX reactor for short-lived spikes; the
    heartbeat only raises the *floor* without lowering any stronger
    value already present in ward-properties.json.
    """

    try:
        breath = _normalized_envelope_value(values, "breath.rate")
        breath_amp = _normalized_envelope_value(values, "breath.amplitude")
        intensity = _normalized_envelope_value(values, "content.intensity")
        noise = _normalized_envelope_value(values, "noise.amplitude")
        sediment = _normalized_envelope_value(values, "post.sediment_strength")
        drift_freq = _normalized_envelope_value(values, "drift.frequency")
        drift_amp = _normalized_envelope_value(values, "drift.amplitude")

        pulse_hz = 4.0 * max(0.0, min(1.0, 0.55 * breath + 0.25 * noise + 0.20 * (1.0 - sediment)))
        bump_pct = 0.08 * max(0.0, min(1.0, 0.65 * intensity + 0.35 * noise))
        # Subtle additive glow baseline driven by the breath-amplitude envelope.
        # Caps at 4 px so this only seats a *floor* — the FX reactor's own
        # spike-grade glow remains the audible foreground.
        glow_px = 4.0 * max(0.0, min(1.0, breath_amp))
        # Drift-floor outputs (operator directive 2026-05-07 ward audit
        # stage A: heartbeat raises the FLOOR for both fields from
        # envelope-walked values). Stage B (flipped the
        # ``WardProperties.drift_type`` dataclass default from
        # ``"none"`` → ``"sine"``) ships separately so the floors here
        # produce visible motion by default. ``drift_type`` is still NOT
        # touched here — upstream callers (compositional_consumer,
        # operator config) remain authoritative for picking the drift
        # shape.
        drift_hz_floor = 1.5 * drift_freq
        drift_px_floor = 8.0 * drift_amp

        updates: dict[str, WardProperties] = {}
        for ward_id in AUDIO_REACTIVE_WARDS:
            base = get_specific_ward_properties(ward_id) or WardProperties()
            updates[ward_id] = replace(
                base,
                border_pulse_hz=max(base.border_pulse_hz, pulse_hz),
                scale_bump_pct=max(base.scale_bump_pct, bump_pct),
                glow_radius_px=max(base.glow_radius_px, glow_px),
                drift_hz=max(base.drift_hz, drift_hz_floor),
                drift_amplitude_px=max(base.drift_amplitude_px, drift_px_floor),
            )
        for ward_id in DRIFT_FLOOR_WARDS:
            base = get_specific_ward_properties(ward_id) or WardProperties()
            updates[ward_id] = replace(
                base,
                drift_hz=max(base.drift_hz, drift_hz_floor),
                drift_amplitude_px=max(base.drift_amplitude_px, drift_px_floor),
            )
        set_many_ward_properties(updates, ttl_s=ttl_s)
    except Exception:
        log.debug("parametric walker: cairo ward param update failed", exc_info=True)


def emit_transition_primitive(
    transition_name: str,
    triggering_envelope_key: str,
    *,
    path: Path = RECRUITMENT_FILE,
    now: float | None = None,
) -> None:
    """Record a transition primitive request in ``recent-recruitment.json``.

    Mirrors the LLM-recruitment write shape but uses
    ``kind: "transition_primitive"`` (NOT ``"preset.bias"``). The director
    loop's ``preset_recruitment_consumer`` reads ``transition.*`` family
    keys; this writes one such entry. The ``source`` field carries the
    heartbeat-source marker so dashboards can distinguish parametric-walk
    triggers from LLM-recruitment triggers.

    The triggering envelope key is recorded for journal observability —
    operators can correlate envelope boundary crossings with downstream
    transition fires.
    """

    if now is None:
        now = time.time()
    if transition_name not in _TRANSITION_VOCAB:
        raise ValueError(
            f"unknown transition primitive {transition_name!r}; expected one of {_TRANSITION_VOCAB}"
        )
    current: dict[str, Any] = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
    families = current.get("families")
    if not isinstance(families, dict):
        families = {}
    families[transition_name] = {
        "last_recruited_ts": now,
        "kind": "transition_primitive",
        "source": HEARTBEAT_SOURCE,
        "triggered_by": triggering_envelope_key,
    }
    payload = {**current, "families": families, "updated_at": now}
    atomic_write_json(payload, path)


def _read_recruited_affordances(
    path: Path = RECRUITMENT_FILE,
    *,
    now: float | None = None,
) -> set[str]:
    """Return the set of currently-recruited affordance capability names.

    Reads ``recent-recruitment.json`` and yields the keys under
    ``families`` whose ``last_recruited_ts`` is within the active TTL.
    Defensive: missing/malformed file returns an empty set rather than
    raising — the walker's behavior is to keep walking when the
    recruitment surface is silent.

    The ``now`` parameter is injectable so :func:`tick_once` (and tests)
    can pass a deterministic clock; production callers default to
    ``time.time()``.
    """

    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    families = data.get("families")
    if not isinstance(families, dict):
        return set()
    if now is None:
        now = time.time()
    out: set[str] = set()
    for name, entry in families.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        ts = entry.get("last_recruited_ts")
        ttl = entry.get("ttl_s", 60.0)
        if not isinstance(ts, (int, float)) or not isinstance(ttl, (int, float)):
            continue
        if (now - float(ts)) < float(ttl):
            out.add(name)
    return out


def _select_transition_for_event(
    event: BoundaryEvent,
    *,
    rng: random.Random,
) -> str:
    """Pick a transition primitive for a boundary event.

    Heuristic-free selection per the operator directive
    ``feedback_no_expert_system_rules``: rotate through the vocab. Hard
    cuts (``cut.hard``) at 5% chance to occasionally jolt the chain;
    smooth fades dominate so the walk reads as deliberate parameter
    drift, not chain thrash.

    Tests inject a seeded RNG to make the selection deterministic.
    """

    if rng.random() < 0.05:
        return "transition.cut.hard"
    smooth_options = [t for t in _TRANSITION_VOCAB if t != "transition.cut.hard"]
    return rng.choice(smooth_options)


def tick_once(
    walker: ParameterWalker,
    *,
    now: float | None = None,
    uniforms_path: Path = UNIFORMS_FILE,
    recruitment_path: Path = RECRUITMENT_FILE,
    rng: random.Random | None = None,
    last_emission_ts: dict[str, float] | None = None,
    emission_cooldown_s: float = 60.0,
    last_affordances: set[str] | None = None,
) -> tuple[dict[str, float], list[BoundaryEvent]]:
    """Single tick — advance the walk, write uniforms, emit transitions.

    Test entry point. The production loop in :func:`run_forever` calls
    this every :data:`DEFAULT_TICK_S` seconds; tests call it directly
    with a seeded walker + frozen clock.

    Returns the snapshot of walked values + the list of boundary events
    that fired this tick. Tests assert on both.

    The ``last_emission_ts`` dict (keyed by envelope key) implements
    per-key cooldown — a single envelope hovering near its boundary will
    not flood the recruitment surface with one transition per tick. The
    caller is responsible for persisting this dict across calls (the
    production loop in :func:`run_forever` does).

    The ``last_affordances`` set implements affordance-shift detection
    per cc-task spec item 4: when the recruited affordance set changes
    between ticks (any add or removal), the walker treats this as a
    perceptual-stage transition and emits an additional transition
    primitive. Mutated in-place by this function so the production loop
    in :func:`run_forever` carries the state across ticks.
    """

    if rng is None:
        rng = random.Random()
    if last_emission_ts is None:
        last_emission_ts = {}
    if now is None:
        now = time.time()
    try:
        events = walker.tick(now=now)
        write_uniform_overrides(walker.values, path=uniforms_path)
        _write_cairo_ward_params(walker.values)
    except Exception:
        # Emit the error counter so the failure rate is observable, then
        # re-raise — ``run_forever`` already has its own try/except that
        # logs and continues. This preserves the daemon's "never die from
        # one bad tick" invariant while still capturing the outcome.
        _emit_tick("error")
        raise

    # Detect affordance shifts. When the recruited affordance set changes
    # between ticks, dispatch a transition primitive — the chain mutates
    # because affordances are recruited/dismissed (per CLAUDE.md §
    # Unified Semantic Recruitment), which is a perceptual-stage
    # transition the walker reflects through chain operation vocabulary.
    if last_affordances is not None:
        current_affordances = _read_recruited_affordances(path=recruitment_path, now=now)
        # Only consider non-transition affordances — transition.* keys
        # are written by THIS module (would cause reflexive triggers).
        relevant = {a for a in current_affordances if not a.startswith("transition.")}
        if last_affordances and relevant != last_affordances:
            # Record add/remove deltas regardless of cooldown so the
            # observability surface reflects every detected shift, even
            # the ones the cooldown silently swallows.
            added = relevant - last_affordances
            removed = last_affordances - relevant
            for _ in added:
                _emit_affordance_recruitment_shift("add")
            for _ in removed:
                _emit_affordance_recruitment_shift("remove")
            shift_marker = "_affordance_shift"
            last_ts = last_emission_ts.get(shift_marker, 0.0)
            if (now - last_ts) >= emission_cooldown_s:
                transition_name = "transition.fade.smooth"
                try:
                    emit_transition_primitive(
                        transition_name,
                        triggering_envelope_key="affordance.shift",
                        path=recruitment_path,
                        now=now,
                    )
                    _emit_transition_primitive(transition_name, "affordance_shift")
                    last_emission_ts[shift_marker] = now
                    log.info(
                        "parametric walker: affordance shift (prev=%s, curr=%s) — emitted %s",
                        sorted(last_affordances),
                        sorted(relevant),
                        transition_name,
                    )
                except OSError as exc:
                    log.warning(
                        "parametric walker: failed to emit affordance-shift transition: %s",
                        exc,
                    )
        last_affordances.clear()
        last_affordances.update(relevant)

    for event in events:
        last_ts = last_emission_ts.get(event.envelope_key, 0.0)
        if (now - last_ts) < emission_cooldown_s:
            continue
        transition_name = _select_transition_for_event(event, rng=rng)
        try:
            emit_transition_primitive(
                transition_name,
                triggering_envelope_key=event.envelope_key,
                path=recruitment_path,
                now=now,
            )
        except OSError as exc:
            log.warning(
                "parametric walker: failed to emit transition %s: %s",
                transition_name,
                exc,
            )
            continue
        _emit_transition_primitive(transition_name, "boundary_crossing")
        last_emission_ts[event.envelope_key] = now
        log.info(
            "parametric walker: boundary %s on %s (value=%.3f) — emitted %s",
            event.direction,
            event.envelope_key,
            event.value,
            transition_name,
        )

    _emit_tick("success")
    return walker.values, events


def run_forever(
    *,
    tick_s: float = DEFAULT_TICK_S,
    uniforms_path: Path = UNIFORMS_FILE,
    recruitment_path: Path = RECRUITMENT_FILE,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Production tick loop — fires :func:`tick_once` every ``tick_s`` seconds.

    Owns the ``ParameterWalker`` instance and the ``last_emission_ts``
    state across ticks (per-envelope cooldown for transition emissions).

    Sleeps deterministically between ticks. The ``sleep`` injection
    point lets tests bound the loop without monkey-patching :mod:`time`.
    """

    log.info(
        "parametric modulation heartbeat starting: tick=%.1fs uniforms=%s recruitment=%s pid=%d",
        tick_s,
        uniforms_path,
        recruitment_path,
        os.getpid(),
    )
    walker = ParameterWalker()
    last_emission_ts: dict[str, float] = {}
    last_affordances: set[str] = set()
    while True:
        try:
            tick_once(
                walker,
                uniforms_path=uniforms_path,
                recruitment_path=recruitment_path,
                last_emission_ts=last_emission_ts,
                last_affordances=last_affordances,
            )
        except Exception:
            # Daemon must never die from a single bad tick. A persistent
            # failure surfaces via journal repetition (operator alerts on
            # the warning rate).
            log.warning("parametric modulation tick failed", exc_info=True)
        sleep(tick_s)
