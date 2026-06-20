"""Read side of the seg-prep producer dependent variable (the SCED crux DV).

The G1 + G4 work made the producer's PRE-gate signal capturable: every council
decision is appended to ``council-decisions.ndjson`` (one file per date dir under
the seg-prep base) carrying, in ``council_decisions.coherence``:

* ``mean_score`` — the producer's pre-gate coherence panel mean, and
* ``criterion`` — the C_k that was in force when the segment was judged (the
  changing-criterion SCED *phase label*),

plus a row-level ``terminal_status`` from which ``released`` is reconstructed.

This module is the READ side. Until it existed there was a captured DV but NO
reader and NO A0 baseline runner — the rows were unqueryable, which (not the
SDLC coordination-commons "tier-0" ledger, which has zero coupling to seg-prep)
is the actual blocker to running the changing-criterion experiment. It globs the
ledger files, parses each row, and emits the per-phase producer pre-gate score
distribution so the changing-criterion analysis (``stats.baseline_corrected_tau``)
can compare phases — and so curriculum (the producer distribution rises with C_k)
is distinguishable from sieve (flat distribution, the gate just rejects more).
S2 topic/type composability attempts are exposed separately: they are part of
the producer-vs-filter crux population, but rejects occur before coherence and
therefore must not be fabricated into numeric ``mean_score`` rows.

It is deliberately lightweight — no pydantic-ai / council imports — so it can run
in plain analysis contexts. The writer-side constants it mirrors are drift-guarded
by ``tests/shared/test_segment_prep_dv_reader.py``.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Mirrors agents.hapax_daimonion.daily_segment_prep.COUNCIL_DECISIONS_LEDGER_FILENAME and
# DEFAULT_PREP_DIR. Re-declared (not imported) to keep this reader free of the heavy
# daimonion import; a drift guard test asserts they stay equal.
COUNCIL_DECISIONS_LEDGER_FILENAME = "council-decisions.ndjson"
S2_COMPOSABILITY_LEDGER_RECORD_TYPE = "producer_s2_composability_ledger_entry"
S2_COMPOSABILITY_GATE_NAME = "s2_composability"
DUAL_READOUT_SCHEMA_VERSION = 1
DUAL_READOUT_RECORD_TYPE = "segment_dual_readout"
AXIS_A_READOUT_KEY = "axis_a_grounding_efficacy"
AXIS_B_READOUT_KEY = "axis_b_integration_honesty"
_RELEASED_TERMINAL_STATUS = "released"
# C_k is a float read from an env var; round the grouping key so float-repr noise
# (3.0000000001) can never split one phase into two.
_CRITERION_KEY_PRECISION = 6


def default_prep_base() -> Path:
    """The seg-prep base dir, resolved exactly as the writer resolves it."""
    return Path(
        os.environ.get(
            "HAPAX_SEGMENT_PREP_DIR",
            os.path.expanduser("~/.cache/hapax/segment-prep"),
        )
    )


@dataclass(frozen=True)
class AxisReadout:
    """One optional dual-readout axis report carried by a producer observation."""

    axis_id: str
    score_0_100: float | None
    score_1_5: float | None
    ok: bool | None
    coverage_ok: bool | None
    report: dict[str, Any]


@dataclass(frozen=True)
class ProducerObservation:
    """One pre-gate producer observation reconstructed from a ledger row."""

    programme_id: str
    ledgered_at: str
    mean_score: float
    criterion: float
    released: bool
    source: str
    axis_a: AxisReadout | None = None
    axis_b: AxisReadout | None = None


@dataclass(frozen=True)
class S2ComposabilityAttempt:
    """One S2 topic/type composability attempt from the producer DV ledger."""

    programme_id: str
    ledgered_at: str
    criterion: float
    accepted: bool
    terminal: bool
    terminal_status: str
    terminal_reason: str | None
    role: str
    topic: str
    reason: str
    source: str


@dataclass(frozen=True)
class PhaseSummary:
    """Per-phase (per-C_k) view of the producer DV.

    ``pre_gate_scores`` is ordered by ``ledgered_at`` so it can feed
    ``stats.baseline_corrected_tau`` directly (BCTau detrends by index, which
    assumes chronological order). ``released_fraction`` is the sieve readout;
    ``mean_pre_gate`` is the curriculum readout.
    """

    criterion: float
    pre_gate_scores: list[float]
    n: int
    released: int
    released_fraction: float
    mean_pre_gate: float | None


@dataclass(frozen=True)
class S2ComposabilitySummary:
    """Per-phase view of S2 producer-gate attempts and rejects."""

    criterion: float
    attempts: int
    accepted: int
    rejected: int
    rejected_fraction: float


def iter_ledger_files(prep_base: Path | None = None) -> Iterator[Path]:
    """Yield every ``council-decisions.ndjson`` under the date-partitioned base."""
    base = prep_base if prep_base is not None else default_prep_base()
    if not base.is_dir():
        return
    yield from sorted(base.glob(f"*/{COUNCIL_DECISIONS_LEDGER_FILENAME}"))


def _iter_rows_in_file(path: Path) -> Iterator[dict]:
    """Parsed JSON rows in one ledger file; malformed lines / unreadable files are
    skipped (best-effort, mirroring the fail-silent writer)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except (ValueError, TypeError):
            continue
        if isinstance(row, dict):
            yield row


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _axis_readout_from_report(report: Any, *, axis_id: str) -> AxisReadout | None:
    if not isinstance(report, Mapping):
        return None
    coverage = report.get("coverage")
    coverage_ok = _bool_or_none(coverage.get("ok")) if isinstance(coverage, Mapping) else None
    return AxisReadout(
        axis_id=axis_id,
        score_0_100=_number_or_none(report.get("score_0_100")),
        score_1_5=_number_or_none(report.get("score_1_5")),
        ok=_bool_or_none(report.get("ok")),
        coverage_ok=coverage_ok,
        report=dict(report),
    )


