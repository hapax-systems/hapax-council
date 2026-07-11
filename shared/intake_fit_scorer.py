"""Intake fit-scorer — the demand-side magnitude feeding the dispatch rank-key.

``plan_dispatches`` ranks each lane's eligible tasks by aged WSJF alone; this module adds a
demand-shape term — a ``fit_score`` derived from the decomposer-written 8-dim
``requirement_vector`` — behind a default-off blend flag. It is the demand-side input to the
eventual (1)↔(2) ``re_route`` loop; this slice wires that signal (+ its telemetry emit), not
the engine itself — ``SdlcRouter.route`` remains unwired into dispatch (a follow-on slice).

Honesty about what this score IS and is NOT (adversarial review 2026-07-04):

* It is a **task-level demand magnitude** — the mean demand over the task's *active*
  non-``quality_floor`` dimensions (score ``> 0``), on the engine's ``0..5`` scale.
* It is **NOT** a projection of the engine's per-(task, candidate) ``requirement_fit``
  (``shared.sdlc_router.SdlcRouter._score_candidate``). That quantity averages the
  *candidate's capability_scores* over the task's active demand dims — it is irreducibly
  per-(task, route) and has no task-only form. This scorer shares only the ``0..5`` scale,
  the ``quality_floor`` exclusion, and the ``>0`` "active dimension" filter (the engine's
  ``_scored_requirement_dimensions``) — the demand side of the same taxonomy, not a shadow
  of the engine's supply-side score.

The ``>0`` active-dim filter is load-bearing for correctness: a *focused-hot* task
(one dim at 5, the rest 0) must rank ABOVE a *diffuse-medium* task (every dim at 3) under a
positive blend — averaging in the zero dims would invert that (0.71 vs 3.0), rewarding
diffuse demand over concentrated critical demand. ``quality_floor`` is excluded for the same
reason the engine excludes it — a hard floor enforced as a veto, not a soft score.

Honest-DARK (mirror of iter-1's ``_parse_requirement_vector``): an absent, partial, or
non-strict-int vector yields ``0.0`` and exerts zero influence when blended. The scorer
NEVER raises (a hostile mapping's iteration is caught and treated as DARK) and NEVER returns
NaN/inf — it is evaluated inside the dispatch rank-key, where a crash or a poisoned sort key
would break the scheduler. Out-of-range and bool values are excluded per-dimension (bool is a
subclass of int but is not a strict-int score), never coerced.

The composite rank-key's golden guarantee: ``blend == 0.0`` short-circuits to ``wsjf_eff``
EXACTLY (returned by identity, not ``wsjf + 0.0 * fit``) so the dispatch plan is byte-identical
to the pre-blend behavior under the default-off flag — the permanent shadow-diff discipline
(``docs/superpowers/specs/2026-05-30-sdlc-frictionless-self-direction-design.md`` §audit C4).
The short-circuit also makes the blend=0 path immune to a NaN/inf ``fit``.
"""

from __future__ import annotations

from collections.abc import Mapping

from shared.sdlc_router import REQUIREMENT_VECTOR_DIMENSIONS

# Excluded from scoring (a hard floor / veto, not a soft score) — mirrors the engine's
# ``_scored_requirement_dimensions``. Source of truth: ``shared.sdlc_router.REQUIREMENT_VECTOR_DIMENSIONS``.
_QUALITY_FLOOR_DIMENSION = "quality_floor"
# The dimensions ``fit_score`` will score: the canonical eight MINUS the ``quality_floor`` veto.
# An unknown key (a typo, a stale decomposer entry) is dropped here as defense-in-depth — it can
# never inflate the score. The parse gate (``coordinator.core._parse_requirement_vector``) is
# stricter still: a vector carrying an unknown dim OR an out-of-range score is rejected wholesale
# (returns None → honest-DARK), so the live dispatch path never reaches ``fit_score`` with
# malformed frontmatter. This guard exists so a direct/test caller cannot score garbage either.
_SCORED_DIMENSIONS = frozenset(REQUIREMENT_VECTOR_DIMENSIONS) - {_QUALITY_FLOOR_DIMENSION}


def fit_score(requirement_vector: Mapping[str, int] | None) -> float:
    """Task-level demand magnitude on the engine's 0..5 scale (0.0 = DARK/neutral).

    The mean of the strict-int (bool rejected) ``1..5`` scores over the canonical non-
    ``quality_floor`` dimensions present in ``requirement_vector`` — ``quality_floor`` is a
    veto (not a soft score), and any key outside ``REQUIREMENT_VECTOR_DIMENSIONS`` is dropped
    (defense-in-depth: a typo or stale decomposer entry can never inflate the score). A dim
    scored ``0`` is *inactive* demand (mirror of the engine's ``>0`` filter) and is excluded
    from both the numerator and the denominator, so a focused-hot task outranks a diffuse-
    medium one. ``None``, a non-mapping, an empty mapping, a mapping whose scored dims are all
    inactive/invalid, or a hostile mapping whose iteration raises all return ``0.0`` — honest-
    DARK, never raises, never NaN.
    """
    try:
        if not isinstance(requirement_vector, Mapping):
            return 0.0
        scored: list[int] = []
        for dim, value in requirement_vector.items():
            # Only the canonical scored dimensions count: ``quality_floor`` (a hard veto, not a
            # soft score) and any unknown key (typo / stale decomposer entry) are both excluded.
            if dim not in _SCORED_DIMENSIONS:
                continue
            # bool is a subclass of int — reject it (strict-int scores, mirror iter-1 + the engine).
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            if (
                value <= 0 or value > 5
            ):  # <=0: inactive demand (engine's >0 filter); >5: out of range
                continue
            scored.append(value)
        if not scored:
            return 0.0
        return sum(scored) / len(scored)
    except Exception:  # noqa: BLE001 - a hostile Mapping's .items() must not break the scheduler.
        return 0.0


def composite_rank_key(wsjf_effective_value: float, fit: float, *, blend: float) -> float:
    """The dispatch rank-key: aged WSJF plus a blended demand-shape term.

    ``blend == 0.0`` returns ``wsjf_effective_value`` by identity — the byte-identical
    golden guarantee (the default-off flag changes nothing in the plan). Any non-zero
    blend (positive OR negative) flows through as plain arithmetic,
    ``wsjf_effective_value + blend * fit`` — this pure function does NOT clamp; range
    policy is enforced at the env gate (``_intake_fit_blend`` clamps
    ``HAPAX_INTAKE_FIT_BLEND`` to the task-spec's ``[0.0, 0.5)`` safe range before it ever
    reaches the rank-key). ``fit`` lives on ``0..5`` while ``wsjf_effective_value`` lives
    on roughly ``1..30`` (raw wsjf ``1..10`` × aging factor ``1..3``), so a blend of
    ``~1`` is a light weight, ``~3`` moderate, ``~5+`` strong.
    """
    if blend == 0.0:
        return wsjf_effective_value
    return wsjf_effective_value + blend * fit
