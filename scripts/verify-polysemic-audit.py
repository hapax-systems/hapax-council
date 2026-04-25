#!/usr/bin/env python3
"""V5 weave wk1 d4 — polysemic audit CI gate (epsilon-owned).

Walks every artifact-bearing markdown file under ``docs/audience/`` (V5
weave outline + manifesto + Constitutional Brief) and ``docs/published-
artifacts/`` (DOI-index landings, when populated) and runs
``agents.authoring.polysemic_audit.audit_artifact`` on each file's body.

Per V5 weave § 12 invariant 5: every artifact passes this gate before
approval-queue entry. The CI surface enforces the gate at PR-time so
no artifact lands on main with unflagged cross-domain readings.

Exit status:
  0 — all artifacts pass
  1 — one or more concerns flagged across the artifacts (stderr lists)
  2 — structural error (path missing, malformed file, etc.)

Usage:
  uv run python scripts/verify-polysemic-audit.py
  uv run python scripts/verify-polysemic-audit.py --paths docs/audience
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = [
    REPO_ROOT / "docs" / "audience",
    REPO_ROOT / "docs" / "published-artifacts",
]


def _scan_dir(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(directory.rglob("*.md"))


def _acknowledged_terms_from_frontmatter(content: str) -> frozenset[str]:
    """Parse ``polysemic_audit_acknowledged_terms`` from YAML frontmatter.

    Returns an empty frozenset when no frontmatter exists or the field
    is absent. Acknowledgement is per-artifact: the operator declares
    multi-register-by-design terms in the source's frontmatter, and the
    audit honors the override.

    Frontmatter shape:

      polysemic_audit_acknowledged_terms:
        - governance
        - compliance
        - safety
      polysemic_audit_acknowledgement_rationale: |
        ... operator-authored rationale ...

    Rationale is optional but operator-recommended (it documents the
    override decision in-band so future readers can audit).
    """
    if not (content.startswith("---\n") or content.startswith("---\r\n")):
        return frozenset()
    after_open = content.split("\n", 1)[1] if "\n" in content else ""
    end_idx = after_open.find("\n---\n")
    if end_idx == -1:
        end_idx = after_open.find("\n---\r\n")
    if end_idx == -1:
        return frozenset()
    fm_text = after_open[:end_idx]
    try:
        import yaml

        parsed = yaml.safe_load(fm_text)
    except (ImportError, Exception):  # noqa: BLE001 — yaml may emit any error
        return frozenset()
    if not isinstance(parsed, dict):
        return frozenset()
    value = parsed.get("polysemic_audit_acknowledged_terms")
    if not isinstance(value, list):
        return frozenset()
    return frozenset(str(v).strip() for v in value if isinstance(v, str))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--paths",
        nargs="+",
        type=Path,
        default=DEFAULT_PATHS,
        help="Directories to scan recursively for *.md artifacts",
    )
    args = parser.parse_args()

    try:
        from agents.authoring.polysemic_audit import audit_artifact
    except ImportError as e:
        sys.stderr.write(f"ERROR: agents.authoring.polysemic_audit not importable: {e}\n")
        return 2

    files: list[Path] = []
    for path in args.paths:
        files.extend(_scan_dir(path))

    if not files:
        # No artifacts yet (eg. docs/published-artifacts/ empty
        # pre-first-publish). Pass cleanly — gate becomes meaningful
        # the moment artifacts land.
        print("OK: no artifacts to audit (empty audience dirs)")
        return 0

    flagged: list[tuple[Path, list[str]]] = []
    for file_path in files:
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as e:
            sys.stderr.write(f"ERROR: unable to read {file_path}: {e}\n")
            return 2
        ack = _acknowledged_terms_from_frontmatter(content)
        result = audit_artifact(content, acknowledged_terms=ack)
        if not result.passed:
            messages = [
                f"{c.term} (registers: {', '.join(c.registers)}) — excerpt: {c.excerpt[:100]}"
                for c in result.concerns
            ]
            flagged.append((file_path, messages))

    if flagged:
        sys.stderr.write(f"FAIL: {len(flagged)} artifact(s) with polysemic-audit concerns:\n")
        for path, messages in flagged:
            try:
                display = path.relative_to(REPO_ROOT)
            except ValueError:
                display = path
            sys.stderr.write(f"  {display}:\n")
            for msg in messages:
                sys.stderr.write(f"    - {msg}\n")
        sys.stderr.write(
            "\nResolution: explicit register-shift sentence at the top of each\n"
            "section so the cross-domain term reads unambiguously within scope.\n"
            "See V5 weave § 12 invariant 5 for the contract.\n"
        )
        return 1

    print(f"OK: {len(files)} artifact(s) passed polysemic audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
