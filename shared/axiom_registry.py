# shared/axiom_registry.py
"""Load axiom definitions from hapaxromana registry.

Reads YAML axiom definitions and derived implications from the hapaxromana
axioms directory. Used by enforcement modules to access axiom text, weights,
and concrete implications.

Usage:
    from shared.axiom_registry import load_axioms, get_axiom, load_implications, validate_supremacy

    axioms = load_axioms()  # All active axioms
    axiom = get_axiom("single_user")
    implications = load_implications("single_user")
    constitutional = load_axioms(scope="constitutional")
    domain = load_axioms(scope="domain", domain="management")
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

from shared.config import HAPAXROMANA_DIR

AXIOMS_PATH: Path = Path(
    os.environ.get(
        "AXIOMS_PATH",
        str(HAPAXROMANA_DIR / "axioms"),
    )
)


@dataclass
class Axiom:
    id: str
    text: str
    weight: int
    type: str  # "hardcoded" | "softcoded"
    created: str
    status: str  # "active" | "retired"
    supersedes: str | None = None
    scope: str = "constitutional"  # "constitutional" | "domain"
    domain: str | None = None  # None for constitutional, "management" | "music" etc.


@dataclass
class Implication:
    id: str
    axiom_id: str
    tier: str  # "T0" | "T1" | "T2" | "T3"
    text: str
    enforcement: str  # "block" | "review" | "warn" | "lint"
    canon: str  # interpretive strategy used
    mode: str = "compatibility"  # "compatibility" | "sufficiency"
    level: str = "component"  # "component" | "subsystem" | "system"


def load_axioms(*, path: Path = AXIOMS_PATH, scope: str = "", domain: str = "") -> list[Axiom]:
    """Load active axioms from registry.yaml with optional filtering.

    Args:
        path: Axioms directory.
        scope: Filter by scope ("constitutional" or "domain"). Empty for all.
        domain: Filter by domain (e.g. "management"). Empty for all.
    """
    registry_file = path / "registry.yaml"
    if not registry_file.exists():
        log.warning("Axiom registry not found: %s", registry_file)
        return []

    try:
        data = yaml.safe_load(registry_file.read_text())
    except Exception as e:
        log.error("Failed to parse axiom registry: %s", e)
        return []

    axioms = []
    for entry in data.get("axioms", []):
        axiom = Axiom(
            id=entry["id"],
            text=entry.get("text", ""),
            weight=entry.get("weight", 50),
            type=entry.get("type", "softcoded"),
            created=entry.get("created", ""),
            status=entry.get("status", "active"),
            supersedes=entry.get("supersedes"),
            scope=entry.get("scope", "constitutional"),
            domain=entry.get("domain"),
        )
        if axiom.status != "active":
            continue
        if scope and axiom.scope != scope:
            continue
        if domain and axiom.domain != domain:
            continue
        axioms.append(axiom)

    return axioms


def get_axiom(axiom_id: str, *, path: Path = AXIOMS_PATH) -> Axiom | None:
    """Look up a single axiom by ID. Returns None if not found or not active."""
    for axiom in load_axioms(path=path):
        if axiom.id == axiom_id:
            return axiom
    return None


def load_implications(axiom_id: str, *, path: Path = AXIOMS_PATH) -> list[Implication]:
    """Load derived implications for a specific axiom."""
    impl_file = path / "implications" / f"{axiom_id.replace('_', '-')}.yaml"
    if not impl_file.exists():
        # Try with underscores
        impl_file = path / "implications" / f"{axiom_id}.yaml"
        if not impl_file.exists():
            return []

    try:
        data = yaml.safe_load(impl_file.read_text())
    except Exception as e:
        log.error("Failed to parse implications for %s: %s", axiom_id, e)
        return []

    impls = []
    for entry in data.get("implications", []):
        impls.append(
            Implication(
                id=entry["id"],
                axiom_id=data.get("axiom_id", axiom_id),
                tier=entry.get("tier", "T2"),
                text=entry.get("text", ""),
                enforcement=entry.get("enforcement", "warn"),
                canon=entry.get("canon", ""),
                mode=entry.get("mode", "compatibility"),
                level=entry.get("level", "component"),
            )
        )

    return impls


@dataclass
class SupremacyTension:
    """A pairing of domain vs constitutional T0 blocks that needs operator review."""

    domain_impl_id: str
    domain_impl_text: str
    constitutional_impl_id: str
    constitutional_impl_text: str
    note: str


def _get_reviewed_impl_ids() -> set[str]:
    """Return domain T0 impl IDs that have operator-authority precedents."""
    try:
        from shared.axiom_precedents import PrecedentStore

        store = PrecedentStore()
        # Scroll all operator-authority precedents
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        results = store.client.scroll(
            "axiom-precedents",
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="authority", match=MatchValue(value="operator")),
                    FieldCondition(key="tier", match=MatchValue(value="T0")),
                    FieldCondition(key="superseded_by", match=MatchValue(value="")),
                ]
            ),
            limit=100,
        )
        reviewed: set[str] = set()
        for point in results[0]:
            situation = point.payload.get("situation", "")
            # Extract impl ID from situation prefix (e.g., "mg-boundary-001: ...")
            if ":" in situation:
                impl_id = situation.split(":")[0].strip()
                reviewed.add(impl_id)
        return reviewed
    except Exception:
        return set()


def validate_supremacy(*, path: Path = AXIOMS_PATH) -> list[SupremacyTension]:
    """Check domain T0 blocks against constitutional T0 blocks for review.

    Returns pairings where a domain axiom has T0 blocks that operate in the
    same enforcement space as constitutional T0 blocks. The operator should
    record precedents acknowledging these — they're not violations, but
    structural overlaps that need explicit reasoning.

    Tensions with existing operator-authority precedents are filtered out.
    """
    constitutional = load_axioms(path=path, scope="constitutional")
    domain_axioms = load_axioms(path=path, scope="domain")

    if not domain_axioms:
        return []

    # Collect constitutional T0 blocks
    const_t0: list[Implication] = []
    for ax in constitutional:
        for impl in load_implications(ax.id, path=path):
            if impl.tier == "T0" and impl.enforcement == "block":
                const_t0.append(impl)

    if not const_t0:
        return []

    # Filter out already-reviewed tensions
    reviewed = _get_reviewed_impl_ids()

    tensions = []
    const_ids = [c.id for c in const_t0]
    for ax in domain_axioms:
        for impl in load_implications(ax.id, path=path):
            if impl.tier != "T0" or impl.enforcement != "block":
                continue
            if impl.id in reviewed:
                continue
            # One entry per domain T0 block — note constitutional T0 blocks exist
            tensions.append(
                SupremacyTension(
                    domain_impl_id=impl.id,
                    domain_impl_text=impl.text,
                    constitutional_impl_id=", ".join(const_ids),
                    constitutional_impl_text=f"{len(const_t0)} constitutional T0 block(s)",
                    note=f"Domain {impl.axiom_id} T0 block needs operator review against constitutional T0 blocks",
                )
            )

    return tensions
