#!/usr/bin/env python3
"""LRR Phase 2 item 9 — archive purge CLI with consent-revocation tie-in.

Auditable deletion of archive data tied to a single ``condition_id``.
Default is **dry-run**: the CLI prints what would be deleted without
touching any file. ``--confirm`` is required for actual deletion.

Refuses to purge the currently-active condition. Every invocation
(dry-run or confirmed) writes an entry to the purge audit log at
``<archive_root>/purge.log``.

**Consent-revocation tie-in (LRR Phase 2 spec §3.9):** the
``--consent-revoked-for <person_id>`` flag binds the purge to the
interpersonal_transparency axiom. When set:

  1. The CLI loads ``ConsentRegistry`` from ``axioms/contracts/``
  2. Looks up the active contract for ``<person_id>``
  3. Requires that EITHER no contract exists, OR the contract's
     ``revoked_at`` is populated
  4. If a live (non-revoked) contract exists, the purge is refused
     with exit 3 — the operator must revoke the contract via the
     contracts YAML before purging the derived data
  5. On confirmed purge, the audit log entry carries the
     ``consent_revoked_for`` field so the purge is traceable to the
     revocation event

This prevents "purge first, revoke later" ordering that would
temporarily violate the axiom's fail-closed semantics.

Usage::

    archive-purge.py --condition <id>               # dry-run (default)
    archive-purge.py --condition <id> --confirm     # live
    archive-purge.py --condition <id> --confirm --reason "consent revocation"
    archive-purge.py --condition <id> --confirm \\
        --consent-revoked-for simon --reason "guardian revoked simon's scope"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from shared.stream_archive import (
    SegmentSidecar,
    archive_root,
)

PURGE_LOG_NAME = "purge.log"
DEFAULT_REASON = "operator explicit"
ACTIVE_CONDITION_POINTER = Path.home() / "hapax-state" / "research-registry" / "current.txt"


def _consent_revocation_check(
    person_id: str,
    contracts_dir: Path | None = None,
) -> tuple[bool, str]:
    """Verify that ``person_id`` has no active (non-revoked) consent contract.

    Returns ``(ok, message)``. ``ok=True`` means the purge is permitted
    with respect to the consent axiom — either no contract exists, or
    the existing contract is revoked. ``ok=False`` means a live contract
    is in place and the purge must be refused until the operator revokes
    it via the contracts YAML first.

    Read-only import — uses the existing ``shared.governance.consent``
    surface which loads ``axioms/contracts/*.yaml`` from disk. Does not
    modify any contract state.
    """
    try:
        from shared.governance.consent import ConsentRegistry
    except ImportError as exc:
        return False, f"ConsentRegistry import failed: {exc}"

    registry = ConsentRegistry()
    registry.load(contracts_dir)
    contract = registry.get_contract_for(person_id)
    if contract is None:
        return True, f"no contract for {person_id!r} — consent check passes"
    if not contract.active:
        return True, f"contract {contract.id!r} for {person_id!r} is revoked — consent check passes"
    return False, (
        f"contract {contract.id!r} for {person_id!r} is LIVE (not revoked); "
        f"revoke it in axioms/contracts/ before purging the derived data"
    )


def _iter_sidecars(root: Path) -> list[Path]:
    paths: list[Path] = []
    for kind in ("hls", "audio"):
        subdir = root / kind
        if not subdir.exists():
            continue
        paths.extend(sorted(subdir.rglob("*.json")))
    return paths


def _load_active_condition(pointer: Path = ACTIVE_CONDITION_POINTER) -> str | None:
    if not pointer.exists():
        return None
    try:
        value = pointer.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _append_audit_log(
    log_path: Path,
    entry: dict[str, object],
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _collect_targets(root: Path, condition_id: str) -> list[tuple[Path, Path, int]]:
    """Find all (sidecar_path, segment_path, size_bytes) for the given condition."""
    results: list[tuple[Path, Path, int]] = []
    for sidecar_path in _iter_sidecars(root):
        try:
            sidecar = SegmentSidecar.from_path(sidecar_path)
        except (ValueError, json.JSONDecodeError, OSError):
            continue
        if sidecar.condition_id != condition_id:
            continue
        segment_path = Path(sidecar.segment_path)
        try:
            size = segment_path.stat().st_size if segment_path.exists() else 0
        except OSError:
            size = 0
        results.append((sidecar_path, segment_path, size))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="archive-purge.py",
        description="Auditable purge of stream archive data for a given condition_id.",
    )
    parser.add_argument("--condition", required=True, help="condition_id to purge")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete files (default: dry-run)",
    )
    parser.add_argument(
        "--reason",
        default=DEFAULT_REASON,
        help=f"Purge reason for the audit log (default: {DEFAULT_REASON!r})",
    )
    parser.add_argument(
        "--archive-root",
        type=str,
        default=None,
        help="Override archive root",
    )
    parser.add_argument(
        "--active-condition-pointer",
        type=str,
        default=None,
        help="Override the active-condition pointer file (test harness)",
    )
    parser.add_argument(
        "--consent-revoked-for",
        default=None,
        help=(
            "Person ID whose consent has been revoked, binding this purge to "
            "the interpersonal_transparency axiom. When set, the CLI verifies "
            "the person has no active (non-revoked) contract before proceeding."
        ),
    )
    parser.add_argument(
        "--contracts-dir",
        default=None,
        help="Override the consent contracts directory (test harness)",
    )
    args = parser.parse_args(argv)

    root = Path(args.archive_root) if args.archive_root else archive_root()
    pointer = (
        Path(args.active_condition_pointer)
        if args.active_condition_pointer
        else ACTIVE_CONDITION_POINTER
    )

    active = _load_active_condition(pointer)
    if active == args.condition:
        print(
            f"ERROR: refusing to purge active condition {args.condition!r}. "
            f"Close it first via research-registry.py close.",
            file=sys.stderr,
        )
        return 2

    # LRR Phase 2 spec §3.9 consent-revocation tie-in.
    if args.consent_revoked_for is not None:
        contracts_dir = Path(args.contracts_dir) if args.contracts_dir else None
        ok, msg = _consent_revocation_check(args.consent_revoked_for, contracts_dir)
        print(f"consent-check: {msg}", file=sys.stderr)
        if not ok:
            print(
                f"ERROR: refusing to purge — {msg}",
                file=sys.stderr,
            )
            return 3

    targets = _collect_targets(root, args.condition)

    total_bytes = sum(size for _, _, size in targets)
    mode = "confirmed" if args.confirm else "dry_run"

    print(
        json.dumps(
            {
                "condition_id": args.condition,
                "mode": mode,
                "segments_affected": len(targets),
                "bytes_affected": total_bytes,
                "reason": args.reason,
                "archive_root": str(root),
            },
            indent=2,
        )
    )

    for sidecar_path, segment_path, _ in targets:
        print(f"  {'WOULD DELETE' if not args.confirm else 'DELETING'}: {segment_path}")
        print(f"  {'WOULD DELETE' if not args.confirm else 'DELETING'}: {sidecar_path}")

    if args.confirm:
        errors: list[str] = []
        for sidecar_path, segment_path, _ in targets:
            for p in (segment_path, sidecar_path):
                try:
                    if p.exists():
                        p.unlink()
                except OSError as exc:
                    errors.append(f"{p}: {exc}")
        if errors:
            print(
                json.dumps({"errors": errors}, indent=2),
                file=sys.stderr,
            )

    # Always write an audit entry — even dry-run runs are audited so the
    # purge.log is a complete history of decisions, not just actions.
    audit_entry: dict[str, object] = {
        "ts": _now_iso(),
        "condition_id": args.condition,
        "mode": mode,
        "operator": "hapax",
        "segments_affected": len(targets),
        "bytes_affected": total_bytes,
        "reason": args.reason,
    }
    if args.consent_revoked_for is not None:
        audit_entry["consent_revoked_for"] = args.consent_revoked_for
    _append_audit_log(root / PURGE_LOG_NAME, audit_entry)

    return 0


if __name__ == "__main__":
    sys.exit(main())
