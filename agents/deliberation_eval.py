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
import logging
from pathlib import Path

from agents._deliberation_metrics import (
    DELIBERATIONS_DIR,
    EVAL_FILE,
    extract_batch,
    format_batch_summary,
    read_recent_metrics,
)

try:
    from agents import _langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

log = logging.getLogger("agents.deliberation_eval")

PSEUDO_THRESHOLD = 3  # number of pseudo-deliberations to trigger escalation


def _escalate_pseudo_deliberations() -> None:
    """If recent metrics show repeated pseudo-deliberations, record a precedent.

    GAP-8: Pseudo-deliberation detection → escalation. When 3+ of the last 50
    metrics are pseudo-deliberations, record an edge_case precedent so
    _collect_precedent_nudges() surfaces it for operator review.
    """
    metrics = read_recent_metrics(n=50)
    pseudo = [m for m in metrics if m.is_pseudo_deliberation]
    if len(pseudo) < PSEUDO_THRESHOLD:
        return

    try:
        from agents._axiom_precedents import Precedent, PrecedentStore

        ids = ", ".join(m.deliberation_id for m in pseudo[:5])
        store = PrecedentStore()
        precedent_id = store.record(
            Precedent(
                id="",
                axiom_id="executive_function",
                situation=(
                    f"{len(pseudo)} of last {len(metrics)} deliberations are pseudo-deliberations "
                    f"(fail all 3 hoop tests despite multiple rounds). IDs: {ids}"
                ),
                decision="edge_case",
                reasoning=(
                    "Repeated pseudo-deliberations indicate the deliberation process is not "
                    "producing genuine engagement between agents. This may signal prompt drift, "
                    "model capability mismatch, or structural issues in the deliberation format. "
                    "Operator review needed to determine root cause and corrective action."
                ),
                tier="T2",
                distinguishing_facts=[
                    f"{len(pseudo)}/{len(metrics)} recent deliberations are pseudo",
                    "All three hoop tests (position shift, argument tracing, counterfactual divergence) failed",
                    "Pattern detected automatically by deliberation_eval escalation",
                ],
                authority="agent",
                created="",
            )
        )
        log.info("Escalated pseudo-deliberation pattern as precedent %s", precedent_id)
        print(f"\n  ** Escalated: {len(pseudo)} pseudo-deliberations → precedent {precedent_id}")
    except Exception as e:
        log.warning("Failed to escalate pseudo-deliberation pattern: %s", e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deliberation metric extraction and evaluation")
    parser.add_argument("--pattern", default="*-v5.yaml", help="Glob pattern for YAML files")
    parser.add_argument("--dir", type=Path, default=DELIBERATIONS_DIR, help="Directory to scan")
    parser.add_argument("--output", type=Path, default=EVAL_FILE, help="JSONL output path")
    parser.add_argument("--probes-only", action="store_true", help="Only run sufficiency probes")
    parser.add_argument("--dry-run", action="store_true", help="Extract without writing JSONL")
    args = parser.parse_args()

    with _tracer.start_as_current_span(
        "deliberation_eval.run",
        attributes={"agent.name": "deliberation_eval", "agent.repo": "hapax-council"},
    ):
        if not args.probes_only:
            output = None if args.dry_run else args.output
            metrics = extract_batch(args.dir, output, args.pattern)
            print(format_batch_summary(metrics))

            # GAP-8: Check for pseudo-deliberation pattern and escalate if needed
            _escalate_pseudo_deliberations()

        # Run deliberation sufficiency probes
        print(f"\n{'=' * 60}")
        print("SUFFICIENCY PROBES (ex-delib-*)")
        print(f"{'=' * 60}")

        from agents._sufficiency_probes import run_probes

        results = run_probes(axiom_id="executive_function")
        delib_results = [r for r in results if r.probe_id.startswith("probe-delib-")]

        for r in delib_results:
            icon = "PASS" if r.met else "FAIL"
            print(f"  [{icon}] {r.probe_id}: {r.evidence}")


if __name__ == "__main__":
    main()
