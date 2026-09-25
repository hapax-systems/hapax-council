"""Static pins for the SDLC resource-shielding units (the anti-kill scheme).

Shield real-time workloads (audio data-loops, the coordinator) from the SDLC
fleet via a cpu.idle slice + an audio-core cpuset fence. These pins keep the
load-bearing directives from silently regressing.
"""

from __future__ import annotations

import ast
import json
import os
import pwd
import re
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
INSTALLER = REPO_ROOT / "systemd" / "scripts" / "install-units.sh"

# Logical cores carrying the SCHED_FIFO 88 audio data-loops (Ryzen 7700X: phys
# 6+7 with SMT siblings). No SDLC worker may ever land here.
AUDIO_CORES = {6, 7, 14, 15}
FLEET_FENCE = {0, 1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 13}


def _directive(text: str, key: str) -> str | None:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip() == key:
            return v.strip()
    return None


def _continued_directive(text: str, key: str) -> str | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        value = line.strip()
        if value.startswith("#") or not value.startswith(f"{key}="):
            continue
        value = value.split("=", 1)[1]
        parts: list[str] = []
        while value.endswith("\\"):
            parts.append(value[:-1].rstrip())
            index += 1
            value = lines[index].strip()
        parts.append(value)
        return " ".join(parts)
    return None


def _parse_cpu_set(spec: str) -> set[int]:
    out: set[int] = set()
    for token in spec.replace(",", " ").split():
        if "-" in token:
            lo, hi = token.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(token))
    return out


# ── L1: the elastic yield slice ──────────────────────────────────────────────


def test_sdlc_slice_exists_and_is_idle_weighted() -> None:
    slice_file = UNITS_DIR / "hapax-sdlc.slice"
    assert slice_file.exists(), "hapax-sdlc.slice is the elastic baseline — must exist"
    text = slice_file.read_text()
    assert _directive(text, "CPUWeight") == "idle", "CPUWeight=idle → cpu.idle=1 (SCHED_IDLE)"


def test_sdlc_slice_fences_audio_cores() -> None:
    text = (UNITS_DIR / "hapax-sdlc.slice").read_text()
    allowed = _parse_cpu_set(_directive(text, "AllowedCPUs") or "")
    assert allowed == FLEET_FENCE
    assert not (allowed & AUDIO_CORES), "no pytest/cargo worker may land on the audio cores"


def test_sdlc_slice_throttles_memory_without_killing() -> None:
    text = (UNITS_DIR / "hapax-sdlc.slice").read_text()
    assert _directive(text, "MemoryHigh") == "48G", "MemoryHigh reclaim-throttles, never kills"
    # MemoryMax-as-throttle would SIGKILL a lane mid-work — that is degradation.
    assert _directive(text, "MemoryMax") is None, "MemoryMax must not be used as a throttle"
    assert _directive(text, "Delegate") == "yes"


def test_app_slice_has_aggregate_oom_backstop() -> None:
    text = (UNITS_DIR / "app.slice.d" / "oom-containment.conf").read_text()
    assert _directive(text, "MemoryHigh") == "72G"
    assert _directive(text, "MemoryMax") == "88G"
    assert _directive(text, "MemorySwapMax") == "8G"
    assert _directive(text, "MemoryLow") == "16G"
    assert _directive(text, "MemoryMin") == "8G"


def test_session_slice_carries_audio_reservation_ancestor() -> None:
    text = (UNITS_DIR / "session.slice.d" / "oom-containment.conf").read_text()
    assert _directive(text, "MemoryHigh") == "infinity"
    assert _directive(text, "MemoryMax") == "infinity"
    assert _directive(text, "MemorySwapMax") == "infinity"
    assert _directive(text, "MemoryLow") == "2G"
    assert _directive(text, "MemoryMin") == "1G"


def test_uid_slice_has_session_and_app_aggregate_oom_backstop() -> None:
    text = (
        REPO_ROOT / "systemd" / "system" / "user-1000.slice.d" / "oom-containment.conf"
    ).read_text()
    assert _directive(text, "MemoryHigh") == "80G"
    assert _directive(text, "MemoryMax") == "96G"
    assert _directive(text, "MemorySwapMax") == "8G"
    assert _directive(text, "MemoryLow") == "20G"
    assert _directive(text, "MemoryMin") == "10G"


