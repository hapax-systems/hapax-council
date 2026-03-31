"""Post-hoc analysis for Measure 3.1 A/B results.

Run: uv run python tests/research/analysis.py tests/research/results/<file>.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def analyze(path: Path) -> None:
    data = json.loads(path.read_text())
    trials = data["trials"]

    flat: dict[str, list[float]] = defaultdict(list)
    temporal: dict[str, list[float]] = defaultdict(list)

    for t in trials:
        target = flat if t["condition"] == "flat" else temporal
        for metric, score in t["scores"].items():
            target[metric].append(score)

    print(f"Trials: {len(trials)} ({len(trials) // 2} pairs)")
    print()

    metrics = sorted(set(flat.keys()) | set(temporal.keys()))
    for metric in metrics:
        f_vals = flat[metric]
        t_vals = temporal[metric]
        f_mean = sum(f_vals) / len(f_vals) if f_vals else 0
        t_mean = sum(t_vals) / len(t_vals) if t_vals else 0
        effect = t_mean - f_mean

        # Paired differences for CI
        n = min(len(f_vals), len(t_vals))
        diffs = [t_vals[i] - f_vals[i] for i in range(n)]
        mean_diff = sum(diffs) / n if n else 0
        var_diff = sum((d - mean_diff) ** 2 for d in diffs) / max(1, n - 1)
        se = (var_diff / max(1, n)) ** 0.5

        # t-statistic (paired)
        t_stat = mean_diff / se if se > 0 else 0

        print(f"{metric}:")
        print(f"  flat={f_mean:.2f}  temporal={t_mean:.2f}  effect={effect:+.3f}")
        print(f"  paired t={t_stat:.2f}  SE={se:.3f}  n={n}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Find most recent result
        results_dir = Path(__file__).parent / "results"
        files = sorted(results_dir.glob("contrast_*.json"))
        if not files:
            print("No results found. Run test_temporal_contrast.py first.")
            sys.exit(1)
        path = files[-1]
    else:
        path = Path(sys.argv[1])

    analyze(path)
