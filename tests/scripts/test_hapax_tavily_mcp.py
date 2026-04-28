"""Tests for scripts/hapax-tavily-mcp."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/hapax-tavily-mcp"
WATCHDOG = Path(__file__).resolve().parents[2] / "systemd/watchdogs/scout-watchdog"
POST_MERGE_DEPLOY = Path(__file__).resolve().parents[2] / "scripts/hapax-post-merge-deploy"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def test_launcher_injects_pass_key_only_into_child(tmp_path, monkeypatch):
    out_path = tmp_path / "child-env.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "pass",
        "#!/usr/bin/env bash\n"
        'test "$1" = show\n'
        'test "$2" = api/tavily\n'
        "printf '%s\\n' child-secret\n",
    )
    _write_executable(
        bin_dir / "capture-child",
        f"#!/usr/bin/env bash\nprintf '%s' \"$TAVILY_API_KEY\" > {out_path}\n",
    )
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        [str(SCRIPT), "--", "capture-child"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0
    assert out_path.read_text() == "child-secret"
    assert "child-secret" not in result.stdout
    assert "child-secret" not in result.stderr
    assert "TAVILY_API_KEY" not in os.environ


def test_launcher_failure_does_not_print_secret(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "pass",
        "#!/usr/bin/env bash\nprintf '%s\\n' hidden-secret >&2\nexit 1\n",
    )
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        [str(SCRIPT), "--", "does-not-run"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 1
    assert "hidden-secret" not in result.stdout
    assert "hidden-secret" not in result.stderr
    assert "api/tavily" in result.stderr


def test_launcher_dry_run_omits_secret(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "pass",
        "#!/usr/bin/env bash\nprintf '%s\\n' dry-secret\n",
    )
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HAPAX_TAVILY_MCP_DRY_RUN": "1",
    }

    result = subprocess.run(
        [str(SCRIPT), "--", "mcp-command"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0
    assert "dry-secret" not in result.stdout
    assert "child-only Tavily key" in result.stdout


def test_scout_watchdog_does_not_export_tavily_key():
    body = WATCHDOG.read_text(encoding="utf-8")

    assert "export TAVILY_API_KEY" not in body
    assert "shared.tavily_client" in body


def test_post_merge_deploy_coverage_classifies_watchdog_path():
    result = subprocess.run(
        [str(POST_MERGE_DEPLOY), "--report-coverage-stdin"],
        input="systemd/watchdogs/scout-watchdog\n",
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "covered by case-globs" in result.stdout
