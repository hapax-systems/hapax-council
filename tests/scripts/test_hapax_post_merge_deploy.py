"""Path-coverage tests for ``scripts/hapax-post-merge-deploy``."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pwd
import re
import shlex
import signal
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-post-merge-deploy"
SMOKE = REPO_ROOT / "scripts" / "hapax-post-merge-smoke"
PRE_GUARD_DEPLOY_SHA = "24fea952007ca370ba97a3e93fe5c6797a1287d6"
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
    relative: "[Service]\nOOMScoreAdjust=100\n"
    for relative in {
        "systemd/units/pipewire.service.d/oom-protect.conf": "pipewire.service",
        "systemd/units/pipewire-pulse.service.d/oom-protect.conf": "pipewire-pulse.service",
        "systemd/units/wireplumber.service.d/oom-protect.conf": "wireplumber.service",
        "systemd/units/hapax-daimonion.service.d/oom-protect.conf": "hapax-daimonion.service",
        "systemd/units/studio-compositor.service.d/oom-protect.conf": "studio-compositor.service",
        "systemd/units/hapax-imagination.service.d/oom-protect.conf": "hapax-imagination.service",
    }
}
P0_PROTECTED_APP_UNITS = {
    relative: (REPO_ROOT / relative).read_text(encoding="utf-8")
    for relative in (
        "systemd/units/hapax-daimonion.service",
        "systemd/units/studio-compositor.service",
        "systemd/units/hapax-imagination.service",
    )
}
OOM_HOST_POLICY_FILES = {
    relative: (REPO_ROOT / relative).read_text(encoding="utf-8")
    for relative in (
        "config/root-required/oom-host-profiles.tsv",
        "config/root-required/oom-host-policy/appendix/app.slice.conf",
        "config/root-required/oom-host-policy/appendix/user-1000.slice.conf",
        "config/root-required/oom-host-policy/appendix/user@1000.service.conf",
        "config/root-required/oom-host-policy/appendix/zram-generator.conf",
        "config/root-required/oom-host-policy/podium/app.slice.conf",
        "config/root-required/oom-host-policy/podium/user-1000.slice.conf",
        "config/root-required/oom-host-policy/podium/user@1000.service.conf",
        "config/root-required/oom-host-policy/podium/zram-generator.conf",
    )
}
P0_OOM_AUDIT_FILES = {
    **OOM_HOST_POLICY_FILES,
    "scripts/hapax-oom-policy-audit": "#!/usr/bin/env python3\n",
    "scripts/hapax-root-required-deploy-audit": "#!/usr/bin/env bash\n",
    "systemd/units/hapax-oom-policy-audit.service": (
        "[Unit]\nDescription=OOM audit\nOnFailure=notify-failure@%n.service\n"
        "[Service]\nType=oneshot\n"
        "TimeoutStartSec=2min\n"
        "Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin\n"
        "ExecStart=/usr/local/sbin/hapax-oom-policy-audit --json\n"
    ),
    "systemd/units/hapax-oom-policy-audit.timer": (
        "[Unit]\nDescription=OOM audit timer\n[Timer]\nOnBootSec=2min\n"
        "OnUnitActiveSec=5min\nUnit=hapax-oom-policy-audit.service\n"
    ),
    "systemd/units/hapax-root-required-deploy-audit.service": (
        REPO_ROOT / "systemd/units/hapax-root-required-deploy-audit.service"
    ).read_text(encoding="utf-8"),
    "systemd/units/hapax-root-required-deploy-audit.timer": (
        "[Unit]\nDescription=Root deploy audit timer\n[Timer]\nOnBootSec=3min\n"
        "OnUnitActiveSec=10min\nUnit=hapax-root-required-deploy-audit.service\n"
    ),
}
ROOT_AUDIT_SOURCE_FILES = {
    "config/root-required/oom-containment.files": OOM_PACKAGE_MANIFEST,
    "config/root-required/apcupsd-power-alerts.files": APCUPSD_PACKAGE_MANIFEST,
    "scripts/install-p0-oom-containment": "#!/usr/bin/env bash\n",
    "config/root-required/hapax-oom-score-enforce.sudoers": (
        "Cmnd_Alias HAPAX_ROOT_REQUIRED_AUDIT = /usr/bin/visudo -cf "
        "/etc/sudoers.d/hapax-oom-score-enforce\n"
        "hapax ALL=(root) NOPASSWD:NOSETENV: HAPAX_ROOT_REQUIRED_AUDIT\n"
    ),
    "scripts/install-apcupsd-power-alerts": "#!/usr/bin/env bash\n",
    "scripts/hapax-oom-score-enforce": "#!/usr/bin/env bash\necho enforcer\n",
    "scripts/hapax-oom-score-trigger": "#!/usr/bin/env bash\necho trigger\n",
    "scripts/hapax-root-failure-intake": "#!/usr/bin/env bash\necho root failure\n",
    **P0_PROTECTED_APP_UNITS,
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
        "[Unit]\n# Hapax-Install-Scope: system\n"
        "StartLimitIntervalSec=1h\nStartLimitBurst=1\n"
        "[Service]\nType=oneshot\nUser=hapax\n"
        "Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin\n"
        "ExecStart=/usr/local/sbin/hapax-root-failure-intake %i\n"
    ),
    "systemd/units/hapax-oom-score-enforce.service": (
        "[Unit]\n# Hapax-Install-Scope: system\n"
        "[Service]\nType=oneshot\nTimeoutStartSec=5s\n"
        "ExecStart=/usr/local/sbin/hapax-oom-score-enforce --apply\n"
    ),
    "systemd/units/hapax-oom-score-enforce.timer": (
        "[Unit]\n# Hapax-Install-Scope: system\n[Timer]\nOnBootSec=120s\n"
        "OnUnitActiveSec=120s\nUnit=hapax-oom-score-enforce.service\n"
    ),
    "systemd/units/app.slice.d/oom-containment.conf": (
        "[Slice]\nMemoryHigh=72G\nMemoryMax=88G\nMemorySwapMax=8G\nMemoryLow=16G\nMemoryMin=8G\n"
    ),
    "systemd/units/session.slice.d/oom-containment.conf": (
        "[Slice]\nMemoryHigh=infinity\nMemoryMax=infinity\nMemorySwapMax=infinity\n"
        "MemoryLow=2G\nMemoryMin=1G\n"
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


def _write_fake_systemd_run(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
runtime=60
runtime_seen=0
user_seen=0
wait_seen=0
pipe_seen=0
collect_seen=0
service_type_seen=0
expand_disabled_seen=0
memory_high_seen=0
memory_max_seen=0
tasks_max_seen=0
stop_timeout_seen=0
kill_mode_seen=0
sigkill_seen=0
no_ask_seen=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --user) user_seen=1 ;;
        --wait) wait_seen=1 ;;
        --pipe) pipe_seen=1 ;;
        --collect) collect_seen=1 ;;
        --service-type=exec) service_type_seen=1 ;;
        --expand-environment=no) expand_disabled_seen=1 ;;
        --property=RuntimeMaxSec=*) runtime_seen=1; runtime="${1#*=}"; runtime="${runtime%s}" ;;
        --property=MemoryHigh=1536M) memory_high_seen=1 ;;
        --property=MemoryMax=2G) memory_max_seen=1 ;;
        --property=TasksMax=512) tasks_max_seen=1 ;;
        --property=TimeoutStopSec=1s) stop_timeout_seen=1 ;;
        --property=KillMode=control-group) kill_mode_seen=1 ;;
        --property=SendSIGKILL=yes) sigkill_seen=1 ;;
        --no-ask-password) no_ask_seen=1 ;;
        --setenv=*=*) export "${1#--setenv=}" ;;
        --) shift; break ;;
    esac
    shift
done
if [ "$runtime_seen$user_seen$wait_seen$pipe_seen$collect_seen$service_type_seen$expand_disabled_seen$memory_high_seen$memory_max_seen$tasks_max_seen$stop_timeout_seen$kill_mode_seen$sigkill_seen$no_ask_seen" != 11111111111111 ]; then
    echo "fake systemd-run: missing bounded-service contract" >&2
    exit 92
fi
/usr/bin/setsid --wait "$@" &
leader=$!
deadline=$((SECONDS + runtime))
while kill -0 "$leader" 2>/dev/null; do
    if [ "$SECONDS" -ge "$deadline" ]; then
        kill -TERM -- "-$leader" 2>/dev/null || true
        sleep 0.1
        kill -KILL -- "-$leader" 2>/dev/null || true
        wait "$leader" 2>/dev/null || true
        exit 137
    fi
    sleep 0.02
done
rc=0
wait "$leader" || rc=$?
if [ -n "${HAPAX_TEST_SMOKE_DESCENDANT_PID_FILE:-}" ] \
    && [ -s "$HAPAX_TEST_SMOKE_DESCENDANT_PID_FILE" ]; then
    read -r descendant < "$HAPAX_TEST_SMOKE_DESCENDANT_PID_FILE"
    kill -TERM "$descendant" 2>/dev/null || true
    sleep 0.05
    kill -KILL "$descendant" 2>/dev/null || true
fi
exit "$rc"
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


@pytest.fixture(autouse=True)
def _isolate_root_required_mutation_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_ROOT_REQUIRED_ISOLATED_TEST_ROOT", str(tmp_path))
    systemd_run = tmp_path / "systemd-run"
    _write_fake_systemd_run(systemd_run)
    monkeypatch.setenv("HAPAX_POST_MERGE_SYSTEMD_RUN_BIN", str(systemd_run))


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


def _deploy_cursor_marker(home: Path) -> Path:
    return home / ".local/state/hapax/root-required/post-merge-deploy-cursor-established"


def _flock_identities(expected_lock: Path) -> set[tuple[int, int, int]]:
    expected = expected_lock.stat()
    identities = {(os.major(expected.st_dev), os.minor(expected.st_dev), expected.st_ino)}
    try:
        mount_lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return identities

    resolved = expected_lock.resolve()
    best_depth = -1
    best_device: tuple[int, int] | None = None
    for line in mount_lines:
        fields = line.partition(" - ")[0].split()
        if len(fields) < 5:
            continue
        mountpoint = Path(
            re.sub(
                r"\\([0-7]{3})",
                lambda match: chr(int(match.group(1), 8)),
                fields[4],
            )
        )
        if resolved != mountpoint and not resolved.is_relative_to(mountpoint):
            continue
        try:
            major_raw, minor_raw = fields[2].split(":", 1)
            device = (int(major_raw), int(minor_raw))
        except ValueError:
            continue
        depth = len(mountpoint.parts)
        if depth > best_depth:
            best_depth = depth
            best_device = device
    if best_device is not None:
        identities.add((*best_device, expected.st_ino))
    return identities


def _wait_for_flock_block(
    process: subprocess.Popen[str], expected_lock: Path, *, timeout: float = 10
) -> None:
    expected_identities = _flock_identities(expected_lock)
    deadline = time.monotonic() + timeout
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
        try:
            lock_lines = Path("/proc/locks").read_text(encoding="utf-8").splitlines()
        except OSError:
            lock_lines = []
        for line in lock_lines:
            fields = line.split()
            if len(fields) < 7 or fields[1:3] != ["->", "FLOCK"]:
                continue
            try:
                waiter_pid = int(fields[5])
                major_raw, minor_raw, inode_raw = fields[6].split(":", 2)
                identity = (int(major_raw, 16), int(minor_raw, 16), int(inode_raw))
            except (ValueError, IndexError):
                continue
            if waiter_pid in descendants and identity in expected_identities:
                return
        time.sleep(0.01)
    raise AssertionError(f"child did not reach the deterministic flock wait on {expected_lock}")


def test_wait_for_flock_block_requires_expected_inode(tmp_path: Path) -> None:
    expected = tmp_path / "expected.lock"
    unrelated = tmp_path / "unrelated.lock"
    expected.write_text("", encoding="utf-8")
    unrelated.write_text("", encoding="utf-8")
    blocker_fd = os.open(unrelated, os.O_RDWR)
    fcntl.flock(blocker_fd, fcntl.LOCK_EX)
    process = subprocess.Popen(
        [
            "/usr/bin/python3",
            "-I",
            "-S",
            "-c",
            (
                "import fcntl, os, sys; "
                "fd = os.open(sys.argv[1], os.O_RDWR); "
                "fcntl.flock(fd, fcntl.LOCK_EX)"
            ),
            str(unrelated),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _wait_for_flock_block(process, unrelated)
        with pytest.raises(AssertionError, match="deterministic flock wait"):
            _wait_for_flock_block(process, expected, timeout=0.2)
    finally:
        fcntl.flock(blocker_fd, fcntl.LOCK_UN)
        os.close(blocker_fd)
        if process.poll() is None:
            _kill_process_group(process)


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=5)


def _fake_git_with_show_failure(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "git-bin"
    bin_dir.mkdir()
    fake = bin_dir / "git"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "matched=0\n"
        "previous=\n"
        'for arg in "$@"; do\n'
        '    if [ "$previous" = show ] && [ "$arg" = "$HAPAX_FAIL_GIT_SHOW_OBJECT" ]; then\n'
        "        matched=1\n"
        "        break\n"
        "    fi\n"
        '    previous="$arg"\n'
        "done\n"
        'if [ "$matched" = 1 ]; then\n'
        "    count=0\n"
        '    if [ -f "$HAPAX_FAIL_GIT_SHOW_COUNT_FILE" ]; then\n'
        '        read -r count < "$HAPAX_FAIL_GIT_SHOW_COUNT_FILE"\n'
        "    fi\n"
        "    count=$((count + 1))\n"
        '    printf \'%s\\n\' "$count" > "$HAPAX_FAIL_GIT_SHOW_COUNT_FILE"\n'
        '    if [ "$count" -eq "$HAPAX_FAIL_GIT_SHOW_ON_COUNT" ]; then\n'
        "        exit 86\n"
        "    fi\n"
        "fi\n"
        'exec /usr/bin/git "$@"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return bin_dir


def _fake_git_with_ls_tree_failure(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "git-bin"
    bin_dir.mkdir()
    fake = bin_dir / "git"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "matched=0\n"
        "subcommand=\n"
        'for arg in "$@"; do\n'
        '    if [ "$arg" = ls-tree ]; then\n'
        "        subcommand=ls-tree\n"
        '    elif [ "$subcommand" = ls-tree ] && [ "$arg" = "$HAPAX_FAIL_GIT_LS_TREE_PATH" ]; then\n'
        "        matched=1\n"
        "    fi\n"
        "done\n"
        'if [ "$matched" = 1 ]; then\n'
        "    count=0\n"
        '    if [ -f "$HAPAX_FAIL_GIT_LS_TREE_COUNT_FILE" ]; then\n'
        '        read -r count < "$HAPAX_FAIL_GIT_LS_TREE_COUNT_FILE"\n'
        "    fi\n"
        "    count=$((count + 1))\n"
        '    printf \'%s\\n\' "$count" > "$HAPAX_FAIL_GIT_LS_TREE_COUNT_FILE"\n'
        '    if [ "$count" -eq "$HAPAX_FAIL_GIT_LS_TREE_ON_COUNT" ]; then\n'
        "        exit 86\n"
        "    fi\n"
        "fi\n"
        'exec /usr/bin/git "$@"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return bin_dir


def _post_merge_script_with_system_dir(
    tmp_path: Path,
    system_dir: Path,
    *,
    expected_uid: int | None = None,
) -> Path:
    staged = tmp_path / "hapax-post-merge-deploy"
    source = SCRIPT.read_text(encoding="utf-8")
    production_assignment = 'SYSTEMD_SYSTEM_DIR="/etc/systemd/system"'
    production_uid = "SYSTEMD_SYSTEM_EXPECTED_UID=0"
    production_trust_root = 'SYSTEMD_SYSTEM_TRUST_ROOT="/"'
    assert source.count(production_assignment) == 1
    assert source.count(production_uid) == 1
    assert source.count(production_trust_root) == 1
    staged.write_text(
        source.replace(
            production_assignment,
            f"SYSTEMD_SYSTEM_DIR={shlex.quote(str(system_dir))}",
        )
        .replace(
            production_uid,
            f"SYSTEMD_SYSTEM_EXPECTED_UID={os.geteuid() if expected_uid is None else expected_uid}",
        )
        .replace(
            production_trust_root,
            f"SYSTEMD_SYSTEM_TRUST_ROOT={shlex.quote(str(system_dir))}",
        ),
        encoding="utf-8",
    )
    staged.chmod(0o755)
    return staged


def _post_merge_script_with_cursor_fsync_failure(tmp_path: Path) -> Path:
    staged = tmp_path / "hapax-post-merge-deploy-fsync-failure"
    source = SCRIPT.read_text(encoding="utf-8")
    needle = """def fsync_dir(parent: Path) -> None:
    dir_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
"""
    replacement = """cursor_test_fsync_counts: dict[str, int] = {}


def fsync_dir(parent: Path) -> None:
    parent_key = str(parent.absolute())
    cursor_test_fsync_counts[parent_key] = cursor_test_fsync_counts.get(parent_key, 0) + 1
    if (
        parent_key == os.environ.get("HAPAX_TEST_CURSOR_FSYNC_PARENT")
        and cursor_test_fsync_counts[parent_key]
        == int(os.environ.get("HAPAX_TEST_CURSOR_FSYNC_COUNT", "2"))
    ):
        raise OSError("injected post-replace cursor directory sync failure")
    dir_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
