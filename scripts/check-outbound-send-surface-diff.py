#!/usr/bin/env python3
"""check-outbound-send-surface-diff — name a diff's outbound send surfaces.

The outbound_message_egress_sensitive release class's CI evidence
(RELEASE_MITIGATION_CHECKS, shared/sdlc_lifecycle.py; CI job
``outbound-send-surface-scan``). It names every send surface the diff adds,
removes or changes. It exits 1 on a new or changed send path that
config/outbound-send-surfaces.yaml does not list at head, or on a file in scope
it cannot parse. Detection lives in shared/outbound_send_surface.py.

Usage:
    check-outbound-send-surface-diff.py --base <rev> --head <rev>

Exit: 0 no unreviewed send surface; 1 unreviewed or unparseable; 2 git or registry error.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from shared.outbound_send_surface import REGISTRY_PATH, assess_diff, parse_registry  # noqa: E402

_repo = REPO_ROOT


def _git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(_repo), *args], capture_output=True, check=True).stdout


def _show(rev: str, path: str) -> bytes:
    """A blob the diff says exists. An unreadable blob raises; it is never absence."""
    return _git("show", f"{rev}:{path}")


def _tree_entry(rev: str, path: str) -> str:
    """The tree entry for ``path`` at ``rev`` ("" when absent), read without the blob."""
    return _git("ls-tree", rev, "--", path).decode()


def _executable(rev: str, path: str) -> bool:
    return _tree_entry(rev, path).startswith("100755")


def _changed(
    base: str, head: str
) -> dict[str, tuple[str | None, bytes | None, bytes | None, bool, bool]]:
    raw = _git("diff", "--name-status", "-M", "-z", f"{base}...{head}").decode()
    fields = raw.split("\0")
    changed: dict[str, tuple[str | None, bytes | None, bytes | None, bool, bool]] = {}
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        if status.startswith(("R", "C")):
            old, new = fields[index + 1], fields[index + 2]
            index += 3
        else:
            old = new = fields[index + 1]
            index += 2
        in_base = not status.startswith("A")
        in_head = not status.startswith("D")
        changed[new] = (
            old,
            _show(base, old) if in_base else None,
            _show(head, new) if in_head else None,
            _executable(base, old) if in_base else False,
            _executable(head, new) if in_head else False,
        )
    return changed


def _registry(rev: str, *, required: bool) -> str | None:
    if not _tree_entry(rev, REGISTRY_PATH):
        if required:
            raise ValueError(
                f"{REGISTRY_PATH} is missing at {rev}; a reviewed registry is required"
            )
        return None
    return _show(rev, REGISTRY_PATH).decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    global _repo
    _repo = args.repo
    try:
        changed = _changed(args.base, args.head)
        # The base may predate the registry. The head never may.
        base_registry = parse_registry(_registry(args.base, required=False))
        head_registry = parse_registry(_registry(args.head, required=True))
    except (subprocess.CalledProcessError, ValueError) as exc:
        detail = (
            exc.stderr.decode("utf-8", "replace").strip()
            if isinstance(exc, subprocess.CalledProcessError)
            else str(exc)
        )
        print(f"outbound-send-surface-scan: ERROR (refusing) {detail or exc}", file=sys.stderr)
        return 2
    verdict = assess_diff(changed, base_registry=base_registry, head_registry=head_registry)
    print(f"outbound-send-surface-scan {args.base}...{args.head}: {len(changed)} changed file(s)")
    if not verdict.changes:
        print("  no send surface added, removed or changed")
    for change in verdict.changes:
        state = "registered" if change.registered else "UNREVIEWED"
        if change.kind == "removed":
            state = "removed"
        print(
            f"  {change.kind:8} {change.path} [{state}] "
            f"base={sorted(change.base_vectors)} head={sorted(change.head_vectors)}"
        )
    for path in verdict.registered_in_diff:
        print(f"  registry+ {path} (listed in this diff: the review quorum judges it)")
    for problem in verdict.unparseable:
        print(f"  UNPARSEABLE {problem}")
    if verdict.ok:
        print("outbound-send-surface-scan: PASS")
        return 0
    print(
        "outbound-send-surface-scan: FAIL — list each new send path in "
        f"{REGISTRY_PATH} (reviewed with this diff) or remove it; fix unparseable files"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
