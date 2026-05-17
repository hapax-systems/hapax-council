"""Contract tests for the L-12 critical USB anti-suspend guard."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "hapax-l12-critical-usb-guard"
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-l12-critical-usb-guard.service"


def _load_guard_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_l12_critical_usb_guard", str(GUARD))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _make_l12_sysfs(root: Path) -> dict[str, Path]:
    sysroot = root / "sys"
    device = sysroot / "devices/pci0000:00/0000:00:08.3/0000:74:00.0/usb9/9-1"
    port = sysroot / "devices/pci0000:00/0000:00:08.3/0000:74:00.0/usb9/9-0:1.0/usb9-port1"
    device.mkdir(parents=True)
    port.mkdir(parents=True)
    bus_link = sysroot / "bus/usb/devices/9-1"
    bus_link.parent.mkdir(parents=True, exist_ok=True)
    bus_link.symlink_to(device)
    (device / "port").symlink_to(port)

    _write(device / "idVendor", "1686\n")
    _write(device / "idProduct", "03d5\n")
    _write(device / "serial", "8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF\n")

    nodes = {
        "root_port": sysroot / "devices/pci0000:00/0000:00:08.3",
        "xhci": sysroot / "devices/pci0000:00/0000:00:08.3/0000:74:00.0",
        "usb_root": sysroot / "devices/pci0000:00/0000:00:08.3/0000:74:00.0/usb9",
        "port": port,
        "device": device,
    }
    for node in nodes.values():
        _write(node / "power/control", "auto\n")
        _write(node / "power/autosuspend_delay_ms", "100\n")
    return {"sysroot": sysroot, **nodes}


def test_guard_pins_l12_device_and_parent_chain(tmp_path: Path) -> None:
    paths = _make_l12_sysfs(tmp_path)
    state = tmp_path / "state.json"

    result = subprocess.run(
        [str(GUARD), "--sysfs-root", str(paths["sysroot"]), "--state-path", str(state)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    for key in ("root_port", "xhci", "usb_root", "port", "device"):
        assert (paths[key] / "power/control").read_text(encoding="utf-8").strip() == "on"
        assert (paths[key] / "power/autosuspend_delay_ms").read_text(
            encoding="utf-8"
        ).strip() == "-1"

    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["device_found"] is True
    assert payload["device_count"] == 1
    guarded_nodes = {
        action["node"]
        for result_payload in payload["results"]
        for action in result_payload["actions"]
    }
    assert str(paths["port"]) in guarded_nodes
    assert str(paths["device"]) in guarded_nodes
    assert str(paths["usb_root"]) in guarded_nodes
    assert str(paths["xhci"]) in guarded_nodes
    assert str(paths["sysroot"] / "devices/pci0000:00") not in guarded_nodes
    assert str(paths["sysroot"] / "devices") not in guarded_nodes


def test_guard_absent_records_status_without_false_failure(tmp_path: Path) -> None:
    sysroot = tmp_path / "sys"
    (sysroot / "bus/usb/devices").mkdir(parents=True)
    state = tmp_path / "state.json"

    result = subprocess.run(
        [str(GUARD), "--sysfs-root", str(sysroot), "--state-path", str(state)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["device_found"] is False
    assert payload["results"] == []


def test_guard_prepares_shared_state_directory_for_user_witness(tmp_path: Path) -> None:
    guard = _load_guard_module()
    shared_dir = tmp_path / "hapax-usb"
    state_path = shared_dir / "l12-critical-guard.json"

    guard.prepare_state_parent(state_path, shared_state_dir=shared_dir)

    assert shared_dir.stat().st_mode & 0o777 == 0o775


def test_guard_tolerates_unsupported_parent_delay_knob(tmp_path: Path) -> None:
    paths = _make_l12_sysfs(tmp_path)
    delay = paths["xhci"] / "power/autosuspend_delay_ms"
    delay.unlink()
    delay.mkdir()
    state = tmp_path / "state.json"

    result = subprocess.run(
        [str(GUARD), "--sysfs-root", str(paths["sysroot"]), "--state-path", str(state)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (paths["xhci"] / "power/control").read_text(encoding="utf-8").strip() == "on"
    payload = json.loads(state.read_text(encoding="utf-8"))
    delay_writes = [
        write
        for result_payload in payload["results"]
        for action in result_payload["actions"]
        for write in action["writes"]
        if write["path"].endswith("autosuspend_delay_ms")
    ]
    assert any(write["error"] and write["required"] is False for write in delay_writes)


def test_guard_can_fail_when_presence_is_required(tmp_path: Path) -> None:
    sysroot = tmp_path / "sys"
    state = tmp_path / "state.json"
    (sysroot / "bus/usb/devices").mkdir(parents=True)

    result = subprocess.run(
        [
            str(GUARD),
            "--sysfs-root",
            str(sysroot),
            "--state-path",
            str(state),
            "--require-present",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "L-12 not present" in result.stderr


def test_guard_unit_prepares_shared_usb_tmpfs_for_user_witness() -> None:
    text = UNIT.read_text(encoding="utf-8")

    assert "ExecStartPre=/usr/bin/install -d -o root -g hapax -m 0775 /dev/shm/hapax-usb" in text
    assert "UMask=0002" in text
    assert "ReadWritePaths=/sys /dev/shm/hapax-usb" in text
