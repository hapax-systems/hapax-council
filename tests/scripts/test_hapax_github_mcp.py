"""Tests for the GitHub MCP launcher wrapper."""

from __future__ import annotations

import os
import pwd
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
WRAPPER = REPO_ROOT / "scripts" / "hapax-github-mcp"
GITHUB_MCP_IMAGE_DIGEST = "sha256:30197479d8036c7811892bc07e06f9a05c9ef3cdd79bc59f256d50647f95788c"
GITHUB_MCP_IMAGE = f"ghcr.io/github/github-mcp-server@{GITHUB_MCP_IMAGE_DIGEST}"
GITHUB_MCP_LOCAL_IMAGE_ID = f"sha256:{'b' * 64}"


def _label_capture_case(label_dir: Path) -> str:
    return f'''--label)
          case "$2" in
            org.hapax.github-mcp.app=*) printf '%s' "${{2#*=}}" > "{label_dir / "app"}" ;;
            org.hapax.github-mcp.uid=*) printf '%s' "${{2#*=}}" > "{label_dir / "uid"}" ;;
            org.hapax.github-mcp.launch=*) printf '%s' "${{2#*=}}" > "{label_dir / "launch"}" ;;
            org.hapax.github-mcp.lease-pid=*) printf '%s' "${{2#*=}}" > "{label_dir / "pid"}" ;;
            org.hapax.github-mcp.lease-start=*) printf '%s' "${{2#*=}}" > "{label_dir / "start"}" ;;
            org.hapax.github-mcp.lease-boot=*) printf '%s' "${{2#*=}}" > "{label_dir / "boot"}" ;;
            *) exit 96 ;;
          esac
          shift 2
          ;;'''


def _valid_inspect_shell(
    container_id: str,
    container_name: Path,
    label_dir: Path,
    *,
    tmpfs_options: str = "rw,noexec,nosuid,size=16m",
    state: str = "exited",
    binds: str = "null",
    mounts: str = "[]",
    privileged: str = "false",
    cap_add: str = "null",
    network_mode: str = '"bridge"',
    pid_mode: str = '""',
    ipc_mode: str = '"private"',
    devices: str = "[]",
    device_requests: str = "null",
    port_bindings: str = "{}",
) -> str:
    return f'''printf '%s\\t' \\
      '{container_id}' "/$(cat "{container_name}")" \\
      "$(cat "{label_dir / "app"}")" "$(cat "{label_dir / "uid"}")" \\
      "$(cat "{label_dir / "launch"}")" "$(cat "{label_dir / "pid"}")" \\
      "$(cat "{label_dir / "start"}")" "$(cat "{label_dir / "boot"}")" \\
      '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}' '/server/github-mcp-server' \\
      '["stdio","--log-file","/tmp/github-mcp.log","--tools=pull_request_read"]' \\
      '536870912' '805306368' 'false' 'true' '["ALL"]' \\
      '["no-new-privileges"]' 'true' 'none' '{{"/tmp":"{tmpfs_options}"}}' \
      '{binds}' '{mounts}' '{privileged}' '{cap_add}' '{network_mode}' '{pid_mode}' \
      '{ipc_mode}' '{devices}' '{device_requests}' '{port_bindings}' '{state}'
    printf '%s\\n' '1' '''


def test_github_mcp_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(WRAPPER)],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr


def test_github_mcp_token_is_not_placed_in_process_arguments() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    launch_body = source.split("launch_local_docker() {", 1)[1].split("\n}\n\nIMAGE_RECORD=", 1)[0]

    assert "exec /usr/bin/docker" in launch_body
    assert "/usr/bin/env" not in launch_body
    assert 'GITHUB_PERSONAL_ACCESS_TOKEN="$github_token"' in launch_body


def test_github_mcp_uses_isolated_python_after_loading_the_pat() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    post_token_source = source.split('if [ -z "${GITHUB_PERSONAL_ACCESS_TOKEN:-}" ]; then', 1)[1]

    assert post_token_source.count("/usr/bin/python3 -I -S -") == 2
    assert '/usr/bin/python3 - "$lease_pid"' not in post_token_source
    assert '/usr/bin/python3 - "$LEASE_PID"' not in post_token_source


