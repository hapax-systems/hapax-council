"""hapax-coord-feed-mirror unit contract — the mirror must never clobber the ledger.

Row `coord-ledger-appendix-mirror-destroys-local-appends-20260925`: the
podium→appendix feed mirror ran as an exclude-list (`--exclude=grants/
--exclude=grant-key`), so `rsync -a` replaced `ledger.db` (and its WAL pair)
whenever a local append changed size or mtime. One transfer silently discards
every local canonical commit and leaves the writer failing `disk I/O error`
indefinitely while `integrity_check` reports ok (E2 §3 of
`frame/append-only-logs-20260925`; predicted by
`relay/inflections/20260810-coord-mirror-destroys-the-ledger-it-mirrors.md`).
The unit's own comment names the payload — the FEED plane — so the payload is
the allowlist, and both units are tracked here instead of living only in
`~/.config/systemd/user/` (the 2026-08-04 grant-plane fix had no review history
for exactly that reason).
"""

from __future__ import annotations

import fnmatch
import os
import shlex
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
SERVICE = UNITS_DIR / "hapax-coord-feed-mirror.service"
TIMER = UNITS_DIR / "hapax-coord-feed-mirror.timer"

FEED_FILES = (
    "sdlc-vocab.json",
    "review-receipts.json",
    "sdlc-events.jsonl",
    "sdlc-events.shadow.json",
)
NEVER_MIRRORED = (
    "ledger.db",
    "ledger.db-wal",
    "ledger.db-shm",
    "ledger.jsonl",
    "dispatch.sqlite",
    "grant-key",
    "spool",
    "grants",
    "static-root",
    "task-locks",
)
# rsync's quick check compares mtimes at whole-second granularity on this host's
# build (measured 2026-09-25): a frozen source must be explicitly OLDER than the
# destination by more than a second or the replace under test never happens.
FROZEN_MTIME = 1785683400  # 2026-08-01T04:10:00Z — the production frozen ledger


def _exec_start_tokens(path: Path) -> list[str]:
    """The unit's ExecStart as tokens (handles `\\` line continuations)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    in_section = False
    values: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == "[Service]"
            i += 1
            continue
        if in_section and stripped and not stripped.startswith(("#", ";")):
            key, _, value = stripped.partition("=")
            if key.strip() == "ExecStart":
                while value.rstrip().endswith("\\") and i + 1 < len(lines):
                    value = value.rstrip()[:-1] + " "
                    i += 1
                    value += lines[i].strip()
                values.append(value)
        i += 1
    assert len(values) == 1, f"expected exactly one ExecStart in {path}"
    return shlex.split(values[0])


def _rsync_filter_rules(tokens: list[str]) -> list[tuple[str, str]]:
    """The unit's rsync include/exclude rules, in order (first match wins)."""
    rules: list[tuple[str, str]] = []
    for token in tokens:
        if token.startswith("--include="):
            rules.append(("include", token.partition("=")[2]))
        elif token.startswith("--exclude="):
            rules.append(("exclude", token.partition("=")[2]))
    return rules


def _rule_allows(rules: list[tuple[str, str]], name: str) -> bool:
    """Minimal rsync leaf-name filter semantics for this unit's pattern shapes.

    All patterns here are bare names (`*` never needs to cross `/`): the first
    matching rule decides; no match means included. An excluded directory is
    never recursed into, which the `*` catch-all guarantees for every
    subdirectory of the coord tree.
    """
    for action, pattern in rules:
        if fnmatch.fnmatchcase(name, pattern):
            return action == "include"
    return True


def test_feed_mirror_units_are_tracked() -> None:
    assert SERVICE.exists(), "hapax-coord-feed-mirror.service must be tracked in systemd/units/"
    assert TIMER.exists(), "hapax-coord-feed-mirror.timer must be tracked in systemd/units/"


