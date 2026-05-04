"""Voice transformation tier spectrum — 7-tier ladder from clear to obliterated.

Implements Phase 1 of docs/research/2026-04-20-voice-transformation-tier-
spectrum.md: the type primitives + per-tier catalog. Tiers are vector
writers — each tier maps to a 9-dim vocal_chain vector + an optional CC
override set. ``apply_tier()`` sets the vocal chain's dimension levels
and optionally emits extra CCs that the 9-dim surface doesn't cover.

Operator-facing vocabulary:

- **T0 UNADORNED** — Kokoro raw, Evil Pet bypass-equivalent. Narration
  register. Intelligibility floor: 1.0.
- **T1 RADIO** — bandpass + mild compression. Broadcast-booth character.
  Intelligibility floor: 0.95.
- **T2 BROADCAST-GHOST** — adds reverb tail + light saturation.
  Ghostly-present voice; legible but haunted. Floor: 0.85.
- **T3 MEMORY** — heavier reverb + pitch jitter. Voice legible with
  effort; feels remembered rather than spoken. Floor: 0.65.
- **T4 UNDERWATER** — low-pass + detune. Voice present but heavily
  processed, not quite intelligible at first pass. Floor: 0.40.
- **T5 GRANULAR-WASH** — position spray + short grains via Evil Pet
  granular engine. Voice becomes texture; words dissolve. Floor: 0.15.
  MUTEX with vinyl Mode D (shared engine).
- **T6 OBLITERATED** — full granular engagement, max scatter. Voice
  indistinguishable from abstract sound. Floor: 0.0. Duration-capped
  at 15 s per research §4.

Integration points (Phase 2+, not this module):

- VocalChainCapability gains a ``granular_engagement`` dim for T5/T6
- director_loop picks tier per-tick given stance × Programme role
- Mode D mutex + single-owner lease for granular engine (per
  docs/research/2026-04-20-mode-d-voice-tier-mutex.md)
- CapabilityRecord registration with monetization_risk tags for T5/T6

References:
    - docs/research/2026-04-20-voice-transformation-tier-spectrum.md §2
    - docs/research/2026-04-20-evil-pet-cc-exhaustive-map.md §2 (CCs)
    - docs/research/2026-04-20-audio-normalization-ducking-strategy.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from shared.affordance import CapabilityRecord, MonetizationRisk, OperationalProperties

if TYPE_CHECKING:
    from shared.programme import ProgrammeRole
    from shared.stimmung import Stance


class VoiceTier(IntEnum):
    """7-tier ordering from clear-and-distinct (0) to obliterated (6).

    IntEnum so tiers compare ordinally — band ranges in the director
    router (e.g. ``T1 <= tier <= T3``) and distance calculations
    (``abs(t_from - t_to)``) both work naturally.
    """

    UNADORNED = 0
    RADIO = 1
    BROADCAST_GHOST = 2
    MEMORY = 3
    UNDERWATER = 4
    GRANULAR_WASH = 5
    OBLITERATED = 6


# Human-readable names for logs, CLI, operator UI.
TIER_NAMES: dict[VoiceTier, str] = {
    VoiceTier.UNADORNED: "unadorned",
    VoiceTier.RADIO: "radio",
    VoiceTier.BROADCAST_GHOST: "broadcast-ghost",
    VoiceTier.MEMORY: "memory",
    VoiceTier.UNDERWATER: "underwater",
    VoiceTier.GRANULAR_WASH: "granular-wash",
    VoiceTier.OBLITERATED: "obliterated",
}


@dataclass(frozen=True)
class TierProfile:
    """Static definition of one tier.

    Attributes:
        tier: The VoiceTier this profile realises.
        description: Operator-facing one-line description.
        intelligibility_floor: 0.0-1.0 lower bound on word recognition
            under this tier. T0 = 1.0, T6 = 0.0. Used by the budget
            system (§5 of the tier spectrum research doc) to cap
            cumulative unintelligibility over rolling windows.
        dimension_vector: target level for each of the 9 vocal_chain
            semantic dims. Keys are bare dim names (without the
            ``vocal_chain.`` prefix).
        cc_overrides: Extra CC writes the 9-dim surface doesn't cover.
            List of (device, channel, cc, value, note) tuples. Empty
            list means "no extra CCs, the 9-dim vector is sufficient".
        mutex_groups: Named mutex groups this tier participates in.
            T5 and T6 both claim the ``evil_pet_granular_engine`` group,
            which makes them mutex with vinyl Mode D.
        max_duration_s: Optional hard cap on how long this tier may be
            active continuously. T6 is capped at 15s per research §4.
            None = no cap.
    """

    tier: VoiceTier
    description: str
    intelligibility_floor: float
    dimension_vector: dict[str, float]
    cc_overrides: list[tuple[str, int, int, int, str]] = field(default_factory=list)
    mutex_groups: frozenset[str] = field(default_factory=frozenset)
    max_duration_s: float | None = None


# Catalog — one TierProfile per tier. Operator tunes the vectors + CC
# overrides in practice; these are the starting points from the research
# doc §2 matrix.
#
# The dimension_vector values are calibrated so each tier produces a
# distinct audible character when vocal_chain.activate_dimension() is
# called with them. T0 is "all zeros" — chain transparent. Later tiers
# progressively push dims that drive intelligibility loss (diffusion,
# temporal_distortion) and character shift (tension, spectral_color).
TIER_CATALOG: dict[VoiceTier, TierProfile] = {
    VoiceTier.UNADORNED: TierProfile(
        tier=VoiceTier.UNADORNED,
        description="Kokoro raw, Evil Pet transparent. Clear narration register.",
        intelligibility_floor=1.0,
        dimension_vector={
            "intensity": 0.0,
            "tension": 0.0,
            "diffusion": 0.0,
            "degradation": 0.0,
            "depth": 0.0,
            "pitch_displacement": 0.0,
            "temporal_distortion": 0.0,
            "spectral_color": 0.0,
            "coherence": 0.0,
        },
    ),
    VoiceTier.RADIO: TierProfile(
        tier=VoiceTier.RADIO,
        description="Bandpass + compression. Broadcast-booth intimacy.",
        intelligibility_floor=0.95,
        dimension_vector={
            "intensity": 0.35,
            "tension": 0.30,
            "diffusion": 0.0,
            "degradation": 0.0,
            "depth": 0.10,
            "pitch_displacement": 0.0,
            "temporal_distortion": 0.0,
            "spectral_color": 0.35,
            "coherence": 0.0,
        },
    ),
    VoiceTier.BROADCAST_GHOST: TierProfile(
        tier=VoiceTier.BROADCAST_GHOST,
        description="Room reverb + light saturation. Ghostly-present voice.",
        intelligibility_floor=0.85,
        dimension_vector={
            "intensity": 0.40,
            "tension": 0.30,
            "diffusion": 0.25,
            "degradation": 0.15,
            "depth": 0.35,
            "pitch_displacement": 0.0,
            "temporal_distortion": 0.10,
            "spectral_color": 0.30,
            "coherence": 0.10,
        },
    ),
    VoiceTier.MEMORY: TierProfile(
        tier=VoiceTier.MEMORY,
        description="Heavy reverb + pitch jitter. Voice legible with effort, remembered not spoken.",
        intelligibility_floor=0.65,
        dimension_vector={
            "intensity": 0.35,
            "tension": 0.25,
            "diffusion": 0.55,
            "degradation": 0.20,
            "depth": 0.65,
            "pitch_displacement": 0.30,
            "temporal_distortion": 0.25,
            "spectral_color": 0.35,
            "coherence": 0.25,
        },
    ),
    VoiceTier.UNDERWATER: TierProfile(
        tier=VoiceTier.UNDERWATER,
        description="Low-pass + detune. Voice present but heavily processed.",
        intelligibility_floor=0.40,
        dimension_vector={
            "intensity": 0.40,
            "tension": 0.50,
            "diffusion": 0.65,
            "degradation": 0.40,
            "depth": 0.75,
            "pitch_displacement": 0.55,
            "temporal_distortion": 0.40,
            "spectral_color": 0.60,
            "coherence": 0.50,
        },
    ),
    VoiceTier.GRANULAR_WASH: TierProfile(
        tier=VoiceTier.GRANULAR_WASH,
        description="Short grains + position spray. Voice becomes texture; words dissolve.",
        intelligibility_floor=0.15,
        dimension_vector={
            "intensity": 0.50,
            "tension": 0.45,
            "diffusion": 0.85,
            "degradation": 0.55,
            "depth": 0.80,
            "pitch_displacement": 0.70,
            "temporal_distortion": 0.75,
            "spectral_color": 0.55,
            "coherence": 0.75,
        },
        cc_overrides=[
            # Engage Evil Pet granular engine — T5/T6 are the only tiers
            # that do. MUTEX with vinyl Mode D (both want CC 11 hot).
            ("evil_pet", 0, 11, 90, "grains volume → 70% (engine active)"),
            ("evil_pet", 0, 40, 110, "mix → 86% wet (defeat-range)"),
        ],
        mutex_groups=frozenset({"evil_pet_granular_engine"}),
    ),
    VoiceTier.OBLITERATED: TierProfile(
        tier=VoiceTier.OBLITERATED,
        description="Full granular engagement. Voice indistinguishable from abstract sound.",
        intelligibility_floor=0.0,
        dimension_vector={
            "intensity": 0.60,
            "tension": 0.50,
            "diffusion": 1.0,
            "degradation": 0.75,
            "depth": 0.85,
            "pitch_displacement": 0.85,
            "temporal_distortion": 0.95,
            "spectral_color": 0.60,
            "coherence": 1.0,
        },
        cc_overrides=[
            ("evil_pet", 0, 11, 120, "grains volume → 94% (max engagement)"),
            ("evil_pet", 0, 40, 127, "mix → 100% wet"),
            ("evil_pet", 0, 94, 60, "shimmer → 47% (iridescent cloud)"),
        ],
        mutex_groups=frozenset({"evil_pet_granular_engine"}),
        max_duration_s=15.0,
    ),
}


def profile_for(tier: VoiceTier) -> TierProfile:
    """Look up the TierProfile for ``tier``. Raises KeyError on unknown."""
    return TIER_CATALOG[tier]


def apply_tier(
    tier: VoiceTier,
    vocal_chain: Any,
    midi_output: Any | None = None,
    impingement: Any | None = None,
) -> None:
    """Apply ``tier`` to ``vocal_chain`` — set the 9-dim vector + emit CC overrides.

    Args:
        tier: Which tier to apply.
        vocal_chain: A VocalChainCapability instance. Must expose
            ``activate_dimension(name, impingement, level)`` with the
            existing semantics (see ``agents/hapax_daimonion/
            vocal_chain.py``).
        midi_output: Optional MidiOutput for CC overrides. If None and
            the tier declares overrides, they are silently skipped
            (callers can check ``profile.cc_overrides`` to decide).
        impingement: Optional Impingement attribution for the dim
            activations. If None, callers SHOULD construct a synthetic
            one with ``source="voice_tier"`` so telemetry attributes
            the change correctly.

    Purely-additive: does not reset dims the tier omits. Callers are
    responsible for ``vocal_chain.deactivate()`` before tier transitions
    if a full reset is desired.
    """
    profile = profile_for(tier)
    for dim_name, level in profile.dimension_vector.items():
        full_name = dim_name if dim_name.startswith("vocal_chain.") else f"vocal_chain.{dim_name}"
        vocal_chain.activate_dimension(full_name, impingement, level)
    if midi_output is not None:
        for _device, channel, cc, value, _note in profile.cc_overrides:
            try:
                midi_output.send_cc(channel=channel, cc=cc, value=value)
            except Exception:  # pragma: no cover — tolerate MIDI-down case
                pass


@dataclass(frozen=True)
class RoleTierBand:
    """Per-ProgrammeRole default tier band + excursion whitelist.

    ``default_band`` is the (low, high) structural band the structural
    director picks inside for a steady-state tick. ``excursion_set`` is
    the whitelist of tiers the narrative director may *jump to* for a
    single tick on an explicit impingement trigger (§4.2 of
    2026-04-20-voice-tier-director-integration.md), bypassing the band
    clamp. Excursion triggers are rate-limited (one per 60 s per
    Programme instance) — that stateful guard is the narrative
    director's concern, not this data's.
    """

    default_band: tuple[VoiceTier, VoiceTier]
    excursion_set: frozenset[VoiceTier] = field(default_factory=frozenset)


# Per-role defaults — see §2 of 2026-04-20-voice-tier-director-integration.md.
#
# Non-contiguous bands (RITUAL: TIER_0 *or* TIER_5-6) are encoded with the
# anchor as the default band and the marker tiers in excursion_set — the
# selector returns the anchor on a steady tick, and the narrative director
# flips to the marker via an explicit excursion request on ritual beats.
# This preserves the "no middle band" rule of RITUAL (the resolver would
# never silently land between the two bands).
_ROLE_TIER_DEFAULTS: dict[str, RoleTierBand] = {
    # Keyed by ProgrammeRole.value (StrEnum). Lookup via role.value so
    # this module has zero runtime coupling to shared.programme — the
    # ProgrammeRole import is annotation-only (TYPE_CHECKING).
    "listening": RoleTierBand(
        default_band=(VoiceTier.UNADORNED, VoiceTier.BROADCAST_GHOST),
        excursion_set=frozenset({VoiceTier.MEMORY}),
    ),
    "showcase": RoleTierBand(
        default_band=(VoiceTier.RADIO, VoiceTier.MEMORY),
        excursion_set=frozenset({VoiceTier.UNDERWATER}),
    ),
    "ritual": RoleTierBand(
        default_band=(VoiceTier.UNADORNED, VoiceTier.UNADORNED),
        excursion_set=frozenset({VoiceTier.GRANULAR_WASH, VoiceTier.OBLITERATED}),
    ),
    "interlude": RoleTierBand(
        default_band=(VoiceTier.BROADCAST_GHOST, VoiceTier.MEMORY),
        excursion_set=frozenset({VoiceTier.UNDERWATER}),
    ),
    "work_block": RoleTierBand(
        default_band=(VoiceTier.UNADORNED, VoiceTier.RADIO),
        excursion_set=frozenset({VoiceTier.BROADCAST_GHOST}),
    ),
    "tutorial": RoleTierBand(
        default_band=(VoiceTier.UNADORNED, VoiceTier.UNADORNED),
        excursion_set=frozenset({VoiceTier.RADIO}),
    ),
    "wind_down": RoleTierBand(
        default_band=(VoiceTier.BROADCAST_GHOST, VoiceTier.UNDERWATER),
        excursion_set=frozenset({VoiceTier.GRANULAR_WASH}),
    ),
    "hothouse_pressure": RoleTierBand(
        default_band=(VoiceTier.MEMORY, VoiceTier.GRANULAR_WASH),
        excursion_set=frozenset({VoiceTier.OBLITERATED}),
    ),
    "ambient": RoleTierBand(
        default_band=(VoiceTier.UNADORNED, VoiceTier.BROADCAST_GHOST),
        excursion_set=frozenset(),
    ),
    "experiment": RoleTierBand(
        default_band=(VoiceTier.UNADORNED, VoiceTier.OBLITERATED),
        excursion_set=frozenset(),
    ),
    "repair": RoleTierBand(
        default_band=(VoiceTier.UNADORNED, VoiceTier.UNADORNED),
        excursion_set=frozenset({VoiceTier.RADIO}),
    ),
    "invitation": RoleTierBand(
        default_band=(VoiceTier.UNADORNED, VoiceTier.RADIO),
        excursion_set=frozenset({VoiceTier.BROADCAST_GHOST}),
    ),
    # Segmented-content formats (operator outcome 2). Bands per the
    # cc-task `segmented-content-formats-expansion`:
    #   tier_list / top_10 → mid (work_block-like, structured exposition)
    #   rant              → high (sustained vocal energy, processed)
    #   react             → high (responsive, expressive)
    #   iceberg           → low-to-mid (depth-tiered surface→deep)
    #   interview         → mid (dialogue)
    #   lecture           → mid (extended monologue, intelligibility-critical)
    "tier_list": RoleTierBand(
        default_band=(VoiceTier.UNADORNED, VoiceTier.RADIO),
        excursion_set=frozenset({VoiceTier.BROADCAST_GHOST}),
    ),
    "top_10": RoleTierBand(
        default_band=(VoiceTier.UNADORNED, VoiceTier.RADIO),
        excursion_set=frozenset({VoiceTier.BROADCAST_GHOST}),
    ),
    "rant": RoleTierBand(
        default_band=(VoiceTier.MEMORY, VoiceTier.UNDERWATER),
        excursion_set=frozenset({VoiceTier.GRANULAR_WASH}),
    ),
    "react": RoleTierBand(
        default_band=(VoiceTier.MEMORY, VoiceTier.UNDERWATER),
        excursion_set=frozenset({VoiceTier.BROADCAST_GHOST}),
    ),
    "iceberg": RoleTierBand(
        default_band=(VoiceTier.UNADORNED, VoiceTier.BROADCAST_GHOST),
        excursion_set=frozenset({VoiceTier.MEMORY, VoiceTier.UNDERWATER}),
    ),
    "interview": RoleTierBand(
        default_band=(VoiceTier.UNADORNED, VoiceTier.RADIO),
        excursion_set=frozenset({VoiceTier.BROADCAST_GHOST}),
    ),
    "lecture": RoleTierBand(
        default_band=(VoiceTier.UNADORNED, VoiceTier.UNADORNED),
        excursion_set=frozenset({VoiceTier.RADIO}),
    ),
}


def role_tier_band(role: ProgrammeRole | str) -> RoleTierBand:
    """Look up the ``RoleTierBand`` for a ``ProgrammeRole``.

    Accepts either the enum or the raw string value (StrEnum equality).
    Raises ``KeyError`` on unknown roles — mirrors ``profile_for``.
    """
    key = role.value if hasattr(role, "value") else str(role)
    return _ROLE_TIER_DEFAULTS[key]


def stance_tier_delta(stance: Stance | str) -> int:
    """Per-stance additive tier bias, before DEGRADED/CRITICAL override.

    Per §3.1: SEEKING → +1 (tracks exploration_deficit); all other
    non-override stances return 0. DEGRADED/CRITICAL are *not* additive
    — they clamp/cap instead — and ``resolve_tier`` handles them before
    this delta is even consulted.
    """
    key = stance.value if hasattr(stance, "value") else str(stance)
    if key == "seeking":
        return 1
    return 0


def _baseline_for_band(band: tuple[VoiceTier, VoiceTier]) -> VoiceTier:
    """Band midpoint rounded *toward high* — §3.1 baseline rule.

    Example: band (1, 3) → baseline 2; band (0, 2) → baseline 1; band
    (0, 6) → baseline 3. Ceiling-division lifts (1,2) to 2 and (0,1) to
    1 so the baseline never lands below the middle of an even-length
    band.
    """
    low, high = int(band[0]), int(band[1])
    return VoiceTier((low + high + 1) // 2)


def resolve_tier(
    role: ProgrammeRole | str,
    stance: Stance | str,
    programme_band_prior: tuple[VoiceTier, VoiceTier] | None = None,
) -> VoiceTier:
    """Pick a tier for the current tick from role + stance.

    Per §2 and §3 of 2026-04-20-voice-tier-director-integration.md:

    1. Effective band = ``programme_band_prior`` if the Programme
       envelope overrides, else ``role_tier_band(role).default_band``.
       Unset prior = "no preference, use the role default" (soft-prior
       pattern — never an exclusion).
    2. CRITICAL stance → clamp to band-low (maximal intelligibility for
       recovery narration; overrides impingement-driven shifts).
    3. DEGRADED stance → cap tier at ``min(band_high, TIER_MEMORY)``;
       if band-low > TIER_MEMORY, clamp to band-low instead.
    4. Other stances → baseline = midpoint→high, plus
       ``stance_tier_delta(stance)``, clamped to the band.

    Impingement-driven shifts (§4) and excursion jumps (§4.2) compose on
    top of this pick — they live in the narrative director, not here.

    Args:
        role: ProgrammeRole or string role value.
        stance: Stance or string stance value.
        programme_band_prior: Optional override for the role default.
            If given, takes precedence over the role default. Must
            satisfy low ≤ high or the function raises ValueError.

    Returns:
        The selected VoiceTier.
    """
    if programme_band_prior is not None:
        low, high = programme_band_prior
        if int(low) > int(high):
            raise ValueError(f"programme_band_prior={programme_band_prior!r} — low must be ≤ high")
        band = (VoiceTier(int(low)), VoiceTier(int(high)))
    else:
        band = role_tier_band(role).default_band

    band_low, band_high = band
    stance_key = stance.value if hasattr(stance, "value") else str(stance)

    if stance_key == "critical":
        return band_low
    if stance_key == "degraded":
        # Cap at TIER_MEMORY unless band-low is already higher.
        if int(band_low) > int(VoiceTier.MEMORY):
            return band_low
        cap = min(int(band_high), int(VoiceTier.MEMORY))
        return VoiceTier(cap)

    baseline = _baseline_for_band(band)
    picked = int(baseline) + stance_tier_delta(stance)
    picked = max(int(band_low), min(int(band_high), picked))
    return VoiceTier(picked)


# -----------------------------------------------------------------
# Phase 4 — monetization classification + capability registration +
# intelligibility budget.
#
# Why per-tier risk: the MonetizationRiskGate reads ``monetization_risk``
# off the candidate payload (shared/governance/monetization_safety.py
# L117). For voice output, the tier — not the Kokoro engine itself —
# determines whether the render is Content-ID-safe and viewer-tolerable.
# UNADORNED narration is zero risk; OBLITERATED pure granular-wash is
# both a Content-ID false-positive magnet (tape-loop-like textures) and a
# listener-abandonment risk when sustained, so it ships as "high" and
# needs explicit excursion + duration cap to render at all.
# -----------------------------------------------------------------

TIER_MONETIZATION_RISK: dict[VoiceTier, MonetizationRisk] = {
    VoiceTier.UNADORNED: "none",
    VoiceTier.RADIO: "none",
    VoiceTier.BROADCAST_GHOST: "none",
    VoiceTier.MEMORY: "none",
    VoiceTier.UNDERWATER: "low",
    VoiceTier.GRANULAR_WASH: "medium",
    VoiceTier.OBLITERATED: "high",
}

TIER_RISK_REASONS: dict[VoiceTier, str] = {
    VoiceTier.UNADORNED: "",
    VoiceTier.RADIO: "",
    VoiceTier.BROADCAST_GHOST: "",
    VoiceTier.MEMORY: "",
    VoiceTier.UNDERWATER: ("heavily processed but audible; minor viewer-parse cost"),
    VoiceTier.GRANULAR_WASH: (
        "Evil Pet granular engine + 0.85 diffusion produces tape-loop-like "
        "texture that can ping Content-ID false-positives; needs Programme "
        "opt-in"
    ),
    VoiceTier.OBLITERATED: (
        "pure granular dissolution at 0.0 intelligibility floor; unbounded "
        "listener-abandonment + Content-ID risk — gated behind explicit "
        "excursion + 15 s duration cap"
    ),
}


def tier_capability_record(tier: VoiceTier) -> CapabilityRecord:
    """Build a ``CapabilityRecord`` for a tier so the affordance pipeline
    can score tier selection as a recruitable capability.

    Phase 4 does NOT auto-register these — the daimonion bootstrap
    registers them explicitly (deferred to the wiring step). This helper
    exists so that registration + ad-hoc gate checks use the same shape.

    The returned record ships:
    - ``name = 'voice.tier.<canonical>'`` keyed off ``TIER_NAMES``
    - ``description`` = Gibson-verb shape, 20-30 words, describing the
      vocal affordance rather than the engine
    - ``operational.medium = 'auditory'`` (destination-modality routing)
    - ``operational.monetization_risk`` from ``TIER_MONETIZATION_RISK``
    - ``operational.risk_reason`` from ``TIER_RISK_REASONS`` (empty for
      zero-risk tiers)
    - ``operational.consent_required = False`` (voice tier is the
      operator's own output; consent contracts gate capture/persistence,
      not emission)

    Callers that register these records MUST dedup by ``name`` — the
    affordance registry rejects duplicate names.
    """
    profile = profile_for(tier)
    canonical = TIER_NAMES[tier].replace("-", "_")
    description = (
        f"Render speech in the {TIER_NAMES[tier]} register — "
        f"{profile.description} Intelligibility floor {profile.intelligibility_floor:.2f}."
    )
    reason = TIER_RISK_REASONS.get(tier) or None
    return CapabilityRecord(
        name=f"voice.tier.{canonical}",
        description=description,
        daemon="hapax-daimonion",
        operational=OperationalProperties(
            latency_class="fast",
            medium="auditory",
            consent_required=False,
            monetization_risk=TIER_MONETIZATION_RISK[tier],
            risk_reason=reason,
        ),
    )


def all_tier_capability_records() -> list[CapabilityRecord]:
    """Return the full 7-tier CapabilityRecord set in ordinal order."""
    return [tier_capability_record(t) for t in VoiceTier]


# -----------------------------------------------------------------
# Intelligibility budget — rolling-window cap on cumulative
# unintelligibility. Prevents the narrative director from chaining high-
# tier picks into a sustained stretch where the operator's speech is
# unintelligible for minutes at a time. Units are "unit-minutes of
# intelligibility loss" — a tier-4 stretch (floor 0.40) active for 60 s
# consumes (1 - 0.40) × (60/60) = 0.6 unit-minutes.
# -----------------------------------------------------------------


@dataclass
class IntelligibilityBudget:
    """Stateful tracker for cumulative unintelligibility over a window.

    Attributes:
        window_s: Size of the rolling window (default 600 s = 10 min).
        budget_units: Hard cap on cumulative unintelligibility inside the
            window, in unit-minutes. Default 3.0 — permits ~7.5 min at
            TIER_UNDERWATER (floor 0.40, loss 0.60/min) or ~5 min at
            TIER_GRANULAR_WASH (floor 0.15, loss 0.85/min).
        lookahead_s: How far ahead ``pick_allowed`` projects a tier's
            cost when deciding admissibility. Default 15 s.
    """

    window_s: float = 600.0
    budget_units: float = 3.0
    lookahead_s: float = 15.0
    _spans: list[tuple[float, float, VoiceTier]] = field(default_factory=list)

    def consumed(self, now: float) -> float:
        """Unit-minutes of unintelligibility inside ``(now - window, now]``."""
        cutoff = now - self.window_s
        total_unit_seconds = 0.0
        for start, end, tier in self._spans:
            overlap_start = max(start, cutoff)
            overlap_end = min(end, now)
            if overlap_end <= overlap_start:
                continue
            duration = overlap_end - overlap_start
            loss = 1.0 - profile_for(tier).intelligibility_floor
            total_unit_seconds += duration * loss
        return total_unit_seconds / 60.0

    def remaining(self, now: float) -> float:
        """Budget units not yet consumed; clamped at 0."""
        return max(0.0, self.budget_units - self.consumed(now))

    def record(self, start_ts: float, end_ts: float, tier: VoiceTier) -> None:
        """Record a span during which ``tier`` was active."""
        if end_ts < start_ts:
            raise ValueError(
                f"end_ts ({end_ts}) must be ≥ start_ts ({start_ts}) — IntelligibilityBudget.record"
            )
        self._spans.append((start_ts, end_ts, tier))
        cutoff = start_ts - self.window_s
        self._spans = [s for s in self._spans if s[1] > cutoff]

    def pick_allowed(self, tier: VoiceTier, now: float) -> bool:
        """Check whether ``tier`` fits ``lookahead_s`` ahead in current budget."""
        loss_per_min = 1.0 - profile_for(tier).intelligibility_floor
        projected_cost = loss_per_min * (self.lookahead_s / 60.0)
        return self.remaining(now) >= projected_cost

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict for SHM persistence.

        Tier values serialise as their int values; caller reconstructs
        via ``from_dict``. Spans compact to ``[start, end, tier_int]``
        tuples so readers don't depend on our field names.
        """
        return {
            "window_s": self.window_s,
            "budget_units": self.budget_units,
            "lookahead_s": self.lookahead_s,
            "spans": [[s, e, int(t)] for s, e, t in self._spans],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntelligibilityBudget:
        """Reconstruct from the ``to_dict`` shape.

        Malformed span entries (wrong length, out-of-range tier,
        non-finite timestamps) are dropped silently — the budget
        shouldn't reject valid future writes just because an earlier
        one corrupted the file. Caller can observe the drop via
        ``len(self._spans)`` vs the raw input.
        """
        raw_spans = data.get("spans", [])
        spans: list[tuple[float, float, VoiceTier]] = []
        for row in raw_spans:
            if not isinstance(row, list) or len(row) != 3:
                continue
            start, end, tier_int = row
            try:
                tier = VoiceTier(int(tier_int))
            except (ValueError, TypeError):
                continue
            try:
                start_f, end_f = float(start), float(end)
            except (TypeError, ValueError):
                continue
            if end_f < start_f:
                continue
            spans.append((start_f, end_f, tier))
        budget = cls(
            window_s=float(data.get("window_s", 600.0)),
            budget_units=float(data.get("budget_units", 3.0)),
            lookahead_s=float(data.get("lookahead_s", 15.0)),
        )
        budget._spans = spans
        return budget

    def save(self, path: Path) -> None:
        """Atomic tmp+rename write so readers never see half-written JSON."""
        import json
        import os

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), sort_keys=True))
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> IntelligibilityBudget:
        """Read from disk; empty budget on missing/corrupt file.

        Fail-safe: if the file doesn't exist or is corrupt, return a
        fresh budget with default bounds. The director never sees a
        half-loaded state that might silently permit an over-budget
        tier.
        """
        import json

        try:
            data = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls.from_dict(data)

    def clamp_tier(self, tier: VoiceTier, now: float) -> VoiceTier:
        """Downshift ``tier`` until it fits remaining budget. Never below UNADORNED."""
        current = tier
        while current != VoiceTier.UNADORNED and not self.pick_allowed(current, now):
            current = VoiceTier(int(current) - 1)
        return current


