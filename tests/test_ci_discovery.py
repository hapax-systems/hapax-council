"""Tests for shared/ci_discovery.py — CI discovery functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared.ci_discovery import (
    discover_agents,
    discover_mcp_servers,
    discover_repos,
    discover_services,
    discover_timers,
)


class TestDiscoverAgents:
    def test_finds_agent_modules(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "__init__.py").write_text("")
        (agents_dir / "briefing.py").write_text('if __name__ == "__main__":\n    pass')
        (agents_dir / "health_monitor.py").write_text('if __name__ == "__main__":\n    pass')
        (agents_dir / "shared_util.py").write_text("# no main block")
        (agents_dir / "__pycache__").mkdir()

        result = discover_agents(agents_dir)
        assert "briefing" in result
        assert "health-monitor" in result
        assert "shared-util" not in result
        assert "__init__" not in result

    def test_empty_dir(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        assert discover_agents(agents_dir) == []

    def test_normalizes_underscores(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "drift_detector.py").write_text('if __name__ == "__main__":\n    pass')
        result = discover_agents(agents_dir)
        assert "drift-detector" in result


class TestDiscoverTimers:
    @patch("subprocess.run")
    def test_parses_timer_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="daily-briefing.timer       enabled  enabled\nhealth-monitor.timer      enabled  enabled\n",
        )
        result = discover_timers()
        assert "daily-briefing" in result
        assert "health-monitor" in result

    @patch("subprocess.run")
    def test_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        assert discover_timers() == []

    @patch("subprocess.run")
    def test_subprocess_failure(self, mock_run):
        mock_run.side_effect = OSError("systemctl not found")
        assert discover_timers() == []


class TestDiscoverServices:
    @patch("subprocess.run")
    def test_parses_docker_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="litellm\nqdrant\npostgres\n",
        )
        result = discover_services()
        assert "litellm" in result
        assert "qdrant" in result
        assert "postgres" in result

    @patch("subprocess.run")
    def test_subprocess_failure(self, mock_run):
        mock_run.side_effect = OSError("docker not found")
        assert discover_services() == []


class TestDiscoverRepos:
    def test_finds_hapax_repos(self, tmp_path):
        # Create fake repos
        for name in ["ai-agents", "hapax-vscode", "unrelated"]:
            repo = tmp_path / name
            repo.mkdir()
            (repo / ".git").mkdir()
        # ai-agents has CLAUDE.md mentioning hapax
        (tmp_path / "ai-agents" / "CLAUDE.md").write_text("Part of hapax system")
        # hapax-vscode matches prefix
        (tmp_path / "hapax-vscode" / "CLAUDE.md").write_text("Extension project")
        # unrelated has no CLAUDE.md
        result = discover_repos(tmp_path)
        assert "ai-agents" in result
        assert "hapax-vscode" in result
        assert "unrelated" not in result


class TestDiscoverMcpServers:
    def test_parses_mcp_config(self, tmp_path):
        config = tmp_path / "mcp_servers.json"
        config.write_text('{"memory": {"command": "uvx"}, "tavily": {"command": "npx"}}')
        result = discover_mcp_servers(config)
        assert "memory" in result
        assert "tavily" in result

    def test_missing_config(self, tmp_path):
        assert discover_mcp_servers(tmp_path / "nonexistent.json") == []
