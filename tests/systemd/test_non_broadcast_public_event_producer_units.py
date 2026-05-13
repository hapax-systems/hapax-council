"""Static checks for non-broadcast public-event producer units.

These tests deliberately do not call live systemd. They pin source residency
and bus-first defaults for producers that can increase public-event volume.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = REPO_ROOT / "systemd"
UNITS_DIR = SYSTEMD_ROOT / "units"

PRODUCER_UNITS = {
    "hapax-weblog-publish-public-event-producer.service": (
        "agents.weblog_publish_public_event_producer"
    ),
    "hapax-governance-enforcement-event-producer.service": (
        "agents.governance_enforcement_public_event_producer"
    ),
    "hapax-chronicle-high-salience-public-event-producer.service": (
        "agents.chronicle_high_salience_public_event_producer"
    ),
    "hapax-velocity-digest.service": "agents.velocity_digest_public_event_producer",
}


def _read_unit(name: str) -> str:
    return (UNITS_DIR / name).read_text(encoding="utf-8")


def _raw_keys(path: Path, section: str, key: str) -> list[str]:
    in_section = False
    values: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == f"[{section}]"
            continue
        if not in_section or not stripped or stripped.startswith(("#", ";")):
            continue
        raw_key, sep, raw_value = stripped.partition("=")
        if sep and raw_key.strip() == key:
            values.append(raw_value.strip())
    return values


def test_non_broadcast_producer_units_live_under_units_dir_only() -> None:
    for unit in [*PRODUCER_UNITS, "hapax-velocity-digest.timer"]:
        assert (UNITS_DIR / unit).exists(), f"{unit} must live under systemd/units"
        assert not (SYSTEMD_ROOT / unit).exists(), f"{unit} shadows systemd/units"


def test_non_broadcast_producer_units_execute_expected_modules() -> None:
    for unit, module in PRODUCER_UNITS.items():
        body = _read_unit(unit)
        assert f"-m {module}" in body
        assert "HAPAX_RESEARCH_VEHICLE_PUBLIC_EVENT_PATH" in body


def test_weblog_unit_keeps_direct_posse_disabled_by_default() -> None:
    exec_starts = _raw_keys(
        UNITS_DIR / "hapax-weblog-publish-public-event-producer.service",
        "Service",
        "ExecStart",
    )
    assert exec_starts == [
        "%h/.cache/hapax/source-activation/worktree/.venv/bin/python "
        "-m agents.weblog_publish_public_event_producer --no-posse"
    ]


def test_velocity_digest_timer_pairs_with_source_service() -> None:
    timer = UNITS_DIR / "hapax-velocity-digest.timer"
    target = _raw_keys(timer, "Timer", "Unit")
    assert target in ([], ["hapax-velocity-digest.service"])
    assert (UNITS_DIR / "hapax-velocity-digest.service").exists()


def test_chronicle_unit_is_rvpe_producer_only() -> None:
    body = _read_unit("hapax-chronicle-high-salience-public-event-producer.service")
    assert "agents.chronicle_high_salience_public_event_producer" in body
    assert "HAPAX_CHRONICLE_EVENTS_PATH=/dev/shm/hapax-chronicle/events.jsonl" in body
    assert "--posse" not in body
    assert "bridgy" not in body.lower()
