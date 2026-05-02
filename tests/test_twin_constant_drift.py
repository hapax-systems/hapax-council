"""Pin shared constants on intentionally-vendored agents/_*.py twins.

R-18 audit-followup: ``agents/_*.py`` modules vendor a subset of their
``shared/*.py`` counterparts (``agents/_config.py:1-3`` documents the
pattern explicitly). The vendoring is intentional — agents/ keeps a
small, stable internal API surface that doesn't pull in the full shared/
module graph.

The drift risk is on **shared constants** (e.g. ``COLLECTION``,
``AUTHORITY_WEIGHTS``) that must match between twins or production code
will quietly partition. This test fails CI on any constant drift.

Extension is two lines per pair: add a tuple to ``TWIN_PAIRS`` and a
constant name to the relevant ``shared_constants`` set.
"""

from __future__ import annotations

import importlib

import pytest

# Each tuple: (canonical_module, vendored_module, shared_constants)
# When adding a new twin pair, list ONLY the constants whose values must
# match — implementation differences (CircuitBreaker wrappers, etc.) are
# intentional and not drift-risk.
TWIN_PAIRS = [
    # The audit's explicit cite — drift here partitions the agentic axiom-
    # precedent search across two collections.
    (
        "shared.axiom_precedents",
        "agents._axiom_precedents",
        {"COLLECTION", "AUTHORITY_WEIGHTS"},
    ),
    # Private stopword set used by both twin enforcement modules. Drift
    # here means one twin matches axiom-violation phrases the other misses.
    (
        "shared.axiom_enforcement",
        "agents._axiom_enforcement",
        {"_STOPWORDS"},
    ),
    # Apperception twin pair — cc-task r18-qdrant-twin-collapse-reconcile
    # (2026-05-02 reconcile pass). 5 ruminative-loop tuning constants
    # appear in both modules; drift would silently bias the imagination
    # ↔ apperception coupling on one side.
    (
        "shared.apperception",
        "agents._apperception",
        {
            "COHERENCE_FLOOR",
            "COHERENCE_CEILING",
            "DEFAULT_RELEVANCE_THRESHOLD",
            "RUMINATION_LIMIT",
            "RUMINATION_GATE_SECONDS",
        },
    ),
    # Dimensions twin pair has a STRUCTURAL twin (two distinct
    # DimensionDef classes) so the DIMENSIONS tuple cannot compare
    # equal across twins via value identity even when the data is
    # byte-identical. Drift detection for the dimension schema is
    # better expressed as a normalized name-list pin (see
    # ``test_dimension_name_parity_across_twins`` below) than as a
    # value-equality entry in TWIN_PAIRS. cc-task
    # ``r18-qdrant-twin-collapse-reconcile`` documents this in
    # ``docs/governance/r18-qdrant-twin-collapse-2026-04-26-reconcile.md``.
]


def test_dimension_name_parity_across_twins() -> None:
    """Pin dimension-name + kind parity across the two dimensions modules.

    ``shared.dimensions.DIMENSIONS`` and ``agents._dimensions.DIMENSIONS``
    are tuples of two DISTINCT ``DimensionDef`` dataclasses (each module
    defines its own). Tuple equality fails on class identity even when
    fields match. This pin uses a normalized projection
    ``(name, kind, interview_eligible)`` per entry so value-drift in the
    canonical 11-dimension profile schema is caught without false-
    failing on the twin's structural class duplication.

    Per cc-task ``r18-qdrant-twin-collapse-reconcile`` (2026-05-02
    reconcile pass).
    """
    import importlib

    shared_mod = importlib.import_module("shared.dimensions")
    agents_mod = importlib.import_module("agents._dimensions")
    shared_proj = [(d.name, d.kind, d.interview_eligible) for d in shared_mod.DIMENSIONS]
    agents_proj = [(d.name, d.kind, d.interview_eligible) for d in agents_mod.DIMENSIONS]
    assert shared_proj == agents_proj, (
        "Dimension schema drift: shared.dimensions.DIMENSIONS vs "
        "agents._dimensions.DIMENSIONS differ on (name, kind, "
        "interview_eligible) projection. Update both modules in the "
        "same PR — drift here partitions profile-fact writes across "
        "two divergent dimension definitions and silently corrupts the "
        "dimension index."
    )


@pytest.mark.parametrize(
    "canonical, vendored, constants",
    TWIN_PAIRS,
    ids=lambda v: v if isinstance(v, str) else "constants",
)
def test_twin_shared_constants_match(canonical: str, vendored: str, constants: set[str]) -> None:
    """Constant values must be identical across canonical + vendored twin."""
    canon_mod = importlib.import_module(canonical)
    vend_mod = importlib.import_module(vendored)

    for name in constants:
        if not hasattr(canon_mod, name):
            pytest.skip(f"{canonical} missing constant {name} — twin pair stale")
        if not hasattr(vend_mod, name):
            pytest.skip(f"{vendored} missing constant {name} — twin pair stale")

        canon_val = getattr(canon_mod, name)
        vend_val = getattr(vend_mod, name)
        assert canon_val == vend_val, (
            f"Twin drift: {canonical}.{name} != {vendored}.{name}\n"
            f"  canonical={canon_val!r}\n"
            f"  vendored ={vend_val!r}\n"
            f"R-18 vendoring rule: constants must match across twin pairs. "
            f"Update both modules in the same PR."
        )


def test_twin_pair_count_pinned() -> None:
    """Pin the cardinality so adding a new pair forces a deliberate test update.

    Extended 2026-05-02 from 2 → 3 value-pair pins per cc-task
    ``r18-qdrant-twin-collapse-reconcile`` (axiom_precedents +
    axiom_enforcement + apperception). The dimensions pair has a
    structural-twin shape (two DimensionDef classes) and is pinned
    via a separate ``test_dimension_name_parity_across_twins``
    projection test. The 5th known pair (``shared.impingement`` /
    ``agents._impingement``) is excluded because
    ``agents/_impingement.py`` is a re-export shim
    (``from shared.impingement import *``), not a vendored copy —
    drift is structurally impossible there.
    """
    assert len(TWIN_PAIRS) == 3, (
        "TWIN_PAIRS changed — extend the registry deliberately and update this pin."
    )
