from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"

GIB = 1024**3

CORE_MEMORY_EXPECTATIONS = {
    "hapax-reverie.service": {"high_gib": 2, "max_gib": 4},
    "visual-layer-aggregator.service": {"high_gib": 2, "max_gib": 4},
    "hapax-imagination-loop.service": {"high_gib": 2, "max_gib": 4},
    "hapax-dmn.service": {"high_gib": 2, "max_gib": 4},
    "health-monitor.service": {"high_gib": 2, "max_gib": 4},
    "dev-story-index.service": {"high_gib": 2, "max_gib": 4},
    "hapax-audio-router.service": {"high_gib": 1, "max_gib": 2},
    "knowledge-maint.service": {"high_gib": 1, "max_gib": 2},
    "llm-backup.service": {"high_gib": 1, "max_gib": 2},
    "hapax-post-merge-deploy.service": {"high_gib": 1, "max_gib": 2},
    "stimmung-sync.service": {"high_gib": 1, "max_gib": 2},
}


def test_core_services_do_not_retain_legacy_one_gib_hard_ceiling() -> None:
    for unit_name, expectation in CORE_MEMORY_EXPECTATIONS.items():
        unit = _parse_unit(UNITS_DIR / unit_name)
        memory_high = _parse_memory_bytes(unit["MemoryHigh"])
        memory_max = _parse_memory_bytes(unit["MemoryMax"])

        assert memory_high == expectation["high_gib"] * GIB
        assert memory_max == expectation["max_gib"] * GIB
        assert memory_high < memory_max
        assert memory_max > GIB, f"{unit_name} retained a 1G hard ceiling"


def _parse_unit(path: Path) -> dict[str, str]:
    assert path.is_file(), f"{path} must exist"
    values: dict[str, str] = {}
    in_service = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "[Service]":
            in_service = True
            continue
        if line.startswith("[") and line.endswith("]"):
            in_service = False
            continue
        if not in_service or not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep:
            values[key] = value
    return values


def _parse_memory_bytes(value: str) -> int:
    suffix = value[-1].upper()
    number = float(value[:-1]) if suffix in {"K", "M", "G", "T"} else float(value)
    multiplier = {
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
    }.get(suffix, 1)
    return int(number * multiplier)
