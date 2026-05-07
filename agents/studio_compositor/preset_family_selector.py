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

# Task #150 Phase 1 — scene → preset-tag bias. When the scene classifier
# publishes a classification, :func:`pick_with_scene_bias` can weight the
# within-family selection toward presets whose ``tags`` metadata matches
# the scene. Table values are sets of preset tags that the scene favors.
# ``mixed-activity`` / ``empty-room`` / None → no bias (uniform pick).
SCENE_TAG_BIAS: dict[str, tuple[str, ...]] = {
    "person-face-closeup": ("intimate", "portrait"),
    "hands-manipulating-gear": ("textural", "macro", "detail"),
    "turntables-playing": ("rotation", "spiral"),
    "outboard-synth-detail": ("electric", "geometric"),
    "room-wide-ambient": ("atmospheric",),
    "screen-only": ("minimal",),
    "empty-room": (),
    "mixed-activity": (),
}

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
        # Audit pools 2026-05-03 (#2406/#2410/#2412/#2415/#2416)
        "chamber_feedback_breathing",
        "chamber_feedback_dense",
        "diff_motion_thermal",
        "diff_motion_trail",
        "pixsort_glitch_horizontal",
        "pixsort_glitch_vertical",
        "electromag_thermal_field",
        "electromag_rutt_etra",
        "kaleido_fractal_dense",
        "kaleido_fractal_mirror",
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
        # Audit pools 2026-05-03
        "water_ripple_caustic",
        "water_ripple_surface",
        "paper_fold_origami",
        "paper_fold_crumple",
        "circular_lens_focus",
        "circular_porthole_view",
        "chrome_mirror_polished",
        "chrome_mirror_brushed",
        "cellular_kuwahara_paint",
        "bloom_solar_flare",
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
        # Audit pools 2026-05-03
        "xerox_smudge_streak",
        "xerox_photocopy_decay",
        "chromakey_lift",
        "chromakey_luma_split",
        "arcane_dither_sigil",
        "broadcast_static_carrier",
        "broadcast_vhs_decay",
        "cellular_reaction",
        "arcane_ascii_glyph",
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
        # Audit pools 2026-05-03
        "mono_print_woodcut",
        "mono_print_newsprint",
        "arcade_8bit_pixel",
        "arcade_palette_remap",
        "bloom_neon_night",
        "neon_grid_arcade",
        "neon_grid_tunnel",
        "sierpinski_line_overlay",
        "sierpinski_recursive",
    ),
    # Neutral baseline — used as the default fallback when no family is
    # recruited. Avoids the "shuffle feel" of uniform random by keeping
    # the fallback inside a coherent aesthetic register. ALSO
    # addressable under the alias ``audio-abstract`` (see
    # ``FAMILY_ALIASES`` below) so the director_loop's preset-family
    # vocabulary routes correctly when the LLM picks the alias.
    "neutral-ambient": (
        "nightvision",
        "screwed",
        "diff_preset",
        # Audit pools 2026-05-03
        "drone_static_drift",
        "drone_dense_static",
        # 2026-05-07: 19 presets were missing from ALL families.
        # Operator directive: all 87 must be available all the time.
        # Distributed across families by aesthetic fit:
        "antivapor_grit",
        "antivapor_thresh",
        "clean",
        "tape_warmth",
        "vinyl_dust",
        "vinyl_pop_static",
        "reverie_vocabulary",
    ),
    "audio-reactive-extended": (
        "dub_echo_spatial",
        "dub_tunnel_chamber",
        "granular_stutter",
        "granular_tile_grid",
        "liquid_flow_breath",
        "liquid_flow_fluid",
        "m8_music_reactive_transport",
        "modulation_pulse_strobe",
        "modulation_pulse_warp",
        "glitch_y2k_block",
        "glitch_y2k_chroma",
        "tape_wow_flutter",
    ),
}