"""
    assert source.count(needle) == 1
    staged.write_text(source.replace(needle, replacement), encoding="utf-8")
    staged.chmod(0o755)
    return staged


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


def _effective_safety_unit_show_script(system_dir: Path, user_dir: Path) -> str:
    lines: list[str] = []
    canonical_home = pwd.getpwuid(os.getuid()).pw_dir
    canonical_runtime = f"/run/user/{os.getuid()}"
    services = (
        (
            "system",
            "hapax-oom-score-enforce.service",
            system_dir / "hapax-oom-score-enforce.service",
            "/usr/local/sbin/hapax-oom-score-enforce --apply",
            "",
        ),
        (
            "user",
            "hapax-oom-policy-audit.service",
            user_dir / "hapax-oom-policy-audit.service",
            "/usr/local/sbin/hapax-oom-policy-audit --json",
            "notify-failure@hapax-oom-policy-audit.service.service",
        ),
        (
            "user",
            "hapax-root-required-deploy-audit.service",
            user_dir / "hapax-root-required-deploy-audit.service",
            "/usr/bin/env -i "
            f"HOME={canonical_home} XDG_RUNTIME_DIR={canonical_runtime} "
            "PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin LANG=C LC_ALL=C "
            "/usr/local/sbin/hapax-root-required-deploy-audit",
            "notify-failure@hapax-root-required-deploy-audit.service.service",
        ),
    )
    for manager, unit, fragment, exec_start, on_failure in services:
        prefix = "--user show" if manager == "user" else "show"
        properties = {
            "FragmentPath": str(fragment),
            "DropInPaths": "",
            "NeedDaemonReload": "no",
            "ExecStart": f"{{ path={exec_start.split()[0]} ; argv[]={exec_start} ; }}",
            "OnFailure": on_failure,
            "User": "",
        }
        for prop, value in properties.items():
            lines.append(
                f'if [ "$*" = "{prefix} {unit} -p {prop} --value" ]; '
                f"then printf '%s\\n' '{value}'; fi\n"
            )
    timers = (
        (
            "system",
            "hapax-oom-score-enforce.timer",
            system_dir / "hapax-oom-score-enforce.timer",
            "hapax-oom-score-enforce.service",
            "120s",
            "120s",
        ),
        (
            "user",
            "hapax-oom-policy-audit.timer",
            user_dir / "hapax-oom-policy-audit.timer",
            "hapax-oom-policy-audit.service",
            "2min",
            "5min",
        ),
        (
            "user",
            "hapax-root-required-deploy-audit.timer",
            user_dir / "hapax-root-required-deploy-audit.timer",
            "hapax-root-required-deploy-audit.service",
            "3min",
            "10min",
        ),
    )
    for manager, unit, fragment, target, on_boot, on_active in timers:
        prefix = "--user show" if manager == "user" else "show"
        properties = {
            "FragmentPath": str(fragment),
            "DropInPaths": "",
            "NeedDaemonReload": "no",
            "Unit": target,
            "TimersMonotonic": (f"OnBootUSec={on_boot} OnUnitActiveUSec={on_active}"),
        }
        for prop, value in properties.items():
            lines.append(
                f'if [ "$*" = "{prefix} {unit} -p {prop} --value" ]; '
                f"then printf '%s\\n' '{value}'; fi\n"
            )
    return "".join(lines)


def _root_audit_env(
    tmp_path: Path,
    *,
    drift_rel: str | None = None,
    missing_source_rel: str | None = None,
) -> dict[str, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source_root = tmp_path / "source"
    installed_source = tmp_path / "installed-source"
    root_defer = tmp_path / "no-deferrals"
    state_root = tmp_path / "root-state"
    receipt_root = root_defer / "installed-receipts"
    desired_root = state_root / "desired-receipts"
    system_dir = tmp_path / "etc" / "systemd" / "system"
    apcupsd_dir = tmp_path / "etc" / "apcupsd"
    apcupsd_audit_log = tmp_path / "var" / "log" / "hapax" / "ups-power-events.jsonl"
    logrotate_dest = tmp_path / "etc" / "logrotate.d" / "hapax-ups-power-events"
    upower_dest = tmp_path / "etc" / "UPower" / "UPower.conf.d" / "90-hapax-apcupsd-owner.conf"
    enforcer_dest = tmp_path / "sbin" / "hapax-oom-score-enforce"
    trigger_dest = tmp_path / "bin" / "hapax-oom-score-trigger"
    sudoers_dest = tmp_path / "etc" / "sudoers.d" / "hapax-oom-score-enforce"
    sudoers_reference_dest = tmp_path / "share" / "hapax-oom-score-enforce.sudoers"
    profile_table_dest = tmp_path / "share" / "oom-host-profiles.tsv"
    zram_generator_dest = tmp_path / "etc" / "systemd" / "zram-generator.conf"
    root_failure_dest = tmp_path / "sbin" / "hapax-root-failure-intake"
    oom_audit_dest = tmp_path / "sbin" / "hapax-oom-policy-audit"
    root_audit_dest = tmp_path / "sbin" / "hapax-root-required-deploy-audit"
    user_dir = tmp_path / "home" / ".config" / "systemd" / "user"
    earlyoom_dest = tmp_path / "etc" / "default" / "earlyoom"
    fake_systemctl = tmp_path / "root-audit-systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$*" = "is-enabled hapax-oom-score-enforce.timer" ]; then printf "static\\n"; exit 0; fi\n'
        'if [ "$*" = "is-active --quiet hapax-oom-score-enforce.timer" ]; then exit 1; fi\n'
        'if [ "$*" = "show hapax-oom-score-enforce.service -p TimeoutStartUSec --value" ]; then printf "5s\\n"; fi\n'
        'if [ "$*" = "--user show hapax-oom-policy-audit.service -p TimeoutStartUSec --value" ]; then printf "2min\\n"; fi\n'
        'if [ "$*" = "--user show hapax-root-required-deploy-audit.service -p TimeoutStartUSec --value" ]; then printf "2min\\n"; fi\n'
        'if [ "$*" = "--user show hapax-oom-policy-audit.service -p Environment --value" ]; then printf "PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin\\n"; fi\n'
        'if [ "$*" = "--user show hapax-root-required-deploy-audit.service -p Environment --value" ]; then printf "PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin\\n"; fi\n'
        f"{_effective_safety_unit_show_script(system_dir, user_dir)}"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    fake_busctl = tmp_path / "root-audit-busctl"
    fake_busctl.write_text("#!/bin/sh\nprintf '%s\\n' 's \"Ignore\"'\n", encoding="utf-8")
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
    sudo_calls = tmp_path / "root-audit-sudo-calls"
    fake_sudo = tmp_path / "root-audit-sudo"
    fake_sudo.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {sudo_calls!s}\n"
        '[ "${1:-}" != "-n" ] || shift\n'
        'exec "$@"\n',
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    dests = {
        "scripts/hapax-oom-score-enforce": enforcer_dest,
        "scripts/hapax-oom-score-trigger": trigger_dest,
        "config/root-required/hapax-oom-score-enforce.sudoers": sudoers_dest,
        "config/root-required/oom-host-profiles.tsv": profile_table_dest,
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
    selected_profile_dests = {
        "config/root-required/oom-host-policy/appendix/app.slice.conf": (
            user_dir / "app.slice.d" / "oom-containment.conf"
        ),
        "config/root-required/oom-host-policy/appendix/user-1000.slice.conf": (
            system_dir / "user-1000.slice.d" / "oom-containment.conf"
        ),
        "config/root-required/oom-host-policy/appendix/user@1000.service.conf": (
            system_dir / "user@1000.service.d" / "oom.conf"
        ),
        "config/root-required/oom-host-policy/appendix/zram-generator.conf": (zram_generator_dest),
    }
    for rel, dest in selected_profile_dests.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(ROOT_AUDIT_SOURCE_FILES[rel], encoding="utf-8")
    sudoers_reference_dest.parent.mkdir(parents=True, exist_ok=True)
    sudoers_reference_dest.write_text(
        ROOT_AUDIT_SOURCE_FILES["config/root-required/hapax-oom-score-enforce.sudoers"],
        encoding="utf-8",
    )
    sudoers_reference_dest.chmod(0o444)
    apcupsd_audit_log.parent.mkdir(parents=True)
    apcupsd_audit_log.write_text("", encoding="utf-8")
    apcupsd_audit_log.chmod(0o640)
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
        "HAPAX_OOM_SUDOERS_REFERENCE_DEST": str(sudoers_reference_dest),
        "HAPAX_OOM_PROFILE_TABLE_DEST": str(profile_table_dest),
        "HAPAX_OOM_ZRAM_GENERATOR_DEST": str(zram_generator_dest),
        "HAPAX_OOM_SUDOERS_OWNER_UID": str(os.getuid()),
        "HAPAX_OOM_SUDOERS_OWNER_GID": str(os.getgid()),
        "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(root_failure_dest),
        "HAPAX_OOM_POLICY_AUDIT_DEST": str(oom_audit_dest),
        "HAPAX_ROOT_REQUIRED_AUDIT_DEST": str(root_audit_dest),
        "HAPAX_OOM_EARLYOOM_DEST": str(earlyoom_dest),
        "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(system_dir),
        "HAPAX_OOM_SYSTEMD_USER_DIR": str(user_dir),
        "HAPAX_APCUPSD_DEST": str(apcupsd_dir),
        "HAPAX_UPS_AUDIT_LOG": str(apcupsd_audit_log),
        "HAPAX_UPS_AUDIT_LOG_OWNER_UID": str(os.getuid()),
        "HAPAX_UPS_AUDIT_LOG_OWNER_GID": str(os.getgid()),
        "HAPAX_APCUPSD_LOGROTATE_DEST": str(logrotate_dest),
        "HAPAX_UPOWER_CONF_DEST": str(upower_dest),
        "HAPAX_ROOT_AUDIT_SYSTEMCTL": str(fake_systemctl),
        "HAPAX_ROOT_AUDIT_BUSCTL": str(fake_busctl),
        "HAPAX_ROOT_AUDIT_APCACCESS": str(fake_apcaccess),
        "HAPAX_ROOT_AUDIT_SUDO": str(fake_sudo),
        "HAPAX_ROOT_AUDIT_VISUDO": str(fake_visudo),
        "HAPAX_ROOT_AUDIT_TEST_MODE": "1",
        "HAPAX_ROOT_AUDIT_HOSTNAME": "hapax-appendix",
        "HAPAX_ROOT_AUDIT_MEMTOTAL_KIB": str(60 * 1024**2),
        "HAPAX_TEST_ROOT_AUDIT_SUDO_CALLS": str(sudo_calls),
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
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'case "$*" in\n'
        '  "--user show "*" -p LoadState --value") printf \'loaded\\n\' ;;\n'
        '  "--user show "*" -p ActiveState --value") printf \'inactive\\n\' ;;\n'
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return bin_dir, calls


def _fake_systemctl_with_system_witness(tmp_path: Path, system_dir: Path) -> tuple[Path, Path]:
    calls = tmp_path / "systemctl-calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "systemctl"
    fake.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"
if [ "${{1:-}}" = show ]; then
    unit="${{2:?}}"
    path="{system_dir}/$unit"
    case "$*" in
        *" --property=LoadState,FragmentPath,DropInPaths,NeedDaemonReload --no-pager")
            if [ -f "$path" ]; then
                printf 'LoadState=loaded\nFragmentPath=%s\n' "$path"
            else
                printf 'LoadState=not-found\nFragmentPath=\n'
            fi
            printf 'DropInPaths='
            separator=
            for dropin in "$path.d"/*.conf; do
                [ -f "$dropin" ] || continue
                printf '%s%s' "$separator" "$dropin"
                separator=' '
            done
            printf '\n'
            marker="${{HAPAX_SYSTEMCTL_NEEDS_RELOAD_MARKER:-}}"
            if [ -n "$marker" ] && [ -e "$marker" ]; then
                printf 'NeedDaemonReload=yes\n'
            else
                printf 'NeedDaemonReload=no\n'
            fi
            ;;
        *" -p LoadState --value") [ -f "$path" ] && printf 'loaded\n' || printf 'not-found\n' ;;
        *" -p FragmentPath --value") [ ! -f "$path" ] || printf '%s\n' "$path" ;;
        *" -p NeedDaemonReload --value")
            marker="${{HAPAX_SYSTEMCTL_NEEDS_RELOAD_MARKER:-}}"
            if [ -n "$marker" ] && [ -e "$marker" ]; then printf 'yes\n'; else printf 'no\n'; fi
            ;;
        *) exit 97 ;;
    esac
elif [ "${{1:-}}" = --user ] && [ "${{2:-}}" = show ]; then
    case "$*" in
        *" --property=LoadState,FragmentPath,ActiveState,SubState --no-pager")
            printf 'LoadState=not-found\nFragmentPath=\nActiveState=inactive\nSubState=dead\n'
            ;;
        *) exit 97 ;;
    esac
fi
exit 0
""",
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


def test_trace_writer_takes_its_own_lock_for_dry_runs() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    trace_writer = source.split("record_post_merge_trace() {", 1)[1].split(
        "\n}\n\ntrace_on_exit()", 1
    )[0]

    assert "fcntl.flock" in trace_writer
    assert "LOCK_EX" in trace_writer


def test_deploy_ignores_repository_replace_refs(tmp_path: Path) -> None:
    path = "systemd/uncovered/replacement-hidden.conf"
    repo, sha = _repo_with_linear_commit(tmp_path, {path: "hidden by replacement\n"})
    parent = _git(repo, "rev-parse", f"{sha}^1")
    replacement = _git(
        repo,
        "commit-tree",
        f"{parent}^{{tree}}",
        "-p",
        parent,
        "-m",
        "replacement hides changed path",
    )
    _git(repo, "replace", sha, replacement)
    assert _git(repo, "diff", "--name-only", f"{sha}^1", sha) == ""

    env = {**os.environ, "REPO": str(repo)}
    env.pop("GIT_NO_REPLACE_OBJECTS", None)
    result = subprocess.run(
        [str(SCRIPT), "--report-coverage", sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert path in result.stderr


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
            "systemd/units/session.slice.d/oom-containment.conf",
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


def test_p0_oom_deploy_validates_and_stages_desired_evidence_without_runtime_mutation(
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
            "Cmnd_Alias HAPAX_ROOT_REQUIRED_AUDIT = /usr/bin/visudo -cf /etc/sudoers.d/hapax-oom-score-enforce\n"
            "hapax ALL=(root) NOPASSWD:NOSETENV: HAPAX_ROOT_REQUIRED_AUDIT\n"
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
            "[Unit]\n# Hapax-Install-Scope: system\n[Timer]\nOnBootSec=120s\nOnUnitActiveSec=120s\n"
        ),
        **P0_OOM_AUDIT_FILES,
        "systemd/units/app.slice.d/oom-containment.conf": (
            "[Slice]\nMemoryHigh=72G\nMemoryMax=88G\nMemorySwapMax=8G\nMemoryLow=16G\nMemoryMin=8G\n"
        ),
        "systemd/units/session.slice.d/oom-containment.conf": (
            "[Slice]\nMemoryHigh=infinity\nMemoryMax=infinity\nMemorySwapMax=infinity\n"
            "MemoryLow=2G\nMemoryMin=1G\n"
        ),
        **P0_USER_OOM_DROPINS,
        **P0_PROTECTED_APP_UNITS,
    }
    repo, sha = _repo_with_linear_commit(tmp_path, files)
    hostile_python = tmp_path / "hostile-python"
    hostile_python.mkdir()
    (hostile_python / "sitecustomize.py").write_text(
        "import os\n"
        "import re\n"
        "\n"
        "_original_write = os.write\n"
        "\n"
        "def _substitute_sha(fd, payload):\n"
        "    if re.fullmatch(rb'[0-9a-f]{40}\\n', payload):\n"
        "        payload = b'f' * 40 + b'\\n'\n"
        "    return _original_write(fd, payload)\n"
        "\n"
        "os.write = _substitute_sha\n",
        encoding="utf-8",
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    defer_dir = tmp_path / "root-required"
    installed_source = tmp_path / "root-state" / "current-source"
    forged_receipt = (
        home / ".local/state/hapax/root-required/installed-receipts/oom-containment.sha"
    )
    forged_receipt.parent.mkdir(parents=True)
    forged_receipt.write_text(f"{sha}\n", encoding="utf-8")
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
        "PYTHONPATH": str(hostile_python),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    installer_args = installer_calls.read_text(encoding="utf-8")
    assert "--check --no-runtime" in installer_args
    assert "--install" not in installer_args
    assert "--verify-live" not in installer_args
    deferred = defer_dir / sha / "oom-containment"
    assert deferred.is_dir(), "a same-UID installed receipt must not suppress desired evidence"
    assert (deferred / ".hapax-root-required-package-sha").read_text(
        encoding="utf-8"
    ).strip() == sha
    desired_receipt = home / ".local/state/hapax/root-required/desired-receipts/oom-containment.sha"
    assert desired_receipt.read_text(encoding="utf-8").strip() == sha
    cursor = tmp_path / "traces/last-deployed-sha"
    assert cursor.read_text(encoding="utf-8").strip() == sha
    runbook = (deferred / "RUNBOOK.txt").read_text(encoding="utf-8")
    assert "non-authoritative desired-state evidence" in runbook
    assert "runtime-authorized root-broker" in runbook
    assert "does not replace, stop, or otherwise reconcile an already installed" in runbook
    assert "historical mutating semantics" in runbook
    assert "sudo -v" not in runbook
    assert "--install/--verify-live" in runbook
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
    assert record["status"] == "completed_with_runtime_deferral"
    assert record["manual_deploy_needed"] is True
    assert record["manual_deploy_executed"] is False
    assert record["runtime_deferred"] == [f"oom-containment:{sha}"]
    assert record["avsdlc"]["runtime_media_witness_required"] is False
    assert record["avsdlc"]["runtime_media_witness_groups"] == []
    assert "no manual deploys needed" not in result.stdout


def test_p0_oom_staging_rejects_non_normalized_manifest_path_before_receipt(
    tmp_path: Path,
) -> None:
    manifest = (
        "config/root-required/oom-containment.files\n"
        "scripts/install-p0-oom-containment\n"
        "scripts/../README.md\n"
    )
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            "config/root-required/oom-containment.files": manifest,
            "scripts/install-p0-oom-containment": "#!/usr/bin/env bash\nexit 0\n",
            "README.md": "must not be staged through a non-normalized alias\n",
        },
    )
    home = tmp_path / "home"

    result = subprocess.run(
        [str(SCRIPT), sha],
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

    assert result.returncode == 2
    assert "malformed root-required manifest entry" in result.stderr
    assert not (
        home / ".local/state/hapax/root-required/desired-receipts/oom-containment.sha"
    ).exists()


@pytest.mark.parametrize(
    ("failed_path", "failed_occurrence", "expected_error", "trace_expected"),
    (
        (
            "config/root-required/oom-containment.files",
            1,
            "refusing package classification",
            False,
        ),
        (
            "config/root-required/oom-containment.files",
            2,
            "refusing to publish an incomplete stage",
            True,
        ),
        (
            "config/root-required/oom-containment.files",
            3,
            "refusing to publish an incomplete stage",
            True,
        ),
        (
            "scripts/install-p0-oom-containment",
            1,
            "refusing to publish an incomplete stage",
            True,
        ),
    ),
    ids=(
        "classification-manifest-read",
        "staging-manifest-read",
        "manifest-payload-read",
        "source-payload-read",
    ),
)
def test_p0_oom_staging_git_read_failure_cannot_publish_package_state(
    tmp_path: Path,
    failed_path: str,
    failed_occurrence: int,
    expected_error: str,
    trace_expected: bool,
) -> None:
    manifest_path = "config/root-required/oom-containment.files"
    installer_path = "scripts/install-p0-oom-containment"
    manifest = f"{manifest_path}\n{installer_path}\n"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            manifest_path: manifest,
            installer_path: (
                "#!/usr/bin/env bash\nprintf 'called\\n' > \"$HAPAX_STAGE_INSTALLER_CALLS\"\n"
            ),
        },
    )
    home = tmp_path / "home"
    temp_root = tmp_path / "stages"
    temp_root.mkdir()
    defer_root = tmp_path / "deferred"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    installer_calls = tmp_path / "installer-calls"
    count_file = tmp_path / "failed-show-count"
    bin_dir = _fake_git_with_show_failure(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "TMPDIR": str(temp_root),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
            "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_root),
            "HAPAX_STAGE_INSTALLER_CALLS": str(installer_calls),
            "HAPAX_FAIL_GIT_SHOW_OBJECT": f"{sha}:{failed_path}",
            "HAPAX_FAIL_GIT_SHOW_COUNT_FILE": str(count_file),
            "HAPAX_FAIL_GIT_SHOW_ON_COUNT": str(failed_occurrence),
        },
    )

    assert result.returncode == 2, (result.stdout, result.stderr)
    assert expected_error in result.stderr
    assert not installer_calls.exists()
    assert not defer_root.exists()
    assert not (
        home / ".local/state/hapax/root-required/desired-receipts/oom-containment.sha"
    ).exists()
    assert not (trace_path.parent / "last-deployed-sha").exists()
    assert not list(temp_root.rglob(".hapax-root-required-package-sha"))
    assert trace_path.exists() is trace_expected
    if trace_expected:
        record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
        assert record["status"] == "failed"
        assert record["exit_code"] == 2


def test_parked_unit_is_stopped_before_later_oom_staging_failure(tmp_path: Path) -> None:
    manifest_path = "config/root-required/oom-containment.files"
    installer_path = "scripts/install-p0-oom-containment"
    unit_path = "systemd/units/retiring-before-oom-stage.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            manifest_path: f"{manifest_path}\n{installer_path}\n",
            installer_path: "#!/usr/bin/env bash\nexit 0\n",
            unit_path: ("# Hapax-Parked: true\n[Service]\nExecStart=/usr/bin/true\nRestart=no\n"),
        },
    )
    home = tmp_path / "home"
    deployed = home / ".config/systemd/user/retiring-before-oom-stage.service"
    deployed.parent.mkdir(parents=True)
    deployed.write_text("[Service]\nExecStart=/usr/bin/false\nRestart=always\n")
    git_bin = _fake_git_with_show_failure(tmp_path)
    systemctl_bin, systemctl_calls = _fake_systemctl(tmp_path)
    count_file = tmp_path / "failed-show-count"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{git_bin}:{systemctl_bin}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/trace.jsonl"),
            "HAPAX_FAIL_GIT_SHOW_OBJECT": f"{sha}:{manifest_path}",
            "HAPAX_FAIL_GIT_SHOW_COUNT_FILE": str(count_file),
            "HAPAX_FAIL_GIT_SHOW_ON_COUNT": "2",
        },
    )

    assert result.returncode == 2
    calls = systemctl_calls.read_text(encoding="utf-8").splitlines()
    assert calls.index("--user stop retiring-before-oom-stage.service") < calls.index(
        "--user disable retiring-before-oom-stage.service"
    )
    assert not (tmp_path / "traces/last-deployed-sha").exists()


def test_pending_transition_parked_unit_stops_before_oom_staging_failure(
    tmp_path: Path,
) -> None:
    manifest_path = "config/root-required/oom-containment.files"
    installer_path = "scripts/install-p0-oom-containment"
    unit_path = "systemd/units/retiring-transition-before-oom.service"
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    parent_unit = (
        "# Hapax-Install-Scope: system\n[Service]\nExecStart=/usr/bin/false\nRestart=always\n"
    )
    parent_path = repo / unit_path
    parent_path.parent.mkdir(parents=True)
    parent_path.write_text(parent_unit, encoding="utf-8")
    _git(repo, "add", unit_path)
    _git(repo, "commit", "-m", "add system-scoped unit")

    parent_path.write_text(
        "# Hapax-Parked: true\n[Service]\nExecStart=/usr/bin/true\nRestart=no\n",
        encoding="utf-8",
    )
    manifest = repo / manifest_path
    manifest.parent.mkdir(parents=True)
    manifest.write_text(f"{manifest_path}\n{installer_path}\n", encoding="utf-8")
    installer = repo / installer_path
    installer.parent.mkdir(parents=True)
    installer.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    installer.chmod(0o755)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "park unit during user-scope transition")
    sha = _git(repo, "rev-parse", "HEAD")

    home = tmp_path / "home"
    deployed = home / ".config/systemd/user/retiring-transition-before-oom.service"
    deployed.parent.mkdir(parents=True)
    deployed.write_text(parent_unit, encoding="utf-8")
    git_bin = _fake_git_with_show_failure(tmp_path)
    systemctl_bin, systemctl_calls = _fake_systemctl(tmp_path)
    count_file = tmp_path / "failed-show-count"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{git_bin}:{systemctl_bin}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/trace.jsonl"),
            "HAPAX_FAIL_GIT_SHOW_OBJECT": f"{sha}:{manifest_path}",
            "HAPAX_FAIL_GIT_SHOW_COUNT_FILE": str(count_file),
            "HAPAX_FAIL_GIT_SHOW_ON_COUNT": "2",
        },
    )

    assert result.returncode == 2, (result.stdout, result.stderr)
    calls = systemctl_calls.read_text(encoding="utf-8").splitlines()
    assert calls.index("--user stop retiring-transition-before-oom.service") < calls.index(
        "--user disable retiring-transition-before-oom.service"
    )
    assert not (tmp_path / "traces/last-deployed-sha").exists()


@pytest.mark.parametrize("preexisting_receipt", (False, True))
def test_p0_oom_semantic_validation_precedes_desired_receipt_publication(
    tmp_path: Path,
    preexisting_receipt: bool,
) -> None:
    files = {
        relative: (REPO_ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            line for line in OOM_PACKAGE_MANIFEST.splitlines() if line and not line.startswith("#")
        )
    }
    profile = "config/root-required/oom-host-profiles.tsv"
    files[profile] = files[profile].replace(
        "hapax-appendix\t59\t61",
        "hapax-appendix\t59\t124",
        1,
    )
    repo, sha = _repo_with_linear_commit(tmp_path, files)
    home = tmp_path / "home"
    receipt = home / ".local/state/hapax/root-required/desired-receipts/oom-containment.sha"
    if preexisting_receipt:
        receipt.parent.mkdir(parents=True)
        receipt.write_text("preserve-this-invalid-sentinel\n", encoding="utf-8")

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "REPO": str(repo),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "trace.jsonl"),
            "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(tmp_path / "deferrals"),
        },
        timeout=30,
    )

    assert result.returncode == 1
    assert "host profile intervals overlap" in result.stderr
    if preexisting_receipt:
        assert receipt.read_text(encoding="utf-8") == "preserve-this-invalid-sentinel\n"
    else:
        assert not receipt.exists()


@pytest.mark.parametrize("installed_state", ("mask", "historical-file"))
def test_historical_local_judge_change_is_always_runtime_deferred(
    tmp_path: Path,
    installed_state: str,
) -> None:
    package_files = {
        relative: (REPO_ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            line for line in OOM_PACKAGE_MANIFEST.splitlines() if line and not line.startswith("#")
        )
    }
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    for relative, body in package_files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        if body.startswith("#!"):
            path.chmod(0o755)
    manifest = repo / "config/root-required/oom-containment.files"
    manifest.write_text(
        OOM_PACKAGE_MANIFEST + "systemd/units/hapax-local-judge.service\n",
        encoding="utf-8",
    )
    historical_unit = repo / "systemd/units/hapax-local-judge.service"
    historical_unit.parent.mkdir(parents=True, exist_ok=True)
    historical_unit.write_text(
        "[Service]\nExecStart=/usr/bin/docker run --name hapax-local-judge mutable\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "historical judge package")

    manifest.write_text(OOM_PACKAGE_MANIFEST, encoding="utf-8")
    historical_unit.unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "retire historical judge source")
    sha = _git(repo, "rev-parse", "HEAD")

    home = tmp_path / "home"
    installed = home / ".config/systemd/user/hapax-local-judge.service"
    installed.parent.mkdir(parents=True)
    if installed_state == "mask":
        installed.symlink_to("/dev/null")
    else:
        installed.write_text("installed historical bytes must be preserved\n", encoding="utf-8")
    before = os.lstat(installed)
    dropin = installed.with_name(f"{installed.name}.d") / "override.conf"
    dropin.parent.mkdir()
    dropin.write_text("[Service]\nRestart=always\n", encoding="utf-8")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "trace.jsonl"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
            "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(tmp_path / "deferrals"),
        },
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    after = os.lstat(installed)
    assert (after.st_dev, after.st_ino, after.st_mode) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
    )
    if installed_state == "mask":
        assert installed.is_symlink()
        assert os.readlink(installed) == "/dev/null"
    else:
        assert installed.read_text(encoding="utf-8") == (
            "installed historical bytes must be preserved\n"
        )
    assert dropin.read_text(encoding="utf-8") == "[Service]\nRestart=always\n"
    calls = systemctl_calls.read_text(encoding="utf-8") if systemctl_calls.exists() else ""
    assert "hapax-local-judge.service" not in calls
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["systemd_units"] == []
    assert record["manual_deploy_needed"] is True
    assert record["manual_deploy_executed"] is False
    assert record["status"] == "completed_with_runtime_deferral"
    assert set(record["runtime_deferred"]) == {
        "local-judge-retirement:systemd/units/hapax-local-judge.service",
        f"oom-containment:{sha}",
    }
    assert record["avsdlc"]["runtime_media_witness_required"] is False
    assert "no manual deploys needed" not in result.stdout


