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
# restic (or the run_restic wrapper), then its statement; a statement holding the forget subcommand is a forget.
_RESTIC = __import__("re").compile(r"\b(?:restic|run_restic)\b")
_FORGET = __import__("re").compile(r"\bforget\b")


def _statement(text: str, start: int) -> str:
    """The command that starts at ``start``: it runs on across a newline while a bracket opened after ``start`` is
    still open, or the line ends in a backslash, a comma or an opening bracket (a multi-line argv list). A closing
    bracket that ``start`` did not open ends it (the enclosing list or call closed)."""

    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                break
        elif ch == "\n" and depth == 0:
            if not text[start:i].rstrip().endswith(("\\", ",", "(", "[", "{")):
                break
        i += 1
    return text[start:i]


def _forget_commands(text: str) -> list[tuple[int, list[str]]]:
    """Every ``restic … forget`` command in ``text``, as (1-based line, argument tokens): global options between
    restic and forget, backslash continuations and multi-line Python argv lists included, comments excluded. Quotes,
    commas and brackets are stripped from the tokens."""

    found = []
    for match in _RESTIC.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        if "#" in text[line_start : match.start()]:
            continue  # a comment (or text after one)
        statement = _statement(text, match.start())
        if not _FORGET.search(statement):
            continue
        tokens = [t.strip("\"',[]()") for t in statement.replace("\\\n", " ").split()]
        found.append(
            (text.count("\n", 0, match.start()) + 1, [t for t in tokens if t and t != "\\"])
        )
    return found


