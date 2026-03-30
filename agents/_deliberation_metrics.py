"""deliberation_metrics.py — Pure metric extraction from deliberation YAML records.

Extracts computable metrics from structured deliberation records for consumption
by sufficiency probes, the briefing, and the deliberation runner.  No evaluation
logic — that belongs in axiom implications and sufficiency probes.

All functions are pure: dict in, values out.  No I/O, no thresholds, no status.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agents._config import PROFILES_DIR

EVAL_FILE = PROFILES_DIR / "deliberation-eval.jsonl"
DELIBERATIONS_DIR = PROFILES_DIR / "deliberations"


# ── Data models ──────────────────────────────────────────────────────────────


@dataclass
class HoopTestResults:
    """Process-tracing hoop tests — each must be True for a genuine deliberation."""

    position_shift: bool = False
    """At least one agent moved position across the exchange."""
    argument_tracing: bool = False
    """Agents reference and engage with each other's specific claims (non-empty claims_attacked)."""
    counterfactual_divergence: bool = False
    """Update conditions were checked and at least one was marked met."""


@dataclass
class DeliberationMetrics:
    """Extracted metrics from a single deliberation record."""

    deliberation_id: str
    timestamp: str = ""

    # Activation rate: fraction of update_conditions_checked where met == True
    activation_rate: float = 0.0
    activation_rate_publius: float = 0.0
    activation_rate_brutus: float = 0.0

    # Concessions
    concession_count: int = 0
    concession_count_publius: int = 0
    concession_count_brutus: int = 0
    concession_asymmetry_ratio: float = 1.0

    # Responsive reference: fraction of rounds after R1 with non-empty claims_attacked
    responsive_reference_rate: float = 0.0

    # Position movement
    position_movement_publius: bool = False
    position_movement_brutus: bool = False

    # Process metadata
    termination_type: str = "unknown"
    total_rounds: int = 0

    # Hoop tests
    hoop_tests: HoopTestResults | None = None

    # Derived
    is_pseudo_deliberation: bool = False


# ── Pure extraction functions ────────────────────────────────────────────────


def extract_activation_rate(record: dict) -> tuple[float, float, float]:
    """Walk rounds 2+, count update_conditions_checked where met == True.

    Returns (overall, publius, brutus).
    """
    agent_checked: dict[str, int] = {"publius": 0, "brutus": 0}
    agent_met: dict[str, int] = {"publius": 0, "brutus": 0}

    for rnd in record.get("rounds", []):
        if rnd.get("round", 1) < 2:
            continue
        agent = rnd.get("agent", "")
        conditions = rnd.get("update_conditions_checked", [])
        for cond in conditions:
            agent_checked[agent] = agent_checked.get(agent, 0) + 1
            if cond.get("met", False):
                agent_met[agent] = agent_met.get(agent, 0) + 1

    total_checked = sum(agent_checked.values())
    total_met = sum(agent_met.values())

    overall = total_met / total_checked if total_checked > 0 else 0.0
    pub_rate = (
        agent_met["publius"] / agent_checked["publius"] if agent_checked["publius"] > 0 else 0.0
    )
    bru_rate = agent_met["brutus"] / agent_checked["brutus"] if agent_checked["brutus"] > 0 else 0.0

    return overall, pub_rate, bru_rate


def extract_concession_counts(record: dict) -> tuple[int, int, int]:
    """From *_final.concessions_made. Returns (total, publius, brutus)."""
    pub = record.get("publius_final", {}).get("concessions_made", []) or []
    bru = record.get("brutus_final", {}).get("concessions_made", []) or []
    pub_count = len(pub)
    bru_count = len(bru)
    return pub_count + bru_count, pub_count, bru_count


def compute_concession_asymmetry(publius: int, brutus: int) -> float:
    """max/min ratio. Returns 99.0 if one is 0 and other > 0, 1.0 if both 0.

    Uses 99.0 as sentinel instead of inf to stay JSON-serializable.
    """
    if publius == 0 and brutus == 0:
        return 1.0
    if publius == 0 or brutus == 0:
        return 99.0
    return max(publius, brutus) / min(publius, brutus)


def extract_responsive_reference_rate(record: dict) -> float:
    """Fraction of rounds after R1 with non-empty claims_attacked."""
    later_rounds = [r for r in record.get("rounds", []) if r.get("round", 1) >= 2]
    if not later_rounds:
        return 0.0
    responsive = sum(1 for r in later_rounds if r.get("claims_attacked"))
    return responsive / len(later_rounds)


