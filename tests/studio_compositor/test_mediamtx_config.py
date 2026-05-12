"""Static pins for the local MediaMTX relay config."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / "config" / "mediamtx.yml"


def _config() -> dict[str, object]:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_mediamtx_accepts_desktop_and_mobile_publish_paths() -> None:
    config = _config()

    paths = config["paths"]
    assert isinstance(paths, dict)
    assert paths["studio"]["source"] == "publisher"
    assert paths["mobile"]["source"] == "publisher"


def test_mediamtx_read_timeout_covers_async_rtmp_connect_window() -> None:
    config = _config()

    assert config["rtmp"] is True
    assert config["rtmpAddress"] == "127.0.0.1:1935"
    assert config["readTimeout"] == "60s"


def test_mediamtx_exposes_local_hls_for_studio_readiness() -> None:
    config = _config()

    assert config["hls"] is True
    assert config["hlsAddress"] == "127.0.0.1:8888"
