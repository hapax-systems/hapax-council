"""Local image credential issuer for the Article 50 MVP."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from agents.art_50_provenance.c2pa_adapter import SignerMaterial, sign_with_c2pa_python
from agents.art_50_provenance.fingerprint import compute_image_fingerprints
from agents.art_50_provenance.manifest import build_c2pa_manifest_preview
from agents.art_50_provenance.models import (
    ART50_EVIDENCE_SOURCES,
    Art50CredentialCertificate,
    Art50CredentialRequest,
)
from agents.art_50_provenance.watermark import apply_visible_watermark


@dataclass(frozen=True)
class IssuedImageCredential:
    """Local issue result: certificate packet plus output asset bytes."""

    certificate: Art50CredentialCertificate
    asset_bytes: bytes


def _credential_id(request: Art50CredentialRequest, source_sha256: str) -> str:
    seed = "\x00".join((request.customer_id, request.asset_id, source_sha256))
    return f"crd_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:24]}"


def issue_image_credential(
    *,
    request: Art50CredentialRequest,
    image_bytes: bytes,
    signer: SignerMaterial | None = None,
    now: datetime | None = None,
) -> IssuedImageCredential:
    """Issue a local Article 50 image certificate packet.

    This does not publish, bill, register accounts, contact Zenodo, or mutate
    hardware. When C2PA signing prerequisites are missing, the certificate keeps
    a machine-readable blocked state while preserving the manifest preview and
    watermarked image for downstream inspection.
    """

    issued_at = now or datetime.now(UTC)
    source = compute_image_fingerprints(
        image_bytes,
        mime_type=request.mime_type,
        require_native_pdq=request.require_native_pdq,
    )
    credential_id = _credential_id(request, source.sha256)
    watermarked_bytes, watermark = apply_visible_watermark(
        image_bytes,
        credential_id=credential_id,
        disclosure_text=request.visible_disclosure,
        mime_type=request.mime_type,
    )
    output = compute_image_fingerprints(
        watermarked_bytes,
        mime_type=request.mime_type,
        require_native_pdq=request.require_native_pdq,
    )
    manifest = build_c2pa_manifest_preview(
        request=request,
        credential_id=credential_id,
        source_fingerprint=source,
        output_fingerprint=output,
        watermark=watermark,
        issued_at=issued_at,
    )
    c2pa_binding, final_bytes = sign_with_c2pa_python(
        manifest=manifest,
        mime_type=request.mime_type,
        asset_bytes=watermarked_bytes,
        signer=signer,
    )
    if final_bytes != watermarked_bytes:
        output = compute_image_fingerprints(
            final_bytes,
            mime_type=request.mime_type,
            require_native_pdq=request.require_native_pdq,
        )
        c2pa_binding.signed_asset_sha256 = output.sha256

    certificate = Art50CredentialCertificate(
        credential_id=credential_id,
        issued_at=issued_at,
        customer_id=request.customer_id,
        asset_id=request.asset_id,
        title=request.title,
        source_fingerprint=source,
        output_fingerprint=output,
        watermark=watermark,
        c2pa=c2pa_binding,
        evidence_sources=ART50_EVIDENCE_SOURCES,
    )
    return IssuedImageCredential(certificate=certificate, asset_bytes=final_bytes)


__all__ = ["IssuedImageCredential", "issue_image_credential"]
