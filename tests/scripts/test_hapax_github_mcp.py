"""Tests for the GitHub MCP launcher wrapper."""

from __future__ import annotations

import json
import os
import pwd
import shlex
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
IMAGE_LABELS = {
    "io.modelcontextprotocol.server.name": "io.github.github/github-mcp-server",
    "org.opencontainers.image.created": "2026-05-29T12:26:39.099Z",
    "org.opencontainers.image.description": "GitHub's official MCP Server",
    "org.opencontainers.image.licenses": "MIT",
    "org.opencontainers.image.revision": "b5397f6e3305531a1c534b90b2d347a70fa84da9",
    "org.opencontainers.image.source": "https://github.com/github/github-mcp-server",
    "org.opencontainers.image.title": "github-mcp-server",
    "org.opencontainers.image.url": "https://github.com/github/github-mcp-server",
    "org.opencontainers.image.version": "1.1.2",
}
LAUNCH_SUFFIX_PLACEHOLDER = "HAPAXLAUNCHSUFFIX"


def _valid_host_config(
    container_name: Path,
    *,
    overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    host_config: dict[str, object] = {
        "AutoRemove": True,
        "Binds": None,
        "BlkioDeviceReadBps": [],
        "BlkioDeviceReadIOps": [],
        "BlkioDeviceWriteBps": [],
        "BlkioDeviceWriteIOps": [],
        "BlkioWeight": 0,
        "BlkioWeightDevice": [],
        "CapAdd": None,
        "CapDrop": ["ALL"],
        "Cgroup": "",
        "CgroupParent": "",
        "CgroupnsMode": "private",
        "ConsoleSize": [0, 0],
        "ContainerIDFile": str(
            container_name.parent
            / "mcp-logs"
            / f"github-mcp.{LAUNCH_SUFFIX_PLACEHOLDER}"
            / "container.cid"
        ),
        "CpuCount": 0,
        "CpuPercent": 0,
        "CpuPeriod": 0,
        "CpuQuota": 0,
        "CpuRealtimePeriod": 0,
        "CpuRealtimeRuntime": 0,
        "CpuShares": 0,
        "CpusetCpus": "",
        "CpusetMems": "",
        "DeviceCgroupRules": None,
        "DeviceRequests": None,
        "Devices": [],
        "Dns": None,
        "DnsOptions": [],
        "DnsSearch": [],
        "ExtraHosts": None,
        "GroupAdd": None,
        "IOMaximumBandwidth": 0,
        "IOMaximumIOps": 0,
        "IpcMode": "private",
        "Isolation": "",
        "Links": None,
        "LogConfig": {"Config": {}, "Type": "none"},
        "MaskedPaths": [
            "/proc/acpi",
            "/proc/asound",
            "/proc/interrupts",
            "/proc/kcore",
            "/proc/keys",
            "/proc/latency_stats",
            "/proc/sched_debug",
            "/proc/scsi",
            "/proc/timer_list",
            "/proc/timer_stats",
            "/sys/devices/virtual/powercap",
            "/sys/firmware",
        ],
        "Memory": 536870912,
        "MemoryReservation": 0,
        "MemorySwap": 805306368,
        "MemorySwappiness": None,
        "NanoCpus": 0,
        "NetworkMode": "bridge",
        "OomKillDisable": None,
        "OomScoreAdj": 0,
        "PidMode": "",
        "PidsLimit": 128,
        "PortBindings": {},
        "Privileged": False,
        "PublishAllPorts": False,
        "ReadonlyPaths": [
            "/proc/bus",
            "/proc/fs",
            "/proc/irq",
            "/proc/sys",
            "/proc/sysrq-trigger",
        ],
        "ReadonlyRootfs": True,
        "RestartPolicy": {"MaximumRetryCount": 0, "Name": "no"},
        "Runtime": "runc",
        "SecurityOpt": ["no-new-privileges:true"],
        "ShmSize": 67108864,
        "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=16m"},
        "UTSMode": "private",
        "Ulimits": [],
        "UsernsMode": "",
        "VolumeDriver": "",
        "VolumesFrom": None,
    }
    host_config.update(overrides or {})
    return host_config


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
    attach_stdin: str = "true",
    attach_stdout: str = "true",
    attach_stderr: str = "true",
    open_stdin: str = "true",
    stdin_once: str = "true",
    tty: str = "false",
    user: str = "0",
    env_count: str = "3",
    env_path: str = "P",
    env_ssl: str = "S",
    env_token: str = "T",
    working_dir: str = "/server",
    stop_signal: str = "SIGTERM",
    network_disabled: str = "false",
    exposed_ports: str = '{"8082/tcp":{}}',
    memory_reservation: str = "0",
    oom_score_adj: str = "0",
    log_config: str = "{}",
    uts_mode: str = '"private"',
    cgroupns_mode: str = '"private"',
    userns_mode: str = '""',
    runtime: str = "runc",
    pids_limit: str = "128",
    restart_name: str = "no",
    restart_max: str = "0",
    nano_cpus: str = "0",
    cpu_shares: str = "0",
    publish_all_ports: str = "false",
    shm_size: str = "67108864",
    dns: str = "null",
    dns_options: str = "null",
    dns_search: str = "null",
    extra_hosts: str = "null",
    links: str = "null",
    group_add: str = "null",
    volumes_from: str = "null",
    network_count: str = "1",
    bridge_network: str = "B",
    host_config_overrides: dict[str, object] | None = None,
    config_overrides: dict[str, object] | None = None,
    config_omissions: tuple[str, ...] = (),
    endpoint_overrides: dict[str, object] | None = None,
    network_overrides: dict[str, object] | None = None,
) -> str:
    host_config = _valid_host_config(
        container_name,
        overrides={
            "Binds": json.loads(binds),
            "CapAdd": json.loads(cap_add),
            "CgroupnsMode": json.loads(cgroupns_mode),
            "CpuShares": int(cpu_shares),
            "DeviceRequests": json.loads(device_requests),
            "Devices": json.loads(devices),
            "Dns": json.loads(dns),
            "DnsOptions": json.loads(dns_options),
            "DnsSearch": json.loads(dns_search),
            "ExtraHosts": json.loads(extra_hosts),
            "GroupAdd": json.loads(group_add),
            "IpcMode": json.loads(ipc_mode),
            "Links": json.loads(links),
            "LogConfig": {"Config": json.loads(log_config), "Type": "none"},
            "MemoryReservation": int(memory_reservation),
            "NanoCpus": int(nano_cpus),
            "NetworkMode": json.loads(network_mode),
            "OomScoreAdj": int(oom_score_adj),
            "PidMode": json.loads(pid_mode),
            "PidsLimit": int(pids_limit),
            "PortBindings": json.loads(port_bindings),
            "Privileged": json.loads(privileged),
            "PublishAllPorts": json.loads(publish_all_ports),
            "RestartPolicy": {"MaximumRetryCount": int(restart_max), "Name": restart_name},
            "Runtime": runtime,
            "ShmSize": int(shm_size),
            "Tmpfs": {"/tmp": tmpfs_options},
            "UTSMode": json.loads(uts_mode),
            "UsernsMode": json.loads(userns_mode),
            "VolumesFrom": json.loads(volumes_from),
            **(host_config_overrides or {}),
        },
    )
    labels = {
        **IMAGE_LABELS,
        "org.hapax.github-mcp.app": "stdio-v1",
        "org.hapax.github-mcp.uid": "HAPAXLABELUID",
        "org.hapax.github-mcp.launch": "HAPAXLABELLAUNCH",
        "org.hapax.github-mcp.lease-pid": "HAPAXLABELPID",
        "org.hapax.github-mcp.lease-start": "HAPAXLABELSTART",
        "org.hapax.github-mcp.lease-boot": "HAPAXLABELBOOT",
    }
    config_probes: dict[str, object] = {
        "Healthcheck": None,
        "Shell": None,
        "OnBuild": None,
        "ArgsEscaped": False,
        "MacAddress": "",
    }
    config: dict[str, object] = {
        "Hostname": container_id[:12],
        "Domainname": "",
        "User": user,
        "AttachStdin": json.loads(attach_stdin),
        "AttachStdout": json.loads(attach_stdout),
        "AttachStderr": json.loads(attach_stderr),
        "ExposedPorts": json.loads(exposed_ports),
        "Tty": json.loads(tty),
        "OpenStdin": json.loads(open_stdin),
        "StdinOnce": json.loads(stdin_once),
        "Env": [
            "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt",
            "GITHUB_PERSONAL_ACCESS_TOKEN=test-token",
        ],
        "Cmd": json.loads(
            '["stdio","--log-file","/tmp/github-mcp.log","--tools=pull_request_read"]'
        ),
        "Image": GITHUB_MCP_IMAGE,
        "Volumes": None,
        "WorkingDir": working_dir,
        "Entrypoint": ["/server/github-mcp-server"],
        "NetworkDisabled": json.loads(network_disabled),
        "Labels": labels,
        "StopSignal": stop_signal,
        "StopTimeout": 1,
    }
    for key, value in (config_overrides or {}).items():
        if key in config_probes:
            config_probes[key] = value
        else:
            config[key] = value
    for key in config_omissions:
        config.pop(key, None)
    endpoint: dict[str, object] = {
        "IPAMConfig": None,
        "Links": None,
        "Aliases": None,
        "DriverOpts": None,
        "GwPriority": 0,
        "NetworkID": "c" * 64,
        "EndpointID": "d" * 64,
        "Gateway": "172.17.0.1",
        "IPAddress": "172.17.0.2",
        "MacAddress": "02:42:ac:11:00:02",
        "IPPrefixLen": 16,
        "IPv6Gateway": "",
        "GlobalIPv6Address": "",
        "GlobalIPv6PrefixLen": 0,
        "DNSNames": None,
    }
    endpoint.update(endpoint_overrides or {})
    networks: dict[str, object] = {"bridge": endpoint}
    networks.update(network_overrides or {})
    host_config_shell = shlex.quote(json.dumps(host_config, separators=(",", ":")))
    labels_shell = shlex.quote(json.dumps(labels, separators=(",", ":")))
    config_shell = shlex.quote(json.dumps(config, separators=(",", ":")))
    networks_shell = shlex.quote(json.dumps(networks, separators=(",", ":")))
    added_config_shell = " ".join(
        shlex.quote(json.dumps(config_probes[field], separators=(",", ":")))
        for field in ("Healthcheck", "Shell", "OnBuild", "ArgsEscaped", "MacAddress")
    )
    return f'''launch_id="$(cat "{label_dir / "launch"}")"
    launch_suffix="${{launch_id#*-}}"
    host_config={host_config_shell}
    host_config="${{host_config/{LAUNCH_SUFFIX_PLACEHOLDER}/$launch_suffix}}"
    labels_json={labels_shell}
    labels_json="${{labels_json/HAPAXLABELUID/$(cat "{label_dir / "uid"}")}}"
    labels_json="${{labels_json/HAPAXLABELLAUNCH/$launch_id}}"
    labels_json="${{labels_json/HAPAXLABELPID/$(cat "{label_dir / "pid"}")}}"
    labels_json="${{labels_json/HAPAXLABELSTART/$(cat "{label_dir / "start"}")}}"
    labels_json="${{labels_json/HAPAXLABELBOOT/$(cat "{label_dir / "boot"}")}}"
    config_json={config_shell}
    config_json="${{config_json/HAPAXLABELUID/$(cat "{label_dir / "uid"}")}}"
    config_json="${{config_json/HAPAXLABELLAUNCH/$launch_id}}"
    config_json="${{config_json/HAPAXLABELPID/$(cat "{label_dir / "pid"}")}}"
    config_json="${{config_json/HAPAXLABELSTART/$(cat "{label_dir / "start"}")}}"
    config_json="${{config_json/HAPAXLABELBOOT/$(cat "{label_dir / "boot"}")}}"
    networks_json={networks_shell}
    printf '%s\\t' \\
      '{container_id}' "/$(cat "{container_name}")" \\
      "$(cat "{label_dir / "app"}")" "$(cat "{label_dir / "uid"}")" \\
      "$(cat "{label_dir / "launch"}")" "$(cat "{label_dir / "pid"}")" \\
      "$(cat "{label_dir / "start"}")" "$(cat "{label_dir / "boot"}")" '15' \\
      '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}' '/server/github-mcp-server' \\
      '["stdio","--log-file","/tmp/github-mcp.log","--tools=pull_request_read"]' \\
      '{attach_stdin}' '{attach_stdout}' '{attach_stderr}' '{open_stdin}' '{stdin_once}' \\
      '{tty}' '{user}' '{env_count}' '{env_path}' '{env_ssl}' '{env_token}' \\
      '{working_dir}' '{stop_signal}' '{network_disabled}' '{exposed_ports}' \\
      '536870912' '805306368' '{memory_reservation}' 'false' '{oom_score_adj}' 'true' \\
      '["ALL"]' '["no-new-privileges"]' 'true' 'none' '{log_config}' \\
      '{{"/tmp":"{tmpfs_options}"}}' '{binds}' '{mounts}' '{privileged}' '{cap_add}' \\
      '{network_mode}' '{pid_mode}' '{ipc_mode}' '{uts_mode}' '{cgroupns_mode}' \\
      '{userns_mode}' '{devices}' '{device_requests}' '{port_bindings}' '{runtime}' \\
      '{pids_limit}' '{restart_name}' '{restart_max}' '{nano_cpus}' '{cpu_shares}' \\
      '{publish_all_ports}' '{shm_size}' '{dns}' '{dns_options}' '{dns_search}' \\
      '{extra_hosts}' '{links}' '{group_add}' '{volumes_from}' '{network_count}' \\
      '{bridge_network}' '{state}' '1' '"{container_id[:12]}"' '""' \\
      '["/server/github-mcp-server"]' \\
      '["stdio","--log-file","/tmp/github-mcp.log","--tools=pull_request_read"]' \\
      'null' '{{"8082/tcp":null}}' {added_config_shell} "$labels_json"
    printf '%s\\t%s\\t%s\\n' "$host_config" "$config_json" "$networks_json" '''


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

    assert post_token_source.count("/usr/bin/python3 -I -S -") == 3
    assert '/usr/bin/python3 - "$lease_pid"' not in post_token_source
    assert '/usr/bin/python3 - "$LEASE_PID"' not in post_token_source


