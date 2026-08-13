"""Tests for scripts/hapax-post-merge-smoke.

Per cc-task ``post-merge-smoke-runner`` (WSJF 6.5, 2026-05-02).
Verifies the active gates:

- services-restarted (systemd/units/*.service in diff → unit must be active,
  except successful timer-backed oneshots, which should exit)
- broadcast-healthy (audio-routing surface diff → world-surface row OK in 30s)
- m8-midi-clock-peer (midi_clock.py diff → M8 tempo signal present, if M8 connected)

The dependent-component gate (wgpu/visual diff → hapax-imagination active)
was retired with the Tauri/WebKit hapax-logos decommission per cc-task
``hapax-logos-decommission-cleanup``. The hapax-imagination binary's
provenance is now covered by scripts/smoke-test.sh.

Each gate is exercised via a per-test git fixture that constructs the
diff shape that triggers it. systemctl / journalctl are stubbed on
PATH so the tests don't touch real services.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE = REPO_ROOT / "scripts" / "hapax-post-merge-smoke"
INSTALL_UNITS_PATH = "systemd/scripts/install-units.sh"


def _bounded_systemd_run_stub() -> str:
    return r"""
set -euo pipefail
runtime=60
runtime_seen=0
user_seen=0
wait_seen=0
pipe_seen=0
collect_seen=0
service_type_seen=0
expand_disabled_seen=0
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
        --property=TimeoutStopSec=1s) stop_timeout_seen=1 ;;
        --property=KillMode=control-group) kill_mode_seen=1 ;;
        --property=SendSIGKILL=yes) sigkill_seen=1 ;;
        --no-ask-password) no_ask_seen=1 ;;
        --setenv=*=*) export "${1#--setenv=}" ;;
        --) shift; break ;;
    esac
    shift
done
if [ "$runtime_seen$user_seen$wait_seen$pipe_seen$collect_seen$service_type_seen$expand_disabled_seen$stop_timeout_seen$kill_mode_seen$sigkill_seen$no_ask_seen" != 11111111111 ]; then
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
"""


def _install_units_source(*decommissioned_units: str) -> str:
    entries = "".join(f"    {unit}\n" for unit in decommissioned_units)
    return f"DECOMMISSIONED_UNITS=(\n{entries})\n"


def _run(
    sha: str,
    *,
    cwd: Path,
    since: str | None = None,
    extra_env: dict[str, str] | None = None,
    stubs: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the smoke script with optional stub binaries on PATH."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(cwd),
        "REPO_ROOT": str(cwd),
        "HAPAX_SMOKE_OFF": "0",
    }
    bin_dir = cwd / "_stubs"
    bin_dir.mkdir(parents=True, exist_ok=True)
    effective_stubs = {"systemd-run": _bounded_systemd_run_stub(), **(stubs or {})}
    for name, body in effective_stubs.items():
        stub = bin_dir / name
        stub.write_text(f"#!/usr/bin/env bash\n{body}\n")
        stub.chmod(0o755)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_SMOKE_ISOLATED_TEST_ROOT"] = str(cwd)
    env["HAPAX_SMOKE_SYSTEMD_RUN_BIN"] = str(bin_dir / "systemd-run")
    if extra_env:
        env.update(extra_env)
    command = ["bash", str(SMOKE)]
    if since is not None:
        command.extend(("--since", since, sha))
    else:
        command.append(sha)
    return subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


def _init_repo(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.email", "t@x"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    return tmp_path


def _make_repo(tmp_path: Path) -> Path:
    """Init a git repo with a baseline commit so SHA^1 resolves after a change."""
    _init_repo(tmp_path)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "GIT_TERMINAL_PROMPT": "0"}
    install_units = tmp_path / INSTALL_UNITS_PATH
    install_units.parent.mkdir(parents=True, exist_ok=True)
    install_units.write_text(_install_units_source())
    (tmp_path / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=tmp_path, check=True, env=env)
    return tmp_path


def _commit_files(repo: Path, files: dict[str, str]) -> str:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(repo), "GIT_TERMINAL_PROMPT": "0"}
    for path, body in files.items():
        full = repo / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(body)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "test"], cwd=repo, check=True, env=env)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return sha


# ── Master kill switch ─────────────────────────────────────────────


class TestKillSwitch:
    def test_smoke_off_short_circuits(self, tmp_path: Path) -> None:
        """`HAPAX_SMOKE_OFF=1` → exit 0 silent."""
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"systemd/units/x.service": "[Unit]\n"})
        result = _run(sha, cwd=repo, extra_env={"HAPAX_SMOKE_OFF": "1"})
        assert result.returncode == 0
        assert result.stderr == ""

    def test_invalid_sha_is_operator_visible_and_notified(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        marker = repo / "ntfy-called"
        result = _run(
            "not-a-sha-deadbeef",
            cwd=repo,
            extra_env={"NTFY_TOPIC": "test-topic", "HAPAX_SMOKE_NTFY_MARKER": str(marker)},
            stubs={"curl": 'printf called > "$HAPAX_SMOKE_NTFY_MARKER"'},
        )

        assert result.returncode == 2
        assert "smoke FAIL: change-discovery:" in result.stderr
        assert "cannot resolve target commit" in result.stderr
        assert "next action:" in result.stderr
        assert marker.read_text() == "called"

    def test_invalid_ref_cannot_expand_notification_beyond_payload_bound(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        payload = repo / "ntfy-payload"
        invalid_ref = "invalid-" + ("x" * 12000)
        result = _run(
            invalid_ref,
            cwd=repo,
            extra_env={
                "NTFY_TOPIC": "test-topic",
                "HAPAX_SMOKE_NTFY_PAYLOAD": str(payload),
            },
            stubs={
                "curl": r"""
