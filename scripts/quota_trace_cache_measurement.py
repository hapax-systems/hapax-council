#!/usr/bin/env python3
"""Bounded read-only replay of real Codex traces; never an installed-effect claim.

Use the --trace-cache-measure mode of scripts/check-quota-headroom-mutations.py.
Uses stable files, at most 64 MiB / 32 files, an explicit baseline commit and scratch root.
Pass arguments after -- in the existing checker. Example on appendix:
  --trace-cache-measure -- --baseline-ref <full-pre-change-SHA> --scratch-root /store-fast/tmp
Does not invoke the live writer, probe providers, mint receipts or change original traces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCES = ("shared/quota_headroom.py", "shared/quota_trace_cache.py")


@contextmanager
def candidate_reader(sources, directory):
    """Execute the captured Git bytes, including lazy reader/cache cross-imports.

    Snapshot files also bind the cache's __file__-based parser fingerprint. Never
    reuse a previously imported reader or reload later working-tree bytes.
    """
    modules = {}
    for relative, data in sources.items():
        path = directory / relative
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        name = relative.removesuffix(".py").replace("/", ".")
        module = ModuleType(name)
        module.__file__ = str(path)
        modules[name] = module
    with patch.dict(sys.modules, modules):
        for relative, data in sources.items():
            module = modules[relative.removesuffix(".py").replace("/", ".")]
            exec(compile(data, module.__file__, "exec"), module.__dict__)
        yield modules["shared.quota_headroom"].read_codex_token_count


def fingerprint(path):
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
    return {
        "source": str(path),
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "sha256": digest.hexdigest(),
    }


class Counted:
    def __init__(self, stream, counter):
        self.stream, self.counter = stream, counter

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def __getattr__(self, key):
        return getattr(self.stream, key)

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line

    def read(self, *args):
        data = self.stream.read(*args)
        self.counter[0] += len(data)
        return data

    def readline(self, *args):
        data = self.stream.readline(*args)
        self.counter[0] += len(data)
        return data


def measure(reader, sessions, *, now, **kwargs):
    """Count binary Path.open read/readline/iteration through scratch trace paths.

    This is scoped logical I/O, not a general I/O interceptor: builtin/os.open,
    resolved source paths, other stream methods and physical reads are excluded.
    The pinned reader/cache use the covered paths; tests check their known counts.
    """
    counter = [0]
    original = Path.open

    def counted(path, *args, **options):
        stream = original(path, *args, **options)
        return Counted(stream, counter) if path.parent == sessions else stream

    psi_before = Path("/proc/pressure/io").read_text()
    io_before = Path("/proc/self/io").read_text()
    start = time.monotonic()
    with patch.object(Path, "open", counted):
        rows = reader(sessions, now=now, **kwargs)
    elapsed = time.monotonic() - start
    return rows, {
        "wall_seconds": elapsed,
        "read_accounting_scope": "binary Path.open read/readline/iteration in scratch sessions",
        "raw_bytes_read": counter[0],
        "io_before": io_before,
        "io_after": Path("/proc/self/io").read_text(),
        "host_io_psi_before": psi_before,
        "host_io_psi_after": Path("/proc/pressure/io").read_text(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=Path, default=Path.home() / ".codex/sessions")
    parser.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-files", type=int, default=32)
    parser.add_argument("--baseline-ref", required=True, help="Full pre-change commit SHA")
    parser.add_argument(
        "--scratch-root", type=Path, required=True, help="Existing scratch directory"
    )
    args = parser.parse_args(argv)
    if not 0 < args.max_bytes <= 64 * 1024 * 1024 or not 0 < args.max_files <= 32:
        parser.error("replay is bounded to 64 MiB and 32 files. Next action: lower the bounds")
    if not re.fullmatch(r"[0-9a-f]{40}", args.baseline_ref):
        parser.error("baseline must be a full commit SHA. Next action: supply the pre-change SHA")
    try:
        baseline_commit = subprocess.check_output(
            ["git", "rev-parse", "--verify", f"{args.baseline_ref}^{{commit}}"],
            cwd=ROOT,
            stderr=subprocess.PIPE,
            text=True,
        ).strip()
        baseline_bytes = subprocess.check_output(
            ["git", "show", f"{baseline_commit}:shared/quota_headroom.py"],
            cwd=ROOT,
            stderr=subprocess.PIPE,
        )
        candidate_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            stderr=subprocess.PIPE,
            text=True,
        ).strip()
        candidate_sources = {
            path: subprocess.check_output(
                ["git", "show", f"{candidate_commit}:{path}"], cwd=ROOT, stderr=subprocess.PIPE
            )
            for path in SOURCES
        }
        if any((ROOT / path).read_bytes() != data for path, data in candidate_sources.items()):
            parser.error(
                "candidate source differs from HEAD. "
                "Next action: commit the reader/cache changes before measuring"
            )
        candidate_bytes = candidate_sources["shared/quota_headroom.py"]
    except (OSError, subprocess.CalledProcessError):
        parser.error("source identity unavailable. Next action: fetch the explicit baseline commit")
    if baseline_bytes == candidate_bytes:
        parser.error(
            "identical reader bytes cannot witness a pre-change comparison. "
            "Next action: supply the actual pre-change commit SHA"
        )
    # Admission for this optional experiment: avoid adding reads during the incident.
    try:
        psi = Path("/proc/pressure/io").read_text()
        full = next(line for line in psi.splitlines() if line.startswith("full "))
        avg10 = float(dict(item.split("=", 1) for item in full.split()[1:])["avg10"])
        if not math.isfinite(avg10) or not 0 <= avg10 <= 100:
            raise ValueError("invalid pressure")
    except (OSError, StopIteration, ValueError, KeyError):
        parser.error(
            "host IO pressure unavailable. Next action: use a Linux host with readable IO PSI"
        )
    if avg10 > 10:
        parser.error(
            "host full IO PSI avg10 > 10%. Next action: wait for an idle window, keep evidence unchanged"
        )
    try:
        return replay(
            args, baseline_commit, baseline_bytes, candidate_commit, candidate_sources, parser
        )
    except (OSError, ValueError) as exc:
        parser.error(
            f"replay unavailable ({type(exc).__name__}). "
            "Next action: check source readability and scratch capacity, then retry"
        )


def replay(args, baseline_commit, baseline_bytes, candidate_commit, candidate_sources, parser):
    if not args.scratch_root.is_dir():
        parser.error("scratch root unavailable. Next action: supply an existing --scratch-root")
    now = datetime.now(UTC)
    selected = []
    total = 0
    for path in sorted(args.sessions.glob("**/rollout-*.jsonl"), reverse=True):
        stat = path.stat()
        if stat.st_mtime > now.timestamp() - 600 or not 65536 <= stat.st_size <= args.max_bytes:
            continue
        if total + stat.st_size > args.max_bytes:
            continue
        selected.append(path)
        total += stat.st_size
        if len(selected) == args.max_files:
            break
    if not selected:
        parser.error(
            "no stable bounded trace sample; no measurement made. "
            "Next action: point --sessions at traces unchanged for at least ten minutes"
        )
    directory = Path(tempfile.mkdtemp(prefix="quota-trace-measure-", dir=args.scratch_root))
    sessions = directory / "sessions"
    sessions.mkdir()
    before = [fingerprint(path) for path in selected]
    for index, path in enumerate(selected):
        (sessions / f"rollout-{index:04}.jsonl").symlink_to(path.absolute())
    baseline = {
        "__name__": "quota_trace_baseline",
        "__file__": str(ROOT / "shared/quota_headroom.py"),
    }
    exec(compile(baseline_bytes, "quota_trace_baseline", "exec"), baseline)
    expected, full_read = measure(baseline["read_codex_token_count"], sessions, now=now)
    if full_read["raw_bytes_read"] == 0:
        parser.error(
            "baseline read zero counted bytes; no reduction can be measured. "
            "Next action: verify the baseline reader and the declared read-accounting scope"
        )
    with candidate_reader(candidate_sources, directory) as read_candidate:
        cold, cold_read = measure(
            read_candidate, sessions, now=now, cache_path=directory / "cache.json"
        )
        warm, warm_read = measure(
            read_candidate, sessions, now=now, cache_path=directory / "cache.json"
        )
    after = [fingerprint(path) for path in selected]
    equal = expected == cold == warm
    preserved = before == after
    report = {
        "scope": "bounded real-trace Codex reader replay; not an installed or full writer tick",
        "now": now.isoformat(),
        "files": len(selected),
        "source_bytes": total,
        "baseline_ref": args.baseline_ref,
        "baseline_commit": baseline_commit,
        "candidate_commit": candidate_commit,
        "candidate_source_binding": "captured Git reader/cache bytes; worktree matched at admission",
        "baseline_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
        "candidate_sha256": {
            p: hashlib.sha256(data).hexdigest() for p, data in candidate_sources.items()
        },
        "baseline": full_read,
        "cold": cold_read,
        "warm": warm_read,
        "exact_outputs_equal": equal,
        "raw_bytes_and_identity_preserved": preserved,
        "outputs": {
            label: [row.model_dump(mode="json") for row in rows]
            for label, rows in (("baseline", expected), ("cold", cold), ("warm", warm))
        },
        "output_sha256": hashlib.sha256(
            json.dumps([r.model_dump(mode="json") for r in expected], sort_keys=True).encode()
        ).hexdigest(),
        "warm_read_reduction": 1 - warm_read["raw_bytes_read"] / full_read["raw_bytes_read"],
        "sources_before": before,
        "sources_after": after,
    }
    report_path = directory / "measurement.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    os.chmod(report_path, 0o600)
    print(
        json.dumps(
            {
                "report": str(report_path),
                "equal": equal,
                "preserved": preserved,
                "baseline": full_read["raw_bytes_read"],
                "warm": warm_read["raw_bytes_read"],
                "reduction": report["warm_read_reduction"],
            }
        )
    )
    return 0 if equal and preserved else 1


if __name__ == "__main__":
    raise SystemExit(main())