def test_github_mcp_signature_covers_host_escape_surfaces() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    signature = source.split("validate_mcp_container_signature() {", 1)[1].split(
        "\n}\n\nLAUNCH_IDENTITY_ERROR", 1
    )[0]

    for field in (
        ".Config.AttachStdin",
        ".Config.AttachStdout",
        ".Config.AttachStderr",
        ".Config.OpenStdin",
        ".Config.StdinOnce",
        ".Config.Tty",
        ".Config.User",
        ".Config.Env",
        ".Config.WorkingDir",
        ".Config.StopSignal",
        ".Config.Hostname",
        ".Config.Domainname",
        ".Config.Entrypoint",
        ".Config.Cmd",
        ".Config.Healthcheck",
        ".Config.Shell",
        ".Config.OnBuild",
        ".Config.ArgsEscaped",
        ".Config.MacAddress",
        ".Config.Volumes",
        ".Config.ExposedPorts",
        ".NetworkSettings.Ports",
        "{{json .Config}}",
        "{{json .NetworkSettings.Networks}}",
        "{{json .HostConfig}}",
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
        ".HostConfig.Runtime",
        ".HostConfig.PidsLimit",
        ".HostConfig.OomScoreAdj",
        ".HostConfig.UTSMode",
        ".HostConfig.CgroupnsMode",
        ".HostConfig.UsernsMode",
        ".HostConfig.RestartPolicy.Name",
        ".HostConfig.RestartPolicy.MaximumRetryCount",
        ".HostConfig.MemoryReservation",
        ".HostConfig.NanoCpus",
        ".HostConfig.CpuShares",
        ".HostConfig.PublishAllPorts",
        ".HostConfig.ShmSize",
        ".HostConfig.Dns",
        ".HostConfig.ExtraHosts",
    ):
        assert field in signature

    launch = source.split("launch_local_docker run", 1)[1]
    for option in (
        "--user 0",
        "--workdir /server",
        "--stop-signal SIGTERM",
        "--runtime runc",
        "--pids-limit 128",
        "--oom-score-adj 0",
        "--uts private",
        "--cgroupns private",
        "--shm-size 64M",
    ):
        assert option in launch


