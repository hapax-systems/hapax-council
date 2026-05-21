"""Contract tests for the audio current-capsule freshness system.

Verifies that config/audio-current-capsule.yaml tracks the correct source
files and that the capsule staleness checker script enforces drift detection.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPSULE_PATH = REPO_ROOT / "config" / "audio-current-capsule.yaml"
STALENESS_SCRIPT = REPO_ROOT / "scripts" / "check-audio-current-capsule-staleness.py"

REQUIRED_TRACKED_SOURCES = (
    "config/audio-topology.yaml",
    "config/audio-routing.yaml",
    "config/hapax/audio-forbidden-links.conf",
    "config/hapax/audio-link-map.conf",
)


def _load_capsule() -> dict[str, object]:
    return yaml.safe_load(CAPSULE_PATH.read_text(encoding="utf-8"))


def test_capsule_file_exists() -> None:
    assert CAPSULE_PATH.exists(), "config/audio-current-capsule.yaml missing"


def test_capsule_schema_version() -> None:
    capsule = _load_capsule()
    assert capsule.get("schema_version") == 1


def test_capsule_tracks_required_audio_sources() -> None:
    capsule = _load_capsule()
    tracked = set(capsule.get("source_hashes", {}).keys())
    for source in REQUIRED_TRACKED_SOURCES:
        assert source in tracked, f"capsule does not track {source}"


def test_capsule_tracked_sources_exist_on_disk() -> None:
    capsule = _load_capsule()
    for rel_path in capsule.get("source_hashes", {}):
        assert (REPO_ROOT / rel_path).exists(), f"capsule tracks {rel_path} but file is missing"


def test_capsule_hashes_are_nonempty_hex() -> None:
    capsule = _load_capsule()
    for rel_path, h in capsule.get("source_hashes", {}).items():
        assert isinstance(h, str) and len(h) == 16, (
            f"capsule hash for {rel_path} should be 16-char hex, got {h!r}"
        )


def test_staleness_checker_script_exists() -> None:
    assert STALENESS_SCRIPT.exists(), "scripts/check-audio-current-capsule-staleness.py missing"


def test_staleness_checker_tracks_same_sources_as_capsule() -> None:
    script_text = STALENESS_SCRIPT.read_text(encoding="utf-8")
    capsule = _load_capsule()
    for rel_path in capsule.get("source_hashes", {}):
        assert rel_path in script_text, f"staleness checker does not reference {rel_path}"
