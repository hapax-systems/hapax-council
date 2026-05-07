"""Ward ↔ FX routing tables.

HOMAGE Phase 6 Layer 5. Operator-tunable mapping from WardDomain → FX
preset family + per-ward audio-reactive flag. Data-driven so the
operator can tune without touching the reactor code.

Three lookups live here:

* :data:`DOMAIN_PRESET_FAMILY` — WardDomain → preset family name. Fed
  into :mod:`preset_family_selector` when a ward FSM transition event
  requests a preset shift to "support" the ward's emergence.
* :data:`WARD_DOMAIN` — ward_id → WardDomain classification. Every
  ward known to the compositor is classified here. Unknown wards fall
  back to ``"perception"`` so callers always get a usable domain.
* :data:`AUDIO_REACTIVE_WARDS` — wards whose chrome accepts the
  parametric heartbeat's baseline floor (``border_pulse_hz`` /
  ``scale_bump_pct`` / ``glow_radius_px`` / ``drift_hz`` /
  ``drift_amplitude_px``). Music-domain members couple to the
  broadcast beat through the FX reactor on top of that floor.
  Membership is anchored at module level — see the data definition
  block below for the live set and per-ward rationale. The
  ``audio_kick_onset`` fan-out path was retired in #2756 (pumping
  carve-out); the heartbeat-floor path is the surviving channel.
"""

from __future__ import annotations

from typing import Literal

from shared.ward_fx_bus import WardDomain

PresetFamily = Literal[
    "audio-reactive",
    "calm-textural",
    "glitch-dense",
    "warm-minimal",
    "neutral-ambient",
]


# Domain → preset family. The mapping reflects aesthetic temperament:
#   communication  → textural (conversations warm the frame)
#   presence       → warm-minimal (attention without distraction)
#   token          → glitch-dense (tokens flip hard, FX match the snap)
#   music          → audio-reactive (obvious)
#   cognition      → calm-textural (slow reflective)
#   director       → neutral-ambient (intentional silence between moves)
#   perception     → calm-textural (default ambient register)
DOMAIN_PRESET_FAMILY: dict[WardDomain, PresetFamily] = {
    "communication": "calm-textural",
    "presence": "warm-minimal",
    "token": "glitch-dense",
    "music": "audio-reactive",
    "cognition": "calm-textural",
    "director": "neutral-ambient",
    "perception": "calm-textural",
}


# Ward → domain classification. Hand-authored from the current ward
# inventory: the Cairo sources under ``cairo_sources/``, the FSM wards
# in ``homage/``, the overlay zones, and the PiP/youtube wards.
#
# When a ward emits a ward_id but lacks a row here, ``domain_for_ward``
# falls back to ``"perception"`` and the accent-colour resolver in
# ``homage/rendering.py::_domain_accent`` paints it green. Add new wards
# explicitly so border-pulses and preset-family routing land in the
# operator-intended hue.
WARD_DOMAIN: dict[str, WardDomain] = {
    # Communication surface
    "chat_ambient": "communication",
    "captions": "communication",
    "stream_overlay": "communication",
    "impingement_cascade": "communication",
    "chat_keyword_legend": "communication",
    # Presence
    "whos_here": "presence",
    "thinking_indicator": "presence",
    "pressure_gauge": "presence",
    "stance_indicator": "presence",
    # Token
    "token_pole": "token",
    # Music
    "album": "music",
    "album_overlay": "music",
    "vinyl_platter": "music",
    "m8-display": "music",
    "m8_oscilloscope": "music",
    # Cognition
    "activity_variety_log": "cognition",
    "recruitment_candidate_panel": "cognition",
    "music_candidate_surfacer": "cognition",
    "activity_header": "cognition",
    "programme-history": "cognition",
    "research-instrument-dashboard": "cognition",
    # Director
    "objectives_overlay": "director",
    "scene_director": "director",
    "structural_director": "director",
    "grounding_provenance_ticker": "director",
    "programme-banner": "director",
    "precedent-ticker": "director",
    "chronicle_ticker": "director",
    # Perception
    "sierpinski": "perception",
    # DURF (Display Under Reflective Frame) — coding-activity
    # reveal surface; classified ``perception`` so its accent stays
    # in the calm-textural family rather than competing with
    # cognition / director hues. The ward gets drift-only modulation
    # via ``DRIFT_FLOOR_WARDS`` (no pulse / scale-bump / glow per
    # operator directive 2026-04-25).
    "durf": "perception",
}


