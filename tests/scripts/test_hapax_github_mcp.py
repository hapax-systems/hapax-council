"""Tests for the GitHub MCP launcher wrapper."""

from __future__ import annotations

import os
import pwd
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
WRAPPER = REPO_ROOT / "scripts" / "hapax-github-mcp"


def _canonical_refusal_source(logger: Path) -> str:
    source = WRAPPER.read_text(encoding="utf-8")
    body = source.split("canonical_refusal() {", 1)[1].split("\n}\n\nCANONICAL_ALIAS", 1)[0]
    return ("canonical_refusal() {" + body + "\n}").replace("/usr/bin/logger", str(logger))


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

    canonical_wrapper = (
        tmp_path / ".cache/hapax/source-activation/worktree/scripts/hapax-github-mcp"
    )
    canonical_wrapper.parent.mkdir(parents=True)
    shutil.copy2(WRAPPER, canonical_wrapper)

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
    assert "--memory 512M" in args
    assert "--memory-swap 768M" in args
    assert "--oom-kill-disable" not in args
    assert "--log-driver none" in args
    assert "-e GITHUB_PERSONAL_ACCESS_TOKEN" in args
    assert "--tools=search_pull_requests,pull_request_read,merge_pull_request" in args
    assert "add_issue_comment,create_pull_request" in args
    assert token_seen.read_text().strip() == "present"
    assert "test-token" not in args
    assert "test-token" not in result.stdout
    assert "test-token" not in result.stderr


def test_github_mcp_fails_before_credentials_when_canonical_release_is_missing(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [str(WRAPPER)],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(tmp_path)},
        timeout=5,
    )

    assert result.returncode == 2
    assert "canonical source-activation wrapper is unavailable" in result.stderr
    assert "next action: reconcile source activation" in result.stderr
    assert "diagnostic recorded in" in result.stderr
    assert "canonical source-activation wrapper is unavailable" in (
        tmp_path / ".cache/hapax/mcp-logs/github-mcp.log"
    ).read_text(encoding="utf-8")
    assert "no GitHub token found" not in result.stderr


def test_github_mcp_reports_canonical_refusal_log_failure(tmp_path: Path) -> None:
    cache_root = tmp_path / "not-a-directory"
    cache_root.write_text("occupied\n", encoding="utf-8")

    result = subprocess.run(
        [str(WRAPPER)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "XDG_CACHE_HOME": str(cache_root),
        },
        timeout=5,
    )

    assert result.returncode == 2
    assert "canonical source-activation wrapper is unavailable" in result.stderr
    assert (
        "file diagnostic failed for" in result.stderr
        or "diagnostic logging failed for" in result.stderr
    )
    assert "system journal fallback unavailable" in result.stderr
    assert "diagnostic recorded in" not in result.stderr


def test_github_mcp_uses_journal_fallback_for_equivalent_account_home(
    tmp_path: Path,
) -> None:
    occupied = tmp_path / "occupied"
    occupied.write_text("not a directory\n", encoding="utf-8")
    logger_calls = tmp_path / "logger-calls"
    fake_logger = tmp_path / "logger"
    fake_logger.write_text(
        '#!/usr/bin/bash\nprintf \'%s\n\' "$*" > "$TEST_LOGGER_CALLS"\n',
        encoding="utf-8",
    )
    fake_logger.chmod(0o755)
    script = (
        'LOG_DIR="$TEST_LOG_DIR"\n'
        'LOG_FILE="$LOG_DIR/github-mcp.log"\n'
        f"{_canonical_refusal_source(fake_logger)}\n"
        'canonical_refusal "canonical probe; next action: repair source activation"\n'
    )
    account_home = pwd.getpwuid(os.getuid()).pw_dir

    result = subprocess.run(
        ["/usr/bin/bash", "--noprofile", "--norc"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": f"{account_home}/",
            "TEST_LOG_DIR": str(occupied / "mcp-logs"),
            "TEST_LOGGER_CALLS": str(logger_calls),
        },
    )

    assert result.returncode == 2
    assert "recorded in the system journal" in result.stderr
    assert "--tag hapax-github-mcp -- canonical probe" in logger_calls.read_text(encoding="utf-8")
