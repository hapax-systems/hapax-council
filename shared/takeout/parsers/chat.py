"""chat.py — Parser for Google Chat exports.

Google Chat Takeout includes JSON files organized by space/DM.
Format varies but typically:
- Groups/{space_name}/messages.json or similar
- DMs/{dm_name}/messages.json
- Each message has: {creator, created_date, text, ...}
"""
from __future__ import annotations

import json
import logging
import zipfile
from collections.abc import Iterator
from datetime import datetime

from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id

log = logging.getLogger("takeout.chat")


def parse(zf: zipfile.ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]:
    """Parse Google Chat messages from a Takeout ZIP."""
    prefix_options = [
        "Takeout/Google Chat/",
        "Google Chat/",
    ]

    for name in sorted(zf.namelist()):
        if not name.endswith(".json"):
            continue

        matched = False
        for prefix in prefix_options:
            if name.startswith(prefix):
                matched = True
                break

        if not matched:
            continue

        try:
            raw = zf.read(name)
            data = json.loads(raw)
        except (json.JSONDecodeError, KeyError) as e:
            log.debug("Skipping %s: %s", name, e)
            continue

        yield from _parse_chat_json(data, name, config)


def _parse_chat_json(
    data: dict | list,
    source_path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse chat messages from a JSON structure.

    Handles multiple formats:
    - {messages: [{creator, created_date, text}]}
    - [{creator, created_date, text}]
    """
    messages: list[dict] = []

    if isinstance(data, dict):
        messages = data.get("messages", [])
    elif isinstance(data, list):
        messages = data

    # Extract space/DM name from path
    space_name = _extract_space_name(source_path)

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        text = msg.get("text", "")
        if not text:
            continue

        # Creator info
        creator = msg.get("creator", {})
        if isinstance(creator, dict):
            sender = creator.get("name", creator.get("email", ""))
        elif isinstance(creator, str):
            sender = creator
        else:
            sender = ""

        # Timestamp
        timestamp = None
        created = msg.get("created_date", msg.get("create_time", ""))
        if created:
            timestamp = _parse_chat_time(created)

        # People
        people: list[str] = []
        if sender:
            people.append(sender)

        # Annotations (links, mentions)
        annotations = msg.get("annotations", [])
        for ann in annotations:
            if isinstance(ann, dict):
                user_mention = ann.get("userMention", {})
                if user_mention:
                    mention_name = user_mention.get("user", {}).get("name", "")
                    if mention_name and mention_name not in people:
                        people.append(mention_name)

        # Build title
        title = f"[{space_name}] {sender}: {text[:60]}" if space_name else f"{sender}: {text[:60]}"
        if len(text) > 60:
            title += "..."

        # Source key
        msg_id = msg.get("message_id", msg.get("name", f"{created}:{sender}:{text[:30]}"))
        record_id = make_record_id("google", "chat", msg_id)

        # Build full text with context
        text_parts = []
        if sender:
            text_parts.append(f"From: {sender}")
        if space_name:
            text_parts.append(f"Space: {space_name}")
        text_parts.append(f"\n{text}")

        yield NormalizedRecord(
            record_id=record_id,
            platform="google",
            service="chat",
            title=title,
            text="\n".join(text_parts),
            content_type="chat_message",
            timestamp=timestamp,
            modality_tags=list(config.modality_defaults),
            people=people,
            structured_fields={
                "space": space_name,
                "sender": sender,
            },
            data_path=config.data_path,
            source_path=source_path,
        )


def _extract_space_name(path: str) -> str:
    """Extract space/DM name from the ZIP path.

    "Takeout/Google Chat/Groups/Team Chat/messages.json" → "Team Chat"
    """
    parts = path.replace("\\", "/").split("/")
    # Find the part after "Groups" or "DMs"
    for i, part in enumerate(parts):
        if part in ("Groups", "DMs", "groups", "dms") and i + 1 < len(parts):
            return parts[i + 1]
    # Fallback: use parent directory name
    if len(parts) >= 2:
        return parts[-2]
    return ""


def _parse_chat_time(time_str: str) -> datetime | None:
    """Parse Google Chat timestamp formats."""
    if not time_str:
        return None

    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%A, %B %d, %Y at %I:%M:%S %p %Z",
        "%A, %B %d, %Y at %I:%M:%S %p",
    ):
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue

    # ISO fallback
    try:
        return datetime.fromisoformat(time_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
