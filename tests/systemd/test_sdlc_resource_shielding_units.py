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
import shutil
import subprocess
from pathlib import Path

import pytest

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
    mutation_boundary = "Every command below mutates the appendix runtime"
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
    assert 'expected_model_size_bytes="$(printf' in text
    assert "JUDGE_MODEL_SIZE_BYTES" in text


def test_local_judge_runbook_requires_live_authenticated_command() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    assert "desired-receipts/oom-containment.sha" in text
    assert 'test "$(/usr/bin/wc -c < "$receipt")" = 41' in text
    assert 'IFS= read -r sha < "$receipt"' in text
    assert '"$stage/scripts/install-p0-oom-containment"' not in text
    assert '[[ "$sha" =~ ^[0-9a-f]{40}$ ]]' in text
    assert 'runbook="$stage/RUNBOOK.txt"' in text
    assert 'test ! -L "$runbook"' in text
    assert 'test ! -x "$runbook"' in text
    assert "DO NOT EXECUTE THIS FILE OR COPY A COMMAND FROM IT" in text
    assert '"$runbook"' in text
    assert 'head -n 5 "$runbook"' not in text
    assert 'release_verify "$sha"' in text
    assert '~/.local/bin/hapax-post-merge-deploy "$sha"' not in text
    assert '/usr/bin/bash -p "$runbook"' not in text
    assert "completed authenticated package=oom-containment sha=$sha" in text
    assert '"$stage/AUTHENTICATED-INSTALL.log"' in text
    assert "cp systemd/units/hapax-local-judge.service" not in text
    install_marker = 'release_verify "$sha"'
    install_fence_start = text.rfind("```bash", 0, text.index(install_marker))
    install_fence_end = text.index("```", text.index(install_marker))
    install_fence = text[install_fence_start:install_fence_end]
    assert '/usr/bin/git -C "$repo" "$@"' in install_fence
    assert 'release_git cat-file blob "$verifier_oid"' in install_fence
    assert "GIT_CONFIG_GLOBAL=/dev/null" in install_fence
    assert 'inner_account_home="$(/usr/bin/env -i' in install_fence
    assert "HOME does not match the passwd-backed account home" in install_fence
    assert "systemctl --user enable" not in install_fence
    assert "systemctl --user restart" not in install_fence


def test_local_judge_fallback_drill_uses_the_unit_owned_lifecycle() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    start = text.index("- **Fallback drill:**")
    drill = text[start:]
    flat_drill = " ".join(drill.split())

    assert "systemctl --user stop hapax-local-judge.service" in flat_drill
    assert "-p ActiveState --value" in flat_drill
    assert "$XDG_RUNTIME_DIR/hapax-local-judge/container.cid" in flat_drill
    assert "docker ps -aq --no-trunc" in flat_drill
    assert "systemctl --user start hapax-local-judge.service" in flat_drill
    assert "docker stop hapax-local-judge" not in flat_drill