def test_user_slice_allocates_ancestor_memory_protection() -> None:
    text = (REPO_ROOT / "systemd" / "system" / "user.slice.d" / "oom-containment.conf").read_text()
    assert _directive(text, "MemoryHigh") == "infinity"
    assert _directive(text, "MemoryMax") == "infinity"
    assert _directive(text, "MemorySwapMax") == "infinity"
    assert _directive(text, "MemoryLow") == "20G"
    assert _directive(text, "MemoryMin") == "10G"


def test_user_manager_does_not_protect_every_interactive_workload() -> None:
    text = (REPO_ROOT / "systemd" / "system" / "user@1000.service.d" / "oom.conf").read_text()
    assert _directive(text, "OOMScoreAdjust") == "100"
    assert _directive(text, "OOMPolicy") == "continue"
    assert _directive(text, "MemoryLow") == "20G"
    assert _directive(text, "MemoryMin") == "10G"
    assert _directive(text, "MemoryHigh") == "80G"
    assert _directive(text, "MemoryMax") == "96G"
    assert _directive(text, "MemorySwapMax") == "8G"


def test_system_slice_has_reciprocal_recovery_plane_reservation() -> None:
    text = (
        REPO_ROOT / "systemd" / "system" / "system.slice.d" / "oom-containment.conf"
    ).read_text()
    assert _directive(text, "MemoryHigh") == "infinity"
    assert _directive(text, "MemoryMax") == "infinity"
    assert _directive(text, "MemoryLow") == "24G"
    assert _directive(text, "MemoryMin") == "12G"


def test_live_cuepoints_is_parked_while_feature_is_disabled() -> None:
    text = (UNITS_DIR / "hapax-live-cuepoints.service").read_text()
    assert "# Hapax-Parked: true" in text
    assert "Environment=HAPAX_LIVE_CUEPOINTS_ENABLED=0" in text
    assert _directive(text, "Restart") == "no"
    assert "PartOf=hapax.target" not in text
    assert "OnFailure=" not in text
    assert "[Install]" not in text
    assert "WantedBy=" not in text


def test_live_cuepoints_runs_from_source_activation_worktree() -> None:
    text = (UNITS_DIR / "hapax-live-cuepoints.service").read_text()
    assert "WorkingDirectory=%h/.cache/hapax/source-activation/worktree" in text
    assert "Environment=PATH=%h/.cache/hapax/source-activation/worktree/.venv/bin" in text
    assert "Environment=PYTHONPATH=%h/.cache/hapax/source-activation/worktree" in text
    assert "ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python" in text
    assert "WorkingDirectory=%h/projects/hapax-council" not in text


def test_recovery_daemon_oom_dropins_are_source_controlled() -> None:
    expected = {
        "apcupsd.service.d/oom-protect.conf": "-900",
        "systemd-logind.service.d/oom-protect.conf": "-800",
        "systemd-resolved.service.d/oom-protect.conf": "-800",
        "systemd-timesyncd.service.d/oom-protect.conf": "-800",
        "NetworkManager.service.d/oom-protect.conf": "-800",
        "dbus-broker.service.d/oom-protect.conf": "-900",
        "sshd.service.d/oom-protect.conf": "0",
    }
    for rel, score in expected.items():
        text = (REPO_ROOT / "systemd" / "system" / rel).read_text()
        assert _directive(text, "OOMScoreAdjust") == score

    sshd = (REPO_ROOT / "systemd" / "system" / "sshd.service.d/oom-protect.conf").read_text()
    assert _directive(sshd, "OOMPolicy") == "continue"


def test_broadcast_critical_user_oom_dropins_are_source_controlled() -> None:
    expected = {
        "pipewire.service.d/oom-protect.conf",
        "pipewire-pulse.service.d/oom-protect.conf",
        "wireplumber.service.d/oom-protect.conf",
        "hapax-daimonion.service.d/oom-protect.conf",
        "studio-compositor.service.d/oom-protect.conf",
        "hapax-imagination.service.d/oom-protect.conf",
    }
    audio_units = {
        "pipewire.service.d/oom-protect.conf",
        "pipewire-pulse.service.d/oom-protect.conf",
        "wireplumber.service.d/oom-protect.conf",
    }
    for rel in expected:
        text = (UNITS_DIR / rel).read_text()
        assert _directive(text, "OOMScoreAdjust") == "100"
        if rel in audio_units:
            assert _directive(text, "ExecStartPost") is None
            assert _directive(text, "NoNewPrivileges") is None
        else:
            assert _directive(text, "ExecStartPost") == "-/usr/local/bin/hapax-oom-score-trigger %n"
        assert _directive(text, "MemoryLow") is not None
        assert _directive(text, "MemoryMin") is not None