while [ "$#" -gt 0 ]; do
    if [ "$1" = "-d" ]; then
        printf '%s' "$2" > "$HAPAX_SMOKE_NTFY_PAYLOAD"
        exit 0
    fi
    shift
done
exit 91
"""
            },
        )

        assert result.returncode == 2
        assert payload.stat().st_size <= 4096
        assert invalid_ref not in payload.read_text(encoding="utf-8")

    def test_foreign_repo_root_is_operator_visible_and_notified(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "expected")
        sha = _commit_files(repo, {"README.md": "target\n"})
        foreign = _make_repo(tmp_path / "foreign")
        marker = repo / "ntfy-called"

        result = _run(
            sha,
            cwd=repo,
            extra_env={
                "REPO_ROOT": str(foreign),
                "NTFY_TOPIC": "test-topic",
                "HAPAX_SMOKE_NTFY_MARKER": str(marker),
            },
            stubs={"curl": 'printf called > "$HAPAX_SMOKE_NTFY_MARKER"'},
        )

        assert result.returncode == 2
        assert "smoke FAIL: change-discovery:" in result.stderr
        assert "cannot resolve target commit" in result.stderr
        assert "next action:" in result.stderr
        assert marker.read_text() == "called"

    def test_missing_since_object_is_operator_visible_and_notified(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"README.md": "target\n"})
        marker = repo / "ntfy-called"

        result = _run(
            sha,
            since="missing-base-deadbeef",
            cwd=repo,
            extra_env={"NTFY_TOPIC": "test-topic", "HAPAX_SMOKE_NTFY_MARKER": str(marker)},
            stubs={"curl": 'printf called > "$HAPAX_SMOKE_NTFY_MARKER"'},
        )

        assert result.returncode == 2
        assert "smoke FAIL: change-discovery:" in result.stderr
        assert "cannot resolve --since commit" in result.stderr
        assert "next action:" in result.stderr
        assert marker.read_text() == "called"

    def test_empty_since_is_rejected_instead_of_collapsing_to_single_commit(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"README.md": "target\n"})

        result = _run(sha, since="", cwd=repo)

        assert result.returncode == 2
        assert "smoke FAIL: change-discovery:" in result.stderr
        assert "empty --since commit" in result.stderr
        assert "next action:" in result.stderr

    def test_root_commit_smokes_added_service(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        sha = _commit_files(
            repo,
            {
                INSTALL_UNITS_PATH: _install_units_source(),
                "systemd/units/root.service": "[Unit]\n",
            },
        )

        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": (
                    'if [ "${2:-}" = show ] && [ "${5:-}" = ActiveState ]; then '
                    "echo inactive; exit 0; fi\nexit 3"
                )
            },
        )

        assert result.returncode == 0
        assert "root.service not active after deploy" in result.stderr

    def test_shallow_boundary_is_not_misclassified_as_a_root_commit(self, tmp_path: Path) -> None:
        origin = _make_repo(tmp_path / "origin")
        _commit_files(origin, {"agents/midi_clock.py": "enabled = True\n"})
        (origin / "agents/midi_clock.py").unlink()
        subprocess.run(["git", "add", "-A"], cwd=origin, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "delete gate input"], cwd=origin, check=True)
        shallow = tmp_path / "shallow"
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", f"file://{origin}", str(shallow)],
            check=True,
        )
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=shallow,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        result = _run(sha, cwd=shallow)

        assert result.returncode == 2
        assert "smoke FAIL: change-discovery:" in result.stderr
        assert "first parent object" in result.stderr
        assert "shallow" in result.stderr
        assert "next action:" in result.stderr

    def test_cumulative_range_smokes_intermediate_service(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        _commit_files(repo, {"systemd/units/intermediate.service": "[Unit]\n"})
        tip = _commit_files(repo, {"README.md": "tip only\n"})

        result = _run(tip, since=base, cwd=repo, stubs={"systemctl": "exit 3"})

        assert result.returncode == 0
        assert "intermediate.service not active after deploy" in result.stderr

    def test_moving_ref_is_pinned_before_parent_and_diff_reads(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        service_sha = _commit_files(repo, {"systemd/units/pinned.service": "[Unit]\n"})
        successor_sha = _commit_files(repo, {"README.md": "unrelated successor\n"})
        subprocess.run(
            ["git", "branch", "moving", service_sha],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        result = _run(
            "moving",
            cwd=repo,
            extra_env={"HAPAX_SMOKE_MOVE_REF_TO": successor_sha},
            stubs={
                "git": r"""
