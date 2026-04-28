"""Policy guardrail tests for Tavily web egress."""

from __future__ import annotations

import pytest

from shared.tavily_client import (
    TavilyPolicyViolation,
    validate_public_web_text,
    validate_public_web_url,
)


@pytest.mark.parametrize(
    "text",
    [
        "from: someone@example.com subject: internal only roadmap",
        "paste raw transcript from yesterday's private meeting",
        "confidential employer strategy document",
        "sk-abcdefghijklmnopqrstuvwxyz1234567890",
    ],
)
def test_private_or_credential_like_queries_are_rejected(text: str) -> None:
    with pytest.raises(TavilyPolicyViolation):
        validate_public_web_text(text)


def test_public_bibliographic_person_query_can_be_allowed() -> None:
    validate_public_web_text(
        "ORCID publication record for researcher@example.edu",
        allow_public_bibliographic_people=True,
    )


def test_allow_private_is_explicit_escape_hatch() -> None:
    validate_public_web_text("from: person@example.com subject: private", allow_private=True)


def test_public_web_url_passes() -> None:
    validate_public_web_url("https://docs.tavily.com")


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8051",
        "http://192.168.1.1",
        "http://169.254.10.1",
        "http://service.local/path",
        "file:///tmp/private.md",
        "/home/hapax/private.md",
        "https://token:secret@example.com",
    ],
)
def test_private_or_local_urls_are_rejected(url: str) -> None:
    with pytest.raises(TavilyPolicyViolation):
        validate_public_web_url(url)


def test_url_allow_private_is_explicit_escape_hatch() -> None:
    validate_public_web_url("http://localhost:8051", allow_private=True)