def test_github_mcp_declared_inventory_bound_fits_bounded_output() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert "readonly MAX_APP_CONTAINERS=63" in source
    assert "readonly MAX_DOCKER_OUTPUT_BYTES=16384" in source


def _stage_wrapper_with_docker(
    tmp_path: Path,
    docker: Path,
    *,
    pass_bin: Path | None = None,
    gh_bin: Path | None = None,
    timeout_bin: Path | None = None,
    head_bin: Path | None = None,
    before_pid_assignment: str | None = None,
) -> Path:
    source = WRAPPER.read_text(encoding="utf-8")
    assert source.count("/usr/bin/docker") == 2
    source = source.replace("/usr/bin/docker", str(docker))
    if pass_bin is not None:
        source = source.replace("/usr/bin/pass", str(pass_bin))
    if gh_bin is not None:
        source = source.replace("/usr/bin/gh", str(gh_bin))
    if timeout_bin is not None:
        source = source.replace("/usr/bin/timeout", str(timeout_bin))
    if head_bin is not None:
        source = source.replace("/usr/bin/head", str(head_bin))
    source = source.replace(
        'LOG_DIR="$HOME/.cache/hapax/mcp-logs"',
        f'LOG_DIR="{tmp_path / "mcp-logs"}"',
    )
    if before_pid_assignment is not None:
        boundary = '  2>>"$LOG_FILE" &\nACTIVE_DOCKER_PID=$!'
        assert source.count(boundary) == 1
        source = source.replace(
            boundary,
            f'  2>>"$LOG_FILE" &\n{before_pid_assignment}\nACTIVE_DOCKER_PID=$!',
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


def test_github_mcp_unexports_pat_before_preverification_helpers(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    leaked = tmp_path / "helper-inherited-pat"

    fake_timeout = bin_dir / "timeout"
    fake_timeout.write_text(
        f"""#!/usr/bin/env bash
if [ -n "${{GITHUB_PERSONAL_ACCESS_TOKEN+x}}" ] || [ -n "${{CODEX_GITHUB_PERSONAL_ACCESS_TOKEN+x}}" ]; then
  printf leaked > "{leaked}"
fi
while [ "$#" -gt 0 ]; do
  case "$1" in
    --signal=*|--kill-after=*) shift ;;
    *s) shift; break ;;
    *) exit 97 ;;
  esac
done
exec "$@"
""",
        encoding="utf-8",
    )
    fake_timeout.chmod(0o755)

    fake_head = bin_dir / "head"
    fake_head.write_text(
        f"""#!/usr/bin/env bash
if [ -n "${{GITHUB_PERSONAL_ACCESS_TOKEN+x}}" ] || [ -n "${{CODEX_GITHUB_PERSONAL_ACCESS_TOKEN+x}}" ]; then
  printf leaked > "{leaked}"
fi
exec /usr/bin/head "$@"
""",
        encoding="utf-8",
    )
    fake_head.chmod(0o755)

    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
case " $* " in
  *" image inspect "*) printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' 'unreviewed@example.invalid' ;;
  *) exit 9 ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    staged = _stage_wrapper_with_docker(
        tmp_path,
        fake_docker,
        timeout_bin=fake_timeout,
        head_bin=fake_head,
    )
    env = _base_env(tmp_path, bin_dir)
    env["GITHUB_PERSONAL_ACCESS_TOKEN"] = "test-token"
    env["CODEX_GITHUB_PERSONAL_ACCESS_TOKEN"] = "second-test-token"

    result = subprocess.run(
        [str(staged)], capture_output=True, text=True, env=env, timeout=5, check=False
    )

    assert result.returncode == 2
    assert not leaked.exists()
    assert "test-token" not in result.stdout
    assert "test-token" not in result.stderr


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
    {_valid_inspect_shell(container_id, container_name, label_dir, config_overrides={"FutureEmptyConfig": None})}
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


