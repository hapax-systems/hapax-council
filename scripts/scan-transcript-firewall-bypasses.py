#!/usr/bin/env python3
"""Scan Python sources for direct reads of §4.B-protected paths.

LRR Phase 6 §3.4.B: the transcript + impingement firewall is a read-side
invariant. Every reader must go through ``shared.transcript_read_gate``.
This scanner detects direct ``open()`` / ``read_text()`` / ``read_bytes()``
calls against the protected path patterns, without the gate.

Run from repo root:
    uv run python scripts/scan-transcript-firewall-bypasses.py

Exit codes:
    0 — clean (no bypasses detected)
    1 — one or more bypasses found (paths printed to stderr)

Allow-list (files permitted to read protected paths directly):
    shared/transcript_read_gate.py       — the gate itself
    shared/sensor_protocol.py            — writes impingements (write side)
    shared/impingement_consumer.py       — daimonion's own consumer (CPAL)
    agents/hapax_daimonion/**            — daimonion owns its own transcripts
    agents/code_narration/**             — writes impingements (write side)
    tests/**                             — test fixtures use tmp_path
    scripts/**                           — operational scripts (e.g. this scanner)

Heuristic: regex match against the protected path patterns in Python sources.
False positives are acceptable (easy to allowlist); false negatives are not.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent

# Path patterns that indicate a protected read target appearing in source.
PROTECTED_PATH_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"events-.*\.jsonl"),
    re.compile(r"hapax-daimonion/recordings"),
    re.compile(r"\.local/share/hapax-daimonion/events"),
    re.compile(r"/dev/shm/hapax-dmn/impingements\.jsonl"),
)

# Call-expression patterns that indicate a read is happening at the
# point the protected path appears. Match on the same line or the prior
# two lines (conservative: most reads are one-liners or short chains).
READ_CALL_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\.read_text\s*\("),
    re.compile(r"\.read_bytes\s*\("),
    re.compile(r"\bopen\s*\("),
    re.compile(r"\.open\s*\("),
    re.compile(r"\.iterdir\s*\("),
    re.compile(r"\.glob\s*\("),
)

# Files permitted to read protected paths directly. Paths relative to repo root.
ALLOWLIST_DIRS: frozenset[str] = frozenset(
    {
        "shared/transcript_read_gate.py",
        "shared/sensor_protocol.py",
        "shared/impingement_consumer.py",
        "shared/exploration_tracker.py",
    }
)

# Directory prefixes whose entire contents are allowed (daimonion owns its own
# transcripts; tests use fixtures; scripts are operational).
ALLOWLIST_PREFIXES: tuple[str, ...] = (
    "agents/hapax_daimonion/",
    "agents/code_narration/",
    "tests/",
    "scripts/",
    ".venv/",
    "docs/",
)


def is_allowlisted(rel_path: str) -> bool:
    if rel_path in ALLOWLIST_DIRS:
        return True
    return any(rel_path.startswith(prefix) for prefix in ALLOWLIST_PREFIXES)


def scan_file(py_path: pathlib.Path) -> list[tuple[int, str]]:
    """Scan one Python file. Returns list of (line_number, offending_line)."""
    try:
        lines = py_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    hits: list[tuple[int, str]] = []

    for i, line in enumerate(lines):
        # Does any protected path pattern appear on this line?
        if not any(p.search(line) for p in PROTECTED_PATH_PATTERNS):
            continue
        # Does any read-call pattern appear on this line or the next one?
        window = "\n".join(lines[i : min(i + 3, len(lines))])
        if any(r.search(window) for r in READ_CALL_PATTERNS):
            hits.append((i + 1, line.rstrip()))

    return hits


def main() -> int:
    violations: list[tuple[str, int, str]] = []
    for py in REPO_ROOT.rglob("*.py"):
        rel = str(py.relative_to(REPO_ROOT))
        if is_allowlisted(rel):
            continue
        for line_no, line in scan_file(py):
            violations.append((rel, line_no, line))

    if not violations:
        print("transcript firewall: 0 bypasses")
        return 0

    print(
        f"transcript firewall: {len(violations)} bypass candidate(s) detected:",
        file=sys.stderr,
    )
    for rel, line_no, line in violations:
        print(f"  {rel}:{line_no}: {line}", file=sys.stderr)
    print(
        "\nEvery reader of §4.B-protected paths must go through "
        "shared.transcript_read_gate.read_transcript_gate(). "
        "Either route the caller through the gate, or add the file to the "
        "ALLOWLIST in this scanner if it's a legitimate exception "
        "(e.g., daimonion's own consumer, the gate itself, tests).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
