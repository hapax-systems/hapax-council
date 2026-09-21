"""Static absence checks for the withdrawn Obsidian Publish units."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("suffix", ["service", "timer"])
def test_obsidian_publish_unit_is_absent(suffix: str) -> None:
    unit = REPO_ROOT / "systemd" / "units" / f"hapax-obsidian-publish-sync.{suffix}"
    assert not (unit.exists() or unit.is_symlink())


def test_obsidian_publish_is_absent_from_preset() -> None:
    preset = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"
    assert "hapax-obsidian-publish" not in preset.read_text(encoding="utf-8").lower()
