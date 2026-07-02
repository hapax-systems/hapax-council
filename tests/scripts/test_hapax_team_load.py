from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_team_load() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "hapax_team_load_under_test",
        str(REPO_ROOT / "scripts" / "hapax-team-load"),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def _snapshot(
    *,
    swap_pct: float = 0.0,
    team_swap_gb: float = 0.0,
    mem_available_gb: float = 64.0,
    memory_psi_some: float = 0.0,
    memory_psi_full: float = 0.0,
    load_per_core: float = 0.1,
    team_cpu: float = 0.0,
    mode: str = "research",
) -> dict[str, Any]:
    return {
        "working_mode": mode,
        "system": {
            "load_1": load_per_core * 16,
            "load_per_core": load_per_core,
            "ncpu": 16,
            "swap_used_kb": int(swap_pct * 1024 * 1024 / 100),
            "swap_total_kb": 1024 * 1024,
            "swap_pct": swap_pct,
            "mem_total_kb": 128 * 1024 * 1024,
            "mem_available_kb": int(mem_available_gb * 1024 * 1024),
            "mem_available_pct": mem_available_gb / 128 * 100,
            "memory_psi_some_avg10": memory_psi_some,
            "memory_psi_full_avg10": memory_psi_full,
        },
        "team": {
            "cpu_pct": team_cpu,
            "rss_kb": 0,
            "swap_kb": int(team_swap_gb * 1024 * 1024),
            "session_count": 1,
            "process_count": 1,
        },
        "operational": {"cpu_pct": 0.0, "rss_kb": 0, "swap_kb": 0, "process_count": 0},
        "relay_mq": {},
        "sessions": [],
    }


def test_high_swap_alone_does_not_close_team_load_gate() -> None:
    team_load = _load_team_load()

    level, reasons = team_load.classify(
        _snapshot(swap_pct=99.0, team_swap_gb=9.0, mem_available_gb=67.0)
    )

    assert level == "green"
    assert reasons == ["system has headroom"]


def test_memavailable_pressure_closes_team_load_gate() -> None:
    team_load = _load_team_load()

    level, reasons = team_load.classify(_snapshot(swap_pct=99.0, mem_available_gb=10.0))

    assert level == "red"
    assert any("MemAvailable" in reason for reason in reasons)


def test_memory_psi_pressure_closes_team_load_gate() -> None:
    team_load = _load_team_load()

    level, reasons = team_load.classify(_snapshot(swap_pct=99.0, memory_psi_some=42.0))

    assert level == "red"
    assert any("memory PSI some" in reason for reason in reasons)


def test_legacy_antigravity_tmux_session_normalizes_to_agy(monkeypatch) -> None:
    team_load = _load_team_load()

    def fake_check_output(cmd: list[str], **_: Any) -> str:
        if cmd[:3] == ["tmux", "list-sessions", "-F"]:
            return "hapax-antigrav-antigravity\nhapax-antigrav-antigravity-2\n"
        if cmd[:3] == ["tmux", "list-panes", "-t"]:
            return "123\n"
        raise AssertionError(cmd)

    monkeypatch.setattr(team_load.subprocess, "check_output", fake_check_output)

    assert team_load.list_team_sessions() == [
        ("agy", "agy", [123]),
        ("agy", "agy-2", [123]),
    ]
