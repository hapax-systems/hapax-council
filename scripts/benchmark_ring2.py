#!/usr/bin/env python
"""Ring 2 classifier benchmark harness — precision/recall per risk class.

Consumes the JSONL produced by ``scripts.generate_ring2_benchmark`` and
runs each sample through the Phase 1 classifier, computing per-risk-class
precision / recall / F1 and an overall confusion matrix.

Pass criteria (from DEMONET-PLAN §3 + CAPSTONE §3 Benchmark path §3):

- ``high`` precision ≥ 0.95 (false positives acceptable; false negatives
  would admit Content-ID fingerprints)
- ``high`` recall ≥ 0.90
- overall accuracy ≥ 0.85

Run:

    # Against a local TabbyAPI (requires LITELLM_API_KEY + tabbyapi running):
    cd ~/projects/hapax-council
    uv run python -m scripts.benchmark_ring2

    # Dry-run with a mock classifier that echoes catalog risk (smoke test
    # of the harness itself — does NOT validate the LLM):
    uv run python -m scripts.benchmark_ring2 --mock

Exits with code 0 when all pass thresholds meet, 1 otherwise. Designed
to plug into CI as a nightly regression pin if TabbyAPI is reachable.

Reference:
    - docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md §3
    - scripts/generate_ring2_benchmark.py — dataset producer
    - shared/governance/ring2_classifier.py — the subject under test
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.governance.classifier_degradation import ClassifierUnavailable  # noqa: E402
from shared.governance.monetization_safety import (  # noqa: E402
    RiskAssessment,
    SurfaceKind,
)

DEFAULT_BENCHMARK_PATH: Final[Path] = ROOT / "benchmarks" / "ring2" / "demonet-ring2-500.jsonl"

PASS_THRESHOLDS: Final[dict[str, dict[str, float]]] = {
    "high": {"precision": 0.95, "recall": 0.90},
    "medium": {"precision": 0.75, "recall": 0.75},
    "low": {"precision": 0.70, "recall": 0.70},
    "none": {"precision": 0.85, "recall": 0.85},
}
OVERALL_ACCURACY_THRESHOLD: Final[float] = 0.85


@dataclass
class Result:
    capability_name: str
    surface: str
    expected_risk: str
    predicted_risk: str
    expected_allowed: bool
    predicted_allowed: bool
    elapsed_s: float
    error: str | None = None


@dataclass
class MockClassifier:
    """Always returns the catalog-expected risk, as if the LLM agreed.

    Useful for validating the harness itself (parsing, metrics) without
    a real LiteLLM round-trip. Does NOT exercise the classifier's JSON-
    parse robustness — that's covered by ``test_ring2_classifier.py``.
    """

    def classify(
        self, *, capability_name: str, rendered_payload: Any, surface: SurfaceKind
    ) -> RiskAssessment:
        # Echo "none" always — guarantees a predictable accuracy baseline
        # the harness can report. Real runs use the real classifier.
        return RiskAssessment(
            allowed=True, risk="none", reason="mock classifier (no LLM)", surface=surface
        )


def load_samples(path: Path) -> list[dict[str, Any]]:
    samples = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            samples.append(json.loads(line))
    return samples


def run_benchmark(
    samples: list[dict[str, Any]],
    classifier: Any,
    *,
    max_samples: int | None = None,
) -> list[Result]:
    """Run classifier over samples, collect predicted vs expected risk."""
    if max_samples is not None:
        samples = samples[:max_samples]
    results: list[Result] = []
    for s in samples:
        surface = SurfaceKind(s["surface"])
        t0 = time.monotonic()
        try:
            assessment = classifier.classify(
                capability_name=s["capability_name"],
                rendered_payload=s["rendered_payload"],
                surface=surface,
            )
            elapsed = time.monotonic() - t0
            results.append(
                Result(
                    capability_name=s["capability_name"],
                    surface=s["surface"],
                    expected_risk=s["expected_risk"],
                    predicted_risk=assessment.risk,
                    expected_allowed=s["expected_allowed"],
                    predicted_allowed=assessment.allowed,
                    elapsed_s=elapsed,
                )
            )
        except ClassifierUnavailable as e:
            elapsed = time.monotonic() - t0
            results.append(
                Result(
                    capability_name=s["capability_name"],
                    surface=s["surface"],
                    expected_risk=s["expected_risk"],
                    predicted_risk="__ERROR__",
                    expected_allowed=s["expected_allowed"],
                    predicted_allowed=False,
                    elapsed_s=elapsed,
                    error=str(e),
                )
            )
    return results


def compute_metrics(results: list[Result]) -> dict[str, Any]:
    """Per-risk precision / recall / F1 + overall accuracy + confusion matrix."""
    risks = ("none", "low", "medium", "high")
    # true_positive[r] = predicted=r AND expected=r
    # false_positive[r] = predicted=r AND expected!=r
    # false_negative[r] = predicted!=r AND expected=r
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    confusion: dict[tuple[str, str], int] = defaultdict(int)
    correct = 0
    total = 0
    errors = 0
    total_time = 0.0

    for r in results:
        total += 1
        total_time += r.elapsed_s
        if r.error is not None:
            errors += 1
            continue
        if r.predicted_risk == r.expected_risk:
            correct += 1
            tp[r.expected_risk] += 1
        else:
            fp[r.predicted_risk] += 1
            fn[r.expected_risk] += 1
        confusion[(r.expected_risk, r.predicted_risk)] += 1

    per_risk: dict[str, dict[str, float]] = {}
    for risk in risks:
        p_denom = tp[risk] + fp[risk]
        r_denom = tp[risk] + fn[risk]
        precision = tp[risk] / p_denom if p_denom else 0.0
        recall = tp[risk] / r_denom if r_denom else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_risk[risk] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "tp": tp[risk],
            "fp": fp[risk],
            "fn": fn[risk],
        }

    return {
        "total": total,
        "errors": errors,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "mean_elapsed_s": total_time / total if total else 0.0,
        "per_risk": per_risk,
        "confusion": {f"{k[0]}→{k[1]}": v for k, v in confusion.items()},
    }


def check_thresholds(metrics: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (all_pass, list_of_failures)."""
    failures: list[str] = []
    for risk, thresholds in PASS_THRESHOLDS.items():
        pm = metrics["per_risk"].get(risk, {})
        for metric, threshold in thresholds.items():
            value = pm.get(metric, 0.0)
            if value < threshold:
                failures.append(f"{risk}.{metric}: {value:.3f} < {threshold:.3f} threshold")
    if metrics["accuracy"] < OVERALL_ACCURACY_THRESHOLD:
        failures.append(
            f"overall accuracy: {metrics['accuracy']:.3f} < "
            f"{OVERALL_ACCURACY_THRESHOLD:.3f} threshold"
        )
    return (len(failures) == 0, failures)


