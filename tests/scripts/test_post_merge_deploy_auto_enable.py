"""Deploy auto-ENABLE behaviour for hapax-post-merge-deploy.

reform-improve-deploy-activation-20260601 (CASE-SDLC-REFORM-001):
`cp + daemon-reload + try-restart` is a NO-OP for a new, never-enabled unit,
so a freshly-merged systemd unit installs-but-sleeps. The deploy now
auto-`enable --now`s units that carry a `# Hapax-Auto-Enable: true` marker
(plus an [Install] section), and exposes a `--verify-auto-enable` assertion
that every marked unit is enabled (and, for timers, active).

The deploy script shells out to `systemctl --user`; these tests intercept it
with a fake `systemctl` on PATH (the repo's watchdog-test idiom) and run the
real script against a throwaway git repo so the commit-time unit content is
read exactly the way production reads it (`git show <sha>:<path>`).
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-post-merge-deploy"

MARKER = "# Hapax-Auto-Enable: true"
ENABLE_ONLY_MARKER = "# Hapax-Timer-Enable-Only: true"

SVC_AUTOENABLE = f"""
{MARKER}
[Unit]
Description=Test auto-enable service
[Service]
Type=oneshot
ExecStart=/bin/true
[Install]
WantedBy=default.target
"""

SVC_MANUAL = """
[Unit]
Description=Test manual (unmarked) service
[Service]
Type=oneshot
ExecStart=/bin/true
[Install]
WantedBy=default.target
"""

SVC_MARKED_NO_INSTALL = f"""
{MARKER}
[Unit]
Description=Marked but no [Install] — enable would fail, so skip
[Service]
Type=oneshot
ExecStart=/bin/true
"""

TIMER_PLAIN = """
[Unit]
Description=Plain timer (no marker) — back-compat auto-enable
[Timer]
OnUnitActiveSec=60
[Install]
WantedBy=timers.target
"""

TIMER_AUTOENABLE = f"""
{MARKER}
[Unit]
Description=Marked timer (the lane-supervisor shape)
[Timer]
OnUnitActiveSec=60
[Install]
WantedBy=timers.target
"""

TIMER_ENABLE_ONLY = f"""
{ENABLE_ONLY_MARKER}
[Unit]
Description=Enable-only timer (no deploy-time start)
[Timer]
OnStartupSec=2min
[Install]
WantedBy=timers.target
"""


def _git(repo: Path, *args: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _make_repo(tmp_path: Path, units: dict[str, str]) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    (repo / "systemd" / "units").mkdir(parents=True)
    for name, body in units.items():
        (repo / "systemd" / "units" / name).write_text(
            textwrap.dedent(body).strip() + "\n", encoding="utf-8"
        )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture units")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, sha


def _make_fake_systemctl(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "systemctl-calls.txt"
    stub = bin_dir / "systemctl"
    stub.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            args="$*"
            printf '%s\\n' "$args" >> "{calls}"
            case "$args" in
              *"is-active --quiet"*) exit "${{FAKE_IS_ACTIVE_QUIET_RC:-1}}" ;;
              *"is-enabled"*)         exit "${{FAKE_IS_ENABLED_RC:-0}}" ;;
              *"is-active"*)          exit "${{FAKE_IS_ACTIVE_RC:-0}}" ;;
              *)                      exit 0 ;;
            esac
            """
        ),
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return bin_dir, calls


