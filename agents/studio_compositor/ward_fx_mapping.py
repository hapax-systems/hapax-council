"""Ward ↔ FX routing tables.

HOMAGE Phase 6 Layer 5. Operator-tunable mapping from WardDomain → FX
preset family + per-ward audio-reactive flag. Data-driven so the
operator can tune without touching the reactor code.

Two lookups live here:

* :data:`DOMAIN_PRESET_FAMILY` — WardDomain → preset family name. Fed
  into :mod:`preset_family_selector` when a ward FSM transition event
  requests a preset shift to "support" the ward's emergence.
* :data:`WARD_DOMAIN` — ward_id → WardDomain classification. Every
  ward known to the compositor is classified here. Unknown wards fall
  back to ``"perception"`` so callers always get a usable domain.
* :data:`AUDIO_REACTIVE_WARDS` — wards whose rendering should respond
  to FX ``audio_kick_onset`` / ``intensity_spike`` events with a
  brightness/shimmer boost. Currently: ``pressure_gauge``,
  ``token_pole``, ``activity_variety_log``.
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
}


AUDIO_REACTIVE_WARDS: frozenset[str] = frozenset(
    {
        "pressure_gauge",
        "token_pole",
        "activity_variety_log",
        "vinyl_platter",
        "m8_oscilloscope",
        "m8-display",
        "album_overlay",
    }
)
"""Wards whose render responds to FX audio signals (kick onsets,
intensity spikes). The reactor modulates these via the ward_properties
SHM path (``scale_bump_pct`` / ``border_pulse_hz``) so the ward renders
the beat without hard-coding audio state in every Cairo source.

The ``album_overlay`` ward joins ``vinyl_platter`` so the cover art
pulses with the broadcast beat alongside the platter — both surfaces
represent the same playing track and should breathe together.

The M8 oscilloscope already renders the M8 device's own SLIP-packet
amplitudes directly — that surface IS its audio. Inclusion here adds
bus-level FX-event coupling on top of that, so the ward gets the same
``scale_bump`` / ``border_pulse`` on broader-mix kicks as the other
music-domain wards (``vinyl_platter``). The two signal paths compose:
the waveform reflects the M8 instantaneously, while the FX reactor
synchronises the ward's chrome to the broadcast's overall beat. The
``m8-display`` ward (sibling IR surface for the same device) joins on
the same FX path so both M8 surfaces breathe with the broadcast beat."""


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
    "PresetFamily",
    "WARD_DOMAIN",
    "domain_for_ward",
    "is_audio_reactive",
    "preset_family_for_domain",
]
