"""Deprecated shim — re-exports the single source-of-truth notifier in shared.notify.

This module was a vendored fork of shared/notify.py that predated the governed P0
incident-intake wiring, so importers that called its ``send_notification`` bypassed the
intake (no coalesced P0 task, no desktop drain). It now re-exports ``shared.notify`` so
every importer inherits the intake routing + drain for free. Import from ``shared.notify``
directly in new code.
"""

from __future__ import annotations

from shared.notify import (
    briefing_uri,
    nudges_uri,
    obsidian_uri,
    send_enriched_notification,
    send_notification,
    send_webhook,
)

__all__ = [
    "briefing_uri",
    "nudges_uri",
    "obsidian_uri",
    "send_enriched_notification",
    "send_notification",
    "send_webhook",
]
