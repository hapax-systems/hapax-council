"""Evil Pet preset pack — CC-burst fallback, `.evl` file-free (#194).

Phase 1 of ``docs/superpowers/plans/2026-04-20-evil-pet-preset-pack-
plan.md``. Ships the CC-burst fallback path per plan §Phase 4:

> "Depending on Phase 5 result, implement as PC message OR as direct
> CC 16-burst of the preset's parameter values, bypassing preset-
> recall entirely."

The `.evl` SD-card preset format reverse is deferred pending operator
providing a factory file. This module gives operators a working
recall pattern today: named presets → CC bursts → direct MIDI emit.

Scope:

- ``EvilPetPreset`` dataclass — name, description, CC map
  (cc_number → value) in 0..127.
- ``PRESETS`` module-level registry with one preset per VoiceTier +
  Mode D + bypass — 9 entries total.
- ``recall_preset(preset_name, midi_output, channel)`` helper —
  emits the CC burst synchronously; tolerates MIDI-down.
- Each preset builds on the shared base-scene CCs from the
  voice-tier Catalog where applicable; tier 5/6 presets add the
  granular engine engagement CCs verbatim from
  ``shared.voice_tier.TIER_CATALOG``.
- ``list_presets()`` / ``get_preset(name)`` — read-only lookups.

Reference:
    - docs/superpowers/plans/2026-04-20-evil-pet-preset-pack-plan.md
      §Phase 2 (build_preset.py) + §Phase 4 (preset-recall MIDI glue)
    - docs/research/2026-04-20-evil-pet-factory-presets-midi.md
    - shared/voice_tier.py — TIER_CATALOG + cc_overrides
    - scripts/evil-pet-configure-base.py — the base-scene precedent
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final

from shared.voice_tier import TIER_CATALOG, VoiceTier

log = logging.getLogger(__name__)

EVIL_PET_MIDI_CHANNEL: Final[int] = 0  # channel 1 on the wire

# Voice-safe base scene — applied as the starting point for every
# non-granular preset so a recall into e.g. "hapax-tier-2" brings a
# fresh voice-safe slate plus tier-specific overrides, not an
# unpredictable hold-over from whatever state the engine was in.
#
# D-24 §11.3: promoted from a private _BASE_SCENE to a public module
# constant so scripts/evil-pet-configure-base.py and other callers
# can reference the single source of truth rather than duplicating
# the same 16 CC values across files.
BASE_SCENE: Final[dict[int, int]] = {
    11: 0,  # Grains volume → 0 (granular off)
    85: 0,  # Overtone volume → 0
    40: 95,  # Mix → 75% wet
    7: 127,  # Volume → max
    80: 64,  # Filter type → bandpass
    70: 76,  # Filter freq → midband
    71: 25,  # Filter resonance → low
    96: 44,  # Env→filter mod
    84: 10,  # Saturator type → distortion
    39: 38,  # Saturator amount → ~30%
    95: 64,  # Reverb type → room
    91: 38,  # Reverb amount → ~30%
    92: 64,  # Reverb tone → neutral
    93: 38,  # Reverb tail → ~30%
    94: 0,  # Shimmer → 0 (voice-safe default)
    69: 0,  # Record enable → 0
}


@dataclass(frozen=True)
class EvilPetPreset:
    """Named CC-burst preset for the Evil Pet.

    ``ccs`` is a dict of MIDI CC number → value (0..127). ``recall``
    emits them as ``control_change`` messages on ``midi_output``
    sequentially with a short delay between writes (matches the base-
    scene script's 20 ms cadence; under the 50 ms rate limit).
    """

    name: str
    description: str
    ccs: dict[int, int] = field(default_factory=dict)


def _tier_preset(tier: VoiceTier) -> EvilPetPreset:
    """Build a voice-tier preset: base scene + tier's cc_overrides."""
    ccs = dict(BASE_SCENE)
    profile = TIER_CATALOG[tier]
    for _device, _channel, cc, value, _note in profile.cc_overrides:
        ccs[cc] = value
    return EvilPetPreset(
        name=f"hapax-{tier.name.lower().replace('_', '-')}",
        description=profile.description,
        ccs=ccs,
    )


# Mode D scene — values match docs/research/2026-04-20-mode-d-voice-
# tier-mutex.md §1 + scripts/hapax-vinyl-mode. Deliberately duplicated
# here rather than imported from vinyl_chain so the preset pack has no
# daimonion-side dependency; the values are load-bearing governance
# (Content ID defeat thresholds per Smitelli 2020).
_MODE_D_CCS: Final[dict[int, int]] = {
    **BASE_SCENE,
    11: 120,  # Grains volume → 94% (engine fully engaged)
    40: 127,  # Mix → 100% wet (kill dry signal)
    80: 64,  # Filter type → bandpass (confirm)
    70: 76,  # Filter freq → mid (confirm)
    91: 70,  # Reverb amount → heavy wash
    93: 80,  # Reverb tail → long
    94: 60,  # Shimmer → on
    84: 40,  # Saturator → bit-crush region
    39: 50,  # Saturator amount → 40%
}


PRESETS: Final[dict[str, EvilPetPreset]] = {
    preset.name: preset
    for preset in (
        *(_tier_preset(t) for t in VoiceTier),
        EvilPetPreset(
            name="hapax-mode-d",
            description="Vinyl anti-DMCA granular wash (Mode D) — Content ID defeat",
            ccs=_MODE_D_CCS,
        ),
        EvilPetPreset(
            name="hapax-bypass",
            description="Voice-safe bypass — base scene, grains off, voice-friendly reverb",
            ccs=BASE_SCENE,
        ),
    )
}


def list_presets() -> list[str]:
    """Sorted list of preset names in the pack."""
    return sorted(PRESETS.keys())


def get_preset(name: str) -> EvilPetPreset:
    """Lookup by name. Raises KeyError on miss."""
    return PRESETS[name]


def recall_preset(
    name: str,
    midi_output: Any,
    *,
    channel: int = EVIL_PET_MIDI_CHANNEL,
    delay_s: float = 0.02,
) -> int:
    """Emit the named preset's CC burst on ``midi_output``.

    Args:
        name: Preset identifier from ``list_presets()``.
        midi_output: Must expose ``send_cc(channel, cc, value)`` — the
            same Protocol used by vocal_chain / vinyl_chain.
        channel: MIDI channel (0-indexed; 0 = channel 1 on the wire).
            Evil Pet ships on channel 1 per the base-scene config.
        delay_s: Gap between consecutive CC writes. 20 ms default
            matches the base-scene script's pacing; stays under the
            Erica MIDI Dispatch's 50 ms rate limit.

    Returns the number of CCs emitted. Tolerates ``send_cc``
    exceptions (logs at WARNING + continues) so a single bad write
    doesn't abort the whole recall.
    """
    import time as _time

    preset = get_preset(name)
    emitted = 0
    for cc, value in preset.ccs.items():
        try:
            midi_output.send_cc(channel=channel, cc=cc, value=value)
            emitted += 1
        except Exception:
            log.warning(
                "evil_pet recall %s: send_cc failed for CC%d=%d",
                name,
                cc,
                value,
                exc_info=True,
            )
        _time.sleep(delay_s)
    log.info("evil_pet recall %s: %d/%d CCs emitted", name, emitted, len(preset.ccs))
    return emitted