def test_root_packages_check_apcupsd_before_oom_source_validation(tmp_path: Path) -> None:
    order = tmp_path / "source-check-order"
    apcupsd_checked = tmp_path / "apcupsd-checked"
    apcupsd_installer = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "apcupsd\\n" >> "$HAPAX_ROOT_PACKAGE_ORDER"\n'
        'touch "$HAPAX_APCUPSD_CHECKED_WITNESS"\n'
    )
    oom_installer = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        '[ -f "$HAPAX_APCUPSD_CHECKED_WITNESS" ] || { echo "apcupsd unchecked" >&2; exit 42; }\n'
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
            "HAPAX_APCUPSD_CHECKED_WITNESS": str(apcupsd_checked),
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


def test_post_merge_squash_equivalence_rejects_git_mode_drift(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "mode-test@example.test")
    _git(repo, "config", "user.name", "Mode Test")
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
    mode_drift = repo / "scripts/hapax-root-failure-intake"
    mode_drift.chmod(0o644)
    _git(repo, "add", mode_drift.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "desired mode drift")
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


def test_concurrent_same_sha_root_required_oom_deploy_stages_complete_deferral(
    tmp_path: Path,
) -> None:
    installer_body = "#!/usr/bin/env bash\nsleep 0.2\nexit 0\n"
    files = {
        "config/root-required/oom-containment.files": OOM_PACKAGE_MANIFEST,
        "scripts/install-p0-oom-containment": installer_body,
        "config/root-required/hapax-oom-score-enforce.sudoers": (
            "Cmnd_Alias HAPAX_ROOT_REQUIRED_AUDIT = /usr/bin/visudo -cf /etc/sudoers.d/hapax-oom-score-enforce\n"
            "hapax ALL=(root) NOPASSWD:NOSETENV: HAPAX_ROOT_REQUIRED_AUDIT\n"
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
            "[Unit]\n# Hapax-Install-Scope: system\n[Timer]\nOnBootSec=120s\nOnUnitActiveSec=120s\n"
        ),
        **P0_OOM_AUDIT_FILES,
        "systemd/units/app.slice.d/oom-containment.conf": (
            "[Slice]\nMemoryHigh=72G\nMemoryMax=88G\nMemorySwapMax=8G\nMemoryLow=16G\nMemoryMin=8G\n"
        ),
        "systemd/units/session.slice.d/oom-containment.conf": (
            "[Slice]\nMemoryHigh=infinity\nMemoryMax=infinity\nMemorySwapMax=infinity\n"
            "MemoryLow=2G\nMemoryMin=1G\n"
        ),
        **P0_USER_OOM_DROPINS,
        **P0_PROTECTED_APP_UNITS,
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

    first_env = {**env, "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "trace-first.jsonl")}
    second_env = {**env, "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "trace-second.jsonl")}
    first = subprocess.Popen(
        [str(SCRIPT), sha],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=first_env,
    )
    second = subprocess.Popen(
        [str(SCRIPT), sha],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=second_env,
    )
    first_stdout, first_stderr = first.communicate(timeout=30)
    second_stdout, second_stderr = second.communicate(timeout=30)

    assert first.returncode == 0, first_stderr
    assert second.returncode == 0, second_stderr
    deferred = defer_dir / sha / "oom-containment"
    assert (deferred / "RUNBOOK.txt").is_file()
    assert (deferred / "scripts" / "install-p0-oom-containment").is_file()
    for rel in (
        line for line in OOM_PACKAGE_MANIFEST.splitlines() if line and not line.startswith("#")
    ):
        assert (deferred / rel).read_bytes() == (repo / rel).read_bytes()
    assert not list((defer_dir / sha).glob(".oom-containment.tmp.*"))
    runbook = (deferred / "RUNBOOK.txt").read_text(encoding="utf-8")
    assert "non-authoritative desired-state evidence" in runbook
    assert "runtime-authorized root-broker" in runbook
    assert "sudo -v" not in runbook
    assert "root shell" not in runbook
    assert "HAPAX_OOM_INSTALL_SUDO=" not in runbook
    assert "HAPAX_ROOT_REQUIRED_DRAIN_DIR=" not in runbook
    assert "HAPAX_ROOT_REQUIRED_PACKAGE_SHA=" not in runbook
    assert "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT=" not in runbook
    assert "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT=" not in runbook
    assert "HAPAX_ROOT_REQUIRED_DESIRED_RECEIPT_ROOT=" not in runbook
    assert "HAPAX_ROOT_REQUIRED_GIT_REPO=" not in runbook
    assert (home / ".config" / "systemd" / "user" / "hapax-demo.service").is_file()
    assert "root-required oom-containment desired-state package staged" in (
        first_stdout + second_stdout
    )
    desired = home / ".local/state/hapax/root-required/desired-receipts/oom-containment.sha"
    assert desired.read_text(encoding="utf-8").strip() == sha

    audit_env = _root_audit_env(tmp_path)
    audit_env["HAPAX_POST_MERGE_ROOT_DEFER_DIR"] = str(defer_dir)
    audit_result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=audit_env,
    )

    assert audit_result.returncode == 1
    assert "root-required post-merge deploy deferrals pending" in audit_result.stderr
    assert "runtime-authorized root-broker" in audit_result.stderr
    assert "install-p0-oom-containment --install --verify-live" not in audit_result.stderr
    (deferred / "RUNBOOK.txt").unlink()
    assert desired.read_text(encoding="utf-8").strip() == sha


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


def test_canonical_root_audit_refuses_every_state_and_tool_selector(
    tmp_path: Path,
) -> None:
    source = ROOT_REQUIRED_AUDIT.read_text(encoding="utf-8")
    selector_block = source.split("canonical_forbidden_selectors=(", 1)[1].split("\n)", 1)[0]
    selectors = [line.strip() for line in selector_block.splitlines() if line.strip()]
    assert len(selectors) >= 35
    referenced_selectors = set(re.findall(r"\bHAPAX_[A-Z0-9_]*[A-Z0-9]\b", source))
    internal_protocol = {
        "HAPAX_ROOT_REQUIRED_LOCK_ANCHOR_FD",
        "HAPAX_ROOT_REQUIRED_LOCK_FD",
        "HAPAX_ROOT_REQUIRED_LOCK_HELD",
        "HAPAX_ROOT_REQUIRED_LOCK_MODE",
    }
    assert referenced_selectors - internal_protocol == set(selectors)

    staged = tmp_path / "hapax-root-required-deploy-audit"
    staged.write_text(
        source.replace("/usr/local/sbin/hapax-root-required-deploy-audit", str(staged)),
        encoding="utf-8",
    )
    staged.chmod(0o755)
    base_env = os.environ.copy()
    for selector in selectors:
        base_env.pop(selector, None)

    for selector in selectors:
        result = subprocess.run(
            [str(staged)],
            env=base_env | {selector: "/tmp/caller-controlled"},
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 2, (selector, result.stderr)
        assert f"refuses production selector {selector}" in result.stderr


def test_root_required_audit_snapshot_list_covers_complete_oom_manifest() -> None:
    body = ROOT_REQUIRED_AUDIT.read_text(encoding="utf-8")
    array = body.split("oom_package_files=(", 1)[1].split(")\napcupsd_package_files=", 1)[0]
    entries = {
        line for line in OOM_PACKAGE_MANIFEST.splitlines() if line and not line.startswith("#")
    }

    for relative in entries:
        assert f"\n    {relative}\n" in array


def test_root_required_audit_binds_profile_source_and_installed_table(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    installed_profile = (
        Path(env["HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT"])
        / "config/root-required/oom-host-policy/appendix/app.slice.conf"
    )
    installed_profile.unlink()

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "installed source is not bound" in result.stderr
    assert "runtime-authorized root-broker" in result.stderr

    installed_drift = tmp_path / "installed-drift"
    installed_drift.mkdir()
    env = _root_audit_env(installed_drift)
    Path(env["HAPAX_OOM_PROFILE_TABLE_DEST"]).write_text("stale\n", encoding="utf-8")
    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "oom-host-profiles.tsv differs" in result.stderr
    assert "runtime-authorized root-broker" in result.stderr


def test_root_required_audit_compares_the_selected_host_policy_and_zram(
    tmp_path: Path,
) -> None:
    env = _root_audit_env(tmp_path)
    installed_root = Path(env["HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT"])
    app_dest = Path(env["HAPAX_OOM_SYSTEMD_USER_DIR"]) / "app.slice.d" / "oom-containment.conf"
    app_dest.write_text(
        (installed_root / "config/root-required/oom-host-policy/podium/app.slice.conf").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "oom-host-policy/appendix/app.slice.conf differs" in result.stderr
    assert str(app_dest) in result.stderr

    podium_root = tmp_path / "podium"
    podium_env = _root_audit_env(podium_root)
    podium_env["HAPAX_ROOT_AUDIT_HOSTNAME"] = "hapax-podium"
    podium_env["HAPAX_ROOT_AUDIT_MEMTOTAL_KIB"] = str(124 * 1024**2)
    podium_installed = Path(podium_env["HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT"])
    selected = {
        "app.slice.conf": (
            Path(podium_env["HAPAX_OOM_SYSTEMD_USER_DIR"]) / "app.slice.d" / "oom-containment.conf"
        ),
        "user-1000.slice.conf": (
            Path(podium_env["HAPAX_OOM_SYSTEMD_SYSTEM_DIR"])
            / "user-1000.slice.d"
            / "oom-containment.conf"
        ),
        "user@1000.service.conf": (
            Path(podium_env["HAPAX_OOM_SYSTEMD_SYSTEM_DIR"]) / "user@1000.service.d" / "oom.conf"
        ),
        "zram-generator.conf": Path(podium_env["HAPAX_OOM_ZRAM_GENERATOR_DEST"]),
    }
    for filename, destination in selected.items():
        destination.write_text(
            (podium_installed / "config/root-required/oom-host-policy/podium" / filename).read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )

    podium_result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=podium_env,
    )

    assert podium_result.returncode == 0, podium_result.stderr
    assert "NON-AUTHORITATIVE" in podium_result.stdout


def test_root_required_audit_fails_when_canonical_audit_group_is_missing(
    tmp_path: Path,
) -> None:
    env = _root_audit_env(tmp_path)
    fake_bin = tmp_path / "missing-group-bin"
    fake_bin.mkdir()
    fake_getent = fake_bin / "getent"
    fake_getent.write_text("#!/usr/bin/env bash\nexit 2\n", encoding="utf-8")
    fake_getent.chmod(0o755)
    env["HAPAX_ROOT_AUDIT_GETENT"] = str(fake_getent)
    env["HAPAX_UPS_AUDIT_LOG"] = "/var/log/hapax/ups-power-events.jsonl"

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "required UPS audit group missing: hapax" in result.stderr
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
    assert "runtime-authorized root-broker" in result.stderr
    assert "install-p0-oom-containment --install --verify-live" not in result.stderr


def test_root_required_audit_rejects_untrusted_root_artifact_owner(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    env["HAPAX_ROOT_AUDIT_TEST_ROOT_UID"] = str(os.getuid() + 1)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "root-artifact ownership drift" in result.stderr
    assert env["HAPAX_OOM_ENFORCER_DEST"] in result.stderr


def test_root_required_audit_rejects_writable_root_artifact_parent(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    Path(env["HAPAX_OOM_ENFORCER_DEST"]).parent.chmod(0o775)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "root-artifact parent trust drift" in result.stderr
    assert str(Path(env["HAPAX_OOM_ENFORCER_DEST"]).parent) in result.stderr


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


def test_root_required_audit_detects_root_owned_sudoers_reference_drift(
    tmp_path: Path,
) -> None:
    env = _root_audit_env(tmp_path)
    Path(env["HAPAX_OOM_SUDOERS_REFERENCE_DEST"]).chmod(0o644)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "root-required install mode drift" in result.stderr
    assert "expected=444" in result.stderr


def test_root_required_audit_detects_sudoers_reference_owner_drift(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    env["HAPAX_OOM_SUDOERS_OWNER_UID"] = str(os.getuid() + 1)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "sudoers audit reference ownership/mode drift" in result.stderr


def test_root_required_audit_detects_stale_user_copy_of_system_unit(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    stale = Path(env["HAPAX_OOM_SYSTEMD_USER_DIR"]) / "hapax-oom-score-enforce.timer"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("[Timer]\nOnUnitActiveSec=30s\n", encoding="utf-8")

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "stale user-scope copy of system unit remains" in result.stderr
    assert "runtime-authorized root-broker" in result.stderr
    assert "install-p0-oom-containment --install --verify-live" not in result.stderr


def test_root_required_audit_reads_sudoers_only_through_narrow_sudo(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    calls = Path(env["HAPAX_TEST_ROOT_AUDIT_SUDO_CALLS"]).read_text(encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert "-n /usr/bin/cmp -s " in calls
    assert f"-n {env['HAPAX_ROOT_AUDIT_VISUDO']} -cf " in calls


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
    assert "runtime-authorized root-broker" in result.stderr
    assert "install-p0-oom-containment --install --verify-live" not in result.stderr


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
    assert "runtime-authorized root-broker" in result.stderr
    assert "production OOM repair is unavailable" in result.stderr


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
    assert "separately runtime-authorized root-broker" in result.stderr
    assert "production APC repair is unavailable" in result.stderr


def test_root_required_audit_detects_enabled_retired_enforcer_timer(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    fake_systemctl = Path(env["HAPAX_ROOT_AUDIT_SYSTEMCTL"])
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$*" = "is-enabled hapax-oom-score-enforce.timer" ]; then printf "enabled\\n"; exit 0; fi\n'
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
    assert "hapax-oom-score-enforce.timer UnitFileState=enabled, expected static" in result.stderr
    assert "runtime-authorized root-broker" in result.stderr


def test_root_required_audit_detects_stale_loaded_enforcer_timeout(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    fake_systemctl = Path(env["HAPAX_ROOT_AUDIT_SYSTEMCTL"])
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$*" = "show hapax-oom-score-enforce.service -p TimeoutStartUSec --value" ]; then printf "infinity\\n"; fi\n'
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
    assert "loaded TimeoutStartUSec=infinity, expected 5s" in result.stderr
    assert "runtime-authorized root-broker" in result.stderr


def test_root_required_audit_detects_stale_loaded_user_audit_timeout(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    fake_systemctl = Path(env["HAPAX_ROOT_AUDIT_SYSTEMCTL"])
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$*" = "show hapax-oom-score-enforce.service -p TimeoutStartUSec --value" ]; then printf "5s\\n"; fi\n'
        'if [ "$*" = "--user show hapax-oom-policy-audit.service -p TimeoutStartUSec --value" ]; then printf "infinity\\n"; fi\n'
        'if [ "$*" = "--user show hapax-root-required-deploy-audit.service -p TimeoutStartUSec --value" ]; then printf "2min\\n"; fi\n'
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
    assert (
        "hapax-oom-policy-audit.service loaded TimeoutStartUSec=infinity, expected 2min"
        in result.stderr
    )
    assert "runtime-authorized root-broker" in result.stderr


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
    assert "runtime-authorized root-broker" in result.stderr


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
    assert "separately runtime-authorized root-broker" in result.stderr
    assert "production APC repair is unavailable" in result.stderr


def test_root_required_audit_detects_stale_loaded_upower_action(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    fake_busctl = Path(env["HAPAX_ROOT_AUDIT_BUSCTL"])
    fake_busctl.write_text("#!/bin/sh\nprintf '%s\\n' 's \"PowerOff\"'\n", encoding="utf-8")
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


def test_root_required_audit_clean_drift_result_is_explicitly_non_authoritative(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=_root_audit_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert "root-required post-merge deploy deferrals: none" in result.stdout
    assert "NON-AUTHORITATIVE" in result.stdout
    assert "same-UID receipts do not attest OOM runtime completion" in result.stdout


def test_root_required_audit_fails_when_deferral_enumeration_fails(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    unreadable = Path(env["HAPAX_POST_MERGE_ROOT_DEFER_DIR"]) / "unreadable"
    unreadable.mkdir(parents=True)
    unreadable.chmod(0)
    try:
        result = subprocess.run(
            [str(ROOT_REQUIRED_AUDIT)],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
    finally:
        unreadable.chmod(0o700)

    assert result.returncode != 0
    assert "cannot enumerate root-required deploy deferrals" in result.stderr
    assert "root-required post-merge deploy deferrals: none" not in result.stdout


def test_root_required_audit_accepts_shipped_service_after_systemd_expansion(
    tmp_path: Path,
) -> None:
    relative = "systemd/units/hapax-root-required-deploy-audit.service"
    shipped = (REPO_ROOT / relative).read_text(encoding="utf-8")
    assert P0_OOM_AUDIT_FILES[relative] == shipped
    assert "HOME=%h" in shipped
    assert "XDG_RUNTIME_DIR=%t" in shipped

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=_root_audit_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr


def test_retired_oom_install_command_is_absent_from_recovery_surfaces() -> None:
    for relative in (
        "scripts/hapax-oom-score-enforce",
        "scripts/hapax-post-merge-deploy",
        "scripts/hapax-root-failure-intake",
        "scripts/hapax-root-required-deploy-audit",
        "systemd/README.md",
    ):
        body = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "install-p0-oom-containment --install --verify-live" not in body


def test_root_required_audit_ignores_hostile_path(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    hostile_bin = tmp_path / "hostile-bin"
    hostile_bin.mkdir()
    marker = tmp_path / "hostile-command-ran"
    for command in ("bash", "git"):
        executable = hostile_bin / command
        executable.write_text(
            f"#!/bin/sh\ntouch {marker!s}\nexit 99\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
    env["PATH"] = str(hostile_bin)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not marker.exists()


def test_root_required_audit_rejects_effective_service_dropin(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    fake_systemctl = Path(env["HAPAX_ROOT_AUDIT_SYSTEMCTL"])
    baseline_systemctl = fake_systemctl.with_name("root-audit-systemctl-baseline")
    fake_systemctl.rename(baseline_systemctl)
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$*" = "--user show hapax-oom-policy-audit.service -p DropInPaths --value" ]; then\n'
        "  printf '%s\\n' '/run/user/1000/systemd/user/hapax-oom-policy-audit.service.d/override.conf'\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$*" = "--user show hapax-oom-policy-audit.service -p ExecStart --value" ]; then\n'
        "  printf '%s\\n' '{ path=/usr/bin/true ; argv[]=/usr/bin/true ; }'\n"
        "  exit 0\n"
        "fi\n"
        f'exec "{baseline_systemctl!s}" "$@"\n',
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
    assert "effective hapax-oom-policy-audit.service unit-source drift" in result.stderr
    assert "override.conf" in result.stderr


def test_root_required_audit_rejects_execstart_substring_with_extra_argv(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    fake_systemctl = Path(env["HAPAX_ROOT_AUDIT_SYSTEMCTL"])
    baseline_systemctl = fake_systemctl.with_name("root-audit-systemctl-baseline")
    fake_systemctl.rename(baseline_systemctl)
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$*" = "--user show hapax-oom-policy-audit.service -p ExecStart --value" ]; then\n'
        "  printf '%s\\n' '{ path=/usr/local/sbin/hapax-oom-policy-audit ; argv[]=/usr/local/sbin/hapax-oom-policy-audit --json --unreviewed ; }'\n"
        "  exit 0\n"
        "fi\n"
        f'exec "{baseline_systemctl!s}" "$@"\n',
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)], text=True, capture_output=True, check=False, env=env
    )

    assert result.returncode == 1
    assert "effective hapax-oom-policy-audit.service ExecStart drift" in result.stderr


def test_root_required_audit_rejects_manager_reload_debt(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    fake_systemctl = Path(env["HAPAX_ROOT_AUDIT_SYSTEMCTL"])
    baseline_systemctl = fake_systemctl.with_name("root-audit-systemctl-baseline")
    fake_systemctl.rename(baseline_systemctl)
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$*" = "--user show hapax-oom-policy-audit.service -p NeedDaemonReload --value" ]; then\n'
        "  printf 'yes\\n'\n"
        "  exit 0\n"
        "fi\n"
        f'exec "{baseline_systemctl!s}" "$@"\n',
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)], text=True, capture_output=True, check=False, env=env
    )

    assert result.returncode == 1
    assert "NeedDaemonReload=yes" in result.stderr


def test_retired_enforcer_has_no_failure_intake_dependency() -> None:
    service = (REPO_ROOT / "systemd/units/hapax-oom-score-enforce.service").read_text(
        encoding="utf-8"
    )
    audit = ROOT_REQUIRED_AUDIT.read_text(encoding="utf-8")

    assert "OnFailure=" not in service
    assert "audit_effective_failure_intake_unit" not in audit


def test_root_required_audit_uses_unabridged_kernel_hostname() -> None:
    audit = ROOT_REQUIRED_AUDIT.read_text(encoding="utf-8")

    assert 'hostname="$(/usr/bin/hostname)"' in audit
    assert "hostname --short" not in audit


@pytest.mark.parametrize(
    ("property_name", "loaded_value", "expected_error"),
    (
        ("Unit", "untrusted.service", "target drift"),
        (
            "TimersMonotonic",
            "OnBootUSec=2min OnUnitActiveUSec=1d",
            "cadence drift",
        ),
    ),
)
def test_root_required_audit_rejects_effective_timer_drift(
    tmp_path: Path,
    property_name: str,
    loaded_value: str,
    expected_error: str,
) -> None:
    env = _root_audit_env(tmp_path)
    fake_systemctl = Path(env["HAPAX_ROOT_AUDIT_SYSTEMCTL"])
    baseline_systemctl = fake_systemctl.with_name("root-audit-systemctl-baseline")
    fake_systemctl.rename(baseline_systemctl)
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$*" = "--user show hapax-oom-policy-audit.timer -p {property_name} --value" ]; then\n'
        f"  printf '%s\\n' '{loaded_value}'\n"
        "  exit 0\n"
        "fi\n"
        f'exec "{baseline_systemctl!s}" "$@"\n',
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
    assert f"effective hapax-oom-policy-audit.timer {expected_error}" in result.stderr
    assert loaded_value in result.stderr


def test_root_required_audit_normalizes_equivalent_timer_durations(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    fake_systemctl = Path(env["HAPAX_ROOT_AUDIT_SYSTEMCTL"])
    baseline_systemctl = fake_systemctl.with_name("root-audit-systemctl-baseline")
    fake_systemctl.rename(baseline_systemctl)
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$*" = "show hapax-oom-score-enforce.timer -p TimersMonotonic --value" ]; then\n'
        "  printf '%s\\n' 'OnBootUSec=2min OnUnitActiveUSec=2min'\n"
        "  exit 0\n"
        "fi\n"
        f'exec "{baseline_systemctl!s}" "$@"\n',
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

    assert result.returncode == 0, result.stderr


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


def test_root_required_audit_ignores_repository_replace_refs(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    repo = Path(env["HAPAX_ROOT_REQUIRED_GIT_REPO"])
    receipt = Path(env["HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT"]) / "oom-containment.sha"
    original_sha = receipt.read_text(encoding="utf-8").strip()
    relative = "scripts/install-p0-oom-containment"
    replacement_body = (repo / relative).read_text(encoding="utf-8") + "# replacement bytes\n"
    (repo / relative).write_text(replacement_body, encoding="utf-8")
    _git(repo, "add", relative)
    _git(repo, "commit", "-m", "replacement-only package bytes")
    replacement_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "replace", original_sha, replacement_sha)
    installed = Path(env["HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT"]) / relative
    installed.write_text(replacement_body, encoding="utf-8")
    installed.chmod(0o755)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "installed source is not bound" in result.stderr
    assert original_sha in result.stderr


@pytest.mark.parametrize(
    "selector",
    (
        "GIT_DIR",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_SHALLOW_FILE",
    ),
)
def test_root_required_audit_ignores_ambient_git_repository_selectors(
    tmp_path: Path,
    selector: str,
) -> None:
    env = _root_audit_env(tmp_path)
    env[selector] = str(tmp_path / "caller-selected-git-state")

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, (selector, result.stderr)


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


@pytest.mark.parametrize("inherited_descriptor", (False, True))
def test_root_required_audit_rejects_lock_path_replaced_while_waiting(
    tmp_path: Path,
    inherited_descriptor: bool,
) -> None:
    env = _root_audit_env(tmp_path)
    lock = Path(env["HAPAX_ROOT_REQUIRED_STATE_ROOT"]) / ".lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("", encoding="utf-8")
    lock.chmod(0o600)
    blocker_fd = os.open(lock, os.O_RDWR)
    waiter_fd = os.open(lock, os.O_RDWR)
    fcntl.flock(blocker_fd, fcntl.LOCK_EX)
    env["HAPAX_ROOT_REQUIRED_LOCK_FILE"] = str(lock)
    pass_fds: tuple[int, ...] = ()
    anchor_fd = -1
    if inherited_descriptor:
        anchor_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        env["HAPAX_ROOT_REQUIRED_LOCK_FD"] = str(waiter_fd)
        env["HAPAX_ROOT_REQUIRED_LOCK_ANCHOR_FD"] = str(anchor_fd)
        env["HAPAX_ROOT_REQUIRED_LOCK_MODE"] = "shared"
        pass_fds = (anchor_fd, waiter_fd)
    audit = subprocess.Popen(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        pass_fds=pass_fds,
        start_new_session=True,
    )
    try:
        _wait_for_flock_block(audit, lock)
        replacement = lock.with_name("replacement.lock")
        replacement.write_text("", encoding="utf-8")
        replacement.chmod(0o600)
        os.replace(replacement, lock)
        fcntl.flock(blocker_fd, fcntl.LOCK_UN)
        stdout, stderr = audit.communicate(timeout=10)
    finally:
        if audit.poll() is None:
            _kill_process_group(audit)
        if anchor_fd >= 0:
            os.close(anchor_fd)
        os.close(waiter_fd)
        os.close(blocker_fd)

    assert audit.returncode == 1, stdout
    assert "lock identity changed while acquiring" in stderr


@pytest.mark.parametrize("link_kind", ("symlink", "hardlink"))
def test_root_required_audit_refuses_unsafe_shared_lock_before_target_mutation(
    tmp_path: Path,
    link_kind: str,
) -> None:
    env = _root_audit_env(tmp_path)
    state_root = Path(env["HAPAX_ROOT_REQUIRED_STATE_ROOT"])
    protected = tmp_path / "protected-target"
    protected.write_text("sentinel\n", encoding="utf-8")
    lock = state_root / ".lock"
    if link_kind == "symlink":
        lock.symlink_to(protected)
    else:
        os.link(protected, lock)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "refused unsafe shared lock" in result.stderr
    assert protected.read_text(encoding="utf-8") == "sentinel\n"
    if link_kind == "symlink":
        assert lock.is_symlink()
    else:
        assert lock.stat().st_ino == protected.stat().st_ino


@pytest.mark.parametrize("link_kind", ("symlink", "hardlink"))
def test_root_required_audit_rejects_unsafe_ups_log_inode(
    tmp_path: Path,
    link_kind: str,
) -> None:
    env = _root_audit_env(tmp_path)
    audit_log = Path(env["HAPAX_UPS_AUDIT_LOG"])
    audit_log.unlink()
    protected = tmp_path / "protected-ups-log-target"
    protected.write_text("sentinel\n", encoding="utf-8")
    if link_kind == "symlink":
        audit_log.symlink_to(protected)
    else:
        os.link(protected, audit_log)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "unsafe UPS audit log" in result.stderr
    assert protected.read_text(encoding="utf-8") == "sentinel\n"


def test_root_required_audit_rejects_symlinked_ups_log_parent(tmp_path: Path) -> None:
    env = _root_audit_env(tmp_path)
    audit_log = Path(env["HAPAX_UPS_AUDIT_LOG"])
    lexical_parent = audit_log.parent
    real_parent = tmp_path / "real-ups-log-parent"
    lexical_parent.rename(real_parent)
    lexical_parent.symlink_to(real_parent, target_is_directory=True)

    result = subprocess.run(
        [str(ROOT_REQUIRED_AUDIT)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "UPS audit log parent trust drift" in result.stderr
    assert lexical_parent.is_symlink()


@pytest.mark.parametrize(
    "selector",
    (
        "HAPAX_POST_MERGE_TRACE_PATH",
        "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH",
        "HAPAX_POST_MERGE_SYSTEMD_PENDING_PATH",
        "HAPAX_POST_MERGE_ROOT_DEFER_DIR",
        "HAPAX_ROOT_REQUIRED_STATE_ROOT",
        "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT",
        "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT",
        "HAPAX_ROOT_REQUIRED_DESIRED_RECEIPT_ROOT",
        "HAPAX_ROOT_REQUIRED_LOCK_FILE",
    ),
)
def test_post_merge_real_deploy_rejects_caller_selected_state_domain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selector: str,
) -> None:
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {"scripts/hapax-demo": "#!/usr/bin/env bash\nexit 0\n"},
    )
    monkeypatch.delenv("HAPAX_ROOT_REQUIRED_ISOLATED_TEST_ROOT")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("HAPAX_ROOT_REQUIRED_") and not key.startswith("HAPAX_POST_MERGE_")
    }
    env.update(
        {
            "HOME": str(tmp_path / "spoofed-home"),
            "REPO": str(repo),
            selector: str(tmp_path / "caller-selected-state"),
        }
    )

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert selector in result.stderr
    assert "caller-selected production state" in result.stderr
    assert not (tmp_path / "spoofed-home/.local/bin/hapax-demo").exists()


def test_post_merge_real_deploy_rejects_home_spoofing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {"scripts/hapax-demo": "#!/usr/bin/env bash\nexit 0\n"},
    )
    monkeypatch.delenv("HAPAX_ROOT_REQUIRED_ISOLATED_TEST_ROOT")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("HAPAX_ROOT_REQUIRED_") and not key.startswith("HAPAX_POST_MERGE_")
    }
    home = tmp_path / "spoofed-home"
    env.update({"HOME": str(home), "REPO": str(repo)})

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert "HOME does not match NSS home" in result.stderr
    assert not (home / ".local/bin/hapax-demo").exists()


def test_post_merge_isolated_test_mode_rejects_state_path_escape(tmp_path: Path) -> None:
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {"scripts/hapax-demo": "#!/usr/bin/env bash\nexit 0\n"},
    )
    escaped_lock = tmp_path.parent / f"{tmp_path.name}-escaped.lock"
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "REPO": str(repo),
        "HAPAX_ROOT_REQUIRED_LOCK_FILE": str(escaped_lock),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2
    assert "HAPAX_ROOT_REQUIRED_LOCK_FILE escapes isolated test root" in result.stderr
    assert not escaped_lock.exists()


@pytest.mark.parametrize("link_kind", ("symlink", "hardlink"))
def test_post_merge_deploy_refuses_unsafe_shared_lock_before_mutation(
    tmp_path: Path,
    link_kind: str,
) -> None:
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {"scripts/hapax-demo": "#!/usr/bin/env bash\nexit 0\n"},
    )
    home = tmp_path / "home"
    state_root = tmp_path / "root-state"
    state_root.mkdir()
    protected = tmp_path / "protected-target"
    protected.write_text("sentinel\n", encoding="utf-8")
    lock = state_root / ".lock"
    if link_kind == "symlink":
        lock.symlink_to(protected)
    else:
        os.link(protected, lock)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "REPO": str(repo),
            "HAPAX_ROOT_REQUIRED_STATE_ROOT": str(state_root),
            "HAPAX_ROOT_REQUIRED_LOCK_FILE": str(lock),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "trace.jsonl"),
        },
    )

    assert result.returncode == 1
    assert "refused unsafe shared lock" in result.stderr
    assert protected.read_text(encoding="utf-8") == "sentinel\n"
    if link_kind == "symlink":
        assert lock.is_symlink()
    else:
        assert lock.stat().st_ino == protected.stat().st_ino
    assert not (home / ".local/bin/hapax-demo").exists()


@pytest.mark.parametrize("inherited_descriptor", (False, True))
def test_post_merge_deploy_rejects_lock_path_replaced_while_waiting(
    tmp_path: Path,
    inherited_descriptor: bool,
) -> None:
    repo, sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=True)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)
    lock = tmp_path / "root-state" / ".lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("", encoding="utf-8")
    lock.chmod(0o600)
    blocker_fd = os.open(lock, os.O_RDWR)
    waiter_fd = os.open(lock, os.O_RDWR)
    fcntl.flock(blocker_fd, fcntl.LOCK_EX)
    env["HAPAX_ROOT_REQUIRED_LOCK_FILE"] = str(lock)
    pass_fds: tuple[int, ...] = ()
    anchor_fd = -1
    if inherited_descriptor:
        anchor_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        env["HAPAX_ROOT_REQUIRED_LOCK_FD"] = str(waiter_fd)
        env["HAPAX_ROOT_REQUIRED_LOCK_ANCHOR_FD"] = str(anchor_fd)
        env["HAPAX_ROOT_REQUIRED_LOCK_MODE"] = "exclusive"
        pass_fds = (anchor_fd, waiter_fd)
    deploy = subprocess.Popen(
        [str(SCRIPT), sha],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        pass_fds=pass_fds,
        start_new_session=True,
    )
    try:
        _wait_for_flock_block(deploy, lock)
        replacement = lock.with_name("replacement.lock")
        replacement.write_text("", encoding="utf-8")
        replacement.chmod(0o600)
        os.replace(replacement, lock)
        fcntl.flock(blocker_fd, fcntl.LOCK_UN)
        stdout, stderr = deploy.communicate(timeout=10)
    finally:
        if deploy.poll() is None:
            _kill_process_group(deploy)
        if anchor_fd >= 0:
            os.close(anchor_fd)
        os.close(waiter_fd)
        os.close(blocker_fd)

    assert deploy.returncode == 1, stdout
    assert "lock identity changed while acquiring" in stderr
    assert not calls.exists()


def test_post_merge_deploy_serializes_after_acquired_lock_path_is_replaced(
    tmp_path: Path,
) -> None:
    repo, older_sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    (repo / "README.md").write_text("newer deploy\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "newer deploy target")
    newer_sha = _git(repo, "rev-parse", "HEAD")
    older_parent = _git(repo, "rev-parse", f"{older_sha}^")
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=False)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)
    state_root = tmp_path / "root-state"
    lock = state_root / ".lock"
    env["HAPAX_ROOT_REQUIRED_STATE_ROOT"] = str(state_root)
    env["HAPAX_ROOT_REQUIRED_LOCK_FILE"] = str(lock)

    marker = tmp_path / "older-inside-critical-section"
    release = tmp_path / "release-older"
    fake_bin = tmp_path / "git-bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'if [ "$*" = "diff --name-only {older_parent} {older_sha}" ]; then\n'
        f"  : > {shlex.quote(str(marker))}\n"
        f"  while [ ! -e {shlex.quote(str(release))} ]; do /usr/bin/sleep 0.01; done\n"
        "fi\n"
        'exec /usr/bin/git "$@"\n',
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    older = subprocess.Popen(
        [str(SCRIPT), older_sha],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    newer: subprocess.Popen[str] | None = None
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and older.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), "older deploy did not enter the locked critical section"
        replacement = lock.with_name("replacement.lock")
        replacement.write_text("", encoding="utf-8")
        replacement.chmod(0o600)
        os.replace(replacement, lock)
        newer = subprocess.Popen(
            [str(SCRIPT), newer_sha],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        _wait_for_flock_block(newer, Path("/"))
        assert not (tmp_path / "traces/last-deployed-sha").exists()
    finally:
        release.touch()
        older_stdout, older_stderr = older.communicate(timeout=20)
        if newer is not None:
            newer_stdout, newer_stderr = newer.communicate(timeout=20)

    assert older.returncode == 0, (older_stdout, older_stderr)
    assert newer is not None
    assert newer.returncode == 0, (newer_stdout, newer_stderr)
    cursor = tmp_path / "traces/last-deployed-sha"
    assert cursor.read_text(encoding="utf-8").strip() == newer_sha


@pytest.mark.parametrize(
    "script",
    (SCRIPT, ROOT_REQUIRED_AUDIT),
)
def test_root_required_lock_helpers_use_isolated_python(script: Path) -> None:
    source = script.read_text(encoding="utf-8")
    lock_region = source[
        source.index("acquire_inherited_root_required_lock()") : source.index(
            "read_last_deployed_sha_under_lock()"
            if script == SCRIPT
            else "resolve_apcupsd_audit_log_identity()"
        )
    ]

    assert "/usr/bin/python3 -I -S -" in lock_region
    assert '/usr/bin/python3 - "$lock_fd"' not in lock_region


@pytest.mark.parametrize(
    "script",
    (
        SCRIPT,
        ROOT_REQUIRED_AUDIT,
        REPO_ROOT / "scripts" / "hapax-root-failure-intake",
        REPO_ROOT / "scripts" / "install-apcupsd-power-alerts",
    ),
)
def test_root_required_embedded_system_python_is_isolated(script: Path) -> None:
    source = script.read_text(encoding="utf-8")

    assert re.search(r"/usr/bin/python3\s+-(?:\s|$)", source) is None
    assert re.search(r"(?:^|\s)python3\s+-(?:\s|$)", source, re.MULTILINE) is None


def test_apcupsd_power_alert_deploy_stages_dedicated_package_for_root_broker(
    tmp_path: Path,
) -> None:
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
    defer_dir = tmp_path / "root-required"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_APCUPSD_INSTALL_CALLS": str(installer_calls),
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
    installer_args = installer_calls.read_text(encoding="utf-8")
    assert "--check" in installer_args
    assert "--install" not in installer_args
    assert "--verify-live" not in installer_args
    deferred = defer_dir / sha / "apcupsd-power-alerts"
    assert (deferred / future_manifest_path).read_text(encoding="utf-8") == "future hook\n"
    runbook = (deferred / "RUNBOOK.txt").read_text(encoding="utf-8")
    assert "non-authoritative desired-state evidence" in runbook
    assert "separately runtime-authorized root-broker" in runbook
    assert "sudo -v" not in runbook
    assert "--install" not in runbook
    assert "HAPAX_ROOT_REQUIRED_PACKAGE_SHA=" not in runbook
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert set(record["deploy_groups"]["apcupsd_power_alerts"]) == set(files)
    assert record["status"] == "completed_with_runtime_deferral"
    assert record["runtime_deferred"] == [f"apcupsd-power-alerts:{sha}"]


@pytest.mark.parametrize("preexisting_receipt", (False, True))
def test_apcupsd_semantic_validation_precedes_desired_receipt_publication(
    tmp_path: Path,
    preexisting_receipt: bool,
) -> None:
    manifest_rel = "config/root-required/apcupsd-power-alerts.files"
    installer_rel = "scripts/install-apcupsd-power-alerts"
    installer_calls = tmp_path / "apcupsd-check-calls"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            manifest_rel: f"{manifest_rel}\n{installer_rel}\n",
            installer_rel: (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'printf \'%s\\n\' "$*" > "$HAPAX_APCUPSD_CHECK_CALLS"\n'
                "exit 41\n"
            ),
        },
    )
    home = tmp_path / "home"
    receipt = home / ".local/state/hapax/root-required/desired-receipts/apcupsd-power-alerts.sha"
    previous = _git(repo, "rev-parse", f"{sha}^")
    if preexisting_receipt:
        receipt.parent.mkdir(parents=True)
        receipt.write_text(f"{previous}\n", encoding="utf-8")

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "REPO": str(repo),
            "HAPAX_APCUPSD_CHECK_CALLS": str(installer_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "trace.jsonl"),
            "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(tmp_path / "deferrals"),
        },
    )

    assert result.returncode == 41, (result.stdout, result.stderr)
    assert "--check" in installer_calls.read_text(encoding="utf-8")
    if preexisting_receipt:
        assert receipt.read_text(encoding="utf-8") == f"{previous}\n"
    else:
        assert not receipt.exists()
    assert not (tmp_path / "deferrals").exists()
    assert not (tmp_path / "last-deployed-sha").exists()


def test_generic_slice_dropin_deploy_uses_runtime_set_property_not_restart(
    tmp_path: Path,
) -> None:
    dropin_path = "systemd/units/demo.slice.d/memory.conf"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            dropin_path: (
                "[Slice]\nMemoryHigh=1G\nMemoryMax=2G\nMemorySwapMax=512M\n"
                "MemoryLow=256M\nMemoryMin=128M\n"
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
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert (
        "--user set-property --runtime demo.slice MemoryHigh=1G MemoryMax=2G "
        "MemorySwapMax=512M MemoryLow=256M MemoryMin=128M" in calls
    )
    assert "--user restart demo.slice" not in calls


@pytest.mark.parametrize(
    "co_resident_content",
    (
        "[Service]\nMemoryMax=64M\n",
        "[Slice]\nMemoryMax=not-a-size\n",
    ),
)
def test_generic_slice_dropin_rejects_unsafe_co_resident_before_mutation(
    tmp_path: Path,
    co_resident_content: str,
) -> None:
    dropin_path = "systemd/units/demo.slice.d/memory.conf"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {dropin_path: "[Slice]\nMemoryHigh=1G\nMemoryMax=2G\n"},
    )
    home = tmp_path / "home"
    co_resident = home / ".config/systemd/user/demo.slice.d/local.conf"
    co_resident.parent.mkdir(parents=True)
    co_resident.write_text(co_resident_content, encoding="utf-8")
    changed_dest = co_resident.with_name("memory.conf")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha],
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

    assert result.returncode == 1
    assert "unsafe co-resident generic slice drop-in" in result.stderr
    assert co_resident.read_text(encoding="utf-8") == co_resident_content
    assert not changed_dest.exists()
    calls = systemctl_calls.read_text(encoding="utf-8") if systemctl_calls.exists() else ""
    assert "daemon-reload" not in calls
    assert "set-property" not in calls


def test_generic_service_dropin_atomically_replaces_changed_destination_symlink(
    tmp_path: Path,
) -> None:
    dropin_path = "systemd/units/demo.service.d/override.conf"
    deployed_content = "[Service]\nEnvironment=DEMO=new\n"
    repo, sha = _repo_with_linear_commit(tmp_path, {dropin_path: deployed_content})
    home = tmp_path / "home"
    mutable_target = tmp_path / "mutable-worktree" / "override.conf"
    mutable_target.parent.mkdir()
    mutable_target.write_text("[Service]\nEnvironment=DEMO=old\n", encoding="utf-8")
    deployed = home / ".config/systemd/user/demo.service.d/override.conf"
    deployed.parent.mkdir(parents=True)
    deployed.symlink_to(mutable_target)
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha],
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
    assert mutable_target.read_text(encoding="utf-8") == "[Service]\nEnvironment=DEMO=old\n"
    assert deployed.read_text(encoding="utf-8") == deployed_content
    assert not deployed.is_symlink()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user restart demo.service" in calls


