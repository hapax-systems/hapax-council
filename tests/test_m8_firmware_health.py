"""Unit tests for the M8 firmware health check.

Verifies SHM sidecar ingest, hardware-name display, staged-vs-installed
drift detection, and graceful degradation when M8 is unplugged.

cc-task: m8-system-info-firmware-ingest
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agents.health_monitor.checks import m8_firmware
from agents.health_monitor.models import Status


def _run(coro):
    return asyncio.run(coro)


def _write_info(
    path: Path,
    *,
    firmware: str = "6.5.2",
    hardware_name: str = "Production M8 Model:02",
    hardware_id: int = 3,
) -> None:
    payload = {
        "hardware_id": hardware_id,
        "hardware_name": hardware_name,
        "firmware": firmware,
        "font_mode": 0,
        "ts": "2026-05-02T03:00:00Z",
    }
    path.write_text(json.dumps(payload))


def test_no_m8_connected_returns_healthy(monkeypatch, tmp_path):
    monkeypatch.setattr(m8_firmware, "_INFO_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(m8_firmware, "_RELAY_DIR", tmp_path / "relay" / "coordination")

    results = _run(m8_firmware.check_m8_firmware())

    assert len(results) == 1
    assert results[0].name == "m8.firmware"
    assert results[0].status == Status.HEALTHY
    assert "no M8 connected" in results[0].message


def test_installed_only_no_staged_returns_healthy(monkeypatch, tmp_path):
    info_path = tmp_path / "m8-info.json"
    _write_info(info_path, firmware="6.5.2")
    monkeypatch.setattr(m8_firmware, "_INFO_PATH", info_path)
    monkeypatch.setattr(m8_firmware, "_RELAY_DIR", tmp_path / "no-such-relay")

    results = _run(m8_firmware.check_m8_firmware())

    assert results[0].status == Status.HEALTHY
    assert "Production M8 Model:02" in results[0].message
    assert "6.5.2" in results[0].message


def test_installed_matches_staged_returns_healthy(monkeypatch, tmp_path):
    info_path = tmp_path / "m8-info.json"
    _write_info(info_path, firmware="6.5.2")
    relay_dir = tmp_path / "relay" / "coordination"
    relay_dir.mkdir(parents=True)
    (relay_dir / "2026-04-26-m8-firmware-update-staged.md").write_text(
        "# Staged firmware update\n\nVersion 6.5.2 staged for bootloader entry."
    )
    monkeypatch.setattr(m8_firmware, "_INFO_PATH", info_path)
    monkeypatch.setattr(m8_firmware, "_RELAY_DIR", relay_dir)

    results = _run(m8_firmware.check_m8_firmware())

    assert results[0].status == Status.HEALTHY
    assert "6.5.2" in results[0].message


def test_installed_differs_from_staged_returns_degraded(monkeypatch, tmp_path):
    info_path = tmp_path / "m8-info.json"
    _write_info(info_path, firmware="6.4.0")
    relay_dir = tmp_path / "relay" / "coordination"
    relay_dir.mkdir(parents=True)
    (relay_dir / "2026-04-26-m8-firmware-update-staged.md").write_text(
        "# Staged firmware update\n\nVersion 6.5.2 staged for bootloader entry."
    )
    monkeypatch.setattr(m8_firmware, "_INFO_PATH", info_path)
    monkeypatch.setattr(m8_firmware, "_RELAY_DIR", relay_dir)

    results = _run(m8_firmware.check_m8_firmware())

    assert results[0].status == Status.DEGRADED
    assert "installed=6.4.0" in results[0].message
    assert "staged=6.5.2" in results[0].message


def test_corrupt_sidecar_treated_as_no_m8(monkeypatch, tmp_path):
    info_path = tmp_path / "m8-info.json"
    info_path.write_text("not valid json{")
    monkeypatch.setattr(m8_firmware, "_INFO_PATH", info_path)
    monkeypatch.setattr(m8_firmware, "_RELAY_DIR", tmp_path / "relay" / "coordination")

    results = _run(m8_firmware.check_m8_firmware())

    assert results[0].status == Status.HEALTHY
    assert "no M8 connected" in results[0].message
