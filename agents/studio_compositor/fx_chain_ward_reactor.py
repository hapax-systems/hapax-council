"""Ward ↔ FX reactor — glues the :mod:`shared.ward_fx_bus` to the compositor.

HOMAGE Phase 6 Layer 5 — implements the two directions of the bidirectional
ward↔FX coupling the operator called for on 2026-04-19:

Direction 1 — ward FSM → FX chain
    * ``ABSENT_TO_ENTERING`` / ``EMPHASIZED_TO_EXITING`` events flash the
      FX chain in the ward's domain accent for ~300ms by writing a bloom
      boost + chromatic aberration into ``uniforms.json``.
    * ``HOLD_TO_EMPHASIZED`` events boost ``temporal_distortion`` and
      ``spectral_color`` by 10–20% for the emphasis window.
    * Preset-family bias: on ENTERING events, write the ward's
      domain-biased family name to ``recent-recruitment.json`` so
      ``preset_family_selector`` picks from the family at its next
      within-family rotation.
    * ``EXITING`` events gently fade the modulated uniform keys toward
      baseline so the next frame doesn't stick at peak values.

Direction 2 — FX chain → ward
    * ``preset_family_change`` → every ward gets a 0.5s accent-pulse
      via ``ward_properties.set_ward_properties`` (``border_pulse_hz``).
    * ``audio_kick_onset`` → audio-reactive wards (see
      :mod:`ward_fx_mapping`) get a single-frame ``scale_bump_pct``
      AND a single-cycle ``border_pulse_hz`` flash. The scale_bump
      path is currently a no-op in the painter (see
      ``ward_properties.py:444`` — disabled until the canvas-safe
      scale clamp lands); the border-pulse path is the visible
      audio-coupling channel for kicks until then.
    * ``chain_swap`` → ``token_pole`` + ``activity_variety_log`` get a
      brief ``scale`` bump.
    * ``intensity_spike`` → audio-reactive wards boost ``border_pulse_hz``.

Reverie (HomageSubstrateSource) is exempt from FSM transitions but
receives a subtle intensity-boost payload (via the existing
``/dev/shm/hapax-compositor/homage-substrate-package.json`` path) on
every ENTERING event peak — the reactor writes a small
``reverie_intensity_boost`` float that the substrate-source consumer
reads without touching the FSM.

Non-destructive overlay clamp (#157) still applies: the reactor never
boosts ward alpha; the prominence emerges from the background FX
modulation instead.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from agents.studio_compositor.ward_fx_mapping import (
    DOMAIN_PRESET_FAMILY,
    preset_family_for_domain,
)
from agents.studio_compositor.ward_properties import (
    WardProperties,
    get_specific_ward_properties,
    set_many_ward_properties,
    set_ward_properties,
)
from shared.ward_fx_bus import (
    FXEvent,
    WardEvent,
    WardFxBus,
    get_bus,
)

log = logging.getLogger(__name__)


_UNIFORMS_JSON: Path = Path("/dev/shm/hapax-imagination/uniforms.json")
_SUBSTRATE_HINT_PATH: Path = Path("/dev/shm/hapax-compositor/homage-substrate-package.json")
_RECENT_RECRUITMENT_PATH: Path = Path("/dev/shm/hapax/recent-recruitment.json")

# Modulation magnitudes (operator-tunable; held at module scope so a
# reload + reseed is cheap and the values are auditable).
_ENTERING_BLOOM_BOOST: float = 0.25
_ENTERING_CHROMATIC_BOOST: float = 0.15
_ENTERING_PULSE_DURATION_S: float = 0.3
_EMPHASIZED_TEMPORAL_BOOST: float = 0.15
_EMPHASIZED_SPECTRAL_BOOST: float = 0.10
_EMPHASIZED_DURATION_S: float = 1.5

_PRESET_CHANGE_ACCENT_HZ: float = 2.0
_PRESET_CHANGE_TTL_S: float = 0.5
_CHAIN_SWAP_SCALE_BUMP: float = 0.12
_CHAIN_SWAP_TTL_S: float = 0.4

# (Removed) audio-kick + intensity-spike fan-out constants. The
# multi-ward synchronous border-pulse + scale-bump fan-out on every
# kick was a "global reactivity pumping" shape banned by operator
# directive 2026-05-06 — see
# ``feedback_never_remove_exception_global_pumping``. The events
# remain on the bus; per-ward scoped consumers (M8 oscilloscope's own
# SLIP-driven amplitude, Sierpinski center waveform) operate on
# independent paths.

_REVERIE_INTENSITY_BOOST_PEAK: float = 0.20

_CHAIN_SWAP_RESPONSE_WARDS: frozenset[str] = frozenset({"token_pole", "activity_variety_log"})


@dataclass
class WardFxReactor:
    """Concrete subscriber wiring WardEvent ↔ FXEvent into the compositor.

    Intended lifecycle: construct once at compositor start, call
    :meth:`connect` (registers subscribers on the :class:`WardFxBus`
    singleton), and hold the instance on the :class:`StudioCompositor`.
    Construction is cheap; no threads are spawned — the reactor runs on
    whatever thread the bus dispatches from (producer-side).

    Field-based config lets tests substitute alternate paths without
    touching module globals.
    """

    uniforms_path: Path = _UNIFORMS_JSON
    substrate_hint_path: Path = _SUBSTRATE_HINT_PATH
    recent_recruitment_path: Path = _RECENT_RECRUITMENT_PATH
    bus: WardFxBus | None = None

    def connect(self) -> None:
        """Register this reactor's callbacks on the event bus."""
        bus = self.bus if self.bus is not None else get_bus()
        bus.subscribe_ward(self.on_ward_event)
        bus.subscribe_fx(self.on_fx_event)

    # ── Direction 1: WardEvent → FX chain ───────────────────────────

    def on_ward_event(self, event: WardEvent) -> None:
        """Route a ward FSM transition to FX-chain modulation."""
        recv_ts = time.monotonic()
        try:
            if event.transition == "ABSENT_TO_ENTERING":
                self._handle_entering(event)
            elif event.transition == "HOLD_TO_EMPHASIZED":
                self._handle_emphasized(event)
            elif event.transition in (
                "HOLD_TO_EXITING",
                "EMPHASIZED_TO_EXITING",
                "EXITING_TO_ABSENT",
            ):
                self._handle_exiting(event)
            else:
                # ENTERING_TO_HOLD / EMPHASIZED_TO_HOLD: no FX modulation
                # required — the HOLD state is the steady visual baseline.
                pass
        except Exception:
            log.warning("WardFxReactor: ward event handler failed", exc_info=True)
        finally:
            self._observe_latency("ward_to_fx", recv_ts, event.ts)

    def _handle_entering(self, event: WardEvent) -> None:
        """Flash bloom + chromatic in the ward's domain accent."""
        intensity = _clamp(event.intensity, 0.0, 1.0)
        updates = {
            "signal.ward_fx_bloom_boost": _ENTERING_BLOOM_BOOST * intensity,
            "signal.ward_fx_chromatic_boost": _ENTERING_CHROMATIC_BOOST * intensity,
            "signal.ward_fx_pulse_started_at": time.monotonic(),
            "signal.ward_fx_pulse_duration_s": _ENTERING_PULSE_DURATION_S,
            "signal.ward_fx_active_domain_hash": float(_hash_domain(event.domain)),
        }
        self._merge_uniforms(updates)
        family = preset_family_for_domain(event.domain)
        self._bias_preset_family(family, event.domain)
        # Reverie gets a small intensity boost on peak ENTERING events.
        self._boost_reverie(_REVERIE_INTENSITY_BOOST_PEAK * intensity, event.domain)

    def _handle_emphasized(self, event: WardEvent) -> None:
        intensity = _clamp(event.intensity, 0.0, 1.0)
        updates = {
            "signal.ward_fx_temporal_boost": _EMPHASIZED_TEMPORAL_BOOST * intensity,
            "signal.ward_fx_spectral_boost": _EMPHASIZED_SPECTRAL_BOOST * intensity,
            "signal.ward_fx_emphasized_started_at": time.monotonic(),
            "signal.ward_fx_emphasized_duration_s": _EMPHASIZED_DURATION_S,
            "signal.ward_fx_active_domain_hash": float(_hash_domain(event.domain)),
        }
        self._merge_uniforms(updates)

    def _handle_exiting(self, event: WardEvent) -> None:
        """Gently decay the modulated keys toward baseline."""
        updates = {
            "signal.ward_fx_bloom_boost": 0.0,
            "signal.ward_fx_chromatic_boost": 0.0,
            "signal.ward_fx_temporal_boost": 0.0,
            "signal.ward_fx_spectral_boost": 0.0,
        }
        self._merge_uniforms(updates)

    # ── Direction 2: FXEvent → ward reactions ───────────────────────

    def on_fx_event(self, event: FXEvent) -> None:
        """Route an FX-chain event to ward-property modulation.

        Audio events (``audio_kick_onset``, ``intensity_spike``) are
        observed but DO NOT fan out to the audio-reactive ward set
        (``AUDIO_REACTIVE_WARDS``). The historical multi-ward synchronous
        border-pulse + scale-bump fan-out produced lockstep pumping
        across 7 wards on every kick — a "global reactivity pumping"
        shape banned by operator directive 2026-05-06 (carve-out to
        never-remove: see ``feedback_never_remove_exception_global_pumping``).

        Per-ward, scoped audio reactivity remains live and mandatory:
        the M8 oscilloscope renders the M8 device's own SLIP-packet
        amplitudes directly, the Sierpinski center waveform renders the
        broadcast envelope as Hapax's speech surface (see
        ``feedback_audio_reactivity_must_be_tight_speech_representation``).
        Those paths do NOT route through this reactor.

        Discrete chain-state events (``preset_family_change``,
        ``chain_swap``) remain — they are not audio-driven pumping.
        """
        recv_ts = time.monotonic()
        try:
            if event.kind == "preset_family_change":
                self._pulse_all_wards(_PRESET_CHANGE_ACCENT_HZ, _PRESET_CHANGE_TTL_S)
            elif event.kind == "chain_swap":
                self._bump_specific_wards(
                    _CHAIN_SWAP_RESPONSE_WARDS,
                    _CHAIN_SWAP_SCALE_BUMP,
                    _CHAIN_SWAP_TTL_S,
                )
            # ``audio_kick_onset`` / ``intensity_spike``: observed only.
            # No multi-ward fan-out (anti-pumping carve-out). The events
            # remain on the bus for any per-ward, scoped consumer that
            # wants to opt in with allow-list-class modulation
            # (vibration / hue / palette / per-region warp).
        except Exception:
            log.warning("WardFxReactor: fx event handler failed", exc_info=True)
        finally:
            self._observe_latency("fx_to_ward", recv_ts, event.ts)

    def _pulse_all_wards(self, pulse_hz: float, ttl_s: float) -> None:
        """Accent-pulse every known ward."""
        updates: dict[str, WardProperties] = {}
        for ward_id in _known_ward_ids():
            base = get_specific_ward_properties(ward_id) or WardProperties()
            updates[ward_id] = _with_border_pulse(base, pulse_hz)
        set_many_ward_properties(updates, ttl_s=ttl_s)

    def _bump_specific_wards(
        self, ward_ids: frozenset[str], scale_bump_pct: float, ttl_s: float
    ) -> None:
        for ward_id in ward_ids:
            base = get_specific_ward_properties(ward_id) or WardProperties()
            next_props = _with_scale(base, 1.0 + scale_bump_pct)
            set_ward_properties(ward_id, next_props, ttl_s=ttl_s)

    # ── SHM writers (shared between directions) ──────────────────────

    def _merge_uniforms(self, updates: dict[str, float]) -> None:
        """Atomic merge of coupling floats into uniforms.json."""
        try:
            self.uniforms_path.parent.mkdir(parents=True, exist_ok=True)
            current: dict = {}
            if self.uniforms_path.exists():
                try:
                    parsed = json.loads(self.uniforms_path.read_text(encoding="utf-8"))
                    if isinstance(parsed, dict):
                        current = parsed
                except Exception:
                    current = {}
            current.update(updates)
            tmp = self.uniforms_path.with_suffix(self.uniforms_path.suffix + ".tmp")
            tmp.write_text(json.dumps(current), encoding="utf-8")
            tmp.replace(self.uniforms_path)
        except Exception:
            log.debug("WardFxReactor: uniforms merge failed", exc_info=True)

    def _bias_preset_family(self, family: str, domain: str) -> None:
        """Write a family-bias hint that preset_family_selector can read."""
        try:
            self.recent_recruitment_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "family": family,
                "source": "ward_fx_reactor",
                "domain": domain,
                "ts": time.monotonic(),
            }
            tmp = self.recent_recruitment_path.with_suffix(
                self.recent_recruitment_path.suffix + ".tmp"
            )
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(self.recent_recruitment_path)
        except Exception:
            log.debug("WardFxReactor: preset family bias write failed", exc_info=True)

    def _boost_reverie(self, boost: float, domain: str) -> None:
        """Add a reverie-intensity-boost hint to the substrate package file.

        Merges into the existing substrate-hint payload so the rest of
        the choreographer-published fields (palette hue, source IDs) are
        preserved. A best-effort merge: if the file doesn't exist yet
        (choreographer has not booted) we create a minimal stub and let
        the choreographer's next broadcast overwrite the structural
        fields while keeping the boost.
        """
        try:
            self.substrate_hint_path.parent.mkdir(parents=True, exist_ok=True)
            existing: dict = {}
            if self.substrate_hint_path.exists():
                try:
                    parsed = json.loads(self.substrate_hint_path.read_text(encoding="utf-8"))
                    if isinstance(parsed, dict):
                        existing = parsed
                except Exception:
                    existing = {}
            existing["reverie_intensity_boost"] = float(boost)
            existing["reverie_boost_domain"] = domain
            existing["reverie_boost_ts"] = time.monotonic()
            tmp = self.substrate_hint_path.with_suffix(self.substrate_hint_path.suffix + ".tmp")
            tmp.write_text(json.dumps(existing), encoding="utf-8")
            tmp.replace(self.substrate_hint_path)
        except Exception:
            log.debug("WardFxReactor: reverie boost write failed", exc_info=True)

    def _observe_latency(self, direction: str, recv_monotonic: float, event_ts: float) -> None:
        """Record the delta between event.ts and now onto the histogram."""
        bus = self.bus if self.bus is not None else get_bus()
        bus.observe_coupling_latency(max(0.0, recv_monotonic - event_ts), direction)


