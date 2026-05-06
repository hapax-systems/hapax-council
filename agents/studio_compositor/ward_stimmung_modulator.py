"""Continuous imagination-dim → ward-property modulator (~5 Hz).

Phase 2 of ``docs/superpowers/specs/2026-04-21-ward-stimmung-modulator-design.md``.
Reads ``/dev/shm/hapax-imagination/current.json`` every sixth fx tick
(~5 Hz at 30 Hz fx cadence), computes per-ward depth attenuation for
non-default-plane wards, and writes bounded ``z_index_float`` + ``alpha``
deltas to the ward-properties SHM. Default-plane (``"on-scrim"``) wards
are not touched so director / recruitment authority is preserved.

Default-off behind ``HAPAX_WARD_MODULATOR_ACTIVE=1``. The instance is
constructed unconditionally so production deploys can flip the flag
without restarting the compositor.

Phase 3 will add per-plane ``drift_amplitude_px`` and route per-plane
colorgrade tint through the Reverie GPU node (depends on scrim Phase 2).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from agents.studio_compositor.ward_fx_mapping import WARD_DOMAIN
from agents.studio_compositor.ward_properties import (
    WardProperties,
    get_specific_ward_properties,
    set_ward_properties,
)
from agents.studio_compositor.z_plane_constants import (
    _Z_INDEX_BASE,
    WARD_Z_PLANE_DEFAULTS,
)

log = logging.getLogger(__name__)

CURRENT_PATH: Path = Path("/dev/shm/hapax-imagination/current.json")
# Imagination loop writes ``current.json`` at LLM cadence — empirically
# 30s–15min between fragments depending on TabbyAPI completion + reverberation.
# The 10s default that shipped with Phase 2 left the modulator in stale-fallback
# almost continuously; 120s tracks the long tail of fragment cadence.
STALENESS_S: float = 120.0
STALENESS_ENV: str = "HAPAX_WARD_MODULATOR_STALENESS_S"
# 2026-04-23 raised 0.4 → 2.5s. The earlier 0.4s TTL caused the 500 ms
# sinewave blink operator flagged: modulator ticks at ~200 ms (tick_every_n=6
# at 30 Hz fx cadence), so with TTL=0.4s any jitter in tick scheduling let
# the ward-properties entry expire BETWEEN writes — alpha decayed to the
# default 1.0 for a frame, producing a visible flash. TTL=2.5s covers
# ~12 tick cycles worth of slack, so entries never expire between writes.
# Combined with the MIN_DELTA epsilon below, this eliminates both sources
# of 5 Hz alpha churn.
WARD_PROPERTIES_TTL_S: float = 2.5
TICK_EVERY_N: int = 6
# 2026-04-23 blink-kill: only write if the new value is meaningfully
# different from what's in the existing ward-properties snapshot. 0.02
# (2% of the [0,1] range) kills micro-oscillation from imagination-depth
# jitter, while still letting meaningful state shifts propagate on the
# next tick. Epsilon applied to alpha AND z_index_float.
MIN_DELTA: float = 0.02
ENABLE_ENV: str = "HAPAX_WARD_MODULATOR_ACTIVE"
# At ~5 Hz, 0.16 alpha/tick crosses a 0.5 alpha span in ~600 ms:
# fast enough to read as live response, slow enough to avoid hard pops.
MAX_ALPHA_STEP: float = 0.16
# 2026-05-06 variance recovery: z-plane movement was reading over-damped
# after the blink-kill pass. Raising only the depth envelope restores
# spatial variance while leaving alpha untouched; through blit_with_depth
# this is still at most ~1.5% opacity multiplier movement per 5 Hz tick.
MAX_Z_INDEX_STEP: float = 0.18
MAX_ALPHA_STEP_ENV: str = "HAPAX_WARD_MODULATOR_MAX_ALPHA_STEP"
MAX_Z_INDEX_STEP_ENV: str = "HAPAX_WARD_MODULATOR_MAX_Z_INDEX_STEP"
# Variance recovery after smoothing: amplify mid-range depth excursions
# before mapping them to bounded alpha targets. The downstream MAX_*_STEP
# envelope still limits per-tick motion, and alpha remains clamped [0, 1].
DEPTH_CONTRAST: float = 1.18
DEPTH_CONTRAST_MIN: float = 0.5
DEPTH_CONTRAST_MAX: float = 1.6
DEPTH_CONTRAST_ENV: str = "HAPAX_WARD_MODULATOR_DEPTH_CONTRAST"


@dataclass
class WardStimmungModulator:
    """Per-fx-tick callable that runs the modulator at ~5 Hz."""

    current_path: Path = CURRENT_PATH
    ward_properties_ttl_s: float = WARD_PROPERTIES_TTL_S
    tick_every_n: int = TICK_EVERY_N
    _tick_counter: int = 0

    def maybe_tick(self) -> None:
        """Increment the tick counter and run when the divisor lands.

        Returns immediately when ``HAPAX_WARD_MODULATOR_ACTIVE`` is unset
        (the default) so existing deploys see no behavior change. Any
        exception inside :meth:`_run` is swallowed; the modulator must
        never raise into ``fx_tick_callback``.
        """
        if not _modulator_enabled():
            return
        self._tick_counter += 1
        if self._tick_counter < self.tick_every_n:
            return
        self._tick_counter = 0
        try:
            self._run()
        except Exception:
            log.debug("ward stimmung modulator tick failed", exc_info=True)

    def _run(self) -> None:
        dims = self._read_dims()
        if dims is None:
            _emit_modulator_stale()
            return
        for ward_id in WARD_DOMAIN:
            existing = get_specific_ward_properties(ward_id)
            base = existing or WardProperties()
            # Apply spec §4 default z-plane assignment when no override
            # exists (or override is on the default plane). Director
            # ``placement_bias`` and recruitment metadata still take
            # precedence — both write z_plane explicitly to non-default,
            # which we honor below.
            if base.z_plane == "on-scrim":
                default_plane = WARD_Z_PLANE_DEFAULTS.get(ward_id)
                if default_plane is not None:
                    base = replace(base, z_plane=default_plane)
            updated = self._apply_dims(base, dims)
            if updated is base and existing is not None:
                continue
            set_ward_properties(ward_id, updated, ttl_s=self.ward_properties_ttl_s)
            _emit_depth_attenuation(updated.z_plane, updated.z_index_float)
        _emit_modulator_tick()
        _emit_z_plane_counts()

    def _read_dims(self) -> dict[str, Any] | None:
        try:
            raw = json.loads(self.current_path.read_text(encoding="utf-8"))
        except Exception:
            log.debug("modulator: current.json read failed", exc_info=True)
            return None
        if not isinstance(raw, dict):
            log.debug(
                "modulator: current.json root is %s, expected mapping",
                type(raw).__name__,
            )
            return None
        ts = raw.get("timestamp")
        if isinstance(ts, (int, float)) and (time.time() - float(ts)) > _staleness_cutoff():
            return None
        dims = raw.get("dimensions")
        if not isinstance(dims, dict):
            return None
        return dims

    def _apply_dims(
        self,
        base: WardProperties,
        dims: dict[str, Any],
    ) -> WardProperties:
        """Compute the new ``WardProperties`` for a ward.

        Phase 2 contract:
        - Modulator MUST NOT touch ``z_plane`` (precedence §7).
        - Modulator only writes bounded ``z_index_float`` and ``alpha``
          deltas for wards on non-default planes. Default-plane
          (``"on-scrim"``) wards are owned by director / reactor and
          untouched.
        - Returns ``base`` unchanged when no field shifts; the caller
          uses identity equality to skip the SHM write.
        """
        z_plane = base.z_plane
        if z_plane == "on-scrim":
            return base
        depth_val = _contrast_depth(_clip01(_safe_float(dims.get("depth"), 0.5)))
        coherence_val = _clip01(_safe_float(dims.get("coherence"), 0.5))
        z_base = _Z_INDEX_BASE.get(z_plane, _Z_INDEX_BASE["on-scrim"])
        # Coherence pulls deeper-plane wards forward at high coherence
        # (convergence) and pushes them back at low coherence (divergence).
        convergence = (coherence_val - 0.5) * 0.2
        # Depth dim attenuates beyond/mid-scrim alpha continuously.
        if z_plane == "beyond-scrim":
            target_alpha = _clip01(0.5 + 0.5 * (1.0 - depth_val))
        elif z_plane == "mid-scrim":
            target_alpha = _clip01(0.7 + 0.3 * (1.0 - depth_val))
        else:  # "surface-scrim"
            target_alpha = _clip01(base.alpha)
        target_z_idx = _clip01(z_base - convergence)
        current_alpha = _clip01(base.alpha)
        current_z_idx = _clip01(base.z_index_float)
        new_alpha = _bounded_step(current_alpha, target_alpha, _max_alpha_step())
        new_z_idx = _bounded_step(current_z_idx, target_z_idx, _max_z_index_step())
        # 2026-04-23 blink-kill: epsilon-gate. Only write if the new
        # alpha / z_index has moved by at least MIN_DELTA (0.02 of the
        # [0,1] range) since the last resolved value. The previous
        # 1e-6 threshold made every micro-jitter in imagination depth
        # trigger a SHM rewrite, which — combined with the prior 0.4s
        # TTL — produced visible 5 Hz alpha oscillation.
        if (
            abs(new_alpha - base.alpha) < MIN_DELTA
            and abs(new_z_idx - base.z_index_float) < MIN_DELTA
        ):
            return base
        return replace(base, alpha=new_alpha, z_index_float=new_z_idx)


def _modulator_enabled() -> bool:
    return os.environ.get(ENABLE_ENV, "0") == "1"


def _staleness_cutoff() -> float:
    raw = os.environ.get(STALENESS_ENV)
    if raw is None:
        return STALENESS_S
    try:
        value = float(raw)
    except ValueError:
        return STALENESS_S
    return value if value > 0.0 else STALENESS_S


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _max_alpha_step() -> float:
    return _positive_env_float(MAX_ALPHA_STEP_ENV, MAX_ALPHA_STEP)


def _max_z_index_step() -> float:
    return _positive_env_float(MAX_Z_INDEX_STEP_ENV, MAX_Z_INDEX_STEP)


def _depth_contrast() -> float:
    return _bounded_env_float(
        DEPTH_CONTRAST_ENV,
        DEPTH_CONTRAST,
        min_value=DEPTH_CONTRAST_MIN,
        max_value=DEPTH_CONTRAST_MAX,
    )


def _contrast_depth(depth: float) -> float:
    depth = _clip01(depth)
    return _clip01(0.5 + (depth - 0.5) * _depth_contrast())


def _bounded_env_float(name: str, default: float, *, min_value: float, max_value: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


def _positive_env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0.0 else default


def _bounded_step(current: float, target: float, max_delta: float) -> float:
    current = _clip01(current)
    target = _clip01(target)
    if abs(target - current) <= max_delta:
        return target
    if target > current:
        return _clip01(current + max_delta)
    return _clip01(current - max_delta)


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _emit_modulator_tick() -> None:
    try:
        from agents.studio_compositor import metrics as _m

        if _m.HAPAX_WARD_MODULATOR_TICK_TOTAL is not None:
            _m.HAPAX_WARD_MODULATOR_TICK_TOTAL.inc()
    except Exception:
        pass


def _emit_modulator_stale() -> None:
    try:
        from agents.studio_compositor import metrics as _m

        if _m.HAPAX_WARD_MODULATOR_STALE_TOTAL is not None:
            _m.HAPAX_WARD_MODULATOR_STALE_TOTAL.inc()
    except Exception:
        pass


def _emit_depth_attenuation(z_plane: str, z_index_float: float) -> None:
    try:
        from agents.studio_compositor import metrics as _m

        if _m.HAPAX_WARD_DEPTH_ATTENUATION is not None:
            _m.HAPAX_WARD_DEPTH_ATTENUATION.labels(z_plane=z_plane, driving_dim="depth").observe(
                z_index_float
            )
    except Exception:
        pass


def _emit_z_plane_counts() -> None:
    """Refresh per-plane ward counts based on the current SHM snapshot."""
    try:
        from agents.studio_compositor import metrics as _m
        from agents.studio_compositor.ward_properties import all_resolved_properties

        gauge = _m.HAPAX_WARD_Z_PLANE_COUNT
        if gauge is None:
            return
        counts: dict[str, int] = {}
        for props in all_resolved_properties().values():
            counts[props.z_plane] = counts.get(props.z_plane, 0) + 1
        for plane in ("beyond-scrim", "mid-scrim", "on-scrim", "surface-scrim"):
            gauge.labels(z_plane=plane).set(counts.get(plane, 0))
    except Exception:
        pass


__all__ = [
    "CURRENT_PATH",
    "ENABLE_ENV",
    "STALENESS_ENV",
    "STALENESS_S",
    "TICK_EVERY_N",
    "WARD_PROPERTIES_TTL_S",
    "WardStimmungModulator",
]
