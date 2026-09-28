"""Focused credential, ledger, startup and live MCP checks for the server slice."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import pwd
import shutil
import types
from pathlib import Path
from typing import Any

import pytest

from shared import research_desk_ledger as ledger_mod
from shared.research_desk import ResearchDeskConfig

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "hapax-research-desk-mcp"
LOOPBACK = "127.0.0.1"
KEY = "test-key-with-enough-entropy-0123456789"


def _load_module() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "hapax_research_desk_mcp_smoke", str(_SCRIPT_PATH)
    )
    spec = importlib.util.spec_from_loader("hapax_research_desk_mcp_smoke", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


desk_mcp = _load_module()


@pytest.fixture
def config(tmp_path: Path) -> ResearchDeskConfig:
    vault = tmp_path / "vault"
    (vault / "20-projects" / "hapax-cc-tasks" / "active").mkdir(parents=True)
    (vault / "30-areas" / "hapax" / "lanebus" / "cx-blue").mkdir(parents=True)
    return ResearchDeskConfig(
        vault_root=vault, state_root=tmp_path / "state", delivery_lane="cx-blue"
    )


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "ledger.jsonl"


def seed_request(config: ResearchDeskConfig, request_id: str, *, status: str = "offered") -> Path:
    path = config.requests_dir / f"{request_id}.md"
    path.write_text(
        "\n".join(
            [
                "---",
                "type: cc-task",
                f"task_id: {request_id}",
                f'title: "{request_id}"',
                "kind: research_request",
                "route_family: perplexity-desk",
                f"status: {status}",
                "priority: p1",
                'question: "Which EU implementing acts landed this quarter?"',
                "---",
                "",
                "Brief body.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_home_cannot_choose_the_credential_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    canonical = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local/bin/hapax-secret"
    monkeypatch.setenv("HOME", "/tmp/hostile-research-desk-home")
    assert Path(desk_mcp._hapax_secret_bin()) == canonical


async def test_schema_rejected_call_is_ledgered(
    config: ResearchDeskConfig, ledger_path: Path
) -> None:
    server = desk_mcp.build_server(config, ledger_path=ledger_path)
    with pytest.raises(Exception):
        await server.call_tool("fetch_request", {})
    (row,) = ledger_mod.read_records(ledger_path).records
    assert row["tool"] == "fetch_request"
    assert row["outcome"] == "error"
    assert row["reason_code"] == "tool_call_error"


async def test_ledger_write_failure_fails_the_tool_call(
    config: ResearchDeskConfig, tmp_path: Path
) -> None:
    blocked_path = tmp_path / "directory-as-ledger"
    blocked_path.mkdir()
    server = desk_mcp.build_server(config, ledger_path=blocked_path)
    with pytest.raises(Exception):
        await server.call_tool("list_open_research_requests", {})


async def test_delivery_cannot_write_when_intent_append_fails(
    config: ResearchDeskConfig, tmp_path: Path
) -> None:
    seed_request(config, "req-no-ledger")
    blocked_path = tmp_path / "directory-as-ledger"
    blocked_path.mkdir()
    server = desk_mcp.build_server(config, ledger_path=blocked_path)
    with pytest.raises(Exception):
        await server.call_tool(
            "deliver_result", {"request_id": "req-no-ledger", "markdown": "answer"}
        )
    assert not list(config.lanebus_dir.glob("*.md"))
    assert "status: offered" in (config.requests_dir / "req-no-ledger.md").read_text()


async def test_delivery_retains_intent_if_outcome_append_fails(
    config: ResearchDeskConfig, ledger_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_request(config, "req-outcome-fails")
    actual_append = ledger_mod.append
    calls = 0

    def fail_after_intent(record: dict[str, Any], *, path: Path | None = None) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("outcome append failed")
        actual_append(record, path=path)

    monkeypatch.setattr(ledger_mod, "append", fail_after_intent)
    server = desk_mcp.build_server(config, ledger_path=ledger_path)
    with pytest.raises(Exception):
        await server.call_tool(
            "deliver_result", {"request_id": "req-outcome-fails", "markdown": "answer"}
        )
    rows = ledger_mod.read_records(ledger_path).records
    assert [row["outcome"] for row in rows] == ["pending"]
    assert len(list(config.lanebus_dir.glob("*.md"))) == 1


def test_check_reports_the_actual_directories_and_ledger(
    config: ResearchDeskConfig,
    ledger_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(desk_mcp, "load_connector_key", lambda: KEY)
    monkeypatch.setattr(desk_mcp.ResearchDeskConfig, "from_env", lambda: config)
    monkeypatch.setenv("HAPAX_RESEARCH_DESK_LEDGER", str(ledger_path))
    assert desk_mcp.main(["--check"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["requests_dir"] == str(config.requests_dir)
    assert report["ledger"] == str(ledger_path)
    assert report["key_present"] is True


def test_check_refuses_missing_queue_directory(
    config: ResearchDeskConfig,
    ledger_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shutil.rmtree(config.requests_dir)
    monkeypatch.setattr(desk_mcp, "load_connector_key", lambda: KEY)
    monkeypatch.setattr(desk_mcp.ResearchDeskConfig, "from_env", lambda: config)
    monkeypatch.setenv("HAPAX_RESEARCH_DESK_LEDGER", str(ledger_path))
    assert desk_mcp.main(["--check"]) == 2
    assert "missing directories" in capsys.readouterr().err
