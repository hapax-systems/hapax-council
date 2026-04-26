"""Refusal annex Publisher ABC subclass — V5 publication-bus integration.

Per cc-task ``leverage-mktg-refusal-annex-series`` Phase 2. Wraps the
Phase 1 renderer with the V5 publication-bus invariants:

1. **AllowlistGate** — only explicitly-registered annex slugs publish.
2. **Legal-name-leak guard** — annex bodies must never contain the
   operator's legal name (refusal artifacts use the operator-referent
   picker; legal name belongs in CITATION.cff and Zenodo creators only).
3. **Prometheus Counter** — per-surface per-result outcome.

The publisher writes one annex per :meth:`publish` call to
``{output_dir}/refusal-annex-{target}.md`` where ``target`` is the
annex slug (e.g., ``declined-bandcamp``).

Phase 2b will integrate this with :func:`agents.marketing.refusal_annex_renderer.publish_all_annexes`
so the orchestrator runs each annex through the publisher chain;
Phase 2a (this PR) ships the publisher class + surface registry entry
+ test coverage.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from agents.marketing.refusal_annex_renderer import (
    DEFAULT_ANNEX_OUTPUT_DIR,
    PER_ANNEX_FILENAME_PREFIX,
    REFUSAL_ANNEX_SLUGS,
)
from agents.publication_bus.publisher_kit import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)

log = logging.getLogger(__name__)

REFUSAL_ANNEX_SURFACE: str = "marketing-refusal-annex"
"""Stable surface identifier for the refusal annex publisher.
Mirrored in :data:`agents.publication_bus.surface_registry.SURFACE_REGISTRY`."""

DEFAULT_ANNEX_ALLOWLIST: AllowlistGate = load_allowlist(
    REFUSAL_ANNEX_SURFACE,
    list(REFUSAL_ANNEX_SLUGS),
)
"""Default allowlist permits the 8 seed slugs from the cc-task. Future
annexes register here as the operator's stance accretes additional
refusals."""


class RefusalAnnexPublisher(Publisher):
    """Local-file-write publisher for refusal annexes.

    Each :meth:`publish` writes one annex's rendered markdown to
    ``{output_dir}/refusal-annex-{target}.md``. The Publisher ABC's
    invariants enforce that:

    - The slug (``payload.target``) is explicitly registered.
    - The body (``payload.text``) contains no legal-name leak.
    - Outcomes counter-record on the canonical
      ``hapax_publication_bus_publishes_total`` metric.
    """

    surface_name: ClassVar[str] = REFUSAL_ANNEX_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_ANNEX_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, output_dir: Path = DEFAULT_ANNEX_OUTPUT_DIR) -> None:
        self.output_dir = output_dir

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        """Write the annex markdown to the per-slug output path."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{PER_ANNEX_FILENAME_PREFIX}{payload.target}.md"
        try:
            path.write_text(payload.text, encoding="utf-8")
        except OSError as exc:
            log.warning("refusal annex write failed for %s: %s", payload.target, exc)
            return PublisherResult(error=True, detail=f"write failed: {exc}")
        return PublisherResult(ok=True, detail=str(path))


__all__ = [
    "DEFAULT_ANNEX_ALLOWLIST",
    "REFUSAL_ANNEX_SURFACE",
    "RefusalAnnexPublisher",
]
