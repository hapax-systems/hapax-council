#!/usr/bin/env python3
"""Bounded read-only replay of real Codex traces; never an installed-effect claim.

Example: TMPDIR=/store-fast/tmp uv run --no-sync python scripts/measure-quota-trace-cache.py
Uses stable files, at most 64 MiB / 32 files; stores private hashes/results on /store-fast.
Does not invoke the live writer, probe providers, mint receipts or change original traces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.quota_headroom import read_codex_token_count  # noqa: E402


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
        "raw_bytes_read": counter[0],
        "io_before": io_before,
        "io_after": Path("/proc/self/io").read_text(),
        "host_io_psi_before": psi_before,
        "host_io_psi_after": Path("/proc/pressure/io").read_text(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=Path, default=Path.home() / ".codex/sessions")
    parser.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-files", type=int, default=32)
    parser.add_argument("--baseline-ref", default="HEAD")
    args = parser.parse_args()
    if not 0 < args.max_bytes <= 64 * 1024 * 1024 or not 0 < args.max_files <= 32:
        parser.error("replay is bounded to 64 MiB and 32 files")
    # Admission for this optional experiment: avoid adding reads during the incident.
    psi = Path("/proc/pressure/io").read_text()
    full = next(line for line in psi.splitlines() if line.startswith("full "))
    if float(full.split("avg10=")[1].split()[0]) > 10:
        parser.error(
            "host full IO PSI avg10 > 10%; wait for an idle window, keep evidence unchanged"
        )
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
        parser.error("no stable bounded trace sample; no measurement made")
    directory = Path(tempfile.mkdtemp(prefix="quota-trace-measure-", dir="/store-fast/tmp"))
    sessions = directory / "sessions"
    sessions.mkdir()
    before = [fingerprint(path) for path in selected]
    for index, path in enumerate(selected):
        (sessions / f"rollout-{index:04}.jsonl").symlink_to(path.absolute())
    baseline_bytes = subprocess.check_output(
        ["git", "show", f"{args.baseline_ref}:shared/quota_headroom.py"], cwd=ROOT
    )
    baseline = {
        "__name__": "quota_trace_baseline",
        "__file__": str(ROOT / "shared/quota_headroom.py"),
    }
    exec(compile(baseline_bytes, "quota_trace_baseline", "exec"), baseline)
    expected, full_read = measure(baseline["read_codex_token_count"], sessions, now=now)
    cold, cold_read = measure(
        read_codex_token_count, sessions, now=now, cache_path=directory / "cache.json"
    )
    warm, warm_read = measure(
        read_codex_token_count, sessions, now=now, cache_path=directory / "cache.json"
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
        "baseline_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
        "candidate_sha256": {
            p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
            for p in ("shared/quota_headroom.py", "shared/quota_trace_cache.py")
        },
        "baseline": full_read,
        "cold": cold_read,
        "warm": warm_read,
        "exact_outputs_equal": equal,
        "raw_bytes_and_identity_preserved": preserved,
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