def _dual_readout_from_row(row: dict) -> tuple[AxisReadout | None, AxisReadout | None]:
    dual_readout = row.get("dual_readout")
    if not isinstance(dual_readout, Mapping):
        return None, None
    if dual_readout.get("schema_version") != DUAL_READOUT_SCHEMA_VERSION:
        return None, None
    if dual_readout.get("record_type") != DUAL_READOUT_RECORD_TYPE:
        return None, None
    return (
        _axis_readout_from_report(dual_readout.get(AXIS_A_READOUT_KEY), axis_id="A"),
        _axis_readout_from_report(dual_readout.get(AXIS_B_READOUT_KEY), axis_id="B"),
    )


def _observation_from_row(row: dict, *, source: str) -> ProducerObservation | None:
    """Extract a producer observation, or None if the row carries no pre-gate score.

    The pre-gate producer signal is the INITIAL coherence check
    (``council_decisions.coherence``), not the post-refine ``coherence_recheck``.
    Rows without a numeric ``mean_score`` (council unavailable / no valid scores)
    have no producer score to contribute and are dropped from the distribution.
    """
    decisions = row.get("council_decisions")
    if not isinstance(decisions, dict):
        return None
    coherence = decisions.get("coherence")
    if not isinstance(coherence, dict):
        return None
    mean_score = coherence.get("mean_score")
    criterion = coherence.get("criterion")
    if not isinstance(mean_score, (int, float)) or isinstance(mean_score, bool):
        return None
    if not isinstance(criterion, (int, float)) or isinstance(criterion, bool):
        return None
    axis_a, axis_b = _dual_readout_from_row(row)
    return ProducerObservation(
        programme_id=str(row.get("programme_id", "")),
        ledgered_at=str(row.get("ledgered_at", "")),
        mean_score=float(mean_score),
        criterion=float(criterion),
        released=row.get("terminal_status") == _RELEASED_TERMINAL_STATUS,
        source=source,
        axis_a=axis_a,
        axis_b=axis_b,
    )


