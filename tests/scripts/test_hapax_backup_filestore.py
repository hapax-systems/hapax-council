"""hapax-backup-filestore: this host's FileStore into the tier-1 NAS restic repository, verified by path listing.

Row filestore-secrets-backup-custody-all-hosts-20260927 (seat design ruling 2026-09-27 14:21Z). The tests run the
real script against a throwaway restic repository (skipped where restic or jq is absent). Every fixture blob holds a
sentinel value that must never appear in the output: the script reads names only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-backup-filestore"
UNITS = REPO_ROOT / "systemd" / "units"
SENTINEL = "SENTINEL-NOT-A-REAL-SECRET"

pytestmark = pytest.mark.skipif(
    shutil.which("restic") is None or shutil.which("jq") is None, reason="restic or jq is absent"
)


def _mount_of(path: Path) -> str:
    return subprocess.run(
        ["findmnt", "-n", "-o", "TARGET", "--target", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()[-1]


def _setup(
    tmp_path: Path, *, entries: int = 3, secret: str = "printf 'test-only\\n'\n"
) -> dict[str, str]:
    store = tmp_path / "secrets"
    store.mkdir()
    (store / ".key").write_text(SENTINEL + "-key", encoding="utf-8")
    for i in range(entries):
        (store / f"entry-{i}.bin").write_text(f"{SENTINEL}-{i}", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "hapax-secret").write_text("#!/usr/bin/env bash\n" + secret, encoding="utf-8")
    (bin_dir / "hapax-secret").chmod(0o755)
    repo = tmp_path / "repo"
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        REINS_SECRET_STORE=str(store),
        RESTIC_REPOSITORY=str(repo),
        RESTIC_CACHE_DIR=str(tmp_path / "cache"),
        HAPAX_FILESTORE_REPOSITORY_MOUNT=_mount_of(tmp_path),
    )
    subprocess.run(
        ["restic", "init"],
        env=dict(env, RESTIC_PASSWORD="test-only"),
        capture_output=True,
        check=True,
        timeout=120,
    )
    return env


def _run(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run([str(SCRIPT)], env=env, capture_output=True, text=True, timeout=300)


def _snapshots(env: dict[str, str]) -> list[dict]:
    out = subprocess.run(
        ["restic", "snapshots", "--json"],
        env=dict(env, RESTIC_PASSWORD="test-only"),
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout
    return json.loads(out) or []


def test_backs_up_and_verifies_the_store_by_names_only(tmp_path: Path) -> None:
    env = _setup(tmp_path)
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert (
        f"holds {env['REINS_SECRET_STORE']}/.key and 3 of 3 entries (names only)" in result.stdout
    )
    assert SENTINEL not in result.stdout + result.stderr
    (snap,) = _snapshots(env)
    assert snap["tags"] == ["tier1-filestore"] and snap["paths"] == [env["REINS_SECRET_STORE"]]


@pytest.mark.parametrize(
    ("break_it", "reason"),
    [
        ("store", "no FileStore at"),
        ("repo", "no restic repository at"),
        ("mount", "not on the required mount"),
    ],
)
def test_refuses_before_writing(tmp_path: Path, break_it: str, reason: str) -> None:
    env = _setup(tmp_path)
    if break_it == "store":
        (Path(env["REINS_SECRET_STORE"]) / ".key").unlink()
    elif break_it == "repo":
        env["RESTIC_REPOSITORY"] = str(tmp_path / "no-such-repo")
    else:
        env["HAPAX_FILESTORE_REPOSITORY_MOUNT"] = "/mnt/nas/backups"
    result = _run(env)
    assert result.returncode == 1
    assert reason in result.stderr and "next action" in result.stderr
    if break_it != "repo":
        assert _snapshots(env) == []


@pytest.mark.parametrize(
    ("secret", "reason"),
    [("exit 1\n", "cannot read the restic password"), ("printf ''\n", "is empty")],
)
def test_an_unreadable_or_empty_password_writes_nothing(
    tmp_path: Path, secret: str, reason: str
) -> None:
    env = _setup(tmp_path, secret=secret)
    result = _run(env)
    assert result.returncode == 1 and reason in result.stderr
    assert _snapshots(env) == []


def _restic_that_drops(tmp_path: Path, env: dict[str, str], pattern: str) -> dict[str, str]:
    """A restic on PATH that passes everything through to the real one, except that `ls` drops lines matching
    ``pattern``: a snapshot that lost entries, as the verify must see it."""

    real = shutil.which("restic")
    wrap = tmp_path / "wrap"
    wrap.mkdir()
    (wrap / "restic").write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = ls ]; then "{real}" "$@" | grep -vE \'{pattern}\'; exit "${{PIPESTATUS[0]}}"; fi\n'
        f'exec "{real}" "$@"\n',
        encoding="utf-8",
    )
    (wrap / "restic").chmod(0o755)
    return dict(env, PATH=f"{wrap}:{env['PATH']}")


def test_verify_fails_when_the_snapshot_lacks_an_entry(tmp_path: Path) -> None:
    env = _restic_that_drops(tmp_path, _setup(tmp_path), r"entry-1\.bin")
    result = _run(env)
    assert result.returncode == 1
    assert "holds 2 entries, fewer than the store's 3" in result.stderr


def test_verify_fails_when_the_snapshot_lacks_the_key(tmp_path: Path) -> None:
    env = _restic_that_drops(tmp_path, _setup(tmp_path), r"/\.key\"")
    result = _run(env)
    assert result.returncode == 1
    assert "does not hold" in result.stderr and ".key" in result.stderr


def test_the_script_reads_no_value_and_prunes_nothing() -> None:
    """Names only: nothing in the script opens a blob; and no forget here, since retention is podium's tier-1 forget
    (--group-by host,tags), so the tree-wide never-prune scan is unchanged."""

    text = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for reader in ("cat ", "head ", "tail -c", "xxd", ' < "$STORE', 'hapax-secret "$'):
        assert reader not in code, reader
    assert "restic forget" not in code


def test_the_unit_runs_the_activation_worktree_and_the_timer_is_daily() -> None:
    unit = (UNITS / "hapax-backup-filestore.service").read_text(encoding="utf-8")
    assert (
        "ExecStart=%h/.cache/hapax/source-activation/worktree/scripts/hapax-backup-filestore\n"
        in unit
    )
    assert "Environment=HAPAX_FILESTORE_REPOSITORY_MOUNT=/mnt/nas/backups\n" in unit
    assert "OnFailure=notify-failure@%n.service\n" in unit
    timer = (UNITS / "hapax-backup-filestore.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 04:45:00\n" in timer and "Persistent=true\n" in timer
