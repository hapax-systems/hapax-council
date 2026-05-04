#!/usr/bin/env python3
"""End-to-end smoke for outcome 1 (vocal) — emits a segment event with quality.

Operator directive (2026-05-04):

    "this is a segment + it happened/didn't + happened well/not well"

This harness wraps the cadence sampler from
:mod:`scripts/verify-vocal-cadence` in the canonical
:class:`~shared.segment_observability.SegmentRecorder` context manager
shipped in PR #2472. The recorder appends one ``STARTED`` line on
entry and one ``HAPPENED`` / ``DIDNT_HAPPEN`` line on exit to the
segments jsonl (default ``~/hapax-state/segments/segments.jsonl``);
the ``quality.vocal`` field on the terminal event captures the
operator's "happened well" axis.

Quality rating maps from three sampler signals:

* ``emissions_per_min`` — in the SLO band [0.6, 2.5]?
* ``longest_silence_s`` — was there a gap > 90s? > 5min?
* ``pressure_p50`` — is the drive surfacing with conviction?

The mapping is intentionally coarse — the operator's frame is
"happened well or not well", not a numeric score. Edge cases
(silent run, programme-not-active, daimonion-down) are recorded as
``DIDNT_HAPPEN`` with the failing gate captured in ``quality.notes``,
so a ``DIDNT_HAPPEN`` segment is still legible from the jsonl alone.

Usage::

    uv run python scripts/smoke-vocal-segment.py
    uv run python scripts/smoke-vocal-segment.py --window-s 120
    HAPAX_SEGMENTS_LOG=/tmp/segs.jsonl uv run python scripts/smoke-vocal-segment.py
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.segment_observability import (
    QualityRating,
    SegmentRecorder,
)

DEFAULT_WINDOW_S = 600.0
DEFAULT_PROGRAMME_ROLE_FALLBACK = "ambient"

# Quality thresholds — keep in sync with the cc-task spec; tests pin
# the exact mapping so changes are visible and intentional.
SLO_MIN = 0.6
SLO_MAX = 2.5
EDGE_MIN = 0.3
EDGE_MAX = 3.5
SILENCE_GOOD_CEIL_S = 90.0
SILENCE_ACCEPT_CEIL_S = 300.0
PRESSURE_HEALTHY_FLOOR = 0.5
PRESSURE_POOR_CEIL = 0.2

# Path to the cadence sampler — loaded via importlib because the
# filename has a hyphen. Resolves at call time so a different
# repository checkout doesn't break testing.
_VERIFIER_NAME = "verify-vocal-cadence.py"


@dataclass(frozen=True)
class QualityAssessment:
    """Quality + human-readable note paired so the segment event can
    persist both without re-deriving the note from the report."""

    rating: QualityRating
    note: str


def _load_verifier() -> Any:
    """Load ``scripts/verify-vocal-cadence.py`` as a module."""
    repo_root = Path(__file__).resolve().parents[1]
    candidate = repo_root / "scripts" / _VERIFIER_NAME
    if not candidate.exists():
        raise RuntimeError(f"cadence sampler not found at {candidate}")
    spec = importlib.util.spec_from_file_location("verify_vocal_cadence_smoke", candidate)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {candidate}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_vocal_cadence_smoke"] = module
    spec.loader.exec_module(module)
    return module


def assess_vocal_quality(report: Any) -> QualityAssessment:
    """Map a :class:`CadenceReport` to a :class:`QualityRating`.

    Pure function — no I/O, no side effects. Pinned by parametrized
    unit tests so the boundaries between ratings are explicit and
    auditable.
    """
    epm = float(report.emissions_per_min)
    silence = float(report.longest_silence_s)
    p50 = report.pressure_p50

    # POOR: silent run, prolonged silence, or weak pressure floor.
    if not report.emissions:
        return QualityAssessment(
            rating=QualityRating.POOR,
            note="0 emissions in window — silent failure somewhere in the chain",
        )
    if silence > SILENCE_ACCEPT_CEIL_S:
        return QualityAssessment(
            rating=QualityRating.POOR,
            note=f"longest silence {silence:.0f}s > {SILENCE_ACCEPT_CEIL_S:.0f}s",
        )
    if p50 is not None and p50 < PRESSURE_POOR_CEIL:
        return QualityAssessment(
            rating=QualityRating.POOR,
            note=f"pressure p50 {p50:.3f} < {PRESSURE_POOR_CEIL} — drive lacking conviction",
        )

    # ACCEPTABLE: edges of SLO band or middling silence.
    if not (SLO_MIN <= epm <= SLO_MAX):
        if EDGE_MIN <= epm <= EDGE_MAX:
            return QualityAssessment(
                rating=QualityRating.ACCEPTABLE,
                note=(
                    f"emissions/min {epm:.2f} outside [{SLO_MIN}, {SLO_MAX}] "
                    f"but within [{EDGE_MIN}, {EDGE_MAX}]"
                ),
            )
        return QualityAssessment(
            rating=QualityRating.POOR,
            note=f"emissions/min {epm:.2f} far outside SLO band",
        )
    if silence > SILENCE_GOOD_CEIL_S:
        return QualityAssessment(
            rating=QualityRating.ACCEPTABLE,
            note=(
                f"emissions/min {epm:.2f} in band but longest silence {silence:.0f}s "
                f"> {SILENCE_GOOD_CEIL_S:.0f}s"
            ),
        )

    # EXCELLENT: in band, short silences, healthy pressure.
    if p50 is not None and p50 >= PRESSURE_HEALTHY_FLOOR:
        return QualityAssessment(
            rating=QualityRating.EXCELLENT,
            note=(
                f"emissions/min {epm:.2f} in band, longest silence "
                f"{silence:.0f}s, pressure p50 {p50:.3f} healthy"
            ),
        )

    # GOOD: in band, short silences, but pressure data missing or middling.
    return QualityAssessment(
        rating=QualityRating.GOOD,
        note=f"emissions/min {epm:.2f} in band, longest silence {silence:.0f}s",
    )


def _gate_failure_note(report: Any) -> str | None:
    """Return a one-line gate-failure summary, or ``None`` if all gates passed.

    Walks the report's pre-check gates and returns the first failure's
    detail string. Smoke runs that hit a gate failure record
    DIDNT_HAPPEN with this note so the operator sees which upstream
    component blocked the run from the jsonl alone.
    """
    for gate in getattr(report, "gates", ()) or ():
        if not gate.ok:
            return f"{gate.name}: {gate.detail}"
    return None


def _resolve_programme_role(report: Any) -> str:
    """Best-effort programme role for the segment record.

    The cadence sampler's ``programme_active`` gate reports the active
    programme's role in its detail string when the gate passed; we
    parse it back to populate the segment event. Falls through to
    ``ambient`` when the gate failed or the role isn't visible.
    """
    for gate in getattr(report, "gates", ()) or ():
        if gate.name == "programme_active" and gate.ok:
            for token in gate.detail.split():
                if token.startswith("role="):
                    return token.split("=", 1)[1]
    return DEFAULT_PROGRAMME_ROLE_FALLBACK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vocal segment smoke test")
    parser.add_argument("--window-s", type=float, default=DEFAULT_WINDOW_S)
    parser.add_argument("--topic-seed", type=str, default=None)
    parser.add_argument(
        "--skip-pre-checks",
        action="store_true",
        help="skip cadence-sampler gates (useful for offline replay)",
    )
    args = parser.parse_args(argv)

    verifier = _load_verifier()
    report = verifier.build_report(
        window_s=args.window_s,
        impingements_path=verifier.DEFAULT_IMPINGEMENTS_PATH,
        audio_safe_path=verifier.DEFAULT_AUDIO_SAFE_PATH,
        skip_pre_checks=args.skip_pre_checks,
    )

    role = _resolve_programme_role(report)
    gate_failure = _gate_failure_note(report)

    with SegmentRecorder(programme_role=role, topic_seed=args.topic_seed) as event:
        if gate_failure is not None:
            # Force DIDNT_HAPPEN by raising — the recorder catches and
            # re-raises, so we use a dedicated sentinel exception caught
            # below for clean exit codes.
            event.quality.vocal = QualityRating.POOR
            event.quality.notes = f"gate failure: {gate_failure}"
            raise _GateFailure(gate_failure)
        assessment = assess_vocal_quality(report)
        event.quality.vocal = assessment.rating
        event.quality.notes = assessment.note

    # Echo the assessment to stdout for the operator + JSON line for trending.
    print(f"vocal_quality={assessment.rating.value} note={assessment.note!r}")
    return 0


class _GateFailure(RuntimeError):
    """Sentinel raised inside SegmentRecorder so the recorder logs
    DIDNT_HAPPEN; ``main`` catches it for a clean exit code."""


def _cli_entrypoint(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except _GateFailure as exc:
        # Recorder already wrote DIDNT_HAPPEN with the failure note.
        print(f"DIDNT_HAPPEN: {exc}", file=sys.stderr)
        return 13


if __name__ == "__main__":
    sys.exit(_cli_entrypoint())