def test_local_judge_predeploy_canary_gates_exact_cap_installation() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    canary_marker = 'canary_name="hapax-local-judge-cap-canary-$$"'
    canary_start = text.rfind("```bash", 0, text.index(canary_marker))
    canary_end = text.index("```", text.index(canary_marker))
    canary = text[canary_start:canary_end]

    assert "--verify-runtime-authority-for-release" in canary
    assert "runtime:docker:pull:ghcr.io/ggml-org/llama.cpp@sha256:" in canary
    assert "runtime:docker:run-remove:hapax-local-judge-cap-canary" in canary
    assert "runtime:root-file:stage-content-addressed:/store-fast/hapax-models/sha256/" in canary
    assert "runtime:state:write-local-judge-cap-receipt" in canary
    assert "runtime:systemd-user:stop-restore:hapax-local-judge.service" in canary
    assert '"$runtime_task" systemd/units/hapax-local-judge.service' not in canary
    assert "PATH=/usr/bin:/bin" in canary
    assert "/usr/bin/env -i" in canary
    assert "/usr/bin/bash --noprofile --norc -p -s" in canary
    assert "<<'HAPAX_LOCAL_JUDGE_CAP_CANARY'" in canary
    assert "DOCKER_HOST=unix:///var/run/docker.sock" in canary
    assert "builtin compgen -A function" not in canary
    assert canary.index("--verify-runtime-authority-for-release") < canary.index("docker pull")
    assert 'candidate_sha="${repo##*/}"' in canary
    assert (
        'test "$(candidate_git rev-parse --verify \'HEAD^{commit}\')" = "$candidate_sha"' in canary
    )
    assert 'test "$desired_sha" = "$candidate_sha"' in canary
    assert 'candidate_git show "$candidate_sha:systemd/units/hapax-local-judge.service"' in canary
    assert '/usr/bin/git -C "$repo" "$@"' in canary
    assert 'candidate_git cat-file blob "$verifier_oid"' in canary
    assert 'workload_oid="$verifier_oid"' in canary
    assert 'candidate_verify "$@"' in canary
    assert 'authority_check="$HOME/.local/bin/hapax-post-merge-deploy"' not in canary
    assert '--run-local-judge-cap-workload "$endpoint" "$results"' in canary
    assert "run_verifierbench.py" not in canary
    assert "verifierbench_test.parquet" not in canary
    assert '"workload_oid=$workload_oid"' in canary
    assert '"model_sha256=$model_sha256"' in canary
    assert '"model_host_dir=$model_host_dir"' in canary
    assert '"model_identity=$model_identity"' in canary
    assert "--measure-protected-local-judge-model" in canary
    model_measure = 'model_evidence="$(candidate_workload --measure-protected-local-judge-model'
    assert canary.index(model_measure) < canary.index("docker run --pull=never")
    assert canary.index(model_measure) < canary.index('receipt_tmp="$(mktemp')
    assert "sudo /usr/bin/install -d -o root -g root -m 0755" in canary
    assert 'sudo /usr/bin/dd of="$model_stage"' in canary
    assert "iflag=fullblock,nofollow" in canary
    assert "oflag=excl,nofollow" in canary
    assert 'sudo /usr/bin/chmod 0444 "$model_stage"' in canary
    assert (
        'test "$model_host_dir" = "/store-fast/hapax-models/sha256/$expected_model_sha256"'
        in canary
    )
    assert '--mount "type=bind,src=$model_host_dir,dst=/models,readonly"' in canary
    assert "--memory 4G --memory-swap 6G" in canary
    assert 'test "$memory" = 4294967296' in canary
    assert 'test "$memory_swap" = 6442450944' in canary
    assert "'requests=24'" in canary
    assert "'workers=8'" in canary
    assert 'test "$before_state" = "$after_state"' in canary
    assert 'test "$before_oom" = "$after_oom"' in canary
    assert 'test "$memory_peak" -le 3221225472' in canary
    assert 'test "$swap_peak" -le 1073741824' in canary
    assert '--cidfile "$canary_cidfile"' in canary
    assert 'docker ps -aq --no-trunc --filter "id=$1"' in canary
    name_check = "observed_name=\"$(docker inspect --format '{{.Name}}'"
    assert "canary ID/name mismatch; refusing container stop" in canary
    assert canary.index(name_check) < canary.index('docker stop "$id"')
    assert 'docker stop "$id"' in canary
    assert 'managed_ids="$(docker ps -aq' in canary
    assert 'read -r memory memory_swap oom_kill_disable extra <<< "$limit_fields"' in canary
    assert 'systemctl --user show "$unit" -p ActiveState --value' in canary
    assert "/usr/bin/ss -H -ltn 'sport = :15001'" in canary
    preflight = "local-judge cap canary preflight passed"
    assert canary.index(preflight) < canary.index("trap on_exit EXIT")
    assert canary.index(preflight) < canary.index('systemctl --user stop "$unit"')
    assert "not restoring $unit because disposable-container absence is unproven" in canary
    assert "next action: inspect $canary_name and the bound ID" in canary
    assert 'canary_receipt="$canary_receipt_root/$candidate_sha.env"' in canary
    assert '"candidate_sha=$candidate_sha"' in canary
    assert '"memory_peak_bytes=$memory_peak"' in canary
    assert '"$image_id" \\' in canary
    assert text.index(canary_marker) < text.index('release_verify "$sha"')
    assert "a skipped or incomplete staging canary is rejected before" in " ".join(text.split())


def test_local_judge_activation_is_separately_authority_gated() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    marker = "activation_phase=restart"
    start = text.rfind("```bash", 0, text.index(marker))
    end = text.index("```", text.index(marker))
    activation = text[start:end]

    assert "--verify-runtime-authority-for-release" in activation
    assert "runtime:systemd-user:daemon-reload" in activation
    assert "runtime:systemd-user:enable:hapax-local-judge.service" in activation
    assert "runtime:systemd-user:restart:hapax-local-judge.service" in activation
    assert "runtime:state:write-local-judge-activation-result" in activation
    assert "systemd/units/hapax-local-judge.service" not in activation
    assert "--verify-local-judge-cap-receipt" in activation
    assert activation.index("--verify-local-judge-cap-receipt") < activation.index(marker)
    assert 'account_home="$(/usr/bin/getent passwd' in activation
    assert "/usr/bin/env -i" in activation
    assert "/usr/bin/bash --noprofile --norc -p -s" in activation
    assert 'release_git cat-file blob "$verifier_oid"' in activation
    assert 'test "$(release_git rev-parse --verify \'HEAD^{commit}\')" = "$sha"' in activation
    assert 'authority_check="$HOME/.local/bin/hapax-post-merge-deploy"' not in activation
    assert '[[ "$exec_start" == *"argv[]=/usr/bin/env -i "* ]]' in activation
    assert "--host=unix:///var/run/docker.sock --config=" in activation
    assert "/hapax-local-judge/docker-config run " in activation
    assert '[[ "$exec_start" == *" --memory 4G "* ]]' in activation
    assert '[[ "$exec_start" == *" --memory-swap 6G "* ]]' in activation
    assert "--fail --silent --show-error --max-time 30" in activation
    assert "partial_success" in activation
    assert "phase=$activation_phase" in activation
    assert "inspect-service-and-journal-then-rerun-authorized-fence" in activation