def tier_from_name(name: str) -> VoiceTier:
    """Parse a human-readable tier name into a VoiceTier. Case-insensitive.

    Accepts the canonical names from ``TIER_NAMES`` plus common aliases
    ("clear" for UNADORNED, "obliterated"/"max"/"full" for OBLITERATED).
    Raises ValueError on unknown names.
    """
    key = name.strip().lower().replace("_", "-")
    aliases: dict[str, VoiceTier] = {
        "t0": VoiceTier.UNADORNED,
        "clear": VoiceTier.UNADORNED,
        "t1": VoiceTier.RADIO,
        "t2": VoiceTier.BROADCAST_GHOST,
        "t3": VoiceTier.MEMORY,
        "t4": VoiceTier.UNDERWATER,
        "t5": VoiceTier.GRANULAR_WASH,
        "granular": VoiceTier.GRANULAR_WASH,
        "t6": VoiceTier.OBLITERATED,
        "max": VoiceTier.OBLITERATED,
        "full": VoiceTier.OBLITERATED,
    }
    if key in aliases:
        return aliases[key]
    for tier, canonical in TIER_NAMES.items():
        if canonical == key:
            return tier
    raise ValueError(
        f"unknown voice tier: {name!r}. Accepted: {sorted(TIER_NAMES.values())} or t0..t6"
    )
