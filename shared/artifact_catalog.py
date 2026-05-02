"""Artifact catalog and release workflow.

Self-serve catalog for paid/free Hapax artifacts: methodology dossiers,
provenance kits, replay packs, Obsidian templates, Grafana dashboards,
axiom/refusal packages, dataset cards, and commercial-use bundles.

The catalog is machine-readable; downstream surfaces consume the
typed records to render catalog pages, generate release manifests,
and gate exports against anonymization/rights decisions.

cc-task: artifact-catalog-release-workflow (WSJF 8.7, P1).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArtifactStream(StrEnum):
    """Top-level catalog stream classification."""

    METHODOLOGY_DOSSIER = "methodology_dossier"
    PROVENANCE_KIT = "provenance_kit"
    REPLAY_PACK = "replay_pack"
    OBSIDIAN_TEMPLATE = "obsidian_template"
    GRAFANA_DASHBOARD = "grafana_dashboard"
    AXIOM_REFUSAL_PACKAGE = "axiom_refusal_package"
    DATASET_CARD = "dataset_card"
    COMMERCIAL_USE_BUNDLE = "commercial_use_bundle"


class RightsClass(StrEnum):
    """Rights posture for the artifact contents."""

    OPERATOR_OWNED = "operator_owned"
    PUBLIC_DOMAIN = "public_domain"
    LICENSED = "licensed"
    UNCLEARED = "uncleared"  # blocks export


class PrivacyClass(StrEnum):
    """Privacy classification for the artifact contents."""

    FULLY_PUBLIC = "fully_public"
    OPERATOR_ONLY = "operator_only"
    ANONYMIZED = "anonymized"
    UNANONYMIZED_PRIVATE = "unanonymized_private"  # blocks export


class LicenseClass(StrEnum):
    """License under which the artifact is published."""

    CC_BY = "cc_by"
    CC_BY_SA = "cc_by_sa"
    CC0 = "cc0"
    CUSTOM_COMMERCIAL = "custom_commercial"
    OPERATOR_RESERVED = "operator_reserved"


class PriceClass(StrEnum):
    """Price tier — covers the four required policies."""

    FREE = "free"
    PAY_WHAT_YOU_WANT = "pay_what_you_want"
    FIXED_PRICE = "fixed_price"
    COMMERCIAL_LICENSE_REQUIRED = "commercial_license_required"


class ReleaseSurface(StrEnum):
    """Where the artifact is published."""

    OMG_LOL_WEBLOG = "omg_lol_weblog"
    INTERNET_ARCHIVE = "internet_archive"
    ZENODO = "zenodo"
    GITHUB_RELEASE = "github_release"
    DIRECT_DOWNLOAD = "direct_download"


class ExportBlocker(StrEnum):
    """Reasons the gate may block an artifact from publication."""

    UNCLEARED_RIGHTS = "uncleared_rights"
    UNANONYMIZED_PRIVATE = "unanonymized_private"
    MISSING_BUNDLE_FILES = "missing_bundle_files"
    MISSING_CHECKSUM = "missing_checksum"


class CatalogModel(BaseModel):
    """Frozen-by-default base — all catalog rows are immutable values."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class BundleFile(CatalogModel):
    """One file inside an artifact's bundle."""

    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    mime_type: str = Field(min_length=1)


class ArtifactRecord(CatalogModel):
    """One artifact in the catalog.

    Schema covers all 12 fields named in the cc-task acceptance:
    title, stream, source refs, rights class, privacy class, license
    class, price class, public claim, bundle files, checksum, version,
    release surface.
    """

    artifact_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    title: str = Field(min_length=1, max_length=200)
    stream: ArtifactStream
    source_refs: tuple[str, ...] = Field(min_length=1)
    rights_class: RightsClass
    privacy_class: PrivacyClass
    license_class: LicenseClass
    price_class: PriceClass
    public_claim: str = Field(min_length=1, max_length=500)
    bundle_files: tuple[BundleFile, ...] = Field(min_length=1)
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")  # SHA-256 of bundle manifest
    version: str = Field(pattern=r"^v?\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?$")
    release_surfaces: tuple[ReleaseSurface, ...] = Field(min_length=1)
    fixed_price_usd: float | None = Field(default=None, ge=0)
    commercial_license_url: str | None = Field(default=None, pattern=r"^https?://")

    @model_validator(mode="after")
    def _validate_price_class_invariants(self) -> Self:
        if self.price_class == PriceClass.FIXED_PRICE and self.fixed_price_usd is None:
            raise ValueError("fixed_price price_class requires fixed_price_usd")
        if (
            self.price_class == PriceClass.COMMERCIAL_LICENSE_REQUIRED
            and not self.commercial_license_url
        ):
            raise ValueError(
                "commercial_license_required price_class requires commercial_license_url"
            )
        if self.price_class == PriceClass.FREE and self.fixed_price_usd is not None:
            raise ValueError("free price_class cannot have fixed_price_usd")
        return self


