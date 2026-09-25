"""install-units.sh regression pins.

Delta 2026-04-14-systemd-timer-enablement-gap.md identified that 14
of 51 council timers were in linked-but-not-enabled state because the
install script only enabled *newly* linked timers, not existing linked
ones. This test pins:

1. The script has a sweep that finds linked-but-not-enabled timers
   and runs ``systemctl --user enable`` on them.
2. The script aborts when run from any worktree other than primary
   alpha (to prevent the runtime bug where running from a temporary
   worktree re-links every systemd symlink to the worktree path).
3. The script uses idempotent ``enable`` in the sweep (not
   ``enable --now``) so dormant timers come up on their natural
   schedule rather than firing synchronously during install.
4. The override env var ``ALLOW_NONSTANDARD_REPO`` is present for
   intentional testing.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pwd
import signal
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SCRIPT = REPO_ROOT / "systemd" / "scripts" / "install-units.sh"
POST_MERGE_DEPLOY = REPO_ROOT / "scripts" / "hapax-post-merge-deploy"
APCUPSD_INSTALLER = REPO_ROOT / "scripts" / "install-apcupsd-power-alerts"
LOCAL_JUDGE_UNIT = REPO_ROOT / "systemd" / "units" / "hapax-local-judge.service"

F53FED723_LOCAL_JUDGE_UNIT = """[Unit]
# Local answer-verification judge — CompassVerifier-7B (GGUF Q5_K_M) served via
# llama.cpp server-cuda. Cost-offload Tier-1 (ISAP S5-CAPACITY-ROUTING-COST-OFFLOAD-TIER1).
# INSTALL TARGET: appendix (hapax-appendix), the SDLC rig. Reached cross-rig by the
# podium LiteLLM gateway as the `local-judge` route -> http://192.168.68.50:5001/v1.
# Deploy + validation: docs/runbooks/local-judge-stack.md.
Description=Hapax Local Judge — CompassVerifier-7B answer-verification (cost-offload Tier-1)
# After= only (no Requires=): docker runs as a system service, so a --user unit
# orders behind it but must not hard-Requires a cross-scope system unit. Matches
# the canonical docker user units (hapax-stack, hapax-container-cleanup).
After=docker.service

[Service]
Type=simple
# Pin to GPU1 (5060 Ti, sm_120 Blackwell) BY UUID so the GPU0 3090 grounding
# instance is never co-resided on (no-co-residency regression, AC1). Regenerate
# the UUID on the target host with: nvidia-smi --query-gpu=index,name,uuid --format=csv
Environment=JUDGE_GPU_UUID=GPU-347222d9-00af-5a94-a365-c57c09dfddcd
Environment=JUDGE_MODEL=/models/CompassVerifier-7B.Q5_K_M.gguf
ExecStartPre=-/usr/bin/docker rm -f hapax-local-judge
ExecStart=/usr/bin/docker run --rm --name hapax-local-judge \\
    --gpus device=${JUDGE_GPU_UUID} \\
    -v %h/models/compassverifier-7b:/models:ro \\
    -p 5001:5001 \\
    ghcr.io/ggml-org/llama.cpp:server-cuda \\
    -m ${JUDGE_MODEL} -a compassverifier-7b \\
    -c 65536 -np 8 -cb -ngl 99 --host 0.0.0.0 --port 5001
ExecStop=/usr/bin/docker stop hapax-local-judge
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""

LOCAL_JUDGE_ARGS = [
    "-m",
    "/models/CompassVerifier-7B.Q5_K_M.gguf",
    "-a",
    "compassverifier-7b",
    "-c",
    "65536",
    "-np",
    "8",
    "-cb",
    "-ngl",
    "99",
    "--host",
    "0.0.0.0",
    "--port",
    "5001",
]

LOCAL_JUDGE_CONFIG_ID = "sha256:71de6ba513bcdb374a8ac597d78277ac78df1f484cdf929e1be01c60a42964af"
LOCAL_JUDGE_IMAGE_DIGEST = "sha256:841b199aed2649a748875b043b32fed2e8c2d4d87e1d563556817fb7fa44b72b"
LOCAL_JUDGE_CONTENT_SOURCE = (
    "/store-fast/hapax-models/sha256/"
    "d6d6fba56c25d2d0f1b2cc8ee261b209b77729510b3d770d43ccb6e741dff0db"
)
LOCAL_JUDGE_IMAGE_CONFIG = {
    "User": "",
    "Env": [
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LLAMA_ARG_HOST=0.0.0.0",
    ],
    "WorkingDir": "/app",
    "Entrypoint": ["/app/llama-server"],
    "Labels": {"org.opencontainers.image.title": "llama.cpp"},
    "Healthcheck": {"Test": ["CMD", "curl", "-f", "http://localhost:8080/health"]},
    "StopSignal": "SIGTERM",
    "ExposedPorts": {"8080/tcp": {}},
    "Volumes": None,
    "OnBuild": None,
    "Shell": None,
}
LOCAL_JUDGE_MASKED_PATHS = [
    "/proc/acpi",
    "/proc/asound",
    "/proc/kcore",
    "/proc/keys",
    "/proc/latency_stats",
    "/proc/scsi",
    "/proc/timer_list",
    "/proc/timer_stats",
    "/sys/devices/virtual/powercap",
    "/sys/firmware",
]
LOCAL_JUDGE_READONLY_PATHS = [
    "/proc/bus",
    "/proc/fs",
    "/proc/irq",
    "/proc/sys",
    "/proc/sysrq-trigger",
]
LOCAL_JUDGE_BRIDGE_ENDPOINT = {
    "IPAMConfig": None,
    "Links": None,
    "Aliases": None,
    "MacAddress": "02:42:ac:11:00:02",
    "DriverOpts": None,
    "GwPriority": 0,
    "NetworkID": "b" * 64,
    "EndpointID": "c" * 64,
    "Gateway": "172.17.0.1",
    "IPAddress": "172.17.0.2",
    "IPPrefixLen": 16,
    "IPv6Gateway": "",
    "GlobalIPv6Address": "",
    "GlobalIPv6PrefixLen": 0,
    "DNSNames": None,
}


def _json_record(*values: object) -> str:
    return "\t".join(json.dumps(value, separators=(",", ":")) for value in values)


def _historical_local_judge_image_record(
    *,
    image_id: str = LOCAL_JUDGE_CONFIG_ID,
    os_name: str = "linux",
    architecture: str = "amd64",
    config_overrides: dict[str, object] | None = None,
) -> str:
    config = json.loads(json.dumps(LOCAL_JUDGE_IMAGE_CONFIG))
    config.update(config_overrides or {})
    return _json_record(image_id, os_name, architecture, config)


def _historical_local_judge_inspect_record(
    container_id: str,
    home: Path,
    *,
    profile: str = "mutable-uncapped-home",
    config_overrides: dict[str, object] | None = None,
    host_overrides: dict[str, object] | None = None,
    network_overrides: dict[str, object] | None = None,
    top_overrides: dict[str, object] | None = None,
) -> str:
    profiles = {
        "mutable-uncapped-home": (
            "ghcr.io/ggml-org/llama.cpp:server-cuda",
            str(home / "models/compassverifier-7b"),
            0,
            0,
        ),
        "mutable-capped-home": (
            "ghcr.io/ggml-org/llama.cpp:server-cuda",
            str(home / "models/compassverifier-7b"),
            4 * 1024**3,
            6 * 1024**3,
        ),
        "pinned-capped-content": (
            f"ghcr.io/ggml-org/llama.cpp@{LOCAL_JUDGE_IMAGE_DIGEST}",
            LOCAL_JUDGE_CONTENT_SOURCE,
            4 * 1024**3,
            6 * 1024**3,
        ),
    }
    config_image, source, memory, memory_swap = profiles[profile]
    image_config = json.loads(json.dumps(LOCAL_JUDGE_IMAGE_CONFIG))
    exposed_ports = json.loads(json.dumps(image_config["ExposedPorts"]))
    exposed_ports["5001/tcp"] = {}
    config = {
        **image_config,
        "Hostname": container_id[:12],
        "Domainname": "",
        "AttachStdin": False,
        "AttachStdout": True,
        "AttachStderr": True,
        "OpenStdin": False,
        "StdinOnce": False,
        "Tty": False,
        "NetworkDisabled": False,
        "ExposedPorts": exposed_ports,
        "Image": config_image,
        "Cmd": LOCAL_JUDGE_ARGS,
        "MacAddress": "",
        "StopTimeout": None,
        "ArgsEscaped": False,
    }
    config.update(config_overrides or {})
    host = {
        "Binds": [f"{source}:/models:ro"],
        "Privileged": False,
        "CapAdd": None,
        "CapDrop": None,
        "SecurityOpt": None,
        "ReadonlyRootfs": False,
        "NetworkMode": "bridge",
        "PidMode": "",
        "IpcMode": "private",
        "UTSMode": "private",
        "CgroupnsMode": "private",
        "UsernsMode": "",
        "Devices": [],
        "DeviceRequests": [
            {
                "Capabilities": [["gpu"]],
                "Count": 0,
                "DeviceIDs": ["GPU-347222d9-00af-5a94-a365-c57c09dfddcd"],
                "Driver": "",
                "Options": {},
            }
        ],
        "PortBindings": {"5001/tcp": [{"HostIp": "", "HostPort": "5001"}]},
        "PublishAllPorts": False,
        "AutoRemove": True,
        "Memory": memory,
        "MemorySwap": memory_swap,
        "MemoryReservation": 0,
        "OomKillDisable": None,
        "OomScoreAdj": 0,
        "Runtime": "runc",
        "PidsLimit": None,
        "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
        "NanoCpus": 0,
        "CpuShares": 0,
        "CpusetCpus": "",
        "CpusetMems": "",
        "ShmSize": 64 * 1024**2,
        "LogConfig": {"Type": "json-file", "Config": {}},
        "Tmpfs": None,
        "Dns": [],
        "DnsOptions": [],
        "DnsSearch": [],
        "ExtraHosts": None,
        "Links": None,
        "GroupAdd": None,
        "VolumesFrom": None,
        "Init": None,
        "MaskedPaths": LOCAL_JUDGE_MASKED_PATHS,
        "ReadonlyPaths": LOCAL_JUDGE_READONLY_PATHS,
        "Sysctls": None,
        "StorageOpt": None,
        "Mounts": [],
        "ConsoleSize": [0, 0],
        "CpuPeriod": 0,
    }
    host.update(host_overrides or {})
    mount = {
        "Destination": "/models",
        "Mode": "ro",
        "Propagation": "rprivate",
        "RW": False,
        "Source": source,
        "Type": "bind",
    }
    bridge_endpoint = json.loads(json.dumps(LOCAL_JUDGE_BRIDGE_ENDPOINT))
    bridge_endpoint.update(network_overrides or {})
    top = {
        "id": container_id,
        "name": "/hapax-local-judge",
        "image": LOCAL_JUDGE_CONFIG_ID,
        "platform": "linux",
        "path": "/app/llama-server",
        "args": LOCAL_JUDGE_ARGS,
        "config": config,
        "host": host,
        "mounts": [mount],
        "networks": {"bridge": bridge_endpoint},
        "state": {"Status": "running"},
    }
    top.update(top_overrides or {})
    return _json_record(
        top["id"],
        top["name"],
        top["image"],
        top["platform"],
        top["path"],
        top["args"],
        top["config"],
        top["host"],
        top["mounts"],
        top["networks"],
        top["state"],
    )


