"""Unsafe cases for the vault snapshot index.lock reap.

A live git on this host, a live git reported on the other host, an
unreachable other host, and a lock younger than the snapshot interval
all refuse the reap. Only an old lock with both sides clear is renamed
into evidence.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "vault-git-snapshot"


def _bash(snippet: str, env: dict[str, str] | None = None) -> str:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    result = subprocess.run(
        ["bash", "-c", f"set -euo pipefail; source {SCRIPT}; {snippet}"],
        check=True,
        capture_output=True,
        text=True,
        env=merged,
    )
    return result.stdout.strip()


def _decision(age: int, interval: int, local: int, remote: str) -> str:
    return _bash(f"vault_snapshot_reap_decision {age} {interval} {local} {remote}")


def test_live_local_git_does_not_reap() -> None:
    assert _decision(5000, 1200, 1, "clear") == "keep local-holder"


def test_live_remote_git_does_not_reap() -> None:
    assert _decision(5000, 1200, 0, "hold") == "keep remote-hold"


def test_unreachable_remote_does_not_reap() -> None:
    assert _decision(5000, 1200, 0, "unreachable") == "keep remote-unreachable"


def test_lock_younger_than_interval_does_not_reap() -> None:
    assert _decision(1199, 1200, 0, "clear") == "keep young"


def test_old_lock_with_no_holder_on_either_host_reaps() -> None:
    assert _decision(1200, 1200, 0, "clear") == "reap"


def test_classify_remote_hold_unreachable_and_clear() -> None:
    assert _bash('vault_snapshot_classify_remote 1 ""') == "unreachable"
    assert _bash("vault_snapshot_classify_remote 0 2") == "hold"
    assert _bash("vault_snapshot_classify_remote 0 0") == "clear"


def test_apply_reap_renames_and_keeps_bytes(tmp_path: Path) -> None:
    lock = tmp_path / "index.lock"
    lock.write_bytes(b"evidence-bytes")
    evidence = tmp_path / "evidence"
    moved = _bash(f"vault_snapshot_apply_reap {lock} {evidence} reap")
    dest = Path(moved)
    assert dest.is_file()
    assert dest.read_bytes() == b"evidence-bytes"
    assert not lock.exists()
    assert dest.parent == evidence


def test_keep_does_not_move_the_lock(tmp_path: Path) -> None:
    lock = tmp_path / "index.lock"
    lock.write_bytes(b"stay")
    evidence = tmp_path / "evidence"
    out = _bash(f"vault_snapshot_apply_reap {lock} {evidence} 'keep young'")
    assert out == ""
    assert lock.read_bytes() == b"stay"
    assert not evidence.exists()


def test_existing_evidence_name_is_not_overwritten(tmp_path: Path) -> None:
    lock = tmp_path / "index.lock"
    lock.write_bytes(b"live-lock")
    evidence = tmp_path / "evidence"
    dest = evidence / "index.lock-fixed"
    dest.parent.mkdir()
    dest.write_bytes(b"already-kept")
    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -euo pipefail; source "$1"; vault_snapshot_apply_reap "$2" "$3" reap "$4"',
            "bash",
            str(SCRIPT),
            str(lock),
            str(evidence),
            str(dest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "evidence destination already exists" in result.stderr
    assert "Next action:" in result.stderr
    assert lock.read_bytes() == b"live-lock"
    assert dest.read_bytes() == b"already-kept"


def test_rename_failure_names_the_next_action(tmp_path: Path) -> None:
    missing = tmp_path / "absent.lock"
    evidence = tmp_path / "evidence"
    dest = evidence / "index.lock-fixed"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -euo pipefail; source "$1"; vault_snapshot_apply_reap "$2" "$3" reap "$4"',
            "bash",
            str(SCRIPT),
            str(missing),
            str(evidence),
            str(dest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "lock rename failed" in result.stderr
    assert "Next action:" in result.stderr
    assert not dest.exists()


def test_missing_bare_mirror_names_the_next_action(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        {
            "VAULT_SNAPSHOT_LOCAL_REPO": str(repo),
            "VAULT_SNAPSHOT_BARE": str(tmp_path / "missing.git"),
            "HOME": str(tmp_path),
        }
    )
    result = subprocess.run(
        ["bash", "-c", 'set -euo pipefail; source "$1"; main', "bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode != 0
    assert "FATAL: bare mirror missing" in result.stdout
    assert "Next action:" in result.stdout


def test_second_reap_does_not_overwrite_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    first = tmp_path / "a.lock"
    second = tmp_path / "b.lock"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    env = {"SOURCE_DATE_EPOCH": ""}
    moved_a = _bash(f"vault_snapshot_apply_reap {first} {evidence} reap", env)
    moved_b = _bash(f"vault_snapshot_apply_reap {second} {evidence} reap", env)
    assert Path(moved_a).read_bytes() == b"first"
    assert Path(moved_b).read_bytes() == b"second"
    assert moved_a != moved_b


def test_scanner_counts_a_live_git_in_the_repo_and_ignores_another(tmp_path: Path) -> None:
    here = tmp_path / "here"
    there = tmp_path / "there"
    here.mkdir()
    there.mkdir()
    subprocess.run(["git", "init"], cwd=here, check=True, capture_output=True)
    subprocess.run(["git", "init"], cwd=there, check=True, capture_output=True)
    holder = subprocess.Popen(
        ["git", "-C", str(here), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
    )
    other = subprocess.Popen(
        ["git", "-C", str(there), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
    )
    try:
        count_here = int(
            _bash(f"vault_snapshot_count_git_holders {here} {here / '.git' / 'index.lock'}")
        )
        count_there_only = int(
            _bash(f"vault_snapshot_count_git_holders {there} {there / '.git' / 'index.lock'}")
        )
        assert count_here >= 1
        assert count_there_only >= 1
        assert _decision(5000, 1200, count_here, "clear") == "keep local-holder"
    finally:
        holder.kill()
        other.kill()
        holder.wait(timeout=5)
        other.wait(timeout=5)


def _fake_ssh(bin_dir: Path, count: str, rc: int = 0) -> None:
    bin_dir.mkdir()
    script = bin_dir / "ssh"
    script.write_text(f"#!/bin/sh\nprintf '%s\\n' '{count}'\nexit {rc}\n")
    script.chmod(0o755)


def _run_main(
    tmp_path: Path, *, lock_age_s: int, ssh_count: str, ssh_rc: int = 0
) -> subprocess.CompletedProcess[str]:
    repo = tmp_path / "repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    lock = git_dir / "index.lock"
    lock.write_bytes(b"stale-or-fresh")
    now = int(lock.stat().st_mtime)
    os.utime(lock, (now - lock_age_s, now - lock_age_s))
    bin_dir = tmp_path / "bin"
    _fake_ssh(bin_dir, ssh_count, ssh_rc)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["HOME"] = str(tmp_path)
    env["VAULT_SNAPSHOT_LOCAL_REPO"] = str(repo)
    env["VAULT_SNAPSHOT_BARE"] = str(tmp_path / "missing.git")
    env["VAULT_SNAPSHOT_INTERVAL_SEC"] = "1200"
    env["VAULT_SNAPSHOT_LOCK_EVIDENCE"] = str(tmp_path / "evidence")
    return subprocess.run(
        ["bash", "-c", 'set -euo pipefail; source "$1"; main', "bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_ssh_probe_returns_the_remote_holder_count(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    _fake_ssh(bin_dir, "4")
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -euo pipefail; source "$1"; vault_snapshot_remote_git_count /repo /repo/.git/index.lock podium',
            "bash",
            str(SCRIPT),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "4"


def test_main_keeps_a_fresh_lock(tmp_path: Path) -> None:
    result = _run_main(tmp_path, lock_age_s=10, ssh_count="0")
    lock = tmp_path / "repo" / ".git" / "index.lock"
    assert result.returncode != 0
    assert lock.read_bytes() == b"stale-or-fresh"
    assert "keep young" in result.stdout


def test_main_keeps_a_lock_when_the_ssh_probe_reports_a_holder(tmp_path: Path) -> None:
    result = _run_main(tmp_path, lock_age_s=5000, ssh_count="3")
    lock = tmp_path / "repo" / ".git" / "index.lock"
    assert result.returncode != 0
    assert lock.read_bytes() == b"stale-or-fresh"
    assert "keep remote-hold" in result.stdout
    assert not (tmp_path / "evidence").exists()


def test_main_reaps_an_old_lock_when_the_ssh_probe_is_clear(tmp_path: Path) -> None:
    result = _run_main(tmp_path, lock_age_s=5000, ssh_count="0")
    lock = tmp_path / "repo" / ".git" / "index.lock"
    assert result.returncode != 0
    assert not lock.exists()
    archived = list((tmp_path / "evidence").iterdir())
    assert len(archived) == 1
    assert archived[0].read_bytes() == b"stale-or-fresh"
    assert "FATAL: bare mirror missing" in result.stdout


def test_main_keeps_a_lock_when_the_ssh_probe_is_unreachable(tmp_path: Path) -> None:
    result = _run_main(tmp_path, lock_age_s=5000, ssh_count="", ssh_rc=1)
    lock = tmp_path / "repo" / ".git" / "index.lock"
    assert result.returncode != 0
    assert lock.read_bytes() == b"stale-or-fresh"
    assert "keep remote-unreachable" in result.stdout


def test_unit_sends_failures_to_the_shipped_notify_failure_template() -> None:
    service = (REPO / "systemd" / "units" / "vault-git-snapshot.service").read_text()
    template = (REPO / "systemd" / "units" / "notify-failure@.service").read_text()
    assert "OnFailure=notify-failure@%n.service" in service
    assert "scripts/vault-git-snapshot" in service
    assert "hapax-p0-incident-intake service-failed %i" in template