class ArtifactCatalog(CatalogModel):
    """The full catalog: machine-readable manifest of all artifacts."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    artifacts: tuple[ArtifactRecord, ...]

    def by_stream(self, stream: ArtifactStream) -> tuple[ArtifactRecord, ...]:
        return tuple(a for a in self.artifacts if a.stream == stream)

    def by_price_class(self, price_class: PriceClass) -> tuple[ArtifactRecord, ...]:
        return tuple(a for a in self.artifacts if a.price_class == price_class)

    def exportable(self) -> tuple[ArtifactRecord, ...]:
        """Subset of artifacts that pass the export gate."""
        return tuple(a for a in self.artifacts if not _gate_block_reasons(a))


def _gate_block_reasons(artifact: ArtifactRecord) -> tuple[ExportBlocker, ...]:
    """Compute export blockers for one artifact (no I/O)."""
    blockers: list[ExportBlocker] = []
    if artifact.rights_class == RightsClass.UNCLEARED:
        blockers.append(ExportBlocker.UNCLEARED_RIGHTS)
    if artifact.privacy_class == PrivacyClass.UNANONYMIZED_PRIVATE:
        blockers.append(ExportBlocker.UNANONYMIZED_PRIVATE)
    if not artifact.bundle_files:
        blockers.append(ExportBlocker.MISSING_BUNDLE_FILES)
    if not artifact.checksum or len(artifact.checksum) != 64:
        blockers.append(ExportBlocker.MISSING_CHECKSUM)
    return tuple(blockers)


class ExportGateVerdict(CatalogModel):
    """Result of running the export gate on an artifact."""

    artifact_id: str
    allowed: bool
    blockers: tuple[ExportBlocker, ...] = Field(default_factory=tuple)


def evaluate_export_gate(artifact: ArtifactRecord) -> ExportGateVerdict:
    """Apply the export gate. Fail-closed: any blocker → not allowed."""
    blockers = _gate_block_reasons(artifact)
    return ExportGateVerdict(
        artifact_id=artifact.artifact_id,
        allowed=not blockers,
        blockers=blockers,
    )


def render_catalog_page(catalog: ArtifactCatalog) -> str:
    """Render a markdown catalog page from the artifact records.

    Groups by stream, sorts by version within stream. Each entry shows
    title, public_claim, price, license, version, and release surfaces.
    """
    lines: list[str] = []
    lines.append("# Hapax Artifact Catalog")
    lines.append("")
    lines.append(f"Generated at {catalog.generated_at.isoformat()}")
    lines.append("")
    lines.append(f"{len(catalog.artifacts)} artifacts; {len(catalog.exportable())} exportable.")
    lines.append("")

    for stream in ArtifactStream:
        stream_artifacts = sorted(
            catalog.by_stream(stream),
            key=lambda a: a.version,
        )
        if not stream_artifacts:
            continue
        lines.append(f"## {stream.value}")
        lines.append("")
        for artifact in stream_artifacts:
            lines.append(f"### {artifact.title}")
            lines.append("")
            lines.append(artifact.public_claim)
            lines.append("")
            lines.append(f"- **Price**: {artifact.price_class.value}")
            if artifact.price_class == PriceClass.FIXED_PRICE:
                lines.append(f"- **Price (USD)**: ${artifact.fixed_price_usd:.2f}")
            lines.append(f"- **License**: {artifact.license_class.value}")
            lines.append(f"- **Version**: {artifact.version}")
            lines.append(
                f"- **Release surfaces**: {', '.join(s.value for s in artifact.release_surfaces)}"
            )
            verdict = evaluate_export_gate(artifact)
            if not verdict.allowed:
                lines.append(
                    f"- **Export blocked**: {', '.join(b.value for b in verdict.blockers)}"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def compute_bundle_checksum(bundle_files: tuple[BundleFile, ...]) -> str:
    """Compute the catalog checksum from the per-file SHA-256 list.

    Deterministic: sort files by relative_path, concatenate
    (path|sha256), SHA-256 the result. Catalog readers can recompute
    and verify.
    """
    sorted_files = sorted(bundle_files, key=lambda f: f.relative_path)
    payload = "\n".join(f"{f.relative_path}|{f.sha256}" for f in sorted_files)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "ArtifactStream",
    "RightsClass",
    "PrivacyClass",
    "LicenseClass",
    "PriceClass",
    "ReleaseSurface",
    "ExportBlocker",
    "BundleFile",
    "ArtifactRecord",
    "ArtifactCatalog",
    "ExportGateVerdict",
    "evaluate_export_gate",
    "render_catalog_page",
    "compute_bundle_checksum",
]
