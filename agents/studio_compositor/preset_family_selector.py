"""Preset family selector — Phase 3 of the volitional-director epic.

The director's compositional impingements can recruit ``fx.family.<family>``
capabilities (audio-reactive, calm-textural, glitch-dense, warm-minimal,
neutral-ambient). Stage 1 routing fix (PR #1044) ensures these recruitments
land on the studio compositor's livestream surface rather than getting
hijacked by Reverie satellites. But the recruitment alone only writes the
*family* to ``recent-recruitment.json``; ``random_mode.py`` historically
treated the family bias as a sleep signal ("director claimed this window,
don't pick uniformly") without actually choosing a preset *within* the
family.

This module implements the missing within-family pick. Used by:

- ``random_mode.py`` — when a family is recruited (within the cooldown
  window), defer to ``pick_from_family(family)`` for the next preset
  selection. When NO family is recruited, fall back to
  ``pick_from_family("neutral-ambient")`` rather than uniform random
  across the entire preset corpus.
- Any future deterministic director path that wants "give me a fresh
  preset from family X" without wiring its own random selection.

Family → preset mapping is curated below. The mapping is intentionally
operator-tunable — preset taxonomy is aesthetic, not mechanical, and the
operator's mental model of which presets fit which families is the
authority. Update :data:`FAMILY_PRESETS` to reflect taste evolution.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from random import Random
from typing import Any

from agents.studio_compositor.preset_mutator import (
    DEFAULT_VARIANCE,
    mutate_preset,
    variety_enabled,
)

log = logging.getLogger(__name__)

PRESET_DIR = Path(__file__).parent.parent.parent / "presets"

# Curated family → preset list mapping. Names match the json filenames
# in ``presets/`` (without the ``.json`` extension). Each preset can
# appear in multiple families if it legitimately fits both. Keep the
# lists narrow rather than wide — narrow gives the director's family
# bias a stronger aesthetic signature, wide collapses the families
# back toward uniform random.
FAMILY_PRESETS: dict[str, tuple[str, ...]] = {
    # Sound-following — beat + energy + spectrum modulation. Used when
    # music is the centerpiece of the moment.
    "audio-reactive": (
        "feedback_preset",
        "heartbeat",
        "fisheye_pulse",
        "neon",
        "mirror_rorschach",
        "tunnelvision",
    ),
    # Slow field-like — chill, reflective, study contexts. Avoids
    # strong rhythm.
    "calm-textural": (
        "ambient",
        "kaleidodream",
        "voronoi_crystal",
        "sculpture",
        "silhouette",
        "ghost",
    ),
    # High-entropy glitch — intense, seeking, curious stances. Heavy
    # procedural distortion.
    "glitch-dense": (
        "datamosh",
        "datamosh_heavy",
        "glitch_blocks_preset",
        "pixsort_preset",
        "slitscan_preset",
        "trap",
    ),
    # Warm minimal — sits quietly as backdrop for conversation /
    # focused work.
    "warm-minimal": (
        "dither_retro",
        "vhs_preset",
        "thermal_preset",
        "halftone_preset",
        "trails",
        "ascii_preset",
    ),
    # Neutral baseline — used as the default fallback when no family is
    # recruited. Avoids the "shuffle feel" of uniform random by keeping
    # the fallback inside a coherent aesthetic register.
    "neutral-ambient": (
        "nightvision",
        "screwed",
        "diff_preset",
    ),
}

# Module-level last-pick memory per family to avoid back-to-back repeats
# without forcing a strict round-robin (which would be too predictable
# given many families have only 3–6 presets).
_LAST_PICK: dict[str, str] = {}


def family_names() -> list[str]:
    """Return the list of registered family names."""
    return sorted(FAMILY_PRESETS)


def presets_for_family(family: str) -> tuple[str, ...]:
    """Return the preset list for ``family``, or empty tuple if unknown."""
    return FAMILY_PRESETS.get(family, ())


def pick_from_family(
    family: str,
    *,
    available: list[str] | None = None,
    last: str | None = None,
) -> str | None:
    """Choose one preset from ``family`` avoiding back-to-back repeat.

    Parameters
    ----------
    family
        Family name (must be a key of :data:`FAMILY_PRESETS`). Unknown
        family names log a warning and return ``None``.
    available
        Optional list of currently-loadable preset names. Useful for
        tests and for filtering against a runtime registry that may
        differ from the family map. When ``None``, all family entries
        are considered candidates.
    last
        Optional explicit "last picked" override — useful when caller
        wants to enforce non-repeat against a different memory than
        ``_LAST_PICK[family]``.

    Returns
    -------
    str | None
        A preset name from the family, or ``None`` when the family is
        unknown OR every family member is filtered out by ``available``.
    """
    if family not in FAMILY_PRESETS:
        log.warning("pick_from_family: unknown family %r", family)
        return None
    candidates = list(FAMILY_PRESETS[family])
    if available is not None:
        avail_set = set(available)
        candidates = [p for p in candidates if p in avail_set]
    if not candidates:
        log.warning(
            "pick_from_family: no candidates for family %r after filtering "
            "(family list: %s; available: %s)",
            family,
            FAMILY_PRESETS[family],
            None if available is None else len(available),
        )
        return None
    last_seen = last if last is not None else _LAST_PICK.get(family)
    non_repeat = [p for p in candidates if p != last_seen]
    pick = random.choice(non_repeat) if non_repeat else random.choice(candidates)
    _LAST_PICK[family] = pick
    return pick


def reset_memory() -> None:
    """Clear the per-family last-pick memory. Tests + restart use this."""
    _LAST_PICK.clear()


def pick_and_load_mutated(
    family: str,
    *,
    available: list[str] | None = None,
    last: str | None = None,
    seed: int | None = None,
    variance: float = DEFAULT_VARIANCE,
    mutate: bool | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Pick a preset from ``family``, load its JSON, and (optionally) mutate.

    Thin wrapper tying :func:`pick_from_family` to the Phase 1 parametric
    mutator (see ``preset_mutator.py``). The director path calls this
    to get a ready-to-write graph in one hop:

    .. code-block:: python

        hit = pick_and_load_mutated("calm-textural", seed=stance_tick)
        if hit is not None:
            preset_name, graph = hit
            write_graph_mutation(graph)

    Parameters
    ----------
    family, available, last
        Forwarded verbatim to :func:`pick_from_family`.
    seed
        Deterministic RNG seed — typically the stance tick index. Same
        ``(preset_name, seed)`` produces the same mutated graph.
    variance
        Jitter fraction; default 0.15 per spec §3.
    mutate
        Force mutation on (``True``) or off (``False``). When ``None``
        (the default), respects the ``HAPAX_PRESET_VARIETY_ACTIVE``
        feature flag (default ON). Tests and the mutation-disabled
        fallback path pass ``False``.

    Returns
    -------
    tuple[str, dict] | None
        ``(preset_name, graph_dict)`` on success; ``None`` when no
        candidate is available, the family is unknown, or the preset
        file is missing on disk.
    """
    preset_name = pick_from_family(family, available=available, last=last)
    if preset_name is None:
        return None
    path = PRESET_DIR / f"{preset_name}.json"
    if not path.exists():
        log.warning("pick_and_load_mutated: missing preset file for %r", preset_name)
        return None
    graph = json.loads(path.read_text())
    do_mutate = variety_enabled() if mutate is None else mutate
    if do_mutate:
        rng = Random(seed) if seed is not None else Random()
        graph = mutate_preset(graph, rng=rng, variance=variance)
    return preset_name, graph


__all__ = [
    "FAMILY_PRESETS",
    "family_names",
    "pick_and_load_mutated",
    "pick_from_family",
    "presets_for_family",
    "reset_memory",
]
