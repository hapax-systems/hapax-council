"""Changing-criterion phase controller for the seg-prep SCED (G3 / LANE-DATA-SPINE #12).

This is the control logic of the changing-criterion single-case experimental design (SCED):
given the producer dependent-variable observations captured by ``segment_prep_dv_reader`` and a
phase plan (the C_k ladder + the §5.1 length/stability parameters), it decides whether the active
phase should HOLD (keep collecting), ADVANCE to the next criterion, or that the run is COMPLETE,
and it emits the next C_k.

It deliberately consumes only the lightweight ``segment_prep_dv_reader`` types (no pydantic-ai /
council imports) so it can run in plain analysis / runner contexts.

The ratified rule (``experiment-design-changing-criterion-sced-2026-06-15.md`` §5.1, which
SUPERSEDES the retired Cycle-2 min-10/max-20 numbers):

* **Baseline (A0):** floor only. Min 8 hosted segments; advance when the last 3 pre-gate means are
  within 20% (stability); max 15.
* **C1 … Cn:** each phase sets C_k > C_{k-1}; same length/stability rules; ≥ 4 ascending steps.
* **Probe / mini-reversal (R):** at least one phase LOWERS the criterion.

Operationalization choices made explicit here (configurable on ``PhasePlan``):

* "Min 8 hosted" → the phase-length FLOOR is ``PhaseSummary.released``. NB this is prep-released
  (passed the coherence gate); the spec's "hosted" denotes aired-in-the-dyad. For the A0 floor-only
  block these largely coincide; an aired-vs-released divergence is an open item for the operator at
  the G8 air step (the ledger carries no aired signal today).
* The spec says "the last 3 PHASE means within 20%". Inside A0 (the first phase) there are no prior
  phase means, so this is operationalized as the trailing ``stability_window`` (default 3) of the
  producer pre-gate ``mean_score`` series WITHIN the active phase (the real DV per §5.2), with
  relative range ``(max - min) / mean`` ≤ ``stability_tolerance`` (default 0.20).
* "max 15" bounds the phase length in PRODUCED segments (total observations = hosted + the gated
  tail), NOT in hosted units — so a non-converging / yield-collapsed phase (the §6 "ceiling reached"
  case) still terminates instead of holding forever for a release count that never arrives.

For the first fully-operative loop (the A0 floor-only block) the plan is a single criterion, so the
controller signals ``baseline_complete`` once the A0 stop condition is met — the stop signal the A0
runner needs, distinct from ``complete`` (a fully-exhausted multi-step ladder). The C1…Cn ladder +
reversal values are calibrate-then-commit from A0 data (operator, post-A0); a phase whose next
criterion is LOWER than the current one is flagged as a reversal probe.

Consumer contract for ``next_criterion``: ``daily_segment_prep`` resolves C_k once at module import
(from ``HAPAX_COHERENCE_CRITERION``) and never re-reads it, so an emitted advance is actionable ONLY
by setting that env var (directly from the ``next_criterion`` float) and re-invoking prep as a FRESH
process. A runner that imports ``run_prep`` and loops in-process would silently keep gating + stamping
the stale import-time C_k.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.segment_prep_dv_reader import PhaseSummary, ProducerObservation, summarize_phases

# Mirrors segment_prep_dv_reader._CRITERION_KEY_PRECISION so a plan's C_k values key into the
# reader's per-phase summaries (which round the grouping key). Drift-guarded by a test.
_CRITERION_KEY_PRECISION = 6


@dataclass(frozen=True)
class PhasePlan:
    """The changing-criterion ladder + the §5.1 length/stability parameters.

    ``criteria`` is the ordered sequence of C_k values the run steps through (NOT necessarily
    ascending: at least one entry should be LOWER than its predecessor — the reversal probe).
    Each phase is identified in the captured DV by its C_k VALUE, so the values MUST be distinct
    (a reused value would silently merge two phases; the reversal lowers to a value no intermediate
    phase uses, which §5.3's varied step sizes make natural). The spec's "or holds it" reversal
    variant (a repeated C_k) is therefore deliberately out of scope for this value-keyed plan. For
    the A0 floor-only block ``criteria`` is a single value.

    Misconfiguration fails LOUD (``__post_init__`` raises) rather than silently changing the stop
    behavior — this controller gates a live-broadcast experiment.
    """

    criteria: tuple[float, ...]
    min_hosted: int = 8
    max_segments: int = 15
    stability_window: int = 3
    stability_tolerance: float = 0.20

    def __post_init__(self) -> None:
        if not self.criteria:
            raise ValueError("PhasePlan.criteria must be non-empty")
        keys = [round(c, _CRITERION_KEY_PRECISION) for c in self.criteria]
        if len(set(keys)) != len(keys):
            raise ValueError(
                "PhasePlan.criteria must be distinct C_k values — phases are keyed by value in the "
                "captured DV, so a reused value silently merges two phases (the reversal probe must "
                "lower to a value no intermediate phase uses)"
            )
        if self.stability_window < 1:
            raise ValueError("PhasePlan.stability_window must be >= 1")
        if self.min_hosted < self.stability_window:
            raise ValueError(
                "PhasePlan.min_hosted must be >= stability_window, else the floor passes before "
                "stability can ever be computed"
            )
        if self.max_segments < self.min_hosted:
            raise ValueError("PhasePlan.max_segments must be >= min_hosted")
        if self.stability_tolerance <= 0:
            raise ValueError("PhasePlan.stability_tolerance must be > 0")


def is_stable(scores: list[float], *, window: int = 3, tolerance: float = 0.20) -> bool:
    """True iff the producer DV is stable over its trailing ``window`` observations.

    Stability (§5.1) = the last ``window`` pre-gate means are within ``tolerance`` of each other,
    operationalized as the relative range ``(max - min) / mean`` ≤ ``tolerance``. A non-positive
    ``window``, fewer than ``window`` observations, or a non-positive window mean cannot be declared
    stable (the relative-range formula assumes a positive central value).
    """
    if window <= 0 or len(scores) < window:
        return False
    last = scores[-window:]
    mean = sum(last) / len(last)
    if mean <= 0:
        return False
    return (max(last) - min(last)) / mean <= tolerance


def phase_complete(summary: PhaseSummary, plan: PhasePlan) -> tuple[bool, str]:
    """Whether the active phase has met the §5.1 stop condition, with a human-readable reason.

    Order matters: the ``max_segments`` cap force-advances even when the DV has not stabilized, so
    it is checked first; below ``min_hosted`` the phase always keeps collecting. Two DIFFERENT
    denominators are deliberate (do NOT "simplify" them to one, or the producer/filter conflation
    §5.2 forbids returns): the cap and the floor count SEGMENTS (cap = total produced ``summary.n``;
    floor = released ``summary.released``), while stability is judged on the full pre-gate producer
    score series (the DV, independent of selection). Capping on TOTAL produced segments is what lets
    a yield-collapsed / ceiling phase terminate (§6) instead of waiting on a release count that never
    arrives.
    """
    hosted = summary.released
    produced = summary.n
    if produced >= plan.max_segments:
        detail = f"produced={produced} >= max_segments={plan.max_segments}"
        if hosted < plan.min_hosted:
            detail += f", hosted={hosted} < min {plan.min_hosted} (likely ceiling / yield-collapse)"
        return True, f"max-segments cap reached ({detail})"
    if hosted < plan.min_hosted:
        return (
            False,
            f"collecting: hosted={hosted} < min_hosted={plan.min_hosted} (produced={produced})",
        )
    if is_stable(
        summary.pre_gate_scores,
        window=plan.stability_window,
        tolerance=plan.stability_tolerance,
    ):
        return (
            True,
            f"stable at hosted={hosted} "
            f"(last {plan.stability_window} pre-gate means within {plan.stability_tolerance:.0%})",
        )
    return (
        False,
        f"hosted={hosted} >= min_hosted but the DV is not yet stable "
        f"over the last {plan.stability_window} pre-gate means",
    )


@dataclass(frozen=True)
class PhaseDecision:
    """The controller's decision for the next segment.

    ``action`` is one of:

    * ``hold`` — keep collecting at ``current_criterion``;
    * ``advance`` — move to ``next_criterion`` (the next ladder value);
    * ``baseline_complete`` — a single-criterion (A0) plan met its stop condition; the operator now
      calibrates the C1…Cn ladder from this data;
    * ``complete`` — a multi-step ladder is fully exhausted.

    ``next_criterion`` is the C_k the runner should use next: the current value while holding, the
    next ladder value when advancing, and ``None`` on baseline_complete / complete. It is actionable
    only by setting ``HAPAX_COHERENCE_CRITERION`` and re-invoking prep as a fresh process (see the
    module docstring). ``is_reversal`` is set when an advance LOWERS the criterion (the §5.1 probe).
    """

    action: str
    current_criterion: float
    next_criterion: float | None
    is_reversal: bool
    hosted: int
    stable: bool
    reason: str


def decide(plan: PhasePlan, observations: list[ProducerObservation]) -> PhaseDecision:
    """Decide hold / advance / baseline_complete / complete from the producer DV and the phase plan.

    The active phase is the highest-index plan criterion that has observations (else the first
    criterion, not yet started). Its summary is evaluated against the §5.1 stop rule; on completion
    the controller advances to the next ladder value, or reports baseline_complete (single-phase A0
    plan) / complete (multi-step ladder exhausted) if none remains.
    """
    summaries = {summary.criterion: summary for summary in summarize_phases(observations)}

    active_index = 0
    for index, criterion in enumerate(plan.criteria):
        summary = summaries.get(round(criterion, _CRITERION_KEY_PRECISION))
        if summary is not None and summary.n > 0:
            active_index = index
    current = plan.criteria[active_index]
    summary = summaries.get(round(current, _CRITERION_KEY_PRECISION))

    if summary is None:
        # The active phase has no observations. If observations exist at criteria NOT in the plan
        # (env/plan drift), surface that instead of a bare "no observations yet" silent stall.
        plan_keys = {round(c, _CRITERION_KEY_PRECISION) for c in plan.criteria}
        off_plan = sorted(key for key in summaries if key not in plan_keys)
        if off_plan:
            off_n = sum(summaries[key].n for key in off_plan)
            reason = (
                f"no observations at any planned C_k, but {off_n} observation(s) exist at off-plan "
                f"C_k {off_plan} — check that the plan matches the in-force HAPAX_COHERENCE_CRITERION"
            )
        else:
            reason = f"collecting: no observations yet at C_k={current}"
        return PhaseDecision(
            action="hold",
            current_criterion=current,
            next_criterion=current,
            is_reversal=False,
            hosted=0,
            stable=False,
            reason=reason,
        )

    done, reason = phase_complete(summary, plan)
    stable = is_stable(
        summary.pre_gate_scores,
        window=plan.stability_window,
        tolerance=plan.stability_tolerance,
    )
    if not done:
        return PhaseDecision(
            action="hold",
            current_criterion=current,
            next_criterion=current,
            is_reversal=False,
            hosted=summary.released,
            stable=stable,
            reason=reason,
        )
    if active_index + 1 < len(plan.criteria):
        nxt = plan.criteria[active_index + 1]
        reversal = nxt < current
        return PhaseDecision(
            action="advance",
            current_criterion=current,
            next_criterion=nxt,
            is_reversal=reversal,
            hosted=summary.released,
            stable=stable,
            reason=f"advance: {reason}; next C_k={nxt}" + (" (reversal probe)" if reversal else ""),
        )
    if len(plan.criteria) == 1:
        return PhaseDecision(
            action="baseline_complete",
            current_criterion=current,
            next_criterion=None,
            is_reversal=False,
            hosted=summary.released,
            stable=stable,
            reason=f"A0 baseline phase complete: {reason}; "
            f"operator calibrates the C1…Cn ladder from this data",
        )
    return PhaseDecision(
        action="complete",
        current_criterion=current,
        next_criterion=None,
        is_reversal=False,
        hosted=summary.released,
        stable=stable,
        reason=f"run complete: {reason}; no further C_k in the ladder",
    )