# Family-name aliases — kept separate from FAMILY_PRESETS so iteration
# (family_names, family_for_preset) stays canonical (one entry per
# family). Aliases resolve via _resolve_family() inside the public
# query helpers (pick_from_family, presets_for_family).
#
# Preset-variety Phase 2 (task #166): the director prompt offers
# ``audio-abstract`` as one of the five vocabulary families to the
# LLM, but the catalog only knew ``neutral-ambient`` — so an
# audio-abstract pick returned an empty preset list and recruitment
# fell through to the neutral-ambient fallback via random_mode, a
# silent monoculture amplifier. The alias closes that gap without
# renaming the canonical fallback key (which downstream code binds
# to by name in random_mode + ward_fx_mapping).
FAMILY_ALIASES: dict[str, str] = {
    "audio-abstract": "neutral-ambient",
}


def _resolve_family(family: str) -> str:
    """Resolve a family name via FAMILY_ALIASES (no-op if not aliased)."""
    return FAMILY_ALIASES.get(family, family)


# ── Programme role → family bias ────────────────────────────────────────────
# Soft prior: when a programme with a given role is active, preset
# recruitment is biased toward the role's preferred families. The bias
# is a MULTIPLIER (0.25–1.5), never zero — programmes EXPAND grounding
# opportunities, they never REPLACE grounding (memory:
# project_programmes_enable_grounding).
#
# Each entry is a tuple of (family_name, weight) pairs. Families not
# listed get weight 1.0 (no bias). A weight < 1.0 is "bias against";
# a weight > 1.0 is "bias toward". The director still picks inside
# the band — the bias just reweights recruitment likelihood.
ROLE_FAMILY_BIAS: dict[str, tuple[tuple[str, float], ...]] = {
    "listening": (("calm-textural", 1.5), ("neutral-ambient", 1.3)),
    "showcase": (("audio-reactive", 1.5), ("glitch-dense", 1.3)),
    "ritual": (("calm-textural", 1.5), ("neutral-ambient", 1.4)),
    "interlude": (("neutral-ambient", 1.5), ("calm-textural", 1.2)),
    "work_block": (("warm-minimal", 1.5), ("neutral-ambient", 1.2)),
    "tutorial": (("warm-minimal", 1.4),),
    "wind_down": (("calm-textural", 1.5), ("neutral-ambient", 1.4)),
    "hothouse_pressure": (("glitch-dense", 1.5), ("audio-reactive", 1.3)),
    "ambient": (("neutral-ambient", 1.5), ("calm-textural", 1.3)),
    "experiment": (("glitch-dense", 1.4), ("audio-reactive", 1.3)),
    "repair": (("warm-minimal", 1.4),),
    "invitation": (("audio-reactive", 1.4), ("warm-minimal", 1.2)),
    # Segmented-content roles (operator outcome 2 — alpha #2465). Each
    # is a Hapax-authored narrative format whose visual register is
    # intentionally dense or animated; biases skew toward audio-reactive
    # / glitch-dense for the high-energy formats and warm-minimal for
    # the talk-track formats. Weights mirror the operator-context
    # role magnitudes (1.3–1.5).
    "tier_list": (("audio-reactive", 1.4), ("glitch-dense", 1.3)),
    "top_10": (("audio-reactive", 1.5), ("glitch-dense", 1.3)),
    "rant": (("glitch-dense", 1.5), ("audio-reactive", 1.3)),
    "react": (("audio-reactive", 1.4), ("glitch-dense", 1.3)),
    "iceberg": (("calm-textural", 1.3), ("warm-minimal", 1.3)),
    "interview": (("warm-minimal", 1.5), ("neutral-ambient", 1.3)),
    "lecture": (("warm-minimal", 1.5), ("neutral-ambient", 1.3)),
}


def family_bias_for_role(role: str) -> dict[str, float]:
    """Return {family_name: weight} bias map for the given programme role.

    Returns an empty dict for unknown roles (no bias applied). Callers
    merge with a default weight of 1.0 for unlisted families.
    """
    entry = ROLE_FAMILY_BIAS.get(role, ())
    return dict(entry)


