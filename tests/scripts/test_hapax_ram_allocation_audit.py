"""Tests for hapax-ram-allocation-audit script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hapax-ram-allocation-audit"
POLICY = REPO / "config" / "infrastructure" / "128gb-ram-policy.yaml"


class TestPolicyFile:
    """Validate the policy file structure."""

    def test_policy_exists(self):
        assert POLICY.is_file()

    def test_policy_is_valid_yaml(self):
        import yaml

        with open(POLICY) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)

    def test_policy_has_sysctl_section(self):
        import yaml

        with open(POLICY) as f:
            data = yaml.safe_load(f)
        assert "sysctl" in data
        assert len(data["sysctl"]) >= 3

    def test_policy_has_containers_section(self):
        import yaml

        with open(POLICY) as f:
            data = yaml.safe_load(f)
        assert "containers" in data
        assert len(data["containers"]) >= 10

    def test_policy_containers_have_limits(self):
        import yaml

        with open(POLICY) as f:
            data = yaml.safe_load(f)
        for name, spec in data["containers"].items():
            assert "mem_limit_gb" in spec or "mem_limit_mb" in spec, (
                f"Container {name} has no memory limit"
            )

    def test_policy_containers_have_rationale(self):
        import yaml

        with open(POLICY) as f:
            data = yaml.safe_load(f)
        for name, spec in data["containers"].items():
            assert "rationale" in spec, f"Container {name} has no rationale"

    def test_total_container_budget_reasonable(self):
        """Total container memory should be < 50% of 128GB."""
        import yaml

        with open(POLICY) as f:
            data = yaml.safe_load(f)
        total_gb = 0
        for spec in data["containers"].values():
            if "mem_limit_gb" in spec:
                total_gb += spec["mem_limit_gb"]
            elif "mem_limit_mb" in spec:
                total_gb += spec["mem_limit_mb"] / 1024
        assert total_gb < 64, f"Total container budget {total_gb}G > 50% of 128G"


class TestAuditScript:
    """Validate the audit script runs and produces correct output."""

    def test_script_exists_and_executable(self):
        assert SCRIPT.is_file()
        assert SCRIPT.stat().st_mode & 0o111

    def test_runs_default_mode(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode in (0, 1), f"Unexpected exit: {result.returncode}\n{result.stderr}"
        assert "128GB RAM Allocation Audit" in result.stdout

    def test_json_output(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode in (0, 1)
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) > 0
        for item in data:
            assert "check" in item
            assert "status" in item
            assert item["status"] in ("pass", "gap", "warn", "error")

    def test_prometheus_output(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--prometheus"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode in (0, 1)
        assert "hapax_ram_audit_check" in result.stdout
        assert "hapax_ram_audit_gaps_total" in result.stdout

    def test_sysctl_checks_present(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
        sysctl_checks = [d for d in data if d["check"].startswith("sysctl.")]
        assert len(sysctl_checks) >= 3, "Expected at least 3 sysctl checks"

    def test_container_checks_present(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
        container_checks = [d for d in data if d["check"].startswith("container.")]
        assert len(container_checks) >= 8, "Expected at least 8 container checks"


class TestSystemdUnits:
    """Validate systemd unit files."""

    def test_service_exists(self):
        assert (REPO / "systemd/units/hapax-ram-allocation-audit.service").is_file()

    def test_timer_exists(self):
        assert (REPO / "systemd/units/hapax-ram-allocation-audit.timer").is_file()

    def test_service_uses_prometheus_output(self):
        text = (REPO / "systemd/units/hapax-ram-allocation-audit.service").read_text()
        assert "--prometheus" in text

    def test_timer_runs_daily(self):
        text = (REPO / "systemd/units/hapax-ram-allocation-audit.timer").read_text()
        assert "OnCalendar" in text
        assert "06:00" in text