if [ "${1:-}" = rev-parse ] && [[ "$*" == *"moving^{commit}"* ]]; then
    resolved="$(/usr/bin/git "$@")" || exit $?
    /usr/bin/git update-ref refs/heads/moving "$HAPAX_SMOKE_MOVE_REF_TO"
    printf '%s\n' "$resolved"
    exit 0
fi
exec /usr/bin/git "$@"
""",
                "systemctl": "exit 3",
            },
        )

        assert result.returncode == 0
        assert "pinned.service not active" in result.stderr

    def test_git_diff_failure_is_operator_visible_and_notified(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"README.md": "changed\n"})
        marker = repo / "ntfy-called"
        result = _run(
            sha,
            cwd=repo,
            extra_env={
                "NTFY_TOPIC": "test-topic",
                "HAPAX_SMOKE_NTFY_MARKER": str(marker),
            },
            stubs={
                "git": r"""
if [ "${1:-}" = diff ]; then
    printf 'simulated object read failure\n' >&2
    exit 91
fi
exec /usr/bin/git "$@"
""",
                "curl": 'printf called > "$HAPAX_SMOKE_NTFY_MARKER"',
            },
        )

        assert result.returncode == 2
        assert "smoke FAIL: change-discovery:" in result.stderr
        assert "cannot enumerate changed files" in result.stderr
        assert "next action:" in result.stderr
        assert marker.read_text() == "called"

    def test_failure_notification_has_a_hard_deadline(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"systemd/units/slow-notice.service": "[Unit]\n"})
        started = time.monotonic()

        result = _run(
            sha,
            cwd=repo,
            extra_env={"NTFY_TOPIC": "test-topic", "HAPAX_SMOKE_NTFY_TIMEOUT_S": "1"},
            stubs={"systemctl": "exit 3", "curl": "trap '' TERM\nwhile :; do :; done"},
        )

        assert result.returncode == 0
        assert time.monotonic() - started < 2.5
        assert "slow-notice.service not active after deploy" in result.stderr

    def test_failure_notification_cgroup_reaps_detached_descendants(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"systemd/units/notice-child.service": "[Unit]\n"})
        pid_file = repo / "detached-notice-child.pid"

        result = _run(
            sha,
            cwd=repo,
            extra_env={
                "NTFY_TOPIC": "test-topic",
                "HAPAX_TEST_SMOKE_DESCENDANT_PID_FILE": str(pid_file),
            },
            stubs={
                "systemctl": "exit 3",
                "curl": (
                    "/usr/bin/setsid /usr/bin/sleep 30 &\n"
                    'printf \'%s\\n\' "$!" > "$HAPAX_TEST_SMOKE_DESCENDANT_PID_FILE"\n'
                    "exit 0"
                ),
            },
        )

        assert result.returncode == 0
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

    def test_failure_notification_payload_and_retained_entries_are_bounded(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        files = {
            f"systemd/units/failure-{index:02d}-{'x' * 96}.service": "[Unit]\n"
            for index in range(20)
        }
        sha = _commit_files(repo, files)
        payload = repo / "ntfy-payload"
        result = _run(
            sha,
            cwd=repo,
            extra_env={
                "NTFY_TOPIC": "test-topic",
                "HAPAX_SMOKE_NTFY_PAYLOAD": str(payload),
            },
            stubs={
                "systemctl": "exit 3",
                "curl": r"""