def test_generic_service_dropin_git_inspection_failure_creates_no_target_directory(
    tmp_path: Path,
) -> None:
    dropin_path = "systemd/units/demo.service.d/override.conf"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {dropin_path: "[Service]\nEnvironment=DEMO=new\n"},
    )
    home = tmp_path / "home"
    dropin_dir = home / ".config/systemd/user/demo.service.d"
    git_bin = _fake_git_with_ls_tree_failure(tmp_path)
    systemctl_bin, systemctl_calls = _fake_systemctl(tmp_path)
    cursor = tmp_path / "traces/last-deployed-sha"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{git_bin}:{systemctl_bin}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/deploy.jsonl"),
            "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
            "HAPAX_FAIL_GIT_LS_TREE_PATH": dropin_path,
            "HAPAX_FAIL_GIT_LS_TREE_COUNT_FILE": str(tmp_path / "git-ls-tree.count"),
            "HAPAX_FAIL_GIT_LS_TREE_ON_COUNT": "1",
        },
    )

    assert result.returncode != 0
    assert "refusing to infer deletion" in result.stderr
    assert not dropin_dir.exists()
    calls = systemctl_calls.read_text(encoding="utf-8") if systemctl_calls.exists() else ""
    assert "daemon-reload" not in calls
    assert not cursor.exists()