def format_report(metrics: dict[str, Any]) -> str:
    lines = []
    lines.append("=" * 72)
    lines.append("Ring 2 classifier benchmark results")
    lines.append("=" * 72)
    lines.append(f"Total samples:     {metrics['total']}")
    lines.append(f"Errors:            {metrics['errors']}")
    lines.append(f"Correct:           {metrics['correct']}")
    lines.append(f"Overall accuracy:  {metrics['accuracy']:.3f}")
    lines.append(f"Mean latency/call: {metrics['mean_elapsed_s']:.3f}s")
    lines.append("")
    lines.append("Per-risk metrics:")
    lines.append(
        f"  {'risk':10s} {'precision':>10s} {'recall':>10s} {'f1':>10s} "
        f"{'tp':>5s} {'fp':>5s} {'fn':>5s}"
    )
    for risk in ("none", "low", "medium", "high"):
        pr = metrics["per_risk"][risk]
        lines.append(
            f"  {risk:10s} {pr['precision']:>10.3f} {pr['recall']:>10.3f} "
            f"{pr['f1']:>10.3f} {pr['tp']:>5d} {pr['fp']:>5d} {pr['fn']:>5d}"
        )
    lines.append("")
    lines.append("Confusion (expected → predicted):")
    for key, count in sorted(metrics["confusion"].items()):
        lines.append(f"  {key:30s} {count:>5d}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ring 2 classifier benchmark")
    parser.add_argument(
        "--benchmark-path",
        type=Path,
        default=DEFAULT_BENCHMARK_PATH,
        help="JSONL benchmark sample file",
    )
    parser.add_argument(
        "--mock", action="store_true", help="Use mock classifier (no LLM round-trip)"
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Limit sample count (useful for smoke tests)",
    )
    parser.add_argument(
        "--no-thresholds",
        action="store_true",
        help="Skip pass/fail threshold checks (report only)",
    )
    args = parser.parse_args()

    if not args.benchmark_path.exists():
        print(
            f"benchmark sample file missing: {args.benchmark_path}\n"
            "Run: uv run python -m scripts.generate_ring2_benchmark",
            file=sys.stderr,
        )
        return 2

    samples = load_samples(args.benchmark_path)
    print(f"Loaded {len(samples)} samples from {args.benchmark_path}")

    if args.mock:
        classifier: Any = MockClassifier()
        print("Classifier: MockClassifier (always returns 'none')")
    else:
        from shared.governance.ring2_classifier import Ring2Classifier

        classifier = Ring2Classifier()
        print(f"Classifier: Ring2Classifier (model={classifier.model})")

    results = run_benchmark(samples, classifier, max_samples=args.max_samples)
    metrics = compute_metrics(results)
    print(format_report(metrics))

    if args.no_thresholds:
        return 0
    ok, failures = check_thresholds(metrics)
    print()
    if ok:
        print("ALL THRESHOLDS MET — classifier is production-ready")
        return 0
    print("THRESHOLD FAILURES:")
    for f in failures:
        print(f"  - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
