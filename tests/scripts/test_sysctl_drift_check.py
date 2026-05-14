"""Tests for the sysctl drift check script's core logic."""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path
from unittest.mock import patch

# Load the script as a module (no .py extension — needs explicit loader)
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "hapax-sysctl-drift-check"


def _load_drift_module() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_sysctl_drift_check", str(_SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("hapax_sysctl_drift_check", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


_mod = _load_drift_module()
parse_sysctl_conf = _mod.parse_sysctl_conf
sysctl_to_procfs_path = _mod.sysctl_to_procfs_path
check_drift = _mod.check_drift


def test_parse_sysctl_conf_extracts_key_values(tmp_path: Path) -> None:
    conf = tmp_path / "99-hapax-test.conf"
    conf.write_text(
        "# comment\n"
        "vm.swappiness = 5\n"
        "vm.dirty_ratio=20\n"
        "; another comment\n"
        "\n"
        "vm.vfs_cache_pressure = 75\n"
    )
    result = parse_sysctl_conf(conf)
    assert result == {
        "vm.swappiness": "5",
        "vm.dirty_ratio": "20",
        "vm.vfs_cache_pressure": "75",
    }


def test_parse_sysctl_conf_empty_file(tmp_path: Path) -> None:
    conf = tmp_path / "99-hapax-empty.conf"
    conf.write_text("# only comments\n")
    assert parse_sysctl_conf(conf) == {}


def test_sysctl_to_procfs_path() -> None:
    assert sysctl_to_procfs_path("vm.swappiness") == Path("/proc/sys/vm/swappiness")
    assert sysctl_to_procfs_path("net.ipv4.ip_forward") == Path("/proc/sys/net/ipv4/ip_forward")


def test_check_drift_detects_mismatch(tmp_path: Path) -> None:
    conf = tmp_path / "99-hapax-test.conf"
    conf.write_text("vm.swappiness = 5\n")

    with patch.object(_mod, "read_live_value", return_value="150"):
        results = check_drift(conf_dir=tmp_path, pattern="99-hapax-*.conf")

    assert len(results) == 1
    assert results[0]["key"] == "vm.swappiness"
    assert results[0]["declared"] == "5"
    assert results[0]["live"] == "150"
    assert results[0]["status"] == "drift"


def test_check_drift_reports_ok_when_matching(tmp_path: Path) -> None:
    conf = tmp_path / "99-hapax-test.conf"
    conf.write_text("vm.swappiness = 5\n")

    with patch.object(_mod, "read_live_value", return_value="5"):
        results = check_drift(conf_dir=tmp_path, pattern="99-hapax-*.conf")

    assert len(results) == 1
    assert results[0]["status"] == "ok"


def test_check_drift_handles_unreadable_keys(tmp_path: Path) -> None:
    conf = tmp_path / "99-hapax-test.conf"
    conf.write_text("vm.nonexistent_key = 42\n")

    with patch.object(_mod, "read_live_value", return_value=None):
        results = check_drift(conf_dir=tmp_path, pattern="99-hapax-*.conf")

    assert len(results) == 1
    assert results[0]["status"] == "unreadable"
    assert results[0]["live"] == "<unreadable>"


def test_check_drift_empty_dir(tmp_path: Path) -> None:
    results = check_drift(conf_dir=tmp_path, pattern="99-hapax-*.conf")
    assert results == []


def test_check_drift_multiple_files(tmp_path: Path) -> None:
    (tmp_path / "99-hapax-a.conf").write_text("vm.swappiness = 5\n")
    (tmp_path / "99-hapax-b.conf").write_text("vm.dirty_ratio = 20\n")

    def mock_live(key: str) -> str:
        return {"vm.swappiness": "5", "vm.dirty_ratio": "10"}.get(key, "0")

    with patch.object(_mod, "read_live_value", side_effect=mock_live):
        results = check_drift(conf_dir=tmp_path, pattern="99-hapax-*.conf")

    assert len(results) == 2
    statuses = {r["key"]: r["status"] for r in results}
    assert statuses["vm.swappiness"] == "ok"
    assert statuses["vm.dirty_ratio"] == "drift"
