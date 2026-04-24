"""Tests for agents/hapax_assets_publisher/config.py — ytb-AUTH-HOSTING."""

from __future__ import annotations

from pathlib import Path

import pytest  # noqa: TC002

from agents.hapax_assets_publisher.config import PublisherConfig


class TestPublisherConfig:
    def test_defaults(self) -> None:
        cfg = PublisherConfig()
        assert cfg.remote_url == "git@github.com:ryanklee/hapax-assets.git"
        assert cfg.branch == "main"
        assert cfg.min_push_interval_sec == 30
        assert cfg.source_dir.name == "aesthetic-library"

    def test_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_ASSETS_REMOTE_URL", "git@example.com:me/assets.git")
        monkeypatch.setenv("HAPAX_ASSETS_BRANCH", "trunk")
        monkeypatch.setenv("HAPAX_ASSETS_MIN_PUSH_INTERVAL_SEC", "60")

        cfg = PublisherConfig.from_env()

        assert cfg.remote_url == "git@example.com:me/assets.git"
        assert cfg.branch == "trunk"
        assert cfg.min_push_interval_sec == 60

    def test_checkout_dir_under_xdg_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("HAPAX_ASSETS_CHECKOUT_DIR", raising=False)
        cfg = PublisherConfig.from_env()
        assert ".cache/hapax" in str(cfg.checkout_dir)
