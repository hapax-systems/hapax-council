#!/usr/bin/env python3
"""Mutation-check the quota accelerator in the existing disposable source overlay.

Use TMPDIR=/store-fast/tmp uv run --no-sync python scripts/check-quota-headroom-mutations.py --trace-cache.
Each break must fail an assertion, restore exact source bytes, then pass its test.
"""

from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = "shared/quota_trace_cache.py"
READER = "shared/quota_headroom.py"
WRITER = "scripts/hapax-quota-telemetry-writer"
TEST = "tests/shared/test_quota_trace_cache.py"
MUTANTS = [
    (
        "raw-line-bound",
        "test_large_irrelevant_record_does_not_disable_acceleration",
        CACHE,
        "MAX_LINE_BYTES = 16 * 1024 * 1024",
        "MAX_LINE_BYTES = 2 * 1024 * 1024",
    ),
    (
        "prefix",
        "test_middle_rewrite_plus_append_verifies_entire_prefix",
        CACHE,
        'if digest.hexdigest() != previous["sha256"]:',
        "if False:",
    ),
    (
        "ctime",
        "test_same_size_middle_rewrite_with_restored_mtime_is_detected",
        CACHE,
        'if previous["stamp"] == before:',
        'if previous["stamp"][:3] == before[:3]:',
    ),
    (
        "identity",
        "test_replaced_identical_source_is_reparsed",
        CACHE,
        'or previous["stamp"][:2] != before[:2]',
        "or False",
    ),
    (
        "checksum",
        "test_cache_schema_or_content_uncertainty_requires_raw_reread[checksum]",
        CACHE,
        'envelope["sha256"] != _digest(_encoded(payload))',
        "False",
    ),
    (
        "parser",
        "test_cache_schema_or_content_uncertainty_requires_raw_reread[parser]",
        CACHE,
        'payload["parser"] != self.parser',
        "False",
    ),
    (
        "source-alias",
        "test_cache_path_cannot_replace_a_raw_trace",
        READER,
        "and not cache_path.resolve().is_relative_to(sessions_root.resolve())",
        "and True",
    ),
    (
        "file-bound",
        "test_memory_and_disk_cache_are_bounded_without_losing_readings",
        CACHE,
        "and (previous is not None or len(self.entries) < MAX_FILES)",
        "and True",
    ),
    (
        "byte-bound",
        "test_cache_byte_budget_does_not_truncate_quota_history",
        CACHE,
        "and self.entry_bytes - old_bytes + entry_bytes <= MAX_CACHE_BYTES - 1024",
        "and True",
    ),
    (
        "reread",
        "test_corruption_narrows_collector_to_unobserved",
        CACHE,
        "return raw_reader(path, contains=b'\"token_count\"')",
        'return removed["records"]',
    ),
    (
        "race",
        "test_racing_source_cannot_publish_a_cached_snapshot",
        CACHE,
        "if _stamp(os.fstat(stream.fileno())) != before or _stamp(path.stat()) != before:",
        "if False:",
    ),
    (
        "read-only",
        "test_writer_check_does_not_create_a_trace_cache",
        WRITER,
        "if not args.check\n                else None",
        "if True\n                else None",
    ),
    (
        "acceleration",
        "test_warm_unchanged_trace_has_bounded_reads",
        CACHE,
        "previous = self.entries.get(key)",
        "previous = None",
    ),
]


def main():
    harness = runpy.run_path(str(ROOT / "scripts/check-quota-headroom-mutations.py"))
    harness["COPIES"].update({CACHE, TEST})
    evidence = Path(tempfile.mkdtemp(prefix="quota-trace-mutations-"))
    work = harness["build_overlay"](evidence / "overlay")
    results = []
    for name, test, relative, old, new in MUTANTS:
        original = (ROOT / relative).read_bytes()
        if original.decode().count(old) != 1:
            raise ValueError(f"nonunique mutant anchor: {name}")
        result = harness["run_mutant"](
            work, evidence, (name, f"{TEST}::{test}", relative, old, new)
        )
        restored = (work / relative).read_bytes() == original
        harness["clear_caches"](work)
        green = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                f"{TEST}::{test}",
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(work / ".pytest-tmp"),
            ],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=120,
        )
        (evidence / f"{name}-restored.log").write_text(green.stdout + green.stderr)
        result.update(
            restored_exact=restored,
            source_sha256=hashlib.sha256(original).hexdigest(),
            green_exit_code=green.returncode,
        )
        results.append(result)
        print(json.dumps(result), flush=True)
    (evidence / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"Evidence: {evidence}", flush=True)
    return (
        0
        if all(r["killed"] and r["restored_exact"] and r["green_exit_code"] == 0 for r in results)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
