"""Tests for IR fleet revival diagnostic — cc-task ir-fleet-revival-diagnostic.

Pins the council-side health-monitor PI_FLEET expansion so the IR Pis
(pi1/pi2/pi6) become visible to `check_pi_fleet`, and pins the on-disk
shape of the audit + restart scripts so future refactors don't silently
drop the contract.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from agents.health_monitor.constants import PI_FLEET

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
PI_EDGE_DIR = REPO_ROOT / "pi-edge"


class TestPiFleetIRExpansion:
    """The 3 IR Pis must be visible to council-side health monitoring.

    Without these entries `check_pi_fleet` only iterates over pi4/pi5,
    so a 12-day heartbeat staleness on pi1/pi2/pi6 is invisible to the
    health surface — the failure mode that surfaced this revival.
    """

    @pytest.mark.parametrize(
        "hostname,role",
        [
            ("hapax-pi1", "ir-desk"),
            ("hapax-pi2", "ir-room"),
            ("hapax-pi6", "ir-overhead"),
        ],
    )
    def test_ir_pi_in_fleet(self, hostname: str, role: str) -> None:
        assert hostname in PI_FLEET, f"{hostname} missing from PI_FLEET"
        assert PI_FLEET[hostname]["role"] == role
        assert PI_FLEET[hostname]["expected_services"] == ["hapax-ir-edge"]

    def test_existing_pis_unchanged(self) -> None:
        """PI_FLEET expansion must not perturb pi4/pi5 entries."""
        assert PI_FLEET["hapax-pi4"]["role"] == "sentinel"
        assert PI_FLEET["hapax-pi5"]["role"] == "rag-edge"


class TestIRFleetScripts:
    """Audit + restart scripts must exist and be executable."""

    def test_audit_script_exists_and_executable(self) -> None:
        script = SCRIPTS_DIR / "ir-fleet-audit.sh"
        assert script.is_file(), "scripts/ir-fleet-audit.sh missing"
        mode = script.stat().st_mode
        assert mode & stat.S_IXUSR, "scripts/ir-fleet-audit.sh not executable"

    def test_restart_script_exists_and_executable(self) -> None:
        script = SCRIPTS_DIR / "ir-fleet-restart.sh"
        assert script.is_file(), "scripts/ir-fleet-restart.sh missing"
        mode = script.stat().st_mode
        assert mode & stat.S_IXUSR, "scripts/ir-fleet-restart.sh not executable"

    def test_restart_script_dry_run_safe(self) -> None:
        """The restart script must accept --dry-run without making changes.

        This is the operator-facing safety latch: the script is only run
        manually when restarting the IR fleet; --dry-run is the obvious
        way to preview what it will do before executing.
        """
        import subprocess

        script = SCRIPTS_DIR / "ir-fleet-restart.sh"
        result = subprocess.run(
            [str(script), "--dry-run", "pi1"],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ},
        )
        assert "[dry-run]" in result.stderr, (
            f"--dry-run did not emit [dry-run] markers; stderr: {result.stderr[:500]}"
        )


class TestHeartbeatUnitURL:
    """The heartbeat service must point at a hostname that actually resolves.

    The historical bug was twofold: the deployed Pi-side unit had a hardcoded
    DHCP IP that drifted (192.168.68.80 → .85), and the repo-tracked unit
    pointed at hapax-podium-2.local — an mDNS name that does not resolve on
    this LAN, so re-deploys would have remained broken. The canonical name
    is hapax-podium.local (the same one hapax_ir_edge.py uses successfully).
    """

    def test_unit_uses_canonical_mdns_name(self) -> None:
        unit = PI_EDGE_DIR / "hapax-heartbeat.service"
        content = unit.read_text()
        assert "hapax-podium.local:8051" in content, (
            "heartbeat unit must use hapax-podium.local (the canonical mDNS name)"
        )
        assert "hapax-podium-2.local" not in content, (
            "hapax-podium-2.local does not resolve on this LAN; do not reintroduce it"
        )
        assert "192.168.68.80" not in content, (
            "do not hardcode DHCP IPs in the heartbeat unit; mDNS only"
        )
