"""Attribution agents — Software Heritage SWHID + ORCID + DataCite leverage.

Per V5 weave drop-leverage strategy. The attribution package consolidates
the academic-citation-graph mechanics: SWH archive trigger + SWHID
collection (ISO/IEC 18670:2025), ORCID auto-update (when credentials
land), DataCite GraphQL mirror (post-Zenodo).

This package is the leverage-side companion to ``agents/publication_bus``
(which carries the publish-bus surfaces). Attribution is what happens
AFTER publication: making published artifacts discoverable via the
academic citation graph without sending direct outreach.
"""

from __future__ import annotations