def _s2_attempt_from_row(row: dict, *, source: str) -> S2ComposabilityAttempt | None:
    """Extract an S2 composability attempt, or None for non-S2 rows."""
    if row.get("record_type") != S2_COMPOSABILITY_LEDGER_RECORD_TYPE:
        return None
    producer_gate = row.get("producer_gate")
    if not isinstance(producer_gate, dict):
        return None
    if producer_gate.get("gate") != S2_COMPOSABILITY_GATE_NAME:
        return None
    accepted = producer_gate.get("accepted")
    criterion = producer_gate.get("criterion")
    if not isinstance(accepted, bool):
        return None
    if not isinstance(criterion, (int, float)) or isinstance(criterion, bool):
        return None
    terminal_reason_raw = row.get("terminal_reason")
    return S2ComposabilityAttempt(
        programme_id=str(row.get("programme_id", "")),
        ledgered_at=str(row.get("ledgered_at", "")),
        criterion=float(criterion),
        accepted=accepted,
        terminal=bool(row.get("terminal")),
        terminal_status=str(row.get("terminal_status", "")),
        terminal_reason=str(terminal_reason_raw) if terminal_reason_raw is not None else None,
        role=str(producer_gate.get("role", "")),
        topic=str(producer_gate.get("topic", "")),
        reason=str(producer_gate.get("reason", "")),
        source=source,
    )


def read_producer_observations(prep_base: Path | None = None) -> list[ProducerObservation]:
    """All pre-gate producer observations, in ledger (chronological) read order."""
    out: list[ProducerObservation] = []
    for path in iter_ledger_files(prep_base):
        for row in _iter_rows_in_file(path):
            obs = _observation_from_row(row, source=str(path))
            if obs is not None:
                out.append(obs)
    return out


def read_s2_composability_attempts(
    prep_base: Path | None = None,
) -> list[S2ComposabilityAttempt]:
    """All S2 topic/type composability attempts, in ledger read order."""
    out: list[S2ComposabilityAttempt] = []
    for path in iter_ledger_files(prep_base):
        for row in _iter_rows_in_file(path):
            attempt = _s2_attempt_from_row(row, source=str(path))
            if attempt is not None:
                out.append(attempt)
    return out


def _criterion_key(criterion: float) -> float:
    return round(criterion, _CRITERION_KEY_PRECISION)


def summarize_phases(observations: list[ProducerObservation]) -> list[PhaseSummary]:
    """Group observations by C_k (phase) → ordered per-phase producer DV summary.

    Phases are returned in ascending C_k order (the ratchet direction). Within a
    phase, scores are ordered by ``ledgered_at`` so BCTau's index-detrend sees
    chronological order.
    """
    by_phase: dict[float, list[ProducerObservation]] = defaultdict(list)
    for obs in observations:
        by_phase[_criterion_key(obs.criterion)].append(obs)

    summaries: list[PhaseSummary] = []
    for criterion in sorted(by_phase):
        rows = sorted(by_phase[criterion], key=lambda o: o.ledgered_at)
        scores = [o.mean_score for o in rows]
        released = sum(1 for o in rows if o.released)
        n = len(rows)
        summaries.append(
            PhaseSummary(
                criterion=criterion,
                pre_gate_scores=scores,
                n=n,
                released=released,
                released_fraction=(released / n) if n else 0.0,
                mean_pre_gate=(sum(scores) / n) if n else None,
            )
        )
    return summaries


def summarize_s2_composability(
    attempts: list[S2ComposabilityAttempt],
) -> list[S2ComposabilitySummary]:
    """Group S2 composability attempts by C_k (phase)."""
    by_phase: dict[float, list[S2ComposabilityAttempt]] = defaultdict(list)
    for attempt in attempts:
        by_phase[_criterion_key(attempt.criterion)].append(attempt)

    summaries: list[S2ComposabilitySummary] = []
    for criterion in sorted(by_phase):
        rows = by_phase[criterion]
        attempts_n = len(rows)
        accepted = sum(1 for row in rows if row.accepted)
        rejected = attempts_n - accepted
        summaries.append(
            S2ComposabilitySummary(
                criterion=criterion,
                attempts=attempts_n,
                accepted=accepted,
                rejected=rejected,
                rejected_fraction=(rejected / attempts_n) if attempts_n else 0.0,
            )
        )
    return summaries


