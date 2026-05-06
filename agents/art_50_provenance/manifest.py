"""C2PA manifest-preview composition for Article 50 image credentials."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agents.art_50_provenance.models import (
    DEFAULT_V5_IDENTITIES,
    Art50CredentialRequest,
    FingerprintBundle,
    WatermarkRecord,
)

CLAIM_GENERATOR_NAME = "hapax-art50-provenance"
CLAIM_GENERATOR_VERSION = "0.1.0"
C2PA_SPEC_VERSION = "2.4"

DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA = (
    "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
)


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_c2pa_manifest_preview(
    *,
    request: Art50CredentialRequest,
    credential_id: str,
    source_fingerprint: FingerprintBundle,
    output_fingerprint: FingerprintBundle,
    watermark: WatermarkRecord,
    issued_at: datetime,
) -> dict[str, Any]:
    """Build the manifest JSON shape consumed by ``c2pa-python``.

    The labels intentionally use current C2PA 2.4 names where available:
    ``c2pa.actions.v2`` plus ``c2pa.ai-disclosure``. Hapax-specific
    assertions are namespaced under ``org.hapax.article50`` so validators can
    ignore them without confusing them for standard C2PA assertions.
    """

    identities = [identity.model_dump(mode="json") for identity in DEFAULT_V5_IDENTITIES]
    ai_disclosure: dict[str, Any] = {
        "modelType": request.model_type,
        "contentProfile": {"humanOversightLevel": request.human_oversight_level.value},
    }
    if request.model_name:
        ai_disclosure["modelName"] = request.model_name
    if request.model_identifier:
        ai_disclosure["modelIdentifier"] = request.model_identifier
    if request.scientific_domain:
        ai_disclosure["scientificDomain"] = list(request.scientific_domain)

    return {
        "claim_generator_info": [
            {
                "name": CLAIM_GENERATOR_NAME,
                "version": CLAIM_GENERATOR_VERSION,
                "specVersion": C2PA_SPEC_VERSION,
            }
        ],
        "title": request.title,
        "format": request.mime_type,
        "assertions": [
            {
                "label": "c2pa.actions.v2",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA,
                            "softwareAgents": [
                                {
                                    "name": CLAIM_GENERATOR_NAME,
                                    "version": CLAIM_GENERATOR_VERSION,
                                }
                            ],
                            "parameters": {
                                "credential_id": credential_id,
                                "issued_at": _rfc3339(issued_at),
                            },
                        },
                        {
                            "action": "c2pa.watermarked.bound",
                            "softwareAgents": [
                                {
                                    "name": CLAIM_GENERATOR_NAME,
                                    "version": CLAIM_GENERATOR_VERSION,
                                }
                            ],
                            "parameters": {
                                "credential_id": credential_id,
                                "watermark_method": watermark.method,
                            },
                        },
                    ]
                },
            },
            {
                "label": "c2pa.ai-disclosure",
                "data": ai_disclosure,
            },
            {
                "label": "org.hapax.article50.identity.v1",
                "data": {
                    "attribution_mode": "V5 unsettled-attribution",
                    "identities": identities,
                    "pii_policy": "no customer PII fields in manifest payload",
                },
            },
            {
                "label": "org.hapax.article50.fingerprints.v1",
                "data": {
                    "source": source_fingerprint.model_dump(mode="json"),
                    "output": output_fingerprint.model_dump(mode="json"),
                },
            },
            {
                "label": "org.hapax.article50.watermark.v1",
                "data": watermark.model_dump(mode="json"),
            },
        ],
    }


def manifest_labels(manifest: dict[str, Any]) -> set[str]:
    """Return assertion labels from a manifest-preview dict."""

    labels: set[str] = set()
    for assertion in manifest.get("assertions", []):
        if isinstance(assertion, dict) and isinstance(assertion.get("label"), str):
            labels.add(assertion["label"])
    return labels


__all__ = [
    "C2PA_SPEC_VERSION",
    "CLAIM_GENERATOR_NAME",
    "CLAIM_GENERATOR_VERSION",
    "DIGITAL_SOURCE_TYPE_TRAINED_ALGORITHMIC_MEDIA",
    "build_c2pa_manifest_preview",
    "manifest_labels",
]