# ── Helpers ──────────────────────────────────────────────────────────────


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _hash_domain(domain: str) -> int:
    """Stable integer identifier per domain (shader palette selector)."""
    table = {name: i for i, name in enumerate(sorted(DOMAIN_PRESET_FAMILY))}
    return table.get(domain, 0)


def _known_ward_ids() -> frozenset[str]:
    """Every ward we're willing to accent-pulse on FX events.

    Reads directly from :data:`ward_fx_mapping.WARD_DOMAIN` so adding a
    ward to the mapping automatically opts it into FX reactions.
    """
    from agents.studio_compositor.ward_fx_mapping import WARD_DOMAIN

    return frozenset(WARD_DOMAIN.keys())


def _with_border_pulse(base: WardProperties, pulse_hz: float) -> WardProperties:
    from dataclasses import asdict

    kwargs = asdict(base)
    kwargs["border_pulse_hz"] = pulse_hz
    return _rebuild(kwargs)


def _with_scale(base: WardProperties, scale: float) -> WardProperties:
    from dataclasses import asdict

    kwargs = asdict(base)
    kwargs["scale"] = scale
    return _rebuild(kwargs)


def _rebuild(kwargs: dict) -> WardProperties:
    """Rebuild a WardProperties from asdict output.

    ``asdict`` flattens nested tuples to lists; WardProperties stores
    the colour fields as tuples. Restore that type-contract so the
    reactor never pollutes the on-disk JSON with tuple/list drift.
    """
    for key in ("glow_color_rgba", "border_color_rgba", "color_override_rgba"):
        value = kwargs.get(key)
        if isinstance(value, list):
            kwargs[key] = tuple(value)
    return WardProperties(**kwargs)


__all__ = ["WardFxReactor"]
