from __future__ import annotations

import configparser
import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "systemd" / "README.md"
STIMMUNG_SYNC_UNIT = REPO_ROOT / "systemd" / "units" / "stimmung-sync.service"
PROFILE_TABLE = REPO_ROOT / "config" / "root-required" / "oom-host-profiles.tsv"


def test_readme_presents_bounded_per_host_policy_as_current_truth() -> None:
    readme = README.read_text(encoding="utf-8")

    stale_current_truth = [
        "Total 63G swap on 62G RAM",
        "zram (31G zstd, priority=100) as tier-1",
        "vm.swappiness=150",
        "**128GB host memory policy**",
        "tuned for 128GB RAM",
    ]
    for phrase in stale_current_truth:
        assert phrase not in readme

    assert "**Bounded per-host memory policy**" in readme
    assert "`vm.swappiness=5`" in readme
    assert "zram saturation, global RAM pressure" in readme
    assert "read-only host receipt" in readme


def test_runtime_application_steps_are_a_separate_receipt_path() -> None:
    readme = README.read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "**Runtime application / receipt path:**" in readme
    for receipt_command in [
        "free -h",
        "zramctl --raw --output",
        "cat /proc/swaps",
        "cat /proc/sys/vm/swappiness",
        "systemctl --user show stimmung-sync.service",
    ]:
        assert receipt_command in normalized

    for runtime_mutation in [
        "sysctl writes",
        "zram-generator changes",
        "daemon reloads",
        "unit installation",
        "service restarts",
    ]:
        assert runtime_mutation in normalized


def test_profile_zram_rows_match_shipped_generator_policy() -> None:
    rows = csv.reader(PROFILE_TABLE.read_text(encoding="utf-8").splitlines(), delimiter="\t")
    seen_profiles: set[str] = set()

    for row in rows:
        if not row or row[0].startswith("#"):
            continue
        profile = row[3]
        assert profile not in seen_profiles
        seen_profiles.add(profile)
        expected_zram_mib = int(row[8])
        config = configparser.ConfigParser(interpolation=None)
        config.read(
            REPO_ROOT
            / "config"
            / "root-required"
            / "oom-host-policy"
            / profile
            / "zram-generator.conf",
            encoding="utf-8",
        )

        assert config.getint("zram0", "zram-size") == expected_zram_mib
        assert config.get("zram0", "compression-algorithm") == "zstd"

    assert seen_profiles == {"appendix", "podium"}


def test_stimmung_sync_ceiling_is_evidence_and_role_specific() -> None:
    readme = README.read_text(encoding="utf-8")
    normalized = " ".join(readme.split())
    unit = _parse_service_section(STIMMUNG_SYNC_UNIT)

    assert unit["MemoryHigh"] == "1G"
    assert unit["MemoryMax"] == "2G"

    for evidence_phrase in [
        "stimmung-sync | 2G | default | unchanged | MemoryHigh=1G",
        "`CONSTRAINT_MEMCG`",
        "old 128M hard ceiling",
        "56.9M peak",
        "MemoryMax=2G",
        "not a blanket limit increase for 128M utility timers",
    ]:
        assert evidence_phrase in normalized


def _parse_service_section(path: Path) -> dict[str, str]:
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
