"""Briefing data collector — parses profiles/briefing.md."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


from shared.config import PROFILES_DIR


@dataclass
class ActionItem:
    priority: str  # "high" | "medium" | "low"
    action: str
    reason: str = ""
    command: str = ""


@dataclass
class BriefingData:
    headline: str = ""
    generated_at: str = ""
    body: str = ""
    action_items: list[ActionItem] = field(default_factory=list)


def collect_briefing() -> BriefingData | None:
    """Read and parse profiles/briefing.md."""
    path = PROFILES_DIR / "briefing.md"
    if not path.exists():
        return None

    text = path.read_text()
    if not text.strip():
        return None

    data = BriefingData()

    # Parse generated timestamp from "*Generated ... *" line
    ts_match = re.search(r"\*Generated\s+(\S+)", text)
    if ts_match:
        data.generated_at = ts_match.group(1)

    # Parse headline from "## <headline>" (first h2 after metadata)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## ") and i > 1:
            data.headline = line[3:].strip()
            break

    # Parse body — text between headline and next ##
    in_body = False
    body_lines: list[str] = []
    for line in lines:
        if line.startswith("## ") and in_body:
            break
        if in_body and line.strip():
            body_lines.append(line)
        if line.startswith("## ") and line[3:].strip() == data.headline:
            in_body = True

    data.body = "\n".join(body_lines).strip()

    # Parse action items from "## Action Items" section
    in_actions = False
    current_item: ActionItem | None = None
    for line in lines:
        if line.strip() == "## Action Items":
            in_actions = True
            continue
        if line.startswith("## ") and in_actions:
            break
        if not in_actions:
            continue

        # New action item: "- **[!!]** ..."
        item_match = re.match(r"^- \*\*\[([!.]{2})\]\*\*\s+(.+)", line)
        if item_match:
            if current_item:
                data.action_items.append(current_item)
            icon = item_match.group(1)
            priority = {"!!": "high", "! ": "medium", "..": "low"}.get(icon, "low")
            current_item = ActionItem(priority=priority, action=item_match.group(2))
            continue

        if current_item and line.strip().startswith("- "):
            detail = line.strip()[2:]
            if detail.startswith("`") and detail.endswith("`"):
                current_item.command = detail.strip("`")
            elif not current_item.reason:
                current_item.reason = detail

    if current_item:
        data.action_items.append(current_item)

    return data