def pick_family_with_role_bias(
    family: str,
    role: str | None,
    *,
    rng: Random | None = None,
) -> str:
    """Potentially reroll the family based on programme role bias.

    If ``role`` is None or the family is already in the role's preferred
    set, the family passes through unchanged. Otherwise, with probability
    proportional to ``1 - role_match_strength``, the family is rerolled
    to a weighted random pick from the role's preferred families.

    The reroll is a SOFT PRIOR, not a hard gate — the original family
    can still win because the coin flip may not trigger.

    Parameters
    ----------
    family
        The originally recruited family name.
    role
        The active programme's ``ProgrammeRole.value`` string, or None.
    rng
        Optional seeded RNG for deterministic tests.
    """
    canonical = _resolve_family(family)
    if role is None:
        return canonical
    bias = family_bias_for_role(role)
    if not bias:
        return canonical
    # If the family is in the preferred set, pass through (already aligned)
    if canonical in bias:
        return canonical
    # Compute role-match strength: higher = family more role-aligned.
    # An unbiased family has strength 0.0; the reroll probability is
    # 1 - role_match_strength = 1.0 for completely misaligned families.
    chooser = rng if rng is not None else random
    # 60% chance of reroll when family is not in the preferred set.
    # This is the soft-prior: unaligned families still have a 40% chance
    # of surviving, preserving grounding diversity.
    if chooser.random() > 0.6:
        return canonical  # the original canonical family survives
    # Weighted random pick from the preferred families
    preferred_families = list(bias.keys())
    preferred_weights = [bias[f] for f in preferred_families]
    rerolled = chooser.choices(preferred_families, weights=preferred_weights, k=1)[0]
    log.info(
        "role bias reroll: %s -> %s (role=%s)",
        family,
        rerolled,
        role,
    )
    return rerolled


# Module-level last-pick memory per family to avoid back-to-back repeats
# without forcing a strict round-robin (which would be too predictable
# given many families have only 3–6 presets).
_LAST_PICK: dict[str, str] = {}


def family_names() -> list[str]:
    """Return the list of registered family names."""
    return sorted(FAMILY_PRESETS)


def family_for_preset(preset_name: str) -> str | None:
    """Return the family a preset belongs to, or ``None`` if unknown.

    HOMAGE Phase 6 Layer 5 — used by the FX chain's family-change
    publisher to tag ``FXEvent(kind="preset_family_change")`` with the
    new family name so the ward-FX reactor can route pulses per family.
    First-match wins; preset names are unique across families by
    convention, so the first hit is the canonical membership.
    """
    for family, presets in FAMILY_PRESETS.items():
        if preset_name in presets:
            return family
    return None


def presets_for_family(family: str) -> tuple[str, ...]:
    """Return the preset list for ``family``, or empty tuple if unknown.

    Resolves FAMILY_ALIASES first, so ``audio-abstract`` returns the
    ``neutral-ambient`` preset list.
    """
    return FAMILY_PRESETS.get(_resolve_family(family), ())


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
        Family name — either a key of :data:`FAMILY_PRESETS` or an
        alias from :data:`FAMILY_ALIASES`. Unknown family names log a
        warning and return ``None``.
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
    canonical = _resolve_family(family)
    if canonical not in FAMILY_PRESETS:
        log.warning("pick_from_family: unknown family %r", family)
        return None
    candidates = list(FAMILY_PRESETS[canonical])
    if available is not None:
        avail_set = set(available)
        candidates = [p for p in candidates if p in avail_set]
    if not candidates:
        log.warning(
            "pick_from_family: no candidates for family %r after filtering "
            "(family list: %s; available: %s)",
            family,
            FAMILY_PRESETS[canonical],
            None if available is None else len(available),
        )
        return None
    last_seen = last if last is not None else _LAST_PICK.get(canonical)
    non_repeat = [p for p in candidates if p != last_seen]
    pick = random.choice(non_repeat) if non_repeat else random.choice(candidates)
    _LAST_PICK[canonical] = pick
    return pick


def reset_memory() -> None:
    """Clear the per-family last-pick memory. Tests + restart use this."""
    _LAST_PICK.clear()