def test_github_mcp_signature_covers_host_escape_surfaces() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    signature = source.split("validate_mcp_container_signature() {", 1)[1].split(
        "\n}\n\nLAUNCH_IDENTITY_ERROR", 1
    )[0]

    for field in (
        ".HostConfig.Binds",
        ".Mounts",
        ".HostConfig.Privileged",
        ".HostConfig.CapAdd",
        ".HostConfig.NetworkMode",
        ".HostConfig.PidMode",
        ".HostConfig.IpcMode",
        ".HostConfig.Devices",
        ".HostConfig.DeviceRequests",
        ".HostConfig.PortBindings",
    ):
        assert field in signature


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
    container_name = tmp_path / "container-name"
    label_dir = tmp_path / "labels"
    label_dir.mkdir()
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
    printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}'
    ;;
  *" run "*)
    cidfile=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --cidfile) cidfile="$2"; shift 2 ;;
        --name) printf '%s' "$2" > "{container_name}"; shift 2 ;;
        {_label_capture_case(label_dir)}
        *) shift ;;
      esac
    done
    [ -n "$cidfile" ]
    printf '%s' '{container_id}' > "$cidfile"
    printf '%s' '{container_id}' > "{state}"
    ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name="*) cat "{state}" 2>/dev/null || true ;;
  *" ps -aq --no-trunc --filter id={container_id} "*)
    cat "{state}"
    ;;
  *" inspect --format "*)
    {_valid_inspect_shell(container_id, container_name, label_dir)}
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
    assert GITHUB_MCP_IMAGE in run_call
    assert "--label org.hapax.github-mcp.app=stdio-v1" in run_call
    assert f"--label org.hapax.github-mcp.uid={os.geteuid()}" in run_call
    assert "--label org.hapax.github-mcp.launch=" in run_call
    assert "--label org.hapax.github-mcp.lease-pid=" in run_call
    assert "--label org.hapax.github-mcp.lease-start=" in run_call
    assert "--label org.hapax.github-mcp.lease-boot=" in run_call
    assert "--name hapax-github-mcp-" in run_call
    assert "-e GITHUB_PERSONAL_ACCESS_TOKEN" in run_call
    assert "--tools=search_pull_requests,pull_request_read,merge_pull_request" in run_call
    assert "add_issue_comment,create_pull_request" in run_call
    assert run_call.endswith("|token=present")
    cleanup_calls = [call for call in calls if " run " not in f" {call} "]
    assert cleanup_calls
    assert all(call.endswith("|token=") for call in cleanup_calls)
    assert any(f" rm -f {container_id}" in call for call in calls)
    assert not any("rm -f hapax-github-mcp" in call for call in calls)
    assert any("--filter name=^/hapax-github-mcp-" in call for call in calls)
    assert state.read_text(encoding="utf-8") == ""
    assert not selector_leaks.exists() or selector_leaks.read_text(encoding="utf-8") == ""
    assert not ambient_tool_ran.exists()
    log_dir = tmp_path / "mcp-logs"
    assert not list(log_dir.glob("github-mcp.*/container.cid"))
    assert "test-token" not in os.linesep.join(calls)
    assert "test-token" not in result.stdout
    assert "test-token" not in result.stderr