def extract_position_movement(record: dict) -> tuple[bool, bool]:
    """From final_position_movement. Returns (publius_moved, brutus_moved).

    "no movement", "converged in round 1", or empty/None -> False.
    """
    pub_movement = record.get("publius_final", {}).get("final_position_movement", "") or ""
    bru_movement = record.get("brutus_final", {}).get("final_position_movement", "") or ""

    no_move_phrases = {"no movement", "converged in round 1", ""}

    pub_moved = pub_movement.lower().strip() not in no_move_phrases
    bru_moved = bru_movement.lower().strip() not in no_move_phrases

    return pub_moved, bru_moved


def run_hoop_tests(record: dict) -> HoopTestResults:
    """Three process-tracing hoop tests for genuine deliberation."""
    pub_moved, bru_moved = extract_position_movement(record)
    position_shift = pub_moved or bru_moved

    later_rounds = [r for r in record.get("rounds", []) if r.get("round", 1) >= 2]
    argument_tracing = any(r.get("claims_attacked") for r in later_rounds)

    counterfactual_divergence = False
    for rnd in later_rounds:
        for cond in rnd.get("update_conditions_checked", []):
            if cond.get("met", False):
                counterfactual_divergence = True
                break
        if counterfactual_divergence:
            break

    return HoopTestResults(
        position_shift=position_shift,
        argument_tracing=argument_tracing,
        counterfactual_divergence=counterfactual_divergence,
    )


def _is_pseudo_deliberation(metrics: DeliberationMetrics) -> bool:
    """A pseudo-deliberation fails all three hoop tests despite multiple rounds."""
    if metrics.total_rounds <= 1:
        return False
    ht = metrics.hoop_tests
    if ht is None:
        return False
    return not ht.position_shift and not ht.argument_tracing and not ht.counterfactual_divergence


# ── Entry point ──────────────────────────────────────────────────────────────


def extract_metrics(record: dict) -> DeliberationMetrics:
    """Pure function: extract all metrics from a deliberation record."""
    delib_id = record.get("id", "unknown")
    metadata = record.get("process_metadata", {})

    activation_overall, activation_pub, activation_bru = extract_activation_rate(record)
    total_conc, pub_conc, bru_conc = extract_concession_counts(record)
    asymmetry = compute_concession_asymmetry(pub_conc, bru_conc)
    ref_rate = extract_responsive_reference_rate(record)
    pub_moved, bru_moved = extract_position_movement(record)
    hoop = run_hoop_tests(record)

    m = DeliberationMetrics(
        deliberation_id=delib_id,
        timestamp=datetime.now(UTC).isoformat(),
        activation_rate=activation_overall,
        activation_rate_publius=activation_pub,
        activation_rate_brutus=activation_bru,
        concession_count=total_conc,
        concession_count_publius=pub_conc,
        concession_count_brutus=bru_conc,
        concession_asymmetry_ratio=asymmetry,
        responsive_reference_rate=ref_rate,
        position_movement_publius=pub_moved,
        position_movement_brutus=bru_moved,
        termination_type=metadata.get("termination", "unknown"),
        total_rounds=metadata.get("total_rounds", 0),
        hoop_tests=hoop,
    )
    m.is_pseudo_deliberation = _is_pseudo_deliberation(m)

    return m


# ── JSONL I/O ────────────────────────────────────────────────────────────────


def _metrics_to_dict(m: DeliberationMetrics) -> dict:
    """Serialize metrics to a JSON-compatible dict."""
    d = {
        "deliberation_id": m.deliberation_id,
        "timestamp": m.timestamp,
        "activation_rate": m.activation_rate,
        "activation_rate_publius": m.activation_rate_publius,
        "activation_rate_brutus": m.activation_rate_brutus,
        "concession_count": m.concession_count,
        "concession_count_publius": m.concession_count_publius,
        "concession_count_brutus": m.concession_count_brutus,
        "concession_asymmetry_ratio": m.concession_asymmetry_ratio,
        "responsive_reference_rate": m.responsive_reference_rate,
        "position_movement_publius": m.position_movement_publius,
        "position_movement_brutus": m.position_movement_brutus,
        "termination_type": m.termination_type,
        "total_rounds": m.total_rounds,
        "is_pseudo_deliberation": m.is_pseudo_deliberation,
    }
    if m.hoop_tests:
        d["hoop_tests"] = {
            "position_shift": m.hoop_tests.position_shift,
            "argument_tracing": m.hoop_tests.argument_tracing,
            "counterfactual_divergence": m.hoop_tests.counterfactual_divergence,
        }
    return d


