"""Image-only Article 50 provenance MVP.

This package is deliberately hermetic by default: it can build a local
certificate packet, watermark an image, compute fingerprints, and verify the
packet structure without calling live publication, banking, CA, HSM, or account
surfaces. C2PA signing is optional and reports an explicit blocked state until
the runtime has ``c2pa-python`` and signer material.
"""

from agents.art_50_provenance.issuer import IssuedImageCredential, issue_image_credential
from agents.art_50_provenance.models import (
    ART50_EVIDENCE_SOURCES,
    DEFAULT_V5_IDENTITIES,
    Art50CredentialCertificate,
    Art50CredentialRequest,
    Art50Identity,
    C2paBinding,
    C2paSigningState,
    FingerprintBundle,
    HumanOversightLevel,
    WatermarkRecord,
)
from agents.art_50_provenance.verify import (
    Art50VerificationResult,
    verify_certificate_payload,
    verify_image_bytes,
)

__all__ = [
    "ART50_EVIDENCE_SOURCES",
    "DEFAULT_V5_IDENTITIES",
    "Art50CredentialCertificate",
    "Art50CredentialRequest",
    "Art50Identity",
    "Art50VerificationResult",
    "C2paBinding",
    "C2paSigningState",
    "FingerprintBundle",
    "HumanOversightLevel",
    "IssuedImageCredential",
    "WatermarkRecord",
    "issue_image_credential",
    "verify_certificate_payload",
    "verify_image_bytes",
]