while [ "$#" -gt 0 ]; do
    if [ "$1" = "-d" ]; then
        printf '%s' "$2" > "$HAPAX_SMOKE_NTFY_PAYLOAD"
        exit 0
    fi
    shift
done
exit 91
""",
            },
        )

        assert result.returncode == 0
        assert "gates_failed=20" in payload.read_text(encoding="utf-8")
        assert payload.stat().st_size <= 4096
        assert "additional smoke failures omitted" in result.stderr
        assert "omitted=" in payload.read_text(encoding="utf-8")


# ── Gate: services-restarted ───────────────────────────────────────


class TestServicesRestartedGate:
    def test_exact_sha_decommission_wins_when_worktree_removes_unit(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        unit = "retired-at-reviewed-sha.service"
        sha = _commit_files(
            repo,
            {
                INSTALL_UNITS_PATH: _install_units_source(unit),
                f"systemd/units/{unit}": "[Unit]\n",
            },
        )
        (repo / INSTALL_UNITS_PATH).write_text(_install_units_source())

        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": (
                    'if [ "${2:-}" = show ] && [ "${5:-}" = ActiveState ]; then '
                    "echo inactive; exit 0; fi\nexit 3"
                )
            },
        )

        assert result.returncode == 0
        assert "services-restarted" not in result.stderr
        assert f"{unit} not active" not in result.stderr

    def test_active_decommissioned_unit_records_retirement_failure(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        unit = "retired-but-still-active.service"
        sha = _commit_files(
            repo,
            {
                INSTALL_UNITS_PATH: _install_units_source(unit),
                f"systemd/units/{unit}": "[Unit]\n",
            },
        )

        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": (
                    'if [ "${2:-}" = show ] && [ "${5:-}" = ActiveState ]; then '
                    "echo active; fi\nexit 0"
                )
            },
        )

        assert result.returncode == 0
        assert "services-restarted" in result.stderr
        assert f"{unit} must be inactive after deploy" in result.stderr
        assert "next action:" in result.stderr

    def test_active_parked_unit_records_retirement_failure(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        unit = "parked-but-still-active.service"
        sha = _commit_files(
            repo,
            {
                f"systemd/units/{unit}": (
                    "# Hapax-Parked: true\n"
                    "[Unit]\nDescription=Parked\n"
                    "[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
                )
            },
        )

        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": (
                    'if [ "${2:-}" = show ] && [ "${5:-}" = ActiveState ]; then '
                    "echo active; fi\nexit 0"
                )
            },
        )

        assert result.returncode == 0
        assert "services-restarted" in result.stderr
        assert f"{unit} must be inactive after deploy" in result.stderr
        assert "next action:" in result.stderr

    def test_worktree_decommission_cannot_override_exact_sha(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        unit = "live-at-reviewed-sha.service"
        sha = _commit_files(repo, {f"systemd/units/{unit}": "[Unit]\n"})
        (repo / INSTALL_UNITS_PATH).write_text(_install_units_source(unit))

        result = _run(sha, cwd=repo, stubs={"systemctl": "exit 3"})

        assert result.returncode == 0
        assert "services-restarted" in result.stderr
        assert f"{unit} not active" in result.stderr

    def test_missing_exact_sha_decommission_data_records_failure(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / INSTALL_UNITS_PATH).unlink()
        sha = _commit_files(repo, {"systemd/units/foo.service": "[Unit]\n"})

        result = _run(sha, cwd=repo, stubs={"systemctl": "exit 0"})

        assert result.returncode == 2
        assert "services-restarted" in result.stderr
        assert "cannot read exact-SHA decommission data" in result.stderr

    def test_malformed_exact_sha_decommission_data_records_failure(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {
                INSTALL_UNITS_PATH: "DECOMMISSIONED_UNITS=(foo.service)\n",
                "systemd/units/foo.service": "[Unit]\n",
            },
        )

        result = _run(sha, cwd=repo, stubs={"systemctl": "exit 0"})

        assert result.returncode == 2
        assert "services-restarted" in result.stderr
        assert "cannot parse exact-SHA decommission data" in result.stderr

    def test_inactive_unit_records_failure(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"systemd/units/foo.service": "[Unit]\n"})
        # systemctl returns non-zero for inactive
        result = _run(
            sha,
            cwd=repo,
            stubs={"systemctl": "exit 3"},
        )
        assert result.returncode == 0
        assert "services-restarted" in result.stderr
        assert "foo.service not active" in result.stderr

    def test_active_unit_passes_silently(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"systemd/units/foo.service": "[Unit]\n"})
        result = _run(
            sha,
            cwd=repo,
            stubs={"systemctl": "exit 0"},
        )
        assert result.returncode == 0
        assert "services-restarted" not in result.stderr

    def test_template_unit_file_passes_without_active_instance(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"systemd/units/hapax-claude-lane@.service": "[Unit]\n"},
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={"systemctl": "exit 3"},
        )

        assert result.returncode == 0
        assert "services-restarted" not in result.stderr
        assert "hapax-claude-lane@.service" not in result.stderr

    def test_system_scoped_unit_file_passes_without_user_active_check(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {
                "systemd/units/hapax-l12-critical-usb-guard.service": (
                    "[Unit]\n# Hapax-Install-Scope: system\nDescription=System scoped guard\n"
                )
            },
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={"systemctl": "exit 3"},
        )

        assert result.returncode == 0
        assert "services-restarted" not in result.stderr
        assert "hapax-l12-critical-usb-guard.service" not in result.stderr

    def test_indented_system_scope_marker_uses_system_classification(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {
                "systemd/units/indented-root.service": (
                    "[Unit]\n  # Hapax-Install-Scope : system  \n"
                    "[Service]\nExecStart=/usr/bin/true\n"
                )
            },
        )

        result = _run(sha, cwd=repo, stubs={"systemctl": "exit 3"})

        assert result.returncode == 0
        assert "services-restarted" not in result.stderr
        assert "indented-root.service" not in result.stderr

    def test_malformed_install_scope_marker_records_classification_failure(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {
                "systemd/units/root-owned.service": (
                    "[Unit]\n# Hapax-Install-Scope: system disabled\n"
                    "[Service]\nExecStart=/usr/bin/true\n"
                )
            },
        )
        result = _run(sha, cwd=repo, stubs={"systemctl": "exit 0"})

        assert result.returncode == 2
        assert "services-restarted" in result.stderr
        assert "invalid Hapax-Install-Scope" in result.stderr

    def test_inactive_expected_state_query_failure_is_execution_failure(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        unit = "retired-query-failure.service"
        sha = _commit_files(
            repo,
            {
                INSTALL_UNITS_PATH: _install_units_source(unit),
                f"systemd/units/{unit}": "[Unit]\n",
            },
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": (
                    'if [ "${2:-}" = show ] && [ "${5:-}" = ActiveState ]; then exit 74; fi\nexit 3'
                )
            },
        )

        assert result.returncode == 2
        assert "cannot query ActiveState" in result.stderr

    def test_successful_oneshot_inactive_unit_passes_silently(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"systemd/units/foo.service": "[Service]\nType=oneshot\n"},
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": """
if [ "$2" = "is-active" ]; then exit 3; fi
if [ "$2" = "show" ]; then
  case "$5" in
    Type) echo oneshot ;;
    Result) echo success ;;
    ExecMainStatus) echo 0 ;;
  esac
  exit 0