def baseline_intervention_scores(
    observations: list[ProducerObservation],
    *,
    baseline_criterion: float,
    intervention_criterion: float,
) -> tuple[list[float], list[float]]:
    """The two ordered score lists for ``stats.baseline_corrected_tau``.

    ``baseline`` = pre-gate scores at ``baseline_criterion``; ``intervention`` =
    pre-gate scores at ``intervention_criterion``. Each is ordered by
    ``ledgered_at``. Empty list(s) if a phase has no observations.
    """
    summaries = {s.criterion: s for s in summarize_phases(observations)}
    baseline = summaries.get(_criterion_key(baseline_criterion))
    intervention = summaries.get(_criterion_key(intervention_criterion))
    return (
        baseline.pre_gate_scores if baseline else [],
        intervention.pre_gate_scores if intervention else [],
    )


def _main(argv: list[str] | None = None) -> int:
    """A0 inspection runner: print the per-phase producer DV, and — given a
    baseline and an intervention C_k — the changing-criterion BCTau between them.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Inspect the seg-prep producer dependent variable (changing-criterion SCED)."
    )
    parser.add_argument(
        "--prep-base",
        type=Path,
        default=None,
        help="seg-prep base dir (default: $HAPAX_SEGMENT_PREP_DIR or ~/.cache/hapax/segment-prep)",
    )
    parser.add_argument(
        "--baseline", type=float, default=None, help="baseline phase C_k for a BCTau comparison"
    )
    parser.add_argument(
        "--intervention",
        type=float,
        default=None,
        help="intervention phase C_k for a BCTau comparison",
    )
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    observations = read_producer_observations(args.prep_base)
    s2_attempts = read_s2_composability_attempts(args.prep_base)
    phases = summarize_phases(observations)
    s2_phases = summarize_s2_composability(s2_attempts)
    report: dict = {
        "n_observations": len(observations),
        "n_axis_a_observations": sum(1 for obs in observations if obs.axis_a is not None),
        "n_axis_b_observations": sum(1 for obs in observations if obs.axis_b is not None),
        "n_dual_readout_complete_observations": sum(
            1 for obs in observations if obs.axis_a is not None and obs.axis_b is not None
        ),
        "n_s2_composability_attempts": len(s2_attempts),
        "phases": [
            {
                "criterion": ph.criterion,
                "n": ph.n,
                "released": ph.released,
                "released_fraction": round(ph.released_fraction, 4),
                "mean_pre_gate": (
                    round(ph.mean_pre_gate, 4) if ph.mean_pre_gate is not None else None
                ),
            }
            for ph in phases
        ],
        "s2_composability": [
            {
                "criterion": ph.criterion,
                "attempts": ph.attempts,
                "accepted": ph.accepted,
                "rejected": ph.rejected,
                "rejected_fraction": round(ph.rejected_fraction, 4),
            }
            for ph in s2_phases
        ],
    }
    if args.baseline is not None and args.intervention is not None:
        from agents.hapax_daimonion import stats

        baseline_scores, intervention_scores = baseline_intervention_scores(
            observations,
            baseline_criterion=args.baseline,
            intervention_criterion=args.intervention,
        )
        report["baseline_corrected_tau"] = stats.baseline_corrected_tau(
            baseline_scores, intervention_scores
        )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"producer-DV observations: {report['n_observations']}")
        print(f"S2 composability attempts: {report['n_s2_composability_attempts']}")
        for ph in report["phases"]:
            print(
                f"  C_k={ph['criterion']}: n={ph['n']} "
                f"released={ph['released']} ({ph['released_fraction']:.0%}) "
                f"mean_pre_gate={ph['mean_pre_gate']}"
            )
        for ph in report["s2_composability"]:
            print(
                f"  S2 C_k={ph['criterion']}: attempts={ph['attempts']} "
                f"accepted={ph['accepted']} rejected={ph['rejected']} "
                f"({ph['rejected_fraction']:.0%})"
            )
        if "baseline_corrected_tau" in report:
            print(
                f"  BCTau(baseline={args.baseline}, intervention={args.intervention}): "
                f"{report['baseline_corrected_tau']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