def test_github_mcp_reclaims_valid_dead_lease_before_next_launch(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.txt"
    state = tmp_path / "container-state"
    stale_id = "9" * 64
    current_id = "a" * 64
    state.write_text(stale_id, encoding="utf-8")
    stale_labels = tmp_path / "stale-labels"
    current_labels = tmp_path / "current-labels"
    stale_labels.mkdir()
    current_labels.mkdir()
    stale_launch = f"{os.geteuid()}-DEADLEASE1"
    stale_name = tmp_path / "stale-name"
    current_name = tmp_path / "current-name"
    stale_name.write_text(f"hapax-github-mcp-{stale_launch}", encoding="utf-8")
    stale_values = {
        "app": "stdio-v1",
        "uid": str(os.geteuid()),
        "launch": stale_launch,
        "pid": "99999999",
        "start": "1",
        "boot": Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip(),
    }
    for name, value in stale_values.items():
        (stale_labels / name).write_text(value, encoding="ascii")

    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
token_state="$(env | grep -q '^GITHUB_PERSONAL_ACCESS_TOKEN=' && echo present || true)"
printf '%s|token=%s\n' "$*" "$token_state" >> "{calls}"
case " $* " in
  *" image inspect "*)
    printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}'
    ;;
  *" run "*)
    cidfile=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --cidfile) cidfile="$2"; shift 2 ;;
        --name) printf '%s' "$2" > "{current_name}"; shift 2 ;;
        {_label_capture_case(current_labels)}
        *) shift ;;
      esac
    done
    printf '%s' '{current_id}' > "$cidfile"
    printf '%s' '{current_id}' > "{state}"
    ;;
  *" ps -aq --no-trunc --filter "*) cat "{state}" ;;
  *" inspect --format "*"{stale_id} "*)
    {_valid_inspect_shell(stale_id, stale_name, stale_labels, tmpfs_options="size=16m,nosuid,rw,noexec")}
    ;;
  *" inspect --format "*"{current_id} "*)
    {_valid_inspect_shell(current_id, current_name, current_labels)}
    ;;
  *" rm -f {stale_id} "*) : > "{state}" ;;
  *" rm -f {current_id} "*) : > "{state}" ;;
  *) echo "unexpected Docker call: $*" >&2; exit 9 ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    staged = _stage_wrapper_with_docker(tmp_path, fake_docker)
    env = _base_env(tmp_path, bin_dir)
    env["GITHUB_PERSONAL_ACCESS_TOKEN"] = "test-token"

    result = subprocess.run(
        [str(staged)], capture_output=True, text=True, env=env, timeout=5, check=False
    )

    assert result.returncode == 0, result.stderr
    docker_calls = calls.read_text(encoding="utf-8").splitlines()
    stale_remove = next(i for i, call in enumerate(docker_calls) if f"rm -f {stale_id}" in call)
    launch = next(i for i, call in enumerate(docker_calls) if " run " in f" {call} ")
    assert stale_remove < launch
    assert any(f"rm -f {current_id}" in call for call in docker_calls)
    assert not any("rm -f hapax-github-mcp-" in call for call in docker_calls)
    assert all(call.endswith("|token=") for call in docker_calls if " run " not in f" {call} ")
    assert state.read_text(encoding="utf-8") == ""


def test_github_mcp_treats_auto_removed_prior_id_as_converged(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.txt"
    prior_state = tmp_path / "prior-state"
    current_state = tmp_path / "current-state"
    current_name = tmp_path / "current-name"
    current_labels = tmp_path / "current-labels"
    current_labels.mkdir()
    launched = tmp_path / "launched"
    prior_id = "9" * 64
    current_id = "a" * 64
    prior_state.write_text(prior_id, encoding="ascii")

    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "{calls}"
case " $* " in
  *" image inspect "*) printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}' ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) cat "{prior_state}" ;;
  *" ps -aq --no-trunc --filter name=^/hapax-github-mcp- "*) cat "{prior_state}" ;;
  *" inspect --format "*" {prior_id} "*) : > "{prior_state}"; exit 1 ;;
  *" ps -aq --no-trunc --filter id={prior_id} "*) cat "{prior_state}" ;;
  *" run "*)
    cidfile=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --cidfile) cidfile="$2"; shift 2 ;;
        --name) printf '%s' "$2" > "{current_name}"; shift 2 ;;
        {_label_capture_case(current_labels)}
        *) shift ;;
      esac
    done
    printf '%s' '{current_id}' > "$cidfile"
    printf '%s' '{current_id}' > "{current_state}"
    : > "{launched}"
    ;;
  *" ps -aq --no-trunc --filter name="*) cat "{current_state}" 2>/dev/null || true ;;
  *" ps -aq --no-trunc --filter id={current_id} "*) cat "{current_state}" ;;
  *" inspect --format "*" {current_id} "*)
    {_valid_inspect_shell(current_id, current_name, current_labels)}
    ;;
  *" rm -f {current_id} "*) : > "{current_state}" ;;
  *) echo "unexpected Docker call: $*" >&2; exit 9 ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    staged = _stage_wrapper_with_docker(tmp_path, fake_docker)
    env = _base_env(tmp_path, bin_dir)
    env["GITHUB_PERSONAL_ACCESS_TOKEN"] = "test-token"

    result = subprocess.run(
        [str(staged)], capture_output=True, text=True, env=env, timeout=5, check=False
    )

    assert result.returncode == 0, result.stderr
    assert launched.exists()
    assert current_state.read_text(encoding="ascii") == ""