AUDIO_REACTIVE_WARDS: frozenset[str] = frozenset(
    {
        # Music-domain wards
        "pressure_gauge",
        "token_pole",
        "activity_variety_log",
        "vinyl_platter",
        "m8_oscilloscope",
        "m8-display",
        "album_overlay",
        # Presence-domain wards (operator directive 2026-05-07 ward audit:
        # these wards rendered ``drift_type=none`` / static defaults after
        # the audio fan-out was removed in #2756; joining them here lets
        # the parametric heartbeat raise the same baseline floor
        # (border_pulse_hz / scale_bump_pct / glow_radius_px /
        # drift_hz / drift_amplitude_px) that the music-domain wards
        # already see, so presence chrome no longer sits flat-zero on
        # broadcast).
        "whos_here",
        "thinking_indicator",
        "stance_indicator",
    }
)
"""Wards whose chrome accepts heartbeat-driven baseline modulation
(``border_pulse_hz`` / ``scale_bump_pct`` / ``glow_radius_px`` /
``drift_hz`` / ``drift_amplitude_px``) plus the FX reactor's
spike-grade overlay on top.

**Music-domain wards** (the original cohort) couple to the broadcast
beat: ``pressure_gauge``, ``token_pole``, ``activity_variety_log``,
``vinyl_platter``, ``m8_oscilloscope``, ``m8-display``,
``album_overlay``. ``album_overlay`` and ``vinyl_platter`` breathe
together because both surfaces represent the same playing track. The
M8 surfaces (``m8_oscilloscope`` + ``m8-display``) render their own
SLIP-packet amplitudes directly; FX-bus inclusion synchronises their
chrome to the broader broadcast beat on top of that.

**Presence-domain wards** joined per the 2026-05-07 ward audit:
``whos_here``, ``thinking_indicator``, ``stance_indicator``. These
wards rendered with static chrome (``drift_type=none``, zero glow,
zero pulse) after the audio fan-out path was retired in #2756.
Joining the AUDIO_REACTIVE set here only hooks them into the
heartbeat's baseline-floor writes — it does NOT subscribe them to
``audio_kick_onset`` events (the anti-pumping carve-out at
``fx_chain_ward_reactor.py`` still applies, pinned by
``test_kick_onset_does_not_fan_out_to_audio_reactive_set``). The
behavioural change is: presence wards now get a slow continuous
breath baseline from the parametric heartbeat instead of sitting
flat-zero."""


DRIFT_FLOOR_WARDS: frozenset[str] = frozenset(
    {
        # DURF (Display Under Reflective Frame). Operator directive
        # 2026-04-25 (recorded at ``z_plane_constants.py:59-66``):
        # "It does need modulation, just not a pulse like that, it's
        # too heavy handed and distracting." The reflective-frame
        # text surface should breathe with the same drift envelope
        # the rest of the chrome moves on, but pulse / scale-bump /
        # glow are explicitly off the table — they pull legibility
        # away from the rendered content.
        "durf",
    }
)
"""Wards that accept the heartbeat's drift-only baseline floor
(``drift_hz`` / ``drift_amplitude_px``) but NOT the pulse / scale-bump
/ glow trio.

Disjoint from ``AUDIO_REACTIVE_WARDS`` by construction (a regression
pin in ``tests/studio_compositor/test_ward_fx_coupling.py`` enforces
the disjointness). The heartbeat iterates the union of both sets and
selectively applies fields based on membership: full 5-field
escalation for ``AUDIO_REACTIVE_WARDS``, drift-only for
``DRIFT_FLOOR_WARDS``."""


def domain_for_ward(ward_id: str) -> WardDomain:
    """Return the classified domain for ``ward_id``.

    Unknown wards default to ``"perception"`` — a safe, low-energy
    classification that keeps FX modulation in the calm-textural family.
    """
    return WARD_DOMAIN.get(ward_id, "perception")


def preset_family_for_domain(domain: WardDomain) -> PresetFamily:
    """Return the preset family biased for ``domain``. Total function."""
    return DOMAIN_PRESET_FAMILY.get(domain, "neutral-ambient")


def is_audio_reactive(ward_id: str) -> bool:
    """True when the ward participates in FX audio-reactive modulation."""
    return ward_id in AUDIO_REACTIVE_WARDS


__all__ = [
    "AUDIO_REACTIVE_WARDS",
    "DOMAIN_PRESET_FAMILY",
    "DRIFT_FLOOR_WARDS",
    "PresetFamily",
    "WARD_DOMAIN",
    "domain_for_ward",
    "is_audio_reactive",
    "preset_family_for_domain",
]
