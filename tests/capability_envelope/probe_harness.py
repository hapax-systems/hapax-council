"""A stand-in harness for envelope tests: it tries every import a native harness makes.

It walks up from its working directory for instruction files, reads the user-level instruction,
memory and config files of every harness the estate runs, reads any absolute paths given on its
command line (a harness that resolves the operator's real home), runs the hooks its settings
name, and spawns the MCP servers its configs name. It never fails on a missing file. It writes
one JSON report to the path given by ``--report``.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from pathlib import Path

WALK_UP_NAMES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "GEMINI.md")
USER_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/CLAUDE.md",
    ".codex/AGENTS.md",
    ".gemini/GEMINI.md",
    ".grok/AGENTS.md",
    ".kimi-code/AGENTS.md",
    ".vibe/AGENTS.md",
)


def _read(path: Path, found: dict[str, str]) -> None:
    try:
        found[str(path)] = path.read_text(errors="replace")
    except OSError:
        pass


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _run(cmd: list[str], ran: list[str]) -> None:
    try:
        subprocess.run(cmd, timeout=10, check=False, capture_output=True)
        ran.append(" ".join(cmd))
    except OSError:
        pass


def main(argv: list[str]) -> int:
    report_path = Path(argv[argv.index("--report") + 1])
    extra = [Path(p) for p in argv[argv.index("--extra") + 1 :]] if "--extra" in argv else []
    home = Path(os.environ.get("HOME", "/nonexistent"))
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(home / ".claude")))
    found: dict[str, str] = {}
    hooks_run: list[str] = []
    mcp_spawned: list[str] = []

    here = Path.cwd()
    for directory in (here, *here.parents):
        for name in WALK_UP_NAMES:
            _read(directory / name, found)
    _read(here / "README.md", found)
    for sub in glob.glob(str(here / "**" / "AGENTS.md"), recursive=True):
        _read(Path(sub), found)
    for rel in USER_FILES:
        _read(home / rel, found)
    _read(config_dir / "CLAUDE.md", found)
    for memory in glob.glob(str(config_dir / "projects" / "*" / "memory" / "*.md")):
        _read(Path(memory), found)
    for path in extra:
        _read(path, found)

    for settings in (config_dir / "settings.json", here / ".claude" / "settings.json"):
        for groups in _load_json(settings).get("hooks", {}).values():
            for group in groups:
                for hook in group.get("hooks", []):
                    _run(["/bin/sh", "-c", hook["command"]], hooks_run)
    for mcp_config in (home / ".claude.json", here / ".mcp.json"):
        for server in _load_json(mcp_config).get("mcpServers", {}).values():
            _run([server["command"], *server.get("args", [])], mcp_spawned)

    marker = home / ".probe-persist-marker"
    prior_marker = marker.exists()
    try:
        marker.write_text("written by a previous run\n")
    except OSError:
        pass

    report_path.write_text(
        json.dumps(
            {
                "read": found,
                "hooks_run": hooks_run,
                "mcp_spawned": mcp_spawned,
                "env": dict(os.environ),
                "prior_marker": prior_marker,
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