def test_feed_mirror_exec_start_is_an_allowlist() -> None:
    tokens = _exec_start_tokens(SERVICE)
    assert tokens[0].endswith("rsync")
    rules = _rsync_filter_rules(tokens)
    assert rules, "the mirror must carry explicit filter rules"
    # The catch-all exclude is what makes this an allowlist.
    assert ("exclude", "*") in rules
    for feed in FEED_FILES:
        assert ("include", feed) in rules, f"feed payload {feed} must be included"
    # The 2026-08-04 escape-authorization incident stays excluded through the
    # catch-all: grants/ and grant-key need no named rule once it exists.
    for feed in FEED_FILES:
        assert _rule_allows(rules, feed), f"{feed} must transfer"
    for name in NEVER_MIRRORED:
        assert not _rule_allows(rules, name), f"{name} must never transfer"


def _make_frozen_ledger(path: Path, rows: int) -> None:
    """A checkpointed ledger with a drained WAL, as the frozen source host holds."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE coord_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event_id TEXT UNIQUE)"
    )
    for i in range(rows):
        conn.execute("INSERT INTO coord_events (event_id) VALUES (?)", (f"frozen-{i}",))
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    # The source keeps an empty WAL file on disk (as production's frozen copy does).
    (path.parent / f"{path.name}-wal").touch()


def _open_local_ledger(path: Path, rows: int, local_rows: int) -> sqlite3.Connection:
    """A ledger with a LIVE writer: local commits sit in the WAL uncheckpointed."""
    _make_frozen_ledger(path, rows)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    for i in range(local_rows):
        conn.execute("INSERT INTO coord_events (event_id) VALUES (?)", (f"local-{i}",))
    conn.commit()
    return conn  # caller holds it open across the mirror run


def _row_count(path: Path) -> int:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM coord_events").fetchone()[0])
    finally:
        conn.close()


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
def test_mirror_run_does_not_clobber_a_local_wal(tmp_path: Path) -> None:
    """The unit's own rsync args, run for real, must not touch a live local WAL.

    Source simulates podium (frozen at the August mtime, drained 0-byte WAL);
    destination simulates appendix with a local canonical writer whose 50
    committed rows live ONLY in `ledger.db-wal` (main db identical in size to
    the source — the quick check's hardest case). This is exactly the shape
    whose replacement destroyed the 2026-09-23/24 appends.
    """
    src = tmp_path / "podium"
    dst = tmp_path / "appendix"
    src.mkdir()
    dst.mkdir()
    _make_frozen_ledger(src / "ledger.db", 3000)
    writer = _open_local_ledger(dst / "ledger.db", 3000, 50)
    try:
        for name in FEED_FILES:
            (src / name).write_text(f'{{"host":"podium","file":"{name}"}}\n', encoding="utf-8")
            (dst / name).write_text(f'{{"host":"stale","file":"{name}"}}\n', encoding="utf-8")
        (dst / "spool").mkdir()
        (dst / "spool" / "intent.jsonl").write_text("{}\n", encoding="utf-8")
        (dst / "grant-key").write_bytes(b"k" * 32)
        for path in src.rglob("*"):
            if path.is_file():
                os.utime(path, (FROZEN_MTIME, FROZEN_MTIME))
        wal_before = (dst / "ledger.db-wal").stat().st_size
        assert wal_before > 0, (
            "the local commits must live in the WAL for this test to mean anything"
        )

        tokens = _exec_start_tokens(SERVICE)
        rules_args = [t for t in tokens if t.startswith(("--include=", "--exclude="))]
        proc = subprocess.run(
            ["rsync", "-a", "--timeout=10", *rules_args, f"{src}/", f"{dst}/"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr

        assert (dst / "ledger.db-wal").stat().st_size == wal_before, "the live WAL is not payload"
        assert writer.execute("SELECT COUNT(*) FROM coord_events").fetchone()[0] == 3050, (
            "local canonical commits must survive a mirror run"
        )
        assert (dst / "spool" / "intent.jsonl").exists(), "the local spool is not mirror payload"
        assert (dst / "grant-key").read_bytes() == b"k" * 32, (
            "the local grant key is not mirror payload"
        )
        for name in FEED_FILES:
            assert "podium" in (dst / name).read_text(encoding="utf-8"), f"{name} must refresh"
    finally:
        writer.close()
