"""Static IndieWeb checks for the omg.lol landing page."""

from __future__ import annotations

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
