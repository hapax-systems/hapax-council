from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "dependabot-auto-merge.yml"


def test_dependabot_label_creation_is_repo_scoped() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for match in re.finditer(r"gh label create needs-human(?P<body>.*?)(?:\n\s*\n|$)", text, re.S):
        assert '--repo "$GH_REPO"' in match.group("body")


def test_dependabot_pr_label_edit_is_repo_scoped() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "gh pr edit" in line and "--add-label" in line:
            assert '--repo "$GH_REPO"' in line