@pytest.mark.parametrize(
    "corruption",
    (
        "launch-label",
        "host-config",
        "healthcheck",
        "shell",
        "on-build",
        "args-escaped",
        "config-mac-address",
        "empty-token",
        "wrong-token-key",
        "missing-config-volumes",
        "unknown-config",
        "aliases",
        "static-ipam",
        "unsafe-endpoint-mac",
        "mismatched-endpoint-mac",
        "unknown-empty-endpoint",
        "unknown-endpoint",
    ),
)
def test_github_mcp_never_removes_unproven_exact_name_candidate(
    tmp_path: Path, corruption: str
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.txt"
    state = tmp_path / "container-state"
    container_name = tmp_path / "container-name"
    label_dir = tmp_path / "labels"
    label_dir.mkdir()
    remove_marker = tmp_path / "remove-ran"
    container_id = "e" * 64
    launch_corruption = (
        f"printf '%s' 'wrong-launch-identity' > \"{label_dir / 'launch'}\""
        if corruption == "launch-label"
        else ":"
    )
    config_corruptions = {
        "healthcheck": {"Healthcheck": {"Test": ["CMD", "/bin/false"]}},
        "shell": {"Shell": ["/bin/sh", "-c"]},
        "on-build": {"OnBuild": ["RUN /bin/false"]},
        "args-escaped": {"ArgsEscaped": True},
        "config-mac-address": {"MacAddress": "02:42:ac:11:00:99"},
        "empty-token": {
            "Env": [
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt",
                "GITHUB_PERSONAL_ACCESS_TOKEN=",
            ]
        },
        "wrong-token-key": {
            "Env": [
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt",
                "GITHUB_TOKEN=test-token",
            ]
        },
        "unknown-config": {"FutureExecutableSurface": ["/bin/false"]},
    }
    endpoint_corruptions = {
        "aliases": {"Aliases": ["trusted-looking-alias"]},
        "static-ipam": {"IPAMConfig": {"IPv4Address": "172.17.0.99"}},
        "unsafe-endpoint-mac": {"MacAddress": "01:42:ac:11:00:02"},
        "mismatched-endpoint-mac": {"MacAddress": "02:42:ac:11:00:03"},
        "unknown-empty-endpoint": {"FutureEmptyEndpoint": None},
        "unknown-endpoint": {"FutureRouteSurface": {"Enabled": True}},
    }
    inspect_record = _valid_inspect_shell(
        container_id,
        container_name,
        label_dir,
        host_config_overrides={"CgroupParent": "/host"} if corruption == "host-config" else None,
        config_overrides=config_corruptions.get(corruption),
        config_omissions=("Volumes",) if corruption == "missing-config-volumes" else (),
        endpoint_overrides=endpoint_corruptions.get(corruption),
    )
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
    {launch_corruption}
    printf '%s' '{container_id}' > "{state}"
    exit 42
    ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name="*) cat "{state}" 2>/dev/null || true ;;
  *" inspect --format "*)
    {inspect_record}
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