def test_github_mcp_retains_cid_scratch_when_exact_cleanup_fails(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.txt"
    state = tmp_path / "container-state"
    container_name = tmp_path / "container-name"
    label_dir = tmp_path / "labels"
    label_dir.mkdir()
    container_id = "b" * 64
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "{calls}"
case " $* " in
  *" image inspect "*)
    printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}'
    ;;
  *" run "*)
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --cidfile) printf '%s' '{container_id}' > "$2"; shift 2 ;;
        --name) printf '%s' "$2" > "{container_name}"; shift 2 ;;
        {_label_capture_case(label_dir)}
        *) shift ;;
      esac
    done
    printf '%s' '{container_id}' > "{state}"
    ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name="*) cat "{state}" 2>/dev/null || true ;;
  *" ps -aq --no-trunc --filter id={container_id} "*) cat "{state}" ;;
  *" inspect --format "*)
    {_valid_inspect_shell(container_id, container_name, label_dir)}
    ;;
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
    state = tmp_path / "container-state"
    container_id = "c" * 64
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
case " $* " in
  *" image inspect "*)
    printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}'
    ;;
  *" run "*)
    while [ "$#" -gt 0 ]; do
      if [ "$1" = "--cidfile" ]; then printf '%s' '{container_id}' > "$2"; fi
      shift
    done
    printf '%s' '{container_id}' > "{state}"
    ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name="*) cat "{state}" 2>/dev/null || true ;;
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
    assert "cannot prove cleanup state" in result.stderr
    assert len(result.stderr) < 2048
    log_dir = tmp_path / "mcp-logs"
    scratch = list(log_dir.glob("github-mcp.*/container.cid"))
    assert len(scratch) == 1
    assert scratch[0].read_text(encoding="utf-8") == container_id
    assert "test-token" not in result.stderr


def test_github_mcp_recovers_created_container_when_cidfile_is_absent(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.txt"
    state = tmp_path / "container-state"
    container_name = tmp_path / "container-name"
    label_dir = tmp_path / "labels"
    label_dir.mkdir()
    container_id = "d" * 64
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "{calls}"
case " $* " in
  *" image inspect "*)
    printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}'
    ;;
  *" run "*)
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --name) printf '%s' "$2" > "{container_name}"; shift 2 ;;
        {_label_capture_case(label_dir)}
        *) shift ;;
      esac
    done
    printf '%s' '{container_id}' > "{state}"
    exit 42
    ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name="*) cat "{state}" 2>/dev/null || true ;;
  *" inspect --format "*)
    {_valid_inspect_shell(container_id, container_name, label_dir)}
    ;;
  *" rm -f {container_id} "*) : > "{state}" ;;
  *" ps -aq --no-trunc --filter id={container_id} "*) cat "{state}" ;;
  *) echo "unexpected Docker call: $*" >&2; exit 9 ;;
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

    assert result.returncode == 42
    assert state.read_text(encoding="utf-8") == ""
    docker_calls = calls.read_text(encoding="utf-8").splitlines()
    assert any("--filter name=^/hapax-github-mcp-" in call for call in docker_calls)
    assert any(f"rm -f {container_id}" in call for call in docker_calls)
    assert not any("rm -f hapax-github-mcp-" in call for call in docker_calls)
    assert not list((tmp_path / "mcp-logs").glob("github-mcp.*/container.cid"))
    assert "test-token" not in result.stderr