def _preset_tags(preset_name: str) -> tuple[str, ...]:
    """Return the ``tags`` array for ``preset_name``, or empty tuple.

    Reads the preset JSON from :data:`PRESET_DIR` and extracts the
    optional ``tags`` field. Missing / malformed / missing-field preset
    files all fall through to ``()`` so callers can treat them as
    untagged (uniform weight).
    """
    path = PRESET_DIR / f"{preset_name}.json"
    if not path.exists():
        return ()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return ()
    tags = data.get("tags") if isinstance(data, dict) else None
    if not isinstance(tags, list):
        return ()
    return tuple(str(t) for t in tags if isinstance(t, str))


def pick_with_scene_bias(
    family: str,
    scene: str | None,
    rng: Random | None = None,
    *,
    available: list[str] | None = None,
    last: str | None = None,
) -> str | None:
    """Pick a preset from ``family`` with optional scene-based weighting.

    Task #150 Phase 1. After the family has been picked (upstream, via
    the director's stance-table recruitment), this chooses a specific
    preset within the family. When ``scene`` matches a key in
    :data:`SCENE_TAG_BIAS`, presets in the family whose ``tags`` overlap
    with the scene's favored tags get ``+1`` weight per matching tag.
    Presets with no matches keep weight ``1.0``. An unknown scene, a
    scene that maps to no tags (``mixed-activity``, ``empty-room``), or
    ``scene=None`` all skip the bias entirely and fall through to
    :func:`pick_from_family`.

    Parameters
    ----------
    family
        Family name (key of :data:`FAMILY_PRESETS`). Unknown family →
        ``None``.
    scene
        Scene label published by :mod:`scene_classifier`, or ``None``
        when the classifier is off / stale.
    rng
        Optional :class:`random.Random` instance. When ``None``, the
        module-global ``random`` is used; tests pass a seeded instance
        for determinism.
    available, last
        Passed through to the underlying candidate filter + non-repeat
        memory; see :func:`pick_from_family`.

    Returns
    -------
    str | None
        A preset name from the family, or ``None`` when the family is
        unknown OR every member was filtered out by ``available``.
    """
    canonical = _resolve_family(family)
    if canonical not in FAMILY_PRESETS:
        log.warning("pick_with_scene_bias: unknown family %r", family)
        return None

    favored = SCENE_TAG_BIAS.get(scene, ()) if scene else ()
    if not favored:
        # No bias to apply — fall through to the legacy non-repeat pick.
        return pick_from_family(family, available=available, last=last)

    candidates = list(FAMILY_PRESETS[canonical])
    if available is not None:
        avail_set = set(available)
        candidates = [p for p in candidates if p in avail_set]
    if not candidates:
        log.warning(
            "pick_with_scene_bias: no candidates for family %r after filtering "
            "(family list: %s; available: %s)",
            family,
            FAMILY_PRESETS[canonical],
            None if available is None else len(available),
        )
        return None

    last_seen = last if last is not None else _LAST_PICK.get(canonical)
    non_repeat = [p for p in candidates if p != last_seen]
    pool = non_repeat if non_repeat else candidates

    favored_set = set(favored)
    weights: list[float] = []
    for preset in pool:
        tags = set(_preset_tags(preset))
        overlap = len(tags & favored_set)
        # Base weight 1.0; +1 per matching tag.
        weights.append(1.0 + float(overlap))

    chooser = rng if rng is not None else random
    pick = chooser.choices(pool, weights=weights, k=1)[0]
    _LAST_PICK[canonical] = pick
    return pick


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
    "FAMILY_ALIASES",
    "FAMILY_PRESETS",
    "ROLE_FAMILY_BIAS",
    "SCENE_TAG_BIAS",
    "family_bias_for_role",
    "family_for_preset",
    "family_names",
    "pick_and_load_mutated",
    "pick_family_with_role_bias",
    "pick_from_family",
    "pick_with_scene_bias",
    "presets_for_family",
    "reset_memory",
]
