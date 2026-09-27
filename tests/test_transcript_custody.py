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


def test_forget_protection_rule() -> None:
    policy = [
        "forget",
        "--group-by",
        "host,tags",
        "--keep-within",
        "120d",
        "--keep-daily",
        "7",
        "--prune",
    ]
    assert not tc.forget_protects_transcripts(policy)
    assert tc.forget_protects_transcripts([*policy, *tc.KEEP_TRANSCRIPTS_ARGS])
    assert tc.forget_protects_transcripts([*policy, "--keep-tag=tier1-transcripts"])
    assert tc.forget_protects_transcripts([*policy, "--tag", "tier1-local"])
    assert not tc.forget_protects_transcripts([*policy, "--tag", "tier1-transcripts"])
    assert not tc.forget_protects_transcripts(
        [*policy, "--tag", "tier1-local", "--tag", "tier1-transcripts"]
    )


_REPO = Path(__file__).resolve().parents[1]
_FORGET = __import__("re").compile(r"\b(?:restic|run_restic)\s+forget\b")


def _forget_invocations() -> list[tuple[str, list[str]]]:
    """Every ``restic forget`` command in the tree's scripts and units, with its continuation lines joined."""

    found = []
    for base in ("scripts", "systemd", "agents", "shared"):
        for path in sorted((_REPO / base).rglob("*")):
            if (
                not path.is_file()
                or path.suffix in {".pyc", ".md"}
                or path.name == "transcript_custody.py"
            ):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(lines):
                if not _FORGET.search(line) or line.lstrip().startswith("#"):
                    continue
                command = [line.rstrip("\\").strip()]
                j = i
                while lines[j].rstrip().endswith("\\") and j + 1 < len(lines):
                    j += 1
                    command.append(lines[j].rstrip("\\").strip())
                found.append((f"{path.relative_to(_REPO)}:{i + 1}", " ".join(command).split()))
    return found


def test_no_forget_in_the_tree_can_prune_transcript_snapshots() -> None:
    # Seat ruling 2026-09-27: tier1-transcripts is never pruned. This fails the moment any forget policy in the
    # tree could match the tag.
    invocations = _forget_invocations()
    assert invocations, "the scan found no forget invocations; the scan itself is broken"
    unsafe = [where for where, args in invocations if not tc.forget_protects_transcripts(args)]
    assert unsafe == [], f"forget policies that could prune {tc.SNAPSHOT_TAG}: {unsafe}"


def test_backup_refuses_an_empty_path_list() -> None:
    with pytest.raises(ValueError):
        tc.backup_args([])


CLI = _REPO / "scripts" / "hapax-transcript-custody"


def _on_own_mount(path: Path) -> bool:
    cur = path.resolve()
    while not os.path.ismount(cur):
        cur = cur.parent
    return str(cur) != "/"


def _cli_env(tmp_path: Path, home: Path) -> dict[str, str]:
    return dict(
        os.environ,
        HOME=str(home),
        RESTIC_REPOSITORY=str(tmp_path / "repo"),
        RESTIC_PASSWORD="test-only",
        RESTIC_CACHE_DIR=str(tmp_path / "cache"),
        PYTHONPATH=str(_REPO),
    )


def _cli(env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    import sys

    return subprocess.run(
        [sys.executable, str(CLI), *args], env=env, capture_output=True, text=True, timeout=300
    )


@pytest.mark.skipif(shutil.which("restic") is None, reason="restic is not installed on this host")
def test_cli_backup_then_verify_end_to_end(tmp_path: Path) -> None:
    """The unit's two commands, through the CLI: a clean snapshot verifies (exit 0); a later snapshot that lost
    most of a path's files fails verify (exit 1) with the drop named."""

    if not _on_own_mount(tmp_path):
        pytest.skip("the temp directory is on the root filesystem, which the CLI rightly refuses")
    home = _home(tmp_path)
    for i in range(3, 9):
        (home / f".claude/projects/p1/s{i}.jsonl").write_text('{"type":"user"}\n')
    env = _cli_env(tmp_path, home)
    subprocess.run(["restic", "init"], env=env, capture_output=True, check=True, timeout=120)

    assert _cli(env, "backup").returncode == 0
    ok = _cli(env, "verify")
    assert ok.returncode == 0, ok.stderr
    assert "holds every transcript path" in ok.stdout

    for i in range(2, 9):  # 8 files -> 1: more than half lost
        (home / f".claude/projects/p1/s{i}.jsonl").unlink()
    assert _cli(env, "backup").returncode == 0
    bad = _cli(env, "verify")
    assert bad.returncode == 1
    assert "dropped:" in bad.stderr and ".claude/projects" in bad.stderr


@pytest.mark.skipif(shutil.which("restic") is None, reason="restic is not installed on this host")
def test_cli_verify_fails_a_snapshot_with_a_stray_credential_target(tmp_path: Path) -> None:
    """Every transcript path present and healthy, plus one extra target that is a credential file: verify must
    fail, because the predicate is "no credential in the snapshot", not "none under the expected paths"."""

    if not _on_own_mount(tmp_path):
        pytest.skip("the temp directory is on the root filesystem, which the CLI rightly refuses")
    home = _home(tmp_path)
    env = _cli_env(tmp_path, home)
    subprocess.run(["restic", "init"], env=env, capture_output=True, check=True, timeout=120)
    stray = tmp_path / "elsewhere" / "auth.json"
    stray.parent.mkdir()
    stray.write_text('{"token":"not-a-real-secret"}')
    real_paths = [p.real for p in tc.resolve_paths(home).paths]
    # The same tag and host as the unit's snapshots, with the credential passed as an extra target (no excludes).
    subprocess.run(
        ["restic", "backup", "--tag", tc.SNAPSHOT_TAG, *real_paths, str(stray)],
        env=env,
        capture_output=True,
        check=True,
        timeout=120,
    )
    result = _cli(env, "verify")
    assert result.returncode == 1
    assert "credential: the snapshot holds" in result.stderr and "auth.json" in result.stderr


def test_cli_inventory_json_and_problem_exit(tmp_path: Path) -> None:
    home = _home(tmp_path)
    env = _cli_env(tmp_path, home)
    ok = _cli(env, "inventory", "--json")
    assert ok.returncode == 0, ok.stderr
    rows = {r["real"]: r for r in json.loads(ok.stdout)["paths"]}
    codex = str(tmp_path / "data2/agent-state/codex/sessions")
    assert rows[codex]["files"] == 1 and rows[codex]["via_symlink"] is True
    assert rows[str(home / ".claude/projects")]["files"] == 2
    # a dangling symlink is a problem: exit 1, reported
    shutil.rmtree(tmp_path / "data2")
    bad = _cli(env, "inventory", "--json")
    assert bad.returncode == 1
    assert any("dangling" in p for p in json.loads(bad.stdout)["problems"])


@pytest.mark.skipif(shutil.which("restic") is None, reason="restic is not installed on this host")
def test_cli_refuses_a_missing_repository(tmp_path: Path) -> None:
    env = _cli_env(tmp_path, _home(tmp_path))  # no `restic init`: an unmounted NAS looks like this
    result = _cli(env, "backup")
    assert result.returncode != 0
    assert "no restic repository" in result.stderr


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
