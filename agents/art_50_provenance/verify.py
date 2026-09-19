"""Required-record checks and image comparisons, not cryptographic verification."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from agents.art_50_provenance.fingerprint import compute_image_fingerprints, phash_distance
from agents.art_50_provenance.manifest import manifest_labels
from agents.art_50_provenance.models import (
    DEFAULT_V5_IDENTITIES,
    Art50CredentialCertificate,
    C2paSigningState,
)


class Art50VerificationStatus(StrEnum):
    """Outcome of required-label/name checks and optional image comparison."""

    STRUCTURE_PRESENT_UNVERIFIED = "structure_present_unverified"
    INVALID = "invalid"


class Art50VerificationResult(BaseModel):
    """Bounded checks; no signature, signer trust or attribution is verified."""

    credential_id: str
    status: Art50VerificationStatus
    c2pa_status: C2paSigningState = Field(
        description="Packet-declared issuance/signing state, not verified by these checks."
    )
    has_ai_disclosure: bool
    has_actions: bool
    has_v5_identities: bool
    has_watermark_record: bool
    has_fingerprints: bool
    exact_sha256_match: bool | None = None
    phash_distance: int | None = Field(default=None, ge=0)
    reasons: tuple[str, ...] = ()


def _identity_names(certificate: Art50CredentialCertificate) -> set[str]:
    manifest = certificate.c2pa.manifest
    names: set[str] = set()
    for assertion in manifest.get("assertions", []):
        if assertion.get("label") != "org.hapax.article50.identity.v1":
            continue
        for identity in assertion.get("data", {}).get("identities", []):
            name = identity.get("name")
            if isinstance(name, str):
                names.add(name)
    return names


def verify_certificate_payload(
    certificate: Art50CredentialCertificate,
) -> Art50VerificationResult:
    """Check required labels and identity names, not assertion truth or validity."""

    labels = manifest_labels(certificate.c2pa.manifest)
    required_names = {identity.name for identity in DEFAULT_V5_IDENTITIES}
    has_ai_disclosure = "c2pa.ai-disclosure" in labels
    has_actions = "c2pa.actions.v2" in labels
    has_v5_identities = required_names <= _identity_names(certificate)
    has_watermark_record = "org.hapax.article50.watermark.v1" in labels
    has_fingerprints = "org.hapax.article50.fingerprints.v1" in labels

    reasons: list[str] = ["cryptographic_verification_not_performed"]
    if not has_ai_disclosure:
        reasons.append("missing_c2pa_ai_disclosure")
    if not has_actions:
        reasons.append("missing_c2pa_actions_v2")
    if not has_v5_identities:
        reasons.append("missing_v5_identities")
    if not has_watermark_record:
        reasons.append("missing_watermark_record")
    if not has_fingerprints:
        reasons.append("missing_fingerprint_record")
    if certificate.c2pa.status is not C2paSigningState.SIGNED_EMBEDDED:
        reasons.append(certificate.c2pa.status.value)

    structurally_valid = all(
        (
            has_ai_disclosure,
            has_actions,
            has_v5_identities,
            has_watermark_record,
            has_fingerprints,
        )
    )
    if not structurally_valid:
        status = Art50VerificationStatus.INVALID
    else:
        status = Art50VerificationStatus.STRUCTURE_PRESENT_UNVERIFIED

    return Art50VerificationResult(
        credential_id=certificate.credential_id,
        status=status,
        c2pa_status=certificate.c2pa.status,
        has_ai_disclosure=has_ai_disclosure,
        has_actions=has_actions,
        has_v5_identities=has_v5_identities,
        has_watermark_record=has_watermark_record,
        has_fingerprints=has_fingerprints,
        reasons=tuple(reasons),
    )


def verify_image_bytes(
    certificate: Art50CredentialCertificate,
    image_bytes: bytes,
    *,
    phash_threshold: int = 4,
) -> Art50VerificationResult:
    """Compare bytes to an unauthenticated recorded digest and measure similarity.

    Neither an exact match nor perceptual similarity establishes signed provenance.
    """

    result = verify_certificate_payload(certificate)
    observed = compute_image_fingerprints(
        image_bytes,
        mime_type=certificate.output_fingerprint.mime_type,
        require_native_pdq=False,
    )
    exact_sha = observed.sha256 == certificate.output_fingerprint.sha256
    distance = phash_distance(observed.phash, certificate.output_fingerprint.phash)
    reasons = list(result.reasons)
    if not exact_sha:
        reasons.append("exact_sha256_mismatch")
        if distance <= phash_threshold:
            reasons.append("perceptual_match_only")
    if not exact_sha and distance > phash_threshold:
        reasons.append("image_fingerprint_mismatch")
        status = Art50VerificationStatus.INVALID
    else:
        status = result.status

    return result.model_copy(
        update={
            "status": status,
            "exact_sha256_match": exact_sha,
            "phash_distance": distance,
            "reasons": tuple(reasons),
        }
    )


__all__ = [
    "Art50VerificationResult",
    "Art50VerificationStatus",
    "verify_certificate_payload",
    "verify_image_bytes",
]
