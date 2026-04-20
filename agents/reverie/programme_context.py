"""Programme-context lookup for Reverie (Phase 8).

Mirrors ``agents.hapax_daimonion.cpal.programme_context`` — a thin
provider helper that goes through ``shared.programme_store`` so the
reverie mixer never imports ``agents.programme_manager`` (which would
introduce a circular dependency between the visual substrate and the
programme lifecycle).

The provider is a callable so callers can inject test doubles. The
default reads the canonical store on every call; the mixer ticks at
~10–30 Hz so a small JSON read in the operator's home dir is fine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from shared.programme import Programme
from shared.programme_store import default_store

log = logging.getLogger(__name__)


ProgrammeProvider = Callable[[], Programme | None]


def default_provider() -> Programme | None:
    """Return the active Programme from the canonical store, or ``None``."""
    try:
        return default_store().active_programme()
    except Exception:
        log.debug("reverie programme_context: lookup failed", exc_info=True)
        return None


def null_provider() -> Programme | None:
    """Test/dev provider — always returns ``None``."""
    return None


__all__ = ["ProgrammeProvider", "default_provider", "null_provider"]
