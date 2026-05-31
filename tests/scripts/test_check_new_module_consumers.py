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