def test_protected_user_unit_allowlist_and_scores_match_across_runtime_surfaces() -> None:
    expected = {
        "pipewire.service": -900,
        "pipewire-pulse.service": -900,
        "wireplumber.service": -900,
        "hapax-daimonion.service": -500,
        "studio-compositor.service": -800,
        "hapax-imagination.service": -800,
    }
    oom_installer = (REPO_ROOT / "scripts/install-p0-oom-containment").read_text()
    installer_block = re.search(
        r"^protected_user_unit_scores=\(\n(?P<body>.*?)^\)",
        oom_installer,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert installer_block is not None
    installer_scores = {}
    for line in installer_block.group("body").splitlines():
        unit, score = line.strip().rsplit(":", 1)
        installer_scores[unit] = int(score)

    enforcer = (REPO_ROOT / "scripts/hapax-oom-score-enforce").read_text()
    enforcer_scores = {
        unit: int(score)
        for unit, score in re.findall(
            r"^apply_unit_score ([a-z0-9@_.-]+) (-?\d+)$", enforcer, flags=re.MULTILINE
        )
    }
    enforcer_allowlist = {}
    enforcer_function = re.search(
        r"protected_user_unit_score\(\) \{(?P<body>.*?)^\}",
        enforcer,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert enforcer_function is not None
    for units, score in re.findall(
        r"^\s+([a-z0-9@_. |/-]+)\)\n\s+printf '%s\\n' (-?\d+)$",
        enforcer_function.group("body"),
        flags=re.MULTILINE,
    ):
        for unit in units.split("|"):
            enforcer_allowlist[unit.strip()] = int(score)

    audit_tree = ast.parse((REPO_ROOT / "scripts/hapax-oom-policy-audit").read_text())
    audit_scores = None
    for node in audit_tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PROTECTED_USER_UNITS"
            for target in node.targets
        ):
            audit_scores = ast.literal_eval(node.value)
            break
    assert audit_scores is not None

    trigger = (REPO_ROOT / "scripts/hapax-oom-score-trigger").read_text()
    trigger_match = re.search(r'case "\$unit" in\n\s+(?P<units>[^\n]+)\) ;;', trigger)
    assert trigger_match is not None
    trigger_units = {unit.strip() for unit in trigger_match.group("units").split("|")}

    sudoers = (REPO_ROOT / "config/root-required/hapax-oom-score-enforce.sudoers").read_text()
    sudoers_units = set(re.findall(r"--apply-unit ([a-z0-9@_.-]+)", sudoers))
    dropin_units = {
        path.parent.name.removesuffix(".d")
        for path in UNITS_DIR.glob("*.service.d/oom-protect.conf")
    }

    assert installer_scores == enforcer_scores == enforcer_allowlist == audit_scores == expected
    assert trigger_units == sudoers_units == dropin_units == set(expected)


def test_oom_policy_audit_timer_is_source_controlled() -> None:
    timer = (UNITS_DIR / "hapax-oom-policy-audit.timer").read_text()
    service = (UNITS_DIR / "hapax-oom-policy-audit.service").read_text()
    assert "Hapax-Installer-Owner: scripts/install-p0-oom-containment" in timer
    assert "Hapax-Auto-Enable" not in timer
    assert "OnUnitActiveSec=5min" in timer
    assert "ExecStart=/usr/local/sbin/hapax-oom-policy-audit --json" in service
    assert "TimeoutStartSec=2min" in service
    assert "Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin" in service
    audit = (REPO_ROOT / "scripts" / "hapax-oom-policy-audit").read_text()
    assert 'SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/bin:/bin"' in audit
    assert 'os.environ["PATH"] = SAFE_PATH' in audit
    assert "hapax-systems/hapax-council/blob/main/systemd/README.md" in service
    assert "hapax-systems/hapax-council/blob/main/systemd/README.md" in timer
    assert "source-activation" not in service
    assert "StartLimitIntervalSec=0" in service
    assert "StartLimitBurst" not in service
    assert "ConditionPathExists" not in service


def test_root_required_deploy_audit_timer_is_source_controlled() -> None:
    timer = (UNITS_DIR / "hapax-root-required-deploy-audit.timer").read_text()
    service = (UNITS_DIR / "hapax-root-required-deploy-audit.service").read_text()
    assert "Hapax-Installer-Owner: scripts/install-p0-oom-containment" in timer
    assert "Hapax-Auto-Enable" not in timer
    assert "OnUnitActiveSec=10min" in timer
    assert "ExecStart=/usr/local/sbin/hapax-root-required-deploy-audit" in service
    assert "TimeoutStartSec=2min" in service
    assert "Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin" in service
    audit = (REPO_ROOT / "scripts" / "hapax-root-required-deploy-audit").read_text()
    assert audit.startswith("#!/usr/bin/bash -p\n")
    assert "PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin\nexport PATH\n" in audit
    assert "hapax-systems/hapax-council/blob/main/systemd/README.md" in service
    assert "hapax-systems/hapax-council/blob/main/systemd/README.md" in timer
    assert "source-activation" not in service
    assert "StartLimitIntervalSec=0" in service
    assert "StartLimitBurst" not in service
    assert "ConditionPathExists" not in service


def test_root_oom_enforcer_uses_system_scoped_failure_intake() -> None:
    enforcer = (UNITS_DIR / "hapax-oom-score-enforce.service").read_text()
    timer = (UNITS_DIR / "hapax-oom-score-enforce.timer").read_text()
    intake = (UNITS_DIR / "hapax-root-failure-intake@.service").read_text()
    assert "# Hapax-Install-Scope: system" in enforcer
    assert "OnFailure=hapax-root-failure-intake@%n.service" in enforcer
    assert "Wants=user@1000.service" not in enforcer
    assert "After=user@1000.service" in enforcer
    assert "StartLimitIntervalSec=0" in enforcer
    assert "StartLimitBurst" not in enforcer
    assert "AccuracySec=1s" in timer
    assert "# Hapax-Install-Scope: system" in intake
    assert "User=hapax" in intake
    assert "Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin" in intake
    assert "/home/hapax/.local/bin" not in intake
    assert "ExecStart=/usr/local/sbin/hapax-root-failure-intake %i" in intake
    assert "SyslogIdentifier=hapax-root-failure-intake" in intake
    assert "%I" not in intake
    assert "source-activation/worktree" not in intake
    assert "StartLimitIntervalSec=1h" in intake
    assert "StartLimitBurst=1" in intake
    assert "source-activation/worktree" not in enforcer
    assert "hapax-systems/hapax-council/blob/main/systemd/README.md" in enforcer
    assert "/home/hapax" not in enforcer
    assert "ConditionPathExists" not in intake


# ── L2: the audio-core cpuset fence ──────────────────────────────────────────


def test_compositor_excluded_from_audio_cores() -> None:
    conf = UNITS_DIR / "studio-compositor.service.d" / "cpu-affinity.conf"
    allowed = _parse_cpu_set(_directive(conf.read_text(), "CPUAffinity") or "")
    assert not (allowed & AUDIO_CORES)


def test_daimonion_cpu_side_fenced_off_audio_cores() -> None:
    conf = UNITS_DIR / "hapax-daimonion.service.d" / "cpu-affinity.conf"
    assert conf.exists(), "daimonion CPU-side work must be pinned off the audio data-loops"
    allowed = _parse_cpu_set(_directive(conf.read_text(), "CPUAffinity") or "")
    assert allowed, "CPUAffinity must be set"
    assert not (allowed & AUDIO_CORES), "daimonion vision/STT spikes must not preempt audio"


# ── Cross-cutting: the controller never starves while throttling the fleet ───


def test_coordinator_has_high_cpuweight() -> None:
    text = (UNITS_DIR / "hapax-coordinator.service").read_text()
    weight = _directive(text, "CPUWeight")
    assert weight is not None and weight.isdigit() and int(weight) >= 1000, (
        "the controller must out-weight the idle fleet it throttles"
    )


def test_coordinator_pinned_to_a_fleet_fenced_core() -> None:
    # The controller gets cores the SDLC fleet is fenced OUT of, so it never
    # starves while throttling the controlled (the exact death of 2026-06-01).
    text = (UNITS_DIR / "hapax-coordinator.service").read_text()
    allowed = _parse_cpu_set(_directive(text, "AllowedCPUs") or "")
    assert allowed, "coordinator must pin to a protected cpuset"
    assert not (allowed & FLEET_FENCE), "coordinator cores must be off the SDLC fleet's cpuset"


def test_coordinator_runs_from_source_activation_worktree() -> None:
    text = (UNITS_DIR / "hapax-coordinator.service").read_text()
    assert "WorkingDirectory=%h/.cache/hapax/source-activation/worktree" in text
    assert "ConditionPathExists=%h/.cache/hapax/source-activation/worktree/pyproject.toml" in text
    assert ".cache/hapax/rebuild/worktree" not in text


def test_coordinator_dispatcher_uses_source_activation_worktree() -> None:
    text = (UNITS_DIR / "hapax-coordinator.service").read_text()
    assert (
        "Environment=HAPAX_METHODOLOGY_DISPATCHER=%h/.cache/hapax/source-activation/"
        "worktree/scripts/hapax-methodology-dispatch"
    ) in text


# ── Deploy visibility: install-units.sh links the slice + drop-ins ───────────


def test_installer_links_slice_units() -> None:
    body = INSTALLER.read_text()
    assert '"$REPO_DIR"/*.slice' in body, "install-units.sh must symlink .slice units"


def test_installer_links_service_dropins() -> None:
    body = INSTALLER.read_text()
    assert '"$REPO_DIR"/*.service.d' in body
    assert '"$REPO_DIR"/*.timer.d' in body
    assert '"$REPO_DIR"/*.slice.d' in body
    assert '"$REPO_DIR"/*.scope.d' in body


def test_p0_oom_containment_has_dedicated_installer() -> None:
    installer = REPO_ROOT / "scripts" / "install-p0-oom-containment"
    body = installer.read_text()
    assert "systemd/system/user-1000.slice.d/oom-containment.conf" in body
    assert "systemd/system/user@1000.service.d/oom.conf" in body
    assert "systemd/units/app.slice.d/oom-containment.conf" in body
    assert "systemd/units/session.slice.d/oom-containment.conf" in body
    assert "systemd/units/hapax-local-judge.service" in body
    assert "config/earlyoom/default" in body
    assert "app_slice_value MemoryHigh" in body
    assert "apply_system_runtime_memory user-1000.slice" in body
    assert "apply_system_runtime_memory user@1000.service" in body
    assert "set-property --runtime app.slice" in body
    assert "set-property --runtime session.slice" in body
    assert "verify_system_unit_runtime_memory user-1000.slice" in body
    assert "verify_app_slice_runtime" in body
    assert "verify_session_slice_runtime" in body


def test_oom_runtime_receipt_requires_each_host_memtotal_before_drain() -> None:
    text = (REPO_ROOT / "systemd" / "README.md").read_text()

    assert "awk '$1 == \"MemTotal:\" {print $2; exit}' /proc/meminfo" in text
    assert "both `hapax-appendix` and" in text
    assert "`hapax-podium` immediately before each host's first authenticated deferred" in text
    assert "a witness from the other" in text
    assert "host is not evidence of the target host's installed RAM class" in text
    assert "Podium's first transition from the observed 8 GiB zram device" in text
    assert "require `zramctl` and `/proc/swaps` to show no swap-backed pressure" in text
    assert "runtime-authorized" in text
    assert "do not hand-edit the generator config" in text


def test_local_judge_container_has_a_finite_memory_cap() -> None:
    text = (UNITS_DIR / "hapax-local-judge.service").read_text()
    assert "--memory 4G --memory-swap 6G" in text
    assert "ghcr.io/ggml-org/llama.cpp:server-cuda" not in text
    assert (
        "Environment=JUDGE_IMAGE=ghcr.io/ggml-org/llama.cpp@sha256:"
        "841b199aed2649a748875b043b32fed2e8c2d4d87e1d563556817fb7fa44b72b"
    ) in text
    assert "Environment=JUDGE_MODEL_SHA256=d6d6fba56c25" in text
    assert "Environment=JUDGE_MODEL_SIZE_BYTES=5444831808" in text
    assert (
        "Environment=JUDGE_MODEL_HOST_DIR=/store-fast/hapax-models/sha256/"
        "d6d6fba56c25d2d0f1b2cc8ee261b209b77729510b3d770d43ccb6e741dff0db"
    ) in text
    assert "--mount type=bind,src=${JUDGE_MODEL_HOST_DIR},dst=/models,readonly" in text
    assert "%h/models/compassverifier-7b:/models:ro" not in text
    assert "${JUDGE_IMAGE}" in text
    assert "--pull=never" in text
    assert "--cidfile %t/hapax-local-judge/container.cid" in text
    assert "RuntimeDirectory=hapax-local-judge" in text
    assert "RuntimeDirectoryPreserve=yes" in text
    assert "hapax-local-judge-container-id wait-daemon" in text
    assert "hapax-local-judge-container-id preflight" in text
    assert "hapax-local-judge-container-id stop" in text
    assert "ExecStop=/usr/bin/docker stop hapax-local-judge" not in text
    assert "--oom-kill-disable" not in text
    assert "ExecStartPre=-/usr/bin/docker rm" not in text
    assert "stop/restart never targets the name" in text


def test_local_judge_launch_clears_hostile_docker_selectors(tmp_path: Path) -> None:
    text = (UNITS_DIR / "hapax-local-judge.service").read_text()
    command = _continued_directive(text, "ExecStart")
    assert command is not None

    unit_env: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("Environment="):
            key, value = line.removeprefix("Environment=").split("=", 1)
            unit_env[key] = value
    for key, value in unit_env.items():
        command = command.replace(f"${{{key}}}", value)

    account = pwd.getpwuid(os.getuid())
    runtime_root = tmp_path / "run"
    command = (
        command.replace("%t", str(runtime_root))
        .replace("%h", account.pw_dir)
        .replace("%u", account.pw_name)
    )
    argv = shlex.split(command)
    assert argv[0] == "/usr/bin/env"
    assert argv[1] == "-i"
    docker_index = argv.index("/usr/bin/docker")

    launch_log = tmp_path / "docker-launch.json"
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/usr/bin/python3\n"
        "import json, os, pathlib, sys\n"
        f"pathlib.Path({str(launch_log)!r}).write_text(\n"
        "    json.dumps({'argv': sys.argv[1:], 'env': dict(os.environ)}),\n"
        "    encoding='utf-8',\n"
        ")\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    argv[docker_index] = str(fake_docker)
    hostile_selectors = {
        "DOCKER_CERT_PATH": str(tmp_path / "hostile-certs"),
        "DOCKER_CONFIG": str(tmp_path / "hostile-config"),
        "DOCKER_CONTEXT": "hostile-remote-context",
        "DOCKER_HOST": "tcp://hostile.invalid:2376",
        "DOCKER_TLS_VERIFY": "1",
        "HOME": str(tmp_path / "hostile-home"),
    }

    result = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, **hostile_selectors},
    )

    assert result.returncode == 0, result.stderr
    launch = json.loads(launch_log.read_text(encoding="utf-8"))
    assert launch["argv"][:3] == [
        "--host=unix:///var/run/docker.sock",
        f"--config={runtime_root}/hapax-local-judge/docker-config",
        "run",
    ]
    assert not {key for key in launch["env"] if key.startswith("DOCKER_")}
    assert launch["env"]["HOME"] == account.pw_dir
    assert launch["env"]["PATH"] == "/usr/bin:/bin"


