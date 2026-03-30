"""Deliberation governance sufficiency probes."""

from __future__ import annotations

from .sufficiency_probes import SufficiencyProbe


def _check_deliberation_hoop_tests() -> tuple[bool, str]:
    """Check that multi-round deliberations pass >= 2 of 3 hoop tests."""
    try:
        from shared.deliberation_metrics import read_recent_metrics
    except ImportError:
        return True, "deliberation_metrics not available (non-critical)"

    metrics = read_recent_metrics(n=20)
    multi_round = [m for m in metrics if m.total_rounds > 1]
    if not multi_round:
        return True, "no multi-round deliberations to evaluate"

    failing: list[str] = []
    for m in multi_round:
        ht = m.hoop_tests
        if ht is None:
            continue
        passes = sum([ht.position_shift, ht.argument_tracing, ht.counterfactual_divergence])
        if passes < 2:
            failing.append(m.deliberation_id)

    if not failing:
        return True, f"all {len(multi_round)} multi-round deliberations pass >= 2/3 hoop tests"
    return (
        False,
        f"{len(failing)}/{len(multi_round)} deliberations fail hoop tests: {', '.join(failing[:3])}",
    )


def _check_deliberation_activation_rate() -> tuple[bool, str]:
    """Check that multi-round deliberation activation rate exceeds 10%."""
    try:
        from shared.deliberation_metrics import read_recent_metrics
    except ImportError:
        return True, "deliberation_metrics not available (non-critical)"

    metrics = read_recent_metrics(n=20)
    multi_round = [m for m in metrics if m.total_rounds > 1]
    if not multi_round:
        return True, "no multi-round deliberations to evaluate"

    low_activation = [m for m in multi_round if m.activation_rate < 0.1]
    if not low_activation:
        mean_act = sum(m.activation_rate for m in multi_round) / len(multi_round)
        return True, f"mean activation rate {mean_act:.0%} across {len(multi_round)} deliberations"
    return (
        False,
        f"{len(low_activation)}/{len(multi_round)} deliberations have activation rate < 10%",
    )


def _check_deliberation_concession_asymmetry() -> tuple[bool, str]:
    """Check that concession asymmetry does not exceed 3.0x."""
    try:
        from shared.deliberation_metrics import read_recent_metrics
    except ImportError:
        return True, "deliberation_metrics not available (non-critical)"

    metrics = read_recent_metrics(n=20)
    with_concessions = [m for m in metrics if m.concession_count > 0]
    if not with_concessions:
        return True, "no deliberations with concessions to evaluate"

    mean_asym = sum(m.concession_asymmetry_ratio for m in with_concessions) / len(with_concessions)
    if mean_asym <= 3.0:
        return (
            True,
            f"mean concession asymmetry {mean_asym:.1f}x across {len(with_concessions)} deliberations",
        )

    pub_total = sum(m.concession_count_publius for m in with_concessions)
    bru_total = sum(m.concession_count_brutus for m in with_concessions)
    dominant = "publius" if pub_total > bru_total else "brutus"
    return (
        False,
        f"concession asymmetry {mean_asym:.1f}x -- {dominant} dominates ({max(pub_total, bru_total)}/{pub_total + bru_total})",
    )


def _check_deliberation_activation_trend() -> tuple[bool, str]:
    """Check activation rate trend is not declining across batches."""
    try:
        from shared.deliberation_metrics import read_recent_metrics
    except ImportError:
        return True, "deliberation_metrics not available (non-critical)"

    metrics = read_recent_metrics(n=20)
    multi_round = [m for m in metrics if m.total_rounds > 1]
    if len(multi_round) < 4:
        return (
            True,
            f"insufficient multi-round data for trend ({len(multi_round)} records, need 4+)",
        )

    mid = len(multi_round) // 2
    first_half = sum(m.activation_rate for m in multi_round[:mid]) / mid
    second_half = sum(m.activation_rate for m in multi_round[mid:]) / (len(multi_round) - mid)
    diff = second_half - first_half

    if diff >= -0.05:
        trend = "rising" if diff > 0.05 else "stable"
        return (
            True,
            f"activation trend {trend} ({first_half:.0%} -> {second_half:.0%}) across {len(multi_round)} deliberations",
        )
    return (
        False,
        f"activation trend falling ({first_half:.0%} -> {second_half:.0%}) across {len(multi_round)} deliberations",
    )


DELIBERATION_PROBES: list[SufficiencyProbe] = [
    SufficiencyProbe(
        id="probe-delib-001",
        axiom_id="executive_function",
        implication_id="ex-delib-001",
        level="system",
        question="Do multi-round deliberations pass >= 2 of 3 hoop tests?",
        check=_check_deliberation_hoop_tests,
    ),
    SufficiencyProbe(
        id="probe-delib-002",
        axiom_id="executive_function",
        implication_id="ex-delib-002",
        level="system",
        question="Does multi-round deliberation activation rate exceed 10%?",
        check=_check_deliberation_activation_rate,
    ),
    SufficiencyProbe(
        id="probe-delib-003",
        axiom_id="executive_function",
        implication_id="ex-delib-003",
        level="system",
        question="Is concession asymmetry within acceptable bounds (< 3.0x)?",
        check=_check_deliberation_concession_asymmetry,
    ),
    SufficiencyProbe(
        id="probe-delib-004",
        axiom_id="executive_function",
        implication_id="ex-delib-004",
        level="system",
        question="Is deliberation activation rate trend not declining?",
        check=_check_deliberation_activation_trend,
    ),
]
