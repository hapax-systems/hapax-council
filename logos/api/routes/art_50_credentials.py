"""Read-only required-label/name checks; signatures and signer trust are unverified."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agents.art_50_provenance.store import load_certificate
from agents.art_50_provenance.verify import verify_certificate_payload

router = APIRouter(tags=["art-50-credentials"])


def _verify_or_404(credential_id: str) -> dict:
    certificate = load_certificate(credential_id)
    if certificate is None:
        raise HTTPException(status_code=404, detail="credential packet not found")
    return verify_certificate_payload(certificate).model_dump(mode="json")


@router.get("/v1/credential/verify/{credential_id}")
def verify_credential_v1(credential_id: str) -> dict:
    """Check stored labels/names; no signature, signer trust or image bytes are verified."""

    return _verify_or_404(credential_id)


@router.get("/api/art-50/credential/verify/{credential_id}")
def verify_credential_api(credential_id: str) -> dict:
    """Check stored labels/names; no signature, signer trust or image bytes are verified."""

    return _verify_or_404(credential_id)


__all__ = ["router", "verify_credential_api", "verify_credential_v1"]
