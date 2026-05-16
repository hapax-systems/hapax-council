"""Research artifact taxonomy and frontmatter validation.

Defines artifact classes, required/recommended frontmatter fields per class,
and a validator that checks documents against the taxonomy. Part of the
research artifact document pipeline (REQ-DOCPIPE-002/003).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from shared.frontmatter import parse_frontmatter


class ArtifactClass(StrEnum):
    RESEARCH = "research"
    SPEC = "spec"
    AUDIT = "audit"
    PLAN = "plan"
    RECEIPT = "receipt"
    BRIEF = "brief"
    UNKNOWN = "unknown"


class DispositionState(StrEnum):
    PROMOTED = "promoted"
    RECEIPT_ONLY = "receipt_only"
    NEEDS_NORMALIZATION = "needs_normalization"
    SUPERSEDED = "superseded"
    REFUSED = "refused"
    EXPIRED = "expired"
    DEBT_RECORDED = "debt_recorded"
    UNCLASSIFIED = "unclassified"


REQUIRED_FIELDS: dict[ArtifactClass, frozenset[str]] = {
    ArtifactClass.SPEC: frozenset({"Status", "Date", "Scope"}),
    ArtifactClass.RESEARCH: frozenset({"Date"}),
    ArtifactClass.AUDIT: frozenset({"Date"}),
    ArtifactClass.PLAN: frozenset({"Status", "Date"}),
    ArtifactClass.RECEIPT: frozenset({"Date"}),
    ArtifactClass.BRIEF: frozenset({"Date"}),
    ArtifactClass.UNKNOWN: frozenset(),
}

RECOMMENDED_FIELDS: dict[ArtifactClass, frozenset[str]] = {
    ArtifactClass.SPEC: frozenset({"Task", "Non-scope"}),
    ArtifactClass.RESEARCH: frozenset({"Scope", "Task"}),
    ArtifactClass.AUDIT: frozenset({"Scope", "Task"}),
    ArtifactClass.PLAN: frozenset({"Task"}),
    ArtifactClass.RECEIPT: frozenset(),
    ArtifactClass.BRIEF: frozenset({"Task"}),
    ArtifactClass.UNKNOWN: frozenset(),
}


def infer_artifact_class(path: Path) -> ArtifactClass:
    """Infer artifact class from file path."""
    parts = path.parts
    name = path.name.lower()

    if "specs" in parts or "spec" in name:
        return ArtifactClass.SPEC
    if "plans" in parts or "plan" in name:
        return ArtifactClass.PLAN
    if "audits" in parts or "audit" in name:
        return ArtifactClass.AUDIT
    if "refusal-briefs" in parts or "brief" in name:
        return ArtifactClass.BRIEF
    if "research" in parts:
        return ArtifactClass.RESEARCH
    if "receipt" in name or "relay" in parts:
        return ArtifactClass.RECEIPT
    return ArtifactClass.UNKNOWN


@dataclass(frozen=True)
class ValidationResult:
    path: str
    artifact_class: ArtifactClass
    missing_required: tuple[str, ...]
    missing_recommended: tuple[str, ...]
    has_frontmatter: bool

    @property
    def valid(self) -> bool:
        return len(self.missing_required) == 0 and self.has_frontmatter


def validate_artifact(path: Path, artifact_class: ArtifactClass | None = None) -> ValidationResult:
    """Validate a research artifact's frontmatter against taxonomy requirements."""
    if artifact_class is None:
        artifact_class = infer_artifact_class(path)

    try:
        fm, _ = parse_frontmatter(path)
    except Exception:
        return ValidationResult(
            path=str(path),
            artifact_class=artifact_class,
            missing_required=tuple(sorted(REQUIRED_FIELDS.get(artifact_class, frozenset()))),
            missing_recommended=tuple(sorted(RECOMMENDED_FIELDS.get(artifact_class, frozenset()))),
            has_frontmatter=False,
        )

    fm_keys = {k.strip() for k in fm}
    fm_keys_lower = {k.lower() for k in fm_keys}

    required = REQUIRED_FIELDS.get(artifact_class, frozenset())
    recommended = RECOMMENDED_FIELDS.get(artifact_class, frozenset())

    missing_req = tuple(sorted(f for f in required if f.lower() not in fm_keys_lower))
    missing_rec = tuple(sorted(f for f in recommended if f.lower() not in fm_keys_lower))

    return ValidationResult(
        path=str(path),
        artifact_class=artifact_class,
        missing_required=missing_req,
        missing_recommended=missing_rec,
        has_frontmatter=bool(fm),
    )
