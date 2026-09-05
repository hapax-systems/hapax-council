"""Static IndieWeb checks for the omg.lol landing page."""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LANDING = REPO_ROOT / "agents" / "omg_web_builder" / "static" / "index.html"


def test_landing_page_has_h_card_identity_anchor() -> None:
    html = LANDING.read_text(encoding="utf-8")

    assert '<header class="h-card">' in html
    assert '<h1 class="p-name">hapax</h1>' in html
    assert 'class="subtitle p-note"' in html
    assert 'class="u-url u-uid" href="https://hapax.omg.lol"' in html
    assert 'rel="me" href="https://youtube.com/@legomena-live"' in html


def test_landing_page_has_no_obsidian_publish_link() -> None:
    html = LANDING.read_text(encoding="utf-8")

    assert "publish.obsidian.md" not in html.lower()


def test_current_copy_and_routes():
    from agents.citable_nexus.vault_content import markdown_to_html

    html = LANDING.read_text(encoding="utf-8")
    home = (REPO_ROOT / "docs/citable-nexus/home.md").read_text()
    assert markdown_to_html(home.split("\n\n", 2)[2]) in html
    assert "Research and engineering on human-agent work, authority, evidence and consent." in html
    for stale in (
        "42 tracked",
        "Forty-two",
        "shell hook",
        "agentgov",
        "weight 88/100",
        "single_user (100)",
        "executive_function (95)",
        "corporate_boundary (90)",
        "interpersonal_transparency (88)",
        "management_governance (85)",
        "March 12",
        "May 10, 2026",
        "3,041",
        "2,871",
        "0.16%",
        '<section id="data">',
        '<dl class="metric-list">',
        '<dl class="axiom-list">',
        "publish.obsidian.md",
    ):
        assert stale not in html, stale
    routes = html.split("<h2>routes</h2>", 1)[1]
    assert '<a href="/weblog">/weblog</a>' in routes
    assert '<a href="https://github.com/hapax-systems">github.com/hapax-systems</a>' in routes
    assert '<a href="mailto:hapax@omg.lol">hapax@omg.lol</a>' in routes
    assert '<a href="https://hapax.weblog.lol">weblog</a>' in html
    assert '<a href="/now">/now</a>' in html


def test_unrelated_bytes_and_routes_preserved():
    html = LANDING.read_text(encoding="utf-8")
    tail = html[html.index('<section id="vocabulary">') :]
    assert (
        hashlib.sha256(tail.encode()).hexdigest()
        == "0c3ae514dd017270d82b77c049d0be12148c5eb5a17a8d5d64d9c7f684e9ae6f"  # pragma: allowlist secret (synthetic digest pin)
    )
    css = html[: html.index('<header class="h-card">')]
    assert (
        hashlib.sha256(css.encode()).hexdigest()
        == "731d517df062ca16206b81471e524566e88adef5d43aac33e41ccade913f2db6"  # pragma: allowlist secret (synthetic digest pin)
    )


def test_landing_html_structure_and_no_network_dependencies():
    class Fragment(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.headings = []

        def handle_starttag(self, tag, attrs):
            assert tag not in ("script", "img", "iframe", "link", "object", "embed")
            assert not any(key.startswith("on") for key, _ in attrs)
            if re.fullmatch(r"h[1-6]", tag):
                self.headings.append(int(tag[1]))
            if tag not in ("br", "hr", "meta"):
                self.stack.append(tag)

        def handle_endtag(self, tag):
            assert self.stack.pop() == tag

    html = LANDING.read_text(encoding="utf-8")
    parser = Fragment()
    parser.feed(html)
    parser.close()
    assert not parser.stack
    assert parser.headings.count(1) == 1
    assert all(level == 2 for level in parser.headings[1:])
    assert not re.search(r"@import|url\s*\(", html, re.I)
