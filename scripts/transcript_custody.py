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


@dataclass
class PathCount:
    path: str
    node_type: str | None = None  # the snapshot's node type at exactly ``path``; None when absent
    files: int = 0
    credential_files: list[str] = field(default_factory=list)


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


REMEDY = (
    "next action: run `hapax-transcript-custody inventory` on this host to see which transcript paths exist and "
    "where they resolve; fix the path table (scripts/transcript_custody.py) or the store; then rerun "
    "`systemctl --user start hapax-backup-transcripts.service` and read its journal"
)