def test_local_judge_uses_bounded_daemon_wait_before_container_preflight() -> None:
    text = (UNITS_DIR / "hapax-local-judge.service").read_text()
    normalized = " ".join(line.removeprefix("# ") for line in text.splitlines())
    wait = text.index("hapax-local-judge-container-id wait-daemon")
    prepare = text.index("hapax-local-judge-container-id prepare")
    preflight = text.index("hapax-local-judge-container-id preflight")

    assert "\nAfter=docker.service" not in text
    assert "Wants=docker.service" not in text
    assert "Requires=docker.service" not in text
    assert "Restart=always" in text
    assert "RestartSec=5" in text
    assert "TimeoutStartSec=90" in text
    assert wait < prepare < preflight
    assert "After=docker.service is deliberately omitted" in text
    assert "cannot order the system manager's docker.service" in normalized
    assert "bounded first preflight probes the pinned local daemon" in normalized
    assert "persistent cross-manager unavailability" in normalized


def test_local_judge_unit_names_the_protected_model_recheck() -> None:
    text = (UNITS_DIR / "hapax-local-judge.service").read_text()

    assert 'scripts/hapax-post-merge-deploy" --measure-protected-local-judge-model' in text
    assert "only once this release is the" in text
    assert "canonical source-activation worktree" in text
    assert "/store-fast/hapax-models/sha256/" in text
    assert "Container-internal path only" in text
    assert "this value never names the mutable host source" in text
    assert 'account_home="$(/usr/bin/getent passwd "$(/usr/bin/id -u)"' in text
    assert "/home/hapax/.cache/hapax/source-activation/worktree" not in text