def _empty_retirement_docker(tmp_path: Path) -> Path:
    docker = tmp_path / "empty-retirement-docker"
    docker.write_text(
        """#!/usr/bin/env bash
case "$*" in
  *" ps -aq --no-trunc --filter name=^/hapax-local-judge$"*) exit 0 ;;
  *) echo "unexpected Docker call: $*" >&2; exit 97 ;;
esac
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return docker


def _retired_manager_systemctl(tmp_path: Path) -> Path:
    systemctl = tmp_path / "retired-manager-systemctl"
    systemctl.write_text(
        """#!/usr/bin/env bash
case "$*" in
  *" show hapax-local-judge.service "*)
    printf 'LoadState=masked\nUnitFileState=masked\nActiveState=inactive\nSubState=dead\nMainPID=0\nControlPID=0\n'
    ;;
  *) exit 0 ;;
esac
""",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    return systemctl


@pytest.fixture(autouse=True)
def _isolate_root_required_mutation_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_ROOT_REQUIRED_ISOLATED_TEST_ROOT", str(tmp_path))


def _basic_installer_env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for command in ("systemctl", "uv"):
        executable = bin_dir / command
        executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    env = {
        **os.environ,
        "ALLOW_NONSTANDARD_REPO": "1",
        "HOME": str(tmp_path / "home"),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HAPAX_INSTALL_UNITS_RETIRE_DOCKER": str(_empty_retirement_docker(tmp_path)),
        "HAPAX_INSTALL_UNITS_RETIRE_SYSTEMCTL": str(_retired_manager_systemctl(tmp_path)),
        "SKIP_TIMER_ENABLE": "1",
    }
    for name in (
        "HAPAX_ROOT_REQUIRED_LOCK_FD",
        "HAPAX_ROOT_REQUIRED_LOCK_FILE",
        "HAPAX_ROOT_REQUIRED_LOCK_MODE",
        "HAPAX_ROOT_REQUIRED_STATE_ROOT",
    ):
        env.pop(name, None)
    return env


def _wait_for_flock_block(process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    while process.poll() is None and time.monotonic() < deadline:
        descendants = {process.pid}
        changed = True
        while changed:
            changed = False
            for status_path in Path("/proc").glob("[0-9]*/status"):
                try:
                    fields = dict(
                        line.split(":", 1) for line in status_path.read_text().splitlines()
                    )
                    pid = int(status_path.parent.name)
                    ppid = int(fields["PPid"].strip())
                except (OSError, KeyError, ValueError):
                    continue
                if ppid in descendants and pid not in descendants:
                    descendants.add(pid)
                    changed = True
        for pid in descendants:
            try:
                waiting = (Path("/proc") / str(pid) / "wchan").read_text().strip()
            except OSError:
                continue
            if waiting == "locks_lock_inode_wait":
                return
        time.sleep(0.01)
    raise AssertionError("child did not reach the deterministic flock wait")


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=5)


class TestInstallUnitsScriptExists:
    def test_script_present(self) -> None:
        assert INSTALL_SCRIPT.is_file(), f"install-units.sh missing at {INSTALL_SCRIPT}"

    def test_script_is_bash(self) -> None:
        first_line = INSTALL_SCRIPT.read_text(encoding="utf-8").splitlines()[0]
        assert "bash" in first_line


class TestPrimaryWorktreeGuard:
    """Guard against the ``install-units.sh from worktree`` footgun.

    Running install-units.sh from a non-primary worktree re-links every
    systemd user unit to that worktree's path. When the worktree is
    later removed, every symlink becomes dangling and services fail to
    start. The guard blocks this by default; ``ALLOW_NONSTANDARD_REPO=1``
    is the escape hatch for intentional testing.
    """

    def test_script_checks_expected_primary(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "EXPECTED_PRIMARY" in body
        assert '${HOME}/projects/hapax-council"' in body, (
            "expected primary worktree path must be the canonical alpha path"
        )

    def test_script_aborts_on_nonstandard_repo(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert 'if [ "$PROJECT_DIR" != "$EXPECTED_PRIMARY" ]' in body
        assert "exit 1" in body

    def test_script_has_override_env_var(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "ALLOW_NONSTANDARD_REPO" in body, (
            "must expose an override env var for intentional non-primary runs"
        )


class TestSharedInstallLock:
    def test_canonical_lock_is_acquired_before_user_unit_mutation(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert (
            'ROOT_REQUIRED_LOCK_FILE="$NSS_HOME/.local/state/hapax/root-required/.lock"'
        ) in body
        assert "pwd.getpwuid(os.geteuid()).pw_dir" in body
        assert 'env["HAPAX_ROOT_REQUIRED_LOCK_FILE"] = lock_path' not in body
        assert '\nreexec_with_safe_root_required_lock\n\nmkdir -p "$DEST_DIR"' in body
        assert "O_CLOEXEC | os.O_CREAT | os.O_NOFOLLOW | os.O_RDWR" in body

    def test_production_refuses_spoofed_home_before_user_mutation(self, tmp_path: Path) -> None:
        env = _basic_installer_env(tmp_path)
        env.pop("HAPAX_ROOT_REQUIRED_ISOLATED_TEST_ROOT")
        spoofed_home = tmp_path / "spoofed-home"
        env["HOME"] = str(spoofed_home)

        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

        assert result.returncode != 0
        assert "HOME must exactly match canonical NSS home" in result.stderr
        assert not (spoofed_home / ".config/systemd/user").exists()

    @pytest.mark.parametrize(
        "selector", ("HAPAX_ROOT_REQUIRED_STATE_ROOT", "HAPAX_ROOT_REQUIRED_LOCK_FILE")
    )
    def test_production_refuses_state_selector_presence_before_mutation(
        self, tmp_path: Path, selector: str
    ) -> None:
        env = _basic_installer_env(tmp_path)
        env.pop("HAPAX_ROOT_REQUIRED_ISOLATED_TEST_ROOT")
        env["HOME"] = pwd.getpwuid(os.geteuid()).pw_dir
        unsafe_selector = tmp_path / "selector-directory"
        unsafe_selector.mkdir()
        env[selector] = str(unsafe_selector)

        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

        assert result.returncode != 0
        assert f"production refuses {selector}" in result.stderr

    @pytest.mark.parametrize("escape_kind", ("home", "lock"))
    def test_isolated_mode_refuses_paths_outside_test_root(
        self, tmp_path: Path, escape_kind: str
    ) -> None:
        isolated_root = tmp_path / "isolated"
        isolated_root.mkdir(mode=0o700)
        env = _basic_installer_env(tmp_path)
        env["HAPAX_ROOT_REQUIRED_ISOLATED_TEST_ROOT"] = str(isolated_root)
        env["HOME"] = str(isolated_root / "home")
        if escape_kind == "home":
            escaped_path = tmp_path / "escaped-home"
            env["HOME"] = str(escaped_path)
        else:
            escaped_path = tmp_path / "escaped.lock"
            env["HAPAX_ROOT_REQUIRED_LOCK_FILE"] = str(escaped_path)

        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

        assert result.returncode != 0
        assert f"isolated test {escape_kind} escapes" in result.stderr
        assert not (Path(env["HOME"]) / ".config/systemd/user").exists()

    def test_default_lock_is_created_private(self, tmp_path: Path) -> None:
        env = _basic_installer_env(tmp_path)

        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
        lock = Path(env["HOME"]) / ".local/state/hapax/root-required/.lock"
        assert lock.is_file() and not lock.is_symlink()
        assert lock.stat().st_mode & 0o777 == 0o600
        assert lock.stat().st_nlink == 1

    @pytest.mark.parametrize("unsafe_kind", ("symlink", "hardlink", "writable", "directory"))
    def test_unsafe_lock_is_refused_before_user_mutation(
        self, tmp_path: Path, unsafe_kind: str
    ) -> None:
        env = _basic_installer_env(tmp_path)
        lock = tmp_path / "shared.lock"
        if unsafe_kind == "symlink":
            target = tmp_path / "lock-target"
            target.write_text("", encoding="utf-8")
            target.chmod(0o600)
            lock.symlink_to(target)
        elif unsafe_kind == "hardlink":
            target = tmp_path / "lock-target"
            target.write_text("", encoding="utf-8")
            target.chmod(0o600)
            os.link(target, lock)
        elif unsafe_kind == "writable":
            lock.write_text("", encoding="utf-8")
            lock.chmod(0o666)
        else:
            lock.mkdir()
        env["HAPAX_ROOT_REQUIRED_LOCK_FILE"] = str(lock)

        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

        assert result.returncode != 0
        assert "refused unsafe shared install lock" in result.stderr
        assert not (Path(env["HOME"]) / ".config/systemd/user").exists()

    def test_inherited_descriptor_must_match_lock_path(self, tmp_path: Path) -> None:
        env = _basic_installer_env(tmp_path)
        lock = tmp_path / "shared.lock"
        other = tmp_path / "other.lock"
        lock.write_text("", encoding="utf-8")
        other.write_text("", encoding="utf-8")
        lock.chmod(0o600)
        other.chmod(0o600)
        fd = os.open(other, os.O_RDWR)
        try:
            env["HAPAX_ROOT_REQUIRED_LOCK_FILE"] = str(lock)
            env["HAPAX_ROOT_REQUIRED_LOCK_FD"] = str(fd)
            result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                pass_fds=(fd,),
                timeout=10,
            )
        finally:
            os.close(fd)

        assert result.returncode != 0
        assert "refused invalid inherited shared install lock" in result.stderr
        assert not (Path(env["HOME"]) / ".config/systemd/user").exists()

    def test_inherited_owner_lock_does_not_self_deadlock(self, tmp_path: Path) -> None:
        env = _basic_installer_env(tmp_path)
        lock = tmp_path / "shared.lock"
        lock.write_text("", encoding="utf-8")
        lock.chmod(0o600)
        fd = os.open(lock, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            env["HAPAX_ROOT_REQUIRED_LOCK_FILE"] = str(lock)
            env["HAPAX_ROOT_REQUIRED_LOCK_FD"] = str(fd)
            result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                pass_fds=(fd,),
                timeout=30,
            )
        finally:
            os.close(fd)

        assert result.returncode == 0, result.stderr

    def test_two_installers_serialize_on_override_lock(self, tmp_path: Path) -> None:
        env = _basic_installer_env(tmp_path)
        events = tmp_path / "lock-events"
        started = tmp_path / "first-started"
        release = tmp_path / "release-first"
        owner = tmp_path / "first-owner"
        retire_systemctl = tmp_path / "blocking-retire-systemctl"
        retire_systemctl.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                printf 'entered %s\n' "$$" >> "{events}"
                if mkdir "{owner}" 2>/dev/null; then
                    touch "{started}"
                    while [ ! -e "{release}" ]; do sleep 0.02; done
                fi
                case "$*" in
                  *" show hapax-local-judge.service "*)
                    printf 'LoadState=masked\nUnitFileState=masked\nActiveState=inactive\nSubState=dead\nMainPID=0\nControlPID=0\n'
                    ;;
                esac
                exit 0
                """
            ),
            encoding="utf-8",
        )
        retire_systemctl.chmod(0o755)
        env["HAPAX_INSTALL_UNITS_RETIRE_SYSTEMCTL"] = str(retire_systemctl)
        env["HAPAX_ROOT_REQUIRED_LOCK_FILE"] = str(tmp_path / "shared.lock")

        first = subprocess.Popen(
            ["bash", str(INSTALL_SCRIPT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        second: subprocess.Popen[str] | None = None
        try:
            deadline = time.monotonic() + 10
            while not started.exists() and first.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            assert started.exists(), "first installer did not reach the controlled mutation"
            second = subprocess.Popen(
                ["bash", str(INSTALL_SCRIPT)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            time.sleep(0.25)
            assert len(events.read_text(encoding="utf-8").splitlines()) == 1
            assert second.poll() is None
            release.touch()
            first_stdout, first_stderr = first.communicate(timeout=30)
            second_stdout, second_stderr = second.communicate(timeout=30)
        finally:
            release.touch(exist_ok=True)
            for process in (first, second):
                if process is not None and process.poll() is None:
                    process.kill()
                    process.communicate()

        assert first.returncode == 0, f"{first_stdout}\n{first_stderr}"
        assert second.returncode == 0, f"{second_stdout}\n{second_stderr}"
        assert len(events.read_text(encoding="utf-8").splitlines()) >= 4

    @pytest.mark.parametrize("inherited_descriptor", (False, True))
    def test_lock_path_replaced_while_waiting_is_refused(
        self, tmp_path: Path, inherited_descriptor: bool
    ) -> None:
        env = _basic_installer_env(tmp_path)
        lock = Path(env["HOME"]) / ".local/state/hapax/root-required/.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("", encoding="utf-8")
        lock.chmod(0o600)
        blocker_fd = os.open(lock, os.O_RDWR)
        waiter_fd = os.open(lock, os.O_RDWR)
        fcntl.flock(blocker_fd, fcntl.LOCK_EX)
        pass_fds: tuple[int, ...] = ()
        if inherited_descriptor:
            env["HAPAX_ROOT_REQUIRED_LOCK_FD"] = str(waiter_fd)
            env["HAPAX_ROOT_REQUIRED_LOCK_MODE"] = "exclusive"
            pass_fds = (waiter_fd,)
        installer = subprocess.Popen(
            ["bash", str(INSTALL_SCRIPT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            pass_fds=pass_fds,
            start_new_session=True,
        )
        try:
            _wait_for_flock_block(installer)
            replacement = lock.with_name("replacement.lock")
            replacement.write_text("", encoding="utf-8")
            replacement.chmod(0o600)
            os.replace(replacement, lock)
            fcntl.flock(blocker_fd, fcntl.LOCK_UN)
            stdout, stderr = installer.communicate(timeout=10)
        finally:
            if installer.poll() is None:
                _kill_process_group(installer)
            os.close(waiter_fd)
            os.close(blocker_fd)

        assert installer.returncode == 1, stdout
        assert "lock identity changed while acquiring" in stderr
        assert not (Path(env["HOME"]) / ".config/systemd/user").exists()

    def test_all_mutating_entry_points_wait_on_one_default_lock(self, tmp_path: Path) -> None:
        env = _basic_installer_env(tmp_path)
        home = Path(env["HOME"])
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        for name in (
            "HAPAX_POST_MERGE_TRACE_PATH",
            "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH",
            "HAPAX_POST_MERGE_SYSTEMD_PENDING_PATH",
            "HAPAX_POST_MERGE_ROOT_DEFER_DIR",
            "HAPAX_ROOT_REQUIRED_STATE_ROOT",
            "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT",
            "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT",
            "HAPAX_ROOT_REQUIRED_DESIRED_RECEIPT_ROOT",
            "HAPAX_ROOT_REQUIRED_LOCK_FILE",
        ):
            env.pop(name, None)
        env.update(
            {
                "REPO": str(repo),
                "HAPAX_APCUPSD_TARGET_UID": str(os.geteuid()),
                "HAPAX_APCUPSD_TARGET_GID": str(os.getegid()),
                "HAPAX_APCUPSD_TARGET_HOME": str(home),
                "HAPAX_APCUPSD_DEST": str(tmp_path / "apcupsd"),
                "HAPAX_APCUPSD_AUDIT_DIR": str(tmp_path / "audit"),
                "HAPAX_APCUPSD_LOGROTATE_DEST": str(tmp_path / "logrotate"),
                "HAPAX_UPOWER_CONF_DEST": str(tmp_path / "upower"),
                "HAPAX_APCUPSD_SYSTEMCTL": str(tmp_path / "bin/systemctl"),
                "HAPAX_APCUPSD_BUSCTL": str(tmp_path / "bin/systemctl"),
                "HAPAX_APCUPSD_APCACCESS": str(tmp_path / "bin/systemctl"),
                "HAPAX_APCUPSD_INSTALL_SUDO": "",
            }
        )
        lock = home / ".local/state/hapax/root-required/.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("", encoding="utf-8")
        lock.chmod(0o600)
        blocker_fd = os.open(lock, os.O_RDWR)
        fcntl.flock(blocker_fd, fcntl.LOCK_EX)
        commands = (
            [str(POST_MERGE_DEPLOY), sha],
            [str(APCUPSD_INSTALLER), "--source", str(tmp_path / "missing"), "--install"],
            ["bash", str(INSTALL_SCRIPT)],
        )
        try:
            for command in commands:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                    start_new_session=True,
                )
                try:
                    _wait_for_flock_block(process)
                    assert process.poll() is None
                finally:
                    _kill_process_group(process)
        finally:
            os.close(blocker_fd)


class TestTimerEnablementSweep:
    """Pin the delta 2026-04-14-systemd-timer-enablement-gap fix."""

    def test_script_sweeps_existing_linked_timers(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "sweep" in body.lower(), (
            "script must explicitly sweep existing linked-but-not-enabled timers"
        )
        assert "enabled_in_sweep" in body

    def test_sweep_skips_already_enabled_timers(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "timers.target.wants" in body, (
            "sweep must check .wants/ for existing enablement before calling enable"
        )

    def test_sweep_uses_plain_enable_not_enable_now(self) -> None:
        """Sweep path uses ``enable`` without ``--now`` so dormant timers
        fire on natural schedule, not synchronously at install time."""
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        # The sweep block should contain a systemctl --user enable call
        # that is NOT enable --now. We check the general shape: there
        # must be at least one enable call without --now in the sweep
        # section.
        lines = body.splitlines()
        sweep_started = False
        sweep_has_plain_enable = False
        for line in lines:
            if "for timer_file in" in line:
                sweep_started = True
            if sweep_started and "systemctl --user enable " in line:
                # Strip comments / strings — look for --now literal
                code_part = line.split("#", 1)[0]
                if "enable --now" not in code_part and '"$timer_name"' in code_part:
                    sweep_has_plain_enable = True
                    break
            if sweep_started and "done" in line and "for " not in line:
                break
        assert sweep_has_plain_enable, (
            "sweep loop must call ``systemctl --user enable <timer>`` without --now"
        )

    def test_sweep_runs_daemon_reload_after_enabling(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "daemon-reload" in body
        # Sweep block must daemon-reload after it enables anything.
        assert 'enabled_in_sweep" -gt 0' in body, (
            "sweep must conditionally run daemon-reload only when it actually enabled something"
        )

    def test_existing_newly_linked_timer_flow_still_works(self) -> None:
        """The original ``new_timers`` + ``enable --now`` path must survive."""
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "new_timers" in body
        assert "enable --now" in body, (
            "first-install path still needs enable --now so freshly linked timers start immediately"
        )

    def test_enable_only_timer_behaviorally_enables_without_starting_on_first_install(
        self, tmp_path: Path
    ) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        calls = tmp_path / "systemctl-calls.txt"
        systemctl = bin_dir / "systemctl"
        systemctl.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                printf '%s\n' "$*" >> "{calls}"
                exit 0
                """
            ),
            encoding="utf-8",
        )
        systemctl.chmod(0o755)
        uv = bin_dir / "uv"
        uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        uv.chmod(0o755)

        env = os.environ.copy()
        env["ALLOW_NONSTANDARD_REPO"] = "1"
        env["HOME"] = str(tmp_path / "home")
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["HAPAX_INSTALL_UNITS_RETIRE_DOCKER"] = str(_empty_retirement_docker(tmp_path))
        env["HAPAX_INSTALL_UNITS_RETIRE_SYSTEMCTL"] = str(_retired_manager_systemctl(tmp_path))
        env.pop("SKIP_TIMER_ENABLE", None)

        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, result.stderr
        text = calls.read_text(encoding="utf-8")
        assert "--user enable hapax-s4-arm.timer" in text
        assert "--user enable --now hapax-s4-arm.timer" not in text
        assert "enabled: hapax-s4-arm.timer (Hapax-Timer-Enable-Only; not started)" in (
            result.stdout
        )


class TestParkedUnits:
    def test_installer_disables_and_stops_marker_owned_parked_units(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        state = tmp_path / "cuepoints-state.txt"
        state.write_text("enabled active failed\n", encoding="utf-8")
        systemctl = bin_dir / "systemctl"
        systemctl.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                read -r enabled active result < "{state}"
                case "$*" in
                  "--user disable --now hapax-live-cuepoints.service")
                    enabled=disabled
                    active=inactive
                    ;;
                  "--user reset-failed hapax-live-cuepoints.service")
                    result=success
                    ;;
                  "--user enable hapax-live-cuepoints.service"|"--user enable --now hapax-live-cuepoints.service")
                    enabled=enabled
                    active=active
                    ;;
                esac
                printf '%s %s %s\n' "$enabled" "$active" "$result" > "{state}"
                exit 0
                """
            ),
            encoding="utf-8",
        )
        systemctl.chmod(0o755)
        uv = bin_dir / "uv"
        uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        uv.chmod(0o755)

        env = os.environ.copy()
        env["ALLOW_NONSTANDARD_REPO"] = "1"
        env["HOME"] = str(tmp_path / "home")
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["HAPAX_INSTALL_UNITS_RETIRE_DOCKER"] = str(_empty_retirement_docker(tmp_path))
        env["HAPAX_INSTALL_UNITS_RETIRE_SYSTEMCTL"] = str(_retired_manager_systemctl(tmp_path))
        env.pop("SKIP_TIMER_ENABLE", None)

        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, result.stderr
        assert state.read_text(encoding="utf-8").strip() == "disabled inactive success"
        assert "parked: hapax-live-cuepoints.service" in result.stdout

    def test_parked_cleanup_timer_is_never_reenabled_by_either_timer_path(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        new_timer_block = body.split('if [ "$is_new" -eq 1 ]', 1)[1].split("done", 1)[0]
        sweep_block = body.split('for timer_file in "$REPO_DIR"/*.timer', 1)[1].split("done", 1)[0]
        first_install_block = body.split('for timer in "${new_timers[@]}"', 1)[1].split("done", 1)[
            0
        ]

        assert 'parked_unit "$unit"' in new_timer_block
        assert 'parked_unit "$timer_file" && continue' in sweep_block
        assert 'parked_unit "$REPO_DIR/$timer" && continue' in first_install_block

    def test_indented_system_scope_marker_grammar_matches_other_deploy_surfaces(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")

        assert "^[[:blank:]]*[#;][[:blank:]]*Hapax-Install-Scope[[:blank:]]*:" in body


class TestServiceDropInInstall:
    """LRR Phase 3 regression pins for the ``*.service.d/`` drop-in
    handling added to install-units.sh.

    Before Phase 3, the script only walked top-level ``*.service``,
    ``*.timer``, ``*.target``, ``*.path`` files under ``systemd/units/``.
    Drop-in directories (``systemd/units/*.service.d/``) were silently
    ignored, so the existing ``audio-recorder.service.d/archive-path.conf``
    and ``contact-mic-recorder.service.d/archive-path.conf`` entries
    were never installed. Phase 3 adds ``tabbyapi.service.d/gpu-pin.conf``
    and ``hapax-daimonion.service.d/gpu-pin.conf`` and MUST install them
    for the Option α → γ partition reconciliation to take effect.

    Historical note: the hapax-daimonion drop-in was originally mis-
    placed on ``hapax-dmn.service.d/`` in PR #811 because beta's
    supplement labeled the GPU-holding service as "hapax-dmn" while
    the actual unit holding the GPU memory is ``hapax-daimonion.service``
    (``-m agents.hapax_daimonion``). ``hapax-dmn.service`` runs
    ``agents.dmn`` which is CPU-only. PR #814 corrected the target.

    These pins lock the drop-in walk in so any future refactor that
    drops it is caught in CI.
    """

    def test_script_walks_service_d_directories(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "*.service.d" in body, (
            "install-units.sh must iterate *.service.d drop-in directories"
        )

    def test_script_creates_destination_service_d_dir(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "mkdir -p " in body
        assert "dest_dropin_dir" in body, (
            "drop-in install must ensure the destination .d directory exists"
        )

    def test_script_symlinks_individual_conf_files(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "ln -sf" in body
        # Look for the specific drop-in loop
        assert '"$conf" "$dest_conf"' in body, (
            "drop-in loop must link each .conf individually, not the parent dir"
        )

    def test_generic_installer_links_all_supported_dropin_classes(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        script = project / "systemd" / "scripts" / "install-units.sh"
        units = project / "systemd" / "units"
        script.parent.mkdir(parents=True)
        units.mkdir(parents=True)
        script.write_text(INSTALL_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
        script.chmod(0o755)

        sources: dict[str, Path] = {}
        for unit_type in ("service", "timer", "slice", "scope"):
            relative = f"ordinary-{unit_type}.{unit_type}.d/positive.conf"
            source = units / relative
            source.parent.mkdir()
            source.write_text("[Unit]\nDescription=positive drop-in witness\n", encoding="utf-8")
            sources[relative] = source

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        calls = tmp_path / "systemctl-calls.txt"
        systemctl = bin_dir / "systemctl"
        systemctl.write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {calls!s}\nexit 0\n",
            encoding="utf-8",
        )
        systemctl.chmod(0o755)
        uv = bin_dir / "uv"
        uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        uv.chmod(0o755)

        env = os.environ.copy()
        env["ALLOW_NONSTANDARD_REPO"] = "1"
        env["HOME"] = str(tmp_path / "home")
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["HAPAX_INSTALL_UNITS_RETIRE_DOCKER"] = str(_empty_retirement_docker(tmp_path))
        env["HAPAX_INSTALL_UNITS_RETIRE_SYSTEMCTL"] = str(_retired_manager_systemctl(tmp_path))
        result = subprocess.run(
            ["bash", str(script)], check=False, capture_output=True, text=True, env=env
        )

        assert result.returncode == 0, result.stderr
        user_dir = Path(env["HOME"]) / ".config" / "systemd" / "user"
        for relative, source in sources.items():
            destination = user_dir / relative
            assert destination.is_symlink()
            assert destination.resolve() == source.resolve()
            assert f"dropin-linked: {relative}" in result.stdout
        assert "--user daemon-reload" in calls.read_text(encoding="utf-8")

    def test_generic_installer_behaviorally_skips_all_dedicated_p0_surfaces(
        self, tmp_path: Path
    ) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        calls = tmp_path / "systemctl-calls.txt"
        systemctl = bin_dir / "systemctl"
        systemctl.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                printf '%s\n' "$*" >> "{calls}"
                exit 0
                """
            ),
            encoding="utf-8",
        )
        systemctl.chmod(0o755)
        uv = bin_dir / "uv"
        uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        uv.chmod(0o755)

        env = os.environ.copy()
        env["ALLOW_NONSTANDARD_REPO"] = "1"
        env["HOME"] = str(tmp_path / "home")
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["HAPAX_INSTALL_UNITS_RETIRE_DOCKER"] = str(_empty_retirement_docker(tmp_path))
        env["HAPAX_INSTALL_UNITS_RETIRE_SYSTEMCTL"] = str(_retired_manager_systemctl(tmp_path))

        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, result.stderr
        p0_dropins = [
            "app.slice.d/oom-containment.conf",
            "session.slice.d/oom-containment.conf",
            "pipewire.service.d/oom-protect.conf",
            "pipewire-pulse.service.d/oom-protect.conf",
            "wireplumber.service.d/oom-protect.conf",
            "hapax-daimonion.service.d/oom-protect.conf",
            "studio-compositor.service.d/oom-protect.conf",
            "hapax-imagination.service.d/oom-protect.conf",
        ]
        user_dir = Path(env["HOME"]) / ".config" / "systemd" / "user"
        for relative in p0_dropins:
            dest = user_dir / relative
            assert not dest.exists()
            assert f"dropin-skipped-dedicated-installer: {relative}" in result.stdout
        p0_audit_units = [
            "hapax-oom-policy-audit.service",
            "hapax-oom-policy-audit.timer",
            "hapax-root-required-deploy-audit.service",
            "hapax-root-required-deploy-audit.timer",
        ]
        for unit in p0_audit_units:
            assert not (user_dir / unit).exists()
            assert f"skipped dedicated P0 OOM unit: {unit}" in result.stdout

    def test_system_install_scope_units_are_not_linked_into_user_dir(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        calls = tmp_path / "systemctl-calls.txt"
        systemctl = bin_dir / "systemctl"
        systemctl.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                printf '%s\n' "$*" >> "{calls}"
                exit 0
                """
            ),
            encoding="utf-8",
        )
        systemctl.chmod(0o755)
        uv = bin_dir / "uv"
        uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        uv.chmod(0o755)

        env = os.environ.copy()
        env["ALLOW_NONSTANDARD_REPO"] = "1"
        env["HOME"] = str(tmp_path / "home")
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["HAPAX_INSTALL_UNITS_RETIRE_DOCKER"] = str(_empty_retirement_docker(tmp_path))
        env["HAPAX_INSTALL_UNITS_RETIRE_SYSTEMCTL"] = str(_retired_manager_systemctl(tmp_path))

        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, result.stderr
        user_dir = Path(env["HOME"]) / ".config" / "systemd" / "user"
        system_units = [
            "hapax-root-failure-intake@.service",
            "hapax-oom-score-enforce.service",
            "hapax-oom-score-enforce.timer",
        ]
        for unit in system_units:
            assert not (user_dir / unit).exists()
            assert f"skipped system-scope unit: {unit}" in result.stdout

    def test_system_install_scope_removes_stale_user_unit(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "home" / ".config" / "systemd" / "user"
        user_dir.mkdir(parents=True)
        stale = user_dir / "hapax-oom-score-enforce.timer"
        stale.write_text("[Timer]\nOnUnitActiveSec=30s\n", encoding="utf-8")
        stale_dropin = user_dir / "hapax-oom-score-enforce.timer.d" / "override.conf"
        stale_dropin.parent.mkdir()
        stale_dropin.write_text("[Timer]\nOnUnitActiveSec=5s\n", encoding="utf-8")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        calls = tmp_path / "systemctl-calls.txt"
        systemctl = bin_dir / "systemctl"
        systemctl.write_text(
            f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {calls!s}\nexit 0\n",
            encoding="utf-8",
        )
        systemctl.chmod(0o755)
        uv = bin_dir / "uv"
        uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        uv.chmod(0o755)

        env = os.environ.copy()
        env["ALLOW_NONSTANDARD_REPO"] = "1"
        env["HOME"] = str(tmp_path / "home")
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["HAPAX_INSTALL_UNITS_RETIRE_DOCKER"] = str(_empty_retirement_docker(tmp_path))
        env["HAPAX_INSTALL_UNITS_RETIRE_SYSTEMCTL"] = str(_retired_manager_systemctl(tmp_path))

        result = subprocess.run(
            ["bash", str(INSTALL_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, result.stderr
        assert not stale.exists()
        assert not stale_dropin.parent.exists()
        assert (
            "removed stale user-scope system unit: hapax-oom-score-enforce.timer" in result.stdout
        )
        assert "--user disable --now hapax-oom-score-enforce.timer" in calls.read_text(
            encoding="utf-8"
        )

    def test_system_scope_base_prevents_generic_user_dropin_install(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        script = project / "systemd" / "scripts" / "install-units.sh"
        units = project / "systemd" / "units"
        script.parent.mkdir(parents=True)
        units.mkdir(parents=True)
        script.write_text(INSTALL_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
        script.chmod(0o755)
        base = units / "root-owned.service"
        base.write_text(
            "[Unit]\n; hapax-install-scope: SYSTEM\n[Service]\nExecStart=/usr/bin/true\n",
            encoding="utf-8",
        )
        dropin = units / "root-owned.service.d" / "override.conf"
        dropin.parent.mkdir()
        dropin.write_text("[Service]\nEnvironment=SHOULD_NOT_INSTALL=1\n", encoding="utf-8")

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for command in ("systemctl", "uv"):
            executable = bin_dir / command
            executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
        home = tmp_path / "home"
        stale_dropin = home / ".config/systemd/user/root-owned.service.d/override.conf"
        stale_dropin.parent.mkdir(parents=True)
        stale_dropin.write_text("stale\n", encoding="utf-8")
        env = {
            **os.environ,
            "ALLOW_NONSTANDARD_REPO": "1",
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HAPAX_INSTALL_UNITS_RETIRE_DOCKER": str(_empty_retirement_docker(tmp_path)),
            "HAPAX_INSTALL_UNITS_RETIRE_SYSTEMCTL": str(_retired_manager_systemctl(tmp_path)),
            "SKIP_TIMER_ENABLE": "1",
        }

        result = subprocess.run(
            ["bash", str(script)], check=False, capture_output=True, text=True, env=env
        )

        assert result.returncode == 0, result.stderr
        assert not stale_dropin.parent.exists()
        assert "skipped system-scope unit: root-owned.service" in result.stdout
        assert "dropin-linked: root-owned.service.d/override.conf" not in result.stdout

    def test_script_reloads_daemon_when_dropins_change(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "dropin_changed" in body
        assert '"$dropin_changed" -gt 0' in body, (
            "daemon-reload must be gated on dropin_changed so idempotent re-runs don't spam reloads"
        )


class TestPhase3DropInsPresent:
    """GPU residency regression pins for shipped service drop-ins.

    The 2026-05-23 dual-rig migration moved podium to RTX 5090 + RTX 5060 Ti:
    TabbyAPI/Command-R stays on the 5090, while daimonion STT stays on the
    5060 Ti. The drop-ins must exist in the repo and preserve that split.
    """

    TABBYAPI_DROPIN = REPO_ROOT / "systemd" / "units" / "tabbyapi.service.d" / "gpu-pin.conf"
    HAPAX_DAIMONION_DROPIN = (
        REPO_ROOT / "systemd" / "units" / "hapax-daimonion.service.d" / "gpu-pin.conf"
    )
    HAPAX_DMN_DROPIN_WRONG = (
        REPO_ROOT / "systemd" / "units" / "hapax-dmn.service.d" / "gpu-pin.conf"
    )

    def test_tabbyapi_dropin_exists(self) -> None:
        assert self.TABBYAPI_DROPIN.is_file(), (
            f"tabbyapi gpu-pin drop-in missing at {self.TABBYAPI_DROPIN} — "
            "Phase 3 partition reconciliation requires it"
        )

    def test_hapax_daimonion_dropin_exists(self) -> None:
        assert self.HAPAX_DAIMONION_DROPIN.is_file(), (
            f"hapax-daimonion gpu-pin drop-in missing at {self.HAPAX_DAIMONION_DROPIN} — "
            "Phase 3 partition reconciliation requires it"
        )

    def test_hapax_dmn_dropin_not_present(self) -> None:
        """PR #814 regression pin: the old mis-placed drop-in must not
        come back. ``hapax-dmn.service`` is CPU-only and any GPU-pin
        drop-in here is a no-op that misleads future readers."""
        assert not self.HAPAX_DMN_DROPIN_WRONG.exists(), (
            f"Stale hapax-dmn drop-in found at {self.HAPAX_DMN_DROPIN_WRONG}. "
            "hapax-dmn.service (agents.dmn) is CPU-only; the GPU-pin drop-in "
            "belongs on hapax-daimonion.service.d/ instead."
        )

    def test_tabbyapi_dropin_pins_to_podium_5090(self) -> None:
        body = self.TABBYAPI_DROPIN.read_text(encoding="utf-8")
        assert "[Service]" in body
        assert "CUDA_DEVICE_ORDER=PCI_BUS_ID" in body, (
            "tabbyapi drop-in must pin CUDA_DEVICE_ORDER=PCI_BUS_ID before any "
            "CUDA_VISIBLE_DEVICES line, or the device-index-to-card mapping "
            "inverts (see Phase 3 spec §1.1)"
        )
        assert "CUDA_VISIBLE_DEVICES=0" in body, (
            "tabbyapi drop-in must pin to podium GPU 0 (RTX 5090) after the "
            "dual-rig migration; Command-R no longer splits across the 5060 Ti"
        )

    def test_hapax_daimonion_dropin_pinned_to_podium_5060_ti(self) -> None:
        body = self.HAPAX_DAIMONION_DROPIN.read_text(encoding="utf-8")
        assert "[Service]" in body
        assert "CUDA_DEVICE_ORDER=PCI_BUS_ID" in body, (
            "hapax-daimonion drop-in must pin CUDA_DEVICE_ORDER=PCI_BUS_ID for the "
            "same reason as tabbyapi (see Phase 3 spec §1.1)"
        )
        assert "CUDA_VISIBLE_DEVICES=1" in body, (
            "hapax-daimonion drop-in must pin STT to podium GPU 1 (RTX 5060 Ti) "
            "after the 5090+5060 Ti rebalance"
        )

    def test_tabbyapi_service_timeout_180(self) -> None:
        """TimeoutStartSec is held at 180 s as Command-R startup headroom."""
        svc = REPO_ROOT / "systemd" / "units" / "tabbyapi.service"
        body = svc.read_text(encoding="utf-8")
        assert "TimeoutStartSec=180" in body, (
            "tabbyapi.service TimeoutStartSec must be 180 s as Command-R startup headroom"
        )


class TestServiceAutoEnableList:
    """24h auditor batch 2026-05-02 finding #13 regression pins.

    Five service units shipped without auto-enable (PRs #2220, #2221, #2223,
    #2235, #2252) lived dormant on the operator workstation because the
    installer only auto-enabled timer units. ``hapax-preset-bias-heartbeat.service``
    (PR #2239) was superseded by the parametric-modulation heartbeat per memory
    ``feedback_no_presets_use_parametric_modulation`` and must be disabled+masked
    on subsequent installs.

    These pins lock in the AUTO_ENABLE_SERVICES array and the
    DECOMMISSIONED_UNITS membership so a future refactor that drops either
    is caught in CI.
    """

    EXPECTED_AUTO_ENABLE = (
        "hapax-bt-firmware-watchdog.service",
        "hapax-xhci-death-watchdog.service",
        "hapax-private-broadcast-leak-guard.service",
        "hapax-broadcast-egress-loopback-producer.service",
        "hapax-parametric-modulation-heartbeat.service",
        "hapax-hls-no-cache.service",
        "hapax-live-surface-guard.service",
    )

    def test_auto_enable_array_declared(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        assert "AUTO_ENABLE_SERVICES=(" in body, (
            "install-units.sh must declare the AUTO_ENABLE_SERVICES bash array "
            "so persistent-daemon services ship enabled by default"
        )

    def test_each_audit_service_in_auto_enable(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        for svc in self.EXPECTED_AUTO_ENABLE:
            assert svc in body, (
                f"AUTO_ENABLE_SERVICES must include {svc} per 24h audit batch "
                f"2026-05-02 finding #13 (feedback_features_on_by_default)"
            )

    def test_auto_enable_loop_uses_enable_now(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        # The auto-enable loop must use ``enable --now`` (so the daemon starts
        # immediately, not just on next boot). Look for the loop body.
        lines = body.splitlines()
        loop_started = False
        loop_uses_enable_now = False
        for line in lines:
            if "AUTO_ENABLE_SERVICES" in line and "for " in line:
                loop_started = True
                continue
            if loop_started and "systemctl --user enable --now" in line:
                if "$service_name" in line:
                    loop_uses_enable_now = True
                    break
            # Stop scanning if we hit the next top-level block before finding it
            if loop_started and line.startswith("# ") and "AUTO_ENABLE" not in line:
                break
        assert loop_uses_enable_now, (
            "AUTO_ENABLE_SERVICES loop must call ``systemctl --user enable --now "
            "<service>`` so shipped services start immediately, not on next boot"
        )

    def test_auto_enable_honors_skip_env_var(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        # The auto-enable block must respect SKIP_TIMER_ENABLE (shared escape
        # hatch) so operators have a quiet-install option during incident
        # response.
        assert "${SKIP_TIMER_ENABLE:-0}" in body
        # The skip path should at minimum mention auto-enabling
        assert "skipped auto-enabling" in body, (
            "SKIP_TIMER_ENABLE branch must announce that auto-enable was skipped "
            "so the operator notices the deferred work"
        )

    def test_auto_enable_skips_missing_units(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        # Defense-in-depth: auto-enable loop must skip + WARN if a listed unit
        # isn't on disk (covers the 'renamed unit but forgot to update array'
        # case). Look for the file-existence guard inside the loop.
        assert 'if [ ! -f "$REPO_DIR/$service_name" ]' in body, (
            "auto-enable loop must guard against missing unit files with a WARN, not a hard failure"
        )

    def test_auto_enable_skips_decommissioned_units(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        # If somebody puts a unit in both lists by mistake, prefer the
        # decommissioned semantics (disabled+masked). The loop must check.
        assert 'if is_decommissioned_unit "$service_name"' in body, (
            "auto-enable loop must defer to DECOMMISSIONED_UNITS to prevent "
            "double-bookkeeping mistakes"
        )


class TestAuditedUnitsExist:
    """Sanity pins: the unit files referenced by AUTO_ENABLE_SERVICES must
    exist in the repo. Catches the case where the array lists a unit that
    has been renamed or moved without updating the installer."""

    UNITS_DIR = REPO_ROOT / "systemd" / "units"
    EXPECTED_UNITS = (
        "hapax-bt-firmware-watchdog.service",
        "hapax-xhci-death-watchdog.service",
        "hapax-private-broadcast-leak-guard.service",
        "hapax-broadcast-egress-loopback-producer.service",
        "hapax-parametric-modulation-heartbeat.service",
        "hapax-hls-no-cache.service",
        "hapax-live-surface-guard.service",
        # Decommissioned but file must still be present so the disable+mask
        # path has something to act on.
    )

    def test_each_unit_file_present(self) -> None:
        for unit in self.EXPECTED_UNITS:
            path = self.UNITS_DIR / unit
            assert path.is_file(), (
                f"Expected unit file {path} to exist — install-units.sh "
                f"AUTO_ENABLE_SERVICES / DECOMMISSIONED_UNITS references it"
            )


def _prepare_local_judge_retirement(
    tmp_path: Path,
    *,
    profile: str = "mutable-uncapped-home",
    container_id: str | None = "a" * 64,
    container_record: str | None = None,
    image_record: str | None = None,
    second_record: str | None = None,
    second_inspect_fails: bool = False,
    docker_inventory_fails: bool = False,
    rm_mode: str = "remove",
    replacement_id: str = "b" * 64,
    poll_linger: int = 0,
    host_facts: dict[str, str] | None = None,
    manager_values: tuple[str, str, str, str, str, str] = (
        "masked",
        "masked",
        "inactive",
        "dead",
        "0",
        "0",
    ),
    manager_bad_after: int | None = None,
    mask_race_after: int | None = None,
    disable_fails: bool = False,
) -> dict[str, object]:
    home = tmp_path / "home"
    unit_dir = home / ".config/systemd/user"
    wants_dir = unit_dir / "default.target.wants"
    dropin_dir = unit_dir / "hapax-local-judge.service.d"
    wants_dir.mkdir(parents=True)
    dropin_dir.mkdir()
    installed = unit_dir / "hapax-local-judge.service"
    installed.write_text(F53FED723_LOCAL_JUDGE_UNIT, encoding="utf-8")
    (wants_dir / installed.name).symlink_to(installed)
    (dropin_dir / "override.conf").write_text("[Service]\nRestart=always\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    events = tmp_path / "events"
    show_count = tmp_path / "show-count"
    show_count.write_text("0\n", encoding="utf-8")

    load_state, unit_file_state, active_state, sub_state, main_pid, control_pid = manager_values
    bad_after = manager_bad_after if manager_bad_after is not None else -1
    race_after = mask_race_after if mask_race_after is not None else -1
    disable_rc = 41 if disable_fails else 0
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            printf 'systemctl %s\n' "$*" >> "{events}"
            case "$*" in
              "--user disable hapax-local-judge.service")
                exit {disable_rc}
                ;;
              "--user daemon-reload")
                exit 0
                ;;
              "--user kill --kill-who=all --signal=SIGKILL hapax-local-judge.service")
                exit 0
                ;;
              "--user reset-failed hapax-local-judge.service")
                exit 0
                ;;
              *" show hapax-local-judge.service "*)
                count="$(cat "{show_count}")"
                count=$((count + 1))
                printf '%s\n' "$count" > "{show_count}"
                if [ {race_after} -ge 0 ] && [ "$count" -gt {race_after} ]; then
                  rm -f "{installed}"
                  ln -s /dev/null "{installed}"
                fi
                if [ {bad_after} -ge 0 ] && [ "$count" -gt {bad_after} ]; then
                  printf 'LoadState=masked\nUnitFileState=masked\nActiveState=active\nSubState=running\nMainPID=99\nControlPID=0\n'
                else
                  printf 'LoadState={load_state}\nUnitFileState={unit_file_state}\nActiveState={active_state}\nSubState={sub_state}\nMainPID={main_pid}\nControlPID={control_pid}\n'
                fi
                ;;
              *)
                exit 0
                ;;
            esac
            """
        ),
        encoding="utf-8",
    )
    systemctl.chmod(0o755)

    name_state = tmp_path / "container-name-state"
    exact_state = tmp_path / "container-exact-state"
    inspect_count = tmp_path / "inspect-count"
    linger_state = tmp_path / "linger-state"
    name_state.write_text(f"{container_id}\n" if container_id else "", encoding="utf-8")
    exact_state.write_text(f"{container_id}\n" if container_id else "", encoding="utf-8")
    inspect_count.write_text("0\n", encoding="utf-8")
    linger_state.write_text(f"{poll_linger}\n", encoding="utf-8")
    record_path = tmp_path / "container-record"
    if container_id:
        record_path.write_text(
            container_record
            or _historical_local_judge_inspect_record(container_id, home, profile=profile),
            encoding="utf-8",
        )
    second_record_path = tmp_path / "second-container-record"
    if second_record is not None:
        second_record_path.write_text(second_record, encoding="utf-8")
    image_record_path = tmp_path / "image-record"
    image_record_path.write_text(
        image_record or _historical_local_judge_image_record(),
        encoding="utf-8",
    )

    inventory_failure = 1 if docker_inventory_fails else 0
    inspect_failure = 1 if second_inspect_fails else 0
    docker = bin_dir / "docker"
    docker.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            printf 'docker %s\n' "$*" >> "{events}"
            [ "$1" = "--host=unix:///var/run/docker.sock" ] || exit 91
            [ "$2" = "--config=/nonexistent/hapax-local-judge-retirement" ] || exit 92
            shift 2
            command="$1"
            shift
            case "$command" in
              ps)
                filter="$4"
                case "$filter" in
                  "name=^/hapax-local-judge$")
                    [ {inventory_failure} -eq 0 ] || exit 55
                    cat "{name_state}"
                    ;;
                  id=*)
                    target="${{filter#id=}}"
                    if grep -qx "$target" "{exact_state}"; then
                      linger="$(cat "{linger_state}")"
                      if [ "$linger" -gt 0 ]; then
                        printf '%s\n' "$target"
                        printf '%s\n' "$((linger - 1))" > "{linger_state}"
                      elif [ "$linger" -eq 0 ] && [ "{rm_mode}" = "remove" ] && [ {poll_linger} -gt 0 ]; then
                        : > "{exact_state}"
                      else
                        printf '%s\n' "$target"
                      fi
                    fi
                    ;;
                  *)
                    exit 93
                    ;;
                esac
                ;;
              image)
                [ "$1" = inspect ] || exit 94
                [ "$4" = "{LOCAL_JUDGE_CONFIG_ID}" ] || exit 95
                cat "{image_record_path}"
                ;;
              container)
                [ "$1" = inspect ] || exit 96
                target="$4"
                [ "$target" = "{container_id or ""}" ] || exit 97
                count="$(cat "{inspect_count}")"
                count=$((count + 1))
                printf '%s\n' "$count" > "{inspect_count}"
                if [ {inspect_failure} -eq 1 ] && [ "$count" -eq 2 ]; then
                  exit 44
                fi
                if [ "$count" -ge 2 ] && [ -f "{second_record_path}" ]; then
                  cat "{second_record_path}"
                else
                  cat "{record_path}"
                fi
                ;;
              rm)
                [ "$1" = -f ] || exit 98
                target="$2"
                [ "$target" = "{container_id or ""}" ] || exit 99
                case "{rm_mode}" in
                  remove)
                    : > "{name_state}"
                    if [ {poll_linger} -eq 0 ]; then
                      : > "{exact_state}"
                    fi
                    ;;
                  replacement)
                    : > "{exact_state}"
                    printf '%s\n' "{replacement_id}" > "{name_state}"
                    ;;
                  stuck)
                    ;;
                  fail)
                    exit 55
                    ;;
                  *)
                    exit 100
                    ;;
                esac
                ;;
              *)
                exit 101
                ;;
            esac
            """
        ),
        encoding="utf-8",
    )
    docker.chmod(0o755)

    uv = bin_dir / "uv"
    uv.write_text(
        f'#!/usr/bin/env bash\nprintf \'uv %s\\n\' "$*" >> "{events}"\n',
        encoding="utf-8",
    )
    uv.chmod(0o755)

    facts = {
        "hostname": "hapax-appendix",
        "passwd_home": str(home),
        "os": "Linux",
        "arch": "x86_64",
    }
    facts.update(host_facts or {})
    env = {
        **os.environ,
        "ALLOW_NONSTANDARD_REPO": "1",
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HAPAX_INSTALL_UNITS_RETIRE_SYSTEMCTL": str(systemctl),
        "HAPAX_INSTALL_UNITS_RETIRE_DOCKER": str(docker),
        "HAPAX_INSTALL_UNITS_RETIRE_TEST_HOSTNAME": facts["hostname"],
        "HAPAX_INSTALL_UNITS_RETIRE_TEST_PASSWD_HOME": facts["passwd_home"],
        "HAPAX_INSTALL_UNITS_RETIRE_TEST_OS": facts["os"],
        "HAPAX_INSTALL_UNITS_RETIRE_TEST_ARCH": facts["arch"],
        "SKIP_TIMER_ENABLE": "1",
    }
    return {
        "home": home,
        "installed": installed,
        "wants": wants_dir / installed.name,
        "dropin": dropin_dir,
        "events": events,
        "name_state": name_state,
        "exact_state": exact_state,
        "inspect_count": inspect_count,
        "show_count": show_count,
        "env": env,
        "container_id": container_id,
        "replacement_id": replacement_id,
    }


def _run_local_judge_retirement(harness: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=harness["env"],
        timeout=30,
    )


def _event_lines(harness: dict[str, object]) -> list[str]:
    return Path(harness["events"]).read_text(encoding="utf-8").splitlines()


class TestLocalJudgeRetirement:
    def test_decommissioned_source_unit_is_absent(self) -> None:
        assert not LOCAL_JUDGE_UNIT.exists()

    def test_historical_source_and_transaction_order_are_pinned(self) -> None:
        body = INSTALL_SCRIPT.read_text(encoding="utf-8")
        historical_sha256 = hashlib.sha256(F53FED723_LOCAL_JUDGE_UNIT.encode("utf-8")).hexdigest()

        assert historical_sha256 == (
            "1329672a612e29035fab32e41e16b9b19b626fe0f0d6fadc1456302d56fb6d5c"
        )
        assert LOCAL_JUDGE_CONFIG_ID in body
        transaction = body.split("retire_historical_local_judge() {", 1)[1].split(
            "remove_decommissioned_unit() {", 1
        )[0]
        assert transaction.index("wait_for_local_judge_manager_quiescence") < transaction.index(
            "query_local_judge_container_id"
        )
        assert 'rm -f "$before_id"' in body
        assert "rm -f hapax-local-judge" not in body
        assert "-p LoadState -p UnitFileState -p ActiveState" in body
        assert "-p SubState -p MainPID -p ControlPID" in body
        assert "masked\\tmasked\\tinactive\\tdead\\t0\\t0" in body
        assert '3<<<"$output"' in body
        assert '3<<<"$LOCAL_JUDGE_IMAGE_RECORD" 4<<<"$output"' in body
        assert '"$LOCAL_JUDGE_CONFIG_ID" "$output"' not in body
        assert '"$LOCAL_JUDGE_IMAGE_RECORD" "$output"' not in body

    @pytest.mark.parametrize(
        "profile",
        (
            "mutable-uncapped-home",
            "mutable-capped-home",
            "pinned-capped-content",
        ),
    )
    def test_complete_historical_profiles_retire_by_exact_id(
        self, tmp_path: Path, profile: str
    ) -> None:
        harness = _prepare_local_judge_retirement(tmp_path, profile=profile)

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 0, result.stderr
        installed = Path(harness["installed"])
        assert installed.is_symlink() and os.readlink(installed) == "/dev/null"
        assert not Path(harness["wants"]).exists()
        assert not Path(harness["dropin"]).exists()
        assert Path(harness["name_state"]).read_text(encoding="utf-8") == ""
        lines = _event_lines(harness)
        first_docker = next(i for i, line in enumerate(lines) if line.startswith("docker "))
        quiesced = next(
            i for i, line in enumerate(lines) if "show hapax-local-judge.service" in line
        )
        assert quiesced < first_docker
        container_id = str(harness["container_id"])
        inspect_indexes = [
            i
            for i, line in enumerate(lines)
            if " container inspect --format " in line and line.endswith(container_id)
        ]
        rm_index = next(i for i, line in enumerate(lines) if f" rm -f {container_id}" in line)
        assert len(inspect_indexes) == 2
        assert inspect_indexes[-1] < rm_index
        assert not any(" rm -f hapax-local-judge" in line for line in lines)
        assert all(
            "--host=unix:///var/run/docker.sock" in line
            and "--config=/nonexistent/hapax-local-judge-retirement" in line
            for line in lines
            if line.startswith("docker ")
        )
        assert f"profile={profile}" in result.stdout

    @pytest.mark.parametrize(
        ("area", "key", "value"),
        (
            ("top", "name", "/foreign"),
            ("top", "image", "sha256:" + "f" * 64),
            ("top", "path", "/bin/sh"),
            ("top", "args", ["-c", "id"]),
            ("config", "User", "1234"),
            ("config", "Env", ["PATH=/tmp", "UNATTESTED=1"]),
            ("config", "WorkingDir", "/tmp"),
            ("config", "Healthcheck", None),
            ("config", "OnBuild", ["RUN id"]),
            ("config", "Shell", ["/bin/sh", "-c"]),
            ("config", "ArgsEscaped", True),
            ("config", "MacAddress", "02:42:ac:11:00:02"),
            ("config", "FutureRuntimeField", {"dangerous": True}),
            ("host", "ReadonlyRootfs", True),
            ("host", "SecurityOpt", ["seccomp=unconfined"]),
            ("host", "Memory", 123),
            ("host", "OomScoreAdj", -500),
            ("host", "LogConfig", {"Type": "none", "Config": {}}),
            ("host", "Runtime", "kata"),
            ("host", "PidsLimit", 17),
        ),
    )
    def test_unattested_container_is_masked_preserved_and_partial(
        self, tmp_path: Path, area: str, key: str, value: object
    ) -> None:
        home = tmp_path / "home"
        container_id = "a" * 64
        kwargs: dict[str, dict[str, object]] = {
            "config_overrides": {},
            "host_overrides": {},
            "top_overrides": {},
        }
        kwargs[f"{area}_overrides"][key] = value
        record = _historical_local_judge_inspect_record(
            container_id,
            home,
            **kwargs,
        )
        harness = _prepare_local_judge_retirement(
            tmp_path,
            container_id=container_id,
            container_record=record,
        )

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        assert "complete historical local-judge profile" in result.stderr
        installed = Path(harness["installed"])
        assert installed.is_symlink() and os.readlink(installed) == "/dev/null"
        assert Path(harness["name_state"]).read_text(encoding="utf-8").strip() == container_id
        lines = _event_lines(harness)
        assert not any(f" rm -f {container_id}" in line for line in lines)
        assert not any(line.startswith("uv ") for line in lines)

    @pytest.mark.parametrize(
        ("key", "value"),
        (
            ("Aliases", ["hapax-local-judge"]),
            ("IPAMConfig", {"IPv4Address": "172.17.0.2"}),
            ("DriverOpts", {}),
            ("NetworkID", "B" * 64),
            ("NetworkID", "0" * 64),
            ("EndpointID", "c" * 63),
            ("EndpointID", LOCAL_JUDGE_BRIDGE_ENDPOINT["NetworkID"]),
            ("Gateway", "not-an-ip"),
            ("Gateway", "10.0.0.1"),
            ("Gateway", "127.0.0.1"),
            ("IPAddress", "0.0.0.0"),
            ("IPAddress", "10.0.0.2"),
            ("IPPrefixLen", 0),
            ("IPPrefixLen", 33),
            ("IPPrefixLen", True),
            ("MacAddress", "not-a-mac"),
            ("MacAddress", "00:42:ac:11:00:02"),
            ("MacAddress", "02:42:ac:11:00:03"),
            ("GwPriority", False),
            ("IPv6Gateway", "::1"),
            ("DNSNames", []),
            ("FutureEndpointField", "enabled"),
        ),
        ids=(
            "alias",
            "static-ipam",
            "driver-options",
            "uppercase-network-id",
            "zero-network-id",
            "short-endpoint-id",
            "equal-network-and-endpoint-id",
            "malformed-gateway",
            "gateway-outside-network",
            "loopback-gateway",
            "unspecified-address",
            "address-outside-network",
            "zero-prefix",
            "oversized-prefix",
            "boolean-prefix",
            "malformed-mac",
            "global-mac",
            "mac-address-mismatch",
            "boolean-priority",
            "ipv6-gateway",
            "dns-names",
            "extra-key",
        ),
    )
    def test_unattested_bridge_endpoint_is_preserved(
        self, tmp_path: Path, key: str, value: object
    ) -> None:
        container_id = "a" * 64
        record = _historical_local_judge_inspect_record(
            container_id,
            tmp_path / "home",
            network_overrides={key: value},
        )
        harness = _prepare_local_judge_retirement(
            tmp_path,
            container_id=container_id,
            container_record=record,
        )

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        assert "complete historical local-judge profile" in result.stderr
        assert Path(harness["name_state"]).read_text(encoding="utf-8").strip() == container_id
        assert not any(f" rm -f {container_id}" in line for line in _event_lines(harness))

    def test_extra_bridge_network_is_preserved(self, tmp_path: Path) -> None:
        container_id = "a" * 64
        networks = {
            "bridge": json.loads(json.dumps(LOCAL_JUDGE_BRIDGE_ENDPOINT)),
            "hostile": json.loads(json.dumps(LOCAL_JUDGE_BRIDGE_ENDPOINT)),
        }
        record = _historical_local_judge_inspect_record(
            container_id,
            tmp_path / "home",
            top_overrides={"networks": networks},
        )
        harness = _prepare_local_judge_retirement(
            tmp_path,
            container_id=container_id,
            container_record=record,
        )

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        assert Path(harness["name_state"]).read_text(encoding="utf-8").strip() == container_id
        assert not any(f" rm -f {container_id}" in line for line in _event_lines(harness))

    def test_missing_bridge_endpoint_key_is_preserved(self, tmp_path: Path) -> None:
        container_id = "a" * 64
        fields = [
            json.loads(value)
            for value in _historical_local_judge_inspect_record(
                container_id, tmp_path / "home"
            ).split("\t")
        ]
        fields[9]["bridge"].pop("EndpointID")
        harness = _prepare_local_judge_retirement(
            tmp_path,
            container_id=container_id,
            container_record=_json_record(*fields),
        )

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        assert Path(harness["name_state"]).read_text(encoding="utf-8").strip() == container_id
        assert not any(f" rm -f {container_id}" in line for line in _event_lines(harness))

    @pytest.mark.parametrize(
        ("record_index", "field"),
        (
            (6, "User"),
            (6, "Healthcheck"),
            (6, "OnBuild"),
            (6, "Shell"),
            (6, "ArgsEscaped"),
            (6, "MacAddress"),
            (7, "OomScoreAdj"),
            (7, "LogConfig"),
        ),
        ids=(
            "missing-config-user",
            "missing-config-healthcheck",
            "missing-config-onbuild",
            "missing-config-shell",
            "missing-config-args-escaped",
            "missing-config-mac-address",
            "missing-host-oom-score",
            "missing-host-log-config",
        ),
    )
    def test_incomplete_inspect_record_is_preserved(
        self, tmp_path: Path, record_index: int, field: str
    ) -> None:
        container_id = "a" * 64
        fields = [
            json.loads(value)
            for value in _historical_local_judge_inspect_record(
                container_id, tmp_path / "home"
            ).split("\t")
        ]
        fields[record_index].pop(field)
        harness = _prepare_local_judge_retirement(
            tmp_path,
            container_record=_json_record(*fields),
        )

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        assert not any(f" rm -f {container_id}" in line for line in _event_lines(harness))
        assert Path(harness["name_state"]).read_text(encoding="utf-8").strip() == container_id

    @pytest.mark.parametrize(
        ("field", "value"),
        (
            ("hostname", "podium"),
            ("passwd_home", "/home/not-hapax"),
            ("os", "FreeBSD"),
            ("arch", "aarch64"),
        ),
    )
    def test_foreign_host_is_masked_but_never_cleaned(
        self, tmp_path: Path, field: str, value: str
    ) -> None:
        harness = _prepare_local_judge_retirement(
            tmp_path,
            host_facts={field: value},
        )

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        assert "exact Appendix/passwd-HOME/linux-amd64" in result.stderr
        lines = _event_lines(harness)
        assert not any(" image inspect " in line for line in lines)
        assert not any(" rm -f " in line for line in lines)
        assert Path(harness["installed"]).is_symlink()

    def test_synthetic_host_facts_reject_nonisolated_client_paths(self, tmp_path: Path) -> None:
        harness = _prepare_local_judge_retirement(tmp_path)
        env = dict(harness["env"])
        isolated_docker = Path(env["HAPAX_INSTALL_UNITS_RETIRE_DOCKER"])
        outside_docker = tmp_path / "outside-docker"
        outside_docker.write_text(isolated_docker.read_text(encoding="utf-8"), encoding="utf-8")
        outside_docker.chmod(0o755)
        env["HAPAX_INSTALL_UNITS_RETIRE_DOCKER"] = str(outside_docker)
        harness["env"] = env

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        assert "isolated owner-controlled test clients" in result.stderr
        assert not any(" rm -f " in line for line in _event_lines(harness))
        assert Path(harness["name_state"]).read_text(encoding="utf-8").strip()

    @pytest.mark.parametrize(
        "image_record",
        (
            _historical_local_judge_image_record(image_id="sha256:" + "f" * 64),
            _historical_local_judge_image_record(os_name="windows"),
            _historical_local_judge_image_record(architecture="arm64"),
        ),
    )
    def test_nonexact_image_platform_is_preserved(self, tmp_path: Path, image_record: str) -> None:
        harness = _prepare_local_judge_retirement(
            tmp_path,
            image_record=image_record,
        )

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        assert "pinned linux/amd64 config" in result.stderr
        assert not any(" rm -f " in line for line in _event_lines(harness))
        assert Path(harness["name_state"]).read_text(encoding="utf-8").strip()

    def test_docker_inventory_failure_occurs_after_manager_quiescence(self, tmp_path: Path) -> None:
        harness = _prepare_local_judge_retirement(
            tmp_path,
            docker_inventory_fails=True,
        )

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        lines = _event_lines(harness)
        show_index = next(i for i, line in enumerate(lines) if " show " in line)
        docker_index = next(i for i, line in enumerate(lines) if line.startswith("docker "))
        assert show_index < docker_index
        assert Path(harness["installed"]).is_symlink()
        assert not any(line.startswith("uv ") for line in lines)

    def test_missing_docker_client_cannot_block_manager_retirement(self, tmp_path: Path) -> None:
        harness = _prepare_local_judge_retirement(tmp_path)
        docker = Path(dict(harness["env"])["HAPAX_INSTALL_UNITS_RETIRE_DOCKER"])
        docker.chmod(0o644)

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        assert "executable pinned Docker client" in result.stderr
        installed = Path(harness["installed"])
        assert installed.is_symlink() and os.readlink(installed) == "/dev/null"
        lines = _event_lines(harness)
        assert "systemctl --user disable hapax-local-judge.service" in lines
        assert any(" show hapax-local-judge.service " in line for line in lines)
        assert not any(line.startswith("docker ") for line in lines)
        assert not any(line.startswith("uv ") for line in lines)

    @pytest.mark.parametrize("race", ("disappear", "signature-change"))
    def test_second_inspect_race_never_reaches_rm(self, tmp_path: Path, race: str) -> None:
        container_id = "a" * 64
        second_record = None
        if race == "signature-change":
            second_record = _historical_local_judge_inspect_record(
                container_id,
                tmp_path / "home",
                host_overrides={"OomScoreAdj": -500},
            )
        harness = _prepare_local_judge_retirement(
            tmp_path,
            second_record=second_record,
            second_inspect_fails=race == "disappear",
        )

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        lines = _event_lines(harness)
        assert sum(" container inspect --format " in line for line in lines) == 2
        assert not any(f" rm -f {container_id}" in line for line in lines)
        assert Path(harness["name_state"]).read_text(encoding="utf-8").strip() == container_id

    def test_exact_id_disappearance_is_bounded_and_polled(self, tmp_path: Path) -> None:
        harness = _prepare_local_judge_retirement(tmp_path, poll_linger=2)

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 0, result.stderr
        container_id = str(harness["container_id"])
        id_polls = [
            line for line in _event_lines(harness) if f" --filter id={container_id}" in line
        ]
        assert len(id_polls) == 3
        assert Path(harness["exact_state"]).read_text(encoding="utf-8") == ""

    def test_stuck_exact_id_returns_partial_without_followup_work(self, tmp_path: Path) -> None:
        harness = _prepare_local_judge_retirement(tmp_path, rm_mode="stuck")

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        assert "remained after bounded removal convergence" in result.stderr
        container_id = str(harness["container_id"])
        assert Path(harness["exact_state"]).read_text(encoding="utf-8").strip() == container_id
        assert not any(line.startswith("uv ") for line in _event_lines(harness))

    def test_replacement_is_reported_and_never_removed(self, tmp_path: Path) -> None:
        harness = _prepare_local_judge_retirement(tmp_path, rm_mode="replacement")

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        replacement_id = str(harness["replacement_id"])
        assert "replacement local-judge container appeared" in result.stderr
        assert Path(harness["name_state"]).read_text(encoding="utf-8").strip() == replacement_id
        assert not any(f" rm -f {replacement_id}" in line for line in _event_lines(harness))

    def test_final_manager_witness_cannot_be_synthesized_across_calls(self, tmp_path: Path) -> None:
        harness = _prepare_local_judge_retirement(tmp_path, manager_bad_after=1)

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        assert "final user-manager witness" in result.stderr
        show_lines = [
            line for line in _event_lines(harness) if " show hapax-local-judge.service " in line
        ]
        assert len(show_lines) == 2
        assert all("-p LoadState -p UnitFileState -p ActiveState" in line for line in show_lines)
        assert all("-p SubState -p MainPID -p ControlPID" in line for line in show_lines)
        assert not any("--value" in line for line in show_lines)

    def test_final_manager_witness_rejects_mask_generation_race(self, tmp_path: Path) -> None:
        harness = _prepare_local_judge_retirement(tmp_path, mask_race_after=1)

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 2
        assert "final user-manager witness" in result.stderr
        installed = Path(harness["installed"])
        assert installed.is_symlink() and os.readlink(installed) == "/dev/null"

    def test_disable_failure_does_not_block_mask_or_attested_cleanup(self, tmp_path: Path) -> None:
        harness = _prepare_local_judge_retirement(tmp_path, disable_fails=True)

        result = _run_local_judge_retirement(harness)

        assert result.returncode == 0, result.stderr
        lines = _event_lines(harness)
        assert "systemctl --user disable hapax-local-judge.service" in lines
        assert Path(harness["installed"]).is_symlink()
        assert Path(harness["name_state"]).read_text(encoding="utf-8") == ""

    def test_empty_retirement_is_idempotent_without_host_admission(self, tmp_path: Path) -> None:
        harness = _prepare_local_judge_retirement(
            tmp_path,
            container_id=None,
            host_facts={"hostname": "not-appendix"},
        )

        first = _run_local_judge_retirement(harness)
        second = _run_local_judge_retirement(harness)

        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        assert Path(harness["installed"]).is_symlink()
        assert not any(" image inspect " in line for line in _event_lines(harness))
