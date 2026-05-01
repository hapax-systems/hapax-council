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

AXIOMS_PATH: Path = Path(
    os.environ.get(
        "AXIOMS_PATH",
        str(Path(__file__).resolve().parent.parent / "axioms"),
    )
)


@dataclass(frozen=True)
class SchemaVer:
    """Schema version using SchemaVer convention: MODEL-REVISION-ADDITION.

    MODEL: breaking change. REVISION: backward-compatible change.
    ADDITION: new optional fields.
    """

    model: int
    revision: int
    addition: int

    def __str__(self) -> str:
        return f"{self.model}-{self.revision}-{self.addition}"

    @classmethod
    def parse(cls, version_str: str) -> SchemaVer:
        """Parse a SchemaVer string like '1-0-0'."""
        parts = version_str.strip().split("-")
        if len(parts) != 3:
            raise ValueError(
                f"Invalid SchemaVer: {version_str!r} (expected MODEL-REVISION-ADDITION)"
            )
        try:
            return cls(model=int(parts[0]), revision=int(parts[1]), addition=int(parts[2]))
        except ValueError as e:
            raise ValueError(f"Invalid SchemaVer components: {version_str!r}") from e


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
class ImplicationScope:
    """E-1: Enumerable scope definition for sufficiency-mode implications."""

    type: str = ""  # "derived" | "enumerated" | "pattern"
    rule: str = ""  # Human-readable scope rule
    items: list[str] | None = None  # Enumerated items (for type="enumerated")


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
    scope: ImplicationScope | None = None  # E-1: optional scope for sufficiency implications


@dataclass(frozen=True)
class Precedent:
    """One axiom-anchored precedent.

    Mirrors the shape of :class:`Implication` for callers that want to
    enumerate the operator-ratified case law backing an axiom's
    enforcement decisions.

    Attributes:
        id: Stable precedent identifier (``sp-XXX-NNN`` form).
        axiom_id: Parent axiom whose enforcement this precedent backs.
        situation: One-paragraph description of the situation that
            motivated the precedent.
        decision: Short label — typically ``"compliant"``,
            ``"non-compliant"``, ``"compliant-with-conditions"``.
        reasoning: Free-form rationale for the decision.
        tier: Optional enforcement tier the precedent applies to
            (T0 / T1 / T2 / T3 / empty).
        created: ISO date the precedent was ratified.
        authority: Who ratified — typically ``"operator"``.
        secondary_axioms: Other axioms the precedent partially backs.
        distinguishing_facts: Facts that make this precedent's holding
            specific (so future cases can be distinguished).
    """

    id: str
    axiom_id: str
    situation: str = ""
    decision: str = ""
    reasoning: str = ""
    tier: str = ""
    created: str = ""
    authority: str = ""
    secondary_axioms: tuple[str, ...] = ()
    distinguishing_facts: tuple[str, ...] = ()


def load_schema_version(*, path: Path = AXIOMS_PATH) -> SchemaVer | None:
    """Load the schema_version from registry.yaml. Returns None if not present."""
    registry_file = path / "registry.yaml"
    if not registry_file.exists():
        return None
    try:
        data = yaml.safe_load(registry_file.read_text())
    except Exception:
        return None
    sv = data.get("schema_version")
    if sv is None:
        return None
    return SchemaVer.parse(str(sv))


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
        scope_data = entry.get("scope")
        scope = None
        if scope_data and isinstance(scope_data, dict):
            items_raw = scope_data.get("items")
            items = list(items_raw) if items_raw and isinstance(items_raw, list) else None
            scope = ImplicationScope(
                type=scope_data.get("type", ""),
                rule=scope_data.get("rule", ""),
                items=items,
            )
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
                scope=scope,
            )
        )

    return impls


