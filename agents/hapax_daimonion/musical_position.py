"""MusicalPosition — hierarchical time decomposition for musical structure.

Decomposes a beat position into bar, phrase, and section levels.
Pure arithmetic — no IO, no side effects. Modeled as Behavior[MusicalPosition]
updated from TimelineMapping.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.hapax_daimonion.primitives import Behavior
from agents.hapax_daimonion.timeline import TimelineMapping, TransportState


@dataclass(frozen=True)
class MusicalPosition:
    """Hierarchical musical time decomposition.

    Frozen dataclass — immutable snapshot of position in musical structure.
    All fields are derived from a single beat number via pure arithmetic.
    """

    beat: float
    bar: int
    beat_in_bar: float
    phrase: int
    bar_in_phrase: int
    section: int
    phrase_in_section: int


def musical_position(
    beat: float,
    beats_per_bar: int = 4,
    bars_per_phrase: int = 4,
    phrases_per_section: int = 4,
) -> MusicalPosition:
    """Decompose a beat number into hierarchical musical position.

    Pure arithmetic — deterministic, no side effects.
    """
    bar = int(beat // beats_per_bar)
    beat_in_bar = beat - bar * beats_per_bar
    phrase = bar // bars_per_phrase
    bar_in_phrase = bar % bars_per_phrase
    section = phrase // phrases_per_section
    phrase_in_section = phrase % phrases_per_section

    return MusicalPosition(
        beat=beat,
        bar=bar,
        beat_in_bar=beat_in_bar,
        phrase=phrase,
        bar_in_phrase=bar_in_phrase,
        section=section,
        phrase_in_section=phrase_in_section,
    )


def create_musical_position_behavior(watermark: float = 0.0) -> Behavior[MusicalPosition]:
    """Create a Behavior with sentinel MusicalPosition at beat 0."""
    return Behavior(musical_position(0.0), watermark=watermark)


def update_musical_position(
    behavior: Behavior[MusicalPosition],
    mapping: TimelineMapping,
    now: float,
    beats_per_bar: int = 4,
    bars_per_phrase: int = 4,
    phrases_per_section: int = 4,
) -> MusicalPosition:
    """Update the musical position Behavior from a TimelineMapping.

    Returns the computed position. Only updates if transport is PLAYING.
    """
    if mapping.transport is TransportState.STOPPED:
        return behavior.value

    beat = mapping.beat_at_time(now)
    pos = musical_position(beat, beats_per_bar, bars_per_phrase, phrases_per_section)
    behavior.update(pos, now)
    return pos
