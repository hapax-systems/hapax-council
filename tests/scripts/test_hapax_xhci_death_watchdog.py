"""Tests for the xHCI controller death watchdog."""

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
SCRIPT = REPO_ROOT / "scripts" / "hapax-xhci-death-watchdog"


def _load_module() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "hapax_xhci_death_watchdog_under_test", str(SCRIPT)
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


def test_detect_event_matches_hc_died_with_bdf(watchdog: types.ModuleType) -> None:
    # The kernel emits the death pattern split across two lines (one declaring
    # not-responding, one declaring HC-died). detect_event matches the
    # canonical "HC died" line on its own.
    line_single = "kernel: xhci_hcd 0000:71:00.0: HC died; cleaning up"
    event = watchdog.detect_event(line_single)
    assert event is not None
    assert event.bdf == "0000:71:00.0"
    assert event.pattern == "HC died"


def test_detect_event_matches_abort_failed(watchdog: types.ModuleType) -> None:
    line = "kernel: xhci_hcd 0000:71:00.0: Abort failed to stop command ring: -110"
    event = watchdog.detect_event(line)
    assert event is not None
    assert event.bdf == "0000:71:00.0"
    assert event.pattern == "Abort failed to stop command ring"


def test_detect_event_extracts_alternate_bdf(watchdog: types.ModuleType) -> None:
    """BDF regex must accept any function digit, including hex like '0xa'."""
    line = "xhci_hcd 0001:0a:00.7: HC died; cleaning up"
    event = watchdog.detect_event(line)
    assert event is not None
    assert event.bdf == "0001:0a:00.7"


def test_detect_event_returns_none_for_unrelated_line(watchdog: types.ModuleType) -> None:
    line = "kernel: usb 3-1: device descriptor read/64, error -71"
    assert watchdog.detect_event(line) is None


def test_detect_event_returns_none_when_pattern_present_but_no_bdf(
    watchdog: types.ModuleType,
) -> None:
    line = "kernel: HC died on something unrelated"
    assert watchdog.detect_event(line) is None


def test_detect_event_supports_custom_pattern(watchdog: types.ModuleType) -> None:
    line = "xhci_hcd 0000:71:00.0: cookie crumbled"
    event = watchdog.detect_event(line, patterns=("cookie crumbled",))
    assert event is not None
    assert event.pattern == "cookie crumbled"


# --- Cooldown logic ------------------------------------------------------


def test_cooldown_state_blocks_within_window(watchdog: types.ModuleType) -> None:
    state = watchdog.RecoveryState()
    state.mark_recovery("0000:71:00.0", now=1000.0)
    assert state.in_cooldown("0000:71:00.0", now=1100.0, cooldown_sec=180)
    assert not state.in_cooldown("0000:71:00.0", now=1200.0, cooldown_sec=180)


def test_cooldown_isolated_per_bdf(watchdog: types.ModuleType) -> None:
    state = watchdog.RecoveryState()
    state.mark_recovery("0000:71:00.0", now=1000.0)
    assert not state.in_cooldown("0000:72:00.0", now=1010.0, cooldown_sec=180)


# --- State persistence ---------------------------------------------------


