"""deliberation_eval.py — CLI for deliberation metric extraction and probe evaluation.

Thin wrapper around shared.deliberation_metrics (extraction) and
shared.sufficiency_probes (evaluation via axiom governance).

Usage:
    uv run python -m agents.deliberation_eval                      # Extract + run probes
    uv run python -m agents.deliberation_eval --pattern '*-v5.yaml' # Custom glob
    uv run python -m agents.deliberation_eval --probes-only         # Just run probes
"""

from __future__ import annotations

import argparse
from pathlib import Path

from shared.deliberation_metrics import (
    DELIBERATIONS_DIR,
    EVAL_FILE,
    extract_batch,
    format_batch_summary,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deliberation metric extraction and evaluation")
    parser.add_argument("--pattern", default="*-v5.yaml", help="Glob pattern for YAML files")
    parser.add_argument("--dir", type=Path, default=DELIBERATIONS_DIR, help="Directory to scan")
    parser.add_argument("--output", type=Path, default=EVAL_FILE, help="JSONL output path")
    parser.add_argument("--probes-only", action="store_true", help="Only run sufficiency probes")
    parser.add_argument("--dry-run", action="store_true", help="Extract without writing JSONL")
    args = parser.parse_args()

    if not args.probes_only:
        output = None if args.dry_run else args.output
        metrics = extract_batch(args.dir, output, args.pattern)
        print(format_batch_summary(metrics))

    # Run deliberation sufficiency probes
    print(f"\n{'=' * 60}")
    print("SUFFICIENCY PROBES (ex-delib-*)")
    print(f"{'=' * 60}")

    from shared.sufficiency_probes import run_probes

    results = run_probes(axiom_id="executive_function")
    delib_results = [r for r in results if r.probe_id.startswith("probe-delib-")]

    for r in delib_results:
        icon = "PASS" if r.met else "FAIL"
        print(f"  [{icon}] {r.probe_id}: {r.evidence}")


if __name__ == "__main__":
    main()