def test_local_judge_runbook_has_read_only_protected_model_recheck_before_mutation() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    unit = (UNITS_DIR / "hapax-local-judge.service").read_text()
    environment = {
        key: value
        for line in unit.splitlines()
        if line.startswith("Environment=")
        for key, value in (line.removeprefix("Environment=").split("=", 1),)
    }

    read_only = "before requesting runtime authority, perform this read-only source/live identity"
    measure = "--measure-protected-local-judge-model"
    mutation_boundary = "Every mutation described below is unavailable"
    flattened = " ".join(text.replace("\\\n", "").split())
    assert read_only in flattened
    assert (
        flattened.index(read_only) < flattened.index(measure) < flattened.index(mutation_boundary)
    )
    assert "without staging, starting, stopping, or replacing anything" in flattened
    assert "An unrecognized option means source activation is stale" in flattened
    assert "A missing protected path means the model has not yet been staged" in flattened
    assert "before an authorized canary and is not an integrity failure" in flattened
    assert f"{measure} {environment['JUDGE_MODEL_HOST']}" in flattened
    assert Path(environment["JUDGE_MODEL_HOST"]).parent == Path(environment["JUDGE_MODEL_HOST_DIR"])
    assert environment["JUDGE_MODEL_SHA256"] in environment["JUDGE_MODEL_HOST"]