def _run(
    script_args: list[str],
    *,
    repo: Path,
    bin_dir: Path,
    tmp_path: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(home)
    env["REPO"] = str(repo)
    env["HAPAX_POST_MERGE_TRACE_PATH"] = str(tmp_path / "trace.jsonl")
    env.pop("GITHUB_WORKSPACE", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(SCRIPT), *script_args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_deploy_auto_enables_marked_service(tmp_path: Path) -> None:
    """A new service carrying the marker + [Install] is enable --now'd —
    this is the gap: today only timers are auto-enabled, services sleep."""
    repo, sha = _make_repo(tmp_path, {"test-autoenable.service": SVC_AUTOENABLE})
    bin_dir, calls = _make_fake_systemctl(tmp_path)
    res = _run([sha], repo=repo, bin_dir=bin_dir, tmp_path=tmp_path)
    assert res.returncode == 0, res.stderr
    assert "enable --now test-autoenable.service" in calls.read_text(encoding="utf-8")


def test_deploy_does_not_enable_unmarked_service(tmp_path: Path) -> None:
    """Conservative: an unmarked service installs but is never auto-enabled."""
    repo, sha = _make_repo(tmp_path, {"test-manual.service": SVC_MANUAL})
    bin_dir, calls = _make_fake_systemctl(tmp_path)
    res = _run([sha], repo=repo, bin_dir=bin_dir, tmp_path=tmp_path)
    assert res.returncode == 0, res.stderr
    assert "enable --now" not in calls.read_text(encoding="utf-8")


def test_deploy_skips_marked_unit_without_install_section(tmp_path: Path) -> None:
    """A marker without an [Install] section can't be enabled — skip it
    rather than fail the deploy with `no installation config`."""
    repo, sha = _make_repo(tmp_path, {"test-noinstall.service": SVC_MARKED_NO_INSTALL})
    bin_dir, calls = _make_fake_systemctl(tmp_path)
    res = _run([sha], repo=repo, bin_dir=bin_dir, tmp_path=tmp_path)
    assert res.returncode == 0, res.stderr
    assert "enable --now" not in calls.read_text(encoding="utf-8")


def test_deploy_auto_enables_marked_timer(tmp_path: Path) -> None:
    """The lane-supervisor shape: a marked timer is enable --now'd."""
    repo, sha = _make_repo(tmp_path, {"test-auto.timer": TIMER_AUTOENABLE})
    bin_dir, calls = _make_fake_systemctl(tmp_path)
    res = _run([sha], repo=repo, bin_dir=bin_dir, tmp_path=tmp_path)
    assert res.returncode == 0, res.stderr
    assert "enable --now test-auto.timer" in calls.read_text(encoding="utf-8")


def test_deploy_enables_plain_timer_backcompat(tmp_path: Path) -> None:
    """Regression guard: an unmarked NEW timer still auto-enables (the
    long-standing behaviour must not regress when markers are introduced)."""
    repo, sha = _make_repo(tmp_path, {"test-plain.timer": TIMER_PLAIN})
    bin_dir, calls = _make_fake_systemctl(tmp_path)
    res = _run([sha], repo=repo, bin_dir=bin_dir, tmp_path=tmp_path)
    assert res.returncode == 0, res.stderr
    assert "enable --now test-plain.timer" in calls.read_text(encoding="utf-8")


def test_deploy_enable_only_timer_does_not_start_during_deploy(tmp_path: Path) -> None:
    """A timer carrying Hapax-Timer-Enable-Only is enabled for future startup,
    but deploy must not start/restart it with --now."""
    repo, sha = _make_repo(tmp_path, {"test-enable-only.timer": TIMER_ENABLE_ONLY})
    bin_dir, calls = _make_fake_systemctl(tmp_path)
    res = _run([sha], repo=repo, bin_dir=bin_dir, tmp_path=tmp_path)
    assert res.returncode == 0, res.stderr
    text = calls.read_text(encoding="utf-8")
    assert "enable test-enable-only.timer" in text
    assert "enable --now test-enable-only.timer" not in text


def test_deploy_enable_only_active_timer_does_not_restart(tmp_path: Path) -> None:
    """An already-active enable-only timer must stay active, not be restarted
    into a deploy-relative firing window."""
    repo, sha = _make_repo(tmp_path, {"test-enable-only.timer": TIMER_ENABLE_ONLY})
    bin_dir, calls = _make_fake_systemctl(tmp_path)
    res = _run(
        [sha],
        repo=repo,
        bin_dir=bin_dir,
        tmp_path=tmp_path,
        extra_env={"FAKE_IS_ACTIVE_QUIET_RC": "0"},
    )
    assert res.returncode == 0, res.stderr
    text = calls.read_text(encoding="utf-8")
    assert "enable test-enable-only.timer" in text
    assert "restart test-enable-only.timer" not in text
    assert "enable --now test-enable-only.timer" not in text


def test_verify_auto_enable_passes_when_marked_units_enabled(tmp_path: Path) -> None:
    """--verify-auto-enable checks is-enabled (and is-active for timers) for
    every marked unit, and ignores unmarked units."""
    repo, _ = _make_repo(
        tmp_path,
        {
            "test-auto.timer": TIMER_AUTOENABLE,
            "test-manual.service": SVC_MANUAL,
        },
    )
    bin_dir, calls = _make_fake_systemctl(tmp_path)
    res = _run(["--verify-auto-enable"], repo=repo, bin_dir=bin_dir, tmp_path=tmp_path)
    assert res.returncode == 0, res.stderr
    text = calls.read_text(encoding="utf-8")
    assert "is-enabled test-auto.timer" in text
    assert "is-active test-auto.timer" in text
    assert "test-manual.service" not in text


def test_verify_auto_enable_fails_when_marked_unit_not_enabled(tmp_path: Path) -> None:
    """A marked unit that is NOT enabled fails the assertion (exit 1)."""
    repo, _ = _make_repo(tmp_path, {"test-auto.timer": TIMER_AUTOENABLE})
    bin_dir, _calls = _make_fake_systemctl(tmp_path)
    res = _run(
        ["--verify-auto-enable"],
        repo=repo,
        bin_dir=bin_dir,
        tmp_path=tmp_path,
        extra_env={"FAKE_IS_ENABLED_RC": "1"},
    )
    assert res.returncode == 1, (res.stdout, res.stderr)
    assert "test-auto.timer" in res.stderr
