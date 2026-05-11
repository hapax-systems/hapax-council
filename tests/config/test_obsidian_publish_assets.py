"""Static checks for Obsidian Publish asset contracts."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = REPO_ROOT / "config" / "obsidian-publish"


def test_home_page_is_publishable_and_indieweb_identified() -> None:
    home = (ASSET_DIR / "Home.md").read_text(encoding="utf-8")

    assert "publish: true" in home
    assert 'class="h-card"' in home
    assert 'class="p-name"' in home
    assert 'class="u-url u-uid"' in home
    assert "https://publish.obsidian.md/hapax" in home
    assert "hapax.omg.lol" in home


def test_publish_css_uses_gruvbox_hard_dark_contract() -> None:
    css = (ASSET_DIR / "publish.css").read_text(encoding="utf-8")

    assert "--hapax-bg-hard: #1d2021;" in css
    assert "--hapax-bg: #282828;" in css
    assert "--hapax-fg: #ebdbb2;" in css
    assert "--hapax-yellow: #fabd2f;" in css
    assert "--hapax-aqua: #8ec07c;" in css
    assert ".published-container" in css
    assert ".h-card" in css
