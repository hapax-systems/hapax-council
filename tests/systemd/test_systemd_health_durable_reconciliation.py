"""Tests for durable systemd health reconciliation (REQ-20260508193745).

Validates source-controlled unit files have the fixes that make
local drop-in overrides unnecessary.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UNITS = REPO / "systemd" / "units"


def _unit_text(name: str) -> str:
    """Read a systemd unit file as raw text."""
    path = UNITS / name
    assert path.is_file(), f"Unit file missing: {path}"
    return path.read_text()


def _unit_value(text: str, section: str, key: str) -> str | None:
    """Extract a value from a systemd unit file.

    Returns the LAST occurrence of the key in the section (systemd semantics).
    For multi-value keys like Environment, returns all values joined.
    """
    in_section = False
    values = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == f"[{section}]"
            continue
        if in_section and "=" in stripped:
            k, _, v = stripped.partition("=")
            if k.strip() == key:
                values.append(v.strip())
    return " ".join(values) if values else None


def _unit_values(text: str, section: str, key: str) -> list[str]:
    """Extract all values for a key in a section."""
    in_section = False
    values = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == f"[{section}]"
            continue
        if in_section and "=" in stripped:
            k, _, v = stripped.partition("=")
            if k.strip() == key:
                values.append(v.strip())
    return values


# ── USB Bandwidth Preflight ──────────────────────────────────────────


class TestUsbBandwidthPreflight:
    """hapax-usb-bandwidth-preflight.service durable fixes."""

    def test_unit_exists(self):
        assert (UNITS / "hapax-usb-bandwidth-preflight.service").is_file()

    def test_has_pythonpath_for_installed_table(self):
        """PYTHONPATH must point to the installed shared package location."""
        text = _unit_text("hapax-usb-bandwidth-preflight.service")
        envs = _unit_values(text, "Service", "Environment")
        pythonpath_found = any("PYTHONPATH=/usr/local/share/hapax-council" in e for e in envs)
        assert pythonpath_found, f"PYTHONPATH not found in Environment lines: {envs}"

    def test_protect_home_is_true(self):
        """ProtectHome=true must be preserved — security hardening."""
        text = _unit_text("hapax-usb-bandwidth-preflight.service")
        val = _unit_value(text, "Service", "ProtectHome")
        assert val and val.lower() == "true"

    def test_success_exit_status_includes_warning_codes(self):
        """Exit 1 (warning) and 2 (saturated) are expected non-error states."""
        text = _unit_text("hapax-usb-bandwidth-preflight.service")
        val = _unit_value(text, "Service", "SuccessExitStatus")
        assert val is not None
        for code in ("0", "1", "2"):
            assert code in val

    @pytest.mark.skipif(
        not Path("/usr/local/share/hapax-council").exists(), reason="requires local installation"
    )
    def test_installed_table_path_exists(self):
        """The installed table must exist at the PYTHONPATH target."""
        table_path = Path("/usr/local/share/hapax-council/shared/usb_bandwidth_table.py")
        assert table_path.is_file(), (
            f"Installed table missing at {table_path}. "
            "Run the install-usb-bandwidth-table makefile target."
        )

    @pytest.mark.skipif(
        not Path("/usr/local/bin/hapax-usb-bandwidth-preflight").exists(),
        reason="requires local installation",
    )
    def test_preflight_runs_with_installed_path(self):
        """The preflight script must produce valid Prometheus output."""
        result = subprocess.run(
            ["/usr/local/bin/hapax-usb-bandwidth-preflight", "--prometheus"],
            capture_output=True,
            text=True,
            timeout=10,
            env={
                "PYTHONPATH": "/usr/local/share/hapax-council",
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": "/tmp",
            },
        )
        assert result.returncode in (0, 1, 2), (
            f"Unexpected exit: {result.returncode}\n{result.stderr}"
        )
        assert "hapax_usb_bandwidth" in result.stdout, "No Prometheus metrics in output"
        assert "Traceback" not in result.stdout, "Traceback in Prometheus output"
        assert "Traceback" not in result.stderr, "Traceback in stderr"


# ── Novelty Shift Emitter ────────────────────────────────────────────


class TestNoveltyShiftEmitter:
    """hapax-novelty-shift-emitter.service durable fixes."""

    def test_unit_exists(self):
        assert (UNITS / "hapax-novelty-shift-emitter.service").is_file()

    def test_start_limit_disabled(self):
        """StartLimitIntervalSec=0 must be set for 1s-cadence oneshot."""
        text = _unit_text("hapax-novelty-shift-emitter.service")
        val = _unit_value(text, "Unit", "StartLimitIntervalSec")
        assert val is not None, "StartLimitIntervalSec not set"
        assert val == "0", f"Expected 0, got {val}"

    def test_timer_1s_cadence(self):
        """Timer must fire every 1 second."""
        text = _unit_text("hapax-novelty-shift-emitter.timer")
        val = _unit_value(text, "Timer", "OnUnitActiveSec")
        assert val == "1s"

    def test_timeout_is_reasonable(self):
        """Oneshot timeout must be short enough for 1s cadence."""
        text = _unit_text("hapax-novelty-shift-emitter.service")
        val = _unit_value(text, "Service", "TimeoutStartSec")
        assert val is not None
        assert int(val) <= 10, f"Timeout {val}s too long for 1s cadence"


# ── Backup Local ─────────────────────────────────────────────────────


class TestBackupLocal:
    """hapax-backup-local.service durable fixes."""

    def test_unit_exists(self):
        assert (UNITS / "hapax-backup-local.service").is_file()

    def test_memory_max_sufficient(self):
        """MemoryMax must be >= 4G to avoid OOM during pg_dump."""
        text = _unit_text("hapax-backup-local.service")
        val = _unit_value(text, "Service", "MemoryMax")
        assert val is not None
        num = int(val.rstrip("GgMm"))
        unit = val[-1].upper()
        bytes_val = num * (1024**3 if unit == "G" else 1024**2)
        assert bytes_val >= 4 * 1024**3, f"MemoryMax={val} too low, need >= 4G"

    def test_memory_high_is_soft_warning(self):
        """MemoryHigh should be set as a soft pressure threshold."""
        text = _unit_text("hapax-backup-local.service")
        val = _unit_value(text, "Service", "MemoryHigh")
        assert val is not None, "MemoryHigh not set — add soft pressure threshold"

    def test_memory_high_less_than_max(self):
        """MemoryHigh must be less than MemoryMax."""
        text = _unit_text("hapax-backup-local.service")
        high = _unit_value(text, "Service", "MemoryHigh")
        maxv = _unit_value(text, "Service", "MemoryMax")
        assert high and maxv
        h = int(high.rstrip("GgMm"))
        m = int(maxv.rstrip("GgMm"))
        assert h < m, f"MemoryHigh={high} should be < MemoryMax={maxv}"

    def test_runs_at_3am(self):
        """Backup timer should run at a low-contention time."""
        text = _unit_text("hapax-backup-local.timer")
        val = _unit_value(text, "Timer", "OnCalendar")
        assert val and "03:00" in val, f"Expected 3am schedule, got: {val}"


# ── Drop-in Override Obsolescence ────────────────────────────────────


class TestDropInObsolescence:
    """Source-controlled units should make drop-ins unnecessary."""

    @pytest.mark.parametrize(
        "unit_name,drop_in_fix",
        [
            ("hapax-usb-bandwidth-preflight.service", "PYTHONPATH"),
            ("hapax-novelty-shift-emitter.service", "StartLimitIntervalSec"),
        ],
    )
    def test_source_unit_contains_drop_in_fix(self, unit_name: str, drop_in_fix: str):
        """The source unit must contain the fix that was in the drop-in."""
        text = _unit_text(unit_name)
        assert drop_in_fix in text, (
            f"{unit_name} is missing {drop_in_fix} — the local drop-in override is still needed"
        )
