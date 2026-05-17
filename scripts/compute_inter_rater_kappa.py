#!/usr/bin/env python3
"""Compute inter-rater reliability (Cohen's kappa) between CCTV and Perplexity verdicts.

Reads paired score data from two JSONL verdict files and computes:
- Cohen's kappa (unweighted) per rubric axis
- Quadratic-weighted kappa per rubric axis (appropriate for ordinal 1-5 scales)
- Aggregate across all axes
- Percent exact agreement and ±1 agreement

Usage:
    uv run python scripts/compute_inter_rater_kappa.py \
        --cctv cctv-calibration-probe-verdicts.jsonl \
        --perplexity perplexity-calibration-probe-verdicts.jsonl

    # Or with defaults (reads from epistemic-quality dataset dir):
    uv run python scripts/compute_inter_rater_kappa.py

Output written to stdout (human-readable) and to a JSONL results file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DATA_DIR = Path.home() / "Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality"
DEFAULT_CCTV = DATA_DIR / "cctv-calibration-probe-verdicts.jsonl"
DEFAULT_PERPLEXITY = DATA_DIR / "perplexity-calibration-probe-verdicts.jsonl"
OUTPUT_FILE = DATA_DIR / "inter-rater-kappa-results.json"

RUBRIC_AXES = [
    "counter_evidence_resilience",
    "evidence_adequacy",
    "falsifiability",
    "scope_honesty",
]
SCORE_RANGE = range(1, 6)  # 1-5 ordinal scale


def load_verdicts(path: Path) -> dict[str, dict[str, int]]:
    """Load verdict file → {probe_id: {axis: score}}."""
    verdicts: dict[str, dict[str, int]] = {}
    for line in path.read_text().strip().splitlines():
        record = json.loads(line)
        probe_id = record.get("probe_id") or record.get("claim_id") or record.get("id")
        scores = record.get("scores", {})
        if probe_id and scores:
            verdicts[probe_id] = {k: int(v) for k, v in scores.items() if k in RUBRIC_AXES}
    return verdicts


def cohens_kappa(ratings_a: list[int], ratings_b: list[int], *, weights: str = "none") -> float:
    """Compute Cohen's kappa between two raters.

    weights: "none" for unweighted, "quadratic" for quadratic-weighted.
    """
    n = len(ratings_a)
    if n == 0:
        return 0.0

    labels = sorted(set(ratings_a) | set(ratings_b) | set(SCORE_RANGE))
    k = len(labels)
    label_idx = {lab: i for i, lab in enumerate(labels)}

    # Build confusion matrix
    confusion = [[0] * k for _ in range(k)]
    for a, b in zip(ratings_a, ratings_b, strict=True):
        confusion[label_idx[a]][label_idx[b]] += 1

    # Weight matrix
    w = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(k):
            if weights == "quadratic":
                w[i][j] = ((i - j) ** 2) / ((k - 1) ** 2) if k > 1 else 0.0
            else:
                w[i][j] = 0.0 if i == j else 1.0

    # Marginals
    row_sums = [sum(confusion[i]) for i in range(k)]
    col_sums = [sum(confusion[i][j] for i in range(k)) for j in range(k)]

    # Observed and expected disagreement
    po = sum(w[i][j] * confusion[i][j] for i in range(k) for j in range(k)) / n
    pe = sum(w[i][j] * row_sums[i] * col_sums[j] for i in range(k) for j in range(k)) / (n * n)

    if pe == 1.0:
        return 1.0 if po == 0.0 else 0.0
    return 1.0 - (po / pe)


def percent_agreement(ratings_a: list[int], ratings_b: list[int], *, tolerance: int = 0) -> float:
    """Fraction of pairs where |a - b| <= tolerance."""
    if not ratings_a:
        return 0.0
    matches = sum(1 for a, b in zip(ratings_a, ratings_b, strict=True) if abs(a - b) <= tolerance)
    return matches / len(ratings_a)


def compute_kappa_report(
    cctv_verdicts: dict[str, dict[str, int]],
    perplexity_verdicts: dict[str, dict[str, int]],
) -> dict:
    """Compute full inter-rater kappa report across matched probes."""
    matched_ids = sorted(set(cctv_verdicts.keys()) & set(perplexity_verdicts.keys()))

    if not matched_ids:
        return {"error": "No matched probe IDs between CCTV and Perplexity verdicts"}

    axis_results: dict[str, dict] = {}
    all_cctv: list[int] = []
    all_perplexity: list[int] = []

    for axis in RUBRIC_AXES:
        cctv_scores = []
        perp_scores = []
        for pid in matched_ids:
            c_score = cctv_verdicts[pid].get(axis)
            p_score = perplexity_verdicts[pid].get(axis)
            if c_score is not None and p_score is not None:
                cctv_scores.append(c_score)
                perp_scores.append(p_score)

        if not cctv_scores:
            axis_results[axis] = {"n": 0, "note": "no paired scores"}
            continue

        kappa_unweighted = cohens_kappa(cctv_scores, perp_scores, weights="none")
        kappa_weighted = cohens_kappa(cctv_scores, perp_scores, weights="quadratic")
        exact = percent_agreement(cctv_scores, perp_scores, tolerance=0)
        within_one = percent_agreement(cctv_scores, perp_scores, tolerance=1)

        axis_results[axis] = {
            "n": len(cctv_scores),
            "kappa_unweighted": round(kappa_unweighted, 4),
            "kappa_quadratic_weighted": round(kappa_weighted, 4),
            "percent_exact_agreement": round(exact, 4),
            "percent_within_1": round(within_one, 4),
            "cctv_mean": round(sum(cctv_scores) / len(cctv_scores), 2),
            "perplexity_mean": round(sum(perp_scores) / len(perp_scores), 2),
            "mean_diff": round(
                sum(c - p for c, p in zip(cctv_scores, perp_scores, strict=True))
                / len(cctv_scores),
                2,
            ),
        }

        all_cctv.extend(cctv_scores)
        all_perplexity.extend(perp_scores)

    # Aggregate
    aggregate = {}
    if all_cctv:
        aggregate = {
            "n_total_pairs": len(all_cctv),
            "n_matched_probes": len(matched_ids),
            "kappa_unweighted": round(cohens_kappa(all_cctv, all_perplexity, weights="none"), 4),
            "kappa_quadratic_weighted": round(
                cohens_kappa(all_cctv, all_perplexity, weights="quadratic"), 4
            ),
            "percent_exact_agreement": round(
                percent_agreement(all_cctv, all_perplexity, tolerance=0), 4
            ),
            "percent_within_1": round(percent_agreement(all_cctv, all_perplexity, tolerance=1), 4),
        }

    return {
        "matched_probe_ids": matched_ids,
        "axes": axis_results,
        "aggregate": aggregate,
    }


def _interpret_kappa(k: float) -> str:
    """Landis & Koch (1977) interpretation."""
    if k < 0:
        return "poor"
    if k < 0.21:
        return "slight"
    if k < 0.41:
        return "fair"
    if k < 0.61:
        return "moderate"
    if k < 0.81:
        return "substantial"
    return "almost perfect"


def print_report(report: dict) -> None:
    """Pretty-print the kappa report."""
    if "error" in report:
        print(f"ERROR: {report['error']}")
        return

    agg = report["aggregate"]
    print("=" * 60)
    print("INTER-RATER RELIABILITY: CCTV vs Perplexity Model Council")
    print("=" * 60)
    print(f"\nMatched probes: {agg['n_matched_probes']}")
    print(f"Total score pairs: {agg['n_total_pairs']}")
    print(
        f"\nAggregate kappa (unweighted):  {agg['kappa_unweighted']:.4f} "
        f"({_interpret_kappa(agg['kappa_unweighted'])})"
    )
    print(
        f"Aggregate kappa (quadratic):   {agg['kappa_quadratic_weighted']:.4f} "
        f"({_interpret_kappa(agg['kappa_quadratic_weighted'])})"
    )
    print(f"Exact agreement:               {agg['percent_exact_agreement']:.1%}")
    print(f"Within ±1 agreement:           {agg['percent_within_1']:.1%}")

    print("\n" + "-" * 60)
    print(f"{'Axis':<30} {'κ_w':>6} {'Exact':>7} {'±1':>7} {'Δ_mean':>7} {'n':>4}")
    print("-" * 60)
    for axis, data in report["axes"].items():
        if data.get("n", 0) == 0:
            print(f"{axis:<30} {'—':>6} {'—':>7} {'—':>7} {'—':>7} {'0':>4}")
            continue
        print(
            f"{axis:<30} "
            f"{data['kappa_quadratic_weighted']:>6.3f} "
            f"{data['percent_exact_agreement']:>6.1%} "
            f"{data['percent_within_1']:>6.1%} "
            f"{data['mean_diff']:>+6.2f} "
            f"{data['n']:>4}"
        )
    print("-" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute CCTV vs Perplexity inter-rater kappa")
    parser.add_argument("--cctv", type=Path, default=DEFAULT_CCTV)
    parser.add_argument("--perplexity", type=Path, default=DEFAULT_PERPLEXITY)
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    args = parser.parse_args()

    if not args.cctv.exists():
        print(f"CCTV verdicts not found: {args.cctv}", file=sys.stderr)
        sys.exit(1)
    if not args.perplexity.exists():
        print(f"Perplexity verdicts not found: {args.perplexity}", file=sys.stderr)
        print(
            "Operator needs to paste probes into Perplexity Model Council and export results.",
            file=sys.stderr,
        )
        sys.exit(1)

    cctv = load_verdicts(args.cctv)
    perplexity = load_verdicts(args.perplexity)

    print(f"CCTV: {len(cctv)} verdicts from {args.cctv.name}")
    print(f"Perplexity: {len(perplexity)} verdicts from {args.perplexity.name}")

    report = compute_kappa_report(cctv, perplexity)
    print_report(report)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(f"\nResults written to: {args.output}")


if __name__ == "__main__":
    main()
