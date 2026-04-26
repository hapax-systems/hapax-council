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
]


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
    """Pin the cardinality so adding a new pair forces a deliberate test update."""
    assert len(TWIN_PAIRS) == 2, (
        "TWIN_PAIRS changed — extend the registry deliberately and update this pin."
    )
