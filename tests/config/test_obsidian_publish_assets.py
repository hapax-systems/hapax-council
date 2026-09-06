"""Pin removal of the repo-owned Obsidian Publish assets."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = REPO_ROOT / "config" / "obsidian-publish"


@pytest.mark.parametrize("name", ["Home.md", "publish.css"])
def test_obsidian_publish_asset_is_absent(name: str) -> None:
    asset = ASSET_DIR / name
    assert not (asset.exists() or asset.is_symlink())
