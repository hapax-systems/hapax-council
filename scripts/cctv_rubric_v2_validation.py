"""CCTV rubric v2 validation — re-run 10 calibration probes.

Runs 10 probes (excerpts at known quality levels) through the deliberative
council with DisconfirmationRubric (v2 with floor_examples). Reports whether
scores align with expected quality bands.

Usage:
    uv run python scripts/cctv_rubric_v2_validation.py [--dry-run]

Cost: ~$3 for full run (6 models × 10 probes × 2 calls each).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from agents.deliberative_council.engine import run_phase1
from agents.deliberative_council.models import CouncilConfig, CouncilInput
from agents.deliberative_council.rubrics import DisconfirmationRubric

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "cctv-rubric-v2"


@dataclass(frozen=True)
class CalibrationProbe:
    id: str
    text: str
    source_ref: str
    expected_band: str  # "floor" (1-2), "weak" (2-3), "strong" (4-5)
    expected_axis_notes: dict[str, str]


PROBES: list[CalibrationProbe] = [
    # --- FLOOR (expected 1-2): evidence is absent or fabricated ---
    CalibrationProbe(
        id="floor_no_evidence",
        text=(
            "The reactive engine handles all edge cases correctly and is production-ready. "
            "It has been extensively tested across all scenarios."
        ),
        source_ref="agents/reactive_engine/__init__.py",
        expected_band="floor",
        expected_axis_notes={
            "evidence_adequacy": "No evidence cited. Pure assertion.",
            "falsifiability": "Unfalsifiable — no test named.",
        },
    ),
    CalibrationProbe(
        id="floor_fabricated_source",
        text=(
            "According to shared/governance/reactive_validator.py (line 42), the system "
            "guarantees zero false positives through its novel validation algorithm."
        ),
        source_ref="shared/governance/reactive_validator.py",
        expected_band="floor",
        expected_axis_notes={
            "evidence_adequacy": "Source file does not exist. Fabricated reference.",
            "scope_honesty": "Claims guarantee without bounding conditions.",
        },
    ),
    CalibrationProbe(
        id="floor_metadata_as_evidence",
        text=(
            "The consent system is fully implemented — the file shared/governance/consent.py "
            "exists (2.4KB, last modified 2026-03-10) and contains a ConsentGatedWriter class."
        ),
        source_ref="shared/governance/consent.py",
        expected_band="floor",
        expected_axis_notes={
            "evidence_adequacy": "File existence ≠ implementation completeness.",
            "counter_evidence_resilience": "Ignores that class might be a stub.",
        },
    ),
    # --- WEAK (expected 2-3): evidence exists but doesn't support the claim well ---
    CalibrationProbe(
        id="weak_tangential_evidence",
        text=(
            "The affordance pipeline achieves sub-100ms latency because it uses "
            "Qdrant for vector similarity. Qdrant's documentation states it can "
            "handle millions of vectors with low latency."
        ),
        source_ref="shared/affordance_pipeline.py",
        expected_band="weak",
        expected_axis_notes={
            "evidence_adequacy": "Qdrant capability ≠ this pipeline's actual latency.",
            "scope_honesty": "Vendor docs ≠ measured system performance.",
        },
    ),
    CalibrationProbe(
        id="weak_overclaimed_scope",
        text=(
            "The voice tier system prevents all audio conflicts through the "
            "EvilPetState mutex. Testing confirms the arbitrate() function "
            "correctly handles priority ordering."
        ),
        source_ref="shared/evil_pet_state.py",
        expected_band="weak",
        expected_axis_notes={
            "scope_honesty": "Unit test of arbitrate() ≠ 'prevents all conflicts'.",
            "counter_evidence_resilience": "Doesn't address real-world race conditions.",
        },
    ),
    CalibrationProbe(
        id="weak_single_source_circular",
        text=(
            "The CPAL evaluator produces well-calibrated confidence scores. "
            "This is evident from cpal/runner.py which uses a BetaDistribution "
            "for Thompson sampling with parameters that converge over time."
        ),
        source_ref="agents/hapax_daimonion/cpal/runner.py",
        expected_band="weak",
        expected_axis_notes={
            "evidence_adequacy": "Implementation exists but no calibration measurement.",
            "falsifiability": "No test or metric that would show miscalibration.",
        },
    ),
    CalibrationProbe(
        id="weak_hedged_but_unsupported",
        text=(
            "The segment prep pipeline likely produces adequate narrative quality "
            "in most cases, though further validation may be needed. The existing "
            "disconfirmation loop provides some quality assurance."
        ),
        source_ref="agents/hapax_daimonion/daily_segment_prep.py",
        expected_band="weak",
        expected_axis_notes={
            "evidence_adequacy": "Hedged language masks absence of measurement.",
            "falsifiability": "'Adequate in most cases' is unfalsifiable.",
        },
    ),
    # --- STRONG (expected 4-5): specific, sourced, bounded, falsifiable ---
    CalibrationProbe(
        id="strong_specific_measurement",
        text=(
            "The EvilPetState heartbeat timeout is 15.0 seconds "
            "(HEARTBEAT_STALE_S in shared/evil_pet_state.py line 129). When a writer "
            "crashes, readers see bypass state after this window. The test "
            "test_stale_heartbeat_releases verifies: setting heartbeat to now-16s "
            "causes read_state() to return EvilPetMode.BYPASS. This does NOT "
            "guarantee sub-second failover — only that a 15s ceiling exists."
        ),
        source_ref="shared/evil_pet_state.py",
        expected_band="strong",
        expected_axis_notes={
            "evidence_adequacy": "Cites exact constant, line, test name, and behavior.",
            "scope_honesty": "Explicitly bounds what is NOT claimed.",
        },
    ),
    CalibrationProbe(
        id="strong_multi_source_bounded",
        text=(
            "The vocal chain maps 9 dimensions to MIDI CCs. Each dimension's "
            "CC range is capped (e.g. intensity: CC39 0-80, not 0-127) to preserve "
            "speech intelligibility per docs/research/2026-04-19-evil-pet-s4-base-config.md §5.1. "
            "Limitation: these ceilings are hardcoded breakpoints, not adaptive — "
            "a speaker with naturally low projection may still be inaudible at "
            "max intensity. No A/B test has validated the ceiling values against "
            "listener comprehension."
        ),
        source_ref="agents/hapax_daimonion/vocal_chain.py",
        expected_band="strong",
        expected_axis_notes={
            "evidence_adequacy": "Implementation + research doc + specific values.",
            "scope_honesty": "Names limitation and missing validation.",
            "falsifiability": "A/B test would validate or falsify ceiling choices.",
        },
    ),
    CalibrationProbe(
        id="strong_counter_evidence_addressed",
        text=(
            "The working mode system uses a single file at ~/.cache/hapax/working-mode "
            "as SSOT (shared/working_mode.py read_working_mode()). Counter-argument: "
            "file-based state is racy under concurrent writers. Mitigated by: "
            "(1) only hapax-working-mode CLI writes this file, (2) writes are "
            "atomic via tmp+rename on tmpfs, (3) readers tolerate stale reads "
            "(propagation is best-effort, 2s polling). Known gap: no flock — "
            "two simultaneous CLI invocations could race, but this is single-user "
            "so the scenario requires operator error."
        ),
        source_ref="shared/working_mode.py",
        expected_band="strong",
        expected_axis_notes={
            "counter_evidence_resilience": "Anticipates and addresses race condition objection.",
            "scope_honesty": "Names remaining gap and why it's acceptable.",
            "falsifiability": "Concurrent CLI test would reveal the race.",
        },
    ),
]


def _band_range(band: str) -> tuple[float, float]:
    return {"floor": (1.0, 2.4), "weak": (2.0, 3.4), "strong": (3.6, 5.0)}[band]


def _score_in_band(score: float, band: str) -> bool:
    lo, hi = _band_range(band)
    return lo <= score <= hi


async def run_validation(dry_run: bool = False) -> dict:
    rubric = DisconfirmationRubric()
    config = CouncilConfig(
        phases=(1,),
        shortcircuit_iqr_threshold=99.0,
    )

    results: list[dict] = []
    start = time.time()

    for probe in PROBES:
        log.info("Running probe: %s (expected: %s)", probe.id, probe.expected_band)

        if dry_run:
            results.append(
                {
                    "probe_id": probe.id,
                    "expected_band": probe.expected_band,
                    "mean_scores": {},
                    "in_band": None,
                    "dry_run": True,
                }
            )
            continue

        inp = CouncilInput(text=probe.text, source_ref=probe.source_ref)
        phase1 = await run_phase1(inp, rubric, config)

        axis_means: dict[str, float] = {}
        for axis in rubric.axes:
            scores = [r.scores.get(axis.name, 0) for r in phase1 if axis.name in r.scores]
            if scores:
                axis_means[axis.name] = sum(scores) / len(scores)

        overall_mean = sum(axis_means.values()) / len(axis_means) if axis_means else 0.0
        in_band = _score_in_band(overall_mean, probe.expected_band)

        per_model = [
            {"model": r.model_alias, "scores": r.scores, "tool_calls": len(r.tool_calls_log)}
            for r in phase1
        ]

        results.append(
            {
                "probe_id": probe.id,
                "expected_band": probe.expected_band,
                "mean_scores": axis_means,
                "overall_mean": round(overall_mean, 2),
                "in_band": in_band,
                "per_model": per_model,
            }
        )

        status = "PASS" if in_band else "MISS"
        log.info("  %s: mean=%.2f band=%s", status, overall_mean, probe.expected_band)

    elapsed = time.time() - start

    in_band_count = sum(1 for r in results if r.get("in_band") is True)
    total_scored = sum(1 for r in results if r.get("in_band") is not None)
    accuracy = in_band_count / total_scored if total_scored else 0.0

    summary = {
        "rubric": rubric.name,
        "rubric_version": rubric.version,
        "probes_run": len(results),
        "in_band": in_band_count,
        "accuracy": round(accuracy, 3),
        "elapsed_s": round(elapsed, 1),
        "results": results,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")
    out_path = RESULTS_DIR / f"validation-{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2))
    log.info(
        "Validation complete: %d/%d in-band (%.0f%%) — %s",
        in_band_count,
        total_scored,
        accuracy * 100,
        out_path,
    )
    return summary


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    summary = asyncio.run(run_validation(dry_run=dry_run))
    if not dry_run:
        accuracy = summary["accuracy"]
        if accuracy < 0.7:
            log.warning("Rubric v2 accuracy below 70%% threshold: %.0f%%", accuracy * 100)
            sys.exit(1)


if __name__ == "__main__":
    main()
