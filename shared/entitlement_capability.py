"""Entitlement → capability-shape classifier.

The pure, testable core of the entitlement→capability reconciler (warehouse-entitlement
supply-model design). Maps a HELD ENTITLEMENT NAME (never a secret value) to the capability
shape it exposes, so a reconciler can enumerate held entitlements and report which are
routable supply and of what shape. Unknown names default to ``NON_CAPABILITY`` — an
unrecognized secret is never mis-surfaced as routable supply (fail-closed classification).
"""

from __future__ import annotations

from enum import StrEnum


class EntitlementShape(StrEnum):
    """The capability shape a held entitlement exposes to the calculi."""

    COGNITION_WAREHOUSE = "cognition_warehouse"  # a many-model aggregator (OpenRouter, HF)
    COGNITION_PROVIDER = "cognition_provider"  # a discrete cognition provider
    WEB_GROUNDING = "web_grounding"  # web-grounded search/research cognition
    MODALITY = "modality"  # voice / audio / visual / video (non-cognition)
    RESOURCE_PUBLISH = "resource_publish"  # public-egress publishing rails
    RESOURCE_MONEY = "resource_money"  # money rails
    RESOURCE_STORAGE = "resource_storage"  # storage pools
    RESOURCE_DATA = "resource_data"  # data / observability services
    NON_CAPABILITY = "non_capability"  # infra creds, not routable supply


#: Exact / substring tokens → shape. First substring match wins (ordered most-specific first).
#: Keys are lowercased entitlement-name fragments as they appear in ``pass``/secrets.
_TOKEN_SHAPE: tuple[tuple[str, EntitlementShape], ...] = (
    ("openrouter", EntitlementShape.COGNITION_WAREHOUSE),
    ("huggingface", EntitlementShape.COGNITION_WAREHOUSE),
    ("hf_token", EntitlementShape.COGNITION_WAREHOUSE),
    ("perplexity", EntitlementShape.WEB_GROUNDING),
    ("tavily", EntitlementShape.WEB_GROUNDING),
    ("cohere", EntitlementShape.COGNITION_PROVIDER),
    ("sakana", EntitlementShape.COGNITION_PROVIDER),
    ("reverb", EntitlementShape.COGNITION_PROVIDER),
    ("mistral", EntitlementShape.COGNITION_PROVIDER),
    ("glmcp", EntitlementShape.COGNITION_PROVIDER),
    ("elevenlabs", EntitlementShape.MODALITY),
    ("picovoice", EntitlementShape.MODALITY),
    ("acoustid", EntitlementShape.MODALITY),
    ("acrcloud", EntitlementShape.MODALITY),
    ("epidemic", EntitlementShape.MODALITY),
    ("youtube", EntitlementShape.MODALITY),
    ("streaming", EntitlementShape.MODALITY),
    ("devto", EntitlementShape.RESOURCE_PUBLISH),
    ("hashnode", EntitlementShape.RESOURCE_PUBLISH),
    ("mastodon", EntitlementShape.RESOURCE_PUBLISH),
    ("mastadon", EntitlementShape.RESOURCE_PUBLISH),  # observed misspelling in the store
    ("bluesky", EntitlementShape.RESOURCE_PUBLISH),
    ("nostr", EntitlementShape.RESOURCE_PUBLISH),
    ("soundcloud", EntitlementShape.RESOURCE_PUBLISH),
    ("zenodo", EntitlementShape.RESOURCE_PUBLISH),
    ("osf", EntitlementShape.RESOURCE_PUBLISH),
    ("orcid", EntitlementShape.RESOURCE_PUBLISH),
    ("philarchive", EntitlementShape.RESOURCE_PUBLISH),
    ("omg-lol", EntitlementShape.RESOURCE_PUBLISH),
    ("internet-archive", EntitlementShape.RESOURCE_PUBLISH),
    ("kofi", EntitlementShape.RESOURCE_MONEY),
    ("ko_fi", EntitlementShape.RESOURCE_MONEY),
    ("liberapay", EntitlementShape.RESOURCE_MONEY),
    ("librepay", EntitlementShape.RESOURCE_MONEY),
    ("lightning", EntitlementShape.RESOURCE_MONEY),
    ("backblaze", EntitlementShape.RESOURCE_STORAGE),
    ("minio", EntitlementShape.RESOURCE_STORAGE),
    ("synology", EntitlementShape.RESOURCE_STORAGE),
    ("rclone", EntitlementShape.RESOURCE_STORAGE),
    ("ibisworld", EntitlementShape.RESOURCE_DATA),
    ("sentry", EntitlementShape.RESOURCE_DATA),
    ("context7", EntitlementShape.RESOURCE_DATA),
)


def classify_entitlement(name: str) -> EntitlementShape:
    """Classify a held entitlement NAME into its capability shape.

    Deterministic + case-insensitive substring match; the first (most specific) token wins.
    An unrecognized name is ``NON_CAPABILITY`` (fail-closed: never surface an unknown secret
    as routable supply)."""
    lowered = name.strip().lower()
    if not lowered:
        return EntitlementShape.NON_CAPABILITY
    for token, shape in _TOKEN_SHAPE:
        if token in lowered:
            return shape
    return EntitlementShape.NON_CAPABILITY


def is_routable_supply(shape: EntitlementShape) -> bool:
    """True when the shape is candidate supply in the routing calculi (everything except
    ``NON_CAPABILITY``)."""
    return shape is not EntitlementShape.NON_CAPABILITY