def _dict_to_metrics(d: dict) -> DeliberationMetrics:
    """Deserialize a dict to DeliberationMetrics."""
    ht_data = d.get("hoop_tests")
    hoop = HoopTestResults(**ht_data) if ht_data else None
    return DeliberationMetrics(
        deliberation_id=d["deliberation_id"],
        timestamp=d.get("timestamp", ""),
        activation_rate=d.get("activation_rate", 0.0),
        activation_rate_publius=d.get("activation_rate_publius", 0.0),
        activation_rate_brutus=d.get("activation_rate_brutus", 0.0),
        concession_count=d.get("concession_count", 0),
        concession_count_publius=d.get("concession_count_publius", 0),
        concession_count_brutus=d.get("concession_count_brutus", 0),
        concession_asymmetry_ratio=d.get("concession_asymmetry_ratio", 1.0),
        responsive_reference_rate=d.get("responsive_reference_rate", 0.0),
        position_movement_publius=d.get("position_movement_publius", False),
        position_movement_brutus=d.get("position_movement_brutus", False),
        termination_type=d.get("termination_type", "unknown"),
        total_rounds=d.get("total_rounds", 0),
        hoop_tests=hoop,
        is_pseudo_deliberation=d.get("is_pseudo_deliberation", False),
    )


def append_metrics(m: DeliberationMetrics, path: Path | None = None) -> None:
    """Append one metrics record as a JSON line."""
    import json

    p = path or EVAL_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(_metrics_to_dict(m)) + "\n")


def read_recent_metrics(path: Path | None = None, n: int = 20) -> list[DeliberationMetrics]:
    """Tail-read the last n metrics from JSONL."""
    import json

    p = path or EVAL_FILE
    if not p.exists():
        return []
    lines = p.read_text().strip().splitlines()
    recent = lines[-n:] if len(lines) > n else lines
    results = []
    for line in recent:
        line = line.strip()
        if not line:
            continue
        try:
            results.append(_dict_to_metrics(json.loads(line)))
        except Exception:
            continue
    return results


# ── Batch extraction ─────────────────────────────────────────────────────────


def extract_batch(
    directory: Path,
    output_path: Path | None = None,
    pattern: str = "*.yaml",
) -> list[DeliberationMetrics]:
    """Extract metrics from all matching YAMLs. Appends to JSONL if output_path given."""
    import sys

    import yaml

    results: list[DeliberationMetrics] = []
    for path in sorted(directory.glob(pattern)):
        try:
            with open(path) as f:
                record = yaml.safe_load(f)
            if not record or "id" not in record:
                continue
            m = extract_metrics(record)
            results.append(m)
            if output_path is not None:
                append_metrics(m, output_path)
        except Exception as e:
            print(f"  WARN: skipping {path.name}: {e}", file=sys.stderr)

    return results


# ── Display ──────────────────────────────────────────────────────────────────


def format_batch_summary(metrics_list: list[DeliberationMetrics]) -> str:
    """Human-readable summary."""
    if not metrics_list:
        return "No deliberation metrics to summarize."

    lines = [
        f"{'=' * 60}",
        f"DELIBERATION METRICS — {len(metrics_list)} record(s)",
        f"{'=' * 60}",
    ]

    for m in metrics_list:
        ht = m.hoop_tests
        hoop_str = "-/-/-"
        if ht:
            hoop_str = "/".join(
                [
                    "P" if ht.position_shift else "-",
                    "A" if ht.argument_tracing else "-",
                    "C" if ht.counterfactual_divergence else "-",
                ]
            )
        pseudo = " [PSEUDO]" if m.is_pseudo_deliberation else ""
        lines.append(
            f"  {m.deliberation_id}: "
            f"act={m.activation_rate:.0%}, conc={m.concession_count}, "
            f"hoops={hoop_str}, rounds={m.total_rounds}{pseudo}"
        )

    return "\n".join(lines)
