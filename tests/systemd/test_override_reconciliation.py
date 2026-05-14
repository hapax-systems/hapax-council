"""Tests for REQ-20260508193745 override reconciliation.

Validates that the source-controlled unit files contain the properties
that were previously applied as local drop-in overrides, so those
overrides can be safely removed.
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

UNITS_DIR = Path(__file__).resolve().parents[2] / "systemd" / "units"


def _parse_unit(name: str) -> configparser.RawConfigParser:
    """Parse a systemd unit file with RawConfigParser to avoid
    interpolation errors on systemd specifiers like %h."""
    path = UNITS_DIR / name
    assert path.exists(), f"unit file {name} not found at {path}"
    cp = configparser.RawConfigParser(strict=False)
    cp.read_string(path.read_text(encoding="utf-8"))
    return cp


class TestUsbBandwidthPreflightReconciliation:
    """REQ-20260508193745 findings #1/#2: USB preflight import fix."""

    def test_protect_home_is_read_only(self) -> None:
        """ProtectHome must be read-only, not true, so the script can
        read ~/projects/hapax-council for shared.usb_bandwidth_table."""
        cp = _parse_unit("hapax-usb-bandwidth-preflight.service")
        assert cp.get("Service", "ProtectHome") == "read-only"

    def test_has_hapax_council_root_env(self) -> None:
        """The HAPAX_COUNCIL_ROOT env var must be set so the import
        resolver finds the repo root deterministically."""
        cp = _parse_unit("hapax-usb-bandwidth-preflight.service")
        env = cp.get("Service", "Environment")
        assert "HAPAX_COUNCIL_ROOT" in env


class TestNoveltyShiftEmitterReconciliation:
    """REQ-20260508193745 finding #4: start-limit for 1s cadence."""

    def test_start_limit_interval_disabled(self) -> None:
        """StartLimitIntervalSec=0 must be in the source unit so the
        1-second timer cadence doesn't trip systemd's default start-limit."""
        cp = _parse_unit("hapax-novelty-shift-emitter.service")
        val = cp.get("Unit", "StartLimitIntervalSec")
        assert val == "0"
