"""Sequential experiment runner for conversational continuity claims.

Fetches Langfuse scores, computes Bayes Factors per claim against
pre-registered priors and ROPEs, applies stopping rules, and writes
results to proofs/claim-N/analysis/.

Run as: uv run python -m agents.hapax_voice.experiment_runner [--since HOURS]
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agents.hapax_voice.stats import bayes_correlation, bayes_factor, rope_check, sequential_check

log = logging.getLogger(__name__)

PROOFS_DIR = Path(__file__).parent / "proofs"


# ── Claim Specifications (from pre-registered hypotheses) ───────────────────


@dataclass(frozen=True)
class ClaimSpec:
    """Pre-registered claim parameters."""

    name: str
    slug: str
    metric: str  # Langfuse score name
    prior_a: float  # Beta prior alpha
    prior_b: float  # Beta prior beta
    rope_low: float
    rope_high: float
    max_sessions: int
    min_turns: int
    threshold: float  # success threshold for binarizing continuous metric


CLAIMS: dict[int, ClaimSpec] = {
    1: ClaimSpec(
        name="Stable frame improves context anchoring",
        slug="claim-1-stable-frame",
        metric="context_anchor_success",
        prior_a=2.0,
        prior_b=2.0,
        rope_low=0.45,
        rope_high=0.55,
        max_sessions=30,
        min_turns=5,
        threshold=0.7,
    ),
    2: ClaimSpec(
        name="Simple message drop maintains reference accuracy",
        slug="claim-2-message-drop",
        metric="reference_accuracy",
        prior_a=8.0,
        prior_b=2.0,
        rope_low=0.7,
        rope_high=0.9,
        max_sessions=20,
        min_turns=10,
        threshold=0.8,
    ),
    3: ClaimSpec(
        name="Cross-session memory enables recall",
        slug="claim-3-cross-session",
        metric="context_anchor_success",
        prior_a=1.0,
        prior_b=1.0,
        rope_low=0.0,
        rope_high=0.2,
        max_sessions=10,
        min_turns=2,
        threshold=0.5,
    ),
    4: ClaimSpec(
        name="Sentinel fact survives system prompt rebuilds",
        slug="claim-4-sentinel",
        metric="sentinel_retrieval",
        prior_a=9.0,
        prior_b=1.0,
        rope_low=0.85,
        rope_high=1.0,
        max_sessions=15,
        min_turns=2,
        threshold=0.5,
    ),
}


# ── Langfuse Data Collection ───────────────────────────────────────────────


def _fetch_voice_traces(since_hours: float = 48) -> list[dict]:
    """Fetch voice traces with full score data from Langfuse REST API."""
    from shared.langfuse_client import langfuse_get

    since = (datetime.now(UTC) - timedelta(hours=since_hours)).isoformat()

    all_traces: list[dict] = []
    page = 1
    while page <= 20:
        resp = langfuse_get(
            "/traces",
            {"name": "voice.utterance", "fromTimestamp": since, "limit": 100, "page": str(page)},
        )
        if not resp:
            break
        data = resp.get("data", [])
        if not data:
            break
        all_traces.extend(data)
        total = resp.get("meta", {}).get("totalItems", 0)
        if page * 100 >= total:
            break
        page += 1

    # Enrich with full score data
    for trace in all_traces:
        detail = langfuse_get(f"/traces/{trace['id']}")
        if detail:
            trace["scores"] = detail.get("scores", [])

    return all_traces


def _fetch_scores(metric: str, since_hours: float = 48) -> list[dict]:
    """Fetch per-turn scores from Langfuse for a specific metric.

    Returns list of {"session_id", "turn", "value", "timestamp"}.
    """
    traces = _fetch_voice_traces(since_hours)

    results: list[dict] = []
    for trace in traces:
        for s in trace.get("scores", []):
            if s.get("name") == metric:
                sid = trace.get("sessionId") or (trace.get("metadata") or {}).get(
                    "session_id", "unknown"
                )
                meta = trace.get("metadata") or {}
                turn_raw = meta.get("turn", 0)
                turn = (
                    turn_raw.get("intValue", turn_raw) if isinstance(turn_raw, dict) else turn_raw
                )
                results.append(
                    {
                        "session_id": sid,
                        "turn": turn,
                        "value": float(s.get("value", 0)),
                        "timestamp": trace.get("timestamp", ""),
                    }
                )
    return results


def _fetch_activation_pairs(since_hours: float = 48) -> list[dict]:
    """Fetch (activation_score, response_tokens, context_anchor_success) triples."""
    traces = _fetch_voice_traces(since_hours)

    results: list[dict] = []
    for trace in traces:
        score_map: dict[str, float] = {}
        for s in trace.get("scores", []):
            name = s.get("name", "")
            val = s.get("value")
            if name and val is not None:
                score_map[name] = float(val)

        activation = score_map.get("activation_score")
        if activation is None or activation < 0:
            continue

        # Use output length as token proxy
        output = trace.get("output")
        if isinstance(output, str):
            tokens = float(len(output.split()))
        elif isinstance(output, dict):
            tokens = float(len(str(output.get("text", "")).split()))
        else:
            tokens = 0.0

        results.append(
            {
                "activation": activation,
                "tokens": tokens,
                "anchor": score_map.get("context_anchor_success", 0.0),
            }
        )
    return results


# ── Per-Claim Analysis ──────────────────────────────────────────────────────


def analyze_claim(claim_id: int, since_hours: float = 48) -> dict:
    """Run sequential analysis for a single claim (1-4).

    Returns analysis dict with bf, decision, rope, session counts.
    """
    spec = CLAIMS[claim_id]
    raw = _fetch_scores(spec.metric, since_hours)

    # Group by session, filter by min_turns
    sessions: dict[str, list[float]] = {}
    for r in raw:
        sid = r["session_id"]
        if sid not in sessions:
            sessions[sid] = []
        sessions[sid].append(r["value"])

    valid_sessions = {s: v for s, v in sessions.items() if len(v) >= spec.min_turns}
    n_sessions = len(valid_sessions)

    # Binarize: each session is a "success" if mean metric >= threshold
    successes = sum(1 for v in valid_sessions.values() if (sum(v) / len(v)) >= spec.threshold)

    if n_sessions == 0:
        return {
            "claim": claim_id,
            "name": spec.name,
            "status": "no_data",
            "n_sessions": 0,
            "successes": 0,
            "bf": None,
            "decision": "no_data",
            "rope": None,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    bf = bayes_factor(
        successes,
        n_sessions,
        prior_a=spec.prior_a,
        prior_b=spec.prior_b,
        rope_low=spec.rope_low,
        rope_high=spec.rope_high,
    )
    decision = sequential_check(bf, n_sessions, spec.max_sessions)
    rope = rope_check(
        successes,
        n_sessions,
        prior_a=spec.prior_a,
        prior_b=spec.prior_b,
        rope_low=spec.rope_low,
        rope_high=spec.rope_high,
    )

    return {
        "claim": claim_id,
        "name": spec.name,
        "status": "analyzed",
        "n_sessions": n_sessions,
        "successes": successes,
        "success_rate": successes / n_sessions,
        "bf": bf,
        "decision": decision,
        "rope": rope,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def analyze_claim5(since_hours: float = 48) -> dict:
    """Run correlation analysis for Claim 5 (salience correlation).

    Returns analysis dict with Bayesian correlation results.
    """
    pairs = _fetch_activation_pairs(since_hours)
    n = len(pairs)

    if n < 50:
        return {
            "claim": 5,
            "name": "Salience activation correlates with response properties",
            "status": "insufficient_data",
            "n_turns": n,
            "required": 50,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    activations = [p["activation"] for p in pairs]
    tokens = [p["tokens"] for p in pairs]
    anchors = [p["anchor"] for p in pairs]

    corr_tokens = bayes_correlation(activations, tokens, prior_mu=0.3, prior_sigma=0.15)
    corr_anchor = bayes_correlation(activations, anchors, prior_mu=0.3, prior_sigma=0.15)

    bf_max = max(corr_tokens["bf"], corr_anchor["bf"])
    decision = sequential_check(bf_max, n, max_n=200, bf_threshold=10.0)

    return {
        "claim": 5,
        "name": "Salience activation correlates with response properties",
        "status": "analyzed",
        "n_turns": n,
        "correlation_tokens": {
            "r": corr_tokens["r"],
            "bf": corr_tokens["bf"],
            "ci_95": list(corr_tokens["ci_95"]),
        },
        "correlation_anchor": {
            "r": corr_anchor["r"],
            "bf": corr_anchor["bf"],
            "ci_95": list(corr_anchor["ci_95"]),
        },
        "decision": decision,
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ── Output ──────────────────────────────────────────────────────────────────


def save_results(results: list[dict]) -> Path:
    """Write analysis results to proofs/analysis/ as timestamped JSON."""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")

    for result in results:
        claim_id = result["claim"]
        if claim_id <= 4:
            slug = CLAIMS[claim_id].slug
        else:
            slug = "claim-5-salience-correlation"

        out_dir = PROOFS_DIR / slug / "analysis"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"run-{ts}.json"
        out_path.write_text(json.dumps(result, indent=2) + "\n")
        log.info("Saved %s → %s", slug, out_path)

    # Also write a combined summary
    summary_path = PROOFS_DIR / f"analysis-{ts}.json"
    summary_path.write_text(json.dumps(results, indent=2) + "\n")
    return summary_path


def format_summary(results: list[dict]) -> str:
    """Format results as a human-readable summary."""
    lines = ["# Experiment Runner Results", f"Timestamp: {datetime.now(UTC).isoformat()}", ""]

    for r in results:
        lines.append(f"## Claim {r['claim']}: {r['name']}")

        if r["status"] == "no_data":
            lines.append("  No data available yet.")
        elif r["status"] == "insufficient_data":
            lines.append(f"  Insufficient data: {r['n_turns']}/{r['required']} turns")
        elif r["claim"] <= 4:
            lines.append(f"  Sessions: {r['n_sessions']}")
            lines.append(f"  Successes: {r['successes']} ({r['success_rate']:.1%})")
            lines.append(f"  Bayes Factor: {r['bf']:.2f}")
            lines.append(
                f"  ROPE: inside={r['rope']['inside']:.3f} outside={r['rope']['outside']:.3f}"
            )
            lines.append(f"  Decision: **{r['decision']}**")
        else:
            ct = r["correlation_tokens"]
            ca = r["correlation_anchor"]
            lines.append(f"  Turns: {r['n_turns']}")
            lines.append(
                f"  r(activation, tokens)={ct['r']:.3f}  BF={ct['bf']:.2f}  CI={ct['ci_95']}"
            )
            lines.append(
                f"  r(activation, anchor)={ca['r']:.3f}  BF={ca['bf']:.2f}  CI={ca['ci_95']}"
            )
            lines.append(f"  Decision: **{r['decision']}**")

        lines.append("")

    # Overall status
    decisions = [r.get("decision", "no_data") for r in results]
    active = sum(1 for d in decisions if d == "continue")
    stopped = sum(1 for d in decisions if d.startswith("stop_"))
    pending = sum(1 for d in decisions if d in ("no_data", "insufficient_data"))
    lines.append(f"**Active: {active} | Stopped: {stopped} | Pending: {pending}**")

    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Sequential experiment runner")
    parser.add_argument("--since", type=float, default=48, help="Hours to look back")
    parser.add_argument("--claims", type=str, default="1,2,3,4,5", help="Comma-separated claim IDs")
    parser.add_argument("--dry-run", action="store_true", help="Print results without saving")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="experiment-runner")

    claim_ids = [int(c.strip()) for c in args.claims.split(",")]
    results: list[dict] = []

    for cid in claim_ids:
        if cid <= 4:
            print(f"Analyzing claim {cid}...")
            results.append(analyze_claim(cid, since_hours=args.since))
        elif cid == 5:
            print("Analyzing claim 5 (correlation)...")
            results.append(analyze_claim5(since_hours=args.since))

    summary = format_summary(results)
    print(summary)

    if not args.dry_run:
        path = save_results(results)
        print(f"\nResults saved to {path}")


if __name__ == "__main__":
    main()