def test_local_judge_runbook_withholds_production_mutation_recipes() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    flattened = " ".join(text.split())
    forbidden = (
        r"(?m)^\s*(?:/usr/bin/)?sudo\b",
        r"(?m)^\s*(?:/usr/bin/)?systemctl\s+--user\s+(?:start|stop|restart|enable)\b",
        r"(?m)^\s*(?:/usr/bin/)?docker\s+(?:run|rm|pull)\b",
        r"(?m)^\s*(?:/usr/bin/)?docker\s+compose\b.*\bup\b",
    )

    for pattern in forbidden:
        assert re.search(pattern, text) is None, pattern
    assert "next action: run:" not in text
    assert "HAPAX_LOCAL_JUDGE_CAP_CANARY" not in text
    assert "HAPAX_LOCAL_JUDGE_AUTHENTICATED_INSTALL" not in text
    assert "HAPAX_LOCAL_JUDGE_INSTALLED_VERIFY" not in text
    assert "current or historical Git helper" not in text
    assert "Current and historical Git helper blobs are data only" in flattened


def test_local_judge_runbook_states_attested_successor_contract() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    flattened = " ".join(text.split())

    assert "Required pre-deploy cap canary unavailable" in text
    assert "Broker-gated package installation unavailable" in text
    assert "Activation and recheck unavailable" in text
    assert "cryptographically attested host-root transaction" in flattened
    assert "source-pinned verifier" in flattened
    assert "current-generation host-root attestations" in flattened
    assert "Production verification must fail" in flattened
    assert "no runnable activation, stale-container cleanup, ad hoc container" in flattened


def test_local_judge_fallback_drill_is_not_runnable() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    start = text.index("- **Fallback drill:**")
    drill = " ".join(text[start:].split())

    assert "unavailable until the attested activation protocol" in drill
    assert "publishes no stop, start, or container removal command" in drill
    assert "systemctl --user stop" not in drill
    assert "systemctl --user start" not in drill


def test_local_judge_managed_runtime_recheck_is_documented_but_not_executable() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    flattened = " ".join(text.split())

    assert (
        "managed 8-worker, 24-request post-activation recheck is intentionally unavailable"
        in flattened
    )
    assert "health, restart, OOM, and peak-memory predicates remain required" in flattened
    assert "HAPAX_LOCAL_JUDGE_MANAGED_RECHECK" not in text
    assert 'container_id="$(release_lifecycle managed-id' not in text
    assert "--run-local-judge-cap-workload http://127.0.0.1:5001" not in text
