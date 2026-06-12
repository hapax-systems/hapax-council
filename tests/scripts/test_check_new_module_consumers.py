from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check-new-module-consumers.py"


def load_gate_module():
    spec = importlib.util.spec_from_file_location("check_new_module_consumers", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_is_module_file() -> None:
    gate = load_gate_module()

    assert gate.is_module_file(Path("shared/working_mode.py")) is True
    assert gate.is_module_file(Path("agents/health_monitor/registry.py")) is True
    assert gate.is_module_file(Path("tests/test_working_mode.py")) is False
    assert gate.is_module_file(Path("agents/test_health.py")) is False
    assert gate.is_module_file(Path("README.md")) is False
    assert gate.is_module_file(Path("config/new-module-allowlist.json")) is False


def test_get_module_name() -> None:
    gate = load_gate_module()

    assert gate.get_module_name(Path("shared/working_mode.py")) == "shared.working_mode"
    assert (
        gate.get_module_name(Path("agents/health_monitor/registry.py"))
        == "agents.health_monitor.registry"
    )


def test_is_allowlisted() -> None:
    gate = load_gate_module()

    allowlist = {"shared.working_mode", "agents.health_monitor.*", "some_entrypoint.py"}

    assert (
        gate.is_allowlisted(Path("shared/working_mode.py"), "shared.working_mode", allowlist)
        is True
    )
    assert (
        gate.is_allowlisted(
            Path("agents/health_monitor/registry.py"), "agents.health_monitor.registry", allowlist
        )
        is True
    )
    assert (
        gate.is_allowlisted(
            Path("agents/health_monitor/checks.py"), "agents.health_monitor.checks", allowlist
        )
        is True
    )
    assert gate.is_allowlisted(Path("agents/other.py"), "agents.other", allowlist) is False
    assert gate.is_allowlisted(Path("some_entrypoint.py"), "some_entrypoint", allowlist) is True


def test_get_imported_modules(tmp_path: Path) -> None:
    gate = load_gate_module()

    file_content = """
import shared.working_mode
from agents.health_monitor import registry
from . import checks
from ..shared import config
from agents import health_monitor
"""
    test_file = tmp_path / "test_import.py"
    test_file.write_text(file_content, encoding="utf-8")

    imported = gate.get_imported_modules(test_file, "agents.health_monitor.registry")

    # absolute import
    assert "shared.working_mode" in imported
    assert "agents.health_monitor.registry" in imported
    assert "agents.health_monitor" in imported

    # relative import from . (level=1 relative to agents.health_monitor) -> agents.health_monitor.checks
    assert "agents.health_monitor.checks" in imported

    # relative import from .. (level=2 relative to agents.health_monitor) -> agents.shared.config
    assert "agents.shared.config" in imported

    # from agents import health_monitor -> agents.health_monitor
    assert "agents.health_monitor" in imported


def test_count_consumers() -> None:
    gate = load_gate_module()

    all_source_files = [
        Path("shared/working_mode.py"),
        Path("agents/health_monitor/registry.py"),
        Path("agents/other.py"),
    ]
    target_file = Path("shared/working_mode.py")

    imports_by_file = {
        Path("shared/working_mode.py"): set(),
        Path("agents/health_monitor/registry.py"): {"shared.working_mode"},
        Path("agents/other.py"): {"shared.working_mode", "something_else"},
    }

    count = gate.count_consumers(
        "shared.working_mode",
        all_source_files,
        target_file,
        imports_by_file,
    )
    assert count == 2


class TestCanaries:
    """Anti-theses canaries: the gate must demonstrably FIRE on an unconsumed
    producer and PASS legitimate patterns — through main(), not helpers."""

    def _repo(self, tmp_path, monkeypatch):
        import check_new_module_consumers as gate

        (tmp_path / "agents").mkdir()
        (tmp_path / "shared").mkdir()
        (tmp_path / "config").mkdir()
        monkeypatch.chdir(tmp_path)
        return gate

    def test_evasion_canary_unconsumed_module_blocks(self, tmp_path, monkeypatch):
        gate = self._repo(tmp_path, monkeypatch)
        rogue = tmp_path / "agents" / "rogue_widget.py"
        rogue.write_text("def run():\n    pass\n")
        monkeypatch.setattr(
            gate, "git_diff_added_files", lambda args: [Path("agents/rogue_widget.py")]
        )
        rc = gate.main([])
        assert rc == 1, "an unconsumed new producer MUST block"

    def test_deadlock_canary_imported_module_passes(self, tmp_path, monkeypatch):
        gate = self._repo(tmp_path, monkeypatch)
        (tmp_path / "agents" / "widget.py").write_text("def run():\n    pass\n")
        (tmp_path / "shared" / "uses.py").write_text("from agents.widget import run\n")
        monkeypatch.setattr(gate, "git_diff_added_files", lambda args: [Path("agents/widget.py")])
        assert gate.main([]) == 0

    def test_deadlock_canary_systemd_consumer_passes(self, tmp_path, monkeypatch):
        gate = self._repo(tmp_path, monkeypatch)
        (tmp_path / "agents" / "lone_daemon.py").write_text("def run():\n    pass\n")
        units = tmp_path / "systemd" / "units"
        units.mkdir(parents=True)
        (units / "hapax-lone.service").write_text(
            "[Service]\nExecStart=uv run python -m agents.lone_daemon\n"
        )
        monkeypatch.setattr(
            gate, "git_diff_added_files", lambda args: [Path("agents/lone_daemon.py")]
        )
        assert gate.main([]) == 0, "a systemd-consumed daemon is NOT unwired"

    def test_deadlock_canary_allowlist_passes(self, tmp_path, monkeypatch):
        import json

        gate = self._repo(tmp_path, monkeypatch)
        (tmp_path / "agents" / "entrypoint.py").write_text("def run():\n    pass\n")
        (tmp_path / "config" / "new-module-allowlist.json").write_text(
            json.dumps(["agents.entrypoint"])
        )
        monkeypatch.setattr(
            gate, "git_diff_added_files", lambda args: [Path("agents/entrypoint.py")]
        )
        assert gate.main([]) == 0
