"""Governance observability — metrics for a principality.

Observes the consent/authority system as a socioeconomic structure:
principals, contracts, information flows, costs, and lifecycle events.

The key abstraction is the Governance Heartbeat: a single 0.0-1.0
score answering "Is the principality well-governed right now?"

All metrics are aggregate (counts, rates, percentages) — never
individual data points. This is homomorphic observation: observing
properties of governed data without accessing the governed data.

Feeds: logos API, context restoration, briefing agent.
Literature: Ostrom IAD framework (monitoring principle),
Myers & Liskov DLM (label inspection), mechanism design (participation).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

PROFILES_DIR = Path.home() / "projects" / "hapax-council" / "profiles"
CONTRACTS_DIR = Path.home() / "projects" / "hapax-council" / "axioms" / "contracts"
CONSENT_AUDIT = PROFILES_DIR / ".consent-audit.jsonl"


# ── Data structures ─────────────────────────────────────────────────


@dataclass
class ConsentCoverage:
    """Per-principal and aggregate consent coverage."""

    total_contracts: int = 0
    active_contracts: int = 0
    persons_covered: list[str] = field(default_factory=list)
    scope_coverage: dict[str, int] = field(default_factory=dict)  # category → contract count
    qdrant_labeled: int = 0
    qdrant_total: int = 0
    coverage_pct: float = 0.0


@dataclass
class BlastRadius:
    """Revocation impact for a principal."""

    person_id: str = ""
    contract_ids: list[str] = field(default_factory=list)
    qdrant_points: int = 0
    carrier_facts: int = 0
    total_items: int = 0


@dataclass
class AuthorityUtilization:
    """Per-agent authority delegation vs exercise."""

    agent_id: str = ""
    delegated_scope: list[str] = field(default_factory=list)
    axiom_bindings: int = 0
    governor_denials: int = 0


@dataclass
class ConsentLifecycle:
    """Temporal metrics for consent activity."""

    total_gate_decisions: int = 0
    allowed: int = 0
    denied: int = 0
    denial_rate: float = 0.0
    stale_contracts: int = 0  # active but not exercised recently
    recent_events: list[dict] = field(default_factory=list)


@dataclass
class CarrierFlowMetrics:
    """Cross-domain information exchange metrics."""

    total_carriers: int = 0
    domains_connected: int = 0
    total_observations: int = 0
    contradictions_detected: int = 0


@dataclass
class GovernanceHeartbeat:
    """The single score: is the principality well-governed?

    0.0 = critical governance failures
    0.5 = gaps exist, attention needed
    0.8 = healthy governance
    1.0 = perfect (unlikely in practice)
    """

    score: float = 0.0
    label: str = "unknown"  # "green" | "yellow" | "red"
    components: dict[str, float] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    coverage: ConsentCoverage | None = None
    lifecycle: ConsentLifecycle | None = None
    timestamp: str = ""


# ── Collectors ───────────────────────────────────────────────────────


def collect_consent_coverage() -> ConsentCoverage:
    """Measure consent coverage across the principality."""
    coverage = ConsentCoverage()

    # Load contracts from disk
    try:
        from shared.governance.consent import load_contracts

        registry = load_contracts()
        coverage.total_contracts = len(registry._contracts)
        coverage.active_contracts = len(registry.active_contracts)

        persons: set[str] = set()
        scope_counts: dict[str, int] = {}
        for contract in registry.active_contracts:
            for party in contract.parties:
                if party != "operator":
                    persons.add(party)
            for cat in contract.scope:
                scope_counts[cat] = scope_counts.get(cat, 0) + 1

        coverage.persons_covered = sorted(persons)
        coverage.scope_coverage = scope_counts
    except Exception:
        log.debug("Failed to load consent contracts", exc_info=True)

    # Qdrant coverage
    try:
        from shared.config import get_qdrant

        client = get_qdrant()
        coverage.qdrant_total = client.count(collection_name="documents").count

        from qdrant_client.models import FieldCondition, Filter, MatchExcept

        coverage.qdrant_labeled = client.count(
            collection_name="documents",
            count_filter=Filter(
                must=[FieldCondition(key="consent_label", match=MatchExcept(except_=[]))]
            ),
        ).count
    except Exception:
        log.debug("Failed to query Qdrant coverage", exc_info=True)

    if coverage.qdrant_total > 0:
        coverage.coverage_pct = round(coverage.qdrant_labeled / coverage.qdrant_total * 100, 1)

    return coverage


def collect_revocation_blast_radius(person_id: str) -> BlastRadius:
    """Precompute what would be purged if a person revokes."""
    blast = BlastRadius(person_id=person_id)

    try:
        from shared.governance.consent import load_contracts

        registry = load_contracts()
        contracts = [
            c
            for c in registry.active_contracts
            if person_id in c.parties and person_id != "operator"
        ]
        blast.contract_ids = [c.id for c in contracts]
    except Exception:
        return blast

    # Qdrant impact
    for cid in blast.contract_ids:
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            from shared.config import get_qdrant

            client = get_qdrant()
            count = client.count(
                collection_name="documents",
                count_filter=Filter(
                    must=[FieldCondition(key="provenance", match=MatchValue(value=cid))]
                ),
            ).count
            blast.qdrant_points += count
        except Exception:
            pass

    # Carrier facts impact
    try:
        from logos.engine.reactive_rules import get_carrier_registry

        carrier = get_carrier_registry()
        for principal_id in list(carrier._capacities.keys()):
            for fact in carrier.facts(principal_id):
                if any(cid in fact.labeled.provenance for cid in blast.contract_ids):
                    blast.carrier_facts += 1
    except Exception:
        pass

    blast.total_items = blast.qdrant_points + blast.carrier_facts
    return blast


def collect_consent_lifecycle() -> ConsentLifecycle:
    """Temporal metrics from the consent gate audit log."""
    lifecycle = ConsentLifecycle()

    if not CONSENT_AUDIT.exists():
        return lifecycle

    try:
        events = []
        for line in CONSENT_AUDIT.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        lifecycle.total_gate_decisions = len(events)
        lifecycle.allowed = sum(1 for e in events if e.get("allowed"))
        lifecycle.denied = sum(1 for e in events if not e.get("allowed"))
        if lifecycle.total_gate_decisions > 0:
            lifecycle.denial_rate = round(
                lifecycle.denied / lifecycle.total_gate_decisions * 100, 1
            )

        # Last 10 events for timeline view
        lifecycle.recent_events = events[-10:]
    except Exception:
        log.debug("Failed to read consent audit log", exc_info=True)

    # Stale contracts (active but created > 30 days ago with no recent gate activity)
    try:
        from shared.governance.consent import load_contracts

        registry = load_contracts()
        now = datetime.now(UTC)
        for contract in registry.active_contracts:
            try:
                created = datetime.fromisoformat(contract.created_at.replace("Z", "+00:00"))
                age_days = (now - created).days
                if age_days > 30:
                    lifecycle.stale_contracts += 1
            except (ValueError, TypeError):
                pass
    except Exception:
        pass

    return lifecycle


def collect_authority_utilization() -> list[AuthorityUtilization]:
    """Per-agent authority delegation metrics from manifests."""
    agents: list[AuthorityUtilization] = []

    try:
        from shared.agent_registry import get_registry

        registry = get_registry()

        for manifest in registry.list_agents():
            util = AuthorityUtilization(
                agent_id=manifest.id,
                axiom_bindings=len(manifest.axiom_bindings),
            )
            for binding in manifest.axiom_bindings:
                for impl in binding.implications:
                    util.delegated_scope.append(impl)
            agents.append(util)
    except Exception:
        log.debug("Failed to load agent manifests", exc_info=True)

    return agents


def collect_carrier_flow() -> CarrierFlowMetrics:
    """Cross-domain carrier fact metrics."""
    metrics = CarrierFlowMetrics()

    try:
        from logos.engine.reactive_rules import get_carrier_registry

        carrier = get_carrier_registry()
        domains: set[str] = set()
        for principal_id in list(carrier._capacities.keys()):
            facts = carrier.facts(principal_id)
            metrics.total_carriers += len(facts)
            for fact in facts:
                domains.add(fact.source_domain)
                metrics.total_observations += fact.observation_count
        metrics.domains_connected = len(domains)
    except Exception:
        pass

    # Contradiction count from detector
    try:
        from agents.contradiction_detector import detect_contradictions

        contradictions = detect_contradictions()
        metrics.contradictions_detected = len(contradictions)
    except Exception:
        pass

    return metrics


# ── Heartbeat ────────────────────────────────────────────────────────


def collect_governance_heartbeat() -> GovernanceHeartbeat:
    """The single governance health score.

    Components (weighted):
    - consent_coverage (0.3): are persons covered by contracts?
    - gate_health (0.3): is the gate operational and not over-denying?
    - contract_freshness (0.2): are contracts active and not stale?
    - authority_health (0.2): are agents properly scoped?

    Score semantics:
    - >= 0.8: green (healthy governance)
    - 0.5 - 0.8: yellow (attention needed)
    - < 0.5: red (governance failures)
    """
    coverage = collect_consent_coverage()
    lifecycle = collect_consent_lifecycle()

    components: dict[str, float] = {}
    issues: list[str] = []

    # 1. Consent coverage score
    if coverage.active_contracts > 0:
        components["consent_coverage"] = 1.0
    elif coverage.total_contracts > 0:
        components["consent_coverage"] = 0.5
        issues.append("All contracts are revoked or inactive")
    else:
        # No contracts needed if no person-adjacent data detected
        components["consent_coverage"] = 0.8  # neutral — no violations either
        issues.append("No consent contracts exist (none may be needed yet)")

    # 2. Gate health
    if lifecycle.total_gate_decisions == 0:
        components["gate_health"] = 0.8  # neutral — gate not yet exercised
    elif lifecycle.denial_rate > 50:
        components["gate_health"] = 0.3
        issues.append(f"High gate denial rate: {lifecycle.denial_rate}%")
    elif lifecycle.denial_rate > 20:
        components["gate_health"] = 0.6
        issues.append(f"Elevated gate denial rate: {lifecycle.denial_rate}%")
    else:
        components["gate_health"] = 1.0

    # 3. Contract freshness
    if lifecycle.stale_contracts > 0:
        components["contract_freshness"] = max(0.3, 1.0 - (lifecycle.stale_contracts * 0.2))
        issues.append(f"{lifecycle.stale_contracts} stale consent contract(s)")
    else:
        components["contract_freshness"] = 1.0

    # 4. Authority health (basic: do agents have manifests?)
    try:
        agents = collect_authority_utilization()
        if agents:
            components["authority_health"] = 1.0
        else:
            components["authority_health"] = 0.5
            issues.append("No agent manifests loaded")
    except Exception:
        components["authority_health"] = 0.5

    # 5. Historical data audit status
    try:
        audit_report = PROFILES_DIR / "consent-audit-report.json"
        if audit_report.exists():
            audit = json.loads(audit_report.read_text())
            flagged = audit.get("flagged", 0)
            if flagged > 0:
                components["historical_audit"] = max(0.2, 1.0 - (flagged * 0.1))
                issues.append(f"{flagged} historical document(s) flagged for consent review")
            else:
                components["historical_audit"] = 1.0
        else:
            components["historical_audit"] = 0.6
            issues.append(
                "No consent audit has been run (use: uv run python -m agents.consent_audit --scan --report)"
            )
    except Exception:
        components["historical_audit"] = 0.5

    # Composite score (weighted average)
    weights = {
        "consent_coverage": 0.25,
        "gate_health": 0.25,
        "contract_freshness": 0.15,
        "authority_health": 0.15,
        "historical_audit": 0.2,
    }
    score = sum(components.get(k, 0) * w for k, w in weights.items())
    score = round(min(1.0, max(0.0, score)), 2)

    if score >= 0.8:
        label = "green"
    elif score >= 0.5:
        label = "yellow"
    else:
        label = "red"

    return GovernanceHeartbeat(
        score=score,
        label=label,
        components=components,
        issues=issues,
        coverage=coverage,
        lifecycle=lifecycle,
        timestamp=datetime.now(UTC).isoformat(),
    )
