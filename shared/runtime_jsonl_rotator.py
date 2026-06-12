"""Size-based rotation for hot JSONL runtime ledgers.

The registry covers append-only files that are written by long-running
daemons but reopened for each append. Dynamic, partitioned, or domain-rotated
ledgers stay outside this registry with explicit writer-side exemptions.

Rotation uses POSIX rename, then creates a fresh live file at the original path.
Writers with an already-open fd finish on the renamed slice; later appends reopen
the original path. The slice is append-gzipped into an archive and removed.
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
    with slice_path.open("rb") as src, gzip.open(archive_path, "ab") as dst:
        shutil.copyfileobj(src, dst)
    slice_path.unlink()
    return archive_path


def _recover_rotating_slices(target: RotationTarget, now: datetime) -> int:
    recovered = 0
    for slice_path in sorted(target.path.parent.glob(f"{target.path.name}.*.rotating*")):
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
