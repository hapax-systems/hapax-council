"""CLI entry: ``uv run python -m agents.publication_bus``.

Surfaces the publication-bus wire-status registry as an operator-action
queue. For every CRED_BLOCKED publisher, prints the ``pass insert`` key
required to unblock wiring, alongside surface slug + rationale.

Phase 2 hook: when the operator runs each ``pass insert`` command, the
wire-status entry flips to WIRED via a follow-up adapter PR (one map
entry in ``publish_orchestrator._DISPATCH_MAP``).

``--check-creds`` polls the local ``pass`` store and emits the LIVE
status: keys present in pass become PRESENT (ready to wire), keys still
absent stay MISSING. This pairs with the cred-provisioner script
(``scripts/bootstrap_cred_tokens.py``, #1667) to give the operator a
"what's left to mint" view at a glance.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from agents.publication_bus.wire_status import (
    PUBLISHER_WIRE_REGISTRY,
    cred_blocked_pass_keys,
    status_summary,
)


def render_operator_queue() -> str:
    """Render the cred-blocked queue as a plain-text operator surface."""
    lines: list[str] = []
    summary = status_summary()
    lines.append("# Publication-bus wire-status")
    lines.append("")
    lines.append(f"WIRED:        {summary['WIRED']:>3}")
    lines.append(f"CRED_BLOCKED: {summary['CRED_BLOCKED']:>3}")
    lines.append(f"DELETE:       {summary['DELETE']:>3}")
    lines.append(f"Total:        {len(PUBLISHER_WIRE_REGISTRY):>3}")
    lines.append("")

    blocked = [
        (entry.surface_slug, entry.pass_key_required, module, entry.rationale)
        for module, entry in PUBLISHER_WIRE_REGISTRY.items()
        if entry.status == "CRED_BLOCKED"
    ]
    if blocked:
        lines.append("## CRED_BLOCKED — operator-action queue")
        lines.append("")
        for slug, pass_key, module, rationale in sorted(blocked):
            pass_display = pass_key or "(no pass key — see rationale)"
            lines.append(f"### {slug}")
            lines.append(f"- module:   {module}")
            lines.append(f"- pass:     {pass_display}")
            lines.append(f"- rationale: {rationale}")
            lines.append("")

    keys = cred_blocked_pass_keys()
    if keys:
        lines.append("## Unblocking pass commands")
        lines.append("")
        for k in keys:
            lines.append(f"  pass insert {k}")
        lines.append("")

    return "\n".join(lines)


def _key_present_in_pass(key: str) -> bool:
    """Return True iff ``pass show <key>`` exits 0."""
    if not shutil.which("pass"):
        return False
    try:
        result = subprocess.run(
            ["pass", "show", key],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return result.returncode == 0


def render_live_cred_status() -> str:
    """Poll pass-store for each CRED_BLOCKED key; emit PRESENT/MISSING per key."""
    lines: list[str] = []
    lines.append("# Publication-bus live cred-status")
    lines.append("")

    keys = cred_blocked_pass_keys()
    if not keys:
        lines.append("(no cred-blocked keys — all surfaces wired)")
        lines.append("")
        return "\n".join(lines)

    present: list[str] = []
    missing: list[str] = []
    for k in keys:
        (present if _key_present_in_pass(k) else missing).append(k)

    lines.append(f"PRESENT: {len(present):>3} / {len(keys)} cred-blocked keys")
    lines.append(f"MISSING: {len(missing):>3} / {len(keys)} cred-blocked keys")
    lines.append("")

    if present:
        lines.append("## Ready-to-wire (pass-store has the key)")
        lines.append("")
        for k in sorted(present):
            lines.append(f"  + {k}")
        lines.append("")

    if missing:
        lines.append("## Still cred-blocked")
        lines.append("")
        for k in sorted(missing):
            lines.append(f"  - {k}")
        lines.append("")
        lines.append("Run scripts/bootstrap_cred_tokens.py (#1667) to mint.")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keys-only",
        action="store_true",
        help="Print just the pass keys (one per line) for shell consumption",
    )
    parser.add_argument(
        "--check-creds",
        action="store_true",
        help="Poll the local pass-store and emit live PRESENT/MISSING per key",
    )
    args = parser.parse_args(argv)

    if args.keys_only:
        for k in cred_blocked_pass_keys():
            print(k)
        return 0

    if args.check_creds:
        sys.stdout.write(render_live_cred_status())
        return 0

    sys.stdout.write(render_operator_queue())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
