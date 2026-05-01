"""Tests for shared.ci_discovery.

133-LOC Configuration Item discovery — agents, timers, services,
repos, MCP servers. Untested before this commit.

Tests use the explicit path/dir parameters where available so the
real workspace is never mutated. Subprocess-based discoveries
(timers, services) are mocked at the subprocess.run boundary.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from shared.ci_discovery import (
    discover_agents,
    discover_mcp_servers,
    discover_repos,
    discover_services,
    discover_timers,
)

# ── discover_agents ────────────────────────────────────────────────


class TestDiscoverAgents:
    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert discover_agents(tmp_path / "nope") == []

    def test_finds_agents_with_main_block(self, tmp_path: Path) -> None:
        (tmp_path / "agent_one.py").write_text(
            "def main():\n    pass\n\nif __name__ == '__main__':\n    main()\n"
        )
        (tmp_path / "agent_two.py").write_text("if __name__ == '__main__':\n    print('hi')\n")
        result = discover_agents(tmp_path)
        assert sorted(result) == ["agent-one", "agent-two"]

    def test_skips_files_without_main(self, tmp_path: Path) -> None:
        (tmp_path / "lib.py").write_text("def helper(): pass\n")
        (tmp_path / "agent.py").write_text("if __name__ == '__main__': pass\n")
        assert discover_agents(tmp_path) == ["agent"]

    def test_skips_underscore_prefixed(self, tmp_path: Path) -> None:
        (tmp_path / "_internal.py").write_text("if __name__ == '__main__': pass\n")
        (tmp_path / "agent.py").write_text("if __name__ == '__main__': pass\n")
        assert discover_agents(tmp_path) == ["agent"]

    def test_underscore_in_name_becomes_dash(self, tmp_path: Path) -> None:
        (tmp_path / "voice_daemon.py").write_text("if __name__ == '__main__': pass\n")
        assert discover_agents(tmp_path) == ["voice-daemon"]


# ── discover_timers ────────────────────────────────────────────────


class TestDiscoverTimers:
    def test_returns_timer_names_without_suffix(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "hapax-sync.timer enabled enabled\nhapax-cleanup.timer disabled disabled\n"
        )
        with patch("shared.ci_discovery.subprocess.run", return_value=mock_result):
            assert discover_timers() == ["hapax-sync", "hapax-cleanup"]

    def test_systemctl_failure_returns_empty(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("shared.ci_discovery.subprocess.run", return_value=mock_result):
            assert discover_timers() == []

    def test_subprocess_timeout_returns_empty(self) -> None:
        with patch(
            "shared.ci_discovery.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="systemctl", timeout=10),
        ):
            assert discover_timers() == []

    def test_oserror_returns_empty(self) -> None:
        with patch(
            "shared.ci_discovery.subprocess.run",
            side_effect=OSError("systemctl not found"),
        ):
            assert discover_timers() == []


# ── discover_services ──────────────────────────────────────────────


class TestDiscoverServices:
    def test_returns_compose_service_names(self, tmp_path: Path) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "litellm\nqdrant\nlangfuse\n"
        with patch("shared.ci_discovery.subprocess.run", return_value=mock_result):
            assert discover_services(tmp_path) == ["litellm", "qdrant", "langfuse"]

    def test_filters_blank_lines(self, tmp_path: Path) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "litellm\n\nqdrant\n   \n"
        with patch("shared.ci_discovery.subprocess.run", return_value=mock_result):
            assert discover_services(tmp_path) == ["litellm", "qdrant"]

    def test_failure_returns_empty(self, tmp_path: Path) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("shared.ci_discovery.subprocess.run", return_value=mock_result):
            assert discover_services(tmp_path) == []


# ── discover_repos ─────────────────────────────────────────────────


class TestDiscoverRepos:
    def test_missing_projects_dir_returns_empty(self, tmp_path: Path) -> None:
        assert discover_repos(tmp_path / "nope") == []

    def test_finds_hapax_prefixed(self, tmp_path: Path) -> None:
        for repo in ["hapax-council", "hapax-officium", "other-project"]:
            (tmp_path / repo / ".git").mkdir(parents=True)
        result = discover_repos(tmp_path)
        assert sorted(result) == ["hapax-council", "hapax-officium"]

    def test_finds_repos_with_hapax_in_claude_md(self, tmp_path: Path) -> None:
        repo = tmp_path / "weird-name"
        (repo / ".git").mkdir(parents=True)
        (repo / "CLAUDE.md").write_text("# This is a Hapax-related project\n")
        result = discover_repos(tmp_path)
        assert "weird-name" in result

    def test_skips_non_git_directories(self, tmp_path: Path) -> None:
        (tmp_path / "hapax-fake").mkdir()  # no .git
        result = discover_repos(tmp_path)
        assert result == []

    def test_unrelated_repo_with_no_claude_md_excluded(self, tmp_path: Path) -> None:
        (tmp_path / "other-thing" / ".git").mkdir(parents=True)
        result = discover_repos(tmp_path)
        assert result == []


# ── discover_mcp_servers ───────────────────────────────────────────


class TestDiscoverMcpServers:
    def test_missing_config_returns_empty(self, tmp_path: Path) -> None:
        assert discover_mcp_servers(tmp_path / "nope.json") == []

    def test_returns_sorted_keys(self, tmp_path: Path) -> None:
        config = tmp_path / "mcp.json"
        config.write_text(
            json.dumps(
                {
                    "context7": {},
                    "gemini-cli": {},
                    "hapax": {},
                }
            )
        )
        assert discover_mcp_servers(config) == ["context7", "gemini-cli", "hapax"]

    def test_non_dict_returns_empty(self, tmp_path: Path) -> None:
        config = tmp_path / "mcp.json"
        config.write_text(json.dumps(["not", "a", "dict"]))
        assert discover_mcp_servers(config) == []

    def test_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        config = tmp_path / "mcp.json"
        config.write_text("{ not valid json")
        assert discover_mcp_servers(config) == []
