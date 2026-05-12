"""Publication-bus compliance pins for public social transports."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_public_social_transports_only_emit_from_publication_bus() -> None:
    """Mastodon/Bluesky API sends must stay inside bus publishers."""

    forbidden = re.compile(r"\.(?:send_post|status_post)\(")
    findings: list[str] = []
    for py_file in (REPO_ROOT / "agents").rglob("*.py"):
        rel = py_file.relative_to(REPO_ROOT)
        if rel.parts[:2] == ("agents", "publication_bus"):
            continue
        text = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            if forbidden.search(line):
                findings.append(f"{rel}:{line_no}: {line.strip()}")

    assert findings == [], (
        "Public social API egress must route through agents/publication_bus:\n"
        + "\n".join(findings)
    )
