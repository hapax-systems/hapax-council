"""Pin removal of the retired Obsidian Publish wrapper without executing it."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-obsidian-publish-sync"


def test_obsidian_publish_wrapper_is_absent() -> None:
    assert not (SCRIPT.exists() or SCRIPT.is_symlink())
