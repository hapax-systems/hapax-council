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


def _stage_wrapper_with_docker(
    tmp_path: Path,
    docker: Path,
    *,
    pass_bin: Path | None = None,
    gh_bin: Path | None = None,
) -> Path:
    source = WRAPPER.read_text(encoding="utf-8")
    assert source.count("/usr/bin/docker") == 2
    source = source.replace("/usr/bin/docker", str(docker))
    if pass_bin is not None:
        source = source.replace("/usr/bin/pass", str(pass_bin))
    if gh_bin is not None:
        source = source.replace("/usr/bin/gh", str(gh_bin))
    source = source.replace(
        'LOG_DIR="$HOME/.cache/hapax/mcp-logs"',
        f'LOG_DIR="{tmp_path / "mcp-logs"}"',
    )
    staged = tmp_path / "hapax-github-mcp"
    staged.write_text(source, encoding="utf-8")
    staged.chmod(0o755)
    return staged


def _base_env(tmp_path: Path, bin_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = pwd.getpwuid(os.geteuid()).pw_dir
    env["USER"] = "hostile-name-is-not-used"
    env.pop("XDG_CACHE_HOME", None)
    env.pop("GITHUB_PERSONAL_ACCESS_TOKEN", None)
    env.pop("CODEX_GITHUB_PERSONAL_ACCESS_TOKEN", None)
    return env


def test_github_mcp_pins_docker_and_cleans_up_by_full_id(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_calls = tmp_path / "docker-calls.txt"
    selector_leaks = tmp_path / "selector-leaks.txt"
    state = tmp_path / "container-state"
    container_id = "a" * 64

    fake_pass = bin_dir / "pass"
    fake_pass.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "show" ] && [ "$2" = "github/codex-personal-access-token" ]; then
  echo test-token
  exit 0
fi
exit 1
""",
        encoding="utf-8",
    )
    fake_pass.chmod(0o755)
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
exit 1
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    ambient_tool_ran = tmp_path / "ambient-tool-ran"
    fake_mkdir = bin_dir / "mkdir"
    fake_mkdir.write_text(
        f"#!/usr/bin/env bash\nprintf ran > {ambient_tool_ran}\nexit 99\n",
        encoding="utf-8",
    )
    fake_mkdir.chmod(0o755)

    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
token_state="$(env | grep -q '^GITHUB_PERSONAL_ACCESS_TOKEN=' && echo present || true)"
echo "$*|token=$token_state" >> "{docker_calls}"
env | grep '^DOCKER_' >> "{selector_leaks}" || true
case " $* " in
  *" image inspect "*)
    echo 'sha256:30197479d8036c7811892bc07e06f9a05c9ef3cdd79bc59f256d50647f95788c'
    ;;
  *" run "*)
    cidfile=""
    while [ "$#" -gt 0 ]; do
      if [ "$1" = "--cidfile" ]; then cidfile="$2"; break; fi
      shift
    done
    [ -n "$cidfile" ]
    printf '%s' '{container_id}' > "$cidfile"
    echo '{container_id}' > "{state}"
    ;;
  *" ps -aq --no-trunc --filter id={container_id} "*)
    cat "{state}"
    ;;
  *" rm -f {container_id} "*)
    : > "{state}"
    ;;
  *)
    echo "unexpected Docker call: $*" >&2
    exit 9
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    staged = _stage_wrapper_with_docker(tmp_path, fake_docker, pass_bin=fake_pass, gh_bin=fake_gh)

    env = _base_env(tmp_path, bin_dir)
    env.update(
        {
            "DOCKER_HOST": "tcp://attacker.invalid:2375",
            "DOCKER_CONTEXT": "attacker",
            "DOCKER_CONFIG": str(tmp_path / "attacker-config"),
            "DOCKER_CERT_PATH": str(tmp_path / "attacker-certs"),
            "DOCKER_TLS_VERIFY": "1",
        }
    )

    result = subprocess.run(
        [str(staged)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    calls = docker_calls.read_text(encoding="utf-8").splitlines()
    assert calls
    assert all(
        "--host=unix:///var/run/docker.sock --config=/nonexistent/hapax-github-mcp-docker" in call
        for call in calls
    )
    run_call = next(call for call in calls if " run " in f" {call} ")
    assert "--memory 512M" in run_call
    assert "--memory-swap 768M" in run_call
    assert "--oom-kill-disable" not in run_call
    assert "--log-driver none" in run_call
    assert "--pull=never" in run_call
    assert "--read-only" in run_call
    assert "--cap-drop ALL" in run_call
    assert "--security-opt no-new-privileges" in run_call
    assert "ghcr.io/github/github-mcp-server@sha256:30197479" in run_call
    assert "-e GITHUB_PERSONAL_ACCESS_TOKEN" in run_call
    assert "--tools=search_pull_requests,pull_request_read,merge_pull_request" in run_call
    assert "add_issue_comment,create_pull_request" in run_call
    assert run_call.endswith("|token=present")
    cleanup_calls = [call for call in calls if " run " not in f" {call} "]
    assert cleanup_calls
    assert all(call.endswith("|token=") for call in cleanup_calls)
    assert any(f" rm -f {container_id}" in call for call in calls)
    assert not any("rm -f hapax-github-mcp" in call for call in calls)
    assert state.read_text(encoding="utf-8") == ""
    assert not selector_leaks.exists() or selector_leaks.read_text(encoding="utf-8") == ""
    assert not ambient_tool_ran.exists()
    log_dir = tmp_path / "mcp-logs"
    assert not list(log_dir.glob("github-mcp.*/container.cid"))
    assert "test-token" not in os.linesep.join(calls)
    assert "test-token" not in result.stdout
    assert "test-token" not in result.stderr


def test_github_mcp_retains_cid_scratch_when_exact_cleanup_fails(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.txt"
    state = tmp_path / "container-state"
    container_id = "b" * 64
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "{calls}"
case " $* " in
  *" image inspect "*)
    echo 'sha256:30197479d8036c7811892bc07e06f9a05c9ef3cdd79bc59f256d50647f95788c'
    ;;
  *" run "*)
    while [ "$#" -gt 0 ]; do
      if [ "$1" = "--cidfile" ]; then printf '%s' '{container_id}' > "$2"; break; fi
      shift
    done
    echo '{container_id}' > "{state}"
    ;;
  *" ps -aq --no-trunc --filter id={container_id} "*) cat "{state}" ;;
  *" rm -f {container_id} "*) echo "simulated remove failure" >&2; exit 17 ;;
  *) exit 9 ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    staged = _stage_wrapper_with_docker(tmp_path, fake_docker)
    env = _base_env(tmp_path, bin_dir)
    env["GITHUB_PERSONAL_ACCESS_TOKEN"] = "test-token"

    result = subprocess.run(
        [str(staged)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "immutable-ID cleanup failed" in result.stderr
    assert container_id in result.stderr
    log_dir = tmp_path / "mcp-logs"
    scratch = list(log_dir.glob("github-mcp.*/container.cid"))
    assert len(scratch) == 1
    assert scratch[0].read_text(encoding="utf-8") == container_id
    docker_calls = calls.read_text(encoding="utf-8").splitlines()
    assert any(f"rm -f {container_id}" in call for call in docker_calls)
    assert not any("rm -f hapax-github-mcp" in call for call in docker_calls)
    assert "test-token" not in result.stderr


def test_github_mcp_bounds_cleanup_probe_output_and_retains_identity(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    container_id = "c" * 64
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
case " $* " in
  *" image inspect "*)
    echo 'sha256:30197479d8036c7811892bc07e06f9a05c9ef3cdd79bc59f256d50647f95788c'
    ;;
  *" run "*)
    while [ "$#" -gt 0 ]; do
      if [ "$1" = "--cidfile" ]; then printf '%s' '{container_id}' > "$2"; break; fi
      shift
    done
    ;;
  *" ps -aq --no-trunc --filter id={container_id} "*)
    printf '%02000d' 0
    ;;
  *) exit 9 ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    staged = _stage_wrapper_with_docker(tmp_path, fake_docker)
    env = _base_env(tmp_path, bin_dir)
    env["GITHUB_PERSONAL_ACCESS_TOKEN"] = "test-token"

    result = subprocess.run(
        [str(staged)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
        check=False,
    )

    assert result.returncode == 2
    assert "unexpected identity" in result.stderr
    assert len(result.stderr) < 1024
    log_dir = tmp_path / "mcp-logs"
    scratch = list(log_dir.glob("github-mcp.*/container.cid"))
    assert len(scratch) == 1
    assert scratch[0].read_text(encoding="utf-8") == container_id
    assert "test-token" not in result.stderr


def test_github_mcp_refuses_substituted_local_image_before_token_release(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.txt"
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
token_state="$(env | grep -q '^GITHUB_PERSONAL_ACCESS_TOKEN=' && echo present || true)"
printf '%s|token=%s\n' "$*" "$token_state" >> "{calls}"
case " $* " in
  *" image inspect "*)
    echo 'sha256:{"f" * 64}'
    ;;
  *)
    echo 'unexpected Docker call' >&2
    exit 9
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    staged = _stage_wrapper_with_docker(tmp_path, fake_docker)
    env = _base_env(tmp_path, bin_dir)
    env["GITHUB_PERSONAL_ACCESS_TOKEN"] = "test-token"

    result = subprocess.run(
        [str(staged)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
        check=False,
    )

    assert result.returncode == 2
    assert "unexpected content ID" in result.stderr
    docker_calls = calls.read_text(encoding="utf-8").splitlines()
    assert len(docker_calls) == 1
    assert "image inspect" in docker_calls[0]
    assert docker_calls[0].endswith("|token=")
    assert not any(" run " in f" {call} " for call in docker_calls)
    assert "test-token" not in result.stderr


def test_github_mcp_refuses_mismatched_ambient_home_before_credentials(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "ambient-pass-ran"
    fake_pass = tmp_path / "pass"
    fake_pass.write_text(
        f"#!/usr/bin/env bash\nprintf ran > {marker}\nexit 0\n",
        encoding="utf-8",
    )
    fake_pass.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "hostile-home")
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    env.pop("GITHUB_PERSONAL_ACCESS_TOKEN", None)
    env.pop("CODEX_GITHUB_PERSONAL_ACCESS_TOKEN", None)

    result = subprocess.run(
        [str(WRAPPER)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
        check=False,
    )

    assert result.returncode == 2
    assert "refusing ambient HOME" in result.stderr
    assert "next action:" in result.stderr
    assert not marker.exists()
