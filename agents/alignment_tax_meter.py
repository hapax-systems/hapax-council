"""Alignment tax measurement — governance overhead as percentage of total cost.

Three dimensions measured:
1. **Token cost**: governance LLM calls vs total LLM calls (from Langfuse)
2. **Wall-clock time**: SDLC axiom-gate duration vs total pipeline duration
3. **Label operation overhead**: consent label join/can_flow_to microbenchmarks

No LLM calls. Pure metric extraction from existing data sources.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agents._config import PROFILES_DIR

log = logging.getLogger(__name__)

SDLC_EVENTS_PATH = PROFILES_DIR / "sdlc-events.jsonl"
ENFORCEMENT_AUDIT_PATH = PROFILES_DIR / ".enforcement-audit.jsonl"

# Governance-specific trace names/metadata patterns
GOVERNANCE_TRACE_PATTERNS = {
    "axiom_gate",
    "axiom_judge",
    "axiom_check",
    "consent_check",
    "contract_check",
    "governance",
}


@dataclass(frozen=True)
class AlignmentTaxSnapshot:
    """Complete alignment tax measurement at a point in time."""

    # Token cost dimension
    governance_token_cost: float = 0.0
    total_token_cost: float = 0.0
    token_tax_pct: float = 0.0

    # SDLC pipeline dimension
    axiom_gate_duration_ms: float = 0.0
    total_pipeline_duration_ms: float = 0.0
    sdlc_tax_pct: float = 0.0

    # Label operation dimension (microbenchmark)
    label_join_us: float = 0.0  # microseconds per join
    label_flow_check_us: float = 0.0  # microseconds per can_flow_to
    governor_check_us: float = 0.0  # microseconds per check_input

    # Metadata
    measurement_timestamp: str = ""
    lookback_days: int = 0
    sdlc_events_counted: int = 0
    langfuse_available: bool = False


def measure_sdlc_overhead(lookback_days: int = 14) -> dict:
    """Extract SDLC axiom-gate overhead from event log.

    Returns dict with axiom_gate_ms, total_pipeline_ms, tax_pct,
    and per-stage breakdown.
    """
    if not SDLC_EVENTS_PATH.exists():
        return {"available": False, "reason": "no sdlc-events.jsonl"}

    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    stage_durations: dict[str, list[float]] = {}
    events_counted = 0

    for line in SDLC_EVENTS_PATH.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        ts_str = event.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts < cutoff:
                continue
        except (ValueError, TypeError):
            continue

        stage = event.get("stage", "")
        duration = event.get("duration_ms", 0)
        if stage and duration > 0:
            stage_durations.setdefault(stage, []).append(duration)
            events_counted += 1

    if not stage_durations:
        return {"available": False, "reason": "no events with duration in window"}

    # Compute totals
    axiom_gate_ms = sum(stage_durations.get("axiom-gate", []))
    total_ms = sum(d for durs in stage_durations.values() for d in durs)

    tax_pct = (axiom_gate_ms / total_ms * 100) if total_ms > 0 else 0.0

    return {
        "available": True,
        "axiom_gate_ms": axiom_gate_ms,
        "total_pipeline_ms": total_ms,
        "tax_pct": round(tax_pct, 1),
        "events_counted": events_counted,
        "by_stage": {
            stage: {"total_ms": sum(durs), "count": len(durs), "avg_ms": sum(durs) / len(durs)}
            for stage, durs in sorted(stage_durations.items())
        },
    }


def measure_token_cost_overhead(lookback_days: int = 14) -> dict:
    """Extract governance vs total token cost from Langfuse.

    Governance calls are identified by trace name patterns
    (axiom_gate, consent_check, etc.) or metadata flags.
    """
    try:
        from agents._langfuse_client import langfuse_get
    except ImportError:
        return {"available": False, "reason": "langfuse_client not available"}

    try:
        obs = langfuse_get(
            "/api/public/observations",
            params={"type": "GENERATION", "limit": 1000},
        )
        if not obs or "data" not in obs:
            return {"available": False, "reason": "no langfuse data"}
    except Exception as e:
        return {"available": False, "reason": str(e)}

    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    governance_cost = 0.0
    total_cost = 0.0
    governance_calls = 0
    total_calls = 0

    for item in obs["data"]:
        # Check timestamp
        ts_str = item.get("startTime", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts < cutoff:
                continue
        except (ValueError, TypeError):
            continue

        cost = item.get("calculatedTotalCost") or 0.0
        total_cost += cost
        total_calls += 1

        # Identify governance calls
        name = (item.get("name") or "").lower()
        metadata = item.get("metadata") or {}
        is_governance = (
            any(pat in name for pat in GOVERNANCE_TRACE_PATTERNS)
            or metadata.get("is_governance_operation")
            or metadata.get("governance_category")
        )
        if is_governance:
            governance_cost += cost
            governance_calls += 1

    tax_pct = (governance_cost / total_cost * 100) if total_cost > 0 else 0.0

    return {
        "available": True,
        "governance_cost": round(governance_cost, 6),
        "total_cost": round(total_cost, 6),
        "tax_pct": round(tax_pct, 1),
        "governance_calls": governance_calls,
        "total_calls": total_calls,
    }


def measure_label_operations(iterations: int = 10000) -> dict:
    """Microbenchmark consent label operations.

    Measures join, can_flow_to, and governor check_input latency.
    Returns times in microseconds.
    """
    from agents._governance import ConsentLabel, GovernorWrapper, Labeled, consent_input_policy

    # Build labels of varying complexity
    small = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
    medium = ConsentLabel(
        frozenset(
            {
                ("alice", frozenset({"bob", "carol"})),
                ("dave", frozenset({"eve"})),
                ("frank", frozenset({"grace", "heidi"})),
            }
        )
    )
    bottom = ConsentLabel.bottom()

    # Benchmark join
    start = time.perf_counter_ns()
    for _ in range(iterations):
        small.join(medium)
    join_ns = (time.perf_counter_ns() - start) / iterations

    # Benchmark can_flow_to
    start = time.perf_counter_ns()
    for _ in range(iterations):
        small.can_flow_to(medium)
    flow_ns = (time.perf_counter_ns() - start) / iterations

    # Benchmark governor check_input
    gov = GovernorWrapper("bench")
    gov.add_input_policy(consent_input_policy(bottom))
    data = Labeled(value="test", label=small)

    start = time.perf_counter_ns()
    for _ in range(iterations):
        gov.check_input(data)
    gov_ns = (time.perf_counter_ns() - start) / iterations

    return {
        "join_us": round(join_ns / 1000, 3),
        "can_flow_to_us": round(flow_ns / 1000, 3),
        "governor_check_us": round(gov_ns / 1000, 3),
        "iterations": iterations,
        "label_sizes": {"small": 1, "medium": 3},
    }


def measure_alignment_tax(lookback_days: int = 14) -> AlignmentTaxSnapshot:
    """Complete alignment tax measurement across all dimensions."""
    sdlc = measure_sdlc_overhead(lookback_days)
    tokens = measure_token_cost_overhead(lookback_days)
    labels = measure_label_operations()

    return AlignmentTaxSnapshot(
        governance_token_cost=tokens.get("governance_cost", 0.0),
        total_token_cost=tokens.get("total_cost", 0.0),
        token_tax_pct=tokens.get("tax_pct", 0.0),
        axiom_gate_duration_ms=sdlc.get("axiom_gate_ms", 0.0),
        total_pipeline_duration_ms=sdlc.get("total_pipeline_ms", 0.0),
        sdlc_tax_pct=sdlc.get("tax_pct", 0.0),
        label_join_us=labels["join_us"],
        label_flow_check_us=labels["can_flow_to_us"],
        governor_check_us=labels["governor_check_us"],
        measurement_timestamp=datetime.now(UTC).isoformat(),
        lookback_days=lookback_days,
        sdlc_events_counted=sdlc.get("events_counted", 0),
        langfuse_available=tokens.get("available", False),
    )


async def main() -> None:
    """CLI entry point: print alignment tax report."""
    import argparse

    parser = argparse.ArgumentParser(description="Measure alignment tax")
    parser.add_argument("--days", type=int, default=14, help="Lookback window")
    parser.add_argument("--save", action="store_true", help="Save to profiles/")
    args = parser.parse_args()

    snapshot = measure_alignment_tax(args.days)

    print(f"Alignment Tax Report ({args.days}-day window)")
    print(f"{'=' * 50}")
    print()

    print("Token Cost Dimension:")
    if snapshot.langfuse_available:
        print(f"  Governance: ${snapshot.governance_token_cost:.4f}")
        print(f"  Total:      ${snapshot.total_token_cost:.4f}")
        print(f"  Tax:        {snapshot.token_tax_pct:.1f}%")
    else:
        print("  Langfuse unavailable")
    print()

    print("SDLC Pipeline Dimension:")
    if snapshot.sdlc_events_counted > 0:
        print(f"  Axiom gate: {snapshot.axiom_gate_duration_ms:.0f}ms")
        print(f"  Total:      {snapshot.total_pipeline_duration_ms:.0f}ms")
        print(f"  Tax:        {snapshot.sdlc_tax_pct:.1f}%")
        print(f"  Events:     {snapshot.sdlc_events_counted}")
    else:
        print("  No SDLC events with duration data")
    print()

    print("Label Operations (microbenchmark):")
    print(f"  join():          {snapshot.label_join_us:.1f}µs")
    print(f"  can_flow_to():   {snapshot.label_flow_check_us:.1f}µs")
    print(f"  governor check:  {snapshot.governor_check_us:.1f}µs")

    if args.save:
        import dataclasses

        out = PROFILES_DIR / "alignment-tax.json"
        out.write_text(json.dumps(dataclasses.asdict(snapshot), indent=2))
        print(f"\nSaved to {out}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
