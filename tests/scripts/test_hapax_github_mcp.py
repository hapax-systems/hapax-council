"""Tests for the GitHub MCP launcher wrapper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
WRAPPER = REPO_ROOT / "scripts" / "hapax-github-mcp"


def test_github_mcp_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(WRAPPER)],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr


def test_github_mcp_loads_token_from_pass_and_filters_tools(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_args = tmp_path / "docker-args.txt"
    token_seen = tmp_path / "token-seen"

    fake_pass = bin_dir / "pass"
    fake_pass.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "show" ] && [ "$2" = "github/codex-personal-access-token" ]; then
  printf '%s\\n' 'test-token'
  exit 0
fi
exit 1
"""
    )
    fake_pass.chmod(0o755)

    fake_gh = bin_dir / "gh"
    fake_gh.write_text("#!/usr/bin/env bash\nexit 1\n")
    fake_gh.chmod(0o755)

    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
if [ "$1" = "rm" ]; then
  exit 0
fi
printf '%s\\n' "$*" > {docker_args}
if [ -n "${{GITHUB_PERSONAL_ACCESS_TOKEN:-}}" ]; then
  printf 'present\\n' > {token_seen}
fi
"""
    )
    fake_docker.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(tmp_path)
    env["USER"] = "hapax"
    env.pop("GITHUB_PERSONAL_ACCESS_TOKEN", None)
    env.pop("CODEX_GITHUB_PERSONAL_ACCESS_TOKEN", None)

    result = subprocess.run(
        [str(WRAPPER)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    args = docker_args.read_text()
    assert "--log-driver none" in args
    assert "-e GITHUB_PERSONAL_ACCESS_TOKEN" in args
    assert "--tools=search_pull_requests,pull_request_read,merge_pull_request" in args
    assert "add_issue_comment,create_pull_request" in args
    assert token_seen.read_text().strip() == "present"
    assert "test-token" not in args
    assert "test-token" not in result.stdout
    assert "test-token" not in result.stderr