def test_github_mcp_forwards_signal_between_async_fork_and_pid_assignment(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "container-state"
    ready = tmp_path / "child-ready"
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
    trap 'printf TERM > "{signal_forwarded}"; exit 143' TERM
    : > "{ready}"
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
    staged = _stage_wrapper_with_docker(
        tmp_path,
        fake_docker,
        before_pid_assignment=(
            f'while [ ! -e "{ready}" ]; do /usr/bin/sleep 0.01; done\nkill -TERM "$BASHPID"'
        ),
    )
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

    assert process.returncode == 143, stderr
    assert signal_forwarded.read_text(encoding="ascii") == "TERM"
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


def test_github_mcp_signal_during_final_name_probe_never_launches(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    final_probe = tmp_path / "final-probe"
    launched = tmp_path / "launched"
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
case " $* " in
  *" image inspect "*) printf '%s\n%s\n' '{GITHUB_MCP_LOCAL_IMAGE_ID}' '{GITHUB_MCP_IMAGE}' ;;
  *" run "*) : > "{launched}" ;;
  *" ps -aq --no-trunc --filter label=org.hapax.github-mcp.app=stdio-v1 "*) : ;;
  *" ps -aq --no-trunc --filter name="*)
    if [[ "$*" == *'$' ]]; then
      : > "{final_probe}"
      sleep 0.25
    fi
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

    process = subprocess.Popen(
        [str(staged)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        deadline = time.monotonic() + 5
        while not final_probe.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert final_probe.exists(), "GitHub MCP wrapper did not enter its final name probe"
        os.kill(process.pid, signal.SIGTERM)
        _stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert process.returncode == 143, stderr
    assert not launched.exists()


@pytest.mark.parametrize("signal_name", ("INT", "TERM", "HUP"))
def test_github_mcp_refuses_inherited_ignored_signal_dispositions(
    tmp_path: Path, signal_name: str
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_ran = tmp_path / "docker-ran"
    fake_docker = bin_dir / "docker-client"
    fake_docker.write_text(
        f'#!/usr/bin/env bash\nprintf ran > "{docker_ran}"\nexit 9\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    staged = _stage_wrapper_with_docker(tmp_path, fake_docker)
    env = _base_env(tmp_path, bin_dir)
    env["GITHUB_PERSONAL_ACCESS_TOKEN"] = "test-token"

    result = subprocess.run(
        [
            "/usr/bin/bash",
            "-c",
            f"trap '' {signal_name}; exec \"$1\"",
            "ignored-signal-parent",
            str(staged),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
        check=False,
    )

    assert result.returncode == 2
    assert "ignored signal disposition" in result.stderr
    assert not docker_ran.exists()


def test_github_mcp_recovers_partial_cidfile_by_exact_launch_name(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "container-state"
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
    printf '%s' '{cid[:12]}' > "$cidfile"
    printf '%s' '{cid}' > "{state}"
    exit 42
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
        [str(staged)], capture_output=True, text=True, env=env, timeout=5, check=False
    )

    assert result.returncode == 42, result.stderr
    assert state.read_text(encoding="utf-8") == ""
    assert not [path for path in (tmp_path / "mcp-logs").glob("github-mcp.*") if path.is_dir()]


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
