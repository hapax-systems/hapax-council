#!/usr/bin/env python3
"""LRR Phase 1 item 4 — frozen-file pre-commit enforcement.

Reads the active research condition's `frozen_files` list from
`~/hapax-state/research-registry/<current>/condition.yaml` and refuses
to commit any change that touches those paths while the condition is
open. The override is an explicit `DEVIATION-NNN.md` filed under
`research/protocols/deviations/` whose body mentions the offending
file path verbatim.

Exit codes:
  0 — no frozen-file violations OR a covering deviation exists
  1 — frozen-file violation with no covering deviation
  2 — registry not initialized (no enforcement, allow commit)
  3 — internal error (yaml parse failure, etc.)

Usage as a pre-commit hook:
    Install via .pre-commit-config.yaml entry, or as
    .git/hooks/pre-commit (single-repo only).

Spike + design context:
    docs/superpowers/specs/2026-04-14-lrr-phase-1-research-registry-design.md
    Bundle 2 §3 Approach A (Python entry point recommended over shell).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "check-frozen-files: PyYAML is required. Install via `uv sync` or `pip install pyyaml`.",
        file=sys.stderr,
    )
    sys.exit(3)


REGISTRY_DIR = Path.home() / "hapax-state" / "research-registry"
CURRENT_FILE = REGISTRY_DIR / "current.txt"
DEVIATIONS_DIR = Path("research/protocols/deviations")


def _read_current_condition_id() -> str | None:
    if not CURRENT_FILE.exists():
        return None
    return CURRENT_FILE.read_text().strip() or None


def _read_frozen_files(condition_id: str) -> list[str]:
    condition_yaml = REGISTRY_DIR / condition_id / "condition.yaml"
    if not condition_yaml.exists():
        return []
    try:
        data = yaml.safe_load(condition_yaml.read_text()) or {}
    except yaml.YAMLError as exc:
        print(f"check-frozen-files: failed to parse {condition_yaml}: {exc}", file=sys.stderr)
        return []
    return list(data.get("frozen_files") or [])


def _staged_files() -> list[str]:
    """Return paths of all staged files (relative to repo root)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "-z"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"check-frozen-files: git diff failed: {exc}", file=sys.stderr)
        return []
    raw = result.stdout
    return [p for p in raw.split("\0") if p]


def _file_is_frozen(staged_path: str, frozen_list: list[str]) -> bool:
    """Match staged path against the frozen list. Exact match or prefix.

    Frozen entries can be exact file paths or directory prefixes.
    A prefix match requires the entry to end with `/` to disambiguate
    from accidental substring matches.
    """
    if staged_path in frozen_list:
        return True
    return any(entry.endswith("/") and staged_path.startswith(entry) for entry in frozen_list)


def _find_covering_deviations(
    frozen_files_touched: list[str],
) -> dict[str, str] | None:
    """Find deviation coverage for each touched file.

    Returns a mapping ``{touched_file: deviation_filename}`` iff every
    file in ``frozen_files_touched`` has at least one covering deviation,
    or ``None`` if even one file has no coverage.

    Phase 1 audit finding H3 fix: the previous ``_find_covering_deviation``
    required a SINGLE deviation to mention every touched file. That was
    correct for the Phase 1 bootstrap (only one deviation could ever
    exist at a time) but breaks the moment two independent deviations
    legitimately cover two different frozen files in the same commit.
    This version walks every deviation and records the FIRST one that
    mentions each file, returning the aggregated coverage map. A single
    deviation covering all files still works (it lands in the map on
    first iteration); a multi-deviation scenario also works because
    every file gets picked up independently.

    Heuristic: grep each deviation body for the file path verbatim. The
    substring-match weakness (Phase 1 audit M2) is a separate issue and
    out of scope for this fix.
    """
    if not DEVIATIONS_DIR.exists():
        return None
    coverage: dict[str, str] = {}
    for deviation_path in sorted(DEVIATIONS_DIR.glob("DEVIATION-*.md")):
        try:
            body = deviation_path.read_text()
        except OSError:
            continue
        for touched in frozen_files_touched:
            if touched in coverage:
                continue
            if touched in body:
                coverage[touched] = deviation_path.name
    if set(coverage.keys()) == set(frozen_files_touched):
        return coverage
    return None


def main() -> int:
    condition_id = _read_current_condition_id()
    if not condition_id:
        # Registry not initialized — no enforcement. Allow commit.
        return 0

    frozen = _read_frozen_files(condition_id)
    if not frozen:
        # No files frozen under this condition. Allow commit.
        return 0

    staged = _staged_files()
    if not staged:
        # Empty staging area (e.g. amending a commit with no new changes).
        return 0

    violations = [p for p in staged if _file_is_frozen(p, frozen)]
    if not violations:
        return 0

    # There IS overlap. Look for covering deviations — per H3 fix, each
    # touched file can be covered by a different deviation.
    coverage = _find_covering_deviations(violations)
    if coverage is not None:
        deviations_used = sorted(set(coverage.values()))
        if len(deviations_used) == 1:
            print(
                f"check-frozen-files: {len(violations)} frozen file(s) touched but "
                f"covered by {deviations_used[0]}: {', '.join(violations)}"
            )
        else:
            coverage_lines = [f"  {f} → {d}" for f, d in sorted(coverage.items())]
            print(
                f"check-frozen-files: {len(violations)} frozen file(s) touched, "
                f"covered by {len(deviations_used)} deviation(s):\n" + "\n".join(coverage_lines)
            )
        return 0

    # No deviation. Reject the commit with a structured error.
    print("=" * 70, file=sys.stderr)
    print("FROZEN-FILE VIOLATION", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(f"Active research condition: {condition_id}", file=sys.stderr)
    print("Files touched that are frozen under this condition:", file=sys.stderr)
    for path in violations:
        print(f"  - {path}", file=sys.stderr)
    print("", file=sys.stderr)
    print("These files cannot be committed while condition is open without", file=sys.stderr)
    print("an explicit deviation. To proceed, file a deviation:", file=sys.stderr)
    print("", file=sys.stderr)
    print("  1. Create research/protocols/deviations/DEVIATION-NNN.md", file=sys.stderr)
    print("     (NNN = next sequential number, see existing files)", file=sys.stderr)
    print("  2. Document why this change is research-validity-safe", file=sys.stderr)
    print("  3. Reference each frozen file path verbatim in the body", file=sys.stderr)
    print("  4. git add the deviation file + your changes", file=sys.stderr)
    print("  5. Re-run the commit", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        "Alternative: close the active condition first via "
        "`scripts/research-registry.py close <id>`, then commit + open a new "
        "condition.",
        file=sys.stderr,
    )
    print("=" * 70, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
