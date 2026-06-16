"""A0 baseline collection runner for the seg-prep changing-criterion SCED (#29 driver).

A thin orchestration driver for the A0 floor-only block: hold C_k at the floor, run prep passes,
and stop at the §5.1 condition the G3 phase controller (:mod:`shared.segment_prep_phase_controller`)
computes from the captured producer DV (:mod:`shared.segment_prep_dv_reader`).

The "run one prep pass" step is an INJECTED callable so the loop is unit-testable without a live
resident-model run. The default impl (:func:`run_prep_subprocess`) sets ``HAPAX_COHERENCE_CRITERION``
and invokes ``python -m agents.hapax_daimonion.daily_segment_prep`` as a FRESH process — prep resolves
C_k once at module import, so an in-process loop would gate every pass at the stale import-time C_k
(the controller's documented consumer contract). The actual A0 emit is the gated / operator-coupled
heavyweight pass; this module is the apparatus that drives it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shared.segment_prep_dv_reader import (
    PhaseSummary,
    ProducerObservation,
    default_prep_base,
    read_producer_observations,
    summarize_phases,
)
from shared.segment_prep_phase_controller import (
    _CRITERION_KEY_PRECISION,
    PhaseDecision,
    PhasePlan,
    decide,
)

# A "run one prep pass" callable: given the in-force C_k and the prep base dir, run one prep
# collection pass (producing zero or more new ledger rows). Injected for testability.
RunPass = Callable[[float, Path], None]

# The controller action that ENDS an A0 collection: the floor phase met its §5.1 stop rule. The A0
# runner is single-criterion (floor-only) by construction, so baseline_complete is the only terminal
# the controller can emit here; advancing a ladder is a separate driver's job.
_TERMINAL_ACTIONS = frozenset({"baseline_complete"})


@dataclass(frozen=True)
class A0Result:
    """Outcome of an A0 collection run."""

    passes_run: int
    stop_reason: str  # "controller" | "max_passes"
    final_decision: PhaseDecision
    phase_summary: PhaseSummary | None


def _active_summary(
    observations: list[ProducerObservation], criterion: float
) -> PhaseSummary | None:
    key = round(criterion, _CRITERION_KEY_PRECISION)
    for summary in summarize_phases(observations):
        if summary.criterion == key:
            return summary
    return None


def run_a0_collection(
    *,
    plan: PhasePlan,
    prep_base: Path,
    run_pass: RunPass,
    max_passes: int = 30,
) -> A0Result:
    """Drive the A0 floor-only collection to the §5.1 stop.

    Loops ``run_pass(floor, prep_base)`` → read the producer observations → ``decide(plan, obs)``
    until the controller returns a terminal action (``baseline_complete`` / ``advance`` /
    ``complete``) or ``max_passes`` is reached. The floor C_k is ``plan.criteria[0]``.
    """
    if max_passes < 1:
        raise ValueError("max_passes must be >= 1")
    if len(plan.criteria) != 1:
        raise ValueError(
            "run_a0_collection drives the A0 floor-only baseline (a single-criterion plan); "
            "a multi-step C1…Cn ladder is a separate driver"
        )
    floor = plan.criteria[0]
    decision: PhaseDecision | None = None
    observations: list[ProducerObservation] = []
    passes = 0
    while passes < max_passes:
        run_pass(floor, prep_base)
        passes += 1
        observations = read_producer_observations(prep_base)
        decision = decide(plan, observations)
        if decision.action in _TERMINAL_ACTIONS:
            return A0Result(
                passes_run=passes,
                stop_reason="controller",
                final_decision=decision,
                phase_summary=_active_summary(observations, floor),
            )
        if observations and _active_summary(observations, floor) is None:
            # Rows exist but NONE at the plan floor: prep is stamping an off-plan C_k (env/plan
            # drift). Stop loud rather than burning every remaining (heavyweight) pass to the cap.
            return A0Result(
                passes_run=passes,
                stop_reason="off_plan_drift",
                final_decision=decision,
                phase_summary=None,
            )
    assert decision is not None  # max_passes >= 1 guarantees at least one iteration
    return A0Result(
        passes_run=passes,
        stop_reason="max_passes",
        final_decision=decision,
        phase_summary=_active_summary(observations, floor),
    )


def run_prep_subprocess(criterion: float, prep_base: Path) -> None:
    """Default ``run_pass``: set ``HAPAX_COHERENCE_CRITERION`` and invoke the prep CLI as a fresh
    process. The criterion is passed via ``repr(float(...))`` so it round-trips exactly to the float
    the plan holds (the active-phase lookup matches the ledger criterion at 6-dp; a lossy format
    could drift the phase out of view). Never imports ``run_prep`` in-process (C_k is import-frozen).
    """
    env = os.environ.copy()
    env["HAPAX_COHERENCE_CRITERION"] = repr(float(criterion))
    env["HAPAX_SEGMENT_PREP_DIR"] = str(prep_base)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "agents.hapax_daimonion.daily_segment_prep",
            "--prep-dir",
            str(prep_base),
        ],
        env=env,
        check=True,
    )


def _main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the (gated / operator-coupled) A0 emit.

    ``python -m shared.segment_prep_a0_runner --floor <C_k>`` drives a floor-only baseline
    collection to the §5.1 stop using the real prep subprocess as the run_pass.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Drive the seg-prep A0 floor-only baseline collection to the §5.1 stop."
    )
    parser.add_argument(
        "--floor",
        type=float,
        required=True,
        help="the A0 floor C_k held constant for the baseline (on the (1.0, 5.0] rubric)",
    )
    parser.add_argument(
        "--prep-base",
        type=Path,
        default=None,
        help="seg-prep base dir (default: $HAPAX_SEGMENT_PREP_DIR or ~/.cache/hapax/segment-prep)",
    )
    parser.add_argument("--max-passes", type=int, default=30)
    parser.add_argument("--min-hosted", type=int, default=8)
    parser.add_argument("--max-segments", type=int, default=15)
    args = parser.parse_args(argv)

    prep_base = args.prep_base if args.prep_base is not None else default_prep_base()
    plan = PhasePlan(
        criteria=(args.floor,),
        min_hosted=args.min_hosted,
        max_segments=args.max_segments,
    )
    result = run_a0_collection(
        plan=plan,
        prep_base=prep_base,
        run_pass=run_prep_subprocess,
        max_passes=args.max_passes,
    )
    print(f"A0 collection: passes={result.passes_run} stop_reason={result.stop_reason}")
    print(f"  decision: {result.final_decision.action} — {result.final_decision.reason}")
    if result.phase_summary is not None:
        ph = result.phase_summary
        print(
            f"  phase C_k={ph.criterion}: hosted={ph.released}/{ph.n} "
            f"released_fraction={ph.released_fraction:.0%} mean_pre_gate={ph.mean_pre_gate}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
