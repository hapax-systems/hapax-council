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
  Mode D + bypass + 4 routing-aware presets (Phase 2 extension:
  hapax-sampler-wet, hapax-bed-music, hapax-drone-loop,
  hapax-s4-companion) — 13 entries total.
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


# Phase 4 observability — preset recall counters. Tolerates
# prometheus_client absence (CPU-only test environments, headless
# scripts) by falling back to a no-op stub. Operator dashboards scrape
# the default registry; the metric name + label are stable contract.
try:
    from prometheus_client import Counter as _Counter

    _preset_recalls_total = _Counter(
        "hapax_evilpet_preset_recalls_total",
        "Evil Pet preset recalls emitted via recall_preset(), per preset name.",
        ("preset_name",),
    )
    _preset_recall_ccs_total = _Counter(
        "hapax_evilpet_preset_recall_ccs_total",
        "Total CCs successfully emitted by recall_preset(), per preset name.",
        ("preset_name",),
    )
    _METRICS_AVAILABLE = True
except Exception:  # pragma: no cover — prometheus_client missing in some envs
    _preset_recalls_total = None
    _preset_recall_ccs_total = None
    _METRICS_AVAILABLE = False


def _emit_recall_metrics(preset_name: str, ccs_emitted: int) -> None:
    """Bump the recall counter + CC counter. No-op if prometheus absent."""
    if not _METRICS_AVAILABLE:
        return
    try:
        _preset_recalls_total.labels(preset_name=preset_name).inc()  # type: ignore[union-attr]
        _preset_recall_ccs_total.labels(preset_name=preset_name).inc(ccs_emitted)  # type: ignore[union-attr]
    except Exception:  # pragma: no cover — metric emit must never break recall
        log.debug("evil_pet recall metric emit failed", exc_info=True)


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


# Routing-aware presets (evilpet-s4-routing Phase 2 extension).
# CC values from spec §7. All build on BASE_SCENE so the engine state
# is reset to a known voice-safe slate before the preset's overrides
# layer in. Each preset is named for the content-class it serves;
# operator selects via the existing recall_preset() pathway.

_SAMPLER_WET_CCS: Final[dict[int, int]] = {
    **BASE_SCENE,
    11: 100,  # Grains volume → 78% (granular engaged, denser than voice T5)
    40: 120,  # Mix → 94% wet (defeat dry sampler bleed)
    91: 60,  # Reverb amount → 47% (longer tail for sampler sustain)
    93: 70,  # Reverb tail → extended (~2.5–3.0 s; won't smear drums)
    39: 50,  # Saturator → 40% (adds harmonic complexity to granular)
    94: 40,  # Shimmer → 31% (iridescent cloud, optional; tune per taste)
}

_BED_MUSIC_CCS: Final[dict[int, int]] = {
    **BASE_SCENE,
    11: 30,  # Grains volume → 23% (light granular color, not primary)
    40: 85,  # Mix → 67% wet (balanced dry/wet for musical legibility)
    91: 45,  # Reverb amount → 35% (ambient wash, not obstructive)
    93: 50,  # Reverb tail → 50% (~1.5 s, non-intrusive)
    39: 25,  # Saturator → 20% (preserve dynamic range of music)
    70: 80,  # Filter freq → slightly bright (emphasize high-frequency details)
}

_DRONE_LOOP_CCS: Final[dict[int, int]] = {
    **BASE_SCENE,
    11: 110,  # Grains volume → 86% (granular primary)
    40: 127,  # Mix → 100% wet (pure texture)
    91: 80,  # Reverb amount → 63% (long ambience)
    93: 90,  # Reverb tail → 70% (~3.5 s, intentional sustain)
    39: 15,  # Saturator → 12% (clean granular texture)
    94: 50,  # Shimmer → 39% (iridescent atmosphere)
    70: 70,  # Filter freq → mild darkening (reduce ear fatigue)
}

