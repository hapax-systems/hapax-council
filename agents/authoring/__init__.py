"""Hapax authoring infrastructure (V5 weave wk1 — epsilon).

Auto-compose pipeline + byline V0-V5 renderer + polysemic-audit CI
gate. Phase 0 of the publish bus (V5 weave inflection 2026-04-25T15:08Z).

Wk1 d1: scaffolding only. Wk1 d2: V0-V5 renderer completion.
Wk1 d4: polysemic_audit.py CI gate.
"""

from agents.authoring.byline import (
    Byline,
    BylineCoauthor,
    BylineVariant,
    render_byline,
)
from agents.authoring.polysemic_audit import (
    PolysemicAuditResult,
    PolysemicConcern,
    audit_artifact,
)

__all__ = [
    "Byline",
    "BylineCoauthor",
    "BylineVariant",
    "PolysemicAuditResult",
    "PolysemicConcern",
    "audit_artifact",
    "render_byline",
]
