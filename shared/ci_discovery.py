"""CI discovery — find live Configuration Items for coverage enforcement.

Discovers agents, timers, services, repos, and MCP servers from the
filesystem, systemd, and Docker. Zero LLM calls.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def discover_agents(agents_dir: Path | None = None) -> list[str]:
    """Discover agent modules by scanning for files with __main__ blocks."""
    if agents_dir is None:
        from shared.config import AI_AGENTS_DIR

        agents_dir = AI_AGENTS_DIR / "agents"

    if not agents_dir.is_dir():
        return []

    agents = []
    for py_file in sorted(agents_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            content = py_file.read_text(errors="replace")
            if "__name__" in content and "__main__" in content:
                name = py_file.stem.replace("_", "-")
                agents.append(name)
        except OSError:
            continue
    return agents


def discover_timers() -> list[str]:
    """Discover active systemd user timers."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-unit-files", "*.timer", "--no-legend"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        timers = []
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if parts:
                name = parts[0].removesuffix(".timer")
                timers.append(name)
        return timers
    except (OSError, subprocess.TimeoutExpired):
        return []


def discover_services(compose_dir: Path | None = None) -> list[str]:
    """Discover running Docker Compose services."""
    if compose_dir is None:
        from shared.config import LLM_STACK_DIR

        compose_dir = LLM_STACK_DIR

    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(compose_dir) if compose_dir.is_dir() else None,
        )
        if result.returncode != 0:
            return []
        return [s.strip() for s in result.stdout.strip().splitlines() if s.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def discover_repos(projects_dir: Path | None = None) -> list[str]:
    """Discover hapax-related git repos.

    A repo is hapax-related if its name starts with 'hapax-' or it has a
    CLAUDE.md containing 'hapax' (case-insensitive).
    """
    if projects_dir is None:
        from shared.config import HAPAX_PROJECTS_DIR

        projects_dir = HAPAX_PROJECTS_DIR

    if not projects_dir.is_dir():
        return []

    repos = []
    for entry in sorted(projects_dir.iterdir()):
        if not entry.is_dir() or not (entry / ".git").exists():
            continue
        # Match by name prefix
        if entry.name.startswith("hapax-"):
            repos.append(entry.name)
            continue
        # Match by CLAUDE.md content
        claude_md = entry / "CLAUDE.md"
        if claude_md.is_file():
            try:
                content = claude_md.read_text(errors="replace")[:2000]
                if "hapax" in content.lower():
                    repos.append(entry.name)
            except OSError:
                continue
    return repos


def discover_mcp_servers(config_path: Path | None = None) -> list[str]:
    """Discover configured MCP servers from Claude Code config."""
    if config_path is None:
        from shared.config import CLAUDE_CONFIG_DIR

        config_path = CLAUDE_CONFIG_DIR / "mcp_servers.json"

    if not config_path.is_file():
        return []

    try:
        data = json.loads(config_path.read_text())
        return sorted(data.keys()) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError):
        return []
