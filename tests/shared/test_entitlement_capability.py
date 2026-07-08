"""Entitlement → capability-shape classifier."""

from __future__ import annotations

import pytest

from shared.entitlement_capability import (
    EntitlementShape,
    classify_entitlement,
    is_routable_supply,
)


@pytest.mark.parametrize(
    ("name", "shape"),
    [
        ("openrouter/api", EntitlementShape.COGNITION_WAREHOUSE),
        ("api/huggingface", EntitlementShape.COGNITION_WAREHOUSE),
        ("HF_TOKEN", EntitlementShape.COGNITION_WAREHOUSE),
        ("perplexity/api-key", EntitlementShape.WEB_GROUNDING),
        ("api/tavily", EntitlementShape.WEB_GROUNDING),
        ("cohere/api-key", EntitlementShape.COGNITION_PROVIDER),
        ("sakana/api-key", EntitlementShape.COGNITION_PROVIDER),
        ("elevenlabs/api-key", EntitlementShape.MODALITY),
        ("picovoice/access-key", EntitlementShape.MODALITY),
        ("streaming/youtube-stream-key", EntitlementShape.MODALITY),
        ("devto/api-key", EntitlementShape.RESOURCE_PUBLISH),
        ("mastodon/access-token", EntitlementShape.RESOURCE_PUBLISH),
        ("zenodo-token", EntitlementShape.RESOURCE_PUBLISH),
        ("kofi/verification-token", EntitlementShape.RESOURCE_MONEY),
        ("lightning/alby-access-token", EntitlementShape.RESOURCE_MONEY),
        ("backblaze/app-key", EntitlementShape.RESOURCE_STORAGE),
        ("minio/root-user", EntitlementShape.RESOURCE_STORAGE),
        ("ibisworld", EntitlementShape.RESOURCE_DATA),
        ("sentry", EntitlementShape.RESOURCE_DATA),
    ],
)
def test_classify_known_entitlements(name: str, shape: EntitlementShape) -> None:
    assert classify_entitlement(name) == shape


def test_unknown_entitlement_defaults_non_capability_fail_closed() -> None:
    # An unrecognized secret must never be surfaced as routable supply.
    assert classify_entitlement("langfuse/secret-key") == EntitlementShape.NON_CAPABILITY
    assert classify_entitlement("postgres/password") == EntitlementShape.NON_CAPABILITY
    assert classify_entitlement("ssh/id-ed25519-private") == EntitlementShape.NON_CAPABILITY
    assert classify_entitlement("") == EntitlementShape.NON_CAPABILITY


def test_is_routable_supply_excludes_only_non_capability() -> None:
    assert is_routable_supply(EntitlementShape.COGNITION_WAREHOUSE) is True
    assert is_routable_supply(EntitlementShape.RESOURCE_MONEY) is True
    assert is_routable_supply(EntitlementShape.NON_CAPABILITY) is False


def test_classification_is_case_insensitive() -> None:
    assert classify_entitlement("OpenRouter/API") == EntitlementShape.COGNITION_WAREHOUSE
