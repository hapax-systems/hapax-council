"""Publication-bus compliance pins for public publication transports."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_public_transports_only_emit_from_publication_bus() -> None:
    """Public publication API writes must stay inside bus publishers."""

    forbidden = re.compile(
        r"\.(?:"
        r"send_post|status_post|post_status|add_block|"
        r"set_web|set_now|set_paste|create_purl|set_email|delete_entry"
        r")\("
    )
    findings: list[str] = []
    for root_name in ("agents", "scripts"):
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        py_files = root.rglob("*.py") if root.is_dir() else []
        for py_file in py_files:
            rel = py_file.relative_to(REPO_ROOT)
            if rel.parts[:2] == ("agents", "publication_bus"):
                continue
            text = py_file.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), 1):
                if forbidden.search(line):
                    findings.append(f"{rel}:{line_no}: {line.strip()}")

    assert findings == [], (
        "Public API egress must route through agents/publication_bus:\n" + "\n".join(findings)
    )
