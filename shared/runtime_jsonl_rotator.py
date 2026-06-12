"""Size-based rotation for hot JSONL runtime ledgers.

The registry covers append-only files that are written by long-running
daemons but reopened for each append. Dynamic, partitioned, or domain-rotated
ledgers stay outside this registry with explicit writer-side exemptions.

Rotation uses POSIX rename, then creates a fresh live file at the original path.
Writers with an already-open fd finish on the renamed slice; later appends reopen
the original path. The slice is append-gzipped into an archive, but it is only
removed after same-user writer fds for the slice inode have closed. Late writes
to retained slices are archived from a saved byte offset on the next rotator run.
Byte-cursor bus consumers must treat shrink/rotation as a cursor reset; unread
records already moved into an archived slice are retained for audit, not replayed
through the live-file bus.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import json
import os
import shutil
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

MIB = 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = REPO_ROOT / "profiles"
PRIMARY_PROFILES_DIR = Path.home() / "projects" / "hapax-council" / "profiles"
HAPAX_HOME = Path(os.environ.get("HAPAX_HOME", str(Path.home())))
HAPAX_CACHE_DIR = HAPAX_HOME / ".cache"


@dataclass(frozen=True)
class RotationTarget:
    name: str
    path: Path
    max_bytes: int
    archive_dir: Path
    keep_archives: int = 14

    @property
    def archive_glob(self) -> str:
        return f"{self.name}.*.jsonl.gz"


@dataclass(frozen=True)
class RotationResult:
    target: str
    status: str
    path: str
    max_bytes: int
    size_before: int
    size_after: int
    archive_path: str | None = None
    recovered_slices: int = 0
    pruned_archives: int = 0
    message: str = ""


DEFAULT_TARGETS: dict[str, RotationTarget] = {
    "dispatch-trace": RotationTarget(
        name="dispatch-trace",
        path=Path.home() / "hapax-state" / "affordance" / "dispatch-trace.jsonl",
        max_bytes=96 * MIB,
        archive_dir=Path.home() / "hapax-state" / "affordance" / "archive",
        keep_archives=14,
    ),
    "recruitment-log": RotationTarget(
        name="recruitment-log",
        path=Path.home() / "hapax-state" / "affordance" / "recruitment-log.jsonl",
        max_bytes=96 * MIB,
        archive_dir=Path.home() / "hapax-state" / "affordance" / "archive",
        keep_archives=14,
    ),
    "dmn-impingements": RotationTarget(
        name="dmn-impingements",
        path=Path("/dev/shm/hapax-dmn/impingements.jsonl"),
        max_bytes=8 * MIB,
        archive_dir=Path("/dev/shm/hapax-dmn/archive"),
        keep_archives=4,
    ),
    "axiom-tool-usage": RotationTarget(
        name="axiom-tool-usage",
        path=HAPAX_CACHE_DIR / "axiom-audit" / "tool-usage.jsonl",
        max_bytes=16 * MIB,
        archive_dir=HAPAX_CACHE_DIR / "axiom-audit" / "archive",
        keep_archives=14,
    ),
    "broadcast-events": RotationTarget(
        name="broadcast-events",
        path=Path("/dev/shm/hapax-broadcast/events.jsonl"),
        max_bytes=8 * MIB,
        archive_dir=Path("/dev/shm/hapax-broadcast/archive"),
        keep_archives=4,
    ),
    "monetization-events": RotationTarget(
        name="monetization-events",
        path=Path("/dev/shm/hapax-monetization/events.jsonl"),
        max_bytes=8 * MIB,
        archive_dir=Path("/dev/shm/hapax-monetization/archive"),
        keep_archives=4,
    ),
    "public-events": RotationTarget(
        name="public-events",
        path=Path("/dev/shm/hapax-public-events/events.jsonl"),
        max_bytes=8 * MIB,
        archive_dir=Path("/dev/shm/hapax-public-events/archive"),
        keep_archives=4,
    ),
    "chronicle-events": RotationTarget(
        name="chronicle-events",
        path=Path("/dev/shm/hapax-chronicle/events.jsonl"),
        max_bytes=96 * MIB,
        archive_dir=Path("/dev/shm/hapax-chronicle/archive"),
        keep_archives=4,
    ),
    "dmn-fortress-actions": RotationTarget(
        name="dmn-fortress-actions",
        path=Path("/dev/shm/hapax-dmn/fortress-actions.jsonl"),
        max_bytes=8 * MIB,
        archive_dir=Path("/dev/shm/hapax-dmn/archive"),
        keep_archives=4,
    ),
    "fortress-sessions": RotationTarget(
        name="fortress-sessions",
        path=PROFILES_DIR / "fortress-sessions.jsonl",
        max_bytes=16 * MIB,
        archive_dir=PROFILES_DIR / "archive",
        keep_archives=14,
    ),
    "fortress-chronicle": RotationTarget(
        name="fortress-chronicle",
        path=PROFILES_DIR / "fortress-chronicle.jsonl",
        max_bytes=16 * MIB,
        archive_dir=PROFILES_DIR / "archive",
        keep_archives=14,
    ),
    "mail-monitor-api-calls": RotationTarget(
        name="mail-monitor-api-calls",
        path=Path.home() / ".cache" / "mail-monitor" / "api-calls.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / ".cache" / "mail-monitor" / "archive",
        keep_archives=14,
    ),
    "audio-processor-changes": RotationTarget(
        name="audio-processor-changes",
        path=Path.home() / ".cache" / "audio-processor" / "changes.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / ".cache" / "audio-processor" / "archive",
        keep_archives=14,
    ),
    "av-correlator-changes": RotationTarget(
        name="av-correlator-changes",
        path=Path.home() / ".cache" / "av-correlator" / "changes.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / ".cache" / "av-correlator" / "archive",
        keep_archives=14,
    ),
    "claude-code-sync-changes": RotationTarget(
        name="claude-code-sync-changes",
        path=Path.home() / ".cache" / "claude-code-sync" / "changes.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / ".cache" / "claude-code-sync" / "archive",
        keep_archives=14,
    ),
    "gcalendar-sync-changes": RotationTarget(
        name="gcalendar-sync-changes",
        path=Path.home() / ".cache" / "gcalendar-sync" / "changes.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / ".cache" / "gcalendar-sync" / "archive",
        keep_archives=14,
    ),
    "gdrive-sync-deletions": RotationTarget(
        name="gdrive-sync-deletions",
        path=Path.home() / ".cache" / "gdrive-sync" / "deletions.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / ".cache" / "gdrive-sync" / "archive",
        keep_archives=14,
    ),
    "git-sync-changes": RotationTarget(
        name="git-sync-changes",
        path=Path.home() / ".cache" / "git-sync" / "changes.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / ".cache" / "git-sync" / "archive",
        keep_archives=14,
    ),
    "gmail-sync-changes": RotationTarget(
        name="gmail-sync-changes",
        path=Path.home() / ".cache" / "gmail-sync" / "changes.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / ".cache" / "gmail-sync" / "archive",
        keep_archives=14,
    ),
    "obsidian-sync-changes": RotationTarget(
        name="obsidian-sync-changes",
        path=Path.home() / ".cache" / "obsidian-sync" / "changes.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / ".cache" / "obsidian-sync" / "archive",
        keep_archives=14,
    ),
    "youtube-sync-changes": RotationTarget(
        name="youtube-sync-changes",
        path=Path.home() / ".cache" / "youtube-sync" / "changes.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / ".cache" / "youtube-sync" / "archive",
        keep_archives=14,
    ),
    "video-processor-changes": RotationTarget(
        name="video-processor-changes",
        path=Path.home() / ".cache" / "video-processor" / "changes.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / ".cache" / "video-processor" / "archive",
        keep_archives=14,
    ),
    "reverie-predictions": RotationTarget(
        name="reverie-predictions",
        path=Path.home() / "hapax-state" / "monitors" / "reverie-predictions.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / "hapax-state" / "monitors" / "archive",
        keep_archives=14,
    ),
    "captions-live": RotationTarget(
        name="captions-live",
        path=Path("/dev/shm/hapax-captions/live.jsonl"),
        max_bytes=8 * MIB,
        archive_dir=Path("/dev/shm/hapax-captions/archive"),
        keep_archives=4,
    ),
    "structural-intent": RotationTarget(
        name="structural-intent",
        path=Path.home() / "hapax-state" / "stream-experiment" / "structural-intent.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / "hapax-state" / "stream-experiment" / "archive",
        keep_archives=14,
    ),
    "axiom-enforcement-audit": RotationTarget(
        name="axiom-enforcement-audit",
        path=PROFILES_DIR / ".enforcement-audit.jsonl",
        max_bytes=16 * MIB,
        archive_dir=PROFILES_DIR / "archive",
        keep_archives=14,
    ),
    "liveness-recovery-ledger": RotationTarget(
        name="liveness-recovery-ledger",
        path=Path.home() / ".cache" / "hapax" / "liveness" / "recovery-ledger.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / ".cache" / "hapax" / "liveness" / "archive",
        keep_archives=14,
    ),
    "recovery-failopen-tmpfs": RotationTarget(
        name="recovery-failopen-tmpfs",
        path=Path("/dev/shm/hapax/recovery/failopen.jsonl"),
        max_bytes=8 * MIB,
        archive_dir=Path("/dev/shm/hapax/recovery/archive"),
        keep_archives=4,
    ),
    "recovery-failopen-fallback": RotationTarget(
        name="recovery-failopen-fallback",
        path=Path.home() / ".cache" / "hapax" / "recovery" / "failopen.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / ".cache" / "hapax" / "recovery" / "archive",
        keep_archives=14,
    ),
    "recovery-shadow-compare": RotationTarget(
        name="recovery-shadow-compare",
        path=Path("/dev/shm/hapax/recovery/shadow-compare.jsonl"),
        max_bytes=8 * MIB,
        archive_dir=Path("/dev/shm/hapax/recovery/archive"),
        keep_archives=4,
    ),
    "research-marker-changes": RotationTarget(
        name="research-marker-changes",
        path=Path.home() / "hapax-state" / "research-registry" / "research_marker_changes.jsonl",
        max_bytes=16 * MIB,
        archive_dir=Path.home() / "hapax-state" / "research-registry" / "archive",
        keep_archives=14,
    ),
}

if PRIMARY_PROFILES_DIR != PROFILES_DIR:
    DEFAULT_TARGETS.update(
        {
            "fortress-sessions-primary": RotationTarget(
                name="fortress-sessions-primary",
                path=PRIMARY_PROFILES_DIR / "fortress-sessions.jsonl",
                max_bytes=16 * MIB,
                archive_dir=PRIMARY_PROFILES_DIR / "archive",
                keep_archives=14,
            ),
            "fortress-chronicle-primary": RotationTarget(
                name="fortress-chronicle-primary",
                path=PRIMARY_PROFILES_DIR / "fortress-chronicle.jsonl",
                max_bytes=16 * MIB,
                archive_dir=PRIMARY_PROFILES_DIR / "archive",
                keep_archives=14,
            ),
            "axiom-enforcement-audit-primary": RotationTarget(
                name="axiom-enforcement-audit-primary",
                path=PRIMARY_PROFILES_DIR / ".enforcement-audit.jsonl",
                max_bytes=16 * MIB,
                archive_dir=PRIMARY_PROFILES_DIR / "archive",
                keep_archives=14,
            ),
        }
    )


def _utc_now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def _archive_path(target: RotationTarget, now: datetime) -> Path:
    return target.archive_dir / f"{target.name}.{now.date().isoformat()}.jsonl.gz"


def _rotating_path(path: Path, now: datetime) -> Path:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    candidate = path.with_name(f"{path.name}.{stamp}.{os.getpid()}.rotating")
    if not candidate.exists():
        return candidate
    for suffix in range(1, 100):
        alternate = path.with_name(f"{candidate.name}.{suffix}")
        if not alternate.exists():
            return alternate
    raise OSError(f"could not allocate rotating path for {path}")


def _archive_offset_path(slice_path: Path) -> Path:
    return slice_path.with_name(f"{slice_path.name}.archive-offset")


def _read_archive_offset(slice_path: Path, source_size: int) -> int:
    offset_path = _archive_offset_path(slice_path)
    try:
        offset = int(offset_path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return 0
    if offset < 0 or offset > source_size:
        return 0
    return offset


def _write_archive_offset(slice_path: Path, offset: int) -> None:
    offset_path = _archive_offset_path(slice_path)
    tmp_path = offset_path.with_name(f"{offset_path.name}.tmp")
    tmp_path.write_text(str(offset), encoding="utf-8")
    tmp_path.replace(offset_path)


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return int(left.st_dev) == int(right.st_dev) and int(left.st_ino) == int(right.st_ino)


def _has_same_user_open_fd(source_stat: os.stat_result) -> bool:
    proc_root = Path("/proc")
    if not proc_root.exists():
        return True
    current_uid = os.getuid()
    for proc_dir in proc_root.iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            if proc_dir.stat().st_uid != current_uid:
                continue
            fd_entries = list((proc_dir / "fd").iterdir())
        except OSError:
            continue
        for fd_entry in fd_entries:
            try:
                if _same_file(os.stat(fd_entry), source_stat):
                    return True
            except OSError:
                continue
    return False


def _lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".rotate.lock")


def _ensure_live_file(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    try:
        return os.fstat(fd).st_size
    finally:
        os.close(fd)


def _archive_slice(
    slice_path: Path,
    target: RotationTarget,
    now: datetime,
) -> Path:
    archive_path = _archive_path(target, now)
    target.archive_dir.mkdir(parents=True, exist_ok=True)
    while True:
        source_stat = slice_path.stat()
        source_size = source_stat.st_size
        offset = _read_archive_offset(slice_path, source_size)
        if offset < source_size:
            with slice_path.open("rb") as src, gzip.open(archive_path, "ab") as dst:
                src.seek(offset)
                shutil.copyfileobj(src, dst)
                copied_until = src.tell()
            _write_archive_offset(slice_path, copied_until)
        if _has_same_user_open_fd(source_stat):
            return archive_path
        latest_size = slice_path.stat().st_size
        latest_offset = _read_archive_offset(slice_path, latest_size)
        if latest_size > latest_offset:
            continue
        slice_path.unlink()
        _archive_offset_path(slice_path).unlink(missing_ok=True)
        return archive_path


def _recover_rotating_slices(target: RotationTarget, now: datetime) -> int:
    recovered = 0
    for slice_path in sorted(target.path.parent.glob(f"{target.path.name}.*.rotating*")):
        if slice_path.name.endswith((".archive-offset", ".archive-offset.tmp")):
            continue
        if not slice_path.is_file():
            continue
        _archive_slice(slice_path, target, now)
        recovered += 1
    return recovered


def _prune_archives(target: RotationTarget) -> int:
    if target.keep_archives < 1 or not target.archive_dir.exists():
        return 0
    archives = sorted(
        (p for p in target.archive_dir.glob(target.archive_glob) if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    pruned = 0
    for path in archives[target.keep_archives :]:
        try:
            path.unlink()
            pruned += 1
        except OSError:
            continue
    return pruned


def rotate_target(target: RotationTarget, *, now: datetime | None = None) -> RotationResult:
    """Rotate one target if it is over its byte cap."""
    current = _utc_now(now)
    target.path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(_lock_path(target.path), os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        recovered = _recover_rotating_slices(target, current)

        if not target.path.exists():
            pruned = _prune_archives(target)
            return RotationResult(
                target=target.name,
                status="noop_missing",
                path=str(target.path),
                max_bytes=target.max_bytes,
                size_before=0,
                size_after=0,
                recovered_slices=recovered,
                pruned_archives=pruned,
            )

        try:
            size_before = target.path.stat().st_size
        except OSError as exc:
            return RotationResult(
                target=target.name,
                status="error",
                path=str(target.path),
                max_bytes=target.max_bytes,
                size_before=-1,
                size_after=-1,
                recovered_slices=recovered,
                message=f"stat failed: {exc}",
            )

        if size_before == 0:
            pruned = _prune_archives(target)
            return RotationResult(
                target=target.name,
                status="noop_empty",
                path=str(target.path),
                max_bytes=target.max_bytes,
                size_before=0,
                size_after=0,
                recovered_slices=recovered,
                pruned_archives=pruned,
            )

        if size_before < target.max_bytes:
            pruned = _prune_archives(target)
            return RotationResult(
                target=target.name,
                status="noop_under_cap",
                path=str(target.path),
                max_bytes=target.max_bytes,
                size_before=size_before,
                size_after=size_before,
                recovered_slices=recovered,
                pruned_archives=pruned,
            )

        rotating = _rotating_path(target.path, current)
        try:
            os.replace(target.path, rotating)
            size_after = _ensure_live_file(target.path)
        except OSError as exc:
            return RotationResult(
                target=target.name,
                status="error",
                path=str(target.path),
                max_bytes=target.max_bytes,
                size_before=size_before,
                size_after=-1,
                recovered_slices=recovered,
                message=f"rename failed: {exc}",
            )

        try:
            archive_path = _archive_slice(rotating, target, current)
            pruned = _prune_archives(target)
        except OSError as exc:
            return RotationResult(
                target=target.name,
                status="partial",
                path=str(target.path),
                max_bytes=target.max_bytes,
                size_before=size_before,
                size_after=size_after,
                recovered_slices=recovered,
                message=f"archive failed; slice left at {rotating}: {exc}",
            )

        return RotationResult(
            target=target.name,
            status="rotated",
            path=str(target.path),
            max_bytes=target.max_bytes,
            size_before=size_before,
            size_after=size_after,
            archive_path=str(archive_path),
            recovered_slices=recovered,
            pruned_archives=pruned,
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def rotate_targets(
    targets: Iterable[RotationTarget],
    *,
    now: datetime | None = None,
) -> list[RotationResult]:
    current = _utc_now(now)
    return [rotate_target(target, now=current) for target in targets]


def _selected_targets(names: list[str] | None) -> list[RotationTarget]:
    if not names or "all" in names:
        return list(DEFAULT_TARGETS.values())
    return [DEFAULT_TARGETS[name] for name in names]


def _result_to_json(result: RotationResult) -> dict[str, object]:
    return asdict(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        action="append",
        choices=["all", *DEFAULT_TARGETS],
        help="Target to rotate. Repeatable; defaults to all.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--list-targets", action="store_true", help="List configured target names.")
    args = parser.parse_args(argv)

    if args.list_targets:
        for name in DEFAULT_TARGETS:
            print(name)
        return 0

    results = rotate_targets(_selected_targets(args.target))
    if args.json:
        print(json.dumps([_result_to_json(result) for result in results], indent=2))
    else:
        for result in results:
            print(
                f"{result.target}: {result.status} "
                f"{result.size_before}->{result.size_after} "
                f"cap={result.max_bytes}"
            )

    bad = {result.status for result in results} & {"error", "partial"}
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "DEFAULT_TARGETS",
    "RotationResult",
    "RotationTarget",
    "main",
    "rotate_target",
    "rotate_targets",
]
