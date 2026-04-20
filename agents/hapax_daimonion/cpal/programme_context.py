"""Programme-context lookup for CPAL.

Phase 6 of the programme-layer plan. CPAL needs to know which Programme
is active so the impingement adapter can compose a programme-biased
surface threshold. This module is a thin lookup helper — it never
imports `agents.programme_manager` (which would introduce a circular
dep with the daimonion); instead it goes through the
``shared.programme_store`` filesystem-as-bus surface.

The provider is a callable so callers can inject test doubles. The
default ``default_provider`` reads the canonical store on every call;
callers that need to amortise the file read should wrap with their own
TTL cache.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from shared.programme import Programme
from shared.programme_store import default_store

log = logging.getLogger(__name__)


ProgrammeProvider = Callable[[], Programme | None]


def default_provider() -> Programme | None:
    """Return the currently-active Programme from the canonical store, or None.

    Filesystem read every call — fine at CPAL's tick cadence (impingements
    arrive at most a few per second; the store is a small JSONL file in
    the operator's home dir). Wrap with a TTL cache only if profiling
    shows it matters.
    """
    try:
        return default_store().active_programme()
    except Exception:
        log.debug("programme_context: lookup failed", exc_info=True)
        return None


def null_provider() -> Programme | None:
    """Test/dev provider — never returns a Programme."""
    return None


__all__ = ["ProgrammeProvider", "default_provider", "null_provider"]
