"""labels.py — Proton Mail label and flag decoding.

Proton uses numeric label IDs and bitmask flags. This module
maps them to human-readable names for output routing and display.
"""

from __future__ import annotations

# Proton system label IDs → human-readable names
SYSTEM_LABELS: dict[str, str] = {
    "0": "Inbox",
    "1": "AllDrafts",
    "2": "AllSent",
    "3": "Trash",
    "4": "Spam",
    "5": "AllMail",
    "6": "Archive",
    "7": "Sent",
    "8": "Drafts",
    "10": "Starred",
    "12": "AllScheduled",
    "15": "AlmostAllMail",
    "16": "Snoozed",
}

# Labels that indicate spam or trash (skip by default)
_SKIP_LABELS = {"3", "4"}

# Labels that indicate sent mail
_SENT_LABELS = {"2", "7"}

# Proton message flag bitmask values
_FLAG_BITS: dict[int, str] = {
    1: "received",
    2: "sent",
    4: "internal",
    8: "e2e",
    16: "auto",
    32: "replied",
    64: "replied_all",
    128: "forwarded",
    256: "auto_replied",
    512: "imported",
    1024: "opened",
    4096: "receipt_sent",
    8192: "receipt_request",
    65536: "public_key",
    131072: "sign",
    1048576: "unsubscribed",
    2097152: "scheduled_send",
    4194304: "alias",
    8388608: "phishing_auto",
    16777216: "suspicious",
    33554432: "ham_manual",
}


def is_spam_or_trash(label_ids: list[str]) -> bool:
    """Check if the email is in Spam or Trash."""
    return bool(_SKIP_LABELS & set(label_ids))


def is_sent(label_ids: list[str]) -> bool:
    """Check if the email is sent mail."""
    return bool(_SENT_LABELS & set(label_ids))


def decode_flags(flags: int) -> set[str]:
    """Decode a Proton flags bitmask to a set of human-readable flag names."""
    result: set[str] = set()
    for bit, name in _FLAG_BITS.items():
        if flags & bit:
            result.add(name)
    return result


def get_label_names(label_ids: list[str]) -> list[str]:
    """Convert label IDs to human-readable names.

    System labels get their name; custom labels (ID > 16) are returned as-is.
    """
    names: list[str] = []
    for lid in label_ids:
        if lid in SYSTEM_LABELS:
            names.append(SYSTEM_LABELS[lid])
        else:
            names.append(f"custom:{lid}")
    return names


def get_folder_name(label_ids: list[str]) -> str:
    """Get the primary folder name for output path routing."""
    for lid in label_ids:
        if lid in SYSTEM_LABELS:
            name = SYSTEM_LABELS[lid]
            if name in ("Inbox", "Sent", "Archive", "Drafts", "Starred"):
                return name.lower()
    return "mail"