def test_github_mcp_never_removes_unproven_exact_name_candidate(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.txt"
    state = tmp_path / "container-state"
    container_name = tmp_path / "container-name"
    label_dir = tmp_path / "labels"
    label_dir.mkdir()
    remove_marker = tmp_path / "remove-ran"
    container_id = "e" * 64
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "{calls}"
case " $* " in
  *" image inspect "*)
    printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}'
    ;;
  *" run "*)
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --name) printf '%s' "$2" > "{container_name}"; shift 2 ;;
        {_label_capture_case(label_dir)}
        *) shift ;;
      esac
    done
    printf '%s' 'wrong-launch-identity' > "{label_dir / "launch"}"
    printf '%s' '{container_id}' > "{state}"
    exit 42
    ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name="*) cat "{state}" 2>/dev/null || true ;;
  *" inspect --format "*)
    {_valid_inspect_shell(container_id, container_name, label_dir)}
    ;;
  *" rm -f "*) printf ran > "{remove_marker}" ;;
  *) echo "unexpected Docker call: $*" >&2; exit 9 ;;
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
    assert "immutable launch signature mismatch" in result.stderr
    assert state.read_text(encoding="utf-8") == container_id
    assert not remove_marker.exists()
    scratch_dirs = [path for path in (tmp_path / "mcp-logs").glob("github-mcp.*") if path.is_dir()]
    assert len(scratch_dirs) == 1
    assert "test-token" not in result.stderr


@pytest.mark.parametrize(
    ("cid_present", "name_id"),
    [(True, "c" * 64), (False, "a" * 64)],
    ids=["cid-name-disagree", "cid-absent-name-present"],
)
def test_github_mcp_disagreement_refusal_is_terminal(
    tmp_path: Path, cid_present: bool, name_id: str
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.txt"
    launched = tmp_path / "launched"
    remove_marker = tmp_path / "remove-ran"
    inspect_marker = tmp_path / "inspect-ran"
    cid = "a" * 64
    id_response = f"printf '%s\\n' '{cid}'" if cid_present else ":"
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "{calls}"
case " $* " in
  *" image inspect "*) printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}' ;;
  *" run "*)
    while [ "$#" -gt 0 ]; do
      if [ "$1" = --cidfile ]; then printf '%s' '{cid}' > "$2"; fi
      shift
    done
    : > "{launched}"
    exit 42
    ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name=^/hapax-github-mcp- "*) : ;;
  *" ps -aq --no-trunc --filter name="*)
    if [ -e "{launched}" ]; then printf '%s\n' '{name_id}'; fi
    ;;
  *" ps -aq --no-trunc --filter id={cid} "*)
    {id_response}
    ;;
  *" inspect --format "*) : > "{inspect_marker}" ;;
  *" rm -f "*) : > "{remove_marker}" ;;
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
        [str(staged)], capture_output=True, text=True, env=env, timeout=5, check=False
    )

    assert result.returncode == 2
    assert launched.exists()
    assert (
        "refusing name-based cleanup" in result.stderr
        or "refusing ambiguous cleanup" in result.stderr
    )
    assert not inspect_marker.exists()
    assert not remove_marker.exists()
    assert not any(" rm -f " in f" {call} " for call in calls.read_text().splitlines())


def test_github_mcp_cid_proof_survives_name_probe_failure(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.txt"
    state = tmp_path / "container-state"
    launched = tmp_path / "launched"
    container_name = tmp_path / "container-name"
    label_dir = tmp_path / "labels"
    label_dir.mkdir()
    cid = "a" * 64
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "{calls}"
case " $* " in
  *" image inspect "*) printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}' ;;
  *" run "*)
    cidfile=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --cidfile) cidfile="$2"; shift 2 ;;
        --name) printf '%s' "$2" > "{container_name}"; shift 2 ;;
        {_label_capture_case(label_dir)}
        *) shift ;;
      esac
    done
    printf '%s' '{cid}' > "$cidfile"
    printf '%s' '{cid}' > "{state}"
    : > "{launched}"
    exit 42
    ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name=^/hapax-github-mcp- "*) : ;;
  *" ps -aq --no-trunc --filter name="*)
    if [ -e "{launched}" ]; then exit 17; fi
    ;;
  *" ps -aq --no-trunc --filter id={cid} "*) cat "{state}" ;;
  *" inspect --format "*) {_valid_inspect_shell(cid, container_name, label_dir)} ;;
  *" rm -f {cid} "*) : > "{state}" ;;
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
        [str(staged)], capture_output=True, text=True, env=env, timeout=5, check=False
    )

    assert result.returncode == 2
    assert any(f"rm -f {cid}" in call for call in calls.read_text().splitlines())
    assert state.read_text(encoding="utf-8") == ""