_S4_COMPANION_CCS: Final[dict[int, int]] = {
    **BASE_SCENE,
    11: 70,  # Grains volume → 55% (secondary granular, not primary)
    40: 100,  # Mix → 78% wet (complement S-4, not compete)
    91: 50,  # Reverb amount → 39% (ambient support, no wash-out)
    93: 60,  # Reverb tail → moderate (~2.0 s, rhythmic coherence with S-4)
    39: 35,  # Saturator → 27% (smooth granular texture)
    94: 30,  # Shimmer → 24% (subtle iridescence, S-4 is primary)
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
        EvilPetPreset(
            name="hapax-sampler-wet",
            description=(
                "Sampler-optimized granular wash — higher grain density + sustained "
                "reverb tail for polyrhythmic textures."
            ),
            ccs=_SAMPLER_WET_CCS,
        ),
        EvilPetPreset(
            name="hapax-bed-music",
            description=(
                "Low-impact music processing — subtle texture without vocals. "
                "Minimal granular, emphasises filter + reverb."
            ),
            ccs=_BED_MUSIC_CCS,
        ),
        EvilPetPreset(
            name="hapax-drone-loop",
            description=(
                "Sustained granular drone — full wet, long reverb tail, minimal "
                "saturation. Use for ambient interludes."
            ),
            ccs=_DRONE_LOOP_CCS,
        ),
        EvilPetPreset(
            name="hapax-s4-companion",
            description=(
                "S-4 companion preset — light Evil Pet coloration when S-4 Mosaic "
                "granular is primary. Permits dual-granular textures (Evil Pet + "
                "S-4) without harshness."
            ),
            ccs=_S4_COMPANION_CCS,
        ),
    )
}


def list_presets() -> list[str]:
    """Sorted list of preset names in the pack."""
    return sorted(PRESETS.keys())


def get_preset(name: str) -> EvilPetPreset:
    """Lookup by name. Raises KeyError on miss."""
    return PRESETS[name]


# Phase B5 — dual-engine pairing recommendations (evilpet-s4-dynamic-dual-processor-design §4.3).
#
# Maps each Evil Pet preset to the S-4 scene that complements its
# character when both engines are engaged simultaneously (dual-engine
# topology classes D1, D2, D3 per spec §5.8-§5.10). The dynamic router
# (Phase B3) consults this dict when selecting paired scenes; operator
# CLI can override per §6.8.
#
# ``None`` indicates the preset should not run paired — e.g. hapax-mode-d
# is the vinyl granular claim and S-4 is not expected to be engaged on
# the voice path while Mode D holds the granular engine.
DEFAULT_PAIRINGS: Final[dict[str, str | None]] = {
    # Voice tiers T0..T6 — pair with companion scenes
    "hapax-unadorned": "BYPASS",
    "hapax-radio": "VOCAL-COMPANION",
    "hapax-broadcast-ghost": "VOCAL-COMPANION",
    "hapax-memory": "MEMORY-COMPANION",
    "hapax-underwater": "UNDERWATER-COMPANION",
    "hapax-granular-wash": "SONIC-RITUAL",
    "hapax-obliterated": "SONIC-RITUAL",
    # Modes
    "hapax-mode-d": None,  # vinyl claims the granular engine; S-4 not paired on voice path
    "hapax-bypass": "BYPASS",
    # Music presets — pair with music scenes (Evil Pet is secondary coloration)
    "hapax-sampler-wet": "BEAT-1",
    "hapax-bed-music": "MUSIC-BED",
    "hapax-drone-loop": "MUSIC-DRONE",
    "hapax-s4-companion": "MUSIC-BED",
}


def get_default_pairing(preset_name: str) -> str | None:
    """Return the recommended S-4 scene for a given Evil Pet preset.

    Returns ``None`` for presets that should not run paired (e.g.
    hapax-mode-d). Raises KeyError if ``preset_name`` is not in the
    Evil Pet pack.
    """
    if preset_name not in PRESETS:
        raise KeyError(
            f"unknown Evil Pet preset '{preset_name}'; available: {', '.join(sorted(PRESETS))}"
        )
    return DEFAULT_PAIRINGS.get(preset_name)


def recall_preset(
    name: str,
    midi_output: Any,
    *,
    channel: int = EVIL_PET_MIDI_CHANNEL,
    delay_s: float = 0.02,
    verify_port: bool = False,
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
        verify_port: D-24 §10.4 — when True, attempt one no-op CC ping
            (CC 0 / value 0 on the target channel) BEFORE the burst to
            surface a closed/missing MIDI port quickly. On ping failure,
            raises ``RuntimeError`` instead of silently logging
            send_cc failures for every CC in the burst. Default False
            preserves the cold-start fire-and-log contract callers
            already rely on.

    Returns the number of CCs emitted. Tolerates ``send_cc``
    exceptions (logs at WARNING + continues) so a single bad write
    doesn't abort the whole recall.

    Raises:
        RuntimeError: when ``verify_port=True`` and the pre-burst
            ping fails — actionable signal that the MIDI port is dead.
    """
    import time as _time

    preset = get_preset(name)
    if verify_port:
        try:
            midi_output.send_cc(channel=channel, cc=0, value=0)
        except Exception as e:
            raise RuntimeError(
                f"evil_pet recall {name}: pre-burst port verify failed "
                f"(channel={channel}); MIDI port likely closed or missing"
            ) from e
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
    _emit_recall_metrics(name, emitted)
    return emitted
