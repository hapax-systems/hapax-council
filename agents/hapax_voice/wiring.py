"""Multi-source perception wiring layer.

Maps physical sources → backend instances → cadence groups → governance chains.
The wiring layer selects which physical source feeds which governance chain via
behavior aliasing: governance chains read bare names, the wiring layer resolves
them to source-qualified Behaviors.

No new primitives. This is configuration and plumbing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from agents.hapax_voice.cadence import CadenceGroup
from agents.hapax_voice.primitives import Behavior
from agents.hapax_voice.source_naming import (
    behaviors_for_base,
    qualify,
    validate_source_id,
)

log = logging.getLogger(__name__)


class BackendType(Enum):
    """Known backend types for source instantiation."""

    AUDIO_ENERGY = "audio_energy"
    EMOTION = "emotion"
    ENERGY_ARC = "energy_arc"
    STREAM_HEALTH = "stream_health"
    MIDI_CLOCK = "midi_clock"


@dataclass(frozen=True)
class SourceSpec:
    """Declaration of a physical source and its backend type."""

    source_id: str
    backend_type: BackendType
    cadence_group: str  # which CadenceGroup this belongs to

    def __post_init__(self) -> None:
        validate_source_id(self.source_id)


@dataclass(frozen=True)
class GovernanceBinding:
    """Maps bare governance behavior names to source-qualified Behaviors.

    Each governance chain expects bare names like ``audio_energy_rms``.
    The binding specifies which physical source provides each signal.
    Unqualified signals (e.g., ``timeline_mapping``) are passed through as-is.
    """

    energy_source: str  # source_id for audio energy
    emotion_source: str  # source_id for emotion
    unqualified: tuple[str, ...] = ("vad_confidence", "timeline_mapping")


@dataclass(frozen=True)
class WiringConfig:
    """Complete wiring specification for a multi-source perception system."""

    sources: tuple[SourceSpec, ...]
    cadence_groups: dict[str, float]  # name → interval_s
    mc_binding: GovernanceBinding
    obs_binding: GovernanceBinding

    def __post_init__(self) -> None:
        # Validate cadence group references
        for spec in self.sources:
            if spec.cadence_group not in self.cadence_groups:
                raise ValueError(
                    f"Source '{spec.source_id}' references unknown cadence group "
                    f"'{spec.cadence_group}'. Available: {list(self.cadence_groups.keys())}"
                )

        # Validate source references in bindings
        source_ids = {s.source_id for s in self.sources}
        for label, binding in [("mc", self.mc_binding), ("obs", self.obs_binding)]:
            if binding.energy_source not in source_ids:
                raise ValueError(
                    f"{label}_binding.energy_source '{binding.energy_source}' "
                    f"not in declared sources: {source_ids}"
                )
            if binding.emotion_source not in source_ids:
                raise ValueError(
                    f"{label}_binding.emotion_source '{binding.emotion_source}' "
                    f"not in declared sources: {source_ids}"
                )

        # Validate no duplicate (source_id, backend_type) pairs
        seen: set[tuple[str, BackendType]] = set()
        for spec in self.sources:
            key = (spec.source_id, spec.backend_type)
            if key in seen:
                raise ValueError(
                    f"Duplicate source spec: {spec.source_id} / {spec.backend_type.value}"
                )
            seen.add(key)


def build_behavior_alias(
    behaviors: dict[str, Behavior],
    binding: GovernanceBinding,
    stream_behaviors: dict[str, Behavior] | None = None,
) -> dict[str, Behavior]:
    """Build a governance-facing view dict that maps bare names to source-qualified Behaviors.

    The governance chain reads ``audio_energy_rms``; the alias dict resolves it to
    ``audio_energy_rms:monitor_mix`` (or whatever the binding specifies).

    Args:
        behaviors: The full engine behaviors dict with source-qualified keys.
        binding: Specifies which source provides each signal type.
        stream_behaviors: Optional dict of stream health behaviors (unqualified).
    """
    alias: dict[str, Behavior] = {}

    # Audio energy signals
    energy_bases = ("audio_energy_rms", "audio_onset")
    for base in energy_bases:
        qualified = qualify(base, binding.energy_source)
        if qualified in behaviors:
            alias[base] = behaviors[qualified]

    # Emotion signals
    emotion_bases = ("emotion_valence", "emotion_arousal", "emotion_dominant")
    for base in emotion_bases:
        qualified = qualify(base, binding.emotion_source)
        if qualified in behaviors:
            alias[base] = behaviors[qualified]

    # Unqualified signals — pass through directly
    for name in binding.unqualified:
        if name in behaviors:
            alias[name] = behaviors[name]

    # Stream health behaviors (always unqualified)
    if stream_behaviors:
        alias.update(stream_behaviors)

    return alias


def build_cadence_groups(config: WiringConfig) -> dict[str, CadenceGroup]:
    """Create CadenceGroup instances from config."""
    return {
        name: CadenceGroup(name=name, interval_s=interval)
        for name, interval in config.cadence_groups.items()
    }


# ---------------------------------------------------------------------------
# Aggregation functions — derive synthetic Behaviors from multiple sources
# ---------------------------------------------------------------------------


def aggregate_max(
    behaviors: dict[str, Behavior],
    base_name: str,
) -> Behavior[float]:
    """Create a Behavior tracking the max value across all sources for a base name.

    Watermark is set to the minimum watermark across contributing sources
    (most conservative — FreshnessGuard rejects based on stalest source).
    """
    matching = behaviors_for_base(behaviors, base_name)
    if not matching:
        return Behavior(0.0, watermark=0.0)

    max_val = max(b.value for b in matching.values())
    min_wm = min(b.watermark for b in matching.values())
    return Behavior(max_val, watermark=min_wm)


def aggregate_mean(
    behaviors: dict[str, Behavior],
    base_name: str,
) -> Behavior[float]:
    """Create a Behavior tracking the mean value across all sources for a base name.

    Watermark is the minimum across contributing sources.
    """
    matching = behaviors_for_base(behaviors, base_name)
    if not matching:
        return Behavior(0.0, watermark=0.0)

    values = [b.value for b in matching.values()]
    mean_val = sum(values) / len(values)
    min_wm = min(b.watermark for b in matching.values())
    return Behavior(mean_val, watermark=min_wm)


def aggregate_any(
    behaviors: dict[str, Behavior],
    base_name: str,
) -> Behavior[bool]:
    """Create a Behavior that is True if any source for the base name is truthy.

    Watermark is the minimum across contributing sources.
    """
    matching = behaviors_for_base(behaviors, base_name)
    if not matching:
        return Behavior(False, watermark=0.0)

    any_true = any(b.value for b in matching.values())
    min_wm = min(b.watermark for b in matching.values())
    return Behavior(any_true, watermark=min_wm)