def _local_judge_activation_inner() -> str:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    delimiter = "HAPAX_LOCAL_JUDGE_ACTIVATION"
    start = text.index(f"<<'{delimiter}'\n") + len(f"<<'{delimiter}'\n")
    end = text.index(f"\n{delimiter}\n", start)
    return text[start:end]


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _activation_release(tmp_path: Path, verifier_source: str) -> tuple[Path, str]:
    home = tmp_path / "account-home"
    staging = tmp_path / "release-staging"
    script = staging / "scripts" / "hapax-post-merge-deploy"
    script.parent.mkdir(parents=True)
    _write_executable(script, verifier_source)
    subprocess.run(["/usr/bin/git", "init", "-q", str(staging)], check=True)
    subprocess.run(
        ["/usr/bin/git", "-C", str(staging), "config", "user.name", "Activation Test"],
        check=True,
    )
    subprocess.run(
        ["/usr/bin/git", "-C", str(staging), "config", "user.email", "activation@test.invalid"],
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
    releases = home / ".cache" / "hapax" / "source-activation" / "releases"
    releases.mkdir(parents=True)
    release = releases / sha
    staging.rename(release)
    (releases.parent / "worktree").symlink_to(release)
    return home, sha


def _activation_command(path: Path, body: str) -> Path:
    _write_executable(path, "#!/bin/bash\nset -euo pipefail\n" + body)
    return path


def _run_activation_inner(
    home: Path,
    inner: str,
    commands: tuple[Path, Path, Path, Path],
) -> subprocess.CompletedProcess[str]:
    runtime_task = home / "runtime-task.md"
    runtime_task.write_text("fixture runtime authority\n", encoding="utf-8")
    return subprocess.run(
        [
            "/usr/bin/bash",
            "--noprofile",
            "--norc",
            "-p",
            "-s",
            "--",
            *(str(path) for path in commands),
        ],
        input=inner,
        text=True,
        capture_output=True,
        check=False,
        env={
            "HOME": str(home),
            "USER": "fixture",
            "LOGNAME": "fixture",
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "XDG_RUNTIME_DIR": str(home / "run"),
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={home}/run/bus",
            "HAPAX_RUNTIME_AUTHORITY_TASK": str(runtime_task),
        },
    )


def test_local_judge_activation_launcher_ignores_hostile_home_and_shell_env(
    tmp_path: Path,
) -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    delimiter = "<<'HAPAX_LOCAL_JUDGE_ACTIVATION'\n"
    marker = text.index(delimiter)
    start = text.rfind("```bash\n", 0, marker) + len("```bash\n")
    launcher = text[start : marker + len(delimiter)]
    expected_home = pwd.getpwuid(os.getuid()).pw_dir
    hostile_home = tmp_path / "hostile-home"
    hostile_home.mkdir()
    bash_env_marker = tmp_path / "bash-env-ran"
    bash_env = tmp_path / "hostile-bash-env"
    bash_env.write_text(f"/usr/bin/printf x >> {bash_env_marker}\n", encoding="utf-8")
    probe = (
        launcher
        + f'test "$HOME" = {shlex.quote(expected_home)}\n'
        + 'test -z "${BASH_ENV+x}"\n'
        + "if declare -F hostile >/dev/null; then exit 91; fi\n"
        + "/usr/bin/printf 'clean-home:%s\\n' \"$HOME\"\n"
        + "HAPAX_LOCAL_JUDGE_ACTIVATION\n"
    )

    result = subprocess.run(
        ["/usr/bin/bash", "--noprofile", "--norc"],
        input=probe,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(hostile_home),
            "BASH_ENV": str(bash_env),
            "BASH_FUNC_hostile%%": "() { return 0; }",
            "HAPAX_RUNTIME_AUTHORITY_TASK": str(tmp_path / "runtime-task.md"),
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"clean-home:{expected_home}\n"
    assert bash_env_marker.read_text(encoding="utf-8") == "x"


def test_local_judge_activation_rejects_substituted_checker_and_fabricated_receipt(
    tmp_path: Path,
) -> None:
    verifier = """#!/bin/bash
printf '%s\\n' "$*" >> "$HOME/release-verifier.log"
case "$1" in
  --verify-runtime-authority-for-release) exit 0 ;;
  --verify-local-judge-cap-receipt) exit 42 ;;
  *) exit 64 ;;
esac
"""
    home, sha = _activation_release(tmp_path, verifier)
    malicious_marker = home / "malicious-checker-ran"
    malicious = home / ".local" / "bin" / "hapax-post-merge-deploy"
    malicious.parent.mkdir(parents=True)
    _write_executable(malicious, f"#!/bin/bash\ntouch {malicious_marker}\nexit 0\n")
    receipt = home / ".local" / "state" / "hapax" / "root-required" / "desired-receipts"
    receipt.mkdir(parents=True)
    (receipt / "oom-containment.sha").write_text(f"{sha}\n", encoding="utf-8")
    command_log = home / "systemctl.log"
    commands = (
        _activation_command(tmp_path / "systemctl", f"printf '%s\\n' \"$*\" >> {command_log}\n"),
        _activation_command(tmp_path / "curl", "exit 0\n"),
        _activation_command(tmp_path / "nvidia-smi", "exit 0\n"),
        _activation_command(tmp_path / "oom-audit", "exit 0\n"),
    )

    result = _run_activation_inner(home, _local_judge_activation_inner(), commands)

    assert result.returncode == 42
    assert not malicious_marker.exists()
    assert not command_log.exists()
    invocations = (home / "release-verifier.log").read_text(encoding="utf-8").splitlines()
    assert invocations[0].startswith(f"--verify-runtime-authority-for-release {sha} ")
    assert invocations[1] == f"--verify-local-judge-cap-receipt {sha} installed"


def test_local_judge_activation_records_partial_success_after_restart_failure(
    tmp_path: Path,
) -> None:
    verifier = """#!/bin/bash
printf '%s\\n' "$*" >> "$HOME/release-verifier.log"
exit 0
"""
    home, sha = _activation_release(tmp_path, verifier)
    systemctl_log = home / "systemctl.log"
    systemctl = _activation_command(
        tmp_path / "systemctl",
        f"""printf '%s\\n' "$*" >> {systemctl_log}
if [[ "$*" == *" -p ExecStart --value" ]]; then
  printf 'argv[]=/usr/bin/env -i HOME=/home/hapax /usr/bin/docker --host=unix:///var/run/docker.sock --config=/run/user/1000/hapax-local-judge/docker-config run --name hapax-local-judge --memory 4G --memory-swap 6G image\\n'
fi
""",
    )
    curl = _activation_command(tmp_path / "curl", "exit 22\n")
    nvidia_marker = home / "nvidia-ran"
    audit_marker = home / "audit-ran"
    commands = (
        systemctl,
        curl,
        _activation_command(tmp_path / "nvidia-smi", f"touch {nvidia_marker}\n"),
        _activation_command(tmp_path / "oom-audit", f"touch {audit_marker}\n"),
    )

    result = _run_activation_inner(home, _local_judge_activation_inner(), commands)

    assert result.returncode == 22
    calls = systemctl_log.read_text(encoding="utf-8").splitlines()
    assert "--user daemon-reload" in calls
    assert "--user enable hapax-local-judge.service" in calls
    assert "--user restart hapax-local-judge.service" in calls
    assert not nvidia_marker.exists()
    assert not audit_marker.exists()
    activation_result = (
        home / ".local" / "state" / "hapax" / "local-judge-activation" / "latest.env"
    ).read_text(encoding="utf-8")
    assert f"candidate_sha={sha}\n" in activation_result
    assert "status=partial_success\n" in activation_result
    assert "phase=model_api\n" in activation_result
    assert "service_mutation_started=true\n" in activation_result
    assert (
        "next_action=inspect-service-and-journal-then-rerun-authorized-fence\n" in activation_result
    )
    assert "local-judge activation partial_success" in result.stderr
    assert "phase=model_api" in result.stderr
    assert "next action: inspect" in result.stderr


def test_local_judge_runtime_fences_are_valid_bash() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    markers = (
        'canary_name="hapax-local-judge-cap-canary-$$"',
        'release_verify "$sha"',
        '"$stage/AUTHENTICATED-INSTALL.log"',
        "activation_phase=restart",
        "container=hapax-local-judge",
    )

    for marker in markers:
        marker_index = text.index(marker)
        start = text.rfind("```bash\n", 0, marker_index) + len("```bash\n")
        end = text.index("```", marker_index)
        result = subprocess.run(
            ["bash", "-n"],
            input=text[start:end],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"{marker}: {result.stderr}"


def test_local_judge_runtime_fences_use_structured_active_task_authority() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    authority_fences = {
        'canary_name="hapax-local-judge-cap-canary-$$"': (
            "runtime:docker:pull:",
            "runtime:docker:run-remove:hapax-local-judge-cap-canary",
            "runtime:root-directory:ensure-root-0755:/store-fast/hapax-models",
            "runtime:root-file:stage-content-addressed:/store-fast/hapax-models/sha256/",
            "runtime:state:write-local-judge-cap-receipt",
            "runtime:state:write-remove-canary-scratch:/store-fast/tmp",
            "runtime:systemd-user:stop-restore:hapax-local-judge.service",
        ),
        "activation_phase=restart": (
            "runtime:systemd-user:daemon-reload",
            "runtime:systemd-user:enable:hapax-local-judge.service",
            "runtime:systemd-user:restart:hapax-local-judge.service",
            "runtime:state:write-local-judge-activation-result",
        ),
        "container=hapax-local-judge": (
            "runtime:state:write-remove-managed-recheck:/store-fast/tmp",
            "runtime:workload:run-local-judge-managed-recheck:requests-24:workers-8",
        ),
    }

    for marker, scopes in authority_fences.items():
        marker_index = text.index(marker)
        start = text.rfind("```bash\n", 0, marker_index)
        end = text.index("```", marker_index)
        fence = text[start:end]
        assert "--verify-runtime-authority" in fence
        assert all(scope in fence for scope in scopes)
        assert '"$runtime_task" systemd/units/hapax-local-judge.service' not in fence
        assert "grep -Fqx 'runtime_mutation_authorized: true'" not in fence

    for marker in (
        'release_verify "$sha"',
        '"$stage/AUTHENTICATED-INSTALL.log"',
    ):
        marker_index = text.index(marker)
        start = text.rfind("```bash\n", 0, marker_index)
        end = text.index("```", marker_index)
        fence = text[start:end]
        assert "--verify-runtime-authority" not in fence


def test_local_judge_cap_receipt_is_required_before_install_and_activation() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    install = text.index('release_verify "$sha"')
    activation = text.index("activation_phase=daemon_reload")
    managed = text.index("container=hapax-local-judge")

    assert text.rfind('--verify-local-judge-cap-receipt "$sha" candidate', 0, install) != -1
    assert text.rfind('--verify-local-judge-cap-receipt "$sha" installed', 0, activation) != -1
    assert text.rfind('--verify-local-judge-cap-receipt "$sha" installed', 0, managed) != -1


def test_local_judge_canary_enters_clean_privileged_shell(tmp_path: Path) -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    marker = 'canary_name="hapax-local-judge-cap-canary-$$"'
    start = text.rfind("```bash\n", 0, text.index(marker)) + len("```bash\n")
    end = text.index("```", text.index(marker))
    fence = text[start:end]
    delimiter = "<<'HAPAX_LOCAL_JUDGE_CAP_CANARY'\n"
    launcher = fence.split(delimiter, 1)[0] + delimiter
    bash_env_marker = tmp_path / "bash-env-ran"
    bash_env = tmp_path / "hostile-bash-env"
    bash_env.write_text(
        f"/usr/bin/printf x >> {bash_env_marker}\n",
        encoding="utf-8",
    )
    probe = (
        launcher
        + "if declare -F builtin >/dev/null; then exit 91; fi\n"
        + "if declare -F docker >/dev/null; then exit 92; fi\n"
        + 'test -z "${BASH_ENV+x}"\n'
        + 'test -z "${DOCKER_CONTEXT+x}"\n'
        + "printf 'clean-shell\\n'\n"
        + "HAPAX_LOCAL_JUDGE_CAP_CANARY\n"
    )
    env = {
        **os.environ,
        "BASH_ENV": str(bash_env),
        "BASH_FUNC_builtin%%": "() { return 0; }",
        "BASH_FUNC_docker%%": "() { printf forged; }",
        "DOCKER_CONTEXT": "hostile-context",
        "HAPAX_RUNTIME_AUTHORITY_TASK": str(tmp_path / "runtime-task.md"),
    }

    result = subprocess.run(
        ["/usr/bin/bash", "--noprofile", "--norc"],
        input=probe,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "clean-shell\n"
    assert bash_env_marker.read_text(encoding="utf-8") == "x"


def test_local_judge_candidate_verifier_clears_bash_env_and_functions(
    tmp_path: Path,
) -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    verify_start = text.index("candidate_verify() {")
    verify_end = text.index("\n}\n", verify_start) + len("\n}\n")
    workload_start = text.index("candidate_workload() {")
    workload_end = text.index("\n}\n", workload_start) + len("\n}\n")
    function_source = text[verify_start:verify_end] + text[workload_start:workload_end]
    workload_source = (
        'if [ -n "${BASH_ENV+x}" ]; then exit 93; fi\n'
        "if declare -F hostile >/dev/null; then exit 94; fi\n"
        "printf 'candidate-clean:%s\\n' \"$1\"\n"
    )
    bash_env_marker = tmp_path / "bash-env-ran"
    bash_env = tmp_path / "hostile-bash-env"
    bash_env.write_text(
        f"/usr/bin/printf x >> {bash_env_marker}\n",
        encoding="utf-8",
    )
    script = f"""
candidate_git() {{
  test "$1" = cat-file
  test "$2" = blob
  test "$3" = "$verifier_oid"
  /usr/bin/printf %s "$TEST_WORKLOAD_SOURCE"
}}
verifier_oid={"a" * 40}
runtime_task=/tmp/runtime-task.md
repo=/tmp/release
DOCKER_HOST=unix:///var/run/docker.sock
XDG_RUNTIME_DIR=/tmp/runtime
DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/runtime/bus
{function_source}
candidate_workload probe
"""

    result = subprocess.run(
        ["/usr/bin/bash", "--noprofile", "--norc"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "BASH_ENV": str(bash_env),
            "BASH_FUNC_hostile%%": "() { printf forged; }",
            "TEST_WORKLOAD_SOURCE": workload_source,
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "candidate-clean:probe\n"
    assert bash_env_marker.read_text(encoding="utf-8") == "x"


@pytest.mark.parametrize(
    ("probe_output", "probe_rc", "expected_rc", "stderr_fragment"),
    (
        ("", 0, 0, ""),
        ("LISTEN 0 128 127.0.0.1:15001 0.0.0.0:*\n", 0, 1, "occupied"),
        ("", 7, 1, "cannot prove"),
    ),
    ids=("free", "occupied", "probe-error"),
)
def test_local_judge_port_preflight_fails_closed(
    tmp_path: Path,
    probe_output: str,
    probe_rc: int,
    expected_rc: int,
    stderr_fragment: str,
) -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    start = text.index('if ! port_probe="')
    end = text.index("printf 'local-judge cap canary preflight passed", start)
    source = text[start:end].replace("/usr/bin/ss", '"$TEST_SS"')
    fake_ss = tmp_path / "ss"
    fake_ss.write_text(
        f"#!/usr/bin/bash\nprintf '%s' {probe_output!r}\nexit {probe_rc}\n",
        encoding="utf-8",
    )
    fake_ss.chmod(0o755)

    result = subprocess.run(
        ["/usr/bin/bash", "--noprofile", "--norc"],
        input=source,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "TEST_SS": str(fake_ss)},
    )

    assert result.returncode == expected_rc, result.stderr
    if stderr_fragment:
        assert stderr_fragment in result.stderr


def _local_judge_predeploy_cleanup_source() -> str:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    marker = text.index('canary_name="hapax-local-judge-cap-canary-$$"')
    start = text.index("canary_id_absent() {", marker)
    end = text.index("on_exit()", start)
    return text[start:end]


def _local_judge_predeploy_exit_source() -> str:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    marker = text.index('canary_name="hapax-local-judge-cap-canary-$$"')
    start = text.index("canary_id_absent() {", marker)
    end_marker = "trap 'exit 143' TERM"
    end = text.index(end_marker, start) + len(end_marker)
    return text[start:end]


def test_local_judge_cleanup_restores_unit_only_after_proven_absence(tmp_path: Path) -> None:
    container_id = "a" * 64
    cleanup_source = _local_judge_predeploy_cleanup_source()
    for failure in (
        "none",
        "already-absent",
        "stop",
        "inspect",
        "invalid-cidfile",
        "foreign-cidfile",
    ):
        case_dir = tmp_path / failure
        case_dir.mkdir()
        cidfile = case_dir / "canary.cid"
        cidfile.write_text(container_id if failure != "invalid-cidfile" else "not-an-id")
        results = case_dir / "results.jsonl"
        results.write_text("result\n")
        calls = case_dir / "calls"
        calls.write_text("")
        script = f"""
set -u
canary_cidfile="$TEST_CIDFILE"
results="$TEST_RESULTS"
canary_name=cap-cleanup-test
canary_id=""
unit=hapax-local-judge.service
was_active=active
failure="$TEST_FAILURE"
stopped=0
docker() {{
  case "$1" in
    inspect)
      if [ "${{2:-}}" = --format ]; then
        if [ "$failure" = inspect ] || [ "$failure" = already-absent ]; then return 1; fi
        if [ "$failure" = foreign-cidfile ]; then
          printf '/foreign-container\n'
        else
          printf '/%s\n' "$canary_name"
        fi
        return 0
      fi
      if [ "$failure" = none ] && [ "$stopped" -eq 1 ]; then return 1; fi
      return 0
      ;;
    stop)
      printf '%s\n' "docker stop $2" >> "$TEST_CALLS"
      if [ "$failure" = stop ]; then return 1; fi
      stopped=1
      return 0
      ;;
    ps)
      if [ "$failure" != none ] && [ "$failure" != already-absent ]; then
        printf '%s\n' '{container_id}'
      fi
      return 0
      ;;
    *) return 2 ;;
  esac
}}
systemctl() {{
  if [ "${{1:-}}" = --user ] && [ "${{2:-}}" = start ]; then
    printf '%s\n' "systemctl $*" >> "$TEST_CALLS"
    return 0
  fi
  if [ "${{1:-}}" = --user ] && [ "${{2:-}}" = show ]; then
    printf '%s\n' active
    return 0
  fi
  return 2
}}
{cleanup_source}
set +e
cleanup_canary
cleanup_rc=$?
set -e
printf 'cleanup_rc=%s\n' "$cleanup_rc"
"""
        result = subprocess.run(
            ["bash"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "TEST_CIDFILE": str(cidfile),
                "TEST_RESULTS": str(results),
                "TEST_CALLS": str(calls),
                "TEST_FAILURE": failure,
            },
        )

        assert result.returncode == 0, result.stderr
        call_text = calls.read_text()
        assert not results.exists()
        if failure in {"none", "already-absent"}:
            assert "cleanup_rc=0" in result.stdout
            assert "systemctl --user start hapax-local-judge.service" in call_text
            assert not cidfile.exists()
        else:
            assert "cleanup_rc=1" in result.stdout
            assert "systemctl --user start" not in call_text
            assert cidfile.exists()
            assert "not restoring hapax-local-judge.service" in result.stderr
            assert "next action:" in result.stderr
            if failure == "foreign-cidfile":
                assert "docker stop" not in call_text
                assert "canary ID/name mismatch" in result.stderr
            if failure == "inspect":
                assert "docker stop" not in call_text
                assert "cannot prove canary ID absence" in result.stderr


def test_local_judge_cleanup_ignores_cidfile_substitution_after_id_binding(
    tmp_path: Path,
) -> None:
    container_id = "a" * 64
    foreign_id = "b" * 64
    cleanup_source = _local_judge_predeploy_cleanup_source()
    cidfile = tmp_path / "canary.cid"
    cidfile.write_text(foreign_id)
    results = tmp_path / "results.jsonl"
    results.write_text("result\n")
    calls = tmp_path / "calls"
    calls.write_text("")
    script = f"""
set -u
canary_cidfile="$TEST_CIDFILE"
results="$TEST_RESULTS"
canary_name=cap-cleanup-test
canary_id="$TEST_CONTAINER_ID"
unit=hapax-local-judge.service
was_active=active
stopped=0
docker() {{
  target="${{@: -1}}"
  case "$1" in
    inspect)
      if [ "${{2:-}}" = --format ]; then
        if [ "$target" = "$TEST_CONTAINER_ID" ]; then
          printf '/%s\n' "$canary_name"
        else
          printf '/foreign-container\n'
        fi
        return 0
      fi
      if [ "$target" = "$TEST_CONTAINER_ID" ] && [ "$stopped" -eq 1 ]; then
        return 1
      fi
      return 0
      ;;
    stop)
      printf '%s\n' "docker stop $2" >> "$TEST_CALLS"
      stopped=1
      return 0
      ;;
    ps) return 0 ;;
    *) return 2 ;;
  esac
}}
systemctl() {{
  if [ "${{1:-}}" = --user ] && [ "${{2:-}}" = start ]; then
    printf '%s\n' "systemctl $*" >> "$TEST_CALLS"
    return 0
  fi
  if [ "${{1:-}}" = --user ] && [ "${{2:-}}" = show ]; then
    printf '%s\n' active
    return 0
  fi
  return 2
}}
{cleanup_source}
cleanup_canary
"""
    result = subprocess.run(
        ["bash"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "TEST_CIDFILE": str(cidfile),
            "TEST_RESULTS": str(results),
            "TEST_CALLS": str(calls),
            "TEST_CONTAINER_ID": container_id,
        },
    )

    assert result.returncode == 0, result.stderr
    call_lines = calls.read_text().splitlines()
    assert f"docker stop {container_id}" in call_lines
    assert f"docker stop {foreign_id}" not in call_lines
    assert "systemctl --user start hapax-local-judge.service" in call_lines
    assert not cidfile.exists()
    assert not results.exists()


def test_local_judge_cleanup_retries_after_interrupt(tmp_path: Path) -> None:
    container_id = "a" * 64
    cidfile = tmp_path / "canary.cid"
    cidfile.write_text(container_id)
    results = tmp_path / "results.jsonl"
    results.write_text("result\n")
    calls = tmp_path / "calls"
    calls.write_text("")
    script = f"""
set -eu
canary_cidfile="$TEST_CIDFILE"
results="$TEST_RESULTS"
canary_name=cap-cleanup-test
canary_id="$TEST_CONTAINER_ID"
unit=hapax-local-judge.service
was_active=active
stopped=0
stop_attempts=0
docker() {{
  case "$1" in
    inspect)
      if [ "${{2:-}}" = --format ]; then
        printf '/%s\n' "$canary_name"
        return 0
      fi
      if [ "$stopped" -eq 1 ]; then return 1; fi
      return 0
      ;;
    stop)
      stop_attempts=$((stop_attempts + 1))
      printf '%s\n' "docker stop $2" >> "$TEST_CALLS"
      if [ "$stop_attempts" -eq 1 ]; then
        kill -INT "$$"
      fi
      stopped=1
      return 0
      ;;
    ps) return 0 ;;
    *) return 2 ;;
  esac
}}
systemctl() {{
  if [ "${{1:-}}" = --user ] && [ "${{2:-}}" = start ]; then
    printf '%s\n' "systemctl $*" >> "$TEST_CALLS"
    return 0
  fi
  if [ "${{1:-}}" = --user ] && [ "${{2:-}}" = show ]; then
    printf '%s\n' active
    return 0
  fi
  return 2
}}
{_local_judge_predeploy_exit_source()}
cleanup_canary
"""
    result = subprocess.run(
        ["bash"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "TEST_CIDFILE": str(cidfile),
            "TEST_RESULTS": str(results),
            "TEST_CALLS": str(calls),
            "TEST_CONTAINER_ID": container_id,
        },
    )

    assert result.returncode == 130, result.stderr
    call_lines = calls.read_text().splitlines()
    assert call_lines.count(f"docker stop {container_id}") == 2
    assert "systemctl --user start hapax-local-judge.service" in call_lines
    assert not cidfile.exists()
    assert not results.exists()


def test_local_judge_exit_cleanup_absorbs_signal_and_retries(tmp_path: Path) -> None:
    container_id = "b" * 64
    cidfile = tmp_path / "canary.cid"
    cidfile.write_text(container_id)
    results = tmp_path / "results.jsonl"
    results.write_text("result\n")
    calls = tmp_path / "calls"
    calls.write_text("")
    script = f"""
set -eu
canary_cidfile="$TEST_CIDFILE"
results="$TEST_RESULTS"
canary_name=cap-cleanup-test
canary_id="$TEST_CONTAINER_ID"
unit=hapax-local-judge.service
was_active=active
stopped=0
stop_attempts=0
docker() {{
  case "$1" in
    inspect)
      if [ "${{2:-}}" = --format ]; then
        printf '/%s\n' "$canary_name"
        return 0
      fi
      if [ "$stopped" -eq 1 ]; then return 1; fi
      return 0
      ;;
    stop)
      stop_attempts=$((stop_attempts + 1))
      printf '%s\n' "docker stop $2" >> "$TEST_CALLS"
      if [ "$stop_attempts" -eq 1 ]; then
        kill -INT "$$"
        return 130
      fi
      stopped=1
      return 0
      ;;
    ps)
      if [ "$stopped" -eq 0 ]; then printf '%s\n' '{container_id}'; fi
      return 0
      ;;
    *) return 2 ;;
  esac
}}
systemctl() {{
  if [ "${{1:-}}" = --user ] && [ "${{2:-}}" = start ]; then
    printf '%s\n' "systemctl $*" >> "$TEST_CALLS"
    return 0
  fi
  if [ "${{1:-}}" = --user ] && [ "${{2:-}}" = show ]; then
    printf '%s\n' active
    return 0
  fi
  return 2
}}
sleep() {{
  kill -TERM "$$"
  return 143
}}
{_local_judge_predeploy_exit_source()}
exit 0
"""
    result = subprocess.run(
        ["bash"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "TEST_CIDFILE": str(cidfile),
            "TEST_RESULTS": str(results),
            "TEST_CALLS": str(calls),
            "TEST_CONTAINER_ID": container_id,
        },
    )

    assert result.returncode == 143, result.stderr
    call_lines = calls.read_text().splitlines()
    assert call_lines.count(f"docker stop {container_id}") == 2
    assert "systemctl --user start hapax-local-judge.service" in call_lines
    assert not cidfile.exists()
    assert not results.exists()


def _local_judge_runtime_canary() -> str:
    text = (REPO_ROOT / "docs" / "runbooks" / "local-judge-stack.md").read_text()
    marker = text.index("container=hapax-local-judge")
    start = text.rfind("```bash", 0, marker)
    end = text.index("```", marker)
    return text[start:end]


def test_local_judge_runtime_canary_fails_fast() -> None:
    canary = _local_judge_runtime_canary()
    assert canary.index("set -euo pipefail") < canary.index("container=hapax-local-judge")
    assert 'account_home="$(/usr/bin/getent passwd' in canary
    assert "/usr/bin/env -i" in canary
    assert "HAPAX_LOCAL_JUDGE_MANAGED_RECHECK" in canary
    assert 'repo_alias="$HOME/.cache/hapax/source-activation/worktree"' in canary
    assert 'repo="$(/usr/bin/realpath -e -- "$repo_alias")"' in canary
    assert 'release_root="$HOME/.cache/hapax/source-activation/releases"' in canary
    assert '[[ "${repo##*/}" =~ ^[0-9a-f]{40}$ ]]' in canary
    assert 'release_git cat-file blob "$verifier_oid"' in canary
    assert "--verify-runtime-authority-for-release" in canary
    assert "--verify-local-judge-cap-receipt" in canary
    assert 'authority_check="$HOME/.local/bin/hapax-post-merge-deploy"' not in canary
    assert '/usr/bin/systemctl --user show "$unit" -p NeedDaemonReload --value' in canary
    assert '/usr/bin/systemctl --user show "$unit" -p FragmentPath --value' in canary
    assert '/usr/bin/systemctl --user show "$unit" -p DropInPaths --value' in canary
    assert '/usr/bin/systemctl --user show "$unit" -p ExecStart --value' in canary
    assert '"argv[]=/usr/bin/env -i "' in canary
    assert "--host=unix:///var/run/docker.sock --config=" in canary
    assert "/hapax-local-judge/docker-config run " in canary
    assert '" --memory 4G "' in canary
    assert '" --memory-swap 6G "' in canary
    assert "{{json .HostConfig.OomKillDisable}}" in canary
    assert '== null || "$oom_kill_disable" == false' in canary
    assert "--run-local-judge-cap-workload http://127.0.0.1:5001" in canary
    assert "run_verifierbench.py" not in canary
    assert "length == 24" in canary
    assert 'has("error")' in canary
    assert 'has("pred")' in canary
    assert ".error == null" in canary
    assert '.pred == "A" or .pred == "B" or .pred == "C"' in canary
    assert 'test "$before_state" = "$after_state"' in canary
    assert 'test "$before_oom" = "$after_oom"' in canary
    assert 'results="/store-fast/tmp/' in canary
    assert 'test "$memory_peak" -le 3221225472' in canary
    assert 'test "$swap_peak" -le 1073741824' in canary


def test_local_judge_runtime_canary_executes_jsonl_acceptance_predicate() -> None:
    jq = shutil.which("jq")
    assert jq is not None
    match = re.search(r"jq -e -s '([^']+)'", _local_judge_runtime_canary())
    assert match is not None
    predicate = match.group(1)

    valid = [{"pred": ("A", "B", "C")[index % 3], "error": None} for index in range(24)]
    cases = {
        "complete": ("\n".join(json.dumps(row) for row in valid), True),
        "partial": ("\n".join(json.dumps(row) for row in valid[:-1]), False),
        "errored": (
            "\n".join(json.dumps(row) for row in [*valid[:-1], {"pred": "A", "error": "timeout"}]),
            False,
        ),
        "invalid-prediction": (
            "\n".join(json.dumps(row) for row in [*valid[:-1], {"pred": "D", "error": None}]),
            False,
        ),
        "missing-error-key": (
            "\n".join(json.dumps(row) for row in [*valid[:-1], {"pred": "A"}]),
            False,
        ),
        "malformed-json": ("\n".join(json.dumps(row) for row in valid[:-1]) + '\n{"pred":', False),
    }

    for name, (payload, should_pass) in cases.items():
        result = subprocess.run(
            [jq, "-e", "-s", predicate],
            input=f"{payload}\n",
            text=True,
            capture_output=True,
            check=False,
        )
        assert (result.returncode == 0) is should_pass, (
            f"{name}: rc={result.returncode} stderr={result.stderr}"
        )
