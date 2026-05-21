#!/usr/bin/env python3
"""cc-close sibling check: warn when closing a task while siblings under the
same parent_request remain offered/stalled.

Prevents the remediation execution gap where a request is marked fulfilled
while planned work items are never executed.

Exit 0 always (advisory, not blocking) — prints warnings to stderr.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

VAULT_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"


def _frontmatter_field(text: str, key: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fm = text[3:end]
    for line in fm.splitlines():
        m = re.match(rf"\s*{re.escape(key)}\s*:\s*(.+)", line)
        if m:
            return m.group(1).strip().strip("'\"")
    return None


def check_siblings(task_path: str) -> None:
    path = Path(task_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return

    parent = _frontmatter_field(text, "parent_request")
    if not parent:
        return

    active_dir = VAULT_ROOT / "active"
    if not active_dir.is_dir():
        return

    task_id = _frontmatter_field(text, "task_id") or ""
    stalled: list[str] = []

    for sibling in active_dir.glob("*.md"):
        try:
            sib_text = sibling.read_text(encoding="utf-8")
        except OSError:
            continue
        sib_parent = _frontmatter_field(sib_text, "parent_request")
        if sib_parent != parent:
            continue
        sib_id = _frontmatter_field(sib_text, "task_id") or ""
        if sib_id == task_id:
            continue
        sib_status = _frontmatter_field(sib_text, "status") or ""
        if sib_status in ("offered", "blocked"):
            stalled.append(f"  - {sib_id} (status: {sib_status})")

    if stalled:
        print(
            f"cc-close-sibling-check: WARNING — {len(stalled)} sibling task(s) "
            f"under {parent} remain unexecuted:",
            file=sys.stderr,
        )
        for line in stalled[:10]:
            print(line, file=sys.stderr)
        print(
            "  Consider: are these intentionally deferred, or should they be "
            "claimed before closing the parent request?",
            file=sys.stderr,
        )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        check_siblings(sys.argv[1])
