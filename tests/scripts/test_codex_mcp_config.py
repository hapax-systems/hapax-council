"""Codex MCP configuration contract tests."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
CODEX_CONFIG = REPO_ROOT / "config" / "codex" / "config.toml"
CODEX_LAUNCHER = REPO_ROOT / "scripts" / "hapax-codex"
CODEX_INSTALLER = REPO_ROOT / "scripts" / "install-codex-config.sh"
TAVILY_WRAPPER = REPO_ROOT / "scripts" / "hapax-tavily-mcp"
PLAYWRIGHT_WRAPPER = REPO_ROOT / "scripts" / "hapax-playwright-mcp"
GITHUB_WRAPPER = REPO_ROOT / "scripts" / "hapax-github-mcp"
GEMINI_WRAPPER = REPO_ROOT / "scripts" / "hapax-gemini-mcp"
CONTEXT7_WRAPPER = REPO_ROOT / "scripts" / "hapax-context7-mcp"


def _installed_config(tmp_path: Path) -> dict:
    codex_home = tmp_path / "codex-home"
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [str(CODEX_INSTALLER), str(CODEX_CONFIG)],
        capture_output=True,
        text=True,
        env={
            "HOME": str(home),
            "CODEX_HOME": str(codex_home),
            "HAPAX_COUNCIL_DIR": str(REPO_ROOT),
            "HAPAX_PROJECTS_DIR": str(home / "projects"),
            "HAPAX_MCP_DIR": str(home / "projects" / "hapax-mcp"),
            "PATH": "/usr/bin:/bin",
        },
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    return tomllib.loads((codex_home / "config.toml").read_text())


def test_epidemic_sound_mcp_is_decommissioned_from_codex() -> None:
    config = tomllib.loads(CODEX_CONFIG.read_text())
    launcher = CODEX_LAUNCHER.read_text()

    assert "epidemic-sound" not in config["mcp_servers"]
    assert "mcp_servers.epidemic-sound" not in launcher
    assert "CODEX_EPIDEMIC_SOUND_TOKEN" not in launcher


def test_codex_config_template_does_not_commit_operator_home_path() -> None:
    assert "/home/hapax/" not in CODEX_CONFIG.read_text()


def test_codex_config_trusts_projects_and_council_root(tmp_path: Path) -> None:
    config = _installed_config(tmp_path)

    projects = config["projects"]
    assert projects[str(tmp_path / "home" / "projects")]["trust_level"] == "trusted"
    assert projects[str(REPO_ROOT)]["trust_level"] == "trusted"


def test_tavily_config_uses_stdio_wrapper_only(tmp_path: Path) -> None:
    config = _installed_config(tmp_path)

    server = config["mcp_servers"]["tavily"]
    assert server == {"command": str(TAVILY_WRAPPER)}


def test_tavily_token_is_not_exported_by_parent_launcher() -> None:
    text = CODEX_LAUNCHER.read_text()

    assert "mcp_servers.tavily.command" in text
    assert "load_first_available_pass_secret TAVILY_API_KEY" not in text
    assert "export TAVILY_API_KEY" not in text
    assert "unset TAVILY_API_KEY" in text


def test_playwright_mcp_uses_noninteractive_wrapper(tmp_path: Path) -> None:
    config = _installed_config(tmp_path)
    launcher = CODEX_LAUNCHER.read_text()
    wrapper = PLAYWRIGHT_WRAPPER.read_text()

    assert config["mcp_servers"]["playwright"] == {"command": str(PLAYWRIGHT_WRAPPER)}
    assert (
        'mcp_servers.playwright.command=\\"$COUNCIL_DIR/scripts/hapax-playwright-mcp\\"' in launcher
    )
    assert "NPM_CONFIG_YES=true" in wrapper
    assert 'npx -y "$PACKAGE"' in wrapper


def test_gemini_mcp_uses_noninteractive_wrapper(tmp_path: Path) -> None:
    config = _installed_config(tmp_path)
    launcher = CODEX_LAUNCHER.read_text()
    wrapper = GEMINI_WRAPPER.read_text()

    assert config["mcp_servers"]["gemini-cli"] == {"command": str(GEMINI_WRAPPER)}
    assert 'mcp_servers.gemini-cli.command=\\"$COUNCIL_DIR/scripts/hapax-gemini-mcp\\"' in launcher
    assert "mcp_servers.gemini-cli.args=[]" in launcher
    assert "NPM_CONFIG_YES=true" in wrapper
    assert 'npx -y "$PACKAGE"' in wrapper


def test_github_mcp_uses_secret_loading_wrapper(tmp_path: Path) -> None:
    config = _installed_config(tmp_path)
    launcher = CODEX_LAUNCHER.read_text()
    wrapper = GITHUB_WRAPPER.read_text()

    assert config["mcp_servers"]["github"] == {"command": str(GITHUB_WRAPPER)}
    assert 'mcp_servers.github.command=\\"$COUNCIL_DIR/scripts/hapax-github-mcp\\"' in launcher
    assert "bearer_token_env_var" not in str(config["mcp_servers"]["github"])
    assert "load_first_available_pass_secret CODEX_GITHUB_PERSONAL_ACCESS_TOKEN" not in launcher
    assert 'GITHUB_PERSONAL_ACCESS_TOKEN="$CODEX_GITHUB_PERSONAL_ACCESS_TOKEN"' not in launcher
    assert "load_first_available_pass_secret GITHUB_PERSONAL_ACCESS_TOKEN" in wrapper
    assert "github/codex-personal-access-token" in wrapper
    assert "-e GITHUB_PERSONAL_ACCESS_TOKEN" in wrapper
    assert "--log-driver none" in wrapper


def test_context7_mcp_uses_secret_loading_wrapper(tmp_path: Path) -> None:
    config = _installed_config(tmp_path)
    launcher = CODEX_LAUNCHER.read_text()
    wrapper = CONTEXT7_WRAPPER.read_text()

    assert config["mcp_servers"]["context7"] == {"command": str(CONTEXT7_WRAPPER)}
    assert 'mcp_servers.context7.command=\\"$COUNCIL_DIR/scripts/hapax-context7-mcp\\"' in launcher
    assert "mcp_servers.context7.bearer_token_env_var" not in launcher
    assert "mcp_servers.context7.bearer_token=" not in launcher
    assert "unset CONTEXT7_API_KEY" in launcher
    assert "load_first_available_pass_secret CONTEXT7_API_KEY context7/api-key" in wrapper
    assert "CONTEXT7_API_KEY" not in str(config["mcp_servers"]["context7"])


def test_codex_mcp_scripts_are_valid_bash() -> None:
    result = subprocess.run(
        [
            "bash",
            "-n",
            str(CODEX_LAUNCHER),
            str(TAVILY_WRAPPER),
            str(PLAYWRIGHT_WRAPPER),
            str(GITHUB_WRAPPER),
            str(GEMINI_WRAPPER),
            str(CONTEXT7_WRAPPER),
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