def test_system_scoped_base_routes_changed_dropin_to_runtime_deferral(tmp_path: Path) -> None:
    unit_path = "systemd/units/demo-root.service"
    dropin_path = f"{unit_path}.d/override.conf"
    unit_body = (
        "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
    )
    dropin_body = "[Service]\nEnvironment=DEMO=system\n"
    repo, _ = _repo_with_linear_commit(
        tmp_path,
        {unit_path: unit_body},
    )
    source_dropin = repo / dropin_path
    source_dropin.parent.mkdir()
    source_dropin.write_text(dropin_body, encoding="utf-8")
    _git(repo, "add", dropin_path)
    _git(repo, "commit", "-m", "add system unit drop-in")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    stale_user_dropin = home / ".config/systemd/user/demo-root.service.d/override.conf"
    stale_user_dropin.parent.mkdir(parents=True)
    stale_user_dropin.write_text("[Service]\nEnvironment=DEMO=user\n", encoding="utf-8")
    system_dir = tmp_path / "systemd-system"
    system_dir.mkdir()
    bin_dir, systemctl_calls = _fake_systemctl_with_system_witness(tmp_path, system_dir)
    script = _post_merge_script_with_system_dir(tmp_path, system_dir)
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(script), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not stale_user_dropin.exists()
    assert "--user restart demo-root.service" not in (
        systemctl_calls.read_text(encoding="utf-8") if systemctl_calls.exists() else ""
    )
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["runtime_deferred"] == [f"systemd-system-dropin:{dropin_path}"]
    assert record["deploy_groups"]["systemd_dropins"] == []
    assert record["deploy_groups"]["systemd_system_dropins"] == [dropin_path]
    pending_path = trace_path.parent / "systemd-runtime-pending.json"
    assert json.loads(pending_path.read_text(encoding="utf-8"))["paths"] == [dropin_path]

    (repo / "README.md").write_text("unrelated drop-in successor\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "unrelated drop-in successor")
    successor_sha = _git(repo, "rev-parse", "HEAD")
    (system_dir / "demo-root.service").write_text(unit_body, encoding="utf-8")
    installed_dropin = system_dir / "demo-root.service.d/override.conf"
    installed_dropin.parent.mkdir()
    installed_dropin.write_text(dropin_body, encoding="utf-8")

    converged = subprocess.run(
        [str(script), successor_sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert converged.returncode == 0, converged.stderr
    assert not pending_path.exists()
    replay_record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert replay_record["changed_files"] == ["README.md"]
    assert replay_record["systemd_runtime_replayed"] == [dropin_path]
    assert replay_record["runtime_deferred"] == []


def test_deleted_system_dropin_converges_with_absent_dropin_directory(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/demo-root.service"
    dropin_path = f"{unit_path}.d/override.conf"
    unit_body = (
        "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
    )
    repo, _ = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: unit_body,
            dropin_path: "[Service]\nEnvironment=OLD=yes\n",
        },
    )
    (repo / dropin_path).unlink()
    _git(repo, "add", "-u")
    _git(repo, "commit", "-m", "delete system drop-in")
    sha = _git(repo, "rev-parse", "HEAD")

    home = tmp_path / "home"
    system_dir = tmp_path / "systemd-system"
    system_dir.mkdir()
    (system_dir / Path(unit_path).name).write_text(unit_body, encoding="utf-8")
    assert not (system_dir / "demo-root.service.d").exists()
    script = _post_merge_script_with_system_dir(tmp_path, system_dir)
    bin_dir, systemctl_calls = _fake_systemctl_with_system_witness(tmp_path, system_dir)
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"

    result = subprocess.run(
        [str(script), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "exact file and system-manager witness" in result.stdout
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["runtime_deferred"] == []
    assert record["deploy_groups"]["systemd_system_dropins"] == [dropin_path]
    assert not (trace_path.parent / "systemd-runtime-pending.json").exists()


@pytest.mark.parametrize("hostile_state", ("writable", "mutated-during-query"))
def test_system_unit_with_no_dropins_requires_stable_trusted_empty_directory(
    tmp_path: Path,
    hostile_state: str,
) -> None:
    unit_path = "systemd/units/demo-root.service"
    old_body = (
        "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
    )
    new_body = old_body.replace("/usr/bin/true", "/usr/bin/false")
    repo, _ = _repo_with_linear_commit(tmp_path, {unit_path: old_body})
    (repo / unit_path).write_text(new_body, encoding="utf-8")
    _git(repo, "add", unit_path)
    _git(repo, "commit", "-m", "change system unit without drop-ins")
    sha = _git(repo, "rev-parse", "HEAD")

    home = tmp_path / "home"
    system_dir = tmp_path / "systemd-system"
    system_dir.mkdir()
    (system_dir / Path(unit_path).name).write_text(new_body, encoding="utf-8")
    installed_dropin_dir = system_dir / "demo-root.service.d"
    installed_dropin_dir.mkdir()
    bin_dir, systemctl_calls = _fake_systemctl_with_system_witness(tmp_path, system_dir)
    if hostile_state == "writable":
        installed_dropin_dir.chmod(0o777)
    else:
        baseline = bin_dir / "systemctl-baseline"
        (bin_dir / "systemctl").rename(baseline)
        (bin_dir / "systemctl").write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'"{baseline}" "$@"\n'
            'if [[ "$*" == "show demo-root.service --property='
            'LoadState,FragmentPath,DropInPaths,NeedDaemonReload --no-pager" ]]; then\n'
            f'  : > "{installed_dropin_dir}/transient"\n'
            f'  /usr/bin/rm -f -- "{installed_dropin_dir}/transient"\n'
            "fi\n",
            encoding="utf-8",
        )
        (bin_dir / "systemctl").chmod(0o755)

    trace_path = tmp_path / "traces/post-merge-traces.jsonl"
    script = _post_merge_script_with_system_dir(tmp_path, system_dir)
    result = subprocess.run(
        [str(script), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "runtime deferred" in result.stderr
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["runtime_deferred"] == [f"systemd-system:{unit_path}"]


def test_generic_slice_dropin_rejects_symlink_with_removed_property(tmp_path: Path) -> None:
    dropin_path = "systemd/units/demo.slice.d/memory.conf"
    candidate_content = "[Slice]\nMemoryHigh=2G\nMemoryMax=3G\n"
    repo, sha = _repo_with_linear_commit(tmp_path, {dropin_path: candidate_content})
    home = tmp_path / "home"
    mutable_target = tmp_path / "mutable-worktree" / "memory.conf"
    mutable_target.parent.mkdir()
    prior_content = "[Slice]\nMemoryHigh=1G\nMemoryLow=256M\n"
    mutable_target.write_text(prior_content, encoding="utf-8")
    deployed = home / ".config/systemd/user/demo.slice.d/memory.conf"
    deployed.parent.mkdir(parents=True)
    deployed.symlink_to(mutable_target)
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha],
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

    assert result.returncode == 1
    assert "unsafe changed generic slice destination" in result.stderr
    assert deployed.is_symlink()
    assert mutable_target.read_text(encoding="utf-8") == prior_content
    calls = systemctl_calls.read_text(encoding="utf-8") if systemctl_calls.exists() else ""
    assert "daemon-reload" not in calls
    assert "set-property" not in calls


def test_generic_slice_dropin_deletion_fails_before_persistent_or_runtime_drift(
    tmp_path: Path,
) -> None:
    dropin_path = "systemd/units/demo.slice.d/memory.conf"
    old_content = "[Slice]\nMemoryHigh=1G\nMemoryLow=256M\n"
    repo, _ = _repo_with_linear_commit(tmp_path, {dropin_path: old_content})
    _git(repo, "rm", dropin_path)
    _git(repo, "commit", "-m", "delete generic slice policy")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    deployed = home / ".config/systemd/user/demo.slice.d/memory.conf"
    deployed.parent.mkdir(parents=True)
    deployed.write_text(old_content, encoding="utf-8")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha],
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

    assert result.returncode == 1
    assert "refusing generic slice drop-in deletion" in result.stderr
    assert "next action:" in result.stderr
    assert deployed.read_text(encoding="utf-8") == old_content
    calls = systemctl_calls.read_text(encoding="utf-8") if systemctl_calls.exists() else ""
    assert "restart demo.slice" not in calls


def test_generic_slice_dropin_rejects_unsupported_live_directive(tmp_path: Path) -> None:
    dropin_path = "systemd/units/demo.slice.d/policy.conf"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {dropin_path: "[Slice]\nMemoryHigh=1G\nCPUWeight=100\n"},
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha],
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

    assert result.returncode == 1
    assert "unsupported generic slice directive" in result.stderr
    assert not (home / ".config/systemd/user" / dropin_path.removeprefix("systemd/units/")).exists()
    calls = systemctl_calls.read_text(encoding="utf-8") if systemctl_calls.exists() else ""
    assert "set-property" not in calls


def test_generic_slice_dropin_rejects_invalid_memory_value_before_mutation(
    tmp_path: Path,
) -> None:
    dropin_path = "systemd/units/demo.slice.d/memory.conf"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {dropin_path: "[Slice]\nMemoryHigh=garbage\nMemoryMax=2G\n"},
    )
    home = tmp_path / "home"
    deployed = home / ".config/systemd/user/demo.slice.d/memory.conf"
    deployed.parent.mkdir(parents=True)
    deployed.write_text("[Slice]\nMemoryHigh=1G\nMemoryMax=2G\n", encoding="utf-8")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha],
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

    assert result.returncode == 1
    assert "invalid generic slice memory value" in result.stderr
    assert deployed.read_text(encoding="utf-8") == "[Slice]\nMemoryHigh=1G\nMemoryMax=2G\n"
    calls = systemctl_calls.read_text(encoding="utf-8") if systemctl_calls.exists() else ""
    assert "daemon-reload" not in calls
    assert "set-property" not in calls


def test_generic_slice_dropin_rejects_memory_property_outside_slice_section(
    tmp_path: Path,
) -> None:
    dropin_path = "systemd/units/demo.slice.d/wrong-section.conf"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {dropin_path: "[Service]\nMemoryHigh=1G\n"},
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha],
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

    assert result.returncode == 1
    assert "unsupported generic slice directive" in result.stderr
    calls = systemctl_calls.read_text(encoding="utf-8") if systemctl_calls.exists() else ""
    assert "set-property" not in calls


def test_generic_slice_dropin_property_removal_fails_before_runtime_drift(
    tmp_path: Path,
) -> None:
    dropin_path = "systemd/units/demo.slice.d/memory.conf"
    old_content = "[Slice]\nMemoryHigh=1G\nMemoryLow=256M\n"
    repo, _ = _repo_with_linear_commit(tmp_path, {dropin_path: old_content})
    updated = repo / dropin_path
    updated.write_text("[Slice]\nMemoryHigh=2G\n", encoding="utf-8")
    _git(repo, "add", dropin_path)
    _git(repo, "commit", "-m", "remove generic slice reservation")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    deployed = home / ".config/systemd/user/demo.slice.d/memory.conf"
    deployed.parent.mkdir(parents=True)
    deployed.write_text(old_content, encoding="utf-8")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha],
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

    assert result.returncode == 1
    assert "refusing generic removal of MemoryLow" in result.stderr
    assert "next action:" in result.stderr
    assert deployed.read_text(encoding="utf-8") == old_content
    calls = systemctl_calls.read_text(encoding="utf-8") if systemctl_calls.exists() else ""
    assert "set-property" not in calls


def test_generic_slice_dropin_skipped_release_property_removal_fails(
    tmp_path: Path,
) -> None:
    dropin_path = "systemd/units/demo.slice.d/memory.conf"
    deployed_content = "[Slice]\nMemoryHigh=1G\nMemoryLow=256M\n"
    repo, _ = _repo_with_linear_commit(tmp_path, {dropin_path: deployed_content})
    updated = repo / dropin_path
    updated.write_text("[Slice]\nMemoryHigh=2G\n", encoding="utf-8")
    _git(repo, "add", dropin_path)
    _git(repo, "commit", "-m", "remove reservation in skipped release")
    updated.write_text("[Slice]\nMemoryHigh=3G\n", encoding="utf-8")
    _git(repo, "add", dropin_path)
    _git(repo, "commit", "-m", "change surviving property")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    deployed = home / ".config/systemd/user/demo.slice.d/memory.conf"
    deployed.parent.mkdir(parents=True)
    deployed.write_text(deployed_content, encoding="utf-8")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha],
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

    assert result.returncode == 1
    assert "refusing generic removal of MemoryLow" in result.stderr
    assert deployed.read_text(encoding="utf-8") == deployed_content
    calls = systemctl_calls.read_text(encoding="utf-8") if systemctl_calls.exists() else ""
    assert "daemon-reload" not in calls
    assert "set-property" not in calls


def test_generic_scope_dropin_fails_closed_without_restart(tmp_path: Path) -> None:
    dropin_path = "systemd/units/demo.scope.d/memory.conf"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {dropin_path: "[Scope]\nMemoryMax=1G\n"},
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha],
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

    assert result.returncode == 1
    assert "refusing generic scope drop-in deploy" in result.stderr
    assert "next action:" in result.stderr
    calls = systemctl_calls.read_text(encoding="utf-8") if systemctl_calls.exists() else ""
    assert "restart demo.scope" not in calls


def test_parked_service_is_disabled_without_restart(tmp_path: Path) -> None:
    unit_path = "systemd/units/demo-parked.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "# Hapax-Parked: true\n"
                "[Unit]\nDescription=Parked test service\n"
                "[Service]\nType=oneshot\nExecStart=/usr/bin/true\nRestart=no\n"
            )
        },
    )
    home = tmp_path / "home"
    deployed = home / ".config/systemd/user/demo-parked.service"
    deployed.parent.mkdir(parents=True)
    deployed.write_text("[Service]\nExecStart=/usr/bin/false\nRestart=always\n", encoding="utf-8")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha],
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
    assert "parking demo-parked.service" in result.stdout
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user stop demo-parked.service" in calls
    assert "--user show demo-parked.service -p ActiveState --value" in calls
    assert "--user disable demo-parked.service" in calls
    assert "--user reset-failed demo-parked.service" in calls
    assert "--user restart demo-parked.service" not in calls
    assert "--user enable --now demo-parked.service" not in calls
    ordered_calls = calls.splitlines()
    assert (
        ordered_calls.index("--user stop demo-parked.service")
        < ordered_calls.index("--user show demo-parked.service -p ActiveState --value")
        < ordered_calls.index("--user disable demo-parked.service")
    )
    assert ordered_calls.index("--user disable demo-parked.service") < ordered_calls.index(
        "--user daemon-reload"
    )


def test_new_parked_service_is_not_pre_stopped_before_its_first_publication(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/new-parked.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "# Hapax-Parked: true\n"
                "[Unit]\nDescription=New parked sentinel\n"
                "[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
            )
        },
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    (bin_dir / "systemctl").write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'case "$*" in\n'
        "  '--user show new-parked.service -p LoadState --value') printf 'not-found\\n' ;;\n"
        "  '--user show new-parked.service -p ActiveState --value') printf 'inactive\\n' ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "systemctl").chmod(0o755)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/trace.jsonl"),
        },
    )

    assert result.returncode == 0, result.stderr
    calls = systemctl_calls.read_text(encoding="utf-8").splitlines()
    assert calls.index("--user daemon-reload") < calls.index("--user stop new-parked.service")
    assert calls.index("--user stop new-parked.service") < calls.index(
        "--user disable new-parked.service"
    )
    assert (home / ".config/systemd/user/new-parked.service").is_file()


def test_loaded_parked_service_without_installed_file_is_pre_stopped(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/loaded-parked.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "# Hapax-Parked: true\n"
                "[Unit]\nDescription=Loaded parked sentinel\n"
                "[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
            )
        },
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    (bin_dir / "systemctl").write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'case "$*" in\n'
        "  '--user show loaded-parked.service -p LoadState --value') printf 'loaded\\n' ;;\n"
        "  '--user show loaded-parked.service -p ActiveState --value') printf 'inactive\\n' ;;\n"
        "  '--user stop loaded-parked.service') : ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "systemctl").chmod(0o755)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/trace.jsonl"),
        },
    )

    assert result.returncode == 0, result.stderr
    calls = systemctl_calls.read_text(encoding="utf-8").splitlines()
    assert (
        calls.index("--user stop loaded-parked.service")
        < calls.index("--user disable loaded-parked.service")
        < calls.index("--user daemon-reload")
    )
    assert (home / ".config/systemd/user/loaded-parked.service").is_file()


def test_not_found_but_active_parked_service_is_pre_stopped(tmp_path: Path) -> None:
    unit_path = "systemd/units/not-found-active-parked.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {unit_path: ("# Hapax-Parked: true\n[Service]\nExecStart=/usr/bin/true\nRestart=no\n")},
    )
    home = tmp_path / "home"
    state = tmp_path / "active-state"
    state.write_text("active\n", encoding="utf-8")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    (bin_dir / "systemctl").write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'case "$*" in\n'
        "  '--user show not-found-active-parked.service -p LoadState --value') printf 'not-found\\n' ;;\n"
        "  '--user show not-found-active-parked.service -p ActiveState --value') cat \"$HAPAX_ACTIVE_STATE\" ;;\n"
        "  '--user stop not-found-active-parked.service') printf 'inactive\\n' > \"$HAPAX_ACTIVE_STATE\" ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "systemctl").chmod(0o755)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_ACTIVE_STATE": str(state),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/trace.jsonl"),
        },
    )

    assert result.returncode == 0, result.stderr
    calls = systemctl_calls.read_text(encoding="utf-8").splitlines()
    assert calls.index("--user stop not-found-active-parked.service") < calls.index(
        "--user daemon-reload"
    )


def test_parked_service_is_disabled_before_a_failing_daemon_reload(tmp_path: Path) -> None:
    unit_path = "systemd/units/demo-parked.service"
    target_body = (
        "# Hapax-Parked: true\n"
        "[Unit]\nDescription=Parked test service\n"
        "[Service]\nType=oneshot\nExecStart=/usr/bin/true\nRestart=no\n"
    )
    repo, sha = _repo_with_linear_commit(tmp_path, {unit_path: target_body})
    home = tmp_path / "home"
    deployed = home / ".config/systemd/user/demo-parked.service"
    deployed.parent.mkdir(parents=True)
    deployed.write_text(
        "[Unit]\nDescription=Historical active detector\n"
        "[Service]\nExecStart=/usr/bin/false\nRestart=always\n",
        encoding="utf-8",
    )
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    (bin_dir / "systemctl").write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'case "$*" in\n'
        "  '--user show demo-parked.service -p ActiveState --value') printf 'inactive\\n'; exit 0 ;;\n"
        "esac\n"
        '[ "$*" != "--user daemon-reload" ] || exit 88\n'
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "systemctl").chmod(0o755)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/trace.jsonl"),
        },
    )

    assert result.returncode == 88
    calls = systemctl_calls.read_text(encoding="utf-8").splitlines()
    assert "--user stop demo-parked.service" in calls
    assert "--user disable demo-parked.service" in calls
    assert calls.index("--user disable demo-parked.service") < calls.index("--user daemon-reload")
    assert deployed.read_text(encoding="utf-8") == target_body
    assert not (tmp_path / "traces/last-deployed-sha").exists()


def test_parked_service_disable_failure_happens_only_after_verified_stop(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/disable-failure-parked.service"
    target_body = "# Hapax-Parked: true\n[Service]\nExecStart=/usr/bin/true\nRestart=no\n"
    repo, sha = _repo_with_linear_commit(tmp_path, {unit_path: target_body})
    home = tmp_path / "home"
    deployed = home / ".config/systemd/user/disable-failure-parked.service"
    deployed.parent.mkdir(parents=True)
    historical_body = "[Service]\nExecStart=/usr/bin/false\nRestart=always\n"
    deployed.write_text(historical_body, encoding="utf-8")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    (bin_dir / "systemctl").write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'case "$*" in\n'
        "  '--user show disable-failure-parked.service -p ActiveState --value') printf 'inactive\\n' ;;\n"
        "  '--user disable disable-failure-parked.service') exit 89 ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "systemctl").chmod(0o755)
    trace_path = tmp_path / "traces/trace.jsonl"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        },
    )

    assert result.returncode == 1
    calls = systemctl_calls.read_text(encoding="utf-8").splitlines()
    assert (
        calls.index("--user stop disable-failure-parked.service")
        < calls.index("--user show disable-failure-parked.service -p ActiveState --value")
        < calls.index("--user disable disable-failure-parked.service")
    )
    assert deployed.read_text(encoding="utf-8") == historical_body
    assert not (trace_path.parent / "last-deployed-sha").exists()


def test_rebuild_service_compatibility_copy_is_byte_identical_to_canonical() -> None:
    compatibility = REPO_ROOT / "systemd/hapax-rebuild-services.service"
    canonical = REPO_ROOT / "systemd/units/hapax-rebuild-services.service"

    assert compatibility.read_bytes() == canonical.read_bytes()


def test_pre_guard_deploy_helper_bootstraps_rebuild_compatibility_copy(
    tmp_path: Path,
) -> None:
    predecessor = tmp_path / "hapax-post-merge-deploy.pre-guard"
    predecessor.write_text(
        _git(REPO_ROOT, "show", f"{PRE_GUARD_DEPLOY_SHA}:scripts/hapax-post-merge-deploy"),
        encoding="utf-8",
    )
    predecessor.chmod(0o755)
    canonical_body = (REPO_ROOT / "systemd/units/hapax-rebuild-services.service").read_text(
        encoding="utf-8"
    )
    legacy_path = "systemd/hapax-rebuild-services.service"
    repo, _ = _repo_with_linear_commit(
        tmp_path,
        {
            legacy_path: "[Service]\nExecStart=/unsafe/predecessor\n",
            "systemd/units/hapax-rebuild-services.service": canonical_body,
        },
    )
    (repo / legacy_path).write_text(canonical_body, encoding="utf-8")
    _git(repo, "add", legacy_path)
    _git(repo, "commit", "-m", "publish safe rebuild compatibility copy")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    deployed = home / ".config/systemd/user/hapax-rebuild-services.service"
    deployed.parent.mkdir(parents=True)
    deployed.write_text("[Service]\nExecStart=/unsafe/installed\n", encoding="utf-8")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(predecessor), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/trace.jsonl"),
        },
    )

    assert result.returncode == 0, result.stderr
    assert deployed.read_text(encoding="utf-8") == canonical_body
    assert "--user daemon-reload" in systemctl_calls.read_text(encoding="utf-8")


