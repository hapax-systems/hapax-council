"""Transcript custody: the path table, real-path resolution, credential exclusion and the post-backup verifier.

The four cases the p0 row names (transcript-backup-custody-all-harnesses-20260927, M174) each have a test here: an
empty-directory capture fails; a symlink included instead of its target fails; a dropped harness path fails; credential
files are excluded. The last test runs the whole path through a real restic repository, and skips where restic is
not installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from scripts import transcript_custody as tc


def _home(tmp_path: Path) -> Path:
    """A fake home: Claude and Grok stores in place, Codex's store behind a symlink (podium's layout)."""

    home = tmp_path / "home"
    (home / ".claude/projects/p1").mkdir(parents=True)
    (home / ".claude/projects/p1/s1.jsonl").write_text('{"type":"user"}\n')
    (home / ".claude/projects/p1/s2.jsonl").write_text('{"type":"user"}\n')
    (home / ".grok/sessions/x").mkdir(parents=True)
    (home / ".grok/sessions/x/updates.jsonl").write_text("{}\n")
    (home / ".grok/sessions/x/auth.json").write_text('{"token":"not-a-real-secret"}')
    store = tmp_path / "data2/agent-state/codex"
    (store / "sessions/2026").mkdir(parents=True)
    (store / "sessions/2026/rollout-1.jsonl").write_text("{}\n")
    (home / ".codex").symlink_to(store)
    return home


def _nodes(files: dict[str, str]) -> list[dict]:
    """A restic ls --json node stream: the path itself, then its files."""

    return [{"struct_type": "node", "path": p, "type": t} for p, t in files.items()]


def test_resolve_includes_the_real_path_not_the_symlink(tmp_path: Path) -> None:
    res = tc.resolve_paths(_home(tmp_path))
    codex = [p for p in res.paths if p.harness == "codex"]
    assert [p.real for p in codex] == [str(tmp_path / "data2/agent-state/codex/sessions")]
    assert codex[0].via_symlink is True
    assert all(not Path(p.real).is_symlink() for p in res.paths)
    assert "--exclude" in tc.backup_args(res.paths)
    assert str(_home_path(tmp_path, ".codex/sessions")) not in tc.backup_args(res.paths)


def _home_path(tmp_path: Path, rel: str) -> Path:
    return tmp_path / "home" / rel


def test_a_dangling_symlink_is_a_problem_not_a_silent_skip(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".codex").symlink_to(tmp_path / "gone")
    (tmp_path / "gone").mkdir()
    (home / ".codex/sessions").mkdir()
    shutil.rmtree(tmp_path / "gone")
    res = tc.resolve_paths(home)
    assert res.paths == []
    assert res.problems and "dangling" in res.problems[0]


def test_empty_directory_capture_fails(tmp_path: Path) -> None:
    # M174: the directory is in the snapshot, but none of its files are.
    rp = tc.ResolvedPath("claude", "~/.claude/projects", "/h/.claude/projects", "dir", False, 1)
    current = tc.count_snapshot(_nodes({"/h/.claude/projects": "dir"}), [rp.real])
    failures = tc.verify([rp], current, snapshot_targets=[rp.real])
    assert any(f.startswith("empty:") for f in failures), failures


def test_symlink_included_instead_of_its_target_fails(tmp_path: Path) -> None:
    rp = tc.ResolvedPath("codex", "~/.codex/sessions", "/h/.codex/sessions", "dir", False, 1)
    current = tc.count_snapshot(_nodes({"/h/.codex/sessions": "symlink"}), [rp.real])
    failures = tc.verify([rp], current, snapshot_targets=[rp.real])
    assert any(f.startswith("symlink:") for f in failures), failures
    # A snapshot target that is a symlink fails even when the host no longer lists it.
    failures = tc.verify([], current, snapshot_targets=[rp.real])
    assert any(f.startswith("symlink:") for f in failures), failures


def test_a_dropped_harness_path_fails(tmp_path: Path) -> None:
    claude = tc.ResolvedPath("claude", "~/.claude/projects", "/h/.claude/projects", "dir", False, 1)
    codex = tc.ResolvedPath("codex", "~/.codex/sessions", "/h/.codex/sessions", "dir", False, 1)
    nodes = _nodes({claude.real: "dir", f"{claude.real}/s.jsonl": "file"})
    current = tc.count_snapshot(nodes, [claude.real, codex.real])
    # The previous snapshot held Codex; this one does not.
    failures = tc.verify(
        [claude],
        current,
        snapshot_targets=[claude.real],
        previous_targets=[claude.real, codex.real],
    )
    assert any(f.startswith("harness path dropped:") and codex.real in f for f in failures), (
        failures
    )
    # A path on the host that the snapshot lacks fails too.
    failures = tc.verify([claude, codex], current, snapshot_targets=[claude.real])
    assert any(f.startswith("missing:") and codex.real in f for f in failures), failures


def test_a_large_drop_against_the_previous_snapshot_fails() -> None:
    rp = tc.ResolvedPath("claude", "~/.claude/projects", "/h/p", "dir", False, 1)
    prev = {rp.real: tc.PathCount(rp.real, "dir", 100)}
    cur = {rp.real: tc.PathCount(rp.real, "dir", 40)}
    assert any(
        f.startswith("dropped:")
        for f in tc.verify([rp], cur, snapshot_targets=[rp.real], previous=prev)
    )
    cur_ok = {rp.real: tc.PathCount(rp.real, "dir", 60)}
    assert tc.verify([rp], cur_ok, snapshot_targets=[rp.real], previous=prev) == []


def test_credential_files_are_excluded_and_a_snapshot_holding_one_fails() -> None:
    args = tc.backup_args(
        [tc.ResolvedPath("grok", "~/.grok/sessions", "/h/.grok/sessions", "dir", False, 1)]
    )
    excluded = {args[i + 1] for i, a in enumerate(args) if a == "--exclude"}
    assert {"auth.json", ".credentials.json", "oauth_creds.json", ".env"} <= excluded
    rp = tc.ResolvedPath("grok", "~/.grok/sessions", "/h/.grok/sessions", "dir", False, 1)
    nodes = _nodes(
        {rp.real: "dir", f"{rp.real}/x/updates.jsonl": "file", f"{rp.real}/x/auth.json": "file"}
    )
    failures = tc.verify([rp], tc.count_snapshot(nodes, [rp.real]), snapshot_targets=[rp.real])
    assert any(f.startswith("credential:") for f in failures), failures


def test_a_clean_snapshot_passes() -> None:
    rp = tc.ResolvedPath("claude", "~/.claude/projects", "/h/p", "dir", False, 1)
    nodes = _nodes({rp.real: "dir", f"{rp.real}/a.jsonl": "file", f"{rp.real}/b.jsonl": "file"})
    current = tc.count_snapshot(nodes, [rp.real])
    assert current[rp.real].files == 2
    assert tc.verify([rp], current, snapshot_targets=[rp.real]) == []


def test_backup_refuses_an_empty_path_list() -> None:
    with pytest.raises(ValueError):
        tc.backup_args([])


@pytest.mark.skipif(shutil.which("restic") is None, reason="restic is not installed on this host")
def test_real_restic_round_trip(tmp_path: Path) -> None:
    """Back up a fake home into a throwaway repository, then verify the snapshot with the real listing.

    The good snapshot passes and holds no credential. A snapshot of the symlink (the M174 mechanism) fails.
    """

    home = _home(tmp_path)
    env = dict(
        os.environ,
        RESTIC_REPOSITORY=str(tmp_path / "repo"),
        RESTIC_PASSWORD="test-only",
        RESTIC_CACHE_DIR=str(tmp_path / "cache"),
    )

    def restic(*args: str) -> str:
        return subprocess.run(
            ["restic", *args], env=env, capture_output=True, text=True, check=True, timeout=120
        ).stdout

    restic("init")
    res = tc.resolve_paths(home)
    restic(*tc.backup_args(res.paths))
    snap = json.loads(restic("snapshots", "--json"))[-1]
    nodes = [
        json.loads(line) for line in restic("ls", "--json", snap["id"]).splitlines() if line.strip()
    ]
    counts = tc.count_snapshot(nodes, [p.real for p in res.paths])
    assert tc.verify(res.paths, counts, snapshot_targets=snap["paths"]) == []
    assert not any(n.get("name") == "auth.json" for n in nodes)

    # The M174 shape: back up the symlink itself instead of its target.
    link = str(home / ".codex")
    restic("backup", "--tag", "bad", link)
    bad = [s for s in json.loads(restic("snapshots", "--json")) if "bad" in (s.get("tags") or [])][
        -1
    ]
    bad_nodes = [
        json.loads(line) for line in restic("ls", "--json", bad["id"]).splitlines() if line.strip()
    ]
    failures = tc.verify([], tc.count_snapshot(bad_nodes, [link]), snapshot_targets=bad["paths"])
    assert any(f.startswith("symlink:") for f in failures), failures