fi
exit 1
""",
            },
        )
        assert result.returncode == 0
        assert "services-restarted" not in result.stderr

    def test_failed_oneshot_inactive_unit_records_failure(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"systemd/units/foo.service": "[Service]\nType=oneshot\n"},
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": """
if [ "$2" = "is-active" ]; then exit 3; fi
if [ "$2" = "show" ]; then
  case "$5" in
    Type) echo oneshot ;;
    Result) echo failed ;;
    ExecMainStatus) echo 1 ;;
  esac
  exit 0
fi
exit 1
""",
            },
        )
        assert result.returncode == 0
        assert "services-restarted" in result.stderr
        assert "foo.service not active" in result.stderr

    def test_disabled_install_only_service_passes_silently(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"systemd/units/foo.service": "[Service]\nType=notify\n"},
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": """
if [ "$2" = "is-active" ]; then exit 3; fi
if [ "$2" = "show" ]; then
  case "$5" in
    Type) echo notify ;;
    Result) echo success ;;
    ExecMainStatus) echo 0 ;;
    UnitFileState) echo disabled ;;
  esac
  exit 0
fi
exit 1
""",
            },
        )
        assert result.returncode == 0
        assert "services-restarted" not in result.stderr

    def test_disabled_failed_service_records_failure(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"systemd/units/foo.service": "[Service]\nType=notify\n"},
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": """
if [ "$2" = "is-active" ]; then exit 3; fi
if [ "$2" = "show" ]; then
  case "$5" in
    Type) echo notify ;;
    Result) echo failed ;;
    ExecMainStatus) echo 1 ;;
    UnitFileState) echo disabled ;;
  esac
  exit 0
