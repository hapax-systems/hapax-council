"""CCTV tool-level ablation — compare FULL vs RESTRICTED vs NONE.

Runs the same probes under three tool conditions to measure the evidence
delta that tools provide. Key finding from initial benchmark: tools produce
a 3-point evidence delta on private claims.

Usage:
    uv run python scripts/cctv_tool_ablation.py [--dry-run] [--probes N]

Output: benchmarks/cctv-rubric-v2/ablation-<timestamp>.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from agents.deliberative_council.engine import run_phase1
from agents.deliberative_council.members import ToolLevel
from agents.deliberative_council.models import CouncilConfig, CouncilInput
from agents.deliberative_council.rubrics import DisconfirmationRubric

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "cctv-rubric-v2"

ABLATION_PROBES = [
    {
        "id": "private_claim_fabricated_path",
        "text": (
            "The governance system validates all agent outputs through "
            "shared/governance/output_validator.py which enforces axiom "
            "compliance before any external emission."
        ),
        "source_ref": "shared/governance/output_validator.py",
        "notes": "File does not exist. Tools should discover this.",
    },
    {
        "id": "private_claim_real_file",
        "text": (
            "The evil pet state module at shared/evil_pet_state.py implements "
            "a 15-second heartbeat timeout for crash recovery, using atomic "
            "tmp+rename writes on tmpfs."
        ),
        "source_ref": "shared/evil_pet_state.py",
        "notes": "File exists, claims are verifiable. Tools should confirm.",
    },
    {
        "id": "private_claim_partial_truth",
        "text": (
            "The affordance pipeline indexes all capabilities in Qdrant and "
            "uses Thompson sampling with Beta(2,1) priors clamped to [1,10] "
            "for selection. The pipeline achieves 100% recall on indexed "
            "affordances."
        ),
        "source_ref": "shared/affordance_pipeline.py",
        "notes": "Implementation details verifiable; 100% recall claim is not.",
    },
    {
        "id": "external_claim_unverifiable",
        "text": (
            "According to the Loewenstein (1994) information gap theory, "
            "curiosity arises from a perceived gap between what one knows "
            "and what one wants to know. This system exploits that mechanism."
        ),
        "source_ref": "docs/research/narrative-theory.md",
        "notes": "External citation. Tools may not help without web access.",
    },
    {
        "id": "mixed_verifiable_unverifiable",
        "text": (
            "The vocal chain maps 9 semantic dimensions to MIDI CCs "
            "(agents/hapax_daimonion/vocal_chain.py). Each dimension's CC "
            "range was validated through A/B listening tests with 12 "
            "participants showing 94% intelligibility at max activation."
        ),
        "source_ref": "agents/hapax_daimonion/vocal_chain.py",
        "notes": "First sentence verifiable (code exists). A/B test claim is fabricated.",
    },
]

CONDITIONS: list[ToolLevel] = [ToolLevel.FULL, ToolLevel.RESTRICTED, ToolLevel.NONE]


async def run_ablation(dry_run: bool = False, max_probes: int | None = None) -> dict:
    rubric = DisconfirmationRubric()
    probes = ABLATION_PROBES[:max_probes] if max_probes else ABLATION_PROBES

    results: list[dict] = []
    start = time.time()

    for probe in probes:
        probe_result: dict = {"probe_id": probe["id"], "conditions": {}}

        for condition in CONDITIONS:
            log.info("Probe %s | condition=%s", probe["id"], condition.value)

            if dry_run:
                probe_result["conditions"][condition.value] = {"dry_run": True}
                continue

            config = CouncilConfig(
                phases=(1,),
                model_aliases=("opus", "balanced", "gemini-3-pro"),
                shortcircuit_iqr_threshold=99.0,
            )
            inp = CouncilInput(text=probe["text"], source_ref=probe["source_ref"])

            from unittest.mock import patch

            from agents.deliberative_council.members import build_member

            def _build_with_level(alias: str, tool_level: ToolLevel | None = None) -> object:
                return build_member(alias, tool_level=condition)

            with patch("agents.deliberative_council.engine.build_member", _build_with_level):
                phase1 = await run_phase1(inp, rubric, config)

            axis_means: dict[str, float] = {}
            for axis in rubric.axes:
                scores = [r.scores.get(axis.name, 0) for r in phase1 if axis.name in r.scores]
                if scores:
                    axis_means[axis.name] = round(sum(scores) / len(scores), 2)

            tool_calls_total = sum(len(r.tool_calls_log) for r in phase1)

            probe_result["conditions"][condition.value] = {
                "mean_scores": axis_means,
                "overall_mean": round(
                    sum(axis_means.values()) / len(axis_means) if axis_means else 0.0, 2
                ),
                "tool_calls_total": tool_calls_total,
                "models_responded": len(phase1),
            }

        results.append(probe_result)

    elapsed = time.time() - start

    deltas: list[dict] = []
    for r in results:
        conds = r.get("conditions", {})
        full = conds.get("full", {}).get("overall_mean", 0)
        none = conds.get("none", {}).get("overall_mean", 0)
        if full and none:
            deltas.append({"probe_id": r["probe_id"], "full_minus_none": round(full - none, 2)})

    summary = {
        "rubric": rubric.name,
        "rubric_version": rubric.version,
        "conditions": [c.value for c in CONDITIONS],
        "probes_run": len(results),
        "elapsed_s": round(elapsed, 1),
        "deltas": deltas,
        "mean_delta": (
            round(sum(d["full_minus_none"] for d in deltas) / len(deltas), 2) if deltas else None
        ),
        "results": results,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")
    out_path = RESULTS_DIR / f"ablation-{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2))
    log.info(
        "Ablation complete: %d probes × %d conditions — %s",
        len(results),
        len(CONDITIONS),
        out_path,
    )
    if summary["mean_delta"] is not None:
        log.info("Mean FULL-NONE delta: %.2f points", summary["mean_delta"])
    return summary


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    max_probes = None
    for arg in sys.argv[1:]:
        if arg.startswith("--probes"):
            idx = sys.argv.index(arg)
            if idx + 1 < len(sys.argv):
                max_probes = int(sys.argv[idx + 1])

    asyncio.run(run_ablation(dry_run=dry_run, max_probes=max_probes))


if __name__ == "__main__":
    main()
