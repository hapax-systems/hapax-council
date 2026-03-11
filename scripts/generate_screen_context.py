#!/usr/bin/env python3
"""Generate static system context for the screen analyzer.

Queries live system state and writes a context file that the screen
analyzer uses as its system knowledge prompt.

Output: ~/.local/share/hapax-voice/screen_context.md
"""

from __future__ import annotations

import subprocess
from pathlib import Path

OUTPUT_PATH = Path.home() / ".local" / "share" / "hapax-voice" / "screen_context.md"


def run_cmd(cmd: list[str], timeout: int = 10) -> str:
    """Run a command and return stdout, or error message."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()
    except Exception as exc:
        return f"(unavailable: {exc})"


def get_docker_services() -> str:
    llm_stack = Path.home() / "llm-stack"
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(llm_stack) if llm_stack.exists() else None,
        )
        return result.stdout.strip()
    except Exception as exc:
        return f"(unavailable: {exc})"


def get_systemd_user_units() -> str:
    output = run_cmd(
        [
            "systemctl",
            "--user",
            "list-units",
            "--type=service,timer",
            "--state=active",
            "--no-pager",
        ]
    )
    return output


def get_listening_ports() -> str:
    output = run_cmd(["ss", "-tlnp"])
    return output


def get_webcam_info() -> str:
    """Enumerate connected webcam devices."""
    try:
        by_id = Path("/dev/v4l/by-id")
        if not by_id.exists():
            return "(no V4L2 devices found)"
        devices = sorted(by_id.iterdir())
        return "\n".join(f"  - {d.name} -> {d.resolve()}" for d in devices)
    except Exception as exc:
        return f"(unavailable: {exc})"


def get_agent_list() -> str:
    agents_dir = Path.home() / "projects" / "ai-agents" / "agents"
    if not agents_dir.exists():
        return "(agents directory not found)"
    agents = sorted(
        d.name for d in agents_dir.iterdir() if d.is_dir() and not d.name.startswith("_")
    )
    return "\n".join(f"- {a}" for a in agents)


def generate() -> str:
    sections = [
        "# Hapax System Context for Screen Analyzer",
        "",
        "This context helps the screen analyzer make intelligent observations about the operator's screen.",
        "",
        "## Running Docker Services",
        "",
        "```",
        get_docker_services(),
        "```",
        "",
        "## Active Systemd User Services/Timers",
        "",
        "```",
        get_systemd_user_units(),
        "```",
        "",
        "## Listening TCP Ports",
        "",
        "```",
        get_listening_ports(),
        "```",
        "",
        "## Agent Roster",
        "",
        get_agent_list(),
        "",
        "## Webcam Devices",
        "",
        get_webcam_info(),
        "",
        "## Common Error Signatures",
        "",
        "- 'connection refused on 6333' = Qdrant is down (breaks RAG ingestion, profiler, search)",
        "- 'connection refused on 4000' = LiteLLM proxy is down (breaks all agent LLM calls)",
        "- 'connection refused on 3000' = Langfuse is down (breaks observability, non-critical)",
        "- 'CUDA out of memory' = GPU VRAM exhausted (unload Ollama models, check vram-watchdog)",
        "- 'unhealthy' in docker ps = container health check failing",
        "",
        "## Operator Desktop Tools",
        "",
        "- VS Code (Flatpak): code editor",
        "- Google Chrome (Flatpak): web browser",
        "- cosmic-term: terminal emulator",
        "- Obsidian: knowledge management (vault at ~/Documents/Personal/)",
        "- Claude Code: CLI AI assistant (this system)",
        "",
    ]
    return "\n".join(sections)


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = generate()
    OUTPUT_PATH.write_text(content)
    print(f"Screen context written to {OUTPUT_PATH}")
    print(f"Size: {len(content)} chars")


if __name__ == "__main__":
    main()