fi
exit 1
""",
            },
        )
        assert result.returncode == 0
        assert "services-restarted" in result.stderr
        assert "foo.service not active" in result.stderr

    def test_bridge_unit_inactive_passes_when_compositor_selects_direct_egress(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"systemd/units/hapax-v4l2-bridge.service": "[Service]\nType=simple\n"},
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": """
if [ "$2" = "is-active" ]; then exit 3; fi
if [ "$2" = "show" ] && [ "$3" = "studio-compositor.service" ] && [ "$5" = "Environment" ]; then
  echo "HAPAX_V4L2_BRIDGE_ENABLED=0 HAPAX_COMPOSITOR_DISABLE_V4L2_OUTPUT=0"
  exit 0
fi
if [ "$2" = "show" ]; then
  case "$5" in
    Type) echo simple ;;
    Result) echo success ;;
    ExecMainStatus) echo 0 ;;
    UnitFileState) echo enabled ;;
  esac
  exit 0
fi
exit 1
""",
            },
        )

        assert result.returncode == 0
        assert "services-restarted" not in result.stderr
        assert "hapax-v4l2-bridge.service not active" not in result.stderr

    def test_bridge_unit_inactive_passes_when_3d_direct_mode_is_active(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"systemd/units/hapax-v4l2-bridge.service": "[Service]\nType=simple\n"},
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": """
if [ "$2" = "is-active" ]; then exit 3; fi
if [ "$2" = "show" ] && [ "$3" = "studio-compositor.service" ] && [ "$5" = "Environment" ]; then
  echo "HAPAX_V4L2_BRIDGE_ENABLED=1 HAPAX_3D_COMPOSITOR=1"
  exit 0
fi
if [ "$2" = "show" ]; then
  case "$5" in
    Type) echo simple ;;
    Result) echo success ;;
    ExecMainStatus) echo 0 ;;
    UnitFileState) echo enabled ;;
  esac
  exit 0
fi
exit 1
""",
            },
        )

        assert result.returncode == 0
        assert "services-restarted" not in result.stderr
        assert "hapax-v4l2-bridge.service not active" not in result.stderr

    def test_bridge_unit_inactive_fails_when_compositor_expects_bridge(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"systemd/units/hapax-v4l2-bridge.service": "[Service]\nType=simple\n"},
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": """
if [ "$2" = "is-active" ]; then exit 3; fi
if [ "$2" = "show" ] && [ "$3" = "studio-compositor.service" ] && [ "$5" = "Environment" ]; then
  echo "HAPAX_V4L2_BRIDGE_ENABLED=1 HAPAX_COMPOSITOR_DISABLE_V4L2_OUTPUT=1"
  exit 0