def _build_precedent(entry: dict, *, default_axiom_id: str) -> Precedent:
    """Build a :class:`Precedent` from a parsed YAML mapping.

    Accepts both the list-schema row shape (``id``, ``axiom_id``
    optional + inherited from parent doc) and the standalone-doc
    shape (``precedent_id`` at root + ``axiom_id`` carries parent).
    Caller pre-normalizes ``id`` before invoking; ``default_axiom_id``
    is the fallback when the entry omits ``axiom_id``.
    """
    secondary_raw = entry.get("secondary_axioms") or ()
    distinguishing_raw = entry.get("distinguishing_facts") or ()
    return Precedent(
        id=entry["id"],
        axiom_id=entry.get("axiom_id", default_axiom_id),
        situation=str(entry.get("situation", "")).strip(),
        decision=str(entry.get("decision", "")).strip(),
        reasoning=str(entry.get("reasoning", "")).strip(),
        tier=str(entry.get("tier", "")).strip(),
        created=str(entry.get("created", "")).strip(),
        authority=str(entry.get("authority", "")).strip(),
        secondary_axioms=tuple(str(s) for s in secondary_raw),
        distinguishing_facts=tuple(str(s) for s in distinguishing_raw),
    )


def _load_list_schema_precedents(precedent_file: Path) -> list[Precedent]:
    """Load list-schema precedents from a seed file.

    File shape: ``precedents:`` list of per-precedent rows. Each row's
    ``axiom_id`` is required (rows in the same file may target
    different axioms — the seed files are organized by topic, not
    by parent axiom).
    """
    try:
        data = yaml.safe_load(precedent_file.read_text())
    except Exception as e:  # pragma: no cover
        log.error("Failed to parse precedent file %s: %s", precedent_file, e)
        return []
    if not isinstance(data, dict):
        return []
    out: list[Precedent] = []
    for entry in data.get("precedents", []) or []:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        # Each row must declare its own axiom_id; no parent fallback.
        axiom_id = entry.get("axiom_id")
        if not axiom_id:
            continue
        out.append(_build_precedent(entry, default_axiom_id=axiom_id))
    return out


def _load_standalone_schema_precedent(precedent_file: Path) -> Precedent | None:
    """Load a single-document standalone-schema precedent file.

    File shape: ``precedent_id:`` at root + ``axiom_id`` + fields.
    Returns ``None`` for list-schema files (which lack
    ``precedent_id``) or malformed YAML.
    """
    try:
        data = yaml.safe_load(precedent_file.read_text())
    except Exception as e:  # pragma: no cover
        log.error("Failed to parse standalone precedent %s: %s", precedent_file, e)
        return None
    if not isinstance(data, dict):
        return None
    pid = data.get("precedent_id")
    axiom_id = data.get("axiom_id")
    if not pid or not axiom_id:
        return None
    entry = {**data, "id": pid}
    return _build_precedent(entry, default_axiom_id=axiom_id)


def load_precedents(axiom_id: str, *, path: Path = AXIOMS_PATH) -> list[Precedent]:
    """Load precedents that anchor a specific axiom's enforcement.

    Discovers two file shapes under ``axioms/precedents/``:

    1. **List schema (seed files)** — ``axioms/precedents/seed/*.yaml``
       with a top-level ``precedents:`` list. Rows declare their own
       ``axiom_id`` (a single seed file may carry rows for multiple
       axioms organized by topic).
    2. **Standalone schema** — ``axioms/precedents/<sp-id>.yaml``
       with a top-level ``precedent_id`` flat document.

    Returns the merged list filtered by the requested ``axiom_id``.
    """
    precedents_dir = path / "precedents"
    if not precedents_dir.is_dir():
        return []

    out: list[Precedent] = []

    # 1. Seed files (list-schema).
    seed_dir = precedents_dir / "seed"
    if seed_dir.is_dir():
        for seed_file in sorted(seed_dir.glob("*.yaml")):
            for prec in _load_list_schema_precedents(seed_file):
                if prec.axiom_id == axiom_id:
                    out.append(prec)

    # 2. Standalone files at the precedents/ root.
    for candidate in sorted(precedents_dir.glob("*.yaml")):
        standalone = _load_standalone_schema_precedent(candidate)
        if standalone is not None and standalone.axiom_id == axiom_id:
            out.append(standalone)

    return out


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
