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


def _show(rev: str, path: str) -> bytes | None:
    try:
        return _git("show", f"{rev}:{path}")
    except subprocess.CalledProcessError:
        return None


def _executable(rev: str, path: str) -> bool:
    try:
        entry = _git("ls-tree", rev, "--", path).decode()
    except subprocess.CalledProcessError:
        return False
    return entry.startswith("100755")


def _changed(
    base: str, head: str
) -> dict[str, tuple[str | None, bytes | None, bytes | None, bool]]:
    raw = _git("diff", "--name-status", "-M", "-z", f"{base}...{head}").decode()
    fields = raw.split("\0")
    changed: dict[str, tuple[str | None, bytes | None, bytes | None, bool]] = {}
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        if status.startswith(("R", "C")):
            old, new = fields[index + 1], fields[index + 2]
            index += 3
        else:
            old = new = fields[index + 1]
            index += 2
        base_bytes = None if status.startswith("A") else _show(base, old)
        head_bytes = None if status.startswith("D") else _show(head, new)
        changed[new] = (old, base_bytes, head_bytes, _executable(head, new))
    return changed


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
        base_registry = parse_registry(_decode(_show(args.base, REGISTRY_PATH)))
        head_registry = parse_registry(_decode(_show(args.head, REGISTRY_PATH)))
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(f"outbound-send-surface-scan: ERROR {exc}", file=sys.stderr)
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


def _decode(data: bytes | None) -> str | None:
    return None if data is None else data.decode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
