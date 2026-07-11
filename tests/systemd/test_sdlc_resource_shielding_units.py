"""Static pins for the SDLC resource-shielding units (the anti-kill scheme).

Shield real-time workloads (audio data-loops, the coordinator) from the SDLC
fleet via a cpu.idle slice + an audio-core cpuset fence. These pins keep the
load-bearing directives from silently regressing.
"""

from __future__ import annotations

import ast
import re
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
    assert "config/earlyoom/default" in body
    assert "app_slice_value MemoryHigh" in body
    assert "apply_system_runtime_memory user-1000.slice" in body
    assert "apply_system_runtime_memory user@1000.service" in body
    assert "set-property --runtime app.slice" in body
    assert "set-property --runtime session.slice" in body
    assert "verify_system_unit_runtime_memory user-1000.slice" in body
    assert "verify_app_slice_runtime" in body
    assert "verify_session_slice_runtime" in body
