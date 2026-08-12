from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "systemd" / "README.md"
STIMMUNG_SYNC_UNIT = REPO_ROOT / "systemd" / "units" / "stimmung-sync.service"


def test_readme_does_not_present_64gb_swap_policy_as_current_truth() -> None:
    readme = README.read_text(encoding="utf-8")

    stale_current_truth = [
        "Total 63G swap on 62G RAM",
        "zram (31G zstd, priority=100) as tier-1",
        "vm.swappiness=150",
    ]
    for phrase in stale_current_truth:
        assert phrase not in readme

    assert "**128GB host memory policy**" in readme
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
