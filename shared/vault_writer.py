"""shared/vault_writer.py — System → Obsidian vault egress.

Writes structured markdown files to the Work vault. Obsidian Sync
picks up changes automatically and syncs to all devices (work laptop,
phone).

Note: import re at module level for slug generation.

Configuration:
    WORK_VAULT_PATH: Path to Work vault (default: ~/Documents/Work)
    PERSONAL_VAULT_PATH: Path to Personal vault (default: ~/Documents/Personal)

Vault layout:
    vault/30-system/                 System-managed folder
    vault/30-system/briefings/       Daily briefings (one per day)
    vault/30-system/digests/         Content digests (one per day)
    vault/30-system/nudges.md        Current nudge state (overwritten)
    vault/30-system/goals.md         Goal snapshot (overwritten)
    vault/30-system/profile-summary.md  Profile overview (overwritten on profiler run)
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from shared.config import VAULT_PATH
from shared.frontmatter_schemas import (
    BridgePromptFrontmatter,
    BriefingFrontmatter,
    DecisionFrontmatter,
    DigestFrontmatter,
    GoalsFrontmatter,
    NudgeFrontmatter,
    validate_frontmatter,
)

_log = logging.getLogger(__name__)
SYSTEM_DIR = VAULT_PATH / "30-system"
BRIEFINGS_DIR = SYSTEM_DIR / "briefings"
DIGESTS_DIR = SYSTEM_DIR / "digests"


def _ensure_dirs() -> None:
    """Create vault directory structure if it doesn't exist."""
    for d in (SYSTEM_DIR, BRIEFINGS_DIR, DIGESTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def write_to_vault(
    folder: str,
    filename: str,
    content: str,
    frontmatter: dict | None = None,
) -> Path | None:
    """Write a markdown file to the Obsidian vault.

    Args:
        folder: Subfolder under vault root (e.g. "system/briefings").
        filename: File name (e.g. "2026-03-01.md").
        content: Markdown body content.
        frontmatter: Optional YAML frontmatter dict.

    Returns:
        Path to the written file, or None if write failed.
    """
    try:
        _ensure_dirs()
        target_dir = VAULT_PATH / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename

        parts: list[str] = []
        if frontmatter:
            import yaml

            parts.append("---")
            parts.append(yaml.dump(frontmatter, default_flow_style=False).strip())
            parts.append("---")
            parts.append("")
        parts.append(content)

        full_content = "\n".join(parts)

        # Atomic write via tempfile
        import tempfile

        tmp_fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".md")
        try:
            with open(tmp_fd, "w", encoding="utf-8") as f:
                f.write(full_content)
            Path(tmp_path).replace(target)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

        _log.debug("vault: wrote %s", target)
        return target
    except (PermissionError, OSError) as exc:
        _log.warning("vault: failed to write %s/%s: %s", folder, filename, exc)
        return None


def write_briefing_to_vault(briefing_md: str) -> Path | None:
    """Write daily briefing to vault/system/briefings/YYYY-MM-DD.md.

    Args:
        briefing_md: Pre-formatted markdown string (from format_briefing_md).

    Returns:
        Path to the written file.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    fm = {
        "type": "briefing",
        "date": today,
        "source": "agents.briefing",
        "tags": ["system", "briefing"],
    }
    validate_frontmatter(fm, BriefingFrontmatter)
    return write_to_vault("30-system/briefings", f"{today}.md", briefing_md, frontmatter=fm)


def write_digest_to_vault(digest_md: str) -> Path | None:
    """Write content digest to vault/system/digests/YYYY-MM-DD-digest.md.

    Args:
        digest_md: Pre-formatted markdown string (from format_digest_md).

    Returns:
        Path to the written file.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    fm = {
        "type": "digest",
        "date": today,
        "source": "agents.digest",
        "tags": ["system", "digest"],
    }
    validate_frontmatter(fm, DigestFrontmatter)
    return write_to_vault("30-system/digests", f"{today}-digest.md", digest_md, frontmatter=fm)