def _rollout_adoption_fixture(tmp_path: Path) -> tuple[Path, Path, str, Path, Path]:
    repo = tmp_path / "rollout-repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "rollout-test@example.test")
    _git(repo, "config", "user.name", "Rollout Test")
    deploy_path = repo / "scripts/hapax-post-merge-deploy"
    smoke_path = repo / "scripts/hapax-post-merge-smoke"
    install_path = repo / "systemd/scripts/install-units.sh"
    deploy_path.parent.mkdir(parents=True)
    install_path.parent.mkdir(parents=True)
    deploy_path.write_text(
        _git(REPO_ROOT, "show", f"{PRE_GUARD_DEPLOY_SHA}:scripts/hapax-post-merge-deploy"),
        encoding="utf-8",
    )
    smoke_path.write_text(
        _git(REPO_ROOT, "show", f"{PRE_GUARD_DEPLOY_SHA}:scripts/hapax-post-merge-smoke"),
        encoding="utf-8",
    )
    install_path.write_text("DECOMMISSIONED_UNITS=(\n)\n", encoding="utf-8")
    deploy_path.chmod(0o755)
    smoke_path.chmod(0o755)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "pre-adoption deploy contract")

    deploy_path.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    smoke_path.write_text(SMOKE.read_text(encoding="utf-8"), encoding="utf-8")
    deploy_path.chmod(0o755)
    smoke_path.chmod(0o755)
    unit = repo / "systemd/units/rollout-adoption.service"
    unit.parent.mkdir(parents=True)
    unit.write_text(
        "[Unit]\nDescription=Rollout adoption witness\n[Service]\nExecStart=/usr/bin/true\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "adopt blocking exact deploy contract")
    sha = _git(repo, "rev-parse", "HEAD")

    predecessor_dir = tmp_path / "predecessor"
    predecessor_dir.mkdir()
    predecessor = predecessor_dir / "hapax-post-merge-deploy"
    predecessor.write_text(
        _git(REPO_ROOT, "show", f"{PRE_GUARD_DEPLOY_SHA}:scripts/hapax-post-merge-deploy"),
        encoding="utf-8",
    )
    predecessor.chmod(0o755)

    bin_dir = tmp_path / "rollout-bin"
    bin_dir.mkdir()
    calls = tmp_path / "rollout-systemctl-calls.txt"
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            printf '%s\n' "$*" >> "{calls}"
            case "$*" in
              "--user show rollout-adoption.service -p ActiveState --value")
                if [ "${{HAPAX_ROLLOUT_MANAGER_FAIL:-0}}" = 1 ]; then exit 86; fi
                printf 'active\n'
                ;;
              "--user is-active --quiet "*) exit 3 ;;
            esac
            exit 0
            """
        ),
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    return repo, predecessor, sha, bin_dir, calls


def test_predecessor_adopts_exact_helper_before_first_completion_receipt(
    tmp_path: Path,
) -> None:
    repo, predecessor, sha, bin_dir, _ = _rollout_adoption_fixture(tmp_path)
    home = tmp_path / "home"
    trace = tmp_path / "traces/deploy.jsonl"
    cursor = trace.parent / "last-deployed-sha"

    result = subprocess.run(
        [str(predecessor), sha],
        text=True,
        capture_output=True,
        check=False,
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace),
            "HAPAX_DRIFT_NTFY": "0",
        },
        timeout=30,
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
    installed_helper = home / ".local/bin/hapax-post-merge-deploy"
    assert installed_helper.read_bytes() == SCRIPT.read_bytes()
    assert cursor.read_text(encoding="utf-8").strip() == sha
    marker = _deploy_cursor_marker(home)
    assert marker.read_text(encoding="utf-8") == "hapax-deploy-cursor-established-v1\n"


def test_predecessor_cannot_stamp_when_adopted_exact_smoke_fails(tmp_path: Path) -> None:
    repo, predecessor, sha, bin_dir, _ = _rollout_adoption_fixture(tmp_path)
    home = tmp_path / "home"
    trace = tmp_path / "traces/deploy.jsonl"
    cursor = trace.parent / "last-deployed-sha"

    result = subprocess.run(
        [str(predecessor), sha],
        text=True,
        capture_output=True,
        check=False,
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace),
            "HAPAX_ROLLOUT_MANAGER_FAIL": "1",
            "HAPAX_DRIFT_NTFY": "0",
        },
        timeout=30,
    )

    assert result.returncode != 0
    assert "exact replacement deploy failed" in result.stderr
    assert "exact-target smoke runner failed" in result.stderr
    assert not cursor.exists()
    assert not _deploy_cursor_marker(home).exists()


def test_current_helper_maps_historical_rebuild_path_to_canonical_object(
    tmp_path: Path,
) -> None:
    legacy_path = "systemd/hapax-rebuild-services.service"
    canonical_path = "systemd/units/hapax-rebuild-services.service"
    canonical_body = "[Service]\nExecStart=/safe/canonical\n"
    repo, _ = _repo_with_linear_commit(
        tmp_path,
        {
            legacy_path: "[Service]\nExecStart=/old/legacy\n",
            canonical_path: canonical_body,
        },
    )
    (repo / legacy_path).write_text("[Service]\nExecStart=/divergent/legacy\n", encoding="utf-8")
    _git(repo, "add", legacy_path)
    _git(repo, "commit", "-m", "change historical path")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    deployed = home / ".config/systemd/user/hapax-rebuild-services.service"
    deployed.parent.mkdir(parents=True)
    deployed.write_text("[Service]\nExecStart=/unsafe/installed\n", encoding="utf-8")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/trace.jsonl"),
        },
    )

    assert result.returncode == 0, result.stderr
    assert deployed.read_text(encoding="utf-8") == canonical_body


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


def test_system_scoped_units_defer_runtime_without_blocking_source_deploy(tmp_path: Path) -> None:
    unit_path = "systemd/units/hapax-l12-critical-usb-guard.service"
    unit_body = (
        "[Unit]\n"
        "  # Hapax-Install-Scope : system  \n"
        "Description=System scoped guard\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "ExecStart=/usr/local/bin/hapax-l12-critical-usb-guard\n"
    )
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {unit_path: unit_body},
    )
    home = tmp_path / "home"
    stale_user_unit = home / ".config" / "systemd" / "user" / "hapax-l12-critical-usb-guard.service"
    stale_user_unit.parent.mkdir(parents=True)
    stale_user_unit.write_text("stale\n", encoding="utf-8")
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    cursor = tmp_path / "traces" / "last-deployed-sha"
    system_dir = tmp_path / "systemd-system"
    system_dir.mkdir()
    bin_dir, systemctl_calls = _fake_systemctl_with_system_witness(tmp_path, system_dir)
    script = _post_merge_script_with_system_dir(tmp_path, system_dir)
    reload_marker = tmp_path / "system-needs-daemon-reload"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
        "HAPAX_SYSTEMCTL_NEEDS_RELOAD_MARKER": str(reload_marker),
    }

    deferred = subprocess.run(
        [str(script), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert deferred.returncode == 0, deferred.stderr
    assert "runtime deferred" in deferred.stderr
    assert not stale_user_unit.exists()
    assert cursor.read_text(encoding="utf-8").strip() == sha
    deferred_record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert deferred_record["status"] == "completed_with_runtime_deferral"
    assert deferred_record["runtime_deferred"] == [f"systemd-system:{unit_path}"]
    pending_path = trace_path.parent / "systemd-runtime-pending.json"
    assert json.loads(pending_path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "paths": [unit_path],
    }

    (repo / "README.md").write_text("unrelated successor\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "unrelated successor")
    successor_sha = _git(repo, "rev-parse", "HEAD")

    (system_dir / Path(unit_path).name).write_text(unit_body, encoding="utf-8")
    reload_marker.touch()
    not_reloaded = subprocess.run(
        [str(script), successor_sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert not_reloaded.returncode == 0
    assert "system manager has not loaded" in not_reloaded.stderr
    assert cursor.read_text(encoding="utf-8").strip() == successor_sha
    replay_record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert replay_record["changed_files"] == ["README.md"]
    assert replay_record["systemd_runtime_replayed"] == [unit_path]
    assert json.loads(pending_path.read_text(encoding="utf-8"))["paths"] == [unit_path]

    reload_marker.unlink()
    result = subprocess.run(
        [str(script), successor_sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "exact file and system-manager witness" in result.stdout
    assert cursor.read_text(encoding="utf-8").strip() == successor_sha
    assert not pending_path.exists()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user disable --now hapax-l12-critical-usb-guard.service" in calls
    assert "--user daemon-reload" in calls
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["systemd_system_units"] == [unit_path]
    assert record["deploy_groups"]["systemd_units"] == []


def test_changed_system_scoped_unit_records_deferral_until_exact_bytes_are_installed(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/hapax-system-demo.service"
    old_body = (
        "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
    )
    new_body = old_body.replace("/usr/bin/true", "/usr/bin/false")
    repo, _ = _repo_with_linear_commit(tmp_path, {unit_path: old_body})
    (repo / unit_path).write_text(new_body, encoding="utf-8")
    _git(repo, "add", unit_path)
    _git(repo, "commit", "-m", "change system unit")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    system_dir = tmp_path / "systemd-system"
    system_dir.mkdir()
    installed = system_dir / Path(unit_path).name
    installed.write_text(old_body, encoding="utf-8")
    script = _post_merge_script_with_system_dir(tmp_path, system_dir)
    bin_dir, systemctl_calls = _fake_systemctl_with_system_witness(tmp_path, system_dir)
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"
    cursor = tmp_path / "traces/last-deployed-sha"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
    }

    deferred = subprocess.run(
        [str(script), sha], text=True, capture_output=True, check=False, env=env
    )
    assert deferred.returncode == 0, deferred.stderr
    assert cursor.read_text(encoding="utf-8").strip() == sha
    deferred_record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert deferred_record["status"] == "completed_with_runtime_deferral"

    installed.write_text(new_body, encoding="utf-8")
    converged = subprocess.run(
        [str(script), sha], text=True, capture_output=True, check=False, env=env
    )
    assert converged.returncode == 0, converged.stderr
    assert cursor.read_text(encoding="utf-8").strip() == sha


@pytest.mark.parametrize(
    "hostile_state",
    ["owner", "mode", "hardlink", "ancestor-mode", "sibling-content"],
)
def test_system_manager_witness_rejects_untrusted_effective_unit_files(
    tmp_path: Path,
    hostile_state: str,
) -> None:
    unit_path = "systemd/units/hapax-system-demo.service"
    dropin_path = f"{unit_path}.d/override.conf"
    old_body = (
        "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
    )
    new_body = old_body.replace("/usr/bin/true", "/usr/bin/false")
    dropin_body = "[Service]\nEnvironment=PINNED=yes\n"
    repo, _ = _repo_with_linear_commit(
        tmp_path,
        {unit_path: old_body, dropin_path: dropin_body},
    )
    (repo / unit_path).write_text(new_body, encoding="utf-8")
    _git(repo, "add", unit_path)
    _git(repo, "commit", "-m", "change exact system unit")
    sha = _git(repo, "rev-parse", "HEAD")

    home = tmp_path / "home"
    system_dir = tmp_path / "systemd-system"
    system_dir.mkdir()
    installed = system_dir / Path(unit_path).name
    installed.write_text(new_body, encoding="utf-8")
    installed_dropin = system_dir / Path(dropin_path).relative_to("systemd/units")
    installed_dropin.parent.mkdir()
    installed_dropin.write_text(dropin_body, encoding="utf-8")

    expected_uid = None
    if hostile_state == "owner":
        expected_uid = os.geteuid() + 1
    elif hostile_state == "mode":
        installed.chmod(0o664)
    elif hostile_state == "hardlink":
        os.link(installed, system_dir / "unexpected-hardlink")
    elif hostile_state == "ancestor-mode":
        system_dir.chmod(0o777)
    elif hostile_state == "sibling-content":
        installed_dropin.write_text("[Service]\nEnvironment=HOSTILE=yes\n", encoding="utf-8")
    else:  # pragma: no cover - exhaustive parametrization guard
        raise AssertionError(hostile_state)

    script = _post_merge_script_with_system_dir(
        tmp_path,
        system_dir,
        expected_uid=expected_uid,
    )
    bin_dir, systemctl_calls = _fake_systemctl_with_system_witness(tmp_path, system_dir)
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"
    result = subprocess.run(
        [str(script), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "runtime deferred" in result.stderr
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["status"] == "completed_with_runtime_deferral"
    assert record["runtime_deferred"] == [f"systemd-system:{unit_path}"]


def test_system_scope_retirement_rechecks_user_filesystem_after_manager_query(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/hapax-system-race.service"
    old_body = (
        "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
    )
    new_body = old_body.replace("/usr/bin/true", "/usr/bin/false")
    repo, _ = _repo_with_linear_commit(tmp_path, {unit_path: old_body})
    (repo / unit_path).write_text(new_body, encoding="utf-8")
    _git(repo, "add", unit_path)
    _git(repo, "commit", "-m", "change system race unit")
    sha = _git(repo, "rev-parse", "HEAD")

    home = tmp_path / "home"
    user_dir = home / ".config/systemd/user"
    wants_dir = user_dir / "default.target.wants"
    wants_dir.mkdir(parents=True)
    system_dir = tmp_path / "systemd-system"
    system_dir.mkdir()
    (system_dir / Path(unit_path).name).write_text(new_body, encoding="utf-8")
    script = _post_merge_script_with_system_dir(tmp_path, system_dir)
    bin_dir, systemctl_calls = _fake_systemctl_with_system_witness(tmp_path, system_dir)
    systemctl = bin_dir / "systemctl"
    baseline = bin_dir / "systemctl-baseline"
    systemctl.rename(baseline)
    injected = wants_dir / Path(unit_path).name
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'if [ "$*" = "--user show {Path(unit_path).name} '
        '--property=LoadState,FragmentPath,ActiveState,SubState --no-pager" ]; then\n'
        f"  /usr/bin/ln -s /dev/null {shlex.quote(str(injected))}\n"
        "fi\n"
        f'exec {shlex.quote(str(baseline))} "$@"\n',
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"

    result = subprocess.run(
        [str(script), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        },
    )

    assert result.returncode != 0
    assert "filesystem state changed across the manager absence witness" in result.stderr
    assert injected.is_symlink()
    assert not (trace_path.parent / "last-deployed-sha").exists()


def test_system_to_user_scope_transition_defers_then_replays_after_system_absence(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/hapax-scope-transition.service"
    system_body = (
        "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
    )
    user_body = "[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
    repo, _ = _repo_with_linear_commit(tmp_path, {unit_path: system_body})
    (repo / unit_path).write_text(user_body, encoding="utf-8")
    _git(repo, "add", unit_path)
    _git(repo, "commit", "-m", "move unit to user scope")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    system_dir = tmp_path / "systemd-system"
    system_dir.mkdir()
    installed_system_unit = system_dir / Path(unit_path).name
    installed_system_unit.write_text(system_body, encoding="utf-8")
    script = _post_merge_script_with_system_dir(tmp_path, system_dir)
    bin_dir, systemctl_calls = _fake_systemctl_with_system_witness(tmp_path, system_dir)
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"
    pending_path = trace_path.parent / "systemd-runtime-pending.json"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    deferred = subprocess.run(
        [str(script), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert deferred.returncode == 0, deferred.stderr
    assert "refusing user-manager publication" in deferred.stderr
    assert not (home / ".config/systemd/user/hapax-scope-transition.service").exists()
    assert json.loads(pending_path.read_text(encoding="utf-8"))["paths"] == [unit_path]

    installed_system_unit.unlink()
    (repo / "README.md").write_text("unrelated transition successor\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "unrelated transition successor")
    successor_sha = _git(repo, "rev-parse", "HEAD")
    result = subprocess.run(
        [str(script), successor_sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "system-to-user transition witness converged" in result.stdout
    assert not pending_path.exists()
    assert (home / ".config/systemd/user/hapax-scope-transition.service").read_text(
        encoding="utf-8"
    ) == user_body


def test_pending_systemd_queue_conflict_preserves_concurrent_addition_and_removal(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/hapax-pending-a.service"
    concurrent_path = "systemd/units/hapax-pending-b.service"
    unit_body = (
        "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
    )
    repo, _ = _repo_with_linear_commit(tmp_path, {unit_path: unit_body})
    (repo / "README.md").write_text("unrelated replay trigger\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "unrelated replay trigger")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    system_dir = tmp_path / "systemd-system"
    system_dir.mkdir()
    (system_dir / Path(unit_path).name).write_text(unit_body, encoding="utf-8")
    script = _post_merge_script_with_system_dir(tmp_path, system_dir)
    bin_dir, systemctl_calls = _fake_systemctl_with_system_witness(tmp_path, system_dir)
    real_systemctl = bin_dir / "systemctl-real"
    (bin_dir / "systemctl").rename(real_systemctl)
    manager_marker = tmp_path / "manager-witness-started"
    manager_release = tmp_path / "manager-witness-release"
    (bin_dir / "systemctl").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ "${1:-}" = show ] && [ ! -e "$HAPAX_MANAGER_WITNESS_MARKER" ]; then\n'
        '  : > "$HAPAX_MANAGER_WITNESS_MARKER"\n'
        '  while [ ! -e "$HAPAX_MANAGER_WITNESS_RELEASE" ]; do /usr/bin/sleep 0.01; done\n'
        "fi\n"
        f'exec {shlex.quote(str(real_systemctl))} "$@"\n',
        encoding="utf-8",
    )
    (bin_dir / "systemctl").chmod(0o755)
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"
    pending_path = trace_path.parent / "systemd-runtime-pending.json"
    pending_path.parent.mkdir(parents=True)
    pending_path.write_text(
        json.dumps({"schema_version": 1, "paths": [unit_path]}) + "\n",
        encoding="utf-8",
    )
    pending_path.chmod(0o600)
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        "HAPAX_MANAGER_WITNESS_MARKER": str(manager_marker),
        "HAPAX_MANAGER_WITNESS_RELEASE": str(manager_release),
    }

    process = subprocess.Popen(
        [str(script), sha],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        deadline = time.monotonic() + 10
        while (
            not manager_marker.exists() and process.poll() is None and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert manager_marker.exists(), "deploy did not reach the system-manager witness"
        pending_path.write_text(
            json.dumps(
                {"schema_version": 1, "paths": [unit_path, concurrent_path]},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        pending_path.chmod(0o600)
    finally:
        manager_release.touch()
        stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 0, (stdout, stderr)
    assert json.loads(pending_path.read_text(encoding="utf-8"))["paths"] == [
        unit_path,
        concurrent_path,
    ]


def test_deleted_system_scoped_unit_records_deferral_until_installed_copy_is_absent(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/hapax-system-demo.service"
    unit_body = (
        "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
    )
    repo, _ = _repo_with_linear_commit(tmp_path, {unit_path: unit_body})
    (repo / unit_path).unlink()
    _git(repo, "add", "-u")
    _git(repo, "commit", "-m", "delete system unit")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    system_dir = tmp_path / "systemd-system"
    system_dir.mkdir()
    installed = system_dir / Path(unit_path).name
    installed.write_text(unit_body, encoding="utf-8")
    script = _post_merge_script_with_system_dir(tmp_path, system_dir)
    bin_dir, systemctl_calls = _fake_systemctl_with_system_witness(tmp_path, system_dir)
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"
    cursor = tmp_path / "traces/last-deployed-sha"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
    }

    deferred = subprocess.run(
        [str(script), sha], text=True, capture_output=True, check=False, env=env
    )
    assert deferred.returncode == 0, deferred.stderr
    assert cursor.read_text(encoding="utf-8").strip() == sha
    deferred_record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert deferred_record["status"] == "completed_with_runtime_deferral"
    pending_path = trace_path.parent / "systemd-runtime-pending.json"
    assert json.loads(pending_path.read_text(encoding="utf-8"))["paths"] == [unit_path]

    (repo / "README.md").write_text("successor after deletion\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "unrelated successor after deletion")
    successor_sha = _git(repo, "rev-parse", "HEAD")

    installed.unlink()
    converged = subprocess.run(
        [str(script), successor_sha], text=True, capture_output=True, check=False, env=env
    )
    assert converged.returncode == 0, converged.stderr
    assert cursor.read_text(encoding="utf-8").strip() == successor_sha
    assert not pending_path.exists()
    replay_record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert replay_record["changed_files"] == ["README.md"]
    assert replay_record["systemd_runtime_replayed"] == [unit_path]


def test_malformed_system_scope_marker_is_refused(tmp_path: Path) -> None:
    unit_path = "systemd/units/hapax-user-demo.service"
    unit_body = (
        "[Unit]\n# Hapax-Install-Scope: system disabled\n"
        "[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
    )
    repo, sha = _repo_with_linear_commit(tmp_path, {unit_path: unit_body})
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        },
    )

    assert result.returncode != 0
    assert "malformed Hapax-Install-Scope marker" in result.stderr
    assert not (home / ".config/systemd/user/hapax-user-demo.service").exists()
    assert not (trace_path.parent / "last-deployed-sha").exists()


def test_system_manager_witness_rejects_file_generation_change(tmp_path: Path) -> None:
    unit_path = "systemd/units/hapax-system-demo.service"
    unit_body = (
        "[Unit]\n# Hapax-Install-Scope: system\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
    )
    repo, sha = _repo_with_linear_commit(tmp_path, {unit_path: unit_body})
    home = tmp_path / "home"
    system_dir = tmp_path / "systemd-system"
    system_dir.mkdir()
    installed = system_dir / Path(unit_path).name
    installed.write_text(unit_body, encoding="utf-8")
    script = _post_merge_script_with_system_dir(tmp_path, system_dir)
    bin_dir, systemctl_calls = _fake_systemctl_with_system_witness(tmp_path, system_dir)
    systemctl = bin_dir / "systemctl"
    original = systemctl.read_text(encoding="utf-8")
    mutation = f'printf "drifted\\n" > {shlex.quote(str(installed))}\n'
    systemctl.write_text(
        original.replace(
            'if [ "${1:-}" = show ]; then\n',
            f'if [ "${{1:-}}" = show ]; then\n{mutation}',
            1,
        ),
        encoding="utf-8",
    )
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"

    result = subprocess.run(
        [str(script), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "exact file and system-manager witness" not in result.stdout
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["status"] == "completed_with_runtime_deferral"
    assert record["runtime_deferred"] == [f"systemd-system:{unit_path}"]


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


def _deleted_user_unit_fixture(tmp_path: Path) -> tuple[Path, str, str]:
    unit_path = "systemd/units/hapax-deleted-demo.service"
    repo, _ = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\nDescription=Deleted demo\n"
                "[Service]\nExecStart=/usr/bin/sleep infinity\n"
                "[Install]\nWantedBy=default.target\n"
            )
        },
    )
    _git(repo, "rm", unit_path)
    _git(repo, "commit", "-m", "delete user service")
    return repo, _git(repo, "rev-parse", "HEAD"), unit_path


def _deleted_user_unit_systemctl(
    tmp_path: Path,
    unit_name: str,
    *,
    stop_rc: int = 0,
) -> tuple[Path, Path, Path]:
    bin_dir = tmp_path / "deleted-unit-bin"
    bin_dir.mkdir()
    calls = tmp_path / "deleted-unit-systemctl-calls.txt"
    state = tmp_path / "deleted-unit-state.txt"
    state.write_text("active enabled\n", encoding="utf-8")
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            printf '%s\n' "$*" >> "{calls}"
            read -r active enabled < "{state}"
            case "$*" in
              "--user stop {unit_name}")
                [ {stop_rc} -eq 0 ] || exit {stop_rc}
                active=inactive
                ;;
              "--user show {unit_name} -p ActiveState --value")
                printf '%s\n' "$active"
                exit 0
                ;;
              "--user disable {unit_name}") enabled=disabled ;;
              "--user show "*" -p LoadState --value") printf 'not-found\n'; exit 0 ;;
              "--user show "*" -p ActiveState --value") printf 'inactive\n'; exit 0 ;;
            esac
            printf '%s %s\n' "$active" "$enabled" > "{state}"
            exit 0
            """
        ),
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    return bin_dir, calls, state


