"""Transcript custody: which files are each harness's transcripts, where they really live, and whether a backup
snapshot actually holds them.

Operator, 2026-09-27: agent-session transcripts are the estate's highest-value record, and any gap in their custody is
p0. Witnessed mechanics M174: podium's ``~/.claude`` was backed up for months as an empty entry (restic recorded the
directory without its contents), and the green job hid it. So this module:

- names each harness's transcript subpaths: transcripts only, not caches, models, binaries or credentials;
- resolves each one to its real path, so a symlinked store (podium's ``~/.codex`` -> ``/data2/...``) is backed up by
  its target, never as a symlink;
- names the credential files that must never enter a snapshot;
- verifies a snapshot listing (``restic ls --json``). Every path present on the host is in the snapshot as a
  directory or file (never a symlink), and holds at least its floor of files. None has dropped by more than
  ``MAX_DROP`` against the previous snapshot. No path the previous snapshot held has gone. No credential file got in.

The green job is never the evidence: ``verify`` opens the snapshot and counts. The CLI is
``scripts/hapax-transcript-custody``; the unit is ``systemd/units/hapax-backup-transcripts.service``.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

#: A path whose file count falls by more than this fraction against the previous snapshot fails verification.
MAX_DROP = 0.5

#: The restic tag for these snapshots. It is distinct from ``tier1-local``, because that job's
#: ``forget --group-by host,tags`` would otherwise count both snapshots of a day as one group and keep only one of them.
SNAPSHOT_TAG = "tier1-transcripts"


#: Seat ruling 2026-09-27: tier1-transcripts snapshots are NEVER pruned. A transcript deleted on the host (Claude's
#: cleanup period, say) must stay recoverable from older snapshots, and dedup keeps the cost low. Every
#: ``restic forget`` in the estate carries this keep rule, or a ``--tag`` filter that excludes the tag.
KEEP_TRANSCRIPTS_ARGS: tuple[str, str] = ("--keep-tag", SNAPSHOT_TAG)


def forget_protects_transcripts(args: Sequence[str]) -> bool:
    """True when a ``restic forget`` argument list cannot remove a tier1-transcripts snapshot.

    Either it keeps the tag (``--keep-tag tier1-transcripts``), or every ``--tag`` filter it applies names other tags
    only. ``--tag a,b`` selects snapshots carrying both a and b; repeated ``--tag`` options are alternatives.
    """

    def values(flag: str) -> list[str]:
        out = []
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                out.append(args[i + 1])
            elif a.startswith(flag + "="):
                out.append(a.split("=", 1)[1])
        return out

    if any(SNAPSHOT_TAG in v.split(",") for v in values("--keep-tag")):
        return True
    filters = values("--tag")
    return bool(filters) and all(SNAPSHOT_TAG not in f.split(",") for f in filters)


@dataclass(frozen=True)
class TranscriptPath:
    """One harness transcript subpath, relative to $HOME. The last component may be a glob."""

    harness: str
    rel: str
    min_files: int = 1


# Measured 2026-09-27 on appendix and podium (the p0 row's inventory). Left out on purpose, and not transcripts:
# ~/.claude/jobs (509 GB of job state on appendix), plugins, caches, binaries, packages and models; Grok's
# upload_queue, downloads and memory stores; Codex's logs and state databases; Antigravity's browser recordings.
TRANSCRIPT_PATHS: tuple[TranscriptPath, ...] = (
    TranscriptPath("claude", ".claude/projects"),
    TranscriptPath("claude", ".claude/history.jsonl"),
    TranscriptPath("claude-glmcp", ".glmcp-claude/projects"),
    TranscriptPath("claude-glmcp", ".glmcp-claude/history.jsonl"),
    TranscriptPath("codex", ".codex/sessions"),
    TranscriptPath("codex", ".codex/archived_sessions"),
    TranscriptPath("codex", ".codex/history.jsonl"),
    TranscriptPath("codex", ".codex/thread_history_*.sqlite"),
    TranscriptPath("gemini-cli", ".gemini/tmp"),
    TranscriptPath("gemini-cli", ".gemini/history"),
    TranscriptPath("antigravity", ".gemini/antigravity/brain"),
    TranscriptPath("antigravity", ".gemini/antigravity/conversations"),
    TranscriptPath("agy", ".gemini/antigravity-cli/brain"),
    TranscriptPath("agy", ".gemini/antigravity-cli/conversations"),
    TranscriptPath("agy", ".gemini/antigravity-cli/history.jsonl"),
    TranscriptPath("kimi", ".kimi-code/sessions"),
    TranscriptPath("kimi", ".kimi-code/session_index.jsonl"),
    TranscriptPath("kimi", ".kimi-code/user-history"),
    TranscriptPath("vibe", ".vibe/logs"),
    TranscriptPath("grok", ".grok/sessions"),
    TranscriptPath("opencode", ".local/share/opencode/opencode.db*"),
    TranscriptPath("opencode", ".local/share/opencode/tool-output"),
    TranscriptPath("muse", ".local/share/muse/sessions"),
)

#: Credential file names (basename globs). They are excluded from the backup, and a snapshot that holds one fails.
CREDENTIAL_PATTERNS: tuple[str, ...] = (
    "auth.json",
    ".credentials.json",
    "auth.json*",
    ".credentials.json*",
    "credentials.json",
    "credentials",
    "oauth_creds.json",
    "google_accounts.json",
    "antigravity-oauth-token",
    "*.pem",
    "*.key",
    ".env",
    "*.token",
)


@dataclass(frozen=True)
class ResolvedPath:
    harness: str
    declared: str  # ~/relative path on this host (a glob expanded)
    real: str  # absolute real path: what the backup includes
    kind: str  # "dir" or "file"
    via_symlink: bool  # some component of the declared path is a symlink
    min_files: int


@dataclass
class Resolution:
    paths: list[ResolvedPath] = field(default_factory=list)
    problems: list[str] = field(
        default_factory=list
    )  # e.g. a dangling symlink: never silently skipped


def _has_glob(rel: str) -> bool:
    return any(c in rel for c in "*?[")


def _dangling_ancestor(home: Path, rel: str) -> Path | None:
    """The first component of ``rel`` (up to any glob) that is a symlink to nothing, if there is one."""

    cur = home
    for part in Path(rel).parts:
        if _has_glob(part):
            break
        cur = cur / part
        if os.path.islink(cur) and not cur.exists():
            return cur
        if not os.path.lexists(cur):
            break
    return None


def resolve_paths(home: Path, table: Sequence[TranscriptPath] = TRANSCRIPT_PATHS) -> Resolution:
    """The transcript paths present under ``home``, each resolved to its real path (deduplicated).

    A declared path that does not exist is not a problem (that harness is not used on this host). A declared path
    that runs through a symlink to nothing (podium's ``~/.codex`` with ``/data2`` unmounted, say) is a problem,
    reported rather than skipped: otherwise the store would look like an unused harness.
    """

    result = Resolution()
    seen: set[str] = set()
    for tp in table:
        dangling = _dangling_ancestor(home, tp.rel)
        if dangling is not None:
            problem = f"dangling: ~/{dangling.relative_to(home)} is a symlink to missing {os.readlink(dangling)}"
            if problem not in result.problems:
                result.problems.append(problem)
            continue
        candidates = sorted(home.glob(tp.rel)) if _has_glob(tp.rel) else [home / tp.rel]
        for declared in candidates:
            if not os.path.lexists(declared):
                continue
            real = Path(os.path.realpath(declared))
            if not real.exists():
                result.problems.append(
                    f"dangling: ~/{declared.relative_to(home)} resolves to missing {real}"
                )
                continue
            if str(real) in seen:
                continue
            seen.add(str(real))
            result.paths.append(
                ResolvedPath(
                    harness=tp.harness,
                    declared=f"~/{declared.relative_to(home)}",
                    real=str(real),
                    kind="dir" if real.is_dir() else "file",
                    via_symlink=real != declared.absolute(),
                    min_files=tp.min_files,
                )
            )
    return result


def is_credential(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in CREDENTIAL_PATTERNS)


def backup_args(paths: Sequence[ResolvedPath], tag: str = SNAPSHOT_TAG) -> list[str]:
    """``restic backup`` arguments: the tag, the credential excludes, then every real path."""

    if not paths:
        raise ValueError("no transcript paths to back up; refusing to write an empty snapshot")
    args = ["backup", "--tag", tag]
    for pattern in CREDENTIAL_PATTERNS:
        args += ["--exclude", pattern]
    args += [p.real for p in paths]
    return args


CAPTURE_FILENAME = "transcripts-consistent.tar"
CAPTURE_MANIFEST = "custody-manifest.json"


def capture_tar(paths: Sequence[ResolvedPath], archive: Path) -> None:
    """Capture the same table into one verified tar; SQLite uses its online backup API.

    The caller creates a private temporary directory and supplies a new archive path.
    No symlink or credential enters it. An unreadable, empty or dangling source fails.
    Only a completely written capture is passed to restic by the CLI.
    """
    import hashlib
    import json
    import shutil
    import sqlite3
    import tarfile
    import tempfile
    from contextlib import closing
    from dataclasses import asdict

    if not paths:
        raise ValueError("no transcript paths to capture")
    manifest = {"paths": [asdict(p) for p in paths], "files": {}}
    with tempfile.TemporaryDirectory(dir=archive.parent) as staging:
        stage = Path(staging)
        with tarfile.open(archive, "x") as tar:
            for target in paths:
                source = Path(target.real)
                files = sorted(source.rglob("*")) if target.kind == "dir" else [source]
                count = 0
                for item in files:
                    if item.is_symlink():
                        raise ValueError(f"nested symlink: {item}")
                    if not item.is_file() or is_credential(item.name):
                        continue
                    # An opencode glob may include SQLite journals: the main database's
                    # online capture already includes its committed WAL. Never copy a
                    # sidecar independently into a supposedly consistent capture.
                    if item.name.endswith(("-wal", "-shm")):
                        continue
                    name = str(item).lstrip("/")
                    output = stage / name
                    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    if item.suffix in (".sqlite", ".db"):
                        with closing(sqlite3.connect(item.as_uri() + "?mode=ro", uri=True)) as db:
                            with closing(sqlite3.connect(output)) as copy:
                                db.backup(copy)
                                if copy.execute("PRAGMA quick_check").fetchone() != ("ok",):
                                    raise ValueError(f"invalid SQLite capture: {item}")
                                copy.execute("PRAGMA journal_mode=DELETE")
                    else:
                        shutil.copyfile(item, output)
                    output.chmod(0o600)
                    data = output.read_bytes()
                    manifest["files"][name] = {
                        "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                    tar.add(output, arcname=name, recursive=False)
                    count += 1
                if count < target.min_files and not target.real.endswith(("-wal", "-shm")):
                    raise ValueError(f"empty transcript capture: {target.real}")
            # Sidecars are not standalone targets; their main SQLite capture is the witness.
            manifest["paths"] = [
                p for p in manifest["paths"] if not p["real"].endswith(("-wal", "-shm"))
            ]
            info = tarfile.TarInfo(CAPTURE_MANIFEST)
            data = json.dumps(manifest).encode()
            info.size = len(data)
            info.mode = 0o600
            import io

            tar.addfile(info, io.BytesIO(data))
        with tarfile.open(archive) as tar:
            read_capture(tar)


def read_capture(members) -> tuple[list[ResolvedPath], list[dict]]:
    """Read every captured byte, verify its manifest hash, and return existing verifier inputs."""
    import hashlib
    import json
    from pathlib import PurePosixPath

    manifest = None
    observed = {}
    nodes = []
    for member in members:
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not member.isfile()
            or is_credential(path.name)
        ):
            raise ValueError(f"unsafe capture member: {member.name}")
        if member.name in observed:
            raise ValueError(f"duplicate capture member: {member.name}")
        handle = members.extractfile(member)
        if handle is None:
            raise ValueError(f"unreadable capture member: {member.name}")
        if member.name == CAPTURE_MANIFEST:
            if manifest is not None:
                raise ValueError("duplicate capture manifest")
            manifest = json.load(handle)
            continue
        digest = hashlib.sha256()
        size = 0
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
        observed[member.name] = {"bytes": size, "sha256": digest.hexdigest()}
        nodes.append({"struct_type": "node", "path": "/" + member.name, "type": "file"})
    if manifest is None or not observed or observed != manifest.get("files"):
        raise ValueError("capture missing, truncated or differs from its file manifest")
    paths = [ResolvedPath(**p) for p in manifest["paths"]]
    for path in paths:
        if path.kind == "dir":
            nodes.append({"struct_type": "node", "path": path.real, "type": "dir"})
    failures = verify(
        paths,
        count_snapshot(nodes, [p.real for p in paths]),
        snapshot_targets=[p.real for p in paths],
    )
    if failures:
        raise ValueError("; ".join(failures))
    return paths, nodes


@dataclass
class PathCount:
    path: str
    node_type: str | None = None  # the snapshot's node type at exactly ``path``; None when absent
    files: int = 0
    credential_files: list[str] = field(default_factory=list)
    # Symlinks inside the path: restic records the link, not what it points to, so a transcript subtree reached
    # through one is not in the snapshot.
    nested_symlinks: list[str] = field(default_factory=list)


def count_snapshot(nodes: Iterable[Mapping], paths: Sequence[str]) -> dict[str, PathCount]:
    """Count, for each path, the regular files at or under it in a ``restic ls --json`` node stream."""

    counts = {p: PathCount(p) for p in paths}
    prefixes = [(p, p.rstrip("/") + "/") for p in paths]
    for node in nodes:
        if not isinstance(node, Mapping) or node.get("struct_type", "node") != "node":
            continue
        npath, ntype = node.get("path"), node.get("type")
        if not isinstance(npath, str):
            continue
        for p, prefix in prefixes:
            if npath == p:
                counts[p].node_type = ntype
                if ntype == "file":
                    counts[p].files += 1
            elif npath.startswith(prefix) and ntype == "file":
                counts[p].files += 1
                if is_credential(os.path.basename(npath)):
                    counts[p].credential_files.append(npath)
            elif npath.startswith(prefix) and ntype == "symlink":
                counts[p].nested_symlinks.append(npath)
    return counts


def credential_nodes(nodes: Iterable[Mapping]) -> list[str]:
    """Every credential file anywhere in a ``restic ls --json`` node stream, not only under the expected paths: a
    snapshot with an extra target (an ``auth.json`` passed by hand, say) must fail too."""

    found = []
    for node in nodes:
        if not isinstance(node, Mapping) or node.get("struct_type", "node") != "node":
            continue
        npath = node.get("path")
        if (
            node.get("type") == "file"
            and isinstance(npath, str)
            and is_credential(os.path.basename(npath))
        ):
            found.append(npath)
    return found


def verify(
    expected: Sequence[ResolvedPath],
    current: Mapping[str, PathCount],
    *,
    snapshot_targets: Sequence[str],
    previous: Mapping[str, PathCount] | None = None,
    previous_targets: Sequence[str] = (),
    max_drop: float = MAX_DROP,
    snapshot_credentials: Sequence[str] = (),
) -> list[str]:
    """Every failure of the snapshot against what the host holds now and what the previous snapshot held.

    ``snapshot_credentials`` is :func:`credential_nodes` over the whole snapshot; any credential there fails the
    snapshot, wherever it sits."""

    failures: list[str] = []
    reported = {f for c in current.values() for f in c.credential_files}
    stray = sorted(set(snapshot_credentials) - reported)
    if stray:
        failures.append(f"credential: the snapshot holds credential file(s) {stray[:3]}")
    symlinked: set[str] = set()
    for rp in expected:
        c = current.get(rp.real)
        if c is None or c.node_type is None:
            failures.append(
                f"missing: {rp.declared} ({rp.real}) is on this host but not in the snapshot"
            )
            continue
        if c.node_type == "symlink":
            symlinked.add(rp.real)
            failures.append(f"symlink: {rp.real} is recorded as a symlink, not its contents (M174)")
            continue
        if c.files < rp.min_files:
            failures.append(
                f"empty: {rp.real} holds {c.files} files in the snapshot (floor {rp.min_files})"
            )
        if c.credential_files:
            failures.append(
                f"credential: {rp.real} holds credential file(s) {sorted(c.credential_files)[:3]}"
            )
        if c.nested_symlinks:
            failures.append(
                f"nested symlink: {rp.real} holds {len(c.nested_symlinks)} symlink(s) "
                f"{sorted(c.nested_symlinks)[:3]}; the snapshot has the links, not their targets. Add each "
                "target's real path to the path table"
            )
        prev = (previous or {}).get(rp.real)
        if prev is not None and prev.files > 0 and c.files < prev.files * (1 - max_drop):
            failures.append(
                f"dropped: {rp.real} holds {c.files} files, against {prev.files} in the previous snapshot "
                f"(more than {int(max_drop * 100)}% lost)"
            )
    for target in snapshot_targets:
        c = current.get(target)
        if c is not None and c.node_type == "symlink" and target not in symlinked:
            failures.append(
                f"symlink: snapshot target {target} is a symlink, not its contents (M174)"
            )
    for target in sorted(set(previous_targets) - set(snapshot_targets)):
        failures.append(
            f"harness path dropped: {target} was in the previous snapshot and is not in this one"
        )
    return failures


#: Windows hosts are pulled, never pushed from (row transcript-custody-windows-hosts-20260927). The puller runs two
#: commands over SSH: a PowerShell inventory of the table's paths under %USERPROFILE%, then the Windows
#: built-in bsdtar streaming exactly those paths, with credentials excluded by name, into
#: ``restic backup --stdin-from-command``. restic fails the backup when the stream command exits non-zero. There is
#: no staging copy and nothing installed or scheduled on the Windows side.
WINDOWS_SSH_OPTIONS: tuple[str, ...] = (
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=15",
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=4",
)

#: A Windows host sleeps, so a missed night is expected. Its newest snapshot may be this old before verify fails
#: (seat ruling 2026-09-27).
WINDOWS_MAX_AGE_HOURS = 72.0

#: ssh exits 255 both for a host that is asleep and for one that refuses us. A refusal is not sleep: it will not heal
#: on its own, so it is a failure, not a quiet night.
SSH_REFUSAL_MARKERS: tuple[str, ...] = (
    "Permission denied",
    "Host key verification failed",
    "REMOTE HOST IDENTIFICATION HAS CHANGED",
    "Too many authentication failures",
)

WINDOWS_REMEDY = (
    "next action: on the puller (HAPAX_TRANSCRIPT_WINDOWS_PULLER), run `ssh <host> echo ok` (a refusal means the key "
    "or host key needs repair on that host); run `hapax-transcript-custody inventory --windows <host>` to see the "
    "paths the pull would take; check that the puller's `hostname` equals the unit's puller name; then rerun "
    "`systemctl --user start hapax-backup-transcripts.service` there and read its journal"
)


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def encoded_powershell(script: str) -> list[str]:
    """A remote command that runs ``script`` in Windows PowerShell 5.1. It uses -EncodedCommand (base64 of UTF-16LE),
    so no quoting survives or breaks through the SSH command line."""

    import base64

    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


def windows_inventory_script(table: Sequence[TranscriptPath] = TRANSCRIPT_PATHS) -> str:
    """PowerShell that prints, as JSON, every table path present under %USERPROFILE%, with its kind, file count and
    reparse-point flag (a junction or symlink, which tar would record as a link, not as its contents)."""

    rels = ", ".join(_ps_quote(tp.rel) for tp in table)
    return (
        "$ErrorActionPreference = 'Stop'\n"
        "$h = $env:USERPROFILE\n"
        "$out = @()\n"
        f"foreach ($r in @({rels})) {{\n"
        "  $p = Join-Path $h ($r -replace '/', '\\')\n"
        "  foreach ($i in @(Get-Item -Force -Path $p -ErrorAction SilentlyContinue)) {\n"
        "    $rel = $i.FullName.Substring($h.Length + 1) -replace '\\\\', '/'\n"
        "    $reparse = [bool]($i.Attributes -band [IO.FileAttributes]::ReparsePoint)\n"
        "    if ($i.PSIsContainer) {\n"
        "      $n = @(Get-ChildItem -Recurse -File -Force -Path $i.FullName -ErrorAction SilentlyContinue).Count\n"
        "      $k = 'dir'\n"
        "    } else { $n = 1; $k = 'file' }\n"
        "    $out += [pscustomobject]@{ rel = $rel; kind = $k; files = $n; reparse = $reparse }\n"
        "  }\n"
        "}\n"
        "ConvertTo-Json -InputObject @($out) -Compress\n"
    )


def windows_tar_script(rels: Sequence[str]) -> str:
    """PowerShell that streams ``rels`` (relative to %USERPROFILE%) as a tar on stdout, excluding every credential
    name, and exits with tar's own exit code."""

    if not rels:
        raise ValueError(
            "no Windows transcript paths to stream; refusing to write an empty snapshot"
        )
    excludes = " ".join(f"--exclude {_ps_quote(p)}" for p in CREDENTIAL_PATTERNS)
    names = " ".join(_ps_quote(r) for r in rels)
    return f"& tar.exe -cf - {excludes} -C $env:USERPROFILE {names}\nexit $LASTEXITCODE\n"


def _table_entry(rel: str, table: Sequence[TranscriptPath]) -> TranscriptPath | None:
    for tp in table:
        if rel == tp.rel or (_has_glob(tp.rel) and fnmatch.fnmatch(rel, tp.rel)):
            return tp
    return None


def parse_windows_inventory(
    host: str, text: str, table: Sequence[TranscriptPath] = TRANSCRIPT_PATHS
) -> Resolution:
    """The inventory's JSON as a :class:`Resolution`. Each path's ``real`` is its member path in the host's tar
    (``/`` + the path relative to %USERPROFILE%), which is what :func:`count_snapshot` matches against. A reparse
    point is a problem, never a silent skip."""

    import json

    rows = json.loads(text or "[]")
    if isinstance(rows, dict):  # PowerShell 5.1 can unwrap a one-element array
        rows = [rows]
    result = Resolution()
    for row in rows:
        rel = str(row["rel"])
        tp = _table_entry(rel, table)
        if tp is None:
            result.problems.append(f"inventory: {host}:~/{rel} matches no path in the table")
            continue
        if row.get("reparse"):
            result.problems.append(
                f"symlink: {host}:~/{rel} is a junction or symlink; tar would record the link, not its contents"
            )
            continue
        result.paths.append(
            ResolvedPath(
                harness=tp.harness,
                declared=f"{host}:~/{rel}",
                real="/" + rel,
                kind="dir" if row.get("kind") == "dir" else "file",
                via_symlink=False,
                min_files=tp.min_files,
            )
        )
    return result


def windows_backup_args(host: str, rels: Sequence[str], tag: str = SNAPSHOT_TAG) -> list[str]:
    """``restic backup`` arguments that pull ``host``'s paths as one tar stream, under the host's own name."""

    return [
        "backup",
        "--stdin-from-command",
        "--stdin-filename",
        f"{host}-transcripts.tar",
        "--host",
        host,
        "--tag",
        tag,
        "--",
        "ssh",
        *WINDOWS_SSH_OPTIONS,
        host,
        *encoded_powershell(windows_tar_script(rels)),
    ]


def tar_nodes(members: Iterable) -> list[dict]:
    """A tar listing (``tarfile.TarInfo`` members) as a ``restic ls --json`` node stream, so that
    :func:`count_snapshot`, :func:`credential_nodes` and :func:`verify` read it unchanged."""

    nodes = []
    for m in members:
        # A hard link's content is in the archive under its first name, so it counts as a file. A symbolic link is
        # only the link, so it is recorded as one, and verify fails it as a nested symlink.
        if m.isdir():
            kind = "dir"
        elif m.isfile() or m.islnk():
            kind = "file"
        elif m.issym():
            kind = "symlink"
        else:
            kind = "other"
        nodes.append({"struct_type": "node", "path": "/" + m.name.rstrip("/"), "type": kind})
    return nodes


def listing_targets(
    nodes: Iterable[Mapping], table: Sequence[TranscriptPath] = TRANSCRIPT_PATHS
) -> list[str]:
    """The table paths a tar listing holds as members of their own (the stream's top-level targets)."""

    found = []
    for node in nodes:
        path = node.get("path")
        if isinstance(path, str) and _table_entry(path.lstrip("/"), table) is not None:
            found.append(path)
    return sorted(set(found))


def listing_expected(
    host: str, nodes: Sequence[Mapping], table: Sequence[TranscriptPath] = TRANSCRIPT_PATHS
) -> list[ResolvedPath]:
    """What a Windows host held when its snapshot was taken, read from the snapshot's own listing. It is used when the
    host cannot be asked now (asleep at verify, or the snapshot is not from this run), so the floor, drop and
    credential checks still apply."""

    kinds = {n.get("path"): n.get("type") for n in nodes}
    expected = []
    for target in listing_targets(nodes, table):
        tp = _table_entry(target.lstrip("/"), table)
        assert tp is not None  # listing_targets returned only table paths
        expected.append(
            ResolvedPath(
                harness=tp.harness,
                declared=f"{host}:~{target}",
                real=target,
                kind="dir" if kinds.get(target) == "dir" else "file",
                via_symlink=False,
                min_files=tp.min_files,
            )
        )
    return expected


REMEDY = (
    "next action: run `hapax-transcript-custody inventory` on this host to see which transcript paths exist and "
    "where they resolve; fix the path table (scripts/transcript_custody.py) or the store; then rerun "
    "`systemctl --user start hapax-backup-transcripts.service` and read its journal"
)
