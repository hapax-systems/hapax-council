"""Regression pin for audit C1 (2026-04-18): every IntentFamily Literal
value must have at least one corresponding catalog entry, otherwise the
post-PR-#1044 family-restricted retrieval returns empty for that family
on every recruitment — silently failing.

Fail-mode caught: PRs #1038/#1039/#1046 promoted ward.* families to
first-class IntentFamily values + first-class prompt enum entries, but
shared/compositional_affordances.py only had entries for ward.highlight,
ward.staging, ward.choreography, ward.cadence — leaving ward.size,
ward.position, ward.appearance with zero catalog rows. Operator's
director would emit ``ward.size.album.grow-150pct`` impingements and
the pipeline would log ``returned no candidates`` every tick.

This test enforces the invariant. Adding a new IntentFamily without
backing catalog entries triggers a CI failure with a list of the
families missing entries.
"""

from __future__ import annotations

from typing import get_args

from shared.affordance_pipeline import AffordancePipeline
from shared.compositional_affordances import COMPOSITIONAL_CAPABILITIES
from shared.director_intent import IntentFamily


def test_every_intent_family_has_at_least_one_catalog_entry() -> None:
    """Audit C1 regression pin — every IntentFamily literal has ≥1 catalog row.

    Without this, family-restricted retrieval (PR #1044) returns empty
    candidates for the orphan family and recruitment silently fails.
    Uses ``_canonical_family_prefix`` (the same mapping the pipeline
    uses) so operator-legible family names like ``camera.hero`` resolve
    to their actual capability prefix ``cam.hero.``.
    """
    intent_families = list(get_args(IntentFamily))
    missing: list[str] = []
    catalog_names = [c.name for c in COMPOSITIONAL_CAPABILITIES]
    for family in intent_families:
        prefix = AffordancePipeline._canonical_family_prefix(family)
        if not any(name.startswith(prefix) for name in catalog_names):
            missing.append(family)
    assert not missing, (
        f"IntentFamily values without catalog entries: {missing}. "
        f"Family-restricted recruitment will fail silently for these. "
        f"Add entries to shared/compositional_affordances.py "
        f"(e.g., a new _WARD_<X> list folded into _WARD_AFFORDANCES). "
        f"Total catalog: {len(COMPOSITIONAL_CAPABILITIES)} entries across "
        f"{len(intent_families) - len(missing)}/{len(intent_families)} families."
    )


def test_seed_script_imports_canonical_pipeline() -> None:
    """Audit C2 regression pin — seed-compositional-affordances.py imports
    from shared.affordance_pipeline (the canonical path), NOT
    agents._affordance_pipeline (a refactor leftover that doesn't exist).
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "seed-compositional-affordances.py"
    text = script.read_text(encoding="utf-8")
    assert "from shared.affordance_pipeline import AffordancePipeline" in text, (
        "seed-compositional-affordances.py must import AffordancePipeline "
        "from shared.affordance_pipeline (the canonical path). "
        "If you see this fail, check the import block and ensure it's not "
        "regressed back to the broken agents._affordance_pipeline path."
    )
    assert "from agents._affordance_pipeline" not in text, (
        "seed-compositional-affordances.py imports from "
        "agents._affordance_pipeline — that module does not exist."
    )