def test_recovery_state_round_trips_through_path(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    state_path = tmp_path / "last-recovery.json"
    state = watchdog.RecoveryState()
    state.mark_recovery("0000:71:00.0", now=1234.5)
    state.mark_recovery("0000:72:00.0", now=2345.6)
    state.to_path(state_path)

    reloaded = watchdog.RecoveryState.from_path(state_path)
    assert reloaded.last_recovery == {
        "0000:71:00.0": 1234.5,
        "0000:72:00.0": 2345.6,
    }


def test_recovery_state_tolerates_missing_file(watchdog: types.ModuleType, tmp_path: Path) -> None:
    state = watchdog.RecoveryState.from_path(tmp_path / "nope.json")
    assert state.last_recovery == {}


def test_recovery_state_tolerates_malformed_file(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    state_path = tmp_path / "malformed.json"
    state_path.write_text("{not json", encoding="utf-8")
    state = watchdog.RecoveryState.from_path(state_path)
    assert state.last_recovery == {}


# --- Recovery sequence ---------------------------------------------------


def test_perform_recovery_dry_run_does_not_write_sysfs(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    sys_root = tmp_path / "sys-bus-pci"
    (sys_root / "devices" / "0000:71:00.0").mkdir(parents=True)
    writes: list[tuple[Path, str]] = []

    def writer(path: Path, value: str) -> bool:
        writes.append((path, value))
        return True

    sleeps: list[float] = []
    runs: list[list[str]] = []

    def runner(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        runs.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    outcome = watchdog.perform_recovery(
        "0000:71:00.0",
        sys_pci_root=sys_root,
        sleep_fn=sleeps.append,
        runner=runner,
        sysfs_writer=writer,
        dry_run=True,
    )
    assert outcome["dry_run"] is True
    assert outcome["remove_attempted"] is True
    assert outcome["rescan_attempted"] is True
    assert outcome["remove_succeeded"] is False
    assert outcome["rescan_succeeded"] is False
    assert writes == []
    assert sleeps == []
    assert runs == []


def test_perform_recovery_writes_sysfs_and_restarts_units(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    sys_root = tmp_path / "sys-bus-pci"
    pci_dev = sys_root / "devices" / "0000:71:00.0"
    pci_dev.mkdir(parents=True)
    writes: list[tuple[Path, str]] = []

    def writer(path: Path, value: str) -> bool:
        writes.append((path, value))
        return True

    sleeps: list[float] = []
    runs: list[list[str]] = []

    def runner(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        runs.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    outcome = watchdog.perform_recovery(
        "0000:71:00.0",
        sys_pci_root=sys_root,
        sleep_fn=sleeps.append,
        runner=runner,
        sysfs_writer=writer,
    )
    assert outcome["remove_succeeded"] is True
    assert outcome["rescan_succeeded"] is True
    assert outcome["reappeared"] is True
    assert writes == [
        (pci_dev / "remove", "1"),
        (sys_root / "rescan", "1"),
    ]
    # Sleeps: 2s after remove, 5s after rescan
    assert sleeps == [2, 5]
    # Both post-recovery units restarted via the operator's USER manager —
    # not the system manager — because POST_RECOVERY_UNITS are user units
    # and this watchdog runs as a system unit (User=root). Pinning the
    # `--user --machine=hapax@.host` invocation prevents the regression
    # surfaced by the 24h auditor (system manager silently drops the
    # restart, leaving the USB router stale).
    assert runs == [
        [
            "systemctl",
            "--user",
            "--machine=hapax@.host",
            "restart",
            "hapax-usb-router.service",
        ],
        [
            "systemctl",
            "--user",
            "--machine=hapax@.host",
            "restart",
            "hapax-usb-topology-witness.service",
        ],
    ]
    assert all(item["succeeded"] for item in outcome["post_recovery_restarts"])


def test_perform_recovery_aborts_when_remove_fails(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    sys_root = tmp_path / "sys-bus-pci"
    (sys_root / "devices" / "0000:71:00.0").mkdir(parents=True)

    def writer(path: Path, value: str) -> bool:
        return False  # always fail

    runs: list[list[str]] = []

    def runner(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        runs.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    outcome = watchdog.perform_recovery(
        "0000:71:00.0",
        sys_pci_root=sys_root,
        sleep_fn=lambda _: None,
        runner=runner,
        sysfs_writer=writer,
    )
    assert outcome["remove_succeeded"] is False
    assert outcome["rescan_attempted"] is False
    # No service restarts attempted on aborted recovery.
    assert runs == []


def test_perform_recovery_warns_when_device_does_not_reappear(
    watchdog: types.ModuleType, tmp_path: Path
) -> None:
    sys_root = tmp_path / "sys-bus-pci"
    # Note: do NOT create the device directory — simulating a controller
    # that did not come back after rescan.

    def writer(path: Path, value: str) -> bool:
        return True

    runs: list[list[str]] = []

    def runner(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        runs.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    outcome = watchdog.perform_recovery(
        "0000:71:00.0",
        sys_pci_root=sys_root,
        sleep_fn=lambda _: None,
        runner=runner,
        sysfs_writer=writer,
    )
    assert outcome["remove_succeeded"] is True
    assert outcome["rescan_succeeded"] is True
    assert outcome["reappeared"] is False


# --- Post-recovery user-unit restart ------------------------------------


def test_post_recovery_argv_targets_user_manager_via_machinectl(
    watchdog: types.ModuleType,
) -> None:
    """Regression pin: post-recovery argv must invoke the USER manager.

    The watchdog runs as a SYSTEM unit (User=root). POST_RECOVERY_UNITS are
    USER units installed under ~/.config/systemd/user/. A bare
    `systemctl restart` would target the system manager and silently fail.
    """

    argv = watchdog._post_recovery_restart_argv("hapax-usb-router.service")
    assert argv == [
        "systemctl",
        "--user",
        "--machine=hapax@.host",
        "restart",
        "hapax-usb-router.service",
    ]


def test_perform_recovery_logs_user_manager_unreachable(
    watchdog: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fallback path: machinectl-unreachable must emit a journal-grepable marker.

    The fallback must NOT swallow the failure — operators rely on grepping
    the journal for `POST_RECOVERY_USER_MANAGER_UNREACHABLE` to notice
    that the user-side restart never landed.
    """

    sys_root = tmp_path / "sys-bus-pci"
    pci_dev = sys_root / "devices" / "0000:71:00.0"
    pci_dev.mkdir(parents=True)

    def writer(path: Path, value: str) -> bool:
        return True

    def runner(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        # Simulate the failure mode: lingering not active, user bus not up.
        return subprocess.CompletedProcess(
            argv,
            1,
            "",
            "Failed to get D-Bus connection: No such file or directory",
        )

    outcome = watchdog.perform_recovery(
        "0000:71:00.0",
        sys_pci_root=sys_root,
        sleep_fn=lambda _: None,
        runner=runner,
        sysfs_writer=writer,
    )

    # Each restart records a structured failure entry — no swallowing.
    assert len(outcome["post_recovery_restarts"]) == len(watchdog.POST_RECOVERY_UNITS)
    for entry in outcome["post_recovery_restarts"]:
        assert entry["succeeded"] is False
        assert entry["returncode"] == 1
        assert entry["machine_unreachable"] is True

    captured = capsys.readouterr()
    # Stderr carries the journal-grepable marker for each failed unit.
    assert "POST_RECOVERY_USER_MANAGER_UNREACHABLE" in captured.err
    assert "hapax-usb-router.service" in captured.err
    assert "hapax-usb-topology-witness.service" in captured.err
    # Operator hint included for next-action discoverability.
    assert "loginctl show-user hapax" in captured.err


def test_perform_recovery_logs_generic_restart_failure(
    watchdog: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-machinectl failures still get a distinct, grepable marker."""

    sys_root = tmp_path / "sys-bus-pci"
    pci_dev = sys_root / "devices" / "0000:71:00.0"
    pci_dev.mkdir(parents=True)

    def writer(path: Path, value: str) -> bool:
        return True

    def runner(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        # User manager IS reachable, but the unit failed to start (e.g.,
        # ExecStart segfault). Different marker, must still surface clearly.
        return subprocess.CompletedProcess(
            argv,
            5,  # systemd "unit not loaded"
            "",
            "Job for hapax-usb-router.service failed because the control process exited",
        )

    outcome = watchdog.perform_recovery(
        "0000:71:00.0",
        sys_pci_root=sys_root,
        sleep_fn=lambda _: None,
        runner=runner,
        sysfs_writer=writer,
    )

    for entry in outcome["post_recovery_restarts"]:
        assert entry["succeeded"] is False
        assert entry["returncode"] == 5
        assert entry["machine_unreachable"] is False

    captured = capsys.readouterr()
    assert "POST_RECOVERY_RESTART_FAILED" in captured.err
    # Must NOT mis-classify as user-manager-unreachable.
    assert "POST_RECOVERY_USER_MANAGER_UNREACHABLE" not in captured.err


# --- watch_loop integration ----------------------------------------------


def test_watch_loop_skips_during_cooldown(watchdog: types.ModuleType, tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"

    lines = [
        watchdog.JournalLine("xhci_hcd 0000:71:00.0: HC died; cleaning up"),
        watchdog.JournalLine("xhci_hcd 0000:71:00.0: HC died; cleaning up"),
    ]
    times = iter([1000.0, 1050.0])
    invocations: list[str] = []

    def fake_recovery(bdf: str, **_: Any) -> dict[str, Any]:
        invocations.append(bdf)
        return {"bdf": bdf, "ok": True}

    count = watchdog.watch_loop(
        state_path=state_path,
        cooldown_sec=180,
        dry_run=True,
        lines=lines,
        now_fn=lambda: next(times),
        recovery_fn=fake_recovery,
    )
    assert count == 1, "second event must be skipped due to cooldown"
    assert invocations == ["0000:71:00.0"]
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert "0000:71:00.0" in persisted["last_recovery"]


def test_watch_loop_recovers_distinct_bdfs(watchdog: types.ModuleType, tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    lines = [
        watchdog.JournalLine("xhci_hcd 0000:71:00.0: HC died; cleaning up"),
        watchdog.JournalLine("xhci_hcd 0000:72:00.0: Abort failed to stop command ring: -110"),
    ]
    invocations: list[str] = []

    def fake_recovery(bdf: str, **_: Any) -> dict[str, Any]:
        invocations.append(bdf)
        return {"bdf": bdf, "ok": True}

    count = watchdog.watch_loop(
        state_path=state_path,
        cooldown_sec=180,
        dry_run=True,
        lines=lines,
        now_fn=lambda: 1000.0,
        recovery_fn=fake_recovery,
    )
    assert count == 2
    assert invocations == ["0000:71:00.0", "0000:72:00.0"]


def test_watch_loop_ignores_non_matching_lines(watchdog: types.ModuleType, tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    lines = [
        watchdog.JournalLine("kernel: random thing happened"),
        watchdog.JournalLine("usb 3-1: New high-speed USB device"),
    ]
    invocations: list[str] = []

    def fake_recovery(bdf: str, **_: Any) -> dict[str, Any]:
        invocations.append(bdf)
        return {"bdf": bdf, "ok": True}

    count = watchdog.watch_loop(
        state_path=state_path,
        cooldown_sec=180,
        dry_run=True,
        lines=lines,
        now_fn=lambda: 1000.0,
        recovery_fn=fake_recovery,
    )
    assert count == 0
    assert invocations == []


# --- CLI surface ---------------------------------------------------------


def test_cli_dry_run_via_input_file(tmp_path: Path) -> None:
    """Smoke-test the CLI: run in --dry-run mode against a fixture journal."""
    state_path = tmp_path / "state.json"
    journal = tmp_path / "journal.txt"
    journal.write_text(
        "kernel: xhci_hcd 0000:71:00.0: HC died; cleaning up\n"
        "unrelated stuff\n"
        "kernel: xhci_hcd 0000:71:00.0: Abort failed to stop command ring: -110\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--state-file",
            str(state_path),
            "--cooldown-sec",
            "180",
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
    assert "death pattern" in proc.stdout
    assert "skipping 0000:71:00.0 (cooldown active)" in proc.stdout
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert "0000:71:00.0" in persisted["last_recovery"]
