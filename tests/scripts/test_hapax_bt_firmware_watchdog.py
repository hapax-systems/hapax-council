"""Tests for the MT7921 BT firmware watchdog."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-bt-firmware-watchdog"


def _load_module() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "hapax_bt_firmware_watchdog_under_test", str(SCRIPT)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def watchdog() -> types.ModuleType:
    return _load_module()


# --- Pattern detection ---------------------------------------------------


def test_detect_event_matches_wmt_command_timeout(watchdog: types.ModuleType) -> None:
    line = "Bluetooth: hci0: Execution of wmt command timed out"
    event = watchdog.detect_event(line)
    assert event is not None
    assert event.hci == "hci0"
    assert event.pattern == "Execution of wmt command timed out"


def test_detect_event_matches_failed_to_send_wmt_patch(watchdog: types.ModuleType) -> None:
    line = "Bluetooth: hci0: Failed to send wmt patch dwnld (-110)"
    event = watchdog.detect_event(line)
    assert event is not None
    assert event.hci == "hci0"
    assert event.pattern == "Failed to send wmt patch dwnld"


def test_detect_event_matches_failed_to_set_up_firmware(watchdog: types.ModuleType) -> None:
    line = "Bluetooth: hci0: Failed to set up firmware (-110)"
    event = watchdog.detect_event(line)
    assert event is not None
    assert event.hci == "hci0"
    assert event.pattern == "Failed to set up firmware"


def test_detect_event_extracts_alternate_hci_index(watchdog: types.ModuleType) -> None:
    line = "Bluetooth: hci3: Execution of wmt command timed out"
    event = watchdog.detect_event(line)
    assert event is not None
    assert event.hci == "hci3"


def test_detect_event_returns_none_for_unrelated_line(watchdog: types.ModuleType) -> None:
    line = "kernel: usb 3-1: device descriptor read/64, error -71"
    assert watchdog.detect_event(line) is None


def test_detect_event_returns_none_when_pattern_present_but_no_hci(
    watchdog: types.ModuleType,
) -> None:
    # Pattern present but no "Bluetooth: hciN:" prefix to anchor on.
    line = "kernel: Execution of wmt command timed out (somewhere)"
    assert watchdog.detect_event(line) is None


# --- HCI -> USB BDF resolution -------------------------------------------


def _stage_bluetooth_link(tmp_path: Path, *, hci: str, bus_port: str) -> Path:
    """Build a fake /sys structure where /sys/class/bluetooth/<hci>
    resolves through a symlink chain into /sys/bus/usb/devices/<bus-port>.
    Returns the simulated /sys/class/bluetooth root."""

    sys_root = tmp_path / "sys"
    bluetooth_root = sys_root / "class" / "bluetooth"
    bluetooth_root.mkdir(parents=True)
    devices_root = sys_root / "bus" / "usb" / "devices"
    devices_root.mkdir(parents=True)

    # Concrete USB device dir mirroring real layout.
    pci_chain = sys_root / "devices" / "pci0000:00" / "usb1" / bus_port
    interface = pci_chain / f"{bus_port}:1.0" / "bluetooth" / hci
    interface.mkdir(parents=True)
    (pci_chain / "idVendor").write_text("13d3", encoding="utf-8")
    (pci_chain / "idProduct").write_text("3602", encoding="utf-8")

    # /sys/class/bluetooth/<hci> -> ../../devices/.../bluetooth/<hci>
    bluetooth_root.joinpath(hci).symlink_to(interface)

    # /sys/bus/usb/devices/<bus-port> -> the same pci_chain dir, mirroring
    # how the kernel exposes the canonical bus-port name.
    devices_root.joinpath(bus_port).symlink_to(pci_chain)

    return bluetooth_root


def test_resolve_usb_bdf_walks_to_parent_usb_device(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    bluetooth_root = _stage_bluetooth_link(tmp_path, hci="hci0", bus_port="1-11")
    fake_usb_devices = tmp_path / "sys" / "bus" / "usb" / "devices"
    bus_port = watchdog.resolve_usb_bdf(
        "hci0",
        sys_class_bluetooth=bluetooth_root,
        sys_bus_usb_devices=fake_usb_devices,
    )
    assert bus_port == "1-11"


def test_resolve_usb_bdf_returns_none_when_hci_missing(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    bluetooth_root = tmp_path / "sys" / "class" / "bluetooth"
    bluetooth_root.mkdir(parents=True)
    assert watchdog.resolve_usb_bdf("hci9", sys_class_bluetooth=bluetooth_root) is None


# --- Cooldown logic ------------------------------------------------------


def test_cooldown_state_blocks_within_window(watchdog: types.ModuleType) -> None:
    state = watchdog.RecoveryState()
    state.mark_recovery("hci0", now=1000.0)
    assert state.in_cooldown("hci0", now=1100.0, cooldown_sec=300)
    assert not state.in_cooldown("hci0", now=1400.0, cooldown_sec=300)


def test_cooldown_isolated_per_hci(watchdog: types.ModuleType) -> None:
    state = watchdog.RecoveryState()
    state.mark_recovery("hci0", now=1000.0)
    assert not state.in_cooldown("hci1", now=1010.0, cooldown_sec=300)


# --- State persistence ---------------------------------------------------


def test_recovery_state_round_trips_through_path(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    state_path = tmp_path / "last-recovery.json"
    state = watchdog.RecoveryState()
    state.mark_recovery("hci0", now=1234.5)
    state.mark_recovery("hci1", now=2345.6)
    state.to_path(state_path)

    reloaded = watchdog.RecoveryState.from_path(state_path)
    assert reloaded.last_recovery == {"hci0": 1234.5, "hci1": 2345.6}


def test_recovery_state_tolerates_missing_or_malformed_file(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    assert watchdog.RecoveryState.from_path(tmp_path / "nope.json").last_recovery == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert watchdog.RecoveryState.from_path(bad).last_recovery == {}


# --- Recovery sequence ---------------------------------------------------


def _success_runner(
    out: str = "",
) -> tuple[list[list[str]], Any]:
    """Build a runner that records all argv and returns rc=0 with ``out``."""

    runs: list[list[str]] = []

    def runner(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        runs.append(argv)
        return subprocess.CompletedProcess(argv, 0, out, "")

    return runs, runner


def test_perform_recovery_dry_run_does_not_write_sysfs(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    event = watchdog.FirmwareFailureEvent(
        hci="hci0",
        pattern="Execution of wmt command timed out",
        line="Bluetooth: hci0: Execution of wmt command timed out",
    )
    writes: list[tuple[Path, str]] = []

    def writer(path: Path, value: str) -> bool:
        writes.append((path, value))
        return True

    sleeps: list[float] = []
    runs, runner = _success_runner()

    outcome = watchdog.perform_recovery(
        event,
        sys_class_bluetooth=tmp_path,
        sys_bus_usb_drivers=tmp_path / "drivers",
        sleep_fn=sleeps.append,
        runner=runner,
        sysfs_writer=writer,
        bdf_resolver=lambda hci, **_: "1-11",
        verifier=lambda **_: True,
        failure_path=tmp_path / "failure.json",
        dry_run=True,
    )
    assert outcome["dry_run"] is True
    assert outcome["bus_port"] == "1-11"
    assert outcome["unbind_attempted"] is True
    assert outcome["bind_attempted"] is True
    assert outcome["unbind_succeeded"] is False
    assert outcome["bind_succeeded"] is False
    assert writes == []
    assert sleeps == []
    assert runs == []
    # Dry-run never writes the failure status file.
    assert not (tmp_path / "failure.json").exists()


def test_perform_recovery_writes_sysfs_and_restarts_bluetooth_on_success(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    event = watchdog.FirmwareFailureEvent(
        hci="hci0",
        pattern="Execution of wmt command timed out",
        line="Bluetooth: hci0: Execution of wmt command timed out",
    )
    writes: list[tuple[Path, str]] = []

    def writer(path: Path, value: str) -> bool:
        writes.append((path, value))
        return True

    sleeps: list[float] = []
    runs, runner = _success_runner()
    drivers = tmp_path / "drivers"
    failure_path = tmp_path / "failure.json"

    outcome = watchdog.perform_recovery(
        event,
        sys_class_bluetooth=tmp_path,
        sys_bus_usb_drivers=drivers,
        sleep_fn=sleeps.append,
        runner=runner,
        sysfs_writer=writer,
        bdf_resolver=lambda hci, **_: "1-11",
        verifier=lambda **_: True,
        failure_path=failure_path,
    )
    assert outcome["bus_port"] == "1-11"
    assert outcome["unbind_succeeded"] is True
    assert outcome["bind_succeeded"] is True
    assert outcome["verify_pattern_seen"] is True
    assert outcome["escalation"] is None
    assert writes == [
        (drivers / "unbind", "1-11"),
        (drivers / "bind", "1-11"),
    ]
    # Sleeps: 2s after unbind, 5s after bind
    assert sleeps == [2, 5]
    # bluetooth.service restart happened
    assert runs == [["systemctl", "restart", "bluetooth.service"]]
    assert outcome["post_recovery_restart"] == {
        "unit": "bluetooth.service",
        "succeeded": True,
    }
    # Successful recovery does NOT write the operator escalation file.
    assert not failure_path.exists()


def test_perform_recovery_escalates_when_verify_fails(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    event = watchdog.FirmwareFailureEvent(
        hci="hci0",
        pattern="Failed to send wmt patch dwnld",
        line="Bluetooth: hci0: Failed to send wmt patch dwnld (-110)",
    )

    def writer(path: Path, value: str) -> bool:
        return True

    runs, runner = _success_runner()
    failure_path = tmp_path / "failure.json"
    fixed_now = 1700000000.0

    outcome = watchdog.perform_recovery(
        event,
        sys_class_bluetooth=tmp_path,
        sys_bus_usb_drivers=tmp_path / "drivers",
        sleep_fn=lambda _: None,
        runner=runner,
        sysfs_writer=writer,
        bdf_resolver=lambda hci, **_: "1-11",
        verifier=lambda **_: False,
        failure_path=failure_path,
        now_fn=lambda: fixed_now,
    )
    # Both rebind steps ran successfully...
    assert outcome["unbind_succeeded"] is True
    assert outcome["bind_succeeded"] is True
    # ... but the verifier reported the rebind was insufficient.
    assert outcome["verify_pattern_seen"] is False
    assert outcome["escalation"] == "rebind-insufficient"
    # bluetooth.service must NOT be restarted on verify-failure.
    assert outcome["post_recovery_restart"] is None
    assert runs == []
    # Escalation status file is written with the operator-facing fields.
    assert failure_path.exists()
    payload = json.loads(failure_path.read_text(encoding="utf-8"))
    assert payload["hci"] == "hci0"
    assert payload["bus_port"] == "1-11"
    assert payload["escalation"] == "rebind-insufficient"
    assert payload["rebind_succeeded"] is True
    assert payload["verify_pattern_seen"] is False
    assert payload["timestamp"] == fixed_now


def test_perform_recovery_escalates_when_no_usb_bdf(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    event = watchdog.FirmwareFailureEvent(
        hci="hci9",
        pattern="Failed to set up firmware",
        line="Bluetooth: hci9: Failed to set up firmware (-110)",
    )

    def writer(path: Path, value: str) -> bool:
        raise AssertionError("must not write sysfs without a BDF")

    runs, runner = _success_runner()
    failure_path = tmp_path / "failure.json"

    outcome = watchdog.perform_recovery(
        event,
        sys_class_bluetooth=tmp_path,
        sys_bus_usb_drivers=tmp_path / "drivers",
        sleep_fn=lambda _: None,
        runner=runner,
        sysfs_writer=writer,
        bdf_resolver=lambda hci, **_: None,
        verifier=lambda **_: True,
        failure_path=failure_path,
    )
    assert outcome["bus_port"] is None
    assert outcome["unbind_attempted"] is False
    assert outcome["bind_attempted"] is False
    assert outcome["escalation"] == "no-usb-bdf"
    assert runs == []
    assert failure_path.exists()
    payload = json.loads(failure_path.read_text(encoding="utf-8"))
    assert payload["escalation"] == "no-usb-bdf"
    assert payload["bus_port"] is None


# --- verify_recovery -----------------------------------------------------


def test_verify_recovery_sees_success_pattern(watchdog: types.ModuleType) -> None:
    captured: list[list[str]] = []

    def runner(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        captured.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            "Bluetooth: hci0: HW/SW Version: 0x12345678\n",
            "",
        )

    assert watchdog.verify_recovery(hci="hci0", runner=runner) is True
    # journalctl was called with --since covering the verify window
    assert captured and captured[0][0] == "journalctl"


def test_verify_recovery_treats_repeat_timeout_as_failure(
    watchdog: types.ModuleType,
) -> None:
    def runner(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            0,
            (
                "Bluetooth: hci0: HW/SW Version: 0x12345678\n"
                "Bluetooth: hci0: Execution of wmt command timed out\n"
            ),
            "",
        )

    # Even though the success pattern shows up, a fresh timeout in the
    # same window means the rebind did not stick.
    assert watchdog.verify_recovery(hci="hci0", runner=runner) is False


def test_verify_recovery_returns_false_on_journalctl_error(
    watchdog: types.ModuleType,
) -> None:
    def runner(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "boom")

    assert watchdog.verify_recovery(hci="hci0", runner=runner) is False


# --- watch_loop integration ----------------------------------------------


def test_watch_loop_skips_during_cooldown(watchdog: types.ModuleType, tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    failure_path = tmp_path / "failure.json"

    lines = [
        watchdog.JournalLine("Bluetooth: hci0: Execution of wmt command timed out"),
        watchdog.JournalLine("Bluetooth: hci0: Execution of wmt command timed out"),
    ]
    times = iter([1000.0, 1050.0])
    invocations: list[str] = []

    def fake_recovery(event: Any, **_: Any) -> dict[str, Any]:
        invocations.append(event.hci)
        return {"hci": event.hci, "ok": True}

    count = watchdog.watch_loop(
        state_path=state_path,
        failure_path=failure_path,
        cooldown_sec=300,
        dry_run=True,
        lines=lines,
        now_fn=lambda: next(times),
        recovery_fn=fake_recovery,
    )
    assert count == 1, "second event must be skipped due to 300s cooldown"
    assert invocations == ["hci0"]
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert "hci0" in persisted["last_recovery"]


def test_watch_loop_recovers_distinct_hcis(watchdog: types.ModuleType, tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    failure_path = tmp_path / "failure.json"
    lines = [
        watchdog.JournalLine("Bluetooth: hci0: Execution of wmt command timed out"),
        watchdog.JournalLine("Bluetooth: hci1: Failed to set up firmware (-110)"),
    ]
    invocations: list[str] = []

    def fake_recovery(event: Any, **_: Any) -> dict[str, Any]:
        invocations.append(event.hci)
        return {"hci": event.hci, "ok": True}

    count = watchdog.watch_loop(
        state_path=state_path,
        failure_path=failure_path,
        cooldown_sec=300,
        dry_run=True,
        lines=lines,
        now_fn=lambda: 1000.0,
        recovery_fn=fake_recovery,
    )
    assert count == 2
    assert invocations == ["hci0", "hci1"]


def test_watch_loop_ignores_non_matching_lines(watchdog: types.ModuleType, tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    failure_path = tmp_path / "failure.json"
    lines = [
        watchdog.JournalLine("kernel: random thing happened"),
        watchdog.JournalLine("usb 3-1: New high-speed USB device"),
    ]
    invocations: list[str] = []

    def fake_recovery(event: Any, **_: Any) -> dict[str, Any]:
        invocations.append(event.hci)
        return {"hci": event.hci, "ok": True}

    count = watchdog.watch_loop(
        state_path=state_path,
        failure_path=failure_path,
        cooldown_sec=300,
        dry_run=True,
        lines=lines,
        now_fn=lambda: 1000.0,
        recovery_fn=fake_recovery,
    )
    assert count == 0
    assert invocations == []


# --- CLI surface ---------------------------------------------------------


def test_cli_dry_run_via_input_file(tmp_path: Path) -> None:
    """Smoke-test the CLI: --dry-run against a fixture journal."""
    state_path = tmp_path / "state.json"
    failure_path = tmp_path / "failure.json"
    journal = tmp_path / "journal.txt"
    journal.write_text(
        "Bluetooth: hci0: Execution of wmt command timed out\n"
        "unrelated stuff\n"
        "Bluetooth: hci0: Failed to set up firmware (-110)\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--state-file",
            str(state_path),
            "--failure-file",
            str(failure_path),
            "--cooldown-sec",
            "300",
            "--dry-run",
            "--input-file",
            str(journal),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "firmware-failure pattern" in proc.stdout
    assert "skipping hci0 (cooldown active)" in proc.stdout
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert "hci0" in persisted["last_recovery"]
    # In dry-run mode the failure file is not written even on a no-bdf
    # path because dry-run short-circuits before sysfs writes.
    assert not failure_path.exists()
