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

It is deliberately lightweight — no pydantic-ai / council imports — so it can run
in plain analysis contexts. The writer-side constants it mirrors are drift-guarded
by ``tests/shared/test_segment_prep_dv_reader.py``.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# Mirrors agents.hapax_daimonion.daily_segment_prep.COUNCIL_DECISIONS_LEDGER_FILENAME and
# DEFAULT_PREP_DIR. Re-declared (not imported) to keep this reader free of the heavy
# daimonion import; a drift guard test asserts they stay equal.
COUNCIL_DECISIONS_LEDGER_FILENAME = "council-decisions.ndjson"
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
class ProducerObservation:
    """One pre-gate producer observation reconstructed from a ledger row."""

    programme_id: str
    ledgered_at: str
    mean_score: float
    criterion: float
    released: bool
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
    return ProducerObservation(
        programme_id=str(row.get("programme_id", "")),
        ledgered_at=str(row.get("ledgered_at", "")),
        mean_score=float(mean_score),
        criterion=float(criterion),
        released=row.get("terminal_status") == _RELEASED_TERMINAL_STATUS,
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
    phases = summarize_phases(observations)
    report: dict = {
        "n_observations": len(observations),
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
        for ph in report["phases"]:
            print(
                f"  C_k={ph['criterion']}: n={ph['n']} "
                f"released={ph['released']} ({ph['released_fraction']:.0%}) "
                f"mean_pre_gate={ph['mean_pre_gate']}"
            )
        if "baseline_corrected_tau" in report:
            print(
                f"  BCTau(baseline={args.baseline}, intervention={args.intervention}): "
                f"{report['baseline_corrected_tau']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
