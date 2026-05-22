"""Tests for L-12 USB wake-lock witness."""

from __future__ import annotations

from pathlib import Path

from shared.l12_usb_wake_lock import (
    CaptureStreamState,
    WakeLockStatus,
    check_l12_wake_lock,
    read_alsa_capture_state,
    read_usb_power_state,
)


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_sysfs(
    tmp_path: Path,
    *,
    vendor: str = "1686",
    product: str = "03d5",
    power_control: str = "on",
    autosuspend_delay_ms: str = "-1",
    runtime_status: str = "active",
) -> Path:
    """Build a minimal sysfs-like directory tree for the L-12."""
    dev = tmp_path / "usb_devices" / "1-2"
    _write_file(dev / "idVendor", vendor)
    _write_file(dev / "idProduct", product)
    _write_file(dev / "power" / "control", power_control)
    _write_file(dev / "power" / "autosuspend_delay_ms", autosuspend_delay_ms)
    _write_file(dev / "power" / "runtime_status", runtime_status)
    return tmp_path / "usb_devices"


def _build_proc_asound(
    tmp_path: Path,
    *,
    card_number: int = 11,
    cards_line: str | None = None,
    hw_params: str = "access: RW_INTERLEAVED\nformat: S16_LE\nrate: 44100\n",
    status: str = "state: RUNNING\nowner_pid   : 1234\n",
) -> Path:
    """Build a minimal /proc/asound-like directory."""
    proc = tmp_path / "proc_asound"
    if cards_line is None:
        cards_line = f" {card_number} [L12            ]: USB-Audio - ZOOM L-12\n"
    _write_file(proc / "cards", cards_line)
    card_dir = proc / f"card{card_number}" / "pcm0c" / "sub0"
    _write_file(card_dir / "hw_params", hw_params)
    _write_file(card_dir / "status", status)
    return proc


class TestReadUsbPowerState:
    def test_locked_state(self, tmp_path: Path) -> None:
        usb_root = _build_sysfs(tmp_path)
        state = read_usb_power_state(usb_root=usb_root)
        assert state.power_control == "on"
        assert state.autosuspend_delay_ms == -1
        assert state.runtime_status == "active"
        assert state.sysfs_path is not None

    def test_auto_suspend_enabled(self, tmp_path: Path) -> None:
        usb_root = _build_sysfs(tmp_path, power_control="auto", autosuspend_delay_ms="2000")
        state = read_usb_power_state(usb_root=usb_root)
        assert state.power_control == "auto"
        assert state.autosuspend_delay_ms == 2000

    def test_device_missing(self, tmp_path: Path) -> None:
        usb_root = tmp_path / "empty_usb"
        usb_root.mkdir()
        state = read_usb_power_state(usb_root=usb_root)
        assert state.sysfs_path is None
        assert state.power_control is None

    def test_wrong_vendor(self, tmp_path: Path) -> None:
        usb_root = _build_sysfs(tmp_path, vendor="046d")
        state = read_usb_power_state(usb_root=usb_root)
        assert state.sysfs_path is None


class TestReadAlsaCaptureState:
    def test_running_capture(self, tmp_path: Path) -> None:
        proc = _build_proc_asound(tmp_path)
        state = read_alsa_capture_state(proc_asound=proc)
        assert state.card_number == 11
        assert state.hw_params_present is True
        assert state.stream_state == CaptureStreamState.RUNNING
        assert state.sample_rate == 44100

    def test_xrun_state(self, tmp_path: Path) -> None:
        proc = _build_proc_asound(
            tmp_path,
            status="state: XRUN\nxrun: 42\n",
        )
        state = read_alsa_capture_state(proc_asound=proc)
        assert state.stream_state == CaptureStreamState.XRUN
        assert state.xrun_count == 42

    def test_card_missing(self, tmp_path: Path) -> None:
        proc = tmp_path / "proc_empty"
        proc.mkdir()
        _write_file(proc / "cards", "")
        state = read_alsa_capture_state(proc_asound=proc)
        assert state.card_number is None


class TestCheckL12WakeLock:
    def test_fully_locked(self, tmp_path: Path) -> None:
        usb_root = _build_sysfs(tmp_path)
        proc = _build_proc_asound(tmp_path)
        report = check_l12_wake_lock(usb_root=usb_root, proc_asound=proc)
        assert report.status == WakeLockStatus.LOCKED
        assert not report.reasons

    def test_auto_suspend_unlocked(self, tmp_path: Path) -> None:
        usb_root = _build_sysfs(tmp_path, power_control="auto", autosuspend_delay_ms="2000")
        proc = _build_proc_asound(tmp_path)
        report = check_l12_wake_lock(usb_root=usb_root, proc_asound=proc)
        assert report.status == WakeLockStatus.UNLOCKED
        assert any("auto" in r for r in report.reasons)
        assert any("2000" in r for r in report.reasons)

    def test_usb_suspended(self, tmp_path: Path) -> None:
        usb_root = _build_sysfs(tmp_path, runtime_status="suspended")
        proc = _build_proc_asound(tmp_path)
        report = check_l12_wake_lock(usb_root=usb_root, proc_asound=proc)
        assert report.status == WakeLockStatus.SUSPENDED

    def test_alsa_xrun_suspended(self, tmp_path: Path) -> None:
        usb_root = _build_sysfs(tmp_path)
        proc = _build_proc_asound(tmp_path, status="state: XRUN\nxrun: 5\n")
        report = check_l12_wake_lock(usb_root=usb_root, proc_asound=proc)
        assert report.status == WakeLockStatus.SUSPENDED

    def test_device_missing(self, tmp_path: Path) -> None:
        usb_root = tmp_path / "empty_usb"
        usb_root.mkdir()
        proc = tmp_path / "proc_empty"
        proc.mkdir()
        _write_file(proc / "cards", "")
        report = check_l12_wake_lock(usb_root=usb_root, proc_asound=proc)
        assert report.status == WakeLockStatus.MISSING

    def test_report_serializes(self, tmp_path: Path) -> None:
        usb_root = _build_sysfs(tmp_path)
        proc = _build_proc_asound(tmp_path)
        report = check_l12_wake_lock(usb_root=usb_root, proc_asound=proc)
        d = report.to_dict()
        assert d["status"] == "locked"
        assert "checked_at" in d
        assert d["usb_power"]["power_control"] == "on"
        assert d["alsa_capture"]["card_number"] == 11