def test_deleted_user_unit_is_stopped_and_disabled_before_fragment_removal(
    tmp_path: Path,
) -> None:
    repo, sha, unit_path = _deleted_user_unit_fixture(tmp_path)
    unit_name = Path(unit_path).name
    home = tmp_path / "home"
    installed = home / ".config/systemd/user" / unit_name
    installed.parent.mkdir(parents=True)
    installed.write_text("historical loaded unit\n", encoding="utf-8")
    dropin = installed.parent / f"{unit_name}.d/override.conf"
    dropin.parent.mkdir()
    dropin.write_text("[Service]\nRestart=always\n", encoding="utf-8")
    wants = installed.parent / f"default.target.wants/{unit_name}"
    wants.parent.mkdir()
    wants.symlink_to(installed)
    bin_dir, calls, state = _deleted_user_unit_systemctl(tmp_path, unit_name)
    cursor = tmp_path / "traces/last-deployed-sha"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/deploy.jsonl"),
            "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
            "HAPAX_DRIFT_NTFY": "0",
        },
    )

    assert result.returncode == 0, result.stderr
    assert not installed.exists()
    assert not dropin.parent.exists()
    assert not wants.exists() and not wants.is_symlink()
    assert state.read_text(encoding="utf-8").strip() == "inactive disabled"
    ordered_calls = calls.read_text(encoding="utf-8").splitlines()
    stop = f"--user stop {unit_name}"
    witness = f"--user show {unit_name} -p ActiveState --value"
    disable = f"--user disable {unit_name}"
    stop_index = ordered_calls.index(stop)
    assert stop_index < ordered_calls.index(witness, stop_index + 1)
    assert ordered_calls.index(witness, stop_index + 1) < ordered_calls.index(disable)
    assert cursor.read_text(encoding="utf-8").strip() == sha


def test_deleted_user_unit_stop_failure_preserves_fragment_and_cursor(
    tmp_path: Path,
) -> None:
    repo, sha, unit_path = _deleted_user_unit_fixture(tmp_path)
    unit_name = Path(unit_path).name
    home = tmp_path / "home"
    installed = home / ".config/systemd/user" / unit_name
    installed.parent.mkdir(parents=True)
    installed.write_text("historical loaded unit\n", encoding="utf-8")
    dropin = installed.parent / f"{unit_name}.d/override.conf"
    dropin.parent.mkdir()
    dropin.write_text("[Service]\nRestart=always\n", encoding="utf-8")
    wants = installed.parent / f"default.target.wants/{unit_name}"
    wants.parent.mkdir()
    wants.symlink_to(installed)
    bin_dir, _, state = _deleted_user_unit_systemctl(tmp_path, unit_name, stop_rc=73)
    cursor = tmp_path / "traces/last-deployed-sha"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/deploy.jsonl"),
            "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
            "HAPAX_DRIFT_NTFY": "0",
        },
    )

    assert result.returncode != 0
    assert "unable to stop deleted user unit" in result.stderr
    assert installed.read_text(encoding="utf-8") == "historical loaded unit\n"
    assert dropin.is_file()
    assert wants.is_symlink()
    assert state.read_text(encoding="utf-8").strip() == "active enabled"
    assert not cursor.exists()


def test_systemd_scope_classification_git_failure_preserves_existing_unit(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/hapax-system-demo.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "# Hapax-Install-Scope: system\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=/usr/bin/true\n"
            )
        },
    )
    home = tmp_path / "home"
    installed = home / ".config/systemd/user/hapax-system-demo.service"
    installed.parent.mkdir(parents=True)
    installed.write_text("prior user unit\n", encoding="utf-8")
    systemctl_bin, systemctl_calls = _fake_systemctl(tmp_path)
    git_bin = _fake_git_with_show_failure(tmp_path)
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"
    cursor = tmp_path / "traces/last-deployed-sha"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{git_bin}:{systemctl_bin}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
            "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
            "HAPAX_FAIL_GIT_SHOW_OBJECT": f"{sha}:{unit_path}",
            "HAPAX_FAIL_GIT_SHOW_COUNT_FILE": str(tmp_path / "git-show.count"),
            "HAPAX_FAIL_GIT_SHOW_ON_COUNT": "1",
        },
    )

    assert result.returncode != 0
    assert "failed to read systemd unit while classifying install scope" in result.stderr
    assert installed.read_text(encoding="utf-8") == "prior user unit\n"
    assert not cursor.exists()


def test_systemd_scope_reconciliation_git_failure_precedes_user_mutation(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/hapax-system-demo.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "# Hapax-Install-Scope: system\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=/usr/bin/true\n"
            )
        },
    )
    home = tmp_path / "home"
    installed = home / ".config/systemd/user/hapax-system-demo.service"
    installed.parent.mkdir(parents=True)
    installed.write_text("prior user unit\n", encoding="utf-8")
    systemctl_bin, systemctl_calls = _fake_systemctl(tmp_path)
    git_bin = _fake_git_with_ls_tree_failure(tmp_path)
    script = _post_merge_script_with_system_dir(tmp_path, tmp_path / "systemd-system")
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"
    cursor = tmp_path / "traces/last-deployed-sha"

    result = subprocess.run(
        [str(script), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{git_bin}:{systemctl_bin}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
            "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
            "HAPAX_FAIL_GIT_LS_TREE_PATH": unit_path,
            "HAPAX_FAIL_GIT_LS_TREE_COUNT_FILE": str(tmp_path / "git-ls-tree.count"),
            # Classification runs only after the lock re-exec; the second read
            # is the authoritative reconciliation snapshot.
            "HAPAX_FAIL_GIT_LS_TREE_ON_COUNT": "2",
        },
    )

    assert result.returncode != 0
    assert "failed to inspect system-scoped systemd unit Git entry" in result.stderr
    assert installed.read_text(encoding="utf-8") == "prior user unit\n"
    assert not systemctl_calls.exists()
    assert not cursor.exists()


def test_systemd_unit_git_show_failure_preserves_existing_bytes(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/hapax-user-demo.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "Description=Replacement user unit\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=/usr/bin/true\n"
            )
        },
    )
    home = tmp_path / "home"
    installed = home / ".config/systemd/user/hapax-user-demo.service"
    installed.parent.mkdir(parents=True)
    installed.write_text("prior user unit\n", encoding="utf-8")
    systemctl_bin, systemctl_calls = _fake_systemctl(tmp_path)
    git_bin = _fake_git_with_show_failure(tmp_path)
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"
    cursor = tmp_path / "traces/last-deployed-sha"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{git_bin}:{systemctl_bin}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
            "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
            "HAPAX_FAIL_GIT_SHOW_OBJECT": f"{sha}:{unit_path}",
            "HAPAX_FAIL_GIT_SHOW_COUNT_FILE": str(tmp_path / "git-show.count"),
            # Classification runs only after the lock re-exec; deployment is
            # the second read.
            "HAPAX_FAIL_GIT_SHOW_ON_COUNT": "2",
        },
    )

    assert result.returncode != 0
    assert "failed to materialize systemd unit" in result.stderr
    assert installed.read_text(encoding="utf-8") == "prior user unit\n"
    assert not list(installed.parent.glob(".hapax-user-demo.service.tmp.*"))
    assert not cursor.exists()


def test_runtime_config_git_inspection_failure_is_not_treated_as_deletion(
    tmp_path: Path,
) -> None:
    config_path = "config/hapax/review-live.conf"
    repo, sha = _repo_with_linear_commit(tmp_path, {config_path: "replacement=true\n"})
    home = tmp_path / "home"
    installed = home / ".config/hapax/review-live.conf"
    installed.parent.mkdir(parents=True)
    installed.write_text("previous=true\n", encoding="utf-8")
    git_bin = _fake_git_with_ls_tree_failure(tmp_path)
    cursor = tmp_path / "traces/last-deployed-sha"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{git_bin}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/deploy.jsonl"),
            "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
            "HAPAX_FAIL_GIT_LS_TREE_PATH": config_path,
            "HAPAX_FAIL_GIT_LS_TREE_COUNT_FILE": str(tmp_path / "git-ls-tree.count"),
            "HAPAX_FAIL_GIT_LS_TREE_ON_COUNT": "1",
            "HAPAX_DRIFT_NTFY": "0",
        },
    )

    assert result.returncode != 0
    assert "refusing to infer deletion" in result.stderr
    assert installed.read_text(encoding="utf-8") == "previous=true\n"
    assert not cursor.exists()


def test_runtime_config_git_show_failure_does_not_truncate_live_bytes(
    tmp_path: Path,
) -> None:
    config_path = "config/hapax/review-live.conf"
    repo, sha = _repo_with_linear_commit(tmp_path, {config_path: "replacement=true\n"})
    home = tmp_path / "home"
    installed = home / ".config/hapax/review-live.conf"
    installed.parent.mkdir(parents=True)
    installed.write_text("previous=true\n", encoding="utf-8")
    git_bin = _fake_git_with_show_failure(tmp_path)
    cursor = tmp_path / "traces/last-deployed-sha"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{git_bin}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/deploy.jsonl"),
            "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
            "HAPAX_FAIL_GIT_SHOW_OBJECT": f"{sha}:{config_path}",
            "HAPAX_FAIL_GIT_SHOW_COUNT_FILE": str(tmp_path / "git-show.count"),
            "HAPAX_FAIL_GIT_SHOW_ON_COUNT": "1",
            "HAPAX_DRIFT_NTFY": "0",
        },
    )

    assert result.returncode != 0
    assert "failed to materialize Hapax runtime configuration" in result.stderr
    assert installed.read_text(encoding="utf-8") == "previous=true\n"
    assert not list(installed.parent.glob(".review-live.conf.tmp.*"))
    assert not cursor.exists()


def test_watchdog_chmod_failure_preserves_live_executable_and_cursor(tmp_path: Path) -> None:
    watchdog_path = "systemd/watchdogs/health-watchdog"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {watchdog_path: "#!/usr/bin/env bash\necho replacement\n"},
    )
    home = tmp_path / "home"
    installed = home / ".local/bin/health-watchdog"
    installed.parent.mkdir(parents=True)
    installed.write_text("#!/usr/bin/env bash\necho previous\n", encoding="utf-8")
    installed.chmod(0o755)
    bin_dir = tmp_path / "chmod-bin"
    bin_dir.mkdir()
    chmod = bin_dir / "chmod"
    chmod.write_text(
        "#!/usr/bin/env bash\n"
        'last="${!#}"\n'
        'case "$last" in\n'
        '  "$HOME"/.local/bin/.health-watchdog.tmp.*) exit 78 ;;\n'
        "esac\n"
        'exec /usr/bin/chmod "$@"\n',
        encoding="utf-8",
    )
    chmod.chmod(0o755)
    cursor = tmp_path / "traces/last-deployed-sha"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/deploy.jsonl"),
            "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
            "HAPAX_DRIFT_NTFY": "0",
        },
    )

    assert result.returncode != 0
    assert "failed to atomically publish systemd watchdog script" in result.stderr
    assert installed.read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho previous\n"
    assert installed.stat().st_mode & 0o777 == 0o755
    assert not list(installed.parent.glob(".health-watchdog.tmp.*"))
    assert not cursor.exists()


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


def test_preset_only_unit_git_show_failure_preserves_existing_bytes(
    tmp_path: Path,
) -> None:
    repo, sha = _repo_with_intake_units_then_preset_commit(tmp_path)
    unit = "hapax-request-decompose.timer"
    unit_path = f"systemd/units/{unit}"
    home = tmp_path / "home"
    installed = home / ".config/systemd/user" / unit
    installed.parent.mkdir(parents=True)
    installed.write_text("prior governed intake unit\n", encoding="utf-8")
    systemctl_bin, systemctl_calls = _fake_systemctl(tmp_path)
    git_bin = _fake_git_with_show_failure(tmp_path)
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"
    cursor = tmp_path / "traces/last-deployed-sha"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{git_bin}:{systemctl_bin}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
            "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
            "HAPAX_FAIL_GIT_SHOW_OBJECT": f"{sha}:{unit_path}",
            "HAPAX_FAIL_GIT_SHOW_COUNT_FILE": str(tmp_path / "git-show.count"),
            "HAPAX_FAIL_GIT_SHOW_ON_COUNT": "1",
        },
    )

    assert result.returncode != 0
    assert "failed to materialize systemd unit" in result.stderr
    assert installed.read_text(encoding="utf-8") == "prior governed intake unit\n"
    assert not list(installed.parent.glob(f".{unit}.tmp.*"))
    assert not cursor.exists()


def test_user_preset_git_show_failure_preserves_existing_bytes(tmp_path: Path) -> None:
    repo, sha = _repo_with_intake_units_then_preset_commit(tmp_path)
    preset_path = "systemd/user-preset.d/hapax.preset"
    home = tmp_path / "home"
    installed = home / ".config/systemd/user-preset/hapax.preset"
    installed.parent.mkdir(parents=True)
    installed.write_text("prior preset bytes\n", encoding="utf-8")
    systemctl_bin, systemctl_calls = _fake_systemctl(tmp_path)
    git_bin = _fake_git_with_show_failure(tmp_path)
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"
    cursor = tmp_path / "traces/last-deployed-sha"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{git_bin}:{systemctl_bin}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
            "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
            "HAPAX_FAIL_GIT_SHOW_OBJECT": f"{sha}:{preset_path}",
            "HAPAX_FAIL_GIT_SHOW_COUNT_FILE": str(tmp_path / "git-show.count"),
            "HAPAX_FAIL_GIT_SHOW_ON_COUNT": "1",
        },
    )

    assert result.returncode != 0
    assert installed.read_text(encoding="utf-8") == "prior preset bytes\n"
    assert not list(installed.parent.glob(".hapax.preset.tmp.*"))
    assert not cursor.exists()


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


def test_hapax_script_deploy_atomically_replaces_hard_link_without_mutating_peer(
    tmp_path: Path,
) -> None:
    script_path = "scripts/hapax-atomic-launcher"
    release_body = "#!/usr/bin/env bash\necho release\n"
    repo, sha = _repo_with_linear_commit(tmp_path, {script_path: release_body})
    home = tmp_path / "home"
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    peer = tmp_path / "launcher-peer"
    peer.write_text("#!/usr/bin/env bash\necho prior peer\n", encoding="utf-8")
    peer.chmod(0o755)
    installed = local_bin / "hapax-atomic-launcher"
    os.link(peer, installed)
    prior_peer_inode = peer.stat().st_ino
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        },
    )

    assert result.returncode == 0, result.stderr
    assert installed.read_text(encoding="utf-8") == release_body
    assert installed.stat().st_mode & 0o777 == 0o755
    assert installed.stat().st_nlink == 1
    assert installed.stat().st_ino != prior_peer_inode
    assert peer.stat().st_ino == prior_peer_inode
    assert peer.stat().st_nlink == 1
    assert peer.read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho prior peer\n"


def test_hapax_script_git_inspection_failure_never_infers_deletion(tmp_path: Path) -> None:
    script_path = "scripts/hapax-read-failure"
    repo, _ = _repo_with_linear_commit(tmp_path, {script_path: "#!/usr/bin/env bash\necho old\n"})
    _git(repo, "rm", script_path)
    _git(repo, "commit", "-m", "delete launcher")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    installed = home / ".local/bin/hapax-read-failure"
    installed.parent.mkdir(parents=True)
    installed.write_text("#!/usr/bin/env bash\necho installed\n", encoding="utf-8")
    installed.chmod(0o755)
    git_bin = _fake_git_with_ls_tree_failure(tmp_path)
    count_file = tmp_path / "failed-ls-tree-count"
    trace_path = tmp_path / "traces/trace.jsonl"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{git_bin}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
            "HAPAX_FAIL_GIT_LS_TREE_PATH": script_path,
            "HAPAX_FAIL_GIT_LS_TREE_COUNT_FILE": str(count_file),
            "HAPAX_FAIL_GIT_LS_TREE_ON_COUNT": "1",
        },
    )

    assert result.returncode == 2
    assert "refusing to infer deletion" in result.stderr
    assert installed.read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho installed\n"
    assert not (trace_path.parent / "last-deployed-sha").exists()


def test_hapax_script_removal_failure_blocks_completion_receipt(tmp_path: Path) -> None:
    script_path = "scripts/hapax-remove-failure"
    repo, _ = _repo_with_linear_commit(tmp_path, {script_path: "#!/usr/bin/env bash\necho old\n"})
    _git(repo, "rm", script_path)
    _git(repo, "commit", "-m", "delete launcher")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    installed = home / ".local/bin/hapax-remove-failure"
    installed.mkdir(parents=True)
    (installed / "preserve").write_text("sentinel\n", encoding="utf-8")
    trace_path = tmp_path / "traces/trace.jsonl"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "REPO": str(repo),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        },
    )

    assert result.returncode != 0
    assert "failed to remove deleted launcher" in result.stderr
    assert (installed / "preserve").read_text(encoding="utf-8") == "sentinel\n"
    assert not (trace_path.parent / "last-deployed-sha").exists()


def test_deploy_rejects_commit_ranges_before_touching_targets(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(SCRIPT), "HEAD..HEAD"],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HOME": str(tmp_path / "home"), "REPO": str(REPO_ROOT)},
    )

    assert result.returncode == 2
    assert "expected a single commit SHA/ref" in result.stderr