fi
if [ "$2" = "show" ]; then
  case "$5" in
    Type) echo simple ;;
    Result) echo success ;;
    ExecMainStatus) echo 0 ;;
    UnitFileState) echo enabled ;;
  esac
  exit 0
fi
exit 1
""",
            },
        )

        assert result.returncode == 0
        assert "services-restarted" in result.stderr
        assert "hapax-v4l2-bridge.service not active" in result.stderr

    def test_no_unit_diff_skips_gate(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"agents/foo.py": "x = 1\n"})
        result = _run(sha, cwd=repo)
        assert result.returncode == 0
        assert "services-restarted" not in result.stderr


# ── Gate: broadcast-healthy ────────────────────────────────────────


class TestBroadcastHealthyGate:
    def test_dryrun_announces_gate(self, tmp_path: Path) -> None:
        """Dry-run path: gate prints which gate would fire, no real check."""
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"agents/studio_compositor/foo.py": "x = 1\n"},
        )
        result = _run(sha, cwd=repo, extra_env={"HAPAX_SMOKE_DRYRUN": "1"})
        assert result.returncode == 0
        assert "broadcast-healthy" in result.stdout

    def test_no_audio_diff_skips_gate(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"agents/foo.py": "x = 1\n"})
        result = _run(sha, cwd=repo, extra_env={"HAPAX_SMOKE_DRYRUN": "1"})
        assert result.returncode == 0
        assert "broadcast-healthy" not in result.stdout

    def test_voice_router_diff_triggers_gate(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"shared/voice_output_router.py": "VoiceRole = 'x'\n"},
        )
        result = _run(sha, cwd=repo, extra_env={"HAPAX_SMOKE_DRYRUN": "1"})
        assert "broadcast-healthy" in result.stdout

    def test_broadcast_health_module_diff_triggers_gate(self, tmp_path: Path) -> None:
        """broadcast_audio_health.py is the producer the gate watches; its
        own diffs must fire the gate (regression risk to the producer)."""
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"shared/broadcast_audio_health.py": "DEFAULT = 'x'\n"},
        )
        result = _run(sha, cwd=repo, extra_env={"HAPAX_SMOKE_DRYRUN": "1"})
        assert "broadcast-healthy" in result.stdout


# ── Gate: m8-midi-clock-peer ───────────────────────────────────────


class TestM8MidiClockPeerGate:
    def test_midi_clock_diff_triggers_gate(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"agents/hapax_daimonion/backends/midi_clock.py": "x=1\n"},
        )
        result = _run(sha, cwd=repo, extra_env={"HAPAX_SMOKE_DRYRUN": "1"})
        assert "m8-midi-clock-peer" in result.stdout

    def test_skips_when_m8_absent(self, tmp_path: Path) -> None:
        """`amidi` present but no M8 device listed → skip silent."""
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"agents/hapax_daimonion/backends/midi_clock.py": "x=1\n"},
        )
        result = _run(sha, cwd=repo, stubs={"amidi": "exit 0"})
        assert "m8-midi-clock-peer" not in result.stderr


# ── Script integrity ───────────────────────────────────────────────


class TestScriptIntegrity:
    def test_script_is_executable(self) -> None:
        assert os.access(SMOKE, os.X_OK)

    def test_script_uses_strict_bash(self) -> None:
        body = SMOKE.read_text(encoding="utf-8")
        assert body.startswith("#!/usr/bin/env bash")
        assert "set -uo pipefail" in body or "set -euo pipefail" in body

    def test_script_documents_kill_switches(self) -> None:
        body = SMOKE.read_text(encoding="utf-8")
        assert "HAPAX_SMOKE_OFF" in body
        assert "HAPAX_SMOKE_DRYRUN" in body

    def test_script_propagates_execution_failures_only(self) -> None:
        """Advisory gates stay zero, but infrastructure failures block receipts."""
        body = SMOKE.read_text(encoding="utf-8")
        assert "record_execution_failure()" in body
        for line in reversed(body.splitlines()):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            assert stripped == 'exit "$EXECUTION_FAILURE"'
            break

    def test_script_uses_ntfy_on_failure(self) -> None:
        body = SMOKE.read_text(encoding="utf-8")
        assert "NTFY_TOPIC" in body
        assert "ntfy.sh" in body
