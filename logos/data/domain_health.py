"""Domain health aggregator — combines sufficiency, momentum, emergence.

Single collector that produces a DomainHealthSnapshot suitable for
the logos sidebar or a dedicated dashboard widget.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from logos._config import VAULT_PATH


@dataclass
class DomainStatus:
    """Health status for a single domain."""

    domain_id: str
    domain_name: str
    status: str  # active | dormant | proposed | retired
    sufficiency_score: float  # 0.0 - 1.0
    total_requirements: int
    satisfied_count: int
    direction: str  # accelerating | steady | decelerating | dormant
    regularity: str  # regular | irregular | sporadic
    alignment: str  # improving | plateaued | regressing


@dataclass
class DomainHealthSnapshot:
    """Aggregated domain health across all domains."""

    domains: list[DomainStatus]
    overall_score: float  # activity-weighted average
    emergence_candidate_count: int
    computed_at: str


def collect_domain_health(
    vault_path: Path | None = None,
) -> DomainHealthSnapshot:
    """Aggregate domain sufficiency, momentum, and emergence into one snapshot."""
    now_iso = datetime.now(UTC).isoformat()[:19] + "Z"
    vp = vault_path or VAULT_PATH

    # Load domain registry for names and statuses
    try:
        from logos.data.knowledge_sufficiency import (
            DOMAIN_REGISTRY_PATH,
            collect_all_domain_gaps,
            load_domain_registry,
        )

        if not DOMAIN_REGISTRY_PATH.is_file():
            return DomainHealthSnapshot(
                domains=[],
                overall_score=1.0,
                emergence_candidate_count=0,
                computed_at=now_iso,
            )
        registry = load_domain_registry()
    except Exception:
        return DomainHealthSnapshot(
            domains=[],
            overall_score=1.0,
            emergence_candidate_count=0,
            computed_at=now_iso,
        )

    # Sufficiency reports
    reports = collect_all_domain_gaps(vault_path=vp)

    # Momentum vectors
    momentum_map: dict[str, tuple[str, str, str]] = {}
    try:
        from logos.data.momentum import collect_domain_momentum

        momentum = collect_domain_momentum(vault_path=vp)
        for v in momentum.vectors:
            momentum_map[v.domain_id] = (v.direction, v.regularity, v.alignment)
    except Exception:
        pass

    # Emergence candidates
    emergence_count = 0
    try:
        from logos.data.emergence import collect_emergence

        emergence = collect_emergence(vault_path=vp)
        emergence_count = len(emergence.candidates)
    except Exception:
        pass

    # Build domain statuses
    domain_lookup = {d["id"]: d for d in registry.get("domains", [])}
    statuses: list[DomainStatus] = []

    for domain_id, domain_def in domain_lookup.items():
        report = reports.get(domain_id)
        direction, regularity, alignment = momentum_map.get(
            domain_id, ("steady", "sporadic", "plateaued")
        )

        statuses.append(
            DomainStatus(
                domain_id=domain_id,
                domain_name=domain_def.get("name", domain_id),
                status=domain_def.get("status", "active"),
                sufficiency_score=report.sufficiency_score if report else 0.0,
                total_requirements=report.total_requirements if report else 0,
                satisfied_count=report.satisfied_count if report else 0,
                direction=direction,
                regularity=regularity,
                alignment=alignment,
            )
        )

    # Overall score: weighted average by activity (active domains weight 1.0,
    # dormant weight 0.1, others weight 0.5)
    total_weight = 0.0
    weighted_sum = 0.0
    for s in statuses:
        weight = 1.0 if s.status == "active" else 0.1 if s.status == "dormant" else 0.5
        weighted_sum += s.sufficiency_score * weight
        total_weight += weight

    overall = weighted_sum / total_weight if total_weight > 0 else 1.0

    return DomainHealthSnapshot(
        domains=statuses,
        overall_score=round(overall, 3),
        emergence_candidate_count=emergence_count,
        computed_at=now_iso,
    )
