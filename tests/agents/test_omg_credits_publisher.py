"""Tests for agents/omg_credits_publisher — ytb-OMG-CREDITS.

Verifies the credits publisher's three stages:

  1. Data assembly — read the aesthetic library's manifest + provenance
     into a credits-page data model with one row per asset.
  2. Template render — Jinja template produces E-panel-styled HTML with
     every asset in a table + per-license attribution footer.
  3. Publish flow — the OmgLolClient is invoked with the correct
     (slug, content, title, listed) shape; hash-dedup skips unchanged
     republish.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from agents.omg_credits_publisher.data import (
    build_credits_model,
)
from agents.omg_credits_publisher.publisher import (
    OmgCreditsPublisher,
    render_credits_html,
)


@pytest.fixture
def fake_library_root(tmp_path: Path) -> Path:
    """Build a minimal aesthetic-library fixture tree with manifest +
    provenance matching the AUTH1 shape."""
    root = tmp_path / "aesthetic-library"
    root.mkdir()

    # BitchX group
    banner = root / "bitchx" / "splash" / "banner.txt"
    banner.parent.mkdir(parents=True)
    banner.write_bytes(b"BitchX banner\n")
    banner_sha = hashlib.sha256(b"BitchX banner\n").hexdigest()
    (root / "bitchx" / "provenance.yaml").write_text(
        "source: bitchx\n"
        "source_url: https://github.com/prime001/BitchX\n"
        'extracted_date: "2026-04-24"\n'
        "original_author: panasync + EPIC Software Labs\n"
        "license: BSD-3-Clause\n"
        'attribution_line: "BitchX (panasync, BSD-3)"\n'
    )

    # Fonts group
    font = root / "fonts" / "Px437.ttf"
    font.parent.mkdir(parents=True)
    font.write_bytes(b"FAKE-TTF-BYTES")
    font_sha = hashlib.sha256(b"FAKE-TTF-BYTES").hexdigest()
    (root / "fonts" / "provenance.yaml").write_text(
        "source: fonts\n"
        "source_url: https://int10h.org/oldschool-pc-fonts/\n"
        'extracted_date: "2026-04-24"\n'
        "original_author: VileR\n"
        "license: CC-BY-SA-4.0\n"
        'attribution_line: "Px437 (VileR, CC-BY-SA-4.0)"\n'
    )

    manifest = {
        "assets": [
            {
                "source": "bitchx",
                "kind": "splash",
                "name": "banner",
                "path": "bitchx/splash/banner.txt",
                "sha256": banner_sha,
                "license": "BSD-3-Clause",
                "author": "panasync + EPIC Software Labs",
                "source_url": "https://github.com/prime001/BitchX",
                "extracted_date": "2026-04-24",
            },
            {
                "source": "fonts",
                "kind": "font",
                "name": "px437",
                "path": "fonts/Px437.ttf",
                "sha256": font_sha,
                "license": "CC-BY-SA-4.0",
                "author": "VileR",
                "source_url": "https://int10h.org/oldschool-pc-fonts/",
                "extracted_date": "2026-04-24",
            },
        ]
    }
    (root / "_manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    return root


class TestBuildCreditsModel:
    def test_collects_one_entry_per_asset(self, fake_library_root: Path) -> None:
        model = build_credits_model(fake_library_root)
        assert len(model.assets) == 2
        names = {a.name for a in model.assets}
        assert names == {"banner", "px437"}

    def test_attribution_line_comes_from_provenance(self, fake_library_root: Path) -> None:
        model = build_credits_model(fake_library_root)
        bitchx = next(a for a in model.assets if a.name == "banner")
        assert "panasync" in bitchx.attribution_line
        assert "BSD-3" in bitchx.attribution_line

    def test_license_groups_unique_licenses(self, fake_library_root: Path) -> None:
        model = build_credits_model(fake_library_root)
        licenses = {a.license for a in model.assets}
        assert licenses == {"BSD-3-Clause", "CC-BY-SA-4.0"}
        assert "BSD-3-Clause" in model.licenses_present
        assert "CC-BY-SA-4.0" in model.licenses_present

    def test_missing_library_returns_empty_model(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does-not-exist"
        model = build_credits_model(nonexistent)
        assert model.assets == []


class TestRenderCreditsHtml:
    def test_html_contains_every_asset(self, fake_library_root: Path) -> None:
        model = build_credits_model(fake_library_root)
        html = render_credits_html(model)
        assert "banner" in html
        assert "px437" in html

    def test_html_contains_license_attribution(self, fake_library_root: Path) -> None:
        model = build_credits_model(fake_library_root)
        html = render_credits_html(model)
        assert "BSD-3-Clause" in html
        assert "CC-BY-SA-4.0" in html

    def test_html_has_epanel_stylesheet_link(self, fake_library_root: Path) -> None:
        model = build_credits_model(fake_library_root)
        html = render_credits_html(model)
        assert "ryanklee.github.io/hapax-assets" in html

    def test_html_has_epanel_structural_element(self, fake_library_root: Path) -> None:
        model = build_credits_model(fake_library_root)
        html = render_credits_html(model)
        assert "e-window" in html


class TestPublisher:
    def _make_mock_client(self) -> MagicMock:
        client = MagicMock()
        client.enabled = True
        client.set_paste.return_value = {
            "request": {"statusCode": 200},
            "response": {"slug": "credits"},
        }
        return client

    def test_publish_calls_set_paste_with_credits_slug(
        self, fake_library_root: Path, tmp_path: Path
    ) -> None:
        client = self._make_mock_client()
        publisher = OmgCreditsPublisher(
            library_root=fake_library_root,
            state_file=tmp_path / "state.json",
            client=client,
            address="hapax",
        )
        outcome = publisher.publish()

        assert outcome == "published"
        client.set_paste.assert_called_once()
        call = client.set_paste.call_args
        assert call.kwargs["title"] == "credits"
        assert call.kwargs.get("content")

    def test_hash_dedup_skips_unchanged(self, fake_library_root: Path, tmp_path: Path) -> None:
        client = self._make_mock_client()
        publisher = OmgCreditsPublisher(
            library_root=fake_library_root,
            state_file=tmp_path / "state.json",
            client=client,
            address="hapax",
        )

        first = publisher.publish()
        second = publisher.publish()

        assert first == "published"
        assert second == "skipped"
        assert client.set_paste.call_count == 1

    def test_dry_run_does_not_call_client(self, fake_library_root: Path, tmp_path: Path) -> None:
        client = self._make_mock_client()
        publisher = OmgCreditsPublisher(
            library_root=fake_library_root,
            state_file=tmp_path / "state.json",
            client=client,
            address="hapax",
        )
        outcome = publisher.publish(dry_run=True)

        assert outcome == "dry-run"
        client.set_paste.assert_not_called()

    def test_publish_with_disabled_client_returns_skipped(
        self, fake_library_root: Path, tmp_path: Path
    ) -> None:
        client = MagicMock()
        client.enabled = False
        publisher = OmgCreditsPublisher(
            library_root=fake_library_root,
            state_file=tmp_path / "state.json",
            client=client,
            address="hapax",
        )
        outcome = publisher.publish()
        assert outcome == "client-disabled"
        client.set_paste.assert_not_called()

    def test_publish_content_change_triggers_republish(
        self, fake_library_root: Path, tmp_path: Path
    ) -> None:
        client = self._make_mock_client()
        publisher = OmgCreditsPublisher(
            library_root=fake_library_root,
            state_file=tmp_path / "state.json",
            client=client,
            address="hapax",
        )
        publisher.publish()

        manifest_path = fake_library_root / "_manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["assets"].append(
            {
                "source": "bitchx",
                "kind": "quotes",
                "name": "quit",
                "path": "bitchx/quotes/quit.txt",
                "sha256": "0" * 64,
                "license": "BSD-3-Clause",
                "author": "panasync",
                "source_url": "https://github.com/prime001/BitchX",
                "extracted_date": "2026-04-24",
            }
        )
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

        second = publisher.publish()
        assert second == "published"
        assert client.set_paste.call_count == 2

    def test_publish_records_content_hash_in_state(
        self, fake_library_root: Path, tmp_path: Path
    ) -> None:
        state_file = tmp_path / "state.json"
        client = self._make_mock_client()
        publisher = OmgCreditsPublisher(
            library_root=fake_library_root,
            state_file=state_file,
            client=client,
            address="hapax",
        )
        publisher.publish()

        import json

        state = json.loads(state_file.read_text())
        assert "last_content_sha256" in state
        assert len(state["last_content_sha256"]) == 64


class TestEnd2End:
    def test_full_flow_empty_library_skips_without_error(self, tmp_path: Path) -> None:
        client = MagicMock()
        client.enabled = True
        publisher = OmgCreditsPublisher(
            library_root=tmp_path / "empty",
            state_file=tmp_path / "state.json",
            client=client,
            address="hapax",
        )
        outcome = publisher.publish()
        assert outcome == "empty-library"
        client.set_paste.assert_not_called()