def test_shallow_target_with_missing_named_parent_fails_before_mutation(
    tmp_path: Path,
) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-b", "main")
    _git(origin, "config", "user.email", "shallow-test@example.test")
    _git(origin, "config", "user.name", "Shallow Test")
    (origin / "README.md").write_text("base\n", encoding="utf-8")
    _git(origin, "add", "README.md")
    _git(origin, "commit", "-m", "base")
    launcher = origin / "scripts/hapax-shallow-mutation"
    launcher.parent.mkdir()
    launcher.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    _git(origin, "add", "scripts/hapax-shallow-mutation")
    _git(origin, "commit", "-m", "target")

    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{origin}", str(shallow)],
        check=True,
    )
    sha = _git(shallow, "rev-parse", "HEAD")
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces/trace.jsonl"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(shallow),
            "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        },
    )

    assert result.returncode == 2
    assert "unavailable first parent" in result.stderr
    assert not (home / ".local/bin/hapax-shallow-mutation").exists()
    assert not (trace_path.parent / "last-deployed-sha").exists()
    assert not systemctl_calls.exists()


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
    the exact target's smoke runner is invoked from the release-copy path. The
    target does not change that runner, so this also proves publication is not
    accidentally conditional on its presence in the current diff."""
    repo, sha = _repo_with_merge_commit(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    smoke_recorder = tmp_path / "smoke-call-record.txt"

    smoke_stub = repo / "scripts" / "hapax-post-merge-smoke"
    smoke_stub.write_text(
        f'#!/bin/sh\nprintf "smoke-invoked args=%s root=%s\\n" "$*" "$REPO_ROOT" '
        f'> "{smoke_recorder}"\nexit 0\n',
        encoding="utf-8",
    )
    smoke_stub.chmod(0o755)
    _git(repo, "add", "scripts/hapax-post-merge-smoke")
    _git(repo, "commit", "-m", "add exact smoke runner")
    target_file = repo / "docs" / "target.md"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("target leaves smoke unchanged\n", encoding="utf-8")
    _git(repo, "add", "docs/target.md")
    _git(repo, "commit", "-m", "target without smoke change")
    sha = _git(repo, "rev-parse", "HEAD")
    tampered_marker = tmp_path / "tampered-smoke-called"
    smoke_stub.write_text(
        f"#!/bin/sh\nprintf tampered > {tampered_marker}\nexit 0\n", encoding="utf-8"
    )

    # HOME isolated so the real deploy's scripts/hapax-demo symlink lands under
    # tmp, not the operator's ~/.local/bin (fix-deploy-symlink-skew leak).
    home = tmp_path / "home"
    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "REPO_ROOT": str(tmp_path / "ambient-foreign-root"),
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
    assert smoke_recorder.read_text(encoding="utf-8").strip() == (
        f"smoke-invoked args={sha} root={repo}"
    )
    assert not tampered_marker.exists(), "deploy invoked mutable worktree smoke bytes"


def test_real_deploy_smoke_execution_failure_blocks_completion_receipt(tmp_path: Path) -> None:
    """A non-zero runner is an execution failure, not an advisory gate result."""
    repo, sha = _repo_with_merge_commit(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"

    smoke_stub = repo / "scripts" / "hapax-post-merge-smoke"
    smoke_stub.write_text("#!/bin/sh\necho smoke-broken >&2\nexit 1\n", encoding="utf-8")
    smoke_stub.chmod(0o755)
    _git(repo, "add", "scripts/hapax-post-merge-smoke")
    _git(repo, "commit", "-m", "add failing smoke runner")
    sha = _git(repo, "rev-parse", "HEAD")

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

    assert result.returncode == 1
    assert "exact-target smoke runner failed" in result.stderr
    assert "next action:" in result.stderr
    assert trace_path.exists(), "post-merge trace was not written"
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["status"] == "failed"
    assert records[-1]["exit_code"] == 1
    assert not (trace_path.parent / "last-deployed-sha").exists()


def test_real_deploy_blocks_receipt_when_exact_smoke_cannot_read_diff(
    tmp_path: Path,
) -> None:
    repo, _ = _repo_with_merge_commit(tmp_path)
    smoke_stub = repo / "scripts/hapax-post-merge-smoke"
    smoke_stub.write_text(SMOKE.read_text(encoding="utf-8"), encoding="utf-8")
    smoke_stub.chmod(0o755)
    target = repo / "docs/smoke-discovery-target.md"
    target.parent.mkdir(parents=True)
    target.write_text("target\n", encoding="utf-8")
    _git(repo, "add", "scripts/hapax-post-merge-smoke", "docs/smoke-discovery-target.md")
    _git(repo, "commit", "-m", "add governed smoke target")
    sha = _git(repo, "rev-parse", "HEAD")
    git_bin = tmp_path / "git-bin"
    git_bin.mkdir()
    diff_count = tmp_path / "git-diff-count"
    fake_git = git_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ "${1:-}" = diff ]; then\n'
        "  count=0\n"
        '  [ ! -f "$HAPAX_GIT_DIFF_COUNT" ] || read -r count < "$HAPAX_GIT_DIFF_COUNT"\n'
        "  count=$((count + 1))\n"
        '  printf \'%s\\n\' "$count" > "$HAPAX_GIT_DIFF_COUNT"\n'
        '  if [ "$count" -eq 2 ]; then exit 91; fi\n'
        "fi\n"
        'exec /usr/bin/git "$@"\n',
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    home = tmp_path / "home"
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{git_bin}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_GIT_DIFF_COUNT": str(diff_count),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        },
    )

    assert result.returncode == 2
    assert "cannot enumerate changed files" in result.stderr
    assert "exact-target smoke runner failed" in result.stderr
    assert not (trace_path.parent / "last-deployed-sha").exists()


def test_real_deploy_with_governed_chain_but_no_smoke_script_fails_visible(
    tmp_path: Path,
) -> None:
    repo, sha = _repo_with_merge_commit(tmp_path)
    deploy_source = repo / "scripts" / "hapax-post-merge-deploy"
    deploy_source.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    deploy_source.chmod(0o755)
    _git(repo, "add", "scripts/hapax-post-merge-deploy")
    _git(repo, "commit", "-m", "adopt governed deploy chain without smoke")
    sha = _git(repo, "rev-parse", "HEAD")
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

    assert result.returncode == 1
    assert "exact-target smoke runner is missing" in result.stderr
    assert sha in result.stderr
    assert "next action:" in result.stderr
    assert trace_path.exists()
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["status"] == "failed"
    assert not (trace_path.parent / "last-deployed-sha").exists()


def test_real_deploy_smoke_runner_has_a_forced_whole_process_deadline(
    tmp_path: Path,
) -> None:
    repo, _ = _repo_with_merge_commit(tmp_path)
    smoke_stub = repo / "scripts" / "hapax-post-merge-smoke"
    smoke_stub.write_text(
        "#!/usr/bin/env bash\ntrap '' TERM\nwhile :; do :; done\n", encoding="utf-8"
    )
    smoke_stub.chmod(0o755)
    _git(repo, "add", "scripts/hapax-post-merge-smoke")
    _git(repo, "commit", "-m", "add wedged smoke runner")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    started = time.monotonic()

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "REPO": str(repo),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
            "HAPAX_POST_MERGE_SMOKE_TIMEOUT_S": "1",
        },
    )

    assert result.returncode == 137
    assert time.monotonic() - started < 3
    assert "exact-target smoke runner failed" in result.stderr
    assert "rc=137" in result.stderr
    assert not (trace_path.parent / "last-deployed-sha").exists()


def test_real_deploy_smoke_cgroup_reaps_detached_descendants(tmp_path: Path) -> None:
    repo, _ = _repo_with_merge_commit(tmp_path)
    pid_file = tmp_path / "detached-smoke-child.pid"
    smoke_stub = repo / "scripts/hapax-post-merge-smoke"
    smoke_stub.write_text(
        "#!/usr/bin/env bash\n"
        "/usr/bin/setsid /usr/bin/sleep 30 &\n"
        'printf \'%s\\n\' "$!" > "$HAPAX_TEST_SMOKE_DESCENDANT_PID_FILE"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    smoke_stub.chmod(0o755)
    _git(repo, "add", "scripts/hapax-post-merge-smoke")
    _git(repo, "commit", "-m", "add detached smoke child")
    sha = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / "home"
    trace_path = tmp_path / "traces/post-merge-traces.jsonl"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "REPO": str(repo),
            "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
            "HAPAX_TEST_SMOKE_DESCENDANT_PID_FILE": str(pid_file),
        },
    )

    assert result.returncode == 0, result.stderr
    pid = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while Path(f"/proc/{pid}").exists() and time.monotonic() < deadline:
        status = Path(f"/proc/{pid}/status")
        if status.exists() and "State:\tZ" in status.read_text(encoding="utf-8"):
            break
        time.sleep(0.02)
    assert not Path(f"/proc/{pid}").exists() or "State:\tZ" in Path(
        f"/proc/{pid}/status"
    ).read_text(encoding="utf-8")


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


def test_pw_deploy_parse_lints_confs() -> None:
    script = SCRIPT.read_text()
    assert "spa-json-dump" in script, "conf parse-lint missing from PW deploy path"
    assert (
        'publish_exact_file_or_delete "$f" "$dest" 0644 "PipeWire configuration" spa-json' in script
    )


def test_pw_parse_failure_preserves_live_config_and_cursor(tmp_path: Path) -> None:
    relative = "config/pipewire/99-invalid.conf"
    repo, sha = _repo_with_linear_commit(tmp_path, {relative: "not valid SPA JSON\n"})
    home = tmp_path / "home"
    live = home / ".config/pipewire/pipewire.conf.d/99-invalid.conf"
    live.parent.mkdir(parents=True)
    live.write_text("previous live configuration\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    validator = bin_dir / "spa-json-dump"
    validator.write_text("#!/usr/bin/env bash\nexit 23\n", encoding="utf-8")
    validator.chmod(0o755)
    cursor = tmp_path / "traces/last-deployed-sha"

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REPO": str(repo),
            "HAPAX_DRIFT_NTFY": "0",
            "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(cursor),
            "HAPAX_POST_MERGE_TRACE_PATH": str(tmp_path / "traces/deploy.jsonl"),
        },
    )

    assert result.returncode != 0
    assert "REFUSED invalid PipeWire SPA JSON" in result.stderr
    assert live.read_text(encoding="utf-8") == "previous live configuration\n"
    assert not cursor.exists()
    assert not list(live.parent.glob(".99-invalid.conf.tmp.*"))


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
for sibling in agent-role.sh escape-grant.sh cc-task-root.sh hapax_check_enable_latch.sh cc-task-gate-bootstrap.py hooks-doctor.sh; do
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
        "hooks/scripts/cc-task-root.sh": "#!/usr/bin/env bash\necho cc-task-root\n",
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
            "cc-task-root.sh",
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
        "cc-task-root.sh",
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
    receipt = tmp_path / "traces" / "last-deployed-sha"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(f"{_git(repo, 'rev-parse', f'{sha}^')}\n", encoding="utf-8")
    # Historical receipts were published 0644; admission accepts that
    # non-writable-by-other mode and the transaction migrates it to 0600.
    receipt.chmod(0o644)

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
    assert receipt.read_text(encoding="utf-8").strip() == sha
    assert receipt.stat().st_mode & 0o777 == 0o600
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


def _repo_with_cursor_backlog(tmp_path: Path) -> tuple[Path, str, str, str]:
    repo, cursor_sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    script_path = repo / "scripts" / "hapax-backlog-demo"
    script_path.parent.mkdir(exist_ok=True)
    script_path.write_text("#!/usr/bin/env bash\necho backlog\n", encoding="utf-8")
    script_path.chmod(0o755)
    _git(repo, "add", "scripts/hapax-backlog-demo")
    _git(repo, "commit", "-m", "add intermediate deployable script")
    intermediate = _git(repo, "rev-parse", "HEAD")
    (repo / "docs" / "later.md").parent.mkdir(exist_ok=True)
    (repo / "docs" / "later.md").write_text("later target\n", encoding="utf-8")
    _git(repo, "add", "docs/later.md")
    _git(repo, "commit", "-m", "add later nondeployable change")
    return repo, cursor_sha, intermediate, _git(repo, "rev-parse", "HEAD")


def test_cursor_baseline_drives_cumulative_diff_without_explicit_since(tmp_path: Path) -> None:
    repo, cursor_sha, _, target = _repo_with_cursor_backlog(tmp_path)
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=False)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)
    cursor = tmp_path / "traces" / "last-deployed-sha"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(f"{cursor_sha}\n", encoding="utf-8")
    cursor.chmod(0o600)

    result = subprocess.run(
        [str(SCRIPT), target],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    deployed = Path(env["HOME"]) / ".local/bin/hapax-backlog-demo"
    assert deployed.is_file()
    assert deployed.read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho backlog\n"
    assert cursor.read_text(encoding="utf-8").strip() == target
    marker = _deploy_cursor_marker(Path(env["HOME"]))
    assert marker.read_text(encoding="utf-8") == "hapax-deploy-cursor-established-v1\n"
    assert marker.stat().st_mode & 0o777 == 0o600


def test_missing_established_cursor_refuses_to_skip_cumulative_backlog(tmp_path: Path) -> None:
    repo, _, _, target = _repo_with_cursor_backlog(tmp_path)
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=False)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)
    cursor = tmp_path / "traces/last-deployed-sha"
    marker = _deploy_cursor_marker(Path(env["HOME"]))
    marker.parent.mkdir(parents=True)
    marker.write_text("hapax-deploy-cursor-established-v1\n", encoding="utf-8")
    marker.chmod(0o600)

    result = subprocess.run(
        [str(SCRIPT), target],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode != 0
    assert "established deploy cursor is missing" in result.stderr
    assert not (Path(env["HOME"]) / ".local/bin/hapax-backlog-demo").exists()
    assert not cursor.exists()
    assert not cursor.parent.exists()
    assert marker.read_text(encoding="utf-8") == "hapax-deploy-cursor-established-v1\n"


def test_explicit_since_cannot_skip_past_trusted_cursor(tmp_path: Path) -> None:
    repo, cursor_sha, intermediate, target = _repo_with_cursor_backlog(tmp_path)
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=False)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)
    cursor = tmp_path / "traces" / "last-deployed-sha"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(f"{cursor_sha}\n", encoding="utf-8")
    cursor.chmod(0o600)

    result = subprocess.run(
        [str(SCRIPT), "--since", intermediate, target],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode != 0
    assert "does not match trusted deploy cursor" in result.stderr
    assert not (Path(env["HOME"]) / ".local/bin/hapax-backlog-demo").exists()
    assert cursor.read_text(encoding="utf-8").strip() == cursor_sha


def test_explicit_since_without_cursor_must_be_target_ancestor(tmp_path: Path) -> None:
    repo, _, intermediate, later = _repo_with_cursor_backlog(tmp_path)
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=False)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)

    result = subprocess.run(
        [str(SCRIPT), "--since", later, intermediate],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode != 0
    assert "is not an ancestor of deploy target" in result.stderr
    assert not (Path(env["HOME"]) / ".local/bin/hapax-backlog-demo").exists()
    assert not (tmp_path / "traces" / "last-deployed-sha").exists()


def test_last_deployed_sha_failure_preserves_previous_cursor_and_records_failure(
    tmp_path: Path,
) -> None:
    if os.geteuid() == 0:
        pytest.skip("directory permission failure requires an unprivileged test user")
    repo, sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=True)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)
    cursor_parent = tmp_path / "readonly-cursor"
    cursor_parent.mkdir()
    cursor = cursor_parent / "last-deployed-sha"
    previous = _git(repo, "rev-parse", f"{sha}^")
    cursor.write_text(f"{previous}\n", encoding="utf-8")
    cursor.chmod(0o600)
    marker = _deploy_cursor_marker(Path(env["HOME"]))
    marker.parent.mkdir(parents=True)
    marker.write_text("hapax-deploy-cursor-established-v1\n", encoding="utf-8")
    marker.chmod(0o600)
    cursor_parent.chmod(0o555)
    env["HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH"] = str(cursor)

    try:
        result = subprocess.run(
            [str(SCRIPT), sha],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
    finally:
        cursor_parent.chmod(0o755)

    assert result.returncode != 0, (result.stdout, result.stderr)
    assert "failed to publish last-deployed SHA" in result.stderr
    assert cursor.read_text(encoding="utf-8").strip() == previous
    assert not list(cursor_parent.glob(".last-deployed-sha.tmp.*"))
    records = [
        json.loads(line)
        for line in Path(env["HAPAX_POST_MERGE_TRACE_PATH"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert records[-1]["status"] == "failed"
    assert records[-1]["exit_code"] == result.returncode


@pytest.mark.parametrize("with_previous_cursor", (True, False))
def test_post_replace_cursor_fsync_failure_rolls_back_visible_cursor(
    tmp_path: Path,
    with_previous_cursor: bool,
) -> None:
    repo, sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=False)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)
    cursor_parent = tmp_path / "cursor-domain"
    cursor_parent.mkdir()
    cursor = cursor_parent / "last-deployed-sha"
    previous = _git(repo, "rev-parse", f"{sha}^")
    marker = _deploy_cursor_marker(Path(env["HOME"]))
    if with_previous_cursor:
        marker.parent.mkdir(parents=True)
        cursor.write_text(f"{previous}\n", encoding="utf-8")
        cursor.chmod(0o600)
        marker.write_text("hapax-deploy-cursor-established-v1\n", encoding="utf-8")
        marker.chmod(0o600)
    env["HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH"] = str(cursor)
    env["HAPAX_TEST_CURSOR_FSYNC_PARENT"] = str(cursor_parent.absolute())
    script = _post_merge_script_with_cursor_fsync_failure(tmp_path)

    result = subprocess.run(
        [str(script), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode != 0
    assert "cursor directory sync failed and the prior cursor state was restored" in result.stderr
    if with_previous_cursor:
        assert cursor.read_text(encoding="utf-8").strip() == previous
        assert marker.read_text(encoding="utf-8") == "hapax-deploy-cursor-established-v1\n"
    else:
        assert not cursor.exists()
        assert not marker.exists()
    assert not list(cursor_parent.glob(".last-deployed-sha.tmp.*"))
    assert not list(cursor_parent.glob(".last-deployed-sha.restore.tmp.*"))


def test_first_publication_marker_fsync_failure_leaves_no_false_establishment(
    tmp_path: Path,
) -> None:
    repo, sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=False)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)
    cursor = tmp_path / "cursor-domain/last-deployed-sha"
    cursor.parent.mkdir()
    marker = _deploy_cursor_marker(Path(env["HOME"]))
    env["HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH"] = str(cursor)
    env["HAPAX_TEST_CURSOR_FSYNC_PARENT"] = str(marker.parent.absolute())
    script = _post_merge_script_with_cursor_fsync_failure(tmp_path)

    result = subprocess.run(
        [str(script), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode != 0
    assert "failed to publish deploy cursor establishment marker" in result.stderr
    assert not cursor.exists()
    assert not marker.exists()


def test_older_process_cannot_regress_cursor_after_newer_deploy_completes(
    tmp_path: Path,
) -> None:
    repo, older_sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    (repo / "README.md").write_text("newer deploy\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "newer deploy target")
    newer_sha = _git(repo, "rev-parse", "HEAD")
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=False)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)

    pause_marker = tmp_path / "older-resolve-paused"
    release = tmp_path / "release-older-resolve"
    count_file = tmp_path / "older-resolve-count"
    fake_bin = tmp_path / "git-bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'if [[ "$*" == *"rev-parse --verify --quiet {older_sha}^{{commit}}"* ]]; then\n'
        "  count=0\n"
        f"  [ ! -f {shlex.quote(str(count_file))} ] || read -r count < {shlex.quote(str(count_file))}\n"
        "  count=$((count + 1))\n"
        f"  printf '%s\\n' \"$count\" > {shlex.quote(str(count_file))}\n"
        '  if [ "$count" -eq 1 ]; then\n'
        f"    : > {shlex.quote(str(pause_marker))}\n"
        f"    while [ ! -e {shlex.quote(str(release))} ]; do /usr/bin/sleep 0.01; done\n"
        "  fi\n"
        "fi\n"
        'exec /usr/bin/git "$@"\n',
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    older = subprocess.Popen(
        [str(SCRIPT), older_sha],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        deadline = time.monotonic() + 10
        while not pause_marker.exists() and older.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pause_marker.exists(), "older deploy did not reach the deterministic pre-lock pause"
        newer = subprocess.run(
            [str(SCRIPT), newer_sha],
            text=True,
            capture_output=True,
            check=False,
            env=env,
            timeout=20,
        )
        assert newer.returncode == 0, newer.stderr
        cursor = tmp_path / "traces/last-deployed-sha"
        assert cursor.read_text(encoding="utf-8").strip() == newer_sha
    finally:
        release.touch()
        older_stdout, older_stderr = older.communicate(timeout=20)

    assert older.returncode != 0, older_stdout
    assert "refusing stale deploy target" in older_stderr
    assert cursor.read_text(encoding="utf-8").strip() == newer_sha


def test_deploy_cursor_rejects_ancestry_divergence_before_mutation(tmp_path: Path) -> None:
    repo, candidate = _repo_with_gate_closure_and_docs_commit(tmp_path)
    parent = _git(repo, "rev-parse", f"{candidate}^")
    _git(repo, "switch", "-c", "divergent-cursor", parent)
    (repo / "divergent.txt").write_text("divergent\n", encoding="utf-8")
    _git(repo, "add", "divergent.txt")
    _git(repo, "commit", "-m", "divergent cursor")
    divergent = _git(repo, "rev-parse", "HEAD")
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=True)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)
    cursor = tmp_path / "traces/last-deployed-sha"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(f"{divergent}\n", encoding="utf-8")
    cursor.chmod(0o600)

    result = subprocess.run(
        [str(SCRIPT), candidate],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode != 0
    assert "refusing ancestry-divergent deploy target" in result.stderr
    assert cursor.read_text(encoding="utf-8").strip() == divergent
    assert not calls.exists(), "rejected target must not reach canonical-gate mutation"


@pytest.mark.parametrize("hostile_state", ["group-writable", "hardlink", "symlink"])
def test_deploy_cursor_rejects_unsafe_inode_before_mutation(
    tmp_path: Path,
    hostile_state: str,
) -> None:
    repo, candidate = _repo_with_gate_closure_and_docs_commit(tmp_path)
    prior = _git(repo, "rev-parse", f"{candidate}^")
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=True)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)
    cursor = tmp_path / "traces/last-deployed-sha"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(f"{prior}\n", encoding="utf-8")
    cursor.chmod(0o600)
    if hostile_state == "group-writable":
        cursor.chmod(0o620)
    elif hostile_state == "hardlink":
        os.link(cursor, cursor.with_name("cursor-hardlink"))
    elif hostile_state == "symlink":
        target = cursor.with_name("cursor-target")
        cursor.rename(target)
        cursor.symlink_to(target)
    else:  # pragma: no cover - exhaustive parametrization guard
        raise AssertionError(hostile_state)

    result = subprocess.run(
        [str(SCRIPT), candidate],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode != 0
    assert "refused unsafe deploy cursor" in result.stderr
    assert not calls.exists(), "unsafe cursor must fail before canonical-gate mutation"


def test_completion_trace_and_cursor_publish_under_one_trace_lock(tmp_path: Path) -> None:
    repo, sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=False)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)
    marker = tmp_path / "trace-python-returned"
    release = tmp_path / "release-trace-python"
    python_bin = tmp_path / "bin" / "python3"
    python_bin.parent.mkdir()
    python_bin.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        '/usr/bin/python3 "$@"\n'
        "rc=$?\n"
        'if [ "${HAPAX_PAUSE_AFTER_TRACE_PYTHON:-0}" = 1 ]; then\n'
        '  : > "$HAPAX_TRACE_PYTHON_RETURNED_MARKER"\n'
        '  while [ ! -e "$HAPAX_TRACE_PYTHON_RELEASE" ]; do /usr/bin/sleep 0.01; done\n'
        "fi\n"
        'exit "$rc"\n',
        encoding="utf-8",
    )
    python_bin.chmod(0o755)
    env["PATH"] = f"{python_bin.parent}:{env['PATH']}"
    env["HAPAX_PAUSE_AFTER_TRACE_PYTHON"] = "1"
    env["HAPAX_TRACE_PYTHON_RETURNED_MARKER"] = str(marker)
    env["HAPAX_TRACE_PYTHON_RELEASE"] = str(release)
    cursor = tmp_path / "traces/last-deployed-sha"

    source = SCRIPT.read_text(encoding="utf-8")
    transaction_start = source.index("def write_temp(")
    transaction = source[transaction_start : source.index("PY\n}", transaction_start)]
    assert (
        transaction.index("fcntl.flock(lock_fd, fcntl.LOCK_EX)")
        < transaction.index("os.replace(trace_temp, path)")
        < transaction.index("os.replace(cursor_temp, cursor)")
        < transaction.index("os.close(lock_fd)")
    )

    release.touch()
    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not marker.exists(), "transactional Python must ignore caller PATH"
    assert cursor.read_text(encoding="utf-8").strip() == sha
    trace = Path(env["HAPAX_POST_MERGE_TRACE_PATH"])
    assert json.loads(trace.read_text(encoding="utf-8").splitlines()[-1])["sha"] == sha


def test_empty_commit_dry_run_never_publishes_deploy_cursor(tmp_path: Path) -> None:
    repo, sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    _git(repo, "commit", "--allow-empty", "-m", "empty dry-run edge")
    sha = _git(repo, "rev-parse", "HEAD")
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=False)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)
    cursor = tmp_path / "traces/last-deployed-sha"

    result = subprocess.run(
        [str(SCRIPT), "--dry-run", sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not cursor.exists()
    record = json.loads(Path(env["HAPAX_POST_MERGE_TRACE_PATH"]).read_text(encoding="utf-8"))
    assert record["mode"] == "dry_run"
    assert record["status"] == "no_changes"


@pytest.mark.parametrize("empty_commit", [False, True], ids=["changed-files", "no-files"])
def test_trace_failure_is_fatal_and_never_advances_writable_cursor(
    tmp_path: Path, empty_commit: bool
) -> None:
    repo, sha = _repo_with_gate_closure_and_docs_commit(tmp_path)
    if empty_commit:
        _git(repo, "commit", "--allow-empty", "-m", "empty deploy edge")
        sha = _git(repo, "rev-parse", "HEAD")
    canon = tmp_path / "canon"
    calls = tmp_path / "hooks-doctor-calls.txt"
    _seed_canonical_gate(repo, canon, stale=False)
    env = _gate_reconcile_env(tmp_path, repo, canon, calls)
    trace_path = Path(env["HAPAX_POST_MERGE_TRACE_PATH"])
    trace_path.mkdir(parents=True)
    cursor = tmp_path / "cursor/last-deployed-sha"
    cursor.parent.mkdir()
    previous = _git(repo, "rev-parse", f"{sha}^")
    cursor.write_text(f"{previous}\n", encoding="utf-8")
    cursor.chmod(0o600)
    env["HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH"] = str(cursor)

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode != 0
    assert "failed to publish completion trace" in result.stderr
    assert cursor.read_text(encoding="utf-8").strip() == previous
    assert not list(cursor.parent.glob(".last-deployed-sha.tmp.*"))


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