def test_github_mcp_absent_cid_and_failed_name_probe_retains_failure_evidence(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launched = tmp_path / "launched"
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
case " $* " in
  *" image inspect "*) printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}' ;;
  *" run "*) : > "{launched}"; exit 42 ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name=^/hapax-github-mcp- "*) : ;;
  *" ps -aq --no-trunc --filter name="*)
    if [ -e "{launched}" ]; then exit 17; fi
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
        [str(staged)], capture_output=True, text=True, env=env, timeout=5, check=False
    )

    assert result.returncode == 2
    assert "cannot prove exact-name cleanup state" in result.stderr
    scratch_dirs = [path for path in (tmp_path / "mcp-logs").glob("github-mcp.*") if path.is_dir()]
    assert len(scratch_dirs) == 1
    assert "test-token" not in result.stderr


def test_github_mcp_ignores_sigterm_during_cleanup(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "container-state"
    launched = tmp_path / "launched"
    signal_sent = tmp_path / "signal-sent"
    container_name = tmp_path / "container-name"
    label_dir = tmp_path / "labels"
    label_dir.mkdir()
    cid = "a" * 64
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
case " $* " in
  *" image inspect "*) printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}' ;;
  *" run "*)
    cidfile=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --cidfile) cidfile="$2"; shift 2 ;;
        --name) printf '%s' "$2" > "{container_name}"; shift 2 ;;
        {_label_capture_case(label_dir)}
        *) shift ;;
      esac
    done
    printf '%s' '{cid}' > "$cidfile"
    printf '%s' '{cid}' > "{state}"
    : > "{launched}"
    exit 42
    ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name=^/hapax-github-mcp- "*) : ;;
  *" ps -aq --no-trunc --filter name="*)
    if [ -e "{launched}" ] && [ ! -e "{signal_sent}" ]; then
      : > "{signal_sent}"
      kill -TERM "$(cat "{label_dir / "pid"}")"
      sleep 0.05
    fi
    cat "{state}" 2>/dev/null || true
    ;;
  *" ps -aq --no-trunc --filter id={cid} "*) cat "{state}" ;;
  *" inspect --format "*) {_valid_inspect_shell(cid, container_name, label_dir)} ;;
  *" rm -f {cid} "*) : > "{state}" ;;
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
        [str(staged)], capture_output=True, text=True, env=env, timeout=5, check=False
    )

    assert signal_sent.exists()
    assert result.returncode == 42, result.stderr
    assert state.read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    ("forwarded_signal", "expected_returncode", "expected_marker"),
    (
        (signal.SIGINT, 130, "INT"),
        (signal.SIGTERM, 143, "TERM"),
        (signal.SIGHUP, 129, "HUP"),
    ),
)
def test_github_mcp_forwards_signal_to_active_docker_child(
    tmp_path: Path,
    forwarded_signal: signal.Signals,
    expected_returncode: int,
    expected_marker: str,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "container-state"
    launched = tmp_path / "launched"
    signal_forwarded = tmp_path / "signal-forwarded"
    child_pid = tmp_path / "child-pid"
    container_name = tmp_path / "container-name"
    label_dir = tmp_path / "labels"
    label_dir.mkdir()
    cid = "a" * 64
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
case " $* " in
  *" image inspect "*) printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}' ;;
  *" run "*)
    cidfile=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --cidfile) cidfile="$2"; shift 2 ;;
        --name) printf '%s' "$2" > "{container_name}"; shift 2 ;;
        {_label_capture_case(label_dir)}
        *) shift ;;
      esac
    done
    printf '%s' '{cid}' > "$cidfile"
    printf '%s' '{cid}' > "{state}"
    printf '%s' "$$" > "{child_pid}"
    : > "{launched}"
    trap 'printf INT > "{signal_forwarded}"; exit 130' INT
    trap 'printf TERM > "{signal_forwarded}"; exit 143' TERM
    trap 'printf HUP > "{signal_forwarded}"; exit 129' HUP
    while true; do sleep 1; done
    ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name=^/hapax-github-mcp- "*) : ;;
  *" ps -aq --no-trunc --filter name="*) cat "{state}" 2>/dev/null || true ;;
  *" ps -aq --no-trunc --filter id={cid} "*) cat "{state}" 2>/dev/null || true ;;
  *" inspect --format "*) {_valid_inspect_shell(cid, container_name, label_dir)} ;;
  *" rm -f {cid} "*) : > "{state}" ;;
  *) exit 9 ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    staged = _stage_wrapper_with_docker(tmp_path, fake_docker)
    env = _base_env(tmp_path, bin_dir)
    env["GITHUB_PERSONAL_ACCESS_TOKEN"] = "test-token"

    process = subprocess.Popen(
        [str(staged)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        deadline = time.monotonic() + 5
        while not launched.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert launched.exists(), "GitHub MCP Docker child did not reach its run loop"
        os.kill(process.pid, forwarded_signal)
        _stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
            if child_pid.exists():
                try:
                    os.kill(int(child_pid.read_text(encoding="ascii")), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    assert process.returncode == expected_returncode, stderr
    assert signal_forwarded.read_text(encoding="ascii") == expected_marker
    assert state.read_text(encoding="utf-8") == ""


def test_github_mcp_interrupt_before_cidfile_terminates_launch_child(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launched = tmp_path / "launched"
    signal_forwarded = tmp_path / "signal-forwarded"
    child_pid = tmp_path / "child-pid"
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
case " $* " in
  *" image inspect "*) printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}' ;;
  *" run "*)
    trap 'printf TERM > "{signal_forwarded}"; exit 143' TERM
    printf '%s' "$$" > "{child_pid}"
    : > "{launched}"
    while true; do sleep 1; done
    ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name=^/hapax-github-mcp- "*) : ;;
  *" ps -aq --no-trunc --filter name="*) : ;;
  *) exit 9 ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    staged = _stage_wrapper_with_docker(tmp_path, fake_docker)
    env = _base_env(tmp_path, bin_dir)
    env["GITHUB_PERSONAL_ACCESS_TOKEN"] = "test-token"

    process = subprocess.Popen(
        [str(staged)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        deadline = time.monotonic() + 5
        while not launched.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert launched.exists(), "GitHub MCP Docker child did not reach its pre-cid run loop"
        os.kill(process.pid, signal.SIGINT)
        _stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
            if child_pid.exists():
                try:
                    os.kill(int(child_pid.read_text(encoding="ascii")), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    assert process.returncode == 130, stderr
    assert signal_forwarded.read_text(encoding="ascii") == "TERM"


def test_github_mcp_preserves_stdio_for_background_docker_child(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "container-state"
    stdin_seen = tmp_path / "stdin-seen"
    container_name = tmp_path / "container-name"
    label_dir = tmp_path / "labels"
    label_dir.mkdir()
    cid = "a" * 64
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
case " $* " in
  *" image inspect "*) printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}' ;;
  *" run "*)
    cidfile=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --cidfile) cidfile="$2"; shift 2 ;;
        --name) printf '%s' "$2" > "{container_name}"; shift 2 ;;
        {_label_capture_case(label_dir)}
        *) shift ;;
      esac
    done
    printf '%s' '{cid}' > "$cidfile"
    printf '%s' '{cid}' > "{state}"
    IFS= read -r request
    printf '%s' "$request" > "{stdin_seen}"
    ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name=^/hapax-github-mcp- "*) : ;;
  *" ps -aq --no-trunc --filter name="*) cat "{state}" 2>/dev/null || true ;;
  *" ps -aq --no-trunc --filter id={cid} "*) cat "{state}" 2>/dev/null || true ;;
  *" inspect --format "*) {_valid_inspect_shell(cid, container_name, label_dir)} ;;
  *" rm -f {cid} "*) : > "{state}" ;;
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
        input="mcp-stdio-request\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert stdin_seen.read_text(encoding="ascii") == "mcp-stdio-request"
    assert state.read_text(encoding="utf-8") == ""


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
    printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' \
      'ghcr.io/github/github-mcp-server@sha256:{"f" * 64}'
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
    assert "RepoDigests do not contain the exact reviewed" in result.stderr
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
