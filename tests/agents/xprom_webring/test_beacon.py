"""Tests for ``agents.xprom_webring.render_beacon``."""

from __future__ import annotations

from agents.xprom_webring import (
    ORCID_BASE,
    WEBRING_REL,
    render_beacon,
)


def test_render_basic_beacon_includes_orcid_link():
    beacon = render_beacon(orcid_id="0000-0001-2345-6789")
    assert 'rel="webring me"' in beacon.html
    assert "0000-0001-2345-6789" in beacon.html
    assert ORCID_BASE in beacon.html
    assert beacon.has_prev_next is False


def test_render_with_webring_home_link():
    beacon = render_beacon(
        orcid_id="0000-0001-2345-6789",
        webring_url="https://example.org/ring",
    )
    assert 'rel="webring"' in beacon.html
    assert "https://example.org/ring" in beacon.html


def test_render_with_prev_next_navigation():
    beacon = render_beacon(
        orcid_id="0000-0001-2345-6789",
        prev_url="https://prev.example.org",
        next_url="https://next.example.org",
    )
    assert 'rel="webring prev"' in beacon.html
    assert 'rel="webring next"' in beacon.html
    assert beacon.has_prev_next is True


def test_render_accepts_full_orcid_url():
    beacon = render_beacon(orcid_id="https://orcid.org/0000-0001-2345-6789")
    # No double-prefix
    assert "https://orcid.org/https://orcid.org/" not in beacon.html
    assert "https://orcid.org/0000-0001-2345-6789" in beacon.html


def test_render_accepts_bare_orcid_id():
    # Without https://orcid.org/ prefix
    beacon = render_beacon(orcid_id="0000-0001-2345-6789")
    assert ORCID_BASE + "0000-0001-2345-6789" in beacon.html


def test_render_strips_whitespace_from_orcid():
    beacon = render_beacon(orcid_id="  0000-0001-2345-6789  ")
    assert beacon.html.count("  0000-0001-2345-6789  ") == 0


def test_render_html_structure_valid():
    beacon = render_beacon(orcid_id="0000-0001-2345-6789")
    assert beacon.html.startswith("<nav")
    assert beacon.html.endswith("</nav>")
    assert "<a " in beacon.html


def test_constants_match_expected_values():
    assert ORCID_BASE == "https://orcid.org/"
    assert WEBRING_REL == "webring"
