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
    return _bash(
        f"vault_snapshot_reap_decision {age} {interval} {local} {remote}"
    )


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
    moved = _bash(
        f"vault_snapshot_apply_reap {lock} {evidence} reap"
    )
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
            _bash(
                f"vault_snapshot_count_git_holders {there} {there / '.git' / 'index.lock'}"
            )
        )
        assert count_here >= 1
        assert count_there_only >= 1
        assert _decision(5000, 1200, count_here, "clear") == "keep local-holder"
    finally:
        holder.kill()
        other.kill()
        holder.wait(timeout=5)
        other.wait(timeout=5)


def test_unit_sends_failures_to_incident_intake() -> None:
    text = (REPO / "systemd" / "units" / "vault-git-snapshot.service").read_text()
    assert "OnFailure=notify-failure@%n.service" in text
    assert "scripts/vault-git-snapshot" in text
