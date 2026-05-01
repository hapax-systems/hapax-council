"""Citable nexus front-door static-site renderer.

Per cc-task ``citable-nexus-front-door-static-site`` (WSJF 11.5).
Phase 0 ships the **renderer + content-generator** that produces the
canonical static HTML the eventual external repo
(``ryanklee/hapax-research``, deployed as ``hapax.research``) will
serve. The renderer reads from filesystem signals — surface registry,
attribution-block constants, refusal-annex output dir — and emits
self-contained HTML pages with V5 attribution boilerplate +
non-engagement clause on every footer.

Phase 0 (this module) ships four pages:

  - ``/`` (landing) — V5 byline + non-engagement clause + page index
  - ``/cite`` — canonical citation block (BibTeX, RIS, plaintext)
  - ``/refuse`` — REFUSED surface catalog rendered from
    :func:`agents.publication_bus.surface_registry.refused_surfaces`
  - ``/surfaces`` — full surface registry rendered as
    FULL_AUTO / CONDITIONAL_ENGAGE / REFUSED tiers

Phase 1+ (deferred):

  - ``/manifesto`` (Manifesto v0 rendering — content lives in operator
    vault, not in this repo; needs a vault-sync ingest step)
  - ``/refusal-brief`` (Refusal Brief rendering — same vault-sync
    requirement)
  - ``/deposits`` (recent Zenodo concept-DOIs from DataCite mirror —
    needs ``HAPAX_OPERATOR_ORCID`` configured + a daily snapshot;
    PR #2018 closed the ORCID config wire-up gap; the snapshot ledger
    still needs the operator's first nightly fire)
  - ``/citation-graph`` (DataCite-derived backlink network — needs
    a graph layout engine; deferred to Phase 2)

External-repo bootstrap is a separate operator-action — see
``docs/governance/citable-nexus-bootstrap-status.md`` §"Repo
Relocation Path" for the ``ryanklee/hapax-research`` setup sequence.

Constitutional posture: ``mode_ceiling: public_archive``. No
operator legal name in body text (V5 byline is the only authorship
surface; Oudepode is the operator-of-record referent). No
"Subscribe" / "Contact" / "Demo" CTAs. The non-engagement clause
appears on every page footer.
"""

from agents.citable_nexus.renderer import (
    PAGE_PATHS,
    PageMeta,
    RenderedSite,
    render_cite_page,
    render_landing_page,
    render_refuse_page,
    render_site,
    render_surfaces_page,
)

__all__ = [
    "PAGE_PATHS",
    "PageMeta",
    "RenderedSite",
    "render_cite_page",
    "render_landing_page",
    "render_refuse_page",
    "render_site",
    "render_surfaces_page",
]
