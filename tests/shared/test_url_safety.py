"""Tests for parsed URL/domain validation helpers."""

from __future__ import annotations

from shared.url_safety import host_matches_domain, url_matches_domain


def test_host_matches_exact_domain_and_subdomain_boundary() -> None:
    assert host_matches_domain("example.com", "example.com")
    assert host_matches_domain("docs.example.com", "example.com")


def test_host_rejects_lookalike_domains() -> None:
    assert not host_matches_domain("evil-example.com", "example.com")
    assert not host_matches_domain("example.com.evil.test", "example.com")


def test_url_matches_domain_requires_parsed_https_origin() -> None:
    assert url_matches_domain("https://example.com/path", "example.com")
    assert not url_matches_domain("http://example.com/path", "example.com")
    assert not url_matches_domain("https://evil.test/path?next=https://example.com", "example.com")
    assert not url_matches_domain("https://example.com.evil.test/example.com", "example.com")
