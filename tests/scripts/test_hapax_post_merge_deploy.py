"""Path-coverage tests for ``scripts/hapax-post-merge-deploy``."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-post-merge-deploy"
ROOT_REQUIRED_AUDIT = REPO_ROOT / "scripts" / "hapax-root-required-deploy-audit"
OOM_PACKAGE_MANIFEST = (REPO_ROOT / "config/root-required/oom-containment.files").read_text(
    encoding="utf-8"
)
APCUPSD_PACKAGE_MANIFEST = (
    REPO_ROOT / "config/root-required/apcupsd-power-alerts.files"
).read_text(encoding="utf-8")
RECOVERY_BUNDLE_SOURCE_FILES = {
    "scripts/hapax-p0-incident-intake": "#!/usr/bin/env bash\necho intake\n",
    "scripts/hapax-coord-deploy": "#!/usr/bin/env bash\necho coord deploy\n",
    "shared/__init__.py": "",
    "shared/jsonl_append.py": "def append_jsonl(*_args, **_kwargs):\n    pass\n",
    "shared/p0_incident_intake.py": "def main():\n    return 0\n",
}
P0_USER_OOM_DROPINS = {
    relative: (
        "[Service]\nOOMScoreAdjust=100\n"
        f"ExecStartPost=-/usr/local/bin/hapax-oom-score-trigger {unit}\n"
    )
    for relative, unit in {
        "systemd/units/pipewire.service.d/oom-protect.conf": "pipewire.service",
        "systemd/units/pipewire-pulse.service.d/oom-protect.conf": "pipewire-pulse.service",
        "systemd/units/wireplumber.service.d/oom-protect.conf": "wireplumber.service",
        "systemd/units/hapax-daimonion.service.d/oom-protect.conf": "hapax-daimonion.service",
        "systemd/units/studio-compositor.service.d/oom-protect.conf": "studio-compositor.service",
        "systemd/units/hapax-imagination.service.d/oom-protect.conf": "hapax-imagination.service",
    }.items()
}
P0_OOM_AUDIT_FILES = {
    "scripts/hapax-oom-policy-audit": "#!/usr/bin/env python3\n",
    "scripts/hapax-root-required-deploy-audit": "#!/usr/bin/env bash\n",
    "systemd/units/hapax-oom-policy-audit.service": (
        "[Unit]\nDescription=OOM audit\n[Service]\nType=oneshot\n"
        "ExecStart=/usr/local/sbin/hapax-oom-policy-audit --json\n"
    ),
    "systemd/units/hapax-oom-policy-audit.timer": (
        "[Unit]\nDescription=OOM audit timer\n[Timer]\nOnUnitActiveSec=5min\n"
    ),
    "systemd/units/hapax-root-required-deploy-audit.service": (
        "[Unit]\nDescription=Root deploy audit\n[Service]\nType=oneshot\n"
        "ExecStart=/usr/local/sbin/hapax-root-required-deploy-audit\n"
    ),
    "systemd/units/hapax-root-required-deploy-audit.timer": (
        "[Unit]\nDescription=Root deploy audit timer\n[Timer]\nOnUnitActiveSec=10min\n"
    ),
}
ROOT_AUDIT_SOURCE_FILES = {
    "config/root-required/oom-containment.files": OOM_PACKAGE_MANIFEST,
    "config/root-required/apcupsd-power-alerts.files": APCUPSD_PACKAGE_MANIFEST,
    "scripts/install-p0-oom-containment": "#!/usr/bin/env bash\n",
    "config/root-required/hapax-oom-score-enforce.sudoers": (
        "hapax ALL=(root) NOPASSWD: /usr/local/sbin/hapax-oom-score-enforce --apply-unit pipewire.service\n"
    ),
    "scripts/install-apcupsd-power-alerts": "#!/usr/bin/env bash\n",
    "scripts/hapax-oom-score-enforce": "#!/usr/bin/env bash\necho enforcer\n",
    "scripts/hapax-oom-score-trigger": "#!/usr/bin/env bash\necho trigger\n",
    "scripts/hapax-root-failure-intake": "#!/usr/bin/env bash\necho root failure\n",
    **P0_OOM_AUDIT_FILES,
    "config/earlyoom/default": 'EARLYOOM_ARGS="--ignore recovery"\n',
    "systemd/system/system.slice.d/oom-containment.conf": (
        "[Slice]\nMemoryHigh=infinity\nMemoryMax=infinity\nMemorySwapMax=infinity\n"
        "MemoryLow=24G\nMemoryMin=12G\n"
    ),
    "systemd/system/user.slice.d/oom-containment.conf": (
        "[Slice]\nMemoryHigh=infinity\nMemoryMax=infinity\nMemorySwapMax=infinity\n"
        "MemoryLow=16G\nMemoryMin=8G\n"
    ),
    "systemd/system/user-1000.slice.d/oom-containment.conf": (
        "[Slice]\nMemoryHigh=80G\nMemoryMax=96G\nMemorySwapMax=8G\nMemoryLow=16G\nMemoryMin=8G\n"
    ),
    "systemd/system/user@1000.service.d/oom.conf": "[Service]\nOOMScoreAdjust=100\n",
    "systemd/system/apcupsd.service.d/oom-protect.conf": "[Service]\nOOMScoreAdjust=-900\n",
    "systemd/system/systemd-logind.service.d/oom-protect.conf": (
        "[Service]\nOOMScoreAdjust=-800\n"
    ),
    "systemd/system/systemd-resolved.service.d/oom-protect.conf": (
        "[Service]\nOOMScoreAdjust=-800\n"
    ),
    "systemd/system/systemd-timesyncd.service.d/oom-protect.conf": (
        "[Service]\nOOMScoreAdjust=-800\n"
    ),
    "systemd/system/NetworkManager.service.d/oom-protect.conf": (
        "[Service]\nOOMScoreAdjust=-800\n"
    ),
    "systemd/system/dbus-broker.service.d/oom-protect.conf": "[Service]\nOOMScoreAdjust=-900\n",
    "systemd/system/sshd.service.d/oom-protect.conf": (
        "[Service]\nOOMScoreAdjust=0\nOOMPolicy=continue\n"
    ),
    "systemd/units/hapax-root-failure-intake@.service": (
        "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\n"
    ),
    "systemd/units/hapax-oom-score-enforce.service": (
        "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\n"
    ),
    "systemd/units/hapax-oom-score-enforce.timer": (
        "[Unit]\n# Hapax-Install-Scope: system\n[Timer]\nOnUnitActiveSec=30s\n"
    ),
    "systemd/units/app.slice.d/oom-containment.conf": (
        "[Slice]\nMemoryHigh=72G\nMemoryMax=88G\nMemorySwapMax=8G\nMemoryLow=16G\nMemoryMin=8G\n"
    ),
    **P0_USER_OOM_DROPINS,
    "config/apcupsd/apcupsd.conf": (
        "## apcupsd.conf v1.1 ##\nUPSNAME podium\nBATTERYLEVEL 20\nMINUTES 5\nTIMEOUT 0\n"
    ),
    "config/apcupsd/hapax-power-event.py": "#!/usr/bin/env python3\n",
    "config/apcupsd/onbattery": "#!/usr/bin/env bash\n",
    "config/apcupsd/offbattery": "#!/usr/bin/env bash\n",
    "config/apcupsd/doshutdown": "#!/usr/bin/env bash\n",
    "config/upower/90-hapax-apcupsd-owner.conf": (
        "[UPower]\nAllowRiskyCriticalPowerAction=true\nCriticalPowerAction=Ignore\n"
    ),
    "systemd/logrotate.d/hapax-ups-power-events": "/var/log/hapax/ups-power-events.jsonl {}\n",
}


def _coverage(paths: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), "--report-coverage-stdin"],
        input="\n".join(paths) + "\n",
        text=True,
        capture_output=True,
        check=False,
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _repo_with_merge_commit(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    _git(repo, "switch", "-c", "trace-branch")
    script_path = repo / "scripts" / "hapax-demo"
    script_path.parent.mkdir()
    script_path.write_text("#!/bin/sh\necho demo\n", encoding="utf-8")
    _git(repo, "add", "scripts/hapax-demo")
    _git(repo, "commit", "-m", "add deployable script")
    _git(repo, "switch", "main")
    main_script_path = repo / "scripts" / "hapax-main-only"
    main_script_path.parent.mkdir(exist_ok=True)
    main_script_path.write_text("#!/bin/sh\necho main\n", encoding="utf-8")
    _git(repo, "add", "scripts/hapax-main-only")
    _git(repo, "commit", "-m", "add main-only deployable script")
    _git(repo, "merge", "--no-ff", "trace-branch", "-m", "merge trace branch")
    return repo, _git(repo, "rev-parse", "HEAD")


def _repo_with_linear_commit(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    for relative, body in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        if body.startswith("#!"):
            path.chmod(0o755)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add deployable files")
    return repo, _git(repo, "rev-parse", "HEAD")


def _repo_with_recovery_installer_then_linear_commit(
    tmp_path: Path, files: dict[str, str]
) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    installer = repo / "scripts" / "hapax-recovery-plane-install"
    installer.parent.mkdir(parents=True)
    installer.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_RECOVERY_INSTALL_CALLS"\n',
        encoding="utf-8",
    )
    installer.chmod(0o755)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md", "scripts/hapax-recovery-plane-install")
    _git(repo, "commit", "-m", "base with recovery installer")
    for relative, body in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add deployable files")
    return repo, _git(repo, "rev-parse", "HEAD")


def _repo_with_recovery_bundle_drift_then_unrelated_commit(
    tmp_path: Path,
) -> tuple[Path, str, str, dict[str, str]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    installer = repo / "scripts" / "hapax-recovery-plane-install"
    installer.parent.mkdir(parents=True)
    installer.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_RECOVERY_INSTALL_CALLS"\n',
        encoding="utf-8",
    )
    installer.chmod(0o755)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    for relative, body in RECOVERY_BUNDLE_SOURCE_FILES.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        if relative.startswith("scripts/"):
            path.chmod(0o755)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base recovery bundle")
    stale_sha = _git(repo, "rev-parse", "HEAD")
    stale_files = dict(RECOVERY_BUNDLE_SOURCE_FILES)

    (repo / "shared" / "p0_incident_intake.py").write_text(
        "def main():\n    return 42\n", encoding="utf-8"
    )
    _git(repo, "add", "shared/p0_incident_intake.py")
    _git(repo, "commit", "-m", "update recovery intake")
    (repo / "docs" / "unrelated.md").parent.mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "unrelated.md").write_text("later unrelated deploy\n", encoding="utf-8")
    _git(repo, "add", "docs/unrelated.md")
    _git(repo, "commit", "-m", "unrelated deploy")
    return repo, _git(repo, "rev-parse", "HEAD"), stale_sha, stale_files


def _recovery_bundle_dest(home: Path) -> Path:
    return home / ".local" / "lib" / "hapax-recovery" / "council" / "current"


def _write_installed_recovery_bundle(dest: Path, source_ref: str, files: dict[str, str]) -> None:
    manifest_files = []
    for relative, body in files.items():
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        mode = "0o755" if relative.startswith("scripts/") else "0o644"
        if relative.startswith("scripts/"):
            target.chmod(0o755)
        manifest_files.append(
            {
                "path": relative,
                "mode": mode,
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
                "bytes": len(body.encode()),
            }
        )
    (dest / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_ref": source_ref,
                "files": manifest_files,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _root_audit_env(
    tmp_path: Path,
    *,
    drift_rel: str | None = None,
    missing_source_rel: str | None = None,
) -> dict[str, str]:
    source_root = tmp_path / "source"
    installed_source = tmp_path / "installed-source"
    root_defer = tmp_path / "no-deferrals"
    state_root = tmp_path / "root-state"
    receipt_root = root_defer / "installed-receipts"
    desired_root = state_root / "desired-receipts"
    system_dir = tmp_path / "etc" / "systemd" / "system"
    apcupsd_dir = tmp_path / "etc" / "apcupsd"
    logrotate_dest = tmp_path / "etc" / "logrotate.d" / "hapax-ups-power-events"
    upower_dest = tmp_path / "etc" / "UPower" / "UPower.conf.d" / "90-hapax-apcupsd-owner.conf"
    enforcer_dest = tmp_path / "sbin" / "hapax-oom-score-enforce"
    trigger_dest = tmp_path / "bin" / "hapax-oom-score-trigger"
    sudoers_dest = tmp_path / "etc" / "sudoers.d" / "hapax-oom-score-enforce"
    root_failure_dest = tmp_path / "sbin" / "hapax-root-failure-intake"
    oom_audit_dest = tmp_path / "sbin" / "hapax-oom-policy-audit"
    root_audit_dest = tmp_path / "sbin" / "hapax-root-required-deploy-audit"
    user_dir = tmp_path / "home" / ".config" / "systemd" / "user"
    earlyoom_dest = tmp_path / "etc" / "default" / "earlyoom"
    fake_systemctl = tmp_path / "root-audit-systemctl"
    fake_systemctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_systemctl.chmod(0o755)
    fake_busctl = tmp_path / "root-audit-busctl"
    fake_busctl.write_text("#!/bin/sh\nprintf 's \\\"Ignore\\\"\\n'\n", encoding="utf-8")
    fake_busctl.chmod(0o755)
    fake_apcaccess = tmp_path / "root-audit-apcaccess"
    fake_apcaccess.write_text(
        "#!/bin/sh\n"
        "printf 'STATUS   : ONLINE\\nMBATTCHG : 20 Percent\\nMINTIMEL : 5 Minutes\\nMAXTIME  : 0 Seconds\\n'\n",
        encoding="utf-8",
    )
    fake_apcaccess.chmod(0o755)
    fake_visudo = tmp_path / "root-audit-visudo"
    fake_visudo.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_visudo.chmod(0o755)
    dests = {
        "scripts/hapax-oom-score-enforce": enforcer_dest,
        "scripts/hapax-oom-score-trigger": trigger_dest,
        "config/root-required/hapax-oom-score-enforce.sudoers": sudoers_dest,
        "scripts/hapax-root-failure-intake": root_failure_dest,
        "scripts/hapax-oom-policy-audit": oom_audit_dest,
        "scripts/hapax-root-required-deploy-audit": root_audit_dest,
        "config/earlyoom/default": earlyoom_dest,
        "systemd/logrotate.d/hapax-ups-power-events": logrotate_dest,
        "config/upower/90-hapax-apcupsd-owner.conf": upower_dest,
    }
    system_units = {
        "systemd/units/hapax-root-failure-intake@.service",
        "systemd/units/hapax-oom-score-enforce.service",
        "systemd/units/hapax-oom-score-enforce.timer",
    }
    for rel in ROOT_AUDIT_SOURCE_FILES:
        if rel.startswith("systemd/system/"):
            dests[rel] = system_dir / rel.removeprefix("systemd/system/")
        elif rel.startswith("systemd/units/"):
            unit_name = rel.removeprefix("systemd/units/")
            if rel in system_units:
                dests[rel] = system_dir / unit_name
            else:
                dests[rel] = user_dir / unit_name
        elif rel.startswith("config/apcupsd/"):
            dests[rel] = apcupsd_dir / rel.removeprefix("config/apcupsd/")
    executable_rels = {
        "scripts/install-p0-oom-containment",
        "scripts/install-apcupsd-power-alerts",
        "scripts/hapax-oom-score-enforce",
        "scripts/hapax-oom-score-trigger",
        "scripts/hapax-root-failure-intake",
        "scripts/hapax-oom-policy-audit",
        "scripts/hapax-root-required-deploy-audit",
        "config/apcupsd/hapax-power-event.py",
        "config/apcupsd/onbattery",
        "config/apcupsd/offbattery",
        "config/apcupsd/doshutdown",
    }
    for rel, body in ROOT_AUDIT_SOURCE_FILES.items():
        source = source_root / rel
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(body, encoding="utf-8")
        if rel in executable_rels:
            source.chmod(0o755)
        if rel != missing_source_rel:
            installed = installed_source / rel
            installed.parent.mkdir(parents=True, exist_ok=True)
            installed.write_text(body, encoding="utf-8")
            if rel in executable_rels:
                installed.chmod(0o755)
        if rel in dests:
            dest = dests[rel]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(("stale\n" if rel == drift_rel else body), encoding="utf-8")
            if rel in executable_rels:
                dest.chmod(0o755)
            elif rel == "config/root-required/hapax-oom-score-enforce.sudoers":
                dest.chmod(0o440)
    _git(source_root, "init", "-b", "main")
    _git(source_root, "config", "user.email", "root-audit@example.test")
    _git(source_root, "config", "user.name", "Root Audit Test")
    _git(source_root, "add", ".")
    _git(source_root, "commit", "-m", "root audit package")
    package_sha = _git(source_root, "rev-parse", "HEAD")
    receipt_root.mkdir(parents=True)
    (receipt_root / "oom-containment.sha").write_text(f"{package_sha}\n", encoding="utf-8")
    (receipt_root / "apcupsd-power-alerts.sha").write_text(f"{package_sha}\n", encoding="utf-8")
    desired_root.mkdir(parents=True)
    (desired_root / "oom-containment.sha").write_text(f"{package_sha}\n", encoding="utf-8")
    (desired_root / "apcupsd-power-alerts.sha").write_text(f"{package_sha}\n", encoding="utf-8")
    return {
        **os.environ,
        "HAPAX_ROOT_REQUIRED_SOURCE_ROOT": str(source_root),
        "HAPAX_ROOT_REQUIRED_STATE_ROOT": str(state_root),
        "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT": str(installed_source),
        "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT": str(receipt_root),
        "HAPAX_ROOT_REQUIRED_DESIRED_RECEIPT_ROOT": str(desired_root),
        "HAPAX_ROOT_REQUIRED_GIT_REPO": str(source_root),
        "HAPAX_OOM_ENFORCER_DEST": str(enforcer_dest),
        "HAPAX_OOM_TRIGGER_DEST": str(trigger_dest),
        "HAPAX_OOM_SUDOERS_DEST": str(sudoers_dest),
        "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(root_failure_dest),
        "HAPAX_OOM_POLICY_AUDIT_DEST": str(oom_audit_dest),
        "HAPAX_ROOT_REQUIRED_AUDIT_DEST": str(root_audit_dest),
        "HAPAX_OOM_EARLYOOM_DEST": str(earlyoom_dest),
        "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(system_dir),
        "HAPAX_OOM_SYSTEMD_USER_DIR": str(user_dir),
        "HAPAX_APCUPSD_DEST": str(apcupsd_dir),
        "HAPAX_APCUPSD_LOGROTATE_DEST": str(logrotate_dest),
        "HAPAX_UPOWER_CONF_DEST": str(upower_dest),
        "HAPAX_ROOT_AUDIT_SYSTEMCTL": str(fake_systemctl),
        "HAPAX_ROOT_AUDIT_BUSCTL": str(fake_busctl),
        "HAPAX_ROOT_AUDIT_APCACCESS": str(fake_apcaccess),
        "HAPAX_ROOT_AUDIT_VISUDO": str(fake_visudo),
        "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(root_defer),
    }


def _repo_with_intake_units_then_preset_commit(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    timer_body = (
        "[Unit]\n"
        "Description=Governed intake timer\n"
        "\n"
        "[Timer]\n"
        "OnUnitActiveSec=60\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    units = repo / "systemd" / "units"
    units.mkdir(parents=True)
    (units / "hapax-request-decompose.timer").write_text(timer_body, encoding="utf-8")
    (units / "hapax-cc-task-offer-ready.timer").write_text(timer_body, encoding="utf-8")
    (units / "hapax-request-decompose.service").write_text(
        "[Unit]\nDescription=Request decomposer\n\n[Service]\nType=oneshot\nExecStart=/bin/true\n",
        encoding="utf-8",
    )
    (units / "hapax-cc-task-offer-ready.service").write_text(
        "[Unit]\nDescription=Offer ready\n\n[Service]\nType=oneshot\nExecStart=/bin/true\n",
        encoding="utf-8",
    )
    _git(repo, "add", "systemd/units")
    _git(repo, "commit", "-m", "base intake timer units")
    preset = repo / "systemd" / "user-preset.d" / "hapax.preset"
    preset.parent.mkdir(parents=True)
    preset.write_text(
        "enable hapax-request-decompose.timer\nenable hapax-cc-task-offer-ready.timer\n",
        encoding="utf-8",
    )
    _git(repo, "add", "systemd/user-preset.d/hapax.preset")
    _git(repo, "commit", "-m", "preset intake timers")
    return repo, _git(repo, "rev-parse", "HEAD")


def _repo_with_intake_timer_missing_service_then_preset_commit(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    units = repo / "systemd" / "units"
    units.mkdir(parents=True)
    (units / "hapax-cc-task-offer-ready.timer").write_text(
        "[Unit]\nDescription=Offer ready timer\n\n[Timer]\nOnUnitActiveSec=300\n\n[Install]\nWantedBy=timers.target\n",
        encoding="utf-8",
    )
    _git(repo, "add", "systemd/units/hapax-cc-task-offer-ready.timer")
    _git(repo, "commit", "-m", "base intake timer without service")
    preset = repo / "systemd" / "user-preset.d" / "hapax.preset"
    preset.parent.mkdir(parents=True)
    preset.write_text("enable hapax-cc-task-offer-ready.timer\n", encoding="utf-8")
    _git(repo, "add", "systemd/user-preset.d/hapax.preset")
    _git(repo, "commit", "-m", "preset intake timer")
    return repo, _git(repo, "rev-parse", "HEAD")


def _repo_with_quake_asset_commit(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    installer = repo / "scripts" / "install-darkplaces-screwm-assets.sh"
    installer.parent.mkdir(parents=True)
    installer.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"${DARKPLACES_GAME_ROOT:-$HOME/.darkplaces}\" "
        '>> "$HAPAX_INSTALL_CALLS"\n',
        encoding="utf-8",
    )
    _git(repo, "add", "scripts/install-darkplaces-screwm-assets.sh")
    _git(repo, "commit", "-m", "base quake installer")
    asset = repo / "assets" / "quake" / "maps" / "screwm.bsp"
    asset.parent.mkdir(parents=True)
    asset.write_text("compiled bsp bytes\n", encoding="utf-8")
    _git(repo, "add", "assets/quake/maps/screwm.bsp")
    _git(repo, "commit", "-m", "update screwm map asset")
    return repo, _git(repo, "rev-parse", "HEAD")


def _repo_with_recovery_bundle_change(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    installer = repo / "scripts" / "hapax-recovery-plane-install"
    installer.parent.mkdir(parents=True)
    installer.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_RECOVERY_INSTALL_CALLS"\n',
        encoding="utf-8",
    )
    installer.chmod(0o755)
    _git(repo, "add", "scripts/hapax-recovery-plane-install")
    _git(repo, "commit", "-m", "base recovery installer")
    shared = repo / "shared" / "p0_incident_intake.py"
    shared.parent.mkdir(parents=True)
    shared.write_text("# changed intake closure\n", encoding="utf-8")
    _git(repo, "add", "shared/p0_incident_intake.py")
    _git(repo, "commit", "-m", "update recovery intake closure")
    return repo, _git(repo, "rev-parse", "HEAD")


def _repo_with_recovery_bundle_missing_installer(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base without recovery installer")
    shared = repo / "shared" / "p0_incident_intake.py"
    shared.parent.mkdir(parents=True)
    shared.write_text("# changed intake closure\n", encoding="utf-8")
    _git(repo, "add", "shared/p0_incident_intake.py")
    _git(repo, "commit", "-m", "update recovery intake closure")
    return repo, _git(repo, "rev-parse", "HEAD")


def _repo_with_recovery_script_change(tmp_path: Path) -> tuple[Path, str]:
    repo, _sha = _repo_with_recovery_bundle_change(tmp_path)
    coord_deploy = repo / "scripts" / "hapax-coord-deploy"
    coord_deploy.write_text("#!/usr/bin/env bash\necho coord deploy changed\n", encoding="utf-8")
    coord_deploy.chmod(0o755)
    _git(repo, "add", "scripts/hapax-coord-deploy")
    _git(repo, "commit", "-m", "update recovery coord deploy")
    return repo, _git(repo, "rev-parse", "HEAD")


def _repo_with_d2_unit_only_change(tmp_path: Path) -> tuple[Path, str, str]:
    unit_path = "systemd/units/notify-failure@.service"
    repo, sha = _repo_with_recovery_installer_then_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "Description=Notify failure\n"
                "ConditionPathExists=%h/.local/lib/hapax-recovery/council/current/scripts/hapax-p0-incident-intake\n"
                "\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=%h/.local/lib/hapax-recovery/council/current/scripts/hapax-p0-incident-intake service-failed %i\n"
            )
        },
    )
    return repo, sha, unit_path


def _fake_systemctl(tmp_path: Path) -> tuple[Path, Path]:
    calls = tmp_path / "systemctl-calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "systemctl"
    fake.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\nexit 0\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return bin_dir, calls


def _fake_systemctl_with_inactive_coord(tmp_path: Path) -> tuple[Path, Path]:
    calls = tmp_path / "systemctl-calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "systemctl"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'case "$*" in\n'
        '    "--user is-active --quiet hapax-coord.service") exit 3 ;;\n'
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return bin_dir, calls


def _fake_audio_safe_restart(
    bin_dir: Path, tmp_path: Path, *, exit_code: int = 0
) -> tuple[Path, Path]:
    calls = tmp_path / "audio-safe-restart-calls.txt"
    fake = bin_dir / "hapax-audio-safe-restart"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_AUDIO_SAFE_RESTART_CALLS"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake, calls


def _fake_systemctl_with_compositor_state(
    tmp_path: Path, *, compositor_active: bool
) -> tuple[Path, Path]:
    """A fake ``systemctl`` whose ``is-active --quiet studio-compositor.service``
    reports the configured liveness; every other call exits 0.

    This lets the deploy reach the audio-safe restart for a changed audio unit
    (the changed unit's own ``is-active`` probe returns 0 → active → restart)
    while the test independently chooses whether a *live broadcast* is on the
    line — i.e. whether ``studio-compositor.service`` is active.
    """
    calls = tmp_path / "systemctl-calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "systemctl"
    # systemctl is-active exits 0 when active, 3 when inactive/dead.
    compositor_rc = 0 if compositor_active else 3
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'case "$*" in\n'
        f"    *is-active*studio-compositor.service*) exit {compositor_rc} ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return bin_dir, calls


def test_dry_run_writes_bounded_post_merge_trace(tmp_path: Path) -> None:
    repo, sha = _repo_with_merge_commit(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        "HAPAX_POST_MERGE_TRACE_MAX_RECORDS": "2",
    }

    for _ in range(3):
        result = subprocess.run(
            [str(SCRIPT), "--dry-run", sha],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        assert "dry-run: post-merge deploy trace written" in result.stdout

    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]

    assert len(records) == 2
    assert records[-1]["event"] == "post_merge_deploy"
    assert records[-1]["sha"] == sha
    assert records[-1]["mode"] == "dry_run"
    assert records[-1]["status"] == "dry_run"
    assert records[-1]["changed_files"] == ["scripts/hapax-demo"]
    assert records[-1]["deploy_groups"]["hapax_scripts"] == ["scripts/hapax-demo"]
    assert records[-1]["manual_deploy_needed"] is True
    assert records[-1]["manual_deploy_executed"] is False
    assert records[-1]["avsdlc"]["gate_point"] == "S9 post-merge production witness"
    assert records[-1]["avsdlc"]["runtime_media_witness_required"] is True
    assert records[-1]["avsdlc"]["runtime_media_witness_groups"] == ["hapax_scripts"]


def test_systemd_coverage_includes_dropins_presets_and_source_overrides() -> None:
    result = _coverage(
        [
            "systemd/units/hapax-datacite-mirror.service",
            "systemd/units/hapax-datacite-mirror.timer",
            "systemd/units/hapax-build-reload.path",
            "systemd/units/hapax-visual-stack.target",
            "systemd/hapax-rebuild-logos.service",
            "systemd/hapax-rebuild-logos.timer",
            "systemd/hapax-build-reload.path",
            "systemd/units/pipewire.service.d/cpu-affinity.conf",
            "systemd/units/app.slice.d/oom-containment.conf",
            "systemd/system/system.slice.d/oom-containment.conf",
            "systemd/system/user.slice.d/oom-containment.conf",
            "systemd/system/user-1000.slice.d/oom-containment.conf",
            "systemd/system/user@1000.service.d/oom.conf",
            "systemd/system/apcupsd.service.d/oom-protect.conf",
            "systemd/user-preset.d/hapax.preset",
            "systemd/scripts/install-units.sh",
            "systemd/logrotate.d/hapax-ups-power-events",
            "systemd/overrides/audio-stability/README.md",
            "systemd/overrides/audio-stability/pipewire-cpu-affinity.conf",
            "systemd/watchdogs/scout-watchdog",
            "systemd/README.md",
            "systemd/expected-timers.yaml",
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "ok: all systemd/** paths" in result.stdout


def test_p0_oom_deploy_uses_installer_without_restart_or_bulk_deferral_clear(
    tmp_path: Path,
) -> None:
    installer_calls = tmp_path / "oom-installer-calls.txt"
    installer_body = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_OOM_INSTALL_CALLS"\n'
    )
    future_manifest_path = "config/earlyoom/future-policy"
    files = {
        "config/root-required/oom-containment.files": (
            OOM_PACKAGE_MANIFEST + f"{future_manifest_path}\n"
        ),
        future_manifest_path: 'FUTURE_EARLYOOM_POLICY="enabled"\n',
        "scripts/install-p0-oom-containment": installer_body,
        "config/root-required/hapax-oom-score-enforce.sudoers": (
            "hapax ALL=(root) NOPASSWD: /usr/local/sbin/hapax-oom-score-enforce --apply-unit pipewire.service\n"
        ),
        "scripts/hapax-oom-score-enforce": "#!/usr/bin/env bash\nexit 0\n",
        "scripts/hapax-oom-score-trigger": "#!/usr/bin/env bash\nexit 0\n",
        "scripts/hapax-root-failure-intake": "#!/usr/bin/env bash\nexit 0\n",
        "config/earlyoom/default": 'EARLYOOM_ARGS="--ignore recovery"\n',
        "systemd/system/system.slice.d/oom-containment.conf": (
            "[Slice]\nMemoryHigh=infinity\nMemoryMax=infinity\nMemorySwapMax=infinity\n"
            "MemoryLow=24G\nMemoryMin=12G\n"
        ),
        "systemd/system/user.slice.d/oom-containment.conf": (
            "[Slice]\nMemoryHigh=infinity\nMemoryMax=infinity\nMemorySwapMax=infinity\n"
            "MemoryLow=16G\nMemoryMin=8G\n"
        ),
        "systemd/system/user-1000.slice.d/oom-containment.conf": (
            "[Slice]\nMemoryHigh=80G\nMemoryMax=96G\nMemorySwapMax=8G\nMemoryLow=16G\nMemoryMin=8G\n"
        ),
        "systemd/system/user@1000.service.d/oom.conf": "[Service]\nOOMScoreAdjust=100\n",
        "systemd/system/apcupsd.service.d/oom-protect.conf": "[Service]\nOOMScoreAdjust=-900\n",
        "systemd/system/systemd-logind.service.d/oom-protect.conf": (
            "[Service]\nOOMScoreAdjust=-800\n"
        ),
        "systemd/system/systemd-resolved.service.d/oom-protect.conf": (
            "[Service]\nOOMScoreAdjust=-800\n"
        ),
        "systemd/system/systemd-timesyncd.service.d/oom-protect.conf": (
            "[Service]\nOOMScoreAdjust=-800\n"
        ),
        "systemd/system/NetworkManager.service.d/oom-protect.conf": (
            "[Service]\nOOMScoreAdjust=-800\n"
        ),
        "systemd/system/dbus-broker.service.d/oom-protect.conf": (
            "[Service]\nOOMScoreAdjust=-900\n"
        ),
        "systemd/system/sshd.service.d/oom-protect.conf": (
            "[Service]\nOOMScoreAdjust=0\nOOMPolicy=continue\n"
        ),
        "systemd/units/hapax-root-failure-intake@.service": (
            "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\n"
        ),
        "systemd/units/hapax-oom-score-enforce.service": (
            "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\nExecStart=/usr/local/sbin/hapax-oom-score-enforce --apply\n"
        ),
        "systemd/units/hapax-oom-score-enforce.timer": (
            "[Unit]\n# Hapax-Install-Scope: system\n[Timer]\nOnBootSec=30s\nOnUnitActiveSec=30s\n"
        ),
        **P0_OOM_AUDIT_FILES,
        "systemd/units/app.slice.d/oom-containment.conf": (
            "[Slice]\nMemoryHigh=72G\nMemoryMax=88G\nMemorySwapMax=8G\nMemoryLow=16G\nMemoryMin=8G\n"
        ),
        **P0_USER_OOM_DROPINS,
    }
    repo, sha = _repo_with_linear_commit(tmp_path, files)
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    defer_dir = tmp_path / "root-required"
    installed_source = tmp_path / "root-state" / "current-source"
    stale_deferral = defer_dir / "old-sha" / "oom-containment"
    stale_deferral.mkdir(parents=True)
    (stale_deferral / "RUNBOOK.txt").write_text("old deferred install\n", encoding="utf-8")
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_OOM_INSTALL_CALLS": str(installer_calls),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_dir),
        "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT": str(installed_source),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "--install --verify-live" in installer_calls.read_text(encoding="utf-8")
    assert stale_deferral.exists(), (
        "only an explicit staged RUNBOOK invocation may drain a deferral"
    )
    assert not installed_source.exists(), (
        "post-merge must not republish installed source after the owning installer releases its lock"
    )
    calls = systemctl_calls.read_text(encoding="utf-8") if systemctl_calls.exists() else ""
    assert "--user restart app.slice" not in calls
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert set(record["deploy_groups"]["oom_containment"]) == set(files)
    assert record["deploy_groups"]["systemd_dropins"] == []


def test_root_packages_install_apcupsd_before_oom_recovery_verification(tmp_path: Path) -> None:
    order = tmp_path / "install-order"
    apcupsd_ready = tmp_path / "apcupsd-ready"
    apcupsd_installer = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "apcupsd\\n" >> "$HAPAX_ROOT_PACKAGE_ORDER"\n'
        'touch "$HAPAX_APCUPSD_READY_WITNESS"\n'
    )
    oom_installer = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        '[ -f "$HAPAX_APCUPSD_READY_WITNESS" ] || { echo "apcupsd inactive" >&2; exit 42; }\n'
        'printf "oom\\n" >> "$HAPAX_ROOT_PACKAGE_ORDER"\n'
    )
    files = {
        "config/root-required/apcupsd-power-alerts.files": (
            "config/root-required/apcupsd-power-alerts.files\n"
            "scripts/install-apcupsd-power-alerts\n"
        ),
        "scripts/install-apcupsd-power-alerts": apcupsd_installer,
        "config/root-required/oom-containment.files": (
            "config/root-required/oom-containment.files\nscripts/install-p0-oom-containment\n"
        ),
        "scripts/install-p0-oom-containment": oom_installer,
    }
    repo, sha = _repo_with_linear_commit(tmp_path, files)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "REPO": str(repo),
            "HAPAX_ROOT_PACKAGE_ORDER": str(order),
            "HAPAX_APCUPSD_READY_WITNESS": str(apcupsd_ready),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "trace.jsonl"),
        },
    )

    assert result.returncode == 0, result.stderr
    assert order.read_text(encoding="utf-8").splitlines() == ["apcupsd", "oom"]


def test_stale_post_merge_deploy_preserves_newer_desired_receipt(tmp_path: Path) -> None:
    repo, sha_a = _repo_with_linear_commit(tmp_path, ROOT_AUDIT_SOURCE_FILES)
    earlyoom = repo / "config" / "earlyoom" / "default"
    earlyoom.write_text('EARLYOOM_ARGS="newer policy"\n', encoding="utf-8")
    _git(repo, "add", "config/earlyoom/default")
    _git(repo, "commit", "-m", "newer OOM package")
    sha_b = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    desired = home / ".local" / "state" / "hapax" / "root-required" / "desired-receipts"
    desired.mkdir(parents=True)
    oom_desired = desired / "oom-containment.sha"
    oom_desired.write_text(f"{sha_b}\n", encoding="utf-8")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha_a],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "trace.jsonl"),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "supersedes stale deploy" in result.stdout
    assert oom_desired.read_text(encoding="utf-8").strip() == sha_b


def test_post_merge_squash_equivalence_rejects_newer_manifest_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "manifest-test@example.test")
    _git(repo, "config", "user.name", "Manifest Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    _git(repo, "switch", "-c", "candidate")
    for relative, body in ROOT_AUDIT_SOURCE_FILES.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        if body.startswith("#!"):
            path.chmod(0o755)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "candidate packages")
    candidate_sha = _git(repo, "rev-parse", "HEAD")

    _git(repo, "switch", "-c", "desired", base_sha)
    _git(repo, "checkout", "candidate", "--", ".")
    desired_manifest = repo / "config/root-required/oom-containment.files"
    desired_manifest.write_text(
        desired_manifest.read_text(encoding="utf-8") + "config/earlyoom/new-policy\n",
        encoding="utf-8",
    )
    extra = repo / "config/earlyoom/new-policy"
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text("new owned policy\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "desired adds owned file")
    desired_sha = _git(repo, "rev-parse", "HEAD")

    home = tmp_path / "home"
    desired_root = home / ".local/state/hapax/root-required/desired-receipts"
    desired_root.mkdir(parents=True)
    desired_receipt = desired_root / "oom-containment.sha"
    desired_receipt.write_text(f"{desired_sha}\n", encoding="utf-8")

    result = subprocess.run(
        [str(SCRIPT), candidate_sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "REPO": str(repo),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "trace.jsonl"),
        },
    )

    assert result.returncode == 1
    assert "refusing divergent desired oom-containment transition" in result.stderr
    assert desired_receipt.read_text(encoding="utf-8").strip() == desired_sha


def test_root_required_oom_deploy_defers_and_continues_to_user_units(tmp_path: Path) -> None:
    installer_body = "#!/usr/bin/env bash\nexit 77\n"
    files = {
        "config/root-required/oom-containment.files": OOM_PACKAGE_MANIFEST,
        "scripts/install-p0-oom-containment": installer_body,
        "config/root-required/hapax-oom-score-enforce.sudoers": (
            "hapax ALL=(root) NOPASSWD: /usr/local/sbin/hapax-oom-score-enforce --apply-unit pipewire.service\n"
        ),
        "scripts/hapax-oom-score-enforce": "#!/usr/bin/env bash\nexit 0\n",
        "scripts/hapax-oom-score-trigger": "#!/usr/bin/env bash\nexit 0\n",
        "scripts/hapax-root-failure-intake": "#!/usr/bin/env bash\nexit 0\n",
        "config/earlyoom/default": 'EARLYOOM_ARGS="--ignore recovery"\n',
        "systemd/system/system.slice.d/oom-containment.conf": (
            "[Slice]\nMemoryHigh=infinity\nMemoryMax=infinity\nMemorySwapMax=infinity\n"
            "MemoryLow=24G\nMemoryMin=12G\n"
        ),
        "systemd/system/user.slice.d/oom-containment.conf": (
            "[Slice]\nMemoryHigh=infinity\nMemoryMax=infinity\nMemorySwapMax=infinity\n"
            "MemoryLow=16G\nMemoryMin=8G\n"
        ),
        "systemd/system/user-1000.slice.d/oom-containment.conf": (
            "[Slice]\nMemoryHigh=80G\nMemoryMax=96G\nMemorySwapMax=8G\nMemoryLow=16G\nMemoryMin=8G\n"
        ),
        "systemd/system/user@1000.service.d/oom.conf": "[Service]\nOOMScoreAdjust=100\n",
        "systemd/system/apcupsd.service.d/oom-protect.conf": "[Service]\nOOMScoreAdjust=-900\n",
        "systemd/system/systemd-logind.service.d/oom-protect.conf": (
            "[Service]\nOOMScoreAdjust=-800\n"
        ),
        "systemd/system/systemd-resolved.service.d/oom-protect.conf": (
            "[Service]\nOOMScoreAdjust=-800\n"
        ),
        "systemd/system/systemd-timesyncd.service.d/oom-protect.conf": (
            "[Service]\nOOMScoreAdjust=-800\n"
        ),
        "systemd/system/NetworkManager.service.d/oom-protect.conf": (
            "[Service]\nOOMScoreAdjust=-800\n"
        ),
        "systemd/system/dbus-broker.service.d/oom-protect.conf": (
            "[Service]\nOOMScoreAdjust=-900\n"
        ),
        "systemd/system/sshd.service.d/oom-protect.conf": (
            "[Service]\nOOMScoreAdjust=0\nOOMPolicy=continue\n"
        ),
        "systemd/units/hapax-root-failure-intake@.service": (
            "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\n"
        ),
        "systemd/units/hapax-oom-score-enforce.service": (
            "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\nExecStart=/usr/local/sbin/hapax-oom-score-enforce --apply\n"
        ),
        "systemd/units/hapax-oom-score-enforce.timer": (
            "[Unit]\n# Hapax-Install-Scope: system\n[Timer]\nOnBootSec=30s\nOnUnitActiveSec=30s\n"
        ),
        **P0_OOM_AUDIT_FILES,
        "systemd/units/app.slice.d/oom-containment.conf": (
            "[Slice]\nMemoryHigh=72G\nMemoryMax=88G\nMemorySwapMax=8G\nMemoryLow=16G\nMemoryMin=8G\n"
        ),
        **P0_USER_OOM_DROPINS,
        "systemd/units/hapax-demo.service": (
            "[Unit]\nDescription=Demo\n\n[Service]\nType=oneshot\nExecStart=/bin/true\n"
        ),
    }
    repo, sha = _repo_with_linear_commit(tmp_path, files)
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    defer_dir = tmp_path / "root-required"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_dir),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    deferred = defer_dir / sha / "oom-containment"
    assert (deferred / "RUNBOOK.txt").is_file()
    assert (deferred / "scripts" / "install-p0-oom-containment").is_file()
    runbook = (deferred / "RUNBOOK.txt").read_text(encoding="utf-8")
    assert "sudo -v" in runbook
    assert "root shell" not in runbook
    assert "HAPAX_OOM_INSTALL_SUDO=" not in runbook
    assert "HAPAX_ROOT_REQUIRED_DRAIN_DIR=" in runbook
    assert f"HAPAX_ROOT_REQUIRED_PACKAGE_SHA={sha}" in runbook
    assert "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT=" in runbook
    assert "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT=" in runbook
    assert "HAPAX_ROOT_REQUIRED_DESIRED_RECEIPT_ROOT=" in runbook
    assert "HAPAX_ROOT_REQUIRED_GIT_REPO=" in runbook
    assert (home / ".config" / "systemd" / "user" / "hapax-demo.service").is_file()
    assert "root-required oom-containment install deferred" in result.stdout
    desired = home / ".local/state/hapax/root-required/desired-receipts/oom-containment.sha"
    assert desired.read_text(encoding="utf-8").strip() == sha

    audit_result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_dir)},
    )

    assert audit_result.returncode == 1
    assert "root-required post-merge deploy deferrals pending" in audit_result.stderr
    assert "--install --verify-live" in audit_result.stderr
    (deferred / "RUNBOOK.txt").unlink()
    assert desired.read_text(encoding="utf-8").strip() == sha


def test_root_required_deferral_staging_is_locked_and_atomic() -> None:
    body = SCRIPT.read_text(encoding="utf-8")

    assert 'flock -x "$lock_fd"' in body
    assert 'temp="$ROOT_DEFER_DIR/$SHA/.${label}.tmp.$$"' in body
    assert 'mv "$temp" "$dest"' in body
    assert "already installed at $SHA; deferral not recreated" in body
    assert "record_root_required_source" not in body


def test_root_required_audit_fails_when_oom_enforcer_source_missing(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=_root_audit_env(
            tmp_path,
            missing_source_rel="scripts/hapax-oom-score-enforce",
        ),
    )

    assert result.returncode == 1
    assert "root-required source missing" in result.stderr
    assert "next action:" in result.stderr


def test_root_required_audit_detects_oom_enforcer_drift(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=_root_audit_env(
            tmp_path,
            drift_rel="scripts/hapax-oom-score-enforce",
        ),
    )

    assert result.returncode == 1
    assert "root-required install drift" in result.stderr
    assert "install-p0-oom-containment --install --verify-live" in result.stderr


def test_root_required_audit_detects_sudoers_mode_drift(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    Path(env["HAPAX_OOM_SUDOERS_DEST"]).chmod(0o644)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "root-required install mode drift" in result.stderr
    assert "expected=440" in result.stderr


def test_root_required_audit_rejects_byte_identical_symlinked_install(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    dest = Path(env["HAPAX_OOM_ENFORCER_DEST"])
    mutable_target = tmp_path / "mutable-worktree" / "hapax-oom-score-enforce"
    mutable_target.parent.mkdir()
    mutable_target.write_bytes(dest.read_bytes())
    mutable_target.chmod(0o755)
    dest.unlink()
    dest.symlink_to(mutable_target)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "install missing or not a regular stable copy" in result.stderr
    assert "install-p0-oom-containment --install --verify-live" in result.stderr


def test_root_required_audit_rejects_nonexact_install_mode(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    earlyoom = Path(env["HAPAX_OOM_EARLYOOM_DEST"])
    earlyoom.chmod(0o600)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "install mode drift" in result.stderr
    assert "mode=600 expected=644" in result.stderr


def test_root_required_audit_rejects_snapshot_not_matching_installed_receipt(
    tmp_path: Path,
) -> None:
    env = _root_audit_env(tmp_path)
    rel = "scripts/hapax-oom-score-enforce"
    installed_path = Path(env["HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT"]) / rel
    installed_path.write_text("stale installed snapshot\n", encoding="utf-8")

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "installed source is not bound" in result.stderr
    assert "oom-containment receipt" in result.stderr


def test_root_required_audit_fails_closed_when_snapshot_file_absent(
    tmp_path: Path,
) -> None:
    env = _root_audit_env(tmp_path)
    installed = Path(env["HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT"])
    (installed / "scripts" / "hapax-oom-score-enforce").unlink()

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "installed source is not bound" in result.stderr
    assert "root-required source missing" in result.stderr


def test_root_required_audit_fails_when_installed_receipt_is_missing(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    receipt = Path(env["HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT"]) / "oom-containment.sha"
    receipt.unlink()

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "installed receipt missing" in result.stderr
    assert "oom-containment.sha" in result.stderr


def test_root_required_audit_detects_desired_package_not_installed(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    repo = Path(env["HAPAX_ROOT_REQUIRED_GIT_REPO"])
    (repo / "unrelated").write_text("new desired deployment\n", encoding="utf-8")
    _git(repo, "add", "unrelated")
    _git(repo, "commit", "-m", "new desired deployment")
    desired_sha = _git(repo, "rev-parse", "HEAD")
    desired = Path(env["HAPAX_ROOT_REQUIRED_DESIRED_RECEIPT_ROOT"]) / "oom-containment.sha"
    desired.write_text(f"{desired_sha}\n", encoding="utf-8")

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "desired package is not installed" in result.stderr
    assert f"desired={desired_sha}" in result.stderr
    assert "even if the cached RUNBOOK was lost" in result.stderr


def test_root_required_audit_detects_nonexecutable_hook(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    hook = Path(env["HAPAX_APCUPSD_DEST"]) / "doshutdown"
    hook.chmod(0o644)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "executable mode drift" in result.stderr
    assert "install-apcupsd-power-alerts" in result.stderr


def test_root_required_audit_detects_disabled_enforcer_timer(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    fake_systemctl = Path(env["HAPAX_ROOT_AUDIT_SYSTEMCTL"])
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$*" = "is-enabled --quiet hapax-oom-score-enforce.timer" ]; then exit 1; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "hapax-oom-score-enforce.timer is not enabled" in result.stderr
    assert "enable --now" in result.stderr


def test_root_required_audit_detects_inactive_earlyoom(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    fake_systemctl = Path(env["HAPAX_ROOT_AUDIT_SYSTEMCTL"])
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$*" = "is-active --quiet earlyoom.service" ]; then exit 1; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "earlyoom.service is not active" in result.stderr
    assert "enable --now earlyoom.service" in result.stderr


def test_root_required_audit_detects_disabled_apcupsd(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    fake_systemctl = Path(env["HAPAX_ROOT_AUDIT_SYSTEMCTL"])
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$*" = "is-enabled --quiet apcupsd.service" ]; then exit 1; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "apcupsd.service is not enabled" in result.stderr
    assert "enable --now apcupsd.service" in result.stderr


def test_root_required_audit_detects_stale_loaded_upower_action(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    fake_busctl = Path(env["HAPAX_ROOT_AUDIT_BUSCTL"])
    fake_busctl.write_text("#!/bin/sh\nprintf 's \\\"PowerOff\\\"\\n'\n", encoding="utf-8")
    fake_busctl.chmod(0o755)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "UPower loaded critical action" in result.stderr
    assert "expected Ignore" in result.stderr


def test_root_required_audit_detects_stale_loaded_apcupsd_thresholds(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    fake_apcaccess = Path(env["HAPAX_ROOT_AUDIT_APCACCESS"])
    fake_apcaccess.write_text(
        "#!/bin/sh\n"
        "printf 'STATUS   : ONLINE\\nMBATTCHG : 99 Percent\\nMINTIMEL : 5 Minutes\\nMAXTIME  : 0 Seconds\\n'\n",
        encoding="utf-8",
    )
    fake_apcaccess.chmod(0o755)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "apcupsd loaded MBATTCHG=99" in result.stderr
    assert "expected 20" in result.stderr


def test_root_required_audit_passes_when_oom_enforcer_matches(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=_root_audit_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert "root-required post-merge deploy deferrals: none" in result.stdout


def test_root_required_audit_legacy_manifest_transition_is_fail_closed(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    repo = Path(env["HAPAX_ROOT_REQUIRED_GIT_REPO"])
    manifest_rel = "config/root-required/apcupsd-power-alerts.files"
    _git(repo, "rm", manifest_rel)
    _git(repo, "commit", "-m", "legacy apcupsd package without manifest")
    legacy_sha = _git(repo, "rev-parse", "HEAD")
    for root_key in (
        "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT",
        "HAPAX_ROOT_REQUIRED_DESIRED_RECEIPT_ROOT",
    ):
        (Path(env[root_key]) / "apcupsd-power-alerts.sha").write_text(
            f"{legacy_sha}\n", encoding="utf-8"
        )

    unexpected_manifest = Path(env["HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT"]) / manifest_rel
    rejected = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert rejected.returncode == 1
    assert "installed manifest is not bound to legacy" in rejected.stderr

    unexpected_manifest.unlink()
    accepted = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert accepted.returncode == 0, accepted.stderr


def test_root_required_audit_waits_for_shared_package_lock(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    lock_path = Path(env["HAPAX_ROOT_REQUIRED_STATE_ROOT"]) / ".lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        audit = subprocess.Popen(
            [str(ROOT_REQUIRED_AUDIT)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        time.sleep(0.2)
        assert audit.poll() is None
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    stdout, stderr = audit.communicate(timeout=5)
    assert audit.returncode == 0, (stdout, stderr)


def test_apcupsd_power_alert_deploy_uses_dedicated_installer(tmp_path: Path) -> None:
    installer_calls = tmp_path / "apcupsd-installer-calls.txt"
    installer_body = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_APCUPSD_INSTALL_CALLS"\n'
    )
    future_manifest_path = "config/apcupsd/future-hook"
    files = {
        "config/root-required/apcupsd-power-alerts.files": (
            APCUPSD_PACKAGE_MANIFEST + f"{future_manifest_path}\n"
        ),
        future_manifest_path: "future hook\n",
        "scripts/install-apcupsd-power-alerts": installer_body,
        "config/apcupsd/apcupsd.conf": (
            "## apcupsd.conf v1.1 ##\nUPSNAME podium\nBATTERYLEVEL 20\nMINUTES 5\nTIMEOUT 0\n"
        ),
        "config/apcupsd/hapax-power-event.py": "#!/usr/bin/env python3\n",
        "config/apcupsd/onbattery": "#!/bin/sh\n",
        "config/apcupsd/offbattery": "#!/bin/sh\n",
        "config/apcupsd/doshutdown": "#!/bin/sh\n",
        "config/upower/90-hapax-apcupsd-owner.conf": (
            "[UPower]\nAllowRiskyCriticalPowerAction=true\nCriticalPowerAction=Ignore\n"
        ),
        "systemd/logrotate.d/hapax-ups-power-events": "/var/log/hapax/ups-power-events.jsonl {\n}\n",
    }
    repo, sha = _repo_with_linear_commit(tmp_path, files)
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_APCUPSD_INSTALL_CALLS": str(installer_calls),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "--install --verify-live" in installer_calls.read_text(encoding="utf-8")
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert set(record["deploy_groups"]["apcupsd_power_alerts"]) == set(files)


def test_generic_slice_dropin_deploy_uses_runtime_set_property_not_restart(
    tmp_path: Path,
) -> None:
    dropin_path = "systemd/units/demo.slice.d/memory.conf"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {dropin_path: "[Slice]\nMemoryHigh=1G\nMemoryMax=2G\nMemorySwapMax=512M\n"},
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert (
        "--user set-property --runtime demo.slice MemoryHigh=1G MemoryMax=2G MemorySwapMax=512M"
        in calls
    )
    assert "--user restart demo.slice" not in calls


def test_systemd_coverage_includes_slice_units() -> None:
    # hapax-sdlc.slice (the SDLC resource-shielding slice) must be deploy-covered;
    # a .slice falling outside the case-globs is the absence-class deploy bug.
    result = _coverage(["systemd/units/hapax-sdlc.slice"])

    assert result.returncode == 0, result.stderr
    assert "ok: all systemd/** paths" in result.stdout


def test_d2_recovery_unit_classifier_uses_canonical_notify_failure_path() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    canonical = "systemd/units/notify-failure@.service"
    spaced_typo = canonical.replace("@", " @")

    assert spaced_typo not in script
    assert f"{canonical}|" in script
    result = _coverage([canonical])
    assert result.returncode == 0, result.stderr
    assert "ok: all systemd/** paths" in result.stdout


def test_systemd_coverage_still_flags_unknown_systemd_paths() -> None:
    result = _coverage(["systemd/uncovered/example.conf"])

    assert result.returncode == 1
    assert "systemd/uncovered/example.conf" in result.stderr


def test_system_scoped_units_skip_user_deploy_and_clean_stale_copy(tmp_path: Path) -> None:
    unit_path = "systemd/units/hapax-l12-critical-usb-guard.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "# Hapax-Install-Scope: system\n"
                "Description=System scoped guard\n"
                "\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=/usr/local/bin/hapax-l12-critical-usb-guard\n"
            )
        },
    )
    home = tmp_path / "home"
    stale_user_unit = home / ".config" / "systemd" / "user" / "hapax-l12-critical-usb-guard.service"
    stale_user_unit.parent.mkdir(parents=True)
    stale_user_unit.write_text("stale\n", encoding="utf-8")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "system-scoped systemd units changed" in result.stdout
    assert not stale_user_unit.exists()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user disable --now hapax-l12-critical-usb-guard.service" in calls
    assert "--user daemon-reload" in calls
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["systemd_system_units"] == [unit_path]
    assert record["deploy_groups"]["systemd_units"] == []


def test_user_scoped_units_still_deploy_to_user_dir(tmp_path: Path) -> None:
    unit_path = "systemd/units/hapax-user-demo.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "Description=User scoped demo\n"
                "\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=%h/.local/bin/hapax-demo\n"
            )
        },
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    installed = home / ".config" / "systemd" / "user" / "hapax-user-demo.service"
    assert installed.read_text(encoding="utf-8") == (
        "[Unit]\n"
        "Description=User scoped demo\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "ExecStart=%h/.local/bin/hapax-demo\n"
    )
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["systemd_units"] == [unit_path]
    assert record["deploy_groups"]["systemd_system_units"] == []


def test_watchdog_change_installs_commit_copy_to_local_bin(tmp_path: Path) -> None:
    home = tmp_path / "home"
    watchdog_body = "#!/usr/bin/env bash\necho deployed-watchdog\n"
    watchdog_path = "systemd/watchdogs/health-watchdog"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            watchdog_path: watchdog_body,
            "systemd/units/health-monitor.service": (
                "[Unit]\n"
                "Description=Health monitor\n"
                "\n"
                "[Service]\n"
                f"ExecStart={home}/.local/bin/health-watchdog\n"
            ),
        },
    )
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    installed = home / ".local" / "bin" / "health-watchdog"
    assert installed.read_text(encoding="utf-8") == watchdog_body
    assert os.access(installed, os.X_OK)
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user is-active --quiet health-monitor.service" in calls
    assert "--user restart health-monitor.service" in calls
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["systemd_watchdogs"] == [watchdog_path]


def test_preset_only_deploy_installs_and_starts_governed_intake_timers(
    tmp_path: Path,
) -> None:
    repo, sha = _repo_with_intake_units_then_preset_commit(tmp_path)
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    user_units = home / ".config" / "systemd" / "user"
    assert (user_units / "hapax-request-decompose.timer").is_file()
    assert (user_units / "hapax-request-decompose.service").is_file()
    assert (user_units / "hapax-cc-task-offer-ready.timer").is_file()
    assert (user_units / "hapax-cc-task-offer-ready.service").is_file()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user daemon-reload" in calls
    assert "--user enable --now hapax-request-decompose.timer" in calls
    assert "--user enable --now hapax-cc-task-offer-ready.timer" in calls
    assert "preset-activated governed intake unit" in result.stdout


def test_preset_only_deploy_removes_stale_ready_offer_dropin(tmp_path: Path) -> None:
    repo, sha = _repo_with_intake_units_then_preset_commit(tmp_path)
    home = tmp_path / "home"
    stale_dropin = (
        home
        / ".config"
        / "systemd"
        / "user"
        / "hapax-cc-task-offer-ready.service.d"
        / "worktree-override.conf"
    )
    stale_dropin.parent.mkdir(parents=True)
    stale_dropin.write_text(
        "[Service]\nExecStart=\nExecStart=/missing/worktree/scripts/cc-task-offer-ready --reconcile\n",
        encoding="utf-8",
    )
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not stale_dropin.exists()
    assert not stale_dropin.parent.exists()
    assert "removing unversioned local drop-in" in result.stdout
    assert (home / ".config/systemd/user/hapax-cc-task-offer-ready.service").is_file()


def test_preset_only_deploy_refuses_governed_intake_timer_without_service(
    tmp_path: Path,
) -> None:
    repo, sha = _repo_with_intake_timer_missing_service_then_preset_commit(tmp_path)
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    user_units = home / ".config" / "systemd" / "user"
    assert not (user_units / "hapax-cc-task-offer-ready.timer").exists()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user enable --now hapax-cc-task-offer-ready.timer" not in calls
    assert "Next action: add systemd/units/hapax-cc-task-offer-ready.service" in result.stderr


def test_quake_asset_changes_install_and_restart_active_darkplaces(tmp_path: Path) -> None:
    repo, sha = _repo_with_quake_asset_commit(tmp_path)
    home = tmp_path / "home"
    game_root = tmp_path / "darkplaces"
    install_calls = tmp_path / "install-calls.txt"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "DARKPLACES_GAME_ROOT": str(game_root),
        "HAPAX_INSTALL_CALLS": str(install_calls),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "quake assets changed (1)" in result.stdout
    assert "installing Screwm Quake assets" in result.stdout
    assert "restarting hapax-darkplaces-v4l2.service" in result.stdout
    assert install_calls.read_text(encoding="utf-8").splitlines() == [str(game_root)]
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user is-active --quiet hapax-darkplaces-v4l2.service" in calls
    assert "--user restart hapax-darkplaces-v4l2.service" in calls
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["quake_assets"] == ["assets/quake/maps/screwm.bsp"]
    assert "quake_assets" in record["avsdlc"]["runtime_media_witness_groups"]


def test_recovery_bundle_changes_refresh_stable_installed_closure(tmp_path: Path) -> None:
    repo, sha = _repo_with_recovery_bundle_change(tmp_path)
    (repo / "scripts" / "hapax-recovery-plane-install").write_text(
        "#!/usr/bin/env bash\nexit 99\n",
        encoding="utf-8",
    )
    (repo / "scripts" / "hapax-recovery-plane-install").chmod(0o644)
    home = tmp_path / "home"
    install_calls = tmp_path / "recovery-install-calls.txt"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "HAPAX_RECOVERY_INSTALL_CALLS": str(install_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "recovery bundle files changed (1)" in result.stdout
    assert install_calls.read_text(encoding="utf-8").splitlines() == [
        f"--source {repo} --source-ref {sha} --dest {_recovery_bundle_dest(home)}"
    ]
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["recovery_bundle"] == ["shared/p0_incident_intake.py"]
    assert "recovery_bundle" in record["avsdlc"]["runtime_media_witness_groups"]


def test_recovery_script_changes_refresh_stable_installed_closure(tmp_path: Path) -> None:
    repo, sha = _repo_with_recovery_script_change(tmp_path)
    home = tmp_path / "home"
    install_calls = tmp_path / "recovery-install-calls.txt"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "HAPAX_RECOVERY_INSTALL_CALLS": str(install_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "recovery bundle files changed (1)" in result.stdout
    assert install_calls.read_text(encoding="utf-8").splitlines() == [
        f"--source {repo} --source-ref {sha} --dest {_recovery_bundle_dest(home)}"
    ]
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["recovery_bundle"] == ["scripts/hapax-coord-deploy"]


def test_missing_recovery_bundle_self_heals_on_later_deploy(tmp_path: Path) -> None:
    repo, sha = _repo_with_recovery_installer_then_linear_commit(
        tmp_path,
        {"docs/unrelated.md": "later deploy after old first rollout\n"},
    )
    home = tmp_path / "home"
    custom_dest = tmp_path / "custom-recovery" / "current"
    install_calls = tmp_path / "recovery-install-calls.txt"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "HAPAX_RECOVERY_INSTALL_CALLS": str(install_calls),
        "HAPAX_RECOVERY_BUNDLE_DEST": str(custom_dest),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "recovery bundle runtime missing/incomplete" in result.stdout
    assert install_calls.read_text(encoding="utf-8").splitlines() == [
        f"--source {repo} --source-ref {sha} --dest {custom_dest}"
    ]
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["recovery_bundle"] == [f"self-heal:{custom_dest}"]
    assert "recovery_bundle" in record["avsdlc"]["runtime_media_witness_groups"]


def test_stale_recovery_bundle_self_heals_on_later_deploy(tmp_path: Path) -> None:
    repo, sha, stale_sha, stale_files = _repo_with_recovery_bundle_drift_then_unrelated_commit(
        tmp_path
    )
    home = tmp_path / "home"
    custom_dest = tmp_path / "custom-recovery" / "current"
    _write_installed_recovery_bundle(custom_dest, stale_sha, stale_files)
    install_calls = tmp_path / "recovery-install-calls.txt"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "HAPAX_RECOVERY_INSTALL_CALLS": str(install_calls),
        "HAPAX_RECOVERY_BUNDLE_DEST": str(custom_dest),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "recovery bundle runtime stale" in result.stdout
    assert install_calls.read_text(encoding="utf-8").splitlines() == [
        f"--source {repo} --source-ref {sha} --dest {custom_dest}"
    ]
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["recovery_bundle"] == [f"self-heal:{custom_dest}"]
    assert "recovery_bundle" in record["avsdlc"]["runtime_media_witness_groups"]


def test_corrupt_recovery_bundle_file_self_heals_on_later_deploy(tmp_path: Path) -> None:
    repo, sha, _stale_sha, stale_files = _repo_with_recovery_bundle_drift_then_unrelated_commit(
        tmp_path
    )
    current_files = dict(stale_files)
    current_files["shared/p0_incident_intake.py"] = "def main():\n    return 42\n"
    home = tmp_path / "home"
    custom_dest = tmp_path / "custom-recovery" / "current"
    _write_installed_recovery_bundle(custom_dest, sha, current_files)
    corrupt_script = custom_dest / "scripts" / "hapax-coord-deploy"
    corrupt_script.write_text("#!/usr/bin/env bash\necho corrupt runtime\n", encoding="utf-8")
    corrupt_script.chmod(0o755)
    install_calls = tmp_path / "recovery-install-calls.txt"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "HAPAX_RECOVERY_INSTALL_CALLS": str(install_calls),
        "HAPAX_RECOVERY_BUNDLE_DEST": str(custom_dest),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "recovery bundle runtime stale" in result.stdout
    assert install_calls.read_text(encoding="utf-8").splitlines() == [
        f"--source {repo} --source-ref {sha} --dest {custom_dest}"
    ]
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["recovery_bundle"] == [f"self-heal:{custom_dest}"]
    assert "recovery_bundle" in record["avsdlc"]["runtime_media_witness_groups"]


def test_d2_unit_only_change_refreshes_recovery_bundle_before_systemd(
    tmp_path: Path,
) -> None:
    repo, sha, unit_path = _repo_with_d2_unit_only_change(tmp_path)
    bin_dir, deploy_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_RECOVERY_INSTALL_CALLS": str(deploy_calls),
        "HAPAX_SYSTEMCTL_CALLS": str(deploy_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    calls = deploy_calls.read_text(encoding="utf-8").splitlines()
    install_call = (
        f"--source {repo} --source-ref {sha} --dest {_recovery_bundle_dest(tmp_path / 'home')}"
    )
    assert install_call in calls
    assert "--user daemon-reload" in calls
    assert calls.index(install_call) < calls.index("--user daemon-reload")
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["recovery_bundle"] == [unit_path]
    assert record["deploy_groups"]["systemd_units"] == [unit_path]


def test_recovery_bundle_missing_installer_at_sha_error_names_next_action(
    tmp_path: Path,
) -> None:
    repo, sha = _repo_with_recovery_bundle_missing_installer(tmp_path)
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces" / "post-merge-traces.jsonl"),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert "missing recovery bundle installer at" in result.stderr
    assert "next: ensure scripts/hapax-recovery-plane-install exists" in result.stderr
    assert "rerun hapax-post-merge-deploy" in result.stderr


def test_coord_service_deploy_stages_activation_before_active_restart(
    tmp_path: Path,
) -> None:
    repo, sha = _repo_with_recovery_installer_then_linear_commit(
        tmp_path,
        {
            "systemd/units/hapax-coord.service": (
                "[Unit]\n"
                "Description=Coord\n"
                "OnFailure=notify-failure@%n.service\n"
                "\n"
                "[Service]\n"
                "Type=simple\n"
                "WorkingDirectory=%h/.cache/hapax/coord-activation/worktree\n"
                "ExecStart=%h/.cache/hapax/coord-activation/worktree/scripts/run-dev.sh --daemon\n"
            ),
        },
    )
    home = tmp_path / "home"
    custom_dest = tmp_path / "custom-recovery" / "current"
    coord_deploy = custom_dest / "scripts" / "hapax-coord-deploy"
    coord_deploy.parent.mkdir(parents=True)
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    coord_deploy.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ "${HAPAX_COORD_DEPLOY_RESTART_IF_UP_TO_DATE:-0}" != "1" ]; then\n'
        '    printf "%s\\n" "missing-coord-restart-if-up-to-date-env" '
        '>> "$HAPAX_SYSTEMCTL_CALLS"\n'
        "    exit 43\n"
        "fi\n"
        'printf "%s\\n" "coord-deploy-restart-if-up-to-date='
        '${HAPAX_COORD_DEPLOY_RESTART_IF_UP_TO_DATE}" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'printf "%s\\n" "coord-deploy" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'printf "%s\\n" "--user restart hapax-coord.service" >> "$HAPAX_SYSTEMCTL_CALLS"\n',
        encoding="utf-8",
    )
    coord_deploy.chmod(0o755)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_RECOVERY_INSTALL_CALLS": str(systemctl_calls),
        "HAPAX_RECOVERY_BUNDLE_DEST": str(custom_dest),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "staging hapax-coord activation before activating hapax-coord.service" in result.stdout
    calls = systemctl_calls.read_text(encoding="utf-8").splitlines()
    assert "coord-deploy-restart-if-up-to-date=1" in calls
    assert calls.index("--user is-active --quiet hapax-coord.service") < calls.index(
        "coord-deploy-restart-if-up-to-date=1"
    )
    assert calls.index("coord-deploy-restart-if-up-to-date=1") < calls.index("coord-deploy")
    assert calls.index("coord-deploy") < calls.index("--user restart hapax-coord.service")
    assert calls.count("--user restart hapax-coord.service") == 1
    assert "--user enable hapax-coord.service" not in calls


def test_coord_service_auto_enable_stages_activation_before_enable(
    tmp_path: Path,
) -> None:
    repo, sha = _repo_with_recovery_installer_then_linear_commit(
        tmp_path,
        {
            "systemd/units/hapax-coord.service": (
                "# Hapax-Auto-Enable: true\n"
                "[Unit]\n"
                "Description=Coord\n"
                "OnFailure=notify-failure@%n.service\n"
                "\n"
                "[Service]\n"
                "Type=simple\n"
                "WorkingDirectory=%h/.cache/hapax/coord-activation/worktree\n"
                "ExecStart=%h/.cache/hapax/coord-activation/worktree/scripts/run-dev.sh --daemon\n"
                "\n"
                "[Install]\n"
                "WantedBy=default.target\n"
            ),
        },
    )
    home = tmp_path / "home"
    coord_deploy = (
        home
        / ".local"
        / "lib"
        / "hapax-recovery"
        / "council"
        / "current"
        / "scripts"
        / "hapax-coord-deploy"
    )
    coord_deploy.parent.mkdir(parents=True)
    bin_dir, systemctl_calls = _fake_systemctl_with_inactive_coord(tmp_path)
    coord_deploy.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ "${HAPAX_COORD_DEPLOY_RESTART_IF_UP_TO_DATE:-0}" != "1" ]; then\n'
        '    printf "%s\\n" "missing-coord-restart-if-up-to-date-env" '
        '>> "$HAPAX_SYSTEMCTL_CALLS"\n'
        "    exit 43\n"
        "fi\n"
        'printf "%s\\n" "coord-deploy-restart-if-up-to-date='
        '${HAPAX_COORD_DEPLOY_RESTART_IF_UP_TO_DATE}" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'printf "%s\\n" "coord-deploy" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'printf "%s\\n" "--user restart hapax-coord.service" >> "$HAPAX_SYSTEMCTL_CALLS"\n',
        encoding="utf-8",
    )
    coord_deploy.chmod(0o755)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_RECOVERY_INSTALL_CALLS": str(systemctl_calls),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "staging hapax-coord activation before activating hapax-coord.service" in result.stdout
    calls = systemctl_calls.read_text(encoding="utf-8").splitlines()
    assert "coord-deploy-restart-if-up-to-date=1" in calls
    assert calls.index("--user is-active --quiet hapax-coord.service") < calls.index(
        "coord-deploy-restart-if-up-to-date=1"
    )
    assert calls.index("coord-deploy-restart-if-up-to-date=1") < calls.index("coord-deploy")
    assert calls.index("coord-deploy") < calls.index("--user restart hapax-coord.service")
    assert calls.index("--user restart hapax-coord.service") < calls.index(
        "--user enable hapax-coord.service"
    )
    assert "--user enable --now hapax-coord.service" not in calls


def test_coord_service_active_restart_refuses_when_activation_deploy_missing(
    tmp_path: Path,
) -> None:
    repo, sha = _repo_with_recovery_installer_then_linear_commit(
        tmp_path,
        {
            "systemd/units/hapax-coord.service": (
                "[Unit]\n"
                "Description=Coord\n"
                "OnFailure=notify-failure@%n.service\n"
                "\n"
                "[Service]\n"
                "Type=simple\n"
                "WorkingDirectory=%h/.cache/hapax/coord-activation/worktree\n"
                "ExecStart=%h/.cache/hapax/coord-activation/worktree/scripts/run-dev.sh --daemon\n"
            ),
        },
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_RECOVERY_INSTALL_CALLS": str(systemctl_calls),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 5
    assert "refusing to restart hapax-coord.service" in result.stderr
    assert "install the D2 recovery bundle" in result.stderr
    calls = systemctl_calls.read_text(encoding="utf-8").splitlines()
    assert "--user restart hapax-coord.service" not in calls


def test_coord_service_auto_enable_refuses_when_activation_deploy_missing(
    tmp_path: Path,
) -> None:
    repo, sha = _repo_with_recovery_installer_then_linear_commit(
        tmp_path,
        {
            "systemd/units/hapax-coord.service": (
                "# Hapax-Auto-Enable: true\n"
                "[Unit]\n"
                "Description=Coord\n"
                "OnFailure=notify-failure@%n.service\n"
                "\n"
                "[Service]\n"
                "Type=simple\n"
                "WorkingDirectory=%h/.cache/hapax/coord-activation/worktree\n"
                "ExecStart=%h/.cache/hapax/coord-activation/worktree/scripts/run-dev.sh --daemon\n"
                "\n"
                "[Install]\n"
                "WantedBy=default.target\n"
            ),
        },
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl_with_inactive_coord(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_RECOVERY_INSTALL_CALLS": str(systemctl_calls),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 5
    assert "refusing to restart hapax-coord.service" in result.stderr
    assert "install the D2 recovery bundle" in result.stderr
    calls = systemctl_calls.read_text(encoding="utf-8").splitlines()
    assert "--user enable hapax-coord.service" not in calls
    assert "--user enable --now hapax-coord.service" not in calls


def test_obs_audio_bind_unit_deploy_removes_stale_audio_l12_dropin(tmp_path: Path) -> None:
    unit_path = "systemd/units/hapax-obs-audio-bind.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "Description=OBS audio bind\n"
                "\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=%h/.cache/hapax/source-activation/worktree/scripts/hapax-obs-audio-bind\n"
            )
        },
    )
    home = tmp_path / "home"
    stale_dropin = (
        home
        / ".config"
        / "systemd"
        / "user"
        / "hapax-obs-audio-bind.service.d"
        / "95-codex-audio-l12-worktree.conf"
    )
    stale_dropin.parent.mkdir(parents=True, exist_ok=True)
    stale_dropin.write_text(
        "[Service]\nWorkingDirectory=/home/hapax/projects/hapax-council--codex-audio-l12\n",
        encoding="utf-8",
    )
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not stale_dropin.exists()
    assert "removing stale local drop-in" in result.stdout
    installed = home / ".config" / "systemd" / "user" / "hapax-obs-audio-bind.service"
    assert installed.exists()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user daemon-reload" in calls


def test_screwm_audio_reactivity_unit_deploy_removes_stale_target_dropin(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/hapax-screwm-audio-reactivity.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "Description=Screwm audio reactivity\n"
                "\n"
                "[Service]\n"
                "Environment=HAPAX_SCREWM_AUDIO_TARGET=hapax-broadcast-normalized\n"
                "ExecStart=%h/.cache/hapax/source-activation/worktree/scripts/"
                "screwm-audio-reactivity-source.py\n"
            )
        },
    )
    home = tmp_path / "home"
    stale_dropin = (
        home
        / ".config"
        / "systemd"
        / "user"
        / "hapax-screwm-audio-reactivity.service.d"
        / "override.conf"
    )
    stale_dropin.parent.mkdir(parents=True, exist_ok=True)
    stale_dropin.write_text(
        "[Service]\nEnvironment=HAPAX_SCREWM_AUDIO_TARGET=hapax-broadcast-normalized-capture\n",
        encoding="utf-8",
    )
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not stale_dropin.exists()
    assert not stale_dropin.parent.exists()
    assert "removing stale local drop-in" in result.stdout
    installed = home / ".config" / "systemd" / "user" / "hapax-screwm-audio-reactivity.service"
    assert installed.exists()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user daemon-reload" in calls


def test_audio_touching_units_restart_through_audio_safe_wrapper(tmp_path: Path) -> None:
    unit_path = "systemd/units/hapax-music-player.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "Description=Music player\n"
                "\n"
                "[Service]\n"
                "ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python "
                "-m agents.local_music_player\n"
            )
        },
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    audio_safe_bin, audio_safe_calls = _fake_audio_safe_restart(bin_dir, tmp_path, exit_code=1)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_AUDIO_SAFE_RESTART_BIN": str(audio_safe_bin),
        "HAPAX_AUDIO_SAFE_RESTART_CALLS": str(audio_safe_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user is-active --quiet hapax-music-player.service" in calls
    assert "--user restart hapax-music-player.service" not in calls
    assert audio_safe_calls.read_text(encoding="utf-8").splitlines() == [
        "hapax-music-player.service"
    ]
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["audio_safe_restart_units"] == ["hapax-music-player.service"]
    assert record["deploy_groups"]["systemd_units"] == [unit_path]


def test_audio_safe_wrapper_prefers_repo_script_over_stale_path(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/hapax-music-player.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "Description=Music player\n"
                "\n"
                "[Service]\n"
                "ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python "
                "-m agents.local_music_player\n"
            )
        },
    )
    repo_safe = repo / "scripts" / "hapax-audio-safe-restart"
    repo_safe.parent.mkdir(parents=True, exist_ok=True)
    repo_safe.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "$HAPAX_REPO_AUDIO_SAFE_CALLS"\nexit 0\n',
        encoding="utf-8",
    )
    repo_safe.chmod(0o755)
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    stale_safe, stale_calls = _fake_audio_safe_restart(bin_dir, tmp_path, exit_code=99)
    stale_safe.chmod(0o755)
    repo_safe_calls = tmp_path / "repo-audio-safe-calls.txt"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_AUDIO_SAFE_RESTART_CALLS": str(stale_calls),
        "HAPAX_REPO_AUDIO_SAFE_CALLS": str(repo_safe_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert repo_safe_calls.read_text(encoding="utf-8").splitlines() == [
        "hapax-music-player.service"
    ]
    assert not stale_calls.exists()


def test_hapax_runtime_config_deploys_to_user_config_and_restarts_reconciler(
    tmp_path: Path,
) -> None:
    config_path = "config/hapax/audio-link-map.conf"
    body = "source:output_FL|target:input_FL\n"
    repo, sha = _repo_with_linear_commit(tmp_path, {config_path: body})
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    installed = home / ".config" / "hapax" / "audio-link-map.conf"
    assert installed.read_text(encoding="utf-8") == body
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user restart hapax-audio-reconciler.service" in calls
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["hapax_runtime_config"] == [config_path]


def test_hapax_script_deploy_restarts_active_units_that_reference_local_bin(
    tmp_path: Path,
) -> None:
    script_path = "scripts/hapax-audio-reconciler"
    unit_path = "systemd/units/hapax-audio-reconciler.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            script_path: "#!/usr/bin/env bash\necho reconciler\n",
            unit_path: (
                "[Unit]\n"
                "Description=Reconciler\n"
                "\n"
                "[Service]\n"
                "ExecStart=%h/.local/bin/hapax-audio-reconciler\n"
            ),
        },
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    installed = home / ".local" / "bin" / "hapax-audio-reconciler"
    # Copy-from-SHA semantics (deploy-scripts-worktree-root-20260611): the
    # installed script is the release content, not a live symlink into a tree.
    assert installed.is_file() and not installed.is_symlink()
    assert installed.read_text() == (repo / script_path).read_text()
    assert installed.stat().st_mode & 0o111, "installed script must be executable"
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user restart hapax-audio-reconciler.service" in calls
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["hapax_scripts"] == [script_path]


def test_deploy_rejects_commit_ranges_before_touching_targets() -> None:
    result = subprocess.run(
        [str(SCRIPT), "HEAD..HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "expected a single commit SHA/ref" in result.stderr


def test_coverage_rejects_commit_ranges_before_touching_targets() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--report-coverage", "HEAD..HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "expected a single commit SHA/ref" in result.stderr


def test_real_deploy_invokes_smoke_runner_with_sha(tmp_path: Path) -> None:
    """The smoke runner is wired into the deploy chain (cc-task
    post-merge-smoke-deploy-wiring). After deploy actions complete,
    ``$REPO/scripts/hapax-post-merge-smoke <sha>`` is invoked. We stub
    the smoke script with a recorder so the test can assert it ran
    with the right SHA, without depending on the live smoke logic."""
    repo, sha = _repo_with_merge_commit(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    smoke_recorder = tmp_path / "smoke-call-record.txt"

    smoke_stub = repo / "scripts" / "hapax-post-merge-smoke"
    smoke_stub.write_text(
        f'#!/bin/sh\nprintf "smoke-invoked sha=%s\\n" "$1" > "{smoke_recorder}"\nexit 0\n',
        encoding="utf-8",
    )
    smoke_stub.chmod(0o755)

    # HOME isolated so the real deploy's scripts/hapax-demo symlink lands under
    # tmp, not the operator's ~/.local/bin (fix-deploy-symlink-skew leak).
    home = tmp_path / "home"
    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert smoke_recorder.exists(), "smoke runner was not invoked"
    assert smoke_recorder.read_text(encoding="utf-8").strip() == f"smoke-invoked sha={sha}"


def test_real_deploy_smoke_failure_does_not_block_trace(tmp_path: Path) -> None:
    """If the smoke runner exits non-zero (defying its own contract),
    the deploy script must still write its post-merge trace and exit
    cleanly. The `|| true` guard around the smoke invocation is the
    contract this test pins."""
    repo, sha = _repo_with_merge_commit(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"

    smoke_stub = repo / "scripts" / "hapax-post-merge-smoke"
    smoke_stub.write_text("#!/bin/sh\necho smoke-broken >&2\nexit 1\n", encoding="utf-8")
    smoke_stub.chmod(0o755)

    # HOME isolated so the real deploy's scripts/hapax-demo symlink lands under
    # tmp, not the operator's ~/.local/bin (fix-deploy-symlink-skew leak).
    home = tmp_path / "home"
    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert trace_path.exists(), "post-merge trace was not written"
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["status"] == "completed"


def test_real_deploy_with_no_smoke_script_is_a_no_op(tmp_path: Path) -> None:
    """If ``scripts/hapax-post-merge-smoke`` is absent (e.g. on a repo
    that hasn't yet adopted the smoke runner), the deploy script
    silently skips smoke and completes normally — backward-compatible
    with the pre-#2148 deploy chain."""
    repo, sha = _repo_with_merge_commit(tmp_path)
    # HOME MUST be isolated: the deploy computes LOCAL_BIN=$HOME/.local/bin and
    # symlinks the fixture's scripts/hapax-demo into it. Without this override a
    # *real* deploy leaks ~/.local/bin/hapax-demo into the operator's PATH that
    # dangles the moment pytest cleans tmp_path (the fix-deploy-symlink-skew
    # leak — every other test here already isolates HOME for the same reason).
    home = tmp_path / "home"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"

    smoke_stub = repo / "scripts" / "hapax-post-merge-smoke"
    assert not smoke_stub.exists(), "fixture should not include smoke script"

    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert trace_path.exists()


def _music_player_unit_body() -> str:
    return (
        "[Unit]\n"
        "Description=Music player\n"
        "\n"
        "[Service]\n"
        "ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python "
        "-m agents.local_music_player\n"
    )


def test_audio_safe_failure_defers_deploy_when_no_live_broadcast(tmp_path: Path) -> None:
    """A hard audio-safe-restart failure (rc>=2 — e.g. audio is intentionally
    down so its broadcast-clean verify can't pass) must NOT abort the whole
    deploy when there is no live broadcast on the line. The deploy DEFERS the
    audio restart (retried next cycle) and still completes (exit 0) so unrelated
    units — e.g. #3850's SDLC ``cpu.idle`` slice — still install.

    Regression for the reform deploy-decouple: previously the bare
    ``return "$safe_rc"`` propagated rc=2 under ``set -e`` and aborted every
    deploy for as long as audio stayed down.
    """
    unit_path = "systemd/units/hapax-music-player.service"
    repo, sha = _repo_with_linear_commit(tmp_path, {unit_path: _music_player_unit_body()})
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl_with_compositor_state(
        tmp_path, compositor_active=False
    )
    audio_safe_bin, audio_safe_calls = _fake_audio_safe_restart(bin_dir, tmp_path, exit_code=2)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_AUDIO_SAFE_RESTART_BIN": str(audio_safe_bin),
        "HAPAX_AUDIO_SAFE_RESTART_CALLS": str(audio_safe_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    # the audio-safe restart was actually attempted (and failed, rc=2)
    assert audio_safe_calls.read_text(encoding="utf-8").splitlines() == [
        "hapax-music-player.service"
    ]
    # it probed for a live broadcast and, finding none, deferred rather than aborted
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user is-active --quiet studio-compositor.service" in calls
    assert "DEFERRING" in result.stderr
    # the deploy still ran to completion despite the deferred audio restart
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["status"] == "completed"


def test_audio_safe_failure_aborts_deploy_during_live_broadcast(tmp_path: Path) -> None:
    """If a live broadcast IS on the line (``studio-compositor.service`` active),
    a hard audio-safe-restart failure must still ABORT the deploy (exit 2):
    breaking the audio chain mid-stream is more critical than deferring a unit
    install. This pins the broadcast-protecting half of the decouple.
    """
    unit_path = "systemd/units/hapax-music-player.service"
    repo, sha = _repo_with_linear_commit(tmp_path, {unit_path: _music_player_unit_body()})
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl_with_compositor_state(
        tmp_path, compositor_active=True
    )
    audio_safe_bin, audio_safe_calls = _fake_audio_safe_restart(bin_dir, tmp_path, exit_code=2)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_AUDIO_SAFE_RESTART_BIN": str(audio_safe_bin),
        "HAPAX_AUDIO_SAFE_RESTART_CALLS": str(audio_safe_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2, (result.returncode, result.stderr)
    assert audio_safe_calls.read_text(encoding="utf-8").splitlines() == [
        "hapax-music-player.service"
    ]
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user is-active --quiet studio-compositor.service" in calls
    assert "LIVE" in result.stderr or "live broadcast" in result.stderr.lower()


# --- deploy-symlink-skew regressions (fix-deploy-symlink-skew-20260602) ---


def test_real_deploy_installs_symlinks_under_isolated_home(tmp_path: Path) -> None:
    """A real deploy MUST install ``scripts/hapax-*`` symlinks under the
    overridden ``$HOME/.local/bin`` — never the operator's real one. Pins the
    isolation contract whose violation leaked a dangling ``~/.local/bin/hapax-demo``
    pointing into a cleaned pytest tmpdir (the skew P0's recurring symptom).
    """
    repo, sha = _repo_with_merge_commit(tmp_path)
    home = tmp_path / "home"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        "HAPAX_DRIFT_NTFY": "0",
    }

    result = subprocess.run(
        [str(SCRIPT), sha], text=True, capture_output=True, check=False, env=env
    )

    assert result.returncode == 0, result.stderr
    leaked = home / ".local" / "bin" / "hapax-demo"
    assert leaked.is_file(), "demo script should install under the isolated home"
    # Copy-from-SHA semantics: a regular file with the release's content, not a
    # symlink into a mutable tree (deploy-scripts-worktree-root-20260611).
    assert not leaked.is_symlink()
    assert leaked.read_text() == (repo / "scripts" / "hapax-demo").read_text()
    # The deploy-end self-check must stay quiet: installed copies are not
    # symlinks, so the drift auditor (symlink-only) has nothing to flag.
    assert "drift" not in result.stderr.lower(), result.stderr


def test_since_invocation_form_is_accepted(tmp_path: Path) -> None:
    """The post-merge-deploy ``.service`` edge-trigger invokes the script as
    ``hapax-post-merge-deploy --since <since> <sha>`` to realize a multi-merge
    backlog in one cumulative deploy. Pin that the script's argument parser
    accepts that exact form and exits 0.

    Regression for fix-deploy-symlink-skew: a ``~/.local/bin`` symlink pointing
    at a STALE worktree (one predating ``--since`` support) made every
    ``.service`` deploy exit 2/INVALIDARGUMENT, silently stranding 9 merged
    commits. This fails loudly if the script ever loses ``--since``.
    """
    repo, sha = _repo_with_merge_commit(tmp_path)
    since = _git(repo, "rev-parse", f"{sha}^1")
    home = tmp_path / "home"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), "--since", since, sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, (result.returncode, result.stderr)


def test_service_unit_since_contract_matches_script() -> None:
    """Static parity guard: if the ``.service`` ExecStart passes ``--since`` the
    script MUST have a ``--since`` handler. This is the precise contract whose
    violation — the wrapper passing a flag the (stale, symlinked) script didn't
    support — stranded the merged-but-undeployed commits.
    """
    unit = (REPO_ROOT / "systemd" / "units" / "hapax-post-merge-deploy.service").read_text(
        encoding="utf-8"
    )
    script_src = SCRIPT.read_text(encoding="utf-8")
    if "--since" in unit:
        assert '"--since"' in script_src, (
            "hapax-post-merge-deploy.service passes --since but the script has no "
            "--since handler — the deploy-symlink-skew arg-contract break."
        )


def _drift_env(tmp_path: Path, bin_dir: Path, **overrides: str) -> dict[str, str]:
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "REPO": str(REPO_ROOT),
        "HAPAX_LOCAL_BIN": str(bin_dir),
        "HAPAX_DRIFT_NTFY": "0",
        "HAPAX_DRIFT_STATE_DIR": str(tmp_path / "state"),
    }
    env.update(overrides)
    return env


def _link(bin_dir: Path, name: str, target: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / name).symlink_to(target)


def _check_drift(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), "--check-symlink-drift"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_check_symlink_drift_passes_when_canonical(tmp_path: Path) -> None:
    """No drift when every ``hapax-*`` symlink resolves under a canonical root."""
    root = tmp_path / "worktree"
    (root / "scripts").mkdir(parents=True)
    demo = root / "scripts" / "hapax-demo"
    demo.write_text("#!/bin/sh\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    _link(bin_dir, "hapax-demo", demo)

    result = _check_drift(_drift_env(tmp_path, bin_dir, HAPAX_DEPLOY_SYMLINK_ROOTS=str(root)))

    assert result.returncode == 0, result.stderr


def test_check_symlink_drift_flags_dangling(tmp_path: Path) -> None:
    """A ``hapax-*`` symlink whose target was removed (deleted worktree / cleaned
    test tmpdir — the skew P0's ``hapax-demo``) is reported as drift, exit 1.
    """
    bin_dir = tmp_path / "bin"
    _link(bin_dir, "hapax-demo", tmp_path / "gone" / "scripts" / "hapax-demo")

    result = _check_drift(_drift_env(tmp_path, bin_dir))

    assert result.returncode == 1, result.stdout
    assert "dangling" in result.stderr
    assert "hapax-demo" in result.stderr


def test_check_symlink_drift_flags_offtree(tmp_path: Path) -> None:
    """A ``hapax-*`` symlink resolving to a ``scripts/`` dir OUTSIDE the canonical
    roots (a stale lane worktree, or a live pytest tmpdir — the exact recurring
    leak) is drift even though the target currently exists.
    """
    foreign = tmp_path / "foreign" / "scripts"
    foreign.mkdir(parents=True)
    demo = foreign / "hapax-demo"
    demo.write_text("#!/bin/sh\n", encoding="utf-8")
    canonical = tmp_path / "worktree"
    (canonical / "scripts").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    _link(bin_dir, "hapax-demo", demo)

    result = _check_drift(_drift_env(tmp_path, bin_dir, HAPAX_DEPLOY_SYMLINK_ROOTS=str(canonical)))

    assert result.returncode == 1, result.stdout
    assert "off-tree" in result.stderr


def test_check_symlink_drift_flags_hapax_script_name_mismatch(tmp_path: Path) -> None:
    """A managed ``hapax-*`` symlink to a different managed script is drift."""
    canonical = tmp_path / "worktree"
    scripts = canonical / "scripts"
    scripts.mkdir(parents=True)
    target = scripts / "hapax-other"
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    _link(bin_dir, "hapax-demo", target)

    result = _check_drift(_drift_env(tmp_path, bin_dir, HAPAX_DEPLOY_SYMLINK_ROOTS=str(canonical)))

    assert result.returncode == 1, result.stdout
    assert "target name mismatch" in result.stderr
    assert "hapax-demo" in result.stderr


def test_check_symlink_drift_ignores_non_script_install_symlinks(tmp_path: Path) -> None:
    """``hapax-hooks-doctor -> ~/.local/lib/hapax/hooks/hooks-doctor.sh`` is a
    manifest-installed hook, not a deploy-tree symlink — its target is not under
    ``*/scripts/*`` so it must NOT be flagged, or the assertion false-positives
    on a healthy system.
    """
    lib = tmp_path / "lib" / "hapax" / "hooks"
    lib.mkdir(parents=True)
    doctor = lib / "hooks-doctor.sh"
    doctor.write_text("#!/bin/sh\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    _link(bin_dir, "hapax-hooks-doctor", doctor)

    result = _check_drift(
        _drift_env(tmp_path, bin_dir, HAPAX_DEPLOY_SYMLINK_ROOTS=str(tmp_path / "wt"))
    )

    assert result.returncode == 0, result.stderr


# --- 2026-06-11 P0 regression: archive resurrection + conf parse-lint ---


def test_archive_confs_are_not_classified_as_deployable(tmp_path):
    """Bash case-globs match across slashes: config/pipewire/archive/** must be
    explicitly excluded or it deploys (the 09:34 P0: 25 archived confs
    resurrected, one syntax-invalid, audio stack start-limit dead)."""

    script = SCRIPT.read_text()
    assert "config/pipewire/archive/*" in script, "archive exclusion branch missing"
    # the exclusion must appear BEFORE the matching deploy branch
    excl = script.index("config/pipewire/archive/*")
    match = script.index("config/pipewire/*.conf)")
    assert excl < match, "exclusion must precede the deploy classification"


def test_pw_deploy_parse_lints_confs(tmp_path):
    script = SCRIPT.read_text()
    assert "spa-json-dump" in script, "conf parse-lint missing from PW deploy path"
    assert "REFUSED (spa-json parse error" in script


def _fake_hooks_doctor() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
from=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --from) from="$2"; shift 2 ;;
        *) shift ;;
    esac
done
from="${from:-$(pwd)}"
if [ -n "${HAPAX_HOOKS_DOCTOR_CALLS:-}" ]; then
    printf '%s\\n' "$from" >> "$HAPAX_HOOKS_DOCTOR_CALLS"
fi
if [ "${HAPAX_FAKE_HOOKS_DOCTOR_FAIL:-0}" = "1" ]; then
    echo "fake hooks-doctor deploy failure" >&2
    exit 23
fi
: "${HAPAX_CANONICAL_HOOKS:?}"
mkdir -p "$HAPAX_CANONICAL_HOOKS"
cp "$from/hooks/scripts/cc-task-gate.impl.sh" "$HAPAX_CANONICAL_HOOKS/cc-task-gate.sh"
for sibling in agent-role.sh escape-grant.sh hapax_check_enable_latch.sh cc-task-gate-bootstrap.py hooks-doctor.sh; do
    cp "$from/hooks/scripts/$sibling" "$HAPAX_CANONICAL_HOOKS/$sibling"
done
"""


def _gate_closure_bodies() -> dict[str, str]:
    return {
        "hooks/scripts/cc-task-gate.impl.sh": (
            "#!/usr/bin/env bash\nis_cognition_path() { return 0; }\necho gate impl\n"
        ),
        "hooks/scripts/agent-role.sh": "#!/usr/bin/env bash\necho agent-role\n",
        "hooks/scripts/escape-grant.sh": "#!/usr/bin/env bash\necho escape-grant\n",
        "hooks/scripts/hapax_check_enable_latch.sh": ("#!/usr/bin/env bash\necho enable-latch\n"),
        "hooks/scripts/cc-task-gate-bootstrap.py": "print('bootstrap')\n",
        "hooks/scripts/hooks-doctor.sh": _fake_hooks_doctor(),
    }


def _repo_with_gate_closure_and_docs_commit(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    for relative, body in _gate_closure_bodies().items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base with gate closure")
    (repo / "docs.md").write_text("docs only\n", encoding="utf-8")
    _git(repo, "add", "docs.md")
    _git(repo, "commit", "-m", "docs only")
    return repo, _git(repo, "rev-parse", "HEAD")


def _seed_canonical_gate(repo: Path, canon: Path, *, stale: bool) -> None:
    canon.mkdir(parents=True, exist_ok=True)
    if stale:
        (canon / "cc-task-gate.sh").write_text(
            "#!/usr/bin/env bash\necho stale\n", encoding="utf-8"
        )
        for sibling in (
            "agent-role.sh",
            "escape-grant.sh",
            "cc-task-gate-bootstrap.py",
            "hooks-doctor.sh",
        ):
            (canon / sibling).write_text(f"stale {sibling}\n", encoding="utf-8")
        return

    (canon / "cc-task-gate.sh").write_text(
        (repo / "hooks" / "scripts" / "cc-task-gate.impl.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for sibling in (
        "agent-role.sh",
        "escape-grant.sh",
        "hapax_check_enable_latch.sh",
        "cc-task-gate-bootstrap.py",
        "hooks-doctor.sh",
    ):
        (canon / sibling).write_text(
            (repo / "hooks" / "scripts" / sibling).read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def _gate_reconcile_env(
    tmp_path: Path, repo: Path, canon: Path, calls: Path, *, fail: bool = False
) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "HAPAX_CANONICAL_HOOKS": str(canon),
        "HAPAX_HOOKS_DOCTOR_CALLS": str(calls),
        "HAPAX_LOCAL_BIN": str(home / ".local" / "bin"),
        "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces" / "post-merge-traces.jsonl"),
        "HAPAX_DRIFT_NTFY": "0",
    }
    env.pop("GITHUB_WORKSPACE", None)
    if fail:
        env["HAPAX_FAKE_HOOKS_DOCTOR_FAIL"] = "1"
    return env


def test_gate_untouched_diff_redeploys_drifted_canonical_gate(tmp_path: Path) -> None:
    repo, sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=True)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "canonical gate drift detected: redeploying canonical gate" in result.stdout
    assert calls.exists(), "drifted canonical gate should invoke hooks-doctor"
    assert (canon / "cc-task-gate.sh").read_text(encoding="utf-8") == (
        repo / "hooks" / "scripts" / "cc-task-gate.impl.sh"
    ).read_text(encoding="utf-8")
    receipt = tmp_path / "traces" / "last-deployed-sha"
    assert receipt.read_text(encoding="utf-8").strip() == sha
    record = json.loads(
        (tmp_path / "traces" / "post-merge-traces.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert record["deploy_groups"]["canonical_gate_closure"] == [
        "hooks/scripts/cc-task-gate.impl.sh"
    ]
    assert record["manual_deploy_needed"] is True
    assert record["manual_deploy_executed"] is True
    assert record["avsdlc"]["runtime_media_witness_required"] is True
    assert record["avsdlc"]["runtime_media_witness_groups"] == ["canonical_gate_closure"]


def test_dry_run_gate_drift_does_not_redeploy(tmp_path: Path) -> None:
    repo, sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=True)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)

    result = subprocess.run(
        [str(SCRIPT), "--dry-run", sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "dry-run: canonical gate drift detected; would redeploy" in result.stdout
    assert not calls.exists(), "dry-run drift should not invoke hooks-doctor"
    assert (canon / "cc-task-gate.sh").read_text(encoding="utf-8") == (
        "#!/usr/bin/env bash\necho stale\n"
    )
    assert not (tmp_path / "traces" / "last-deployed-sha").exists()
    record = json.loads(
        (tmp_path / "traces" / "post-merge-traces.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert record["status"] == "dry_run"
    assert record["deploy_groups"]["canonical_gate_closure"] == [
        "hooks/scripts/cc-task-gate.impl.sh"
    ]
    assert record["manual_deploy_needed"] is True
    assert record["manual_deploy_executed"] is False


def test_no_files_path_gate_drift_success_records_completed_deploy(tmp_path: Path) -> None:
    repo, _ = _repo_with_gate_closure_and_docs_commit(tmp_path)
    _git(repo, "commit", "--allow-empty", "-m", "empty merge")
    sha = _git(repo, "rev-parse", "HEAD")
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=True)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert calls.exists(), "zero-file drift should still invoke hooks-doctor"
    assert (tmp_path / "traces" / "last-deployed-sha").read_text(encoding="utf-8").strip() == sha
    record = json.loads(
        (tmp_path / "traces" / "post-merge-traces.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert record["status"] == "completed"
    assert record["changed_files"] == []
    assert record["deploy_groups"]["canonical_gate_closure"] == [
        "hooks/scripts/cc-task-gate.impl.sh"
    ]
    assert record["manual_deploy_needed"] is True
    assert record["manual_deploy_executed"] is True


def test_healthy_canonical_gate_does_not_redeploy(tmp_path: Path) -> None:
    repo, sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=False)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "canonical gate closure already matches" in result.stdout
    assert not calls.exists(), "healthy canonical gate should not invoke hooks-doctor"
    record = json.loads(
        (tmp_path / "traces" / "post-merge-traces.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert record["deploy_groups"]["canonical_gate_closure"] == []
    assert record["manual_deploy_needed"] is False
    assert record["manual_deploy_executed"] is False


def test_canonical_gate_deploy_failure_does_not_stamp_last_deployed_sha(
    tmp_path: Path,
) -> None:
    repo, sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=True)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls, fail=True)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 23, (result.stdout, result.stderr)
    assert "canonical gate deploy failed" in result.stderr
    assert "next: inspect hooks-doctor --deploy-canonical output" in result.stderr
    assert calls.exists(), "failing deploy should still attempt hooks-doctor"
    assert not (tmp_path / "traces" / "last-deployed-sha").exists()
    assert (canon / "cc-task-gate.sh").read_text(encoding="utf-8") == (
        "#!/usr/bin/env bash\necho stale\n"
    )
    record = json.loads(
        (tmp_path / "traces" / "post-merge-traces.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert record["status"] == "failed"
    assert record["exit_code"] == 23
    assert record["deploy_groups"]["canonical_gate_closure"] == [
        "hooks/scripts/cc-task-gate.impl.sh"
    ]


def test_partial_gate_closure_fails_with_next_action(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    partial = repo / "hooks" / "scripts" / "cc-task-gate.impl.sh"
    partial.parent.mkdir(parents=True)
    partial.write_text("#!/usr/bin/env bash\necho partial\n", encoding="utf-8")
    partial.chmod(0o755)
    _git(repo, "add", str(partial.relative_to(repo)))
    _git(repo, "commit", "-m", "partial gate closure")
    sha = _git(repo, "rev-parse", "HEAD")
    env = _gate_reconcile_env(tmp_path, repo, tmp_path / "canon", tmp_path / "calls.txt")

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "incomplete canonical gate closure" in result.stderr
    assert "next: ensure every GATE_CLOSURE_FILES member exists" in result.stderr
    assert not (tmp_path / "traces" / "last-deployed-sha").exists()


def test_enable_latch_change_counts_as_gate_closure(tmp_path: Path) -> None:
    repo, _ = _repo_with_gate_closure_and_docs_commit(tmp_path)
    latch = repo / "hooks" / "scripts" / "hapax_check_enable_latch.sh"
    latch.write_text("#!/usr/bin/env bash\necho changed-enable-latch\n", encoding="utf-8")
    _git(repo, "add", str(latch.relative_to(repo)))
    _git(repo, "commit", "-m", "change enable latch")
    sha = _git(repo, "rev-parse", "HEAD")
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=True)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "gate closure changed (1): redeploying canonical gate" in result.stdout
    assert (canon / "hapax_check_enable_latch.sh").read_text(encoding="utf-8") == (
        "#!/usr/bin/env bash\necho changed-enable-latch\n"
    )


def test_no_files_path_gate_deploy_failure_does_not_stamp(tmp_path: Path) -> None:
    """The zero-files-changed path must also refuse the stamp when the gate
    redeploy fails (set -e propagates the bare reconcile call — lock it)."""
    repo, _ = _repo_with_gate_closure_and_docs_commit(tmp_path)
    _git(repo, "commit", "--allow-empty", "-m", "empty merge")
    sha = _git(repo, "rev-parse", "HEAD")
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=True)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls, fail=True)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode != 0, (result.stdout, result.stderr)
    assert not (tmp_path / "traces" / "last-deployed-sha").exists()
    assert (canon / "cc-task-gate.sh").read_text(encoding="utf-8") == (
        "#!/usr/bin/env bash\necho stale\n"
    )


def test_reconcile_stages_complete_closure_for_real_hooks_doctor(tmp_path: Path) -> None:
    """Contract test against the REPOSITORY hooks-doctor: deploy_canonical
    refuses an incomplete staged closure, so the script's GATE_CLOSURE_FILES
    must stay a superset of hooks-doctor's CLOSURE_SIBLINGS. A fake doctor
    with a shortened list would hide exactly that regression."""
    real_doctor = (REPO_ROOT / "hooks" / "scripts" / "hooks-doctor.sh").read_text(encoding="utf-8")
    bodies = _gate_closure_bodies()
    bodies["hooks/scripts/hooks-doctor.sh"] = real_doctor
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    for relative, body in bodies.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base with real-doctor gate closure")
    (repo / "docs.md").write_text("docs only\n", encoding="utf-8")
    _git(repo, "add", "docs.md")
    _git(repo, "commit", "-m", "docs only")
    sha = _git(repo, "rev-parse", "HEAD")
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=True)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
    deployed = (canon / "cc-task-gate.sh").read_text(encoding="utf-8")
    assert "is_cognition_path" in deployed, "real hooks-doctor must accept the staged closure"
    assert (canon / "hapax_check_enable_latch.sh").exists()

    second = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert second.returncode == 0, (second.stdout, second.stderr)
    assert "canonical gate closure already matches" in second.stdout


def test_check_symlink_drift_ignores_legacy_alias_to_nonmatching_script(
    tmp_path: Path,
) -> None:
    """``hapax-request-decompose -> scripts/request-decompose`` is a legacy alias,
    not a deploy-managed ``scripts/hapax-*`` link. The live unit runs
    ``scripts/request-decompose`` directly, so the drift auditor should stop
    advertising this alias as off-tree deploy drift.
    """
    foreign = tmp_path / "foreign" / "scripts"
    foreign.mkdir(parents=True)
    target = foreign / "request-decompose"
    target.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    _link(bin_dir, "hapax-request-decompose", target)

    result = _check_drift(
        _drift_env(tmp_path, bin_dir, HAPAX_DEPLOY_SYMLINK_ROOTS=str(tmp_path / "wt"))
    )

    assert result.returncode == 0, result.stderr
