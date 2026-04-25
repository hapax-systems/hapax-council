#!/usr/bin/env python3
"""Verify publication-contract redaction entries match the registry.

Walks every ``axioms/contracts/publication/*.yaml`` (or the directory
specified via ``--contracts-dir``) and validates each ``redactions:``
entry as one of:

  * a registered transform name (in
    :data:`shared.governance.publication_allowlist.REDACTION_TRANSFORMS`)
  * a dict-key pattern (a string with a ``.`` (dot-prefixed nested
    key) or ``*`` wildcard suffix)

Any other entry — a bare word that's neither registered nor pattern-
shaped — is a likely typo or unregistered transform. Phase B's
wire-in (#1384) silently no-ops on such entries; this linter
fails fast at CI time so production never ships a misnamed transform.

Spec: AUDIT-22 Phase B-2 (linter + naming alignment).

Exit status:
  0 — clean
  1 — one or more invalid redaction entries
  2 — structural error (malformed YAML, missing dir, etc.)

Usage:
  uv run python scripts/verify-redaction-transforms.py
  uv run python scripts/verify-redaction-transforms.py --contracts-dir /tmp/x
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACTS_DIR = REPO_ROOT / "axioms" / "contracts" / "publication"


def _is_dict_key_pattern(entry: str) -> bool:
    """A redaction entry is a dict-key pattern when it contains a dot
    (literal dotted key like ``chat.author_id`` or wildcard like
    ``operator_profile.*``) or ends with a bare ``*``. Bare words
    that the publication_allowlist would treat as exact-key matchers
    are accepted only via the registered-transform check; ambiguous
    bare words are rejected."""
    return "." in entry or entry.endswith("*")


def _validate_contract(path: Path, registered: set[str]) -> list[str]:
    """Return a list of human-readable error strings for ``path``.
    Empty list = clean. Caller treats non-empty as exit-code-1."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        return [f"{path.name}: malformed YAML: {e}"]

    if not isinstance(data, dict):
        return [f"{path.name}: top-level YAML is not a mapping"]

    redactions = data.get("redactions") or []
    if not isinstance(redactions, list):
        return [f"{path.name}: 'redactions' is not a list"]

    errors: list[str] = []
    for entry in redactions:
        if not isinstance(entry, str):
            errors.append(f"{path.name}: redaction entry is not a string: {entry!r}")
            continue
        if entry in registered:
            continue
        if _is_dict_key_pattern(entry):
            continue
        errors.append(
            f"{path.name}: redaction entry {entry!r} is neither a registered "
            f"transform nor a dict-key pattern (likely typo or unregistered "
            f"transform)"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contracts-dir",
        type=Path,
        default=DEFAULT_CONTRACTS_DIR,
        help="Directory containing publication contract YAMLs",
    )
    args = parser.parse_args()

    if not args.contracts_dir.is_dir():
        sys.stderr.write(f"ERROR: contracts dir missing: {args.contracts_dir}\n")
        return 2

    try:
        from shared.governance.publication_allowlist import REDACTION_TRANSFORMS
    except ImportError as e:
        sys.stderr.write(f"ERROR: shared.governance.publication_allowlist not importable: {e}\n")
        return 2

    registered = set(REDACTION_TRANSFORMS.keys())

    all_errors: list[str] = []
    contract_count = 0
    for path in sorted(args.contracts_dir.glob("*.yaml")):
        contract_count += 1
        all_errors.extend(_validate_contract(path, registered))

    if all_errors:
        sys.stderr.write(
            f"FAIL: {len(all_errors)} invalid redaction entr"
            f"{'y' if len(all_errors) == 1 else 'ies'} across "
            f"{contract_count} contract(s):\n"
        )
        for err in all_errors:
            sys.stderr.write(f"  - {err}\n")
        sys.stderr.write(
            f"\nRegistered transforms: {sorted(registered)}\n"
            f"Dict-key patterns: contain '.' or end with '*'\n"
        )
        return 1

    print(
        f"OK: {contract_count} contract(s) validated against "
        f"{len(registered)} registered transform(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
