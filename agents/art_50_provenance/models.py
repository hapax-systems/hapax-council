"""Typed Article 50 provenance packet models."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ART50_EVIDENCE_SOURCES: tuple[str, ...] = (
    "https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-50",
    "https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content",
    "https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html",
    "https://github.com/contentauth/c2pa-python",
    "/home/hapax/.cache/hapax/gemini-jr-team/packets/"
    "20260504T230725Z-jr-currentness-scout-eu-ai-act-art50-c2pa-currentness-2026-05-04.md",
    "/home/hapax/.cache/hapax/gemini-jr-team/packets/"
    "20260505T001841Z-jr-currentness-scout-c2pa-rs-python-libraries-2026-05-04.md",
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b")


class PiiDetected(ValueError):
    """Raised when a manifest-bound field contains obvious PII."""


class HumanOversightLevel(StrEnum):
    """C2PA 2.4 ``c2pa.ai-disclosure`` human oversight values."""

    FULLY_AUTONOMOUS = "fully_autonomous"
    PROMPT_GUIDED = "prompt_guided"
    HUMAN_VALIDATED = "human_validated"


class C2paSigningState(StrEnum):
    """C2PA signing state for a local certificate packet."""

    BLOCKED_MISSING_C2PA = "blocked_missing_c2pa_python"
    BLOCKED_MISSING_SIGNER = "blocked_missing_signer"
    SIGNING_ERROR = "signing_error"
    SIGNED_EMBEDDED = "signed_embedded"


class Art50Identity(BaseModel):
    """One V5 co-attribution identity carried in the manifest packet."""

    name: str
    role: str
    assertion_kind: Literal["entity", "agent", "operator_alias"]


DEFAULT_V5_IDENTITIES: tuple[Art50Identity, ...] = (
    Art50Identity(name="Hapax", role="provenance issuer", assertion_kind="entity"),
    Art50Identity(name="Claude Code", role="implementation agent", assertion_kind="agent"),
    Art50Identity(name="Oudepode", role="operator alias", assertion_kind="operator_alias"),
)


def _assert_manifest_safe_text(value: str) -> str:
    if _EMAIL_RE.search(value) or _PHONE_RE.search(value):
        raise PiiDetected("manifest-bound Article 50 fields must not contain obvious PII")
    return value


class Art50CredentialRequest(BaseModel):
    """Input contract for image-only Article 50 credential issuance."""

    customer_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,80}$")
    asset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,120}$")
    title: str = Field(min_length=1, max_length=160)
    mime_type: Literal["image/jpeg", "image/png", "image/webp", "image/tiff"] = "image/png"
    model_type: str = "c2pa.types.model.image-generator"
    model_name: str = "unspecified-image-generator"
    model_identifier: str | None = None
    human_oversight_level: HumanOversightLevel = HumanOversightLevel.PROMPT_GUIDED
    scientific_domain: tuple[str, ...] = ("cs.CV",)
    visible_disclosure: str = Field(default="AI GENERATED", min_length=2, max_length=48)
    require_native_pdq: bool = False

    @field_validator("title", "model_name", "model_identifier", "visible_disclosure")
    @classmethod
    def _no_obvious_pii(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _assert_manifest_safe_text(value)

    @field_validator("scientific_domain")
    @classmethod
    def _domain_shape(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not re.match(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$", item):
                raise ValueError(f"invalid arXiv-like scientific domain: {item}")
        return value


class FingerprintBundle(BaseModel):
    """Cryptographic and perceptual fingerprints for one image rendition."""

    mime_type: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    phash: str = Field(pattern=r"^[0-9a-f]{16}$")
    phash_bits: int = 64
    pdq: str = Field(pattern=r"^[0-9a-f]{64}$")
    pdq_bits: int = 256
    pdq_status: Literal["native", "fallback"]
    pdq_algorithm: str


class WatermarkRecord(BaseModel):
    """Visible watermark metadata embedded in the certificate packet."""

    credential_id: str
    disclosure_text: str
    method: str
    position: str
    output_format: str
    byte_length: int = Field(ge=1)


class C2paBinding(BaseModel):
    """Machine-readable C2PA manifest preview plus signing state."""

    status: C2paSigningState
    manifest: dict
    signed_asset_sha256: str | None = None
    detail: str


class Art50CredentialCertificate(BaseModel):
    """Local certificate packet emitted by the image-only MVP."""

    schema_version: str = "2026-05-05.art50.image-mvp.v1"
    jsonld_context: tuple[str, ...] = (
        "https://schema.org",
        "https://c2pa.org/ns/",
        "https://hapax.local/ns/article50",
    )
    credential_id: str = Field(pattern=r"^crd_[0-9a-f]{24}$")
    issued_at: datetime
    customer_id: str
    asset_id: str
    title: str
    source_fingerprint: FingerprintBundle
    output_fingerprint: FingerprintBundle
    watermark: WatermarkRecord
    c2pa: C2paBinding
    evidence_sources: tuple[str, ...] = ART50_EVIDENCE_SOURCES
    limitations: tuple[str, ...] = (
        "This packet is Article 50 audit-trail evidence, not legal advice.",
        "Unsigned or blocked C2PA states are implementation readiness signals, not trusted "
        "claim-signer validation.",
        "The fallback PDQ-DCT hash is not native PDQ and must be replaced or accepted by a "
        "production owner before claiming native PDQ coverage.",
        "No court-admissibility or forensic-authenticity claim is made.",
    )


__all__ = [
    "ART50_EVIDENCE_SOURCES",
    "DEFAULT_V5_IDENTITIES",
    "Art50CredentialCertificate",
    "Art50CredentialRequest",
    "Art50Identity",
    "C2paBinding",
    "C2paSigningState",
    "FingerprintBundle",
    "HumanOversightLevel",
    "PiiDetected",
    "WatermarkRecord",
]