def _tracked_files() -> list[Path]:
    """Every tracked file that can run: the whole tree but tests, docs and Markdown (git ls-files; a plain walk
    when the checkout has no git)."""

    try:
        names = subprocess.run(
            ["git", "-C", str(_REPO), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout.splitlines()
        paths = [_REPO / n for n in names]
    except (OSError, subprocess.SubprocessError):
        paths = [p for p in _REPO.rglob("*") if ".git" not in p.parts and ".venv" not in p.parts]
    return sorted(
        p
        for p in paths
        if p.is_file()
        and p.relative_to(_REPO).parts[0] not in {"tests", "docs"}
        and p.suffix not in {".md", ".pyc"}
        and p.name != "transcript_custody.py"
    )


def _forget_invocations() -> list[tuple[str, list[str]]]:
    """Every ``restic … forget`` command in the tree's tracked, runnable files."""

    found = []
    for path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "forget" not in text:
            continue
        for line, args in _forget_commands(text):
            found.append((f"{path.relative_to(_REPO)}:{line}", args))
    return found


def test_the_forget_scan_sees_every_command_form() -> None:
    """The scan must see global options between restic and forget, the run_restic wrapper, continuation lines, Python
    argv lists on one line or many, and restic and forget on separate lines; it must not match comments."""

    sample = "\n".join(
        [
            'restic -r "$repo" forget --prune --keep-daily 7',  # 1: global option before forget
            "run_restic forget \\",  # 2-3: wrapper, continuation line
            "    --keep-tag tier1-transcripts --prune",
            'subprocess.run(["restic", "--repo", repo, "forget", "--keep-daily", "7"])',  # 4: Python argv
            "# restic forget --prune",  # 5: a comment
            "restic snapshots --json",  # 6: not a forget
            "cmd = [",  # 7-12: a multi-line Python argv list, restic and forget on separate lines
            '    "restic",',
            '    "--repo", repo,',
            '    "forget",',
            '    "--prune",',
            "]",
            "restic \\",  # 13-15: a shell command, restic and forget on separate lines
            '    -r "$repo" \\',
            "    forget --keep-tag=tier1-transcripts --prune",
            'subprocess.run(["restic", "snapshots"], check=True)',  # 16: not a forget
            'print("forget it")',  # 17: forget without restic
        ]
    )
    commands = _forget_commands(sample)
    assert [line for line, _ in commands] == [1, 2, 4, 8, 13]
    assert [tc.forget_protects_transcripts(args) for _, args in commands] == [
        False,
        True,
        False,
        False,
        True,
    ]


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
        HAPAX_TRANSCRIPT_WINDOWS_PULLER="",  # no Windows pull unless a test asks for one
        HAPAX_TRANSCRIPT_WINDOWS_HOSTS="",
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


@pytest.mark.skipif(shutil.which("restic") is None, reason="restic is not installed on this host")
def test_cli_verify_fails_when_the_newest_snapshot_is_not_from_this_run(tmp_path: Path) -> None:
    """Verify is bound to this run's snapshot: if the newest one is two days old (tonight's backup took none),
    a healthy old snapshot must not pass as tonight's."""

    if not _on_own_mount(tmp_path):
        pytest.skip("the temp directory is on the root filesystem, which the CLI rightly refuses")
    home = _home(tmp_path)
    env = _cli_env(tmp_path, home)
    subprocess.run(["restic", "init"], env=env, capture_output=True, check=True, timeout=120)
    backdated = tc.backup_args(tc.resolve_paths(home).paths) + ["--time", "2020-01-01 04:15:00"]
    subprocess.run(["restic", *backdated], env=env, capture_output=True, check=True, timeout=120)
    stale = _cli(env, "verify")
    assert stale.returncode == 1
    assert "stale: the newest tier1-transcripts snapshot" in stale.stderr
    assert _cli(env, "verify", "--max-age-hours", "1e9").returncode == 0


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


def test_cli_inventory_reports_a_nested_symlink(tmp_path: Path) -> None:
    """A transcript subtree reached through a symlink inside a table path would be backed up as the link: the
    inventory names it and exits 1."""

    home = _home(tmp_path)
    elsewhere = tmp_path / "elsewhere-sessions"
    elsewhere.mkdir()
    (elsewhere / "s9.jsonl").write_text("{}\n")
    (home / ".claude/projects/p2").symlink_to(elsewhere)
    result = _cli(_cli_env(tmp_path, home), "inventory", "--json")
    assert result.returncode == 1
    out = json.loads(result.stdout)
    assert any("nested symlink" in p and "p2" in p for p in out["problems"])
    assert {r["real"]: r for r in out["paths"]}[str(home / ".claude/projects")][
        "nested_symlinks"
    ] == 1


def test_a_nested_symlink_in_the_snapshot_fails() -> None:
    rp = tc.ResolvedPath("claude", "~/.claude/projects", "/h/.claude/projects", "dir", False, 1)
    nodes = _nodes(
        {
            "/h/.claude/projects": "dir",
            "/h/.claude/projects/p1/s1.jsonl": "file",
            "/h/.claude/projects/p2": "symlink",
        }
    )
    failures = tc.verify([rp], tc.count_snapshot(nodes, [rp.real]), snapshot_targets=[rp.real])
    assert any(f.startswith("nested symlink: /h/.claude/projects") for f in failures)


def test_cli_backup_dry_run_prints_the_restic_command(tmp_path: Path) -> None:
    home = _home(tmp_path)
    result = _cli(_cli_env(tmp_path, home), "backup", "--dry-run")
    assert result.returncode == 0, result.stderr
    argv = json.loads(result.stdout)
    assert argv[:4] == ["restic", "backup", "--tag", tc.SNAPSHOT_TAG]
    exclude = argv.index("auth.json")
    assert argv[exclude - 1 : exclude + 1] == ["--exclude", "auth.json"]
    assert str(tmp_path / "data2/agent-state/codex/sessions") in argv  # the real path, not ~/.codex
    assert str(home / ".codex/sessions") not in argv


def _cli_module():
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader

    loader = SourceFileLoader("hapax_transcript_custody_cli", str(CLI))
    module = module_from_spec(spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def test_cli_refuses_a_repository_on_the_root_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unmounted NAS path falls through to the root filesystem; a repository found there is refused."""

    cli = _cli_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config").write_text("")
    monkeypatch.setattr(cli, "_mount_point", lambda _path: "/")
    with pytest.raises(SystemExit, match="is on the root filesystem"):
        cli._require_repository(str(repo))
    monkeypatch.setattr(cli, "_mount_point", lambda _path: str(tmp_path))
    monkeypatch.delenv("HAPAX_TRANSCRIPT_REPOSITORY_MOUNT", raising=False)
    cli._require_repository(str(repo))  # on its own mount: accepted
    cli._require_repository("rclone:gdrive:somewhere")  # a remote repository is not a local path


def test_cli_refuses_a_repository_off_the_required_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the NAS absent, a repository under another mount (/mnt, say) must not pass: the unit names the mount."""

    cli = _cli_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config").write_text("")
    monkeypatch.setattr(cli, "_mount_point", lambda _path: "/mnt")
    monkeypatch.setenv("HAPAX_TRANSCRIPT_REPOSITORY_MOUNT", "/mnt/nas/backups")
    with pytest.raises(SystemExit, match="not on the required mount /mnt/nas/backups"):
        cli._require_repository(str(repo))
    monkeypatch.setattr(cli, "_mount_point", lambda _path: "/mnt/nas/backups")
    cli._require_repository(str(repo))  # on the named mount: accepted


def test_the_unit_names_the_repository_mount() -> None:
    unit = (_REPO / "systemd/units/hapax-backup-transcripts.service").read_text(encoding="utf-8")
    assert "Environment=HAPAX_TRANSCRIPT_REPOSITORY_MOUNT=/mnt/nas/backups\n" in unit
    assert "Environment=RESTIC_REPOSITORY=/mnt/nas/backups/restic\n" in unit


@pytest.mark.skipif(shutil.which("restic") is None, reason="restic is not installed on this host")
def test_cli_verify_fails_a_nested_symlink_through_real_restic(tmp_path: Path) -> None:
    if not _on_own_mount(tmp_path):
        pytest.skip("the temp directory is on the root filesystem, which the CLI rightly refuses")
    home = _home(tmp_path)
    elsewhere = tmp_path / "elsewhere-sessions"
    elsewhere.mkdir()
    (elsewhere / "s9.jsonl").write_text("{}\n")
    (home / ".claude/projects/p2").symlink_to(elsewhere)
    env = _cli_env(tmp_path, home)
    subprocess.run(["restic", "init"], env=env, capture_output=True, check=True, timeout=120)
    assert _cli(env, "backup").returncode == 0
    result = _cli(env, "verify")
    assert result.returncode == 1
    assert "nested symlink:" in result.stderr and "p2" in result.stderr


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


# --- Windows hosts, pulled over SSH (row transcript-custody-windows-hosts-20260927) ---

# A stand-in for `ssh <options> <host> powershell ... -EncodedCommand <b64>`. It decodes the PowerShell. An inventory
# script is answered from FAKE_PROFILE_<host> as the real one would. A tar script streams a real tar of the named
# paths, honouring --exclude unless the host's mode is "leak". Mode "unreachable" exits 255, as ssh does with no
# connection; mode "cut" writes part of the stream, then exits 1.
_FAKE_SSH = r"""#!/usr/bin/env python3
import base64, fnmatch, json, os, re, sys, tarfile
args = sys.argv[1:]
i = 0
while args[i] == "-o":
    i += 2
host, rest = args[i], args[i + 1:]
key = host.replace("-", "_")
mode = os.environ.get("FAKE_SSH_MODE_" + key, "ok")
with open(os.environ["FAKE_SSH_LOG"], "a") as log:
    log.write(host + "\n")
if mode == "unreachable":
    sys.exit(255)
if mode == "denied":
    sys.stderr.write(host + ": Permission denied (publickey).\n")
    sys.exit(255)
script = base64.b64decode(rest[rest.index("-EncodedCommand") + 1]).decode("utf-16-le")
profile = os.environ["FAKE_PROFILE_" + key]
quoted = lambda text: [q.replace("''", "'") for q in re.findall(r"'((?:[^']|'')*)'", text)]
if "tar.exe" in script:
    excludes = [] if mode == "leak" else quoted(" ".join(re.findall(r"--exclude '(?:[^']|'')*'", script)))
    names = quoted(script.split("-C $env:USERPROFILE", 1)[1])
    out = tarfile.open(fileobj=sys.stdout.buffer, mode="w|")
    keep = lambda ti: None if any(fnmatch.fnmatch(os.path.basename(ti.name), p) for p in excludes) else ti
    for n, name in enumerate(names):
        out.add(os.path.join(profile, name), arcname=name, filter=keep)
        if mode == "cut" and n == 0:
            sys.stdout.buffer.flush()
            sys.exit(1)
    out.close()
    sys.exit(0)
rels = quoted(script.split("foreach ($r in @(", 1)[1].split(")", 1)[0])
rows = []
for rel in rels:
    for full in sorted(__import__("glob").glob(os.path.join(profile, rel))):
        name = os.path.relpath(full, profile).replace(os.sep, "/")
        if os.path.isdir(full) and not os.path.islink(full):
            files = sum(len(f) for _, _, f in os.walk(full))
            rows.append({"rel": name, "kind": "dir", "files": files, "reparse": False})
        else:
            rows.append({"rel": name, "kind": "file", "files": 1, "reparse": os.path.islink(full)})
print(json.dumps(rows[0] if len(rows) == 1 else rows))
"""


def _windows_env(tmp_path: Path, **modes: str) -> tuple[dict[str, str], Path]:
    """A CLI environment in which this host pulls one Windows host, "win-a", through the fake ssh."""

    import socket
    import sys

    home = _home(tmp_path)
    profile = tmp_path / "win-a-profile"
    (profile / ".claude/projects/p1").mkdir(parents=True)
    for i in range(4):
        (profile / f".claude/projects/p1/s{i}.jsonl").write_text('{"type":"user"}\n')
    (profile / ".claude/history.jsonl").write_text("{}\n")
    (profile / ".claude/.credentials.json").write_text('{"token":"not-a-real-secret"}')
    (profile / ".grok/sessions/g1").mkdir(parents=True)
    (profile / ".grok/sessions/g1/updates.jsonl").write_text("{}\n")
    # Inside a streamed path, so only the by-name exclusion keeps it out of the snapshot.
    (profile / ".grok/sessions/g1/auth.json").write_text('{"token":"not-a-real-secret"}')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "ssh"
    fake.write_text(_FAKE_SSH.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1))
    fake.chmod(0o755)
    env = _cli_env(tmp_path, home)
    env.update(
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        HAPAX_TRANSCRIPT_WINDOWS_PULLER=socket.gethostname(),
        HAPAX_TRANSCRIPT_WINDOWS_HOSTS="win-a",
        FAKE_PROFILE_win_a=str(profile),
        FAKE_SSH_LOG=str(tmp_path / "ssh.log"),
        **{f"FAKE_SSH_MODE_{k}": v for k, v in modes.items()},
    )
    subprocess.run(["restic", "init"], env=env, capture_output=True, check=True, timeout=120)
    return env, profile


def _win_snapshots(env: dict[str, str]) -> list[dict]:
    out = subprocess.run(
        ["restic", "snapshots", "--json", "--host", "win-a", "--tag", tc.SNAPSHOT_TAG],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout
    return json.loads(out) or []


_needs_restic = pytest.mark.skipif(shutil.which("restic") is None, reason="restic is not installed")


@_needs_restic
def test_windows_pull_backs_up_and_verifies_without_the_credential(tmp_path: Path) -> None:
    if not _on_own_mount(tmp_path):
        pytest.skip("the temp directory is on the root filesystem, which the CLI rightly refuses")
    env, _ = _windows_env(tmp_path)
    backup = _cli(env, "backup")
    assert backup.returncode == 0, backup.stderr
    (snap,) = _win_snapshots(env)
    assert snap["hostname"] == "win-a" and snap["paths"] == ["/win-a-transcripts.tar"]
    result = _cli(env, "verify")
    assert result.returncode == 0, result.stderr
    assert "win-a snapshot" in result.stdout and "holds every transcript path" in result.stdout
    assert "4 files" in result.stdout and "win-a:~/.claude/projects" in result.stdout


@_needs_restic
def test_windows_credential_in_the_stream_fails_verify(tmp_path: Path) -> None:
    if not _on_own_mount(tmp_path):
        pytest.skip("the temp directory is on the root filesystem, which the CLI rightly refuses")
    env, _ = _windows_env(tmp_path, win_a="leak")
    assert _cli(env, "backup").returncode == 0
    result = _cli(env, "verify")
    assert result.returncode == 1
    assert "win-a: credential:" in result.stderr and "g1/auth.json" in result.stderr


@_needs_restic
def test_windows_cut_stream_fails_the_backup_and_saves_no_snapshot(tmp_path: Path) -> None:
    if not _on_own_mount(tmp_path):
        pytest.skip("the temp directory is on the root filesystem, which the CLI rightly refuses")
    env, _ = _windows_env(tmp_path, win_a="cut")
    result = _cli(env, "backup")
    assert result.returncode == 1
    assert "restic backup of win-a exited" in result.stderr
    assert _win_snapshots(env) == []


@_needs_restic
def test_windows_unreachable_is_reported_then_fails_only_when_stale(tmp_path: Path) -> None:
    if not _on_own_mount(tmp_path):
        pytest.skip("the temp directory is on the root filesystem, which the CLI rightly refuses")
    env, profile = _windows_env(tmp_path)
    assert _cli(env, "backup").returncode == 0
    env["FAKE_SSH_MODE_win_a"] = "unreachable"
    asleep = _cli(env, "backup")
    assert asleep.returncode == 0, asleep.stderr  # a sleeping host is not a failure tonight
    assert "win-a is unreachable" in asleep.stderr
    fresh = _cli(env, "verify")
    assert fresh.returncode == 0, fresh.stderr
    assert "the snapshot's own listing" in fresh.stdout

    # Only an old snapshot: stale past the bound.
    env2, _ = _windows_env(tmp_path / "old")
    rels = [".claude/projects", ".claude/history.jsonl", ".grok/sessions"]
    args = tc.windows_backup_args("win-a", rels)
    cut = args.index("--")
    old = [*args[:cut], "--time", "2020-01-01 04:15:00", *args[cut:]]
    subprocess.run(["restic", *old], env=env2, capture_output=True, check=True, timeout=120)
    assert (
        _cli({**env2, "HAPAX_TRANSCRIPT_WINDOWS_HOSTS": ""}, "backup").returncode == 0
    )  # local only
    env2["FAKE_SSH_MODE_win_a"] = "unreachable"
    stale = _cli(env2, "verify")
    assert stale.returncode == 1
    assert "win-a: stale:" in stale.stderr


@_needs_restic
def test_windows_nested_symlink_and_drop_fail_verify(tmp_path: Path) -> None:
    if not _on_own_mount(tmp_path):
        pytest.skip("the temp directory is on the root filesystem, which the CLI rightly refuses")
    env, profile = _windows_env(tmp_path)
    assert _cli(env, "backup").returncode == 0
    for i in range(1, 4):  # 4 files -> 1: more than half lost
        (profile / f".claude/projects/p1/s{i}.jsonl").unlink()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (profile / ".claude/projects/p2").symlink_to(elsewhere)
    assert _cli(env, "backup").returncode == 0
    result = _cli(env, "verify")
    assert result.returncode == 1
    assert "win-a: dropped:" in result.stderr and "win-a: nested symlink:" in result.stderr


@_needs_restic
def test_windows_refused_ssh_is_a_failure_not_a_quiet_night(tmp_path: Path) -> None:
    """ssh exits 255 for a sleeping host and for a refused key alike; a refusal will not heal, so it fails now."""

    if not _on_own_mount(tmp_path):
        pytest.skip("the temp directory is on the root filesystem, which the CLI rightly refuses")
    env, _ = _windows_env(tmp_path, win_a="denied")
    result = _cli(env, "backup")
    assert result.returncode == 1
    assert "win-a refused the connection (Permission denied)" in result.stderr
    assert "next action" in result.stderr


@_needs_restic
def test_windows_reachable_host_with_no_transcripts_fails_backup(tmp_path: Path) -> None:
    if not _on_own_mount(tmp_path):
        pytest.skip("the temp directory is on the root filesystem, which the CLI rightly refuses")
    env, profile = _windows_env(tmp_path)
    assert _cli(env, "backup").returncode == 0
    shutil.rmtree(profile / ".claude")
    shutil.rmtree(profile / ".grok")
    result = _cli(env, "backup")
    assert result.returncode == 1
    assert "win-a is reachable but holds no transcript path" in result.stderr


@_needs_restic
def test_windows_harness_path_that_vanishes_fails_verify(tmp_path: Path) -> None:
    if not _on_own_mount(tmp_path):
        pytest.skip("the temp directory is on the root filesystem, which the CLI rightly refuses")
    env, profile = _windows_env(tmp_path)
    assert _cli(env, "backup").returncode == 0
    shutil.rmtree(profile / ".grok")
    assert _cli(env, "backup").returncode == 0
    result = _cli(env, "verify")
    assert result.returncode == 1
    assert "win-a: harness path dropped: /.grok/sessions" in result.stderr


@_needs_restic
def test_every_host_checks_windows_freshness_so_a_silent_puller_fails(tmp_path: Path) -> None:
    """If the puller silently pulls nothing (its hostname differs from the unit's puller name), the other hosts'
    verify still fails: every host checks that each Windows host has a present, fresh snapshot."""

    if not _on_own_mount(tmp_path):
        pytest.skip("the temp directory is on the root filesystem, which the CLI rightly refuses")
    env, _ = _windows_env(tmp_path)
    env["HAPAX_TRANSCRIPT_WINDOWS_PULLER"] = "the-puller-is-elsewhere"
    assert _cli(env, "backup").returncode == 0  # local only: this host does not pull
    missing = _cli(env, "verify")
    assert missing.returncode == 1
    assert "no tier1-transcripts snapshot for Windows host win-a" in missing.stderr

    import socket

    env["HAPAX_TRANSCRIPT_WINDOWS_PULLER"] = socket.gethostname()
    assert _cli(env, "backup").returncode == 0  # now the pull happens
    env["HAPAX_TRANSCRIPT_WINDOWS_PULLER"] = "the-puller-is-elsewhere"
    fresh = _cli(env, "verify")
    assert fresh.returncode == 0, fresh.stderr
    assert "win-a has a fresh tier1-transcripts snapshot" in fresh.stdout
    assert not any(
        "win-a:~" in line for line in fresh.stdout.splitlines()
    )  # contents only on the puller


def test_windows_unreadable_tar_is_a_reported_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tar that cannot be listed from its snapshot fails with a next action, not a traceback."""

    from datetime import UTC, datetime

    cli = _cli_module()
    snap = {
        "id": "abc",
        "short_id": "abc",
        "time": datetime.now(UTC).isoformat(),
        "paths": ["/win-a-transcripts.tar"],
    }
    monkeypatch.setattr(cli, "_restic_json", lambda _env, *_cmd: json.dumps([snap]))

    def broken(_env: dict, _snapshot: dict) -> list:
        raise subprocess.CalledProcessError(1, ["restic", "dump"])

    monkeypatch.setattr(cli, "_tar_listing", broken)
    assert cli._verify_windows({}, "win-a", 26.0) == 1
    err = capsys.readouterr().err
    assert "FAIL win-a: unreadable: the tar in snapshot abc could not be listed" in err
    assert "restic check" in err and "next action" in err


@_needs_restic
def test_inventory_asks_named_windows_hosts(tmp_path: Path) -> None:
    env, _ = _windows_env(tmp_path)
    env["HAPAX_TRANSCRIPT_WINDOWS_PULLER"] = ""
    result = _cli(env, "inventory", "--json", "--windows", "win-a")
    assert result.returncode == 0, result.stderr
    declared = sorted(w["declared"] for w in json.loads(result.stdout)["windows"])
    assert declared == [
        "win-a:~/.claude/history.jsonl",
        "win-a:~/.claude/projects",
        "win-a:~/.grok/sessions",
    ]
    env["FAKE_SSH_MODE_win_a"] = "unreachable"
    asleep = _cli(env, "inventory", "--json", "--windows", "win-a")
    assert asleep.returncode == 1
    assert "unreachable: win-a" in " ".join(json.loads(asleep.stdout)["problems"])


def test_windows_pull_runs_only_on_the_named_puller(tmp_path: Path) -> None:
    env, _ = _windows_env_without_restic(tmp_path)
    env["HAPAX_TRANSCRIPT_WINDOWS_PULLER"] = "some-other-host"
    result = _cli(env, "backup", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.strip().splitlines()) == 1  # the local command only
    assert not (tmp_path / "ssh.log").exists()


def _windows_env_without_restic(tmp_path: Path) -> tuple[dict[str, str], Path]:
    real = shutil.which("restic")
    if real is None:
        pytest.skip("restic is not installed")
    return _windows_env(tmp_path)


def test_parse_windows_inventory() -> None:
    one = tc.parse_windows_inventory(
        "h", '{"rel": ".claude/projects", "kind": "dir", "files": 3, "reparse": false}'
    )
    assert [(p.real, p.kind, p.declared) for p in one.paths] == [
        ("/.claude/projects", "dir", "h:~/.claude/projects")
    ]
    many = tc.parse_windows_inventory(
        "h",
        json.dumps(
            [
                {"rel": ".grok/sessions", "kind": "dir", "files": 1, "reparse": True},
                {"rel": ".grok/downloads", "kind": "dir", "files": 1, "reparse": False},
                {
                    "rel": ".codex/thread_history_1.sqlite",
                    "kind": "file",
                    "files": 1,
                    "reparse": False,
                },
            ]
        ),
    )
    assert [p.real for p in many.paths] == ["/.codex/thread_history_1.sqlite"]
    assert any(p.startswith("symlink: h:~/.grok/sessions") for p in many.problems)
    assert any("matches no path in the table" in p for p in many.problems)
    assert tc.parse_windows_inventory("h", "").paths == []


def test_windows_scripts_and_tar_nodes() -> None:
    import base64
    import io
    import tarfile

    with pytest.raises(ValueError):
        tc.windows_tar_script([])
    script = tc.windows_tar_script([".claude/projects", "odd'name"])
    assert "--exclude '.credentials.json'" in script and "--exclude 'auth.json'" in script
    assert "'odd''name'" in script and script.rstrip().endswith("exit $LASTEXITCODE")
    cmd = tc.encoded_powershell(script)
    assert base64.b64decode(cmd[-1]).decode("utf-16-le") == script

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, kind in (
            ("d", tarfile.DIRTYPE),
            ("d/f", tarfile.REGTYPE),
            ("d/l", tarfile.SYMTYPE),
        ):
            info = tarfile.TarInfo(name)
            info.type = kind
            tar.addfile(info)
        hard = tarfile.TarInfo("d/h")
        hard.type, hard.linkname = tarfile.LNKTYPE, "d/f"
        tar.addfile(hard)
    buf.seek(0)
    nodes = tc.tar_nodes(tarfile.open(fileobj=buf, mode="r"))
    assert [(n["path"], n["type"]) for n in nodes] == [
        ("/d", "dir"),
        ("/d/f", "file"),
        ("/d/l", "symlink"),
        ("/d/h", "file"),
    ]


@pytest.mark.skipif(shutil.which("bsdtar") is None, reason="bsdtar (libarchive) is not installed")
def test_real_bsdtar_honours_the_generated_excludes_at_any_depth(tmp_path: Path) -> None:
    """Windows' tar.exe is libarchive's bsdtar. Run the same engine with exactly the --exclude arguments that
    windows_tar_script generates, over credentials nested inside streamed paths: none may reach the stream."""

    import re
    import tarfile

    profile = tmp_path / "profile"
    (profile / ".grok/sessions/g1/deep").mkdir(parents=True)
    (profile / ".grok/sessions/g1/updates.jsonl").write_text("{}\n")
    for name in (
        "auth.json",
        "deep/.credentials.json",
        "deep/server.pem",
        "deep/api.token",
        "deep/.env",
    ):
        (profile / ".grok/sessions/g1" / name).write_text("not-a-real-secret")
    (profile / ".claude/projects").mkdir(parents=True)
    (profile / ".claude/projects/s.jsonl").write_text("{}\n")
    script = tc.windows_tar_script([".grok/sessions", ".claude/projects"])
    excludes = [p.replace("''", "'") for p in re.findall(r"--exclude '((?:[^']|'')*)'", script)]
    assert excludes == list(tc.CREDENTIAL_PATTERNS)
    cmd = ["bsdtar", "-cf", "-"]
    for pattern in excludes:
        cmd += ["--exclude", pattern]
    cmd += ["-C", str(profile), ".grok/sessions", ".claude/projects"]
    stream = subprocess.run(cmd, capture_output=True, check=True, timeout=60).stdout
    import io

    nodes = tc.tar_nodes(tarfile.open(fileobj=io.BytesIO(stream), mode="r"))
    assert tc.credential_nodes(nodes) == []
    files = sorted(n["path"] for n in nodes if n["type"] == "file")
    assert files == ["/.claude/projects/s.jsonl", "/.grok/sessions/g1/updates.jsonl"]


def test_the_unit_names_the_windows_puller_and_hosts() -> None:
    unit = (_REPO / "systemd/units/hapax-backup-transcripts.service").read_text(encoding="utf-8")
    assert 'Environment="HAPAX_TRANSCRIPT_WINDOWS_HOSTS=hapax-dextra hapax-talus"\n' in unit
    assert "Environment=HAPAX_TRANSCRIPT_WINDOWS_PULLER=hapax-appendix\n" in unit
