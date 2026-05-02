"""Tests for the artifact catalog and release workflow.

cc-task: artifact-catalog-release-workflow.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from shared.artifact_catalog import (
    ArtifactCatalog,
    ArtifactRecord,
    ArtifactStream,
    BundleFile,
    ExportBlocker,
    LicenseClass,
    PriceClass,
    PrivacyClass,
    ReleaseSurface,
    RightsClass,
    compute_bundle_checksum,
    evaluate_export_gate,
    render_catalog_page,
)


def _file(name: str, *, content: str = "test") -> BundleFile:
    sha256 = hashlib.sha256(content.encode()).hexdigest()
    return BundleFile(
        relative_path=name,
        sha256=sha256,
        size_bytes=len(content),
        mime_type="application/octet-stream",
    )


def _record(
    *,
    artifact_id: str = "test-artifact-001",
    price_class: PriceClass = PriceClass.FREE,
    fixed_price_usd: float | None = None,
    commercial_license_url: str | None = None,
    rights_class: RightsClass = RightsClass.OPERATOR_OWNED,
    privacy_class: PrivacyClass = PrivacyClass.FULLY_PUBLIC,
) -> ArtifactRecord:
    files = (_file("README.md"),)
    return ArtifactRecord(
        artifact_id=artifact_id,
        title="Test Artifact",
        stream=ArtifactStream.METHODOLOGY_DOSSIER,
        source_refs=("docs/spec.md",),
        rights_class=rights_class,
        privacy_class=privacy_class,
        license_class=LicenseClass.CC_BY,
        price_class=price_class,
        public_claim="A test artifact for the catalog.",
        bundle_files=files,
        checksum=compute_bundle_checksum(files),
        version="v1.0.0",
        release_surfaces=(ReleaseSurface.GITHUB_RELEASE,),
        fixed_price_usd=fixed_price_usd,
        commercial_license_url=commercial_license_url,
    )


def test_artifact_record_minimal_construction_works():
    record = _record()
    assert record.artifact_id == "test-artifact-001"
    assert record.price_class == PriceClass.FREE


def test_fixed_price_class_requires_fixed_price_usd():
    with pytest.raises(ValueError, match="fixed_price_usd"):
        _record(price_class=PriceClass.FIXED_PRICE)


def test_fixed_price_class_with_price_works():
    record = _record(price_class=PriceClass.FIXED_PRICE, fixed_price_usd=29.99)
    assert record.fixed_price_usd == 29.99


def test_commercial_license_class_requires_url():
    with pytest.raises(ValueError, match="commercial_license_url"):
        _record(price_class=PriceClass.COMMERCIAL_LICENSE_REQUIRED)


def test_commercial_license_class_with_url_works():
    record = _record(
        price_class=PriceClass.COMMERCIAL_LICENSE_REQUIRED,
        commercial_license_url="https://hapax.weblog.lol/commercial-license",
    )
    assert record.commercial_license_url is not None


def test_free_price_class_cannot_have_fixed_price():
    with pytest.raises(ValueError):
        _record(price_class=PriceClass.FREE, fixed_price_usd=10.0)


def test_pay_what_you_want_price_class_works():
    record = _record(price_class=PriceClass.PAY_WHAT_YOU_WANT)
    assert record.price_class == PriceClass.PAY_WHAT_YOU_WANT
    assert record.fixed_price_usd is None


def test_export_gate_passes_clean_artifact():
    record = _record()
    verdict = evaluate_export_gate(record)
    assert verdict.allowed is True
    assert verdict.blockers == ()


def test_export_gate_blocks_uncleared_rights():
    record = _record(rights_class=RightsClass.UNCLEARED)
    verdict = evaluate_export_gate(record)
    assert verdict.allowed is False
    assert ExportBlocker.UNCLEARED_RIGHTS in verdict.blockers


def test_export_gate_blocks_unanonymized_private():
    record = _record(privacy_class=PrivacyClass.UNANONYMIZED_PRIVATE)
    verdict = evaluate_export_gate(record)
    assert verdict.allowed is False
    assert ExportBlocker.UNANONYMIZED_PRIVATE in verdict.blockers


def test_compute_bundle_checksum_deterministic():
    files = (_file("a.txt"), _file("b.txt"))
    files_reversed = tuple(reversed(files))

    checksum_1 = compute_bundle_checksum(files)
    checksum_2 = compute_bundle_checksum(files_reversed)

    # Sorted internally → identical regardless of input order
    assert checksum_1 == checksum_2


def test_artifact_catalog_groups_by_stream():
    catalog = ArtifactCatalog(
        generated_at=datetime.now(tz=UTC),
        artifacts=(
            _record(artifact_id="dossier-1"),
            _record(artifact_id="dossier-2"),
        ),
    )
    by_stream = catalog.by_stream(ArtifactStream.METHODOLOGY_DOSSIER)
    assert len(by_stream) == 2


def test_artifact_catalog_filters_by_price_class():
    catalog = ArtifactCatalog(
        generated_at=datetime.now(tz=UTC),
        artifacts=(
            _record(artifact_id="free-1", price_class=PriceClass.FREE),
            _record(
                artifact_id="paid-1",
                price_class=PriceClass.FIXED_PRICE,
                fixed_price_usd=49.99,
            ),
        ),
    )
    free = catalog.by_price_class(PriceClass.FREE)
    paid = catalog.by_price_class(PriceClass.FIXED_PRICE)
    assert len(free) == 1
    assert len(paid) == 1
    assert free[0].artifact_id == "free-1"
    assert paid[0].artifact_id == "paid-1"


def test_artifact_catalog_exportable_excludes_blocked():
    catalog = ArtifactCatalog(
        generated_at=datetime.now(tz=UTC),
        artifacts=(
            _record(artifact_id="ok-1"),
            _record(artifact_id="blocked-1", rights_class=RightsClass.UNCLEARED),
        ),
    )
    exportable = catalog.exportable()
    assert len(exportable) == 1
    assert exportable[0].artifact_id == "ok-1"


def test_render_catalog_page_includes_all_required_fields():
    catalog = ArtifactCatalog(
        generated_at=datetime.now(tz=UTC),
        artifacts=(
            _record(
                artifact_id="paid-1",
                price_class=PriceClass.FIXED_PRICE,
                fixed_price_usd=49.99,
            ),
        ),
    )
    page = render_catalog_page(catalog)
    assert "Test Artifact" in page
    assert "fixed_price" in page
    assert "$49.99" in page
    assert "cc_by" in page
    assert "v1.0.0" in page
    assert "github_release" in page


def test_render_catalog_page_marks_blocked_artifacts():
    catalog = ArtifactCatalog(
        generated_at=datetime.now(tz=UTC),
        artifacts=(_record(artifact_id="blocked-1", rights_class=RightsClass.UNCLEARED),),
    )
    page = render_catalog_page(catalog)
    assert "Export blocked" in page
    assert "uncleared_rights" in page


def test_artifact_id_validation():
    with pytest.raises(ValueError):
        _record(artifact_id="UPPERCASE_NOT_ALLOWED")


def test_release_surfaces_must_be_non_empty():
    files = (_file("README.md"),)
    with pytest.raises(ValueError):
        ArtifactRecord(
            artifact_id="test-artifact-002",
            title="Test",
            stream=ArtifactStream.METHODOLOGY_DOSSIER,
            source_refs=("docs/spec.md",),
            rights_class=RightsClass.OPERATOR_OWNED,
            privacy_class=PrivacyClass.FULLY_PUBLIC,
            license_class=LicenseClass.CC_BY,
            price_class=PriceClass.FREE,
            public_claim="claim",
            bundle_files=files,
            checksum=compute_bundle_checksum(files),
            version="v1.0.0",
            release_surfaces=(),
        )
