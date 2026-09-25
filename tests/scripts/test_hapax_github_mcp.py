"""Tests for the GitHub MCP launcher wrapper."""

from __future__ import annotations

import os
import pwd
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


def _canonical_resolver_source() -> str:
    text = WRAPPER.read_text(encoding="utf-8")
    git_start = text.index("canonical_git() {")
    resolver_end = text.index("\n}\n\nresolve_canonical_wrapper\n", git_start) + len("\n}\n")
    return text[git_start:resolver_end]


def _canonical_release(tmp_path: Path) -> tuple[Path, Path, str]:
    account_home = tmp_path / "account-home"
    activation = account_home / ".cache" / "hapax" / "source-activation"
    staging = activation / "staging"
    wrapper = staging / "scripts" / "hapax-github-mcp"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("#!/usr/bin/bash\nexit 0\n", encoding="utf-8")
    wrapper.chmod(0o755)
    subprocess.run(["/usr/bin/git", "init", "-q", str(staging)], check=True)
    subprocess.run(
        ["/usr/bin/git", "-C", str(staging), "config", "user.name", "MCP Test"],
        check=True,
    )
    subprocess.run(
        ["/usr/bin/git", "-C", str(staging), "config", "user.email", "mcp@test.invalid"],
        check=True,
    )
    subprocess.run(["/usr/bin/git", "-C", str(staging), "add", "."], check=True)
    subprocess.run(
        ["/usr/bin/git", "-C", str(staging), "commit", "-q", "-m", "fixture"],
        check=True,
    )
    sha = subprocess.run(
        ["/usr/bin/git", "-C", str(staging), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    releases = activation / "releases"
    releases.mkdir()
    release = releases / sha
    staging.rename(release)
    (activation / "worktree").symlink_to(release)
    return account_home, release / "scripts" / "hapax-github-mcp", sha


def _run_canonical_resolver(account_home: Path) -> subprocess.CompletedProcess[str]:
    source = f"""
set -euo pipefail
ACCOUNT_HOME="$1"
canonical_refusal() {{
  /usr/bin/printf '%s\\n' "$1" >&2
  exit 2
}}
{_canonical_resolver_source()}
resolve_canonical_wrapper
/usr/bin/printf '%s\\n' "$CANONICAL_SHA" "$CANONICAL_WRAPPER"
"""
    return subprocess.run(
        ["/usr/bin/bash", "--noprofile", "--norc", "-s", "--", str(account_home)],
        input=source,
        text=True,
        capture_output=True,
        check=False,
    )


def test_github_mcp_launch_uses_fixed_credential_and_docker_commands() -> None:
    text = WRAPPER.read_text(encoding="utf-8")

    assert "PATH=/usr/local/bin:/usr/bin:/bin" in text
    assert "DOCKER_HOST=unix:///var/run/docker.sock" in text
    assert "/usr/bin/pass show" in text
    assert "/usr/bin/gh auth token" in text
    assert "/usr/bin/jq -r" in text
    assert "/usr/bin/docker run -i --rm" in text
    assert '--cidfile "$CID_FILE"' in text
    assert "--memory 512M" in text
    assert "--memory-swap 768M" in text
    assert "--oom-kill-disable" not in text
    assert "--log-driver none" in text
    assert "-e GITHUB_PERSONAL_ACCESS_TOKEN" in text
    assert "search_pull_requests,pull_request_read,merge_pull_request" in text
    assert "add_issue_comment,create_pull_request" in text
    assert 'FILTER_ARGS=(--tools="$TOOLS")' in text
    assert '/usr/bin/docker rm -f "$cid"' in text
    assert '/usr/bin/docker rm -f "$CONTAINER_NAME"' not in text


def _run_launch_tail(
    tmp_path: Path,
    *,
    cleanup_mode: str = "absent",
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_args = tmp_path / "docker-args.txt"
    docker_calls = tmp_path / "docker-calls.txt"
    token_seen = tmp_path / "token-seen"
    fake_pass = bin_dir / "pass"
    fake_pass.write_text(
        """#!/usr/bin/env bash
if [ "$1" = show ] && [ "$2" = github/codex-personal-access-token ]; then
  printf '%s\\n' test-token
  exit 0
fi
exit 1
""",
        encoding="utf-8",
    )
    fake_pass.chmod(0o755)
    fake_gh = bin_dir / "gh"
    fake_gh.write_text("#!/usr/bin/bash\nexit 1\n", encoding="utf-8")
    fake_gh.chmod(0o755)
    fake_jq = bin_dir / "jq"
    fake_jq.write_text("#!/usr/bin/bash\nexit 1\n", encoding="utf-8")
    fake_jq.chmod(0o755)
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$TEST_DOCKER_CALLS"
case "$1" in
  run)
    printf '%s\\n' "$*" > "$TEST_DOCKER_ARGS"
    cidfile=""
    prior=""
    for argument in "$@"; do
      if [ "$prior" = --cidfile ]; then
        cidfile="$argument"
        break
      fi
      prior="$argument"
    done
    test -n "$cidfile"
    printf '%s' "$TEST_CONTAINER_ID" > "$cidfile"
    if [ -n "${GITHUB_PERSONAL_ACCESS_TOKEN:-}" ]; then
      printf 'present\\n' > "$TEST_TOKEN_SEEN"
    fi
    ;;
  ps)
    if [ "$TEST_CLEANUP_MODE" = rm-failure ]; then
      printf '%s\\n' "$TEST_CONTAINER_ID"
    fi
    ;;
  rm)
    if [ "$TEST_CLEANUP_MODE" = rm-failure ]; then
      printf 'simulated Docker cleanup denial\\n' >&2
      exit 73
    fi
    ;;
  *)
    exit 91
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    source = WRAPPER.read_text(encoding="utf-8")
    diagnostic_start = source.index("bounded_diagnostic_reason() {")
    diagnostic_end = source.index("run_test_refusal_probe() {", diagnostic_start)
    diagnostic_functions = source[diagnostic_start:diagnostic_end]
    launch_tail = source[source.index("pass_first_line() {") :]
    for production, fixture in (
        ("/usr/bin/pass", fake_pass),
        ("/usr/bin/gh", fake_gh),
        ("/usr/bin/jq", fake_jq),
        ("/usr/bin/docker", fake_docker),
    ):
        launch_tail = launch_tail.replace(production, str(fixture))
    script = f"""
set -euo pipefail
HOME="$TEST_HOME"
USER=hapax
LOG_DIR="$TEST_HOME/logs"
LOG_FILE="$LOG_DIR/github-mcp.log"
LOGGER=/usr/bin/logger
{diagnostic_functions}
{launch_tail}
"""
    env = os.environ.copy()
    env["TEST_HOME"] = str(tmp_path)
    env.pop("GITHUB_PERSONAL_ACCESS_TOKEN", None)
    env.pop("CODEX_GITHUB_PERSONAL_ACCESS_TOKEN", None)
    env.pop("HAPAX_GITHUB_MCP_TOOLS", None)
    env.pop("HAPAX_GITHUB_MCP_TOOLSETS", None)
    env.update(
        {
            "TEST_CLEANUP_MODE": cleanup_mode,
            "TEST_CONTAINER_ID": "a" * 64,
            "TEST_DOCKER_ARGS": str(docker_args),
            "TEST_DOCKER_CALLS": str(docker_calls),
            "TEST_TOKEN_SEEN": str(token_seen),
        }
    )

    result = subprocess.run(
        ["/usr/bin/bash", "--noprofile", "--norc"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    return result, docker_args, token_seen


def test_github_mcp_launch_tail_loads_token_and_applies_limits(tmp_path: Path) -> None:
    result, docker_args, token_seen = _run_launch_tail(tmp_path)

    assert result.returncode == 0, result.stderr
    args = docker_args.read_text(encoding="utf-8")
    assert "--memory 512M" in args
    assert "--memory-swap 768M" in args
    assert "--oom-kill-disable" not in args
    assert "--log-driver none" in args
    assert "-e GITHUB_PERSONAL_ACCESS_TOKEN" in args
    assert "--tools=search_pull_requests,pull_request_read,merge_pull_request" in args
    assert "add_issue_comment,create_pull_request" in args
    assert token_seen.read_text(encoding="utf-8").strip() == "present"
    assert "test-token" not in args
    assert "test-token" not in result.stdout
    assert "test-token" not in result.stderr
    assert not list((tmp_path / "logs").glob("github-mcp.*/container.cid"))


def test_github_mcp_cleanup_retains_bound_id_and_reports_removal_failure(
    tmp_path: Path,
) -> None:
    result, _docker_args, _token_seen = _run_launch_tail(tmp_path, cleanup_mode="rm-failure")

    assert result.returncode == 2
    assert "immutable-ID cleanup failed and container" in result.stderr
    assert "simulated Docker cleanup denial" in result.stderr
    assert "next action: inspect and remove that exact ID" in result.stderr
    retained = list((tmp_path / "logs").glob("github-mcp.*/container.cid"))
    assert len(retained) == 1
    assert retained[0].read_text(encoding="utf-8") == "a" * 64
    diagnostic = (tmp_path / "logs" / "github-mcp.log").read_text(encoding="utf-8")
    assert "immutable-ID cleanup failed" in diagnostic
    assert "simulated Docker cleanup denial" in diagnostic
    calls = (tmp_path / "docker-calls.txt").read_text(encoding="utf-8").splitlines()
    assert f"rm -f {'a' * 64}" in calls
    assert all("hapax-github-mcp-hapax-" not in call for call in calls if call.startswith("rm "))


def test_github_mcp_accepts_only_an_exact_release_wrapper(tmp_path: Path) -> None:
    account_home, wrapper, sha = _canonical_release(tmp_path)

    accepted = _run_canonical_resolver(account_home)

    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout.splitlines() == [sha, str(wrapper)]

    wrapper.write_text("#!/usr/bin/bash\nexit 99\n", encoding="utf-8")
    wrapper.chmod(0o755)
    rejected = _run_canonical_resolver(account_home)

    assert rejected.returncode == 2
    assert "canonical wrapper does not match its release Git object" in rejected.stderr
    assert "next action: discard the modified release" in rejected.stderr


def test_github_mcp_rejects_release_path_that_does_not_match_head(tmp_path: Path) -> None:
    account_home, wrapper, _sha = _canonical_release(tmp_path)
    activation = account_home / ".cache" / "hapax" / "source-activation"
    wrong_release = wrapper.parents[1].with_name("0" * 40)
    wrapper.parents[1].rename(wrong_release)
    (activation / "worktree").unlink()
    (activation / "worktree").symlink_to(wrong_release)

    result = _run_canonical_resolver(account_home)

    assert result.returncode == 2
    assert "canonical release Git identity does not match its release path" in result.stderr
    assert "next action: discard the malformed release" in result.stderr


def test_github_mcp_rejects_hostile_home_before_credentials(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    credential_marker = tmp_path / "credential-command-ran"
    docker_marker = tmp_path / "docker-ran"
    for name, marker in (
        ("pass", credential_marker),
        ("gh", credential_marker),
        ("docker", docker_marker),
    ):
        executable = bin_dir / name
        executable.write_text(f"#!/usr/bin/bash\ntouch {marker}\n", encoding="utf-8")
        executable.chmod(0o755)

    result = subprocess.run(
        [str(WRAPPER)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GITHUB_PERSONAL_ACCESS_TOKEN": "must-not-be-forwarded",
        },
        timeout=5,
    )

    assert result.returncode == 2
    assert "HOME does not match the passwd-backed account home" in result.stderr
    assert "next action: remove the hostile HOME override" in result.stderr
    assert not credential_marker.exists()
    assert not docker_marker.exists()
    assert "no GitHub token found" not in result.stderr
    assert "must-not-be-forwarded" not in result.stderr


def test_github_mcp_reports_canonical_refusal_log_failure(tmp_path: Path) -> None:
    occupied = tmp_path / "not-a-directory"
    occupied.write_text("occupied\n", encoding="utf-8")
    fake_logger = tmp_path / "logger"
    fake_logger.write_text(
        "#!/usr/bin/bash\nprintf 'journal socket unavailable\\n' >&2\nexit 73\n",
        encoding="utf-8",
    )
    fake_logger.chmod(0o755)
    account_home = pwd.getpwuid(os.getuid()).pw_dir

    result = subprocess.run(
        [str(WRAPPER), "--test-canonical-refusal"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": account_home,
            "HAPAX_GITHUB_MCP_TEST_MODE": "1",
            "HAPAX_GITHUB_MCP_TEST_LOG_DIR": str(occupied / "mcp-logs"),
            "HAPAX_GITHUB_MCP_TEST_LOGGER": str(fake_logger),
        },
        timeout=5,
    )

    assert result.returncode == 2
    assert "canonical probe; next action: repair source activation" in result.stderr
    assert "diagnostic logging failed for" in result.stderr
    assert "not-a-directory" in result.stderr
    assert "journal socket unavailable" in result.stderr
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
    account_home = pwd.getpwuid(os.getuid()).pw_dir

    result = subprocess.run(
        [str(WRAPPER), "--test-canonical-refusal"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": f"{account_home}/",
            "HAPAX_GITHUB_MCP_TEST_MODE": "1",
            "HAPAX_GITHUB_MCP_TEST_LOG_DIR": str(occupied / "mcp-logs"),
            "HAPAX_GITHUB_MCP_TEST_LOGGER": str(fake_logger),
            "TEST_LOGGER_CALLS": str(logger_calls),
        },
    )

    assert result.returncode == 2
    assert "recorded in the system journal" in result.stderr
    assert "occupied" in result.stderr or "Not a directory" in result.stderr
    assert "--tag hapax-github-mcp -- canonical probe" in logger_calls.read_text(encoding="utf-8")


def test_github_mcp_refusal_probe_errors_all_carry_next_actions() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    start = text.index("run_test_refusal_probe() {")
    end = text.index('\n}\n\nif [ "${1:-}" = --test-canonical-refusal', start)
    probe = text[start:end]

    error_lines = [line for line in probe.splitlines() if 'echo "hapax-github-mcp:' in line]
    assert len(error_lines) == 5
    assert all("next action:" in line for line in error_lines)