def write_nudges_to_vault(nudges: list[dict]) -> Path | None:
    """Write current nudge state to vault/system/nudges.md.

    Overwrites the file each time — this is a live snapshot, not history.

    Args:
        nudges: List of nudge dicts with keys: priority, source, message, action.

    Returns:
        Path to the written file.
    """
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = ["# Active Nudges", f"*Updated {now}*", ""]

    if not nudges:
        lines.append("No active nudges.")
    else:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        for n in sorted(nudges, key=lambda x: -x.get("priority", 50)):
            pri = n.get("priority", 50)
            source = n.get("source", "unknown")
            msg = n.get("message", "")
            action = n.get("action", "")
            # Obsidian Tasks priority: ⏫ high (score>=65), 🔼 medium (50-64), 🔽 low (<50)
            # Higher priority_score = more urgent
            pri_emoji = " ⏫" if pri >= 65 else " 🔼" if pri >= 50 else " 🔽"
            lines.append(f"- [ ] ({source}) {msg}{pri_emoji} 📅 {today}")
            if action:
                lines.append(f"  - {action}")

    fm = {"type": "nudges", "updated": now, "source": "logos", "tags": ["system"]}
    validate_frontmatter(fm, NudgeFrontmatter)
    return write_to_vault("30-system", "nudges.md", "\n".join(lines), frontmatter=fm)


def write_goals_to_vault(goals: list[dict]) -> Path | None:
    """Write operator goals snapshot to vault/system/goals.md.

    Args:
        goals: List of goal dicts from operator.json.

    Returns:
        Path to the written file.
    """
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = ["# Operator Goals", f"*Synced {now}*", ""]

    for g in goals:
        name = g.get("name", g.get("id", "unnamed"))
        status = g.get("status", "unknown")
        desc = g.get("description", "")
        lines.append(f"## {name}")
        lines.append(f"**Status:** {status}")
        if desc:
            lines.append(f"\n{desc}")
        lines.append("")

    fm = {
        "type": "goals",
        "updated": now,
        "source": "operator.json",
        "tags": ["system"],
    }
    validate_frontmatter(fm, GoalsFrontmatter)
    return write_to_vault("30-system", "goals.md", "\n".join(lines), frontmatter=fm)


def create_decision_starter(decision_text: str, meeting_ref: str) -> Path | None:
    """Create a decision note starter doc in the vault."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    slug = re.sub(r"[^a-z0-9]+", "-", decision_text[:50].lower()).strip("-")
    if not slug:
        slug = "decision"

    content = "\n".join(
        [
            f"# Decision: {decision_text[:100]}",
            "",
            f"**Source:** [[{meeting_ref}]]",
            "",
            "## Decision",
            decision_text,
            "",
            "## Rationale",
            "",
            "",
            "## Consequences",
            "",
        ]
    )
    fm = {
        "type": "decision",
        "status": "decided",
        "date": today,
        "meeting-ref": meeting_ref,
        "auto-generated": True,
        "tags": ["decision", "system"],
    }
    validate_frontmatter(fm, DecisionFrontmatter)
    return write_to_vault("10-work/decisions", f"{today}-{slug}.md", content, frontmatter=fm)


def write_bridge_prompt_to_vault(prompt_name: str, prompt_md: str) -> Path | None:
    """Write a bridge zone prompt template to vault/32-bridge/prompts/{name}.md.

    Args:
        prompt_name: Filename (without extension) for the prompt.
        prompt_md: Pre-formatted markdown prompt content.

    Returns:
        Path to the written file.
    """
    fm = {
        "type": "bridge-prompt",
        "source": "system",
        "tags": ["bridge", "prompt"],
    }
    validate_frontmatter(fm, BridgePromptFrontmatter)
    return write_to_vault("32-bridge/prompts", f"{prompt_name}.md", prompt_md, frontmatter=fm)
