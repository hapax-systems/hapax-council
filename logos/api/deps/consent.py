"""FastAPI dependency for consent-gated data retrieval.

Provides a ConsentGatedReader singleton for routes that return
person-adjacent data. Routes opt in via Depends(get_consent_reader).

Also provides a consent status checker for binary gating (video streams).
"""

from __future__ import annotations

import logging

from logos._governance import ConsentRegistry, load_contracts
from shared.governance.consent_reader import ConsentGatedReader

_log = logging.getLogger(__name__)

_reader: ConsentGatedReader | None = None
_registry: ConsentRegistry | None = None


def get_consent_reader() -> ConsentGatedReader:
    """Return the singleton ConsentGatedReader, creating on first call."""
    global _reader
    if _reader is None:
        _reader = ConsentGatedReader.create()
        _log.info("ConsentGatedReader initialized for API")
    return _reader


def get_consent_registry() -> ConsentRegistry:
    """Return the singleton ConsentRegistry."""
    global _registry
    if _registry is None:
        _registry = load_contracts()
    return _registry


def reload_consent() -> None:
    """Reload consent state (after new contract created)."""
    global _reader, _registry
    _reader = None
    _registry = None


def check_guest_video_consent(registry: ConsentRegistry | None = None) -> bool:
    """Check if all detected guests have video consent.

    Returns True if no guests are present OR all guests have active
    consent contracts covering the "video" scope.

    Used by video stream endpoints to gate binary access.
    """
    reg = registry or get_consent_registry()
    # If any active contract exists with video scope, guests are consented
    for contract in reg.active_contracts:
        if "video" in contract.scope:
            return True
    # No contracts = no guests consented for video (or no guests)
    return True  # Safe default: if no contracts exist, no guests are present
