from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError

from agents.art_50_provenance.fingerprint import PdqUnavailable, compute_image_fingerprints
from agents.art_50_provenance.issuer import issue_image_credential
from agents.art_50_provenance.manifest import manifest_labels
from agents.art_50_provenance.models import (
    Art50CredentialRequest,
    C2paSigningState,
)
from agents.art_50_provenance.store import load_certificate, write_certificate
from agents.art_50_provenance.verify import (
    Art50VerificationStatus,
    verify_certificate_payload,
    verify_image_bytes,
)
from agents.art_50_provenance.webhook import (
    Art50WebhookError,
    MemoryIdempotencyStore,
    render_signature_header,
    verify_signature_header,
)
from agents.publication_bus.surface_registry import SURFACE_REGISTRY, AutomationStatus
from logos.api.routes.art_50_credentials import verify_credential_api


def _png_bytes() -> bytes:
    image = Image.new("RGB", (180, 120), (34, 87, 142))
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _request(**overrides: object) -> Art50CredentialRequest:
    payload = {
        "customer_id": "pilot-customer",
        "asset_id": "asset-001",
        "title": "Synthetic reference image",
        "mime_type": "image/png",
        "model_name": "hapax-test-image-generator",
    }
    payload.update(overrides)
    return Art50CredentialRequest(**payload)


def test_issue_image_credential_builds_manifest_watermark_and_fingerprints() -> None:
    issued = issue_image_credential(
        request=_request(),
        image_bytes=_png_bytes(),
        now=datetime(2026, 5, 5, 1, 0, tzinfo=UTC),
    )

    certificate = issued.certificate
    assert certificate.credential_id.startswith("crd_")
    assert certificate.watermark.disclosure_text == "AI GENERATED"
    assert certificate.source_fingerprint.sha256 != certificate.output_fingerprint.sha256
    assert certificate.output_fingerprint.pdq_status in {"fallback", "native"}
    assert certificate.c2pa.status is C2paSigningState.BLOCKED_MISSING_C2PA

    labels = manifest_labels(certificate.c2pa.manifest)
    assert "c2pa.actions.v2" in labels
    assert "c2pa.ai-disclosure" in labels
    assert "org.hapax.article50.identity.v1" in labels
    assert "org.hapax.article50.fingerprints.v1" in labels
    assert "org.hapax.article50.watermark.v1" in labels

    identity_assertion = next(
        assertion
        for assertion in certificate.c2pa.manifest["assertions"]
        if assertion["label"] == "org.hapax.article50.identity.v1"
    )
    names = {identity["name"] for identity in identity_assertion["data"]["identities"]}
    assert {"Hapax", "Claude Code", "Oudepode"} <= names


def test_verify_image_bytes_accepts_exact_output_bytes() -> None:
    issued = issue_image_credential(request=_request(), image_bytes=_png_bytes())
    result = verify_image_bytes(issued.certificate, issued.asset_bytes)

    assert result.status is Art50VerificationStatus.VALID_UNSIGNED_PREVIEW
    assert result.exact_sha256_match is True
    assert result.phash_distance == 0
    assert "blocked_missing_c2pa_python" in result.reasons


def test_certificate_payload_verification_requires_current_manifest_assertions() -> None:
    issued = issue_image_credential(request=_request(), image_bytes=_png_bytes())
    certificate = issued.certificate.model_copy(deep=True)
    certificate.c2pa.manifest["assertions"] = [
        assertion
        for assertion in certificate.c2pa.manifest["assertions"]
        if assertion["label"] != "c2pa.ai-disclosure"
    ]

    result = verify_certificate_payload(certificate)

    assert result.status is Art50VerificationStatus.INVALID
    assert "missing_c2pa_ai_disclosure" in result.reasons


def test_native_pdq_requirement_fails_closed_without_pdq_package() -> None:
    with pytest.raises(PdqUnavailable):
        compute_image_fingerprints(
            _png_bytes(),
            mime_type="image/png",
            require_native_pdq=True,
        )


def test_manifest_bound_request_fields_reject_obvious_pii() -> None:
    with pytest.raises(ValidationError, match="must not contain obvious PII"):
        _request(title="deliver to person@example.com")


def test_webhook_signature_enforces_replay_window_and_idempotency() -> None:
    body = b'{"asset_id":"asset-001"}'
    secret = "test-secret"
    header = render_signature_header(secret=secret, timestamp_s=1000, body=body)

    assert verify_signature_header(secret=secret, header=header, body=body, now_s=1001) == 1000
    with pytest.raises(Art50WebhookError):
        verify_signature_header(secret=secret, header=header, body=body, now_s=1401)

    store = MemoryIdempotencyStore()
    assert store.accept_once("delivery-1", now_s=1000)
    assert not store.accept_once("delivery-1", now_s=1001)
    assert store.accept_once("delivery-1", now_s=1000 + 86_401)


def test_surface_registry_registers_art50_surfaces_as_full_auto() -> None:
    assert SURFACE_REGISTRY["art-50-credential-issue"].automation_status is (
        AutomationStatus.FULL_AUTO
    )
    assert SURFACE_REGISTRY["art-50-credential-verify"].automation_status is (
        AutomationStatus.FULL_AUTO
    )


def test_verify_route_reads_local_certificate_packet(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_STATE", str(tmp_path))
    issued = issue_image_credential(request=_request(), image_bytes=_png_bytes())
    write_certificate(issued.certificate, state_root=tmp_path)

    assert load_certificate(issued.certificate.credential_id, state_root=tmp_path) is not None
    payload = verify_credential_api(issued.certificate.credential_id)

    assert payload["credential_id"] == issued.certificate.credential_id
    assert payload["status"] == "valid_unsigned_preview"
