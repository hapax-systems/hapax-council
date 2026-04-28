"""Tests for the Tavily MCP launcher wrapper."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

from shared.tavily_client import TavilySearchResponse, TavilySearchResult

REPO_ROOT = Path(__file__).parent.parent.parent
WRAPPER = REPO_ROOT / "scripts" / "hapax-tavily-mcp"
SERVER = REPO_ROOT / "scripts" / "hapax_tavily_mcp_server.py"
WATCHDOG = REPO_ROOT / "systemd" / "watchdogs" / "scout-watchdog"


def test_tavily_mcp_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(WRAPPER)],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr


def test_tavily_mcp_server_search_uses_guarded_client(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("hapax_tavily_mcp_server", SERVER)
    assert spec and spec.loader
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    calls = []

    class FakeClient:
        def search(self, request):
            calls.append(request)
            return TavilySearchResponse(
                query=request.query,
                results=[
                    TavilySearchResult(
                        title="Docs",
                        url="https://docs.tavily.com",
                        content="Tavily docs",
                    )
                ],
            )

    monkeypatch.setattr(server, "TavilyClient", lambda: FakeClient())

    payload = json.loads(server.tavily_search("tavily docs", lane="interactive_coding"))

    assert payload["ok"] is True
    assert payload["results"][0]["url"] == "https://docs.tavily.com"
    assert calls[0].lane == "interactive_coding"


def test_tavily_mcp_default_proxy_execs_repo_server_without_exported_token(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    out_file = tmp_path / "uv-args.txt"
    token_seen = tmp_path / "token-seen"

    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" > {out_file}
if [ -n "${{TAVILY_API_KEY:-}}" ]; then
  printf 'present\\n' > {token_seen}
fi
"""
    )
    fake_uv.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(tmp_path)
    env["UV_BIN"] = str(fake_uv)
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env.pop("TAVILY_API_KEY", None)

    result = subprocess.run(
        [str(WRAPPER)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    args = out_file.read_text()
    assert "--directory" in args
    assert str(REPO_ROOT) in args
    assert str(SERVER) in args
    assert not token_seen.exists()


def test_tavily_mcp_rejects_direct_upstream_without_explicit_override(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["HAPAX_TAVILY_MCP_MODE"] = "local"
    env.pop("HAPAX_TAVILY_ALLOW_UPSTREAM_MCP", None)

    result = subprocess.run(
        [str(WRAPPER)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "bypasses Hapax budget/cache/ledger guardrails" in result.stderr


def test_tavily_mcp_upstream_remote_mode_is_disabled_even_with_override(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npx_called = tmp_path / "npx-called"

    fake_npx = bin_dir / "npx"
    fake_npx.write_text(
        f"""#!/usr/bin/env bash
printf 'called\\n' > {npx_called}
"""
    )
    fake_npx.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(tmp_path)
    env["HAPAX_TAVILY_MCP_MODE"] = "upstream-remote"
    env["HAPAX_TAVILY_ALLOW_UPSTREAM_MCP"] = "1"
    env.pop("TAVILY_API_KEY", None)

    result = subprocess.run(
        [str(WRAPPER)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "remote upstream mode is disabled" in result.stderr
    assert "remote-token" not in result.stderr
    assert not npx_called.exists()


def test_scout_watchdog_does_not_export_tavily_api_key() -> None:
    text = WATCHDOG.read_text()

    assert "export TAVILY_API_KEY" not in text
    assert "shared.tavily_client" in text
