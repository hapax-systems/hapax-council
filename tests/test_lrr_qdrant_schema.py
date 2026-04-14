"""LRR Phase 1 item 10 — Qdrant schema drift regression pin.

Pins the canonical 10-collection list documented in
docs/research/2026-04-14-qdrant-schema-drift-audit.md so a future
refactor of shared/qdrant_schema.py can't silently drop a collection
that LRR phases depend on.

Specifically guards:
- All 10 expected collections are present in EXPECTED_COLLECTIONS
- hapax-apperceptions and operator-patterns are present (Q026 Phase 4
  Finding 1 fix)
- stream-reactions is present (Phase 1 LRR uses this for per-segment
  metadata; backfill subcommand in research-registry.py targets it)

The other test_qdrant_schema.py file (if it exists) covers the schema
shape (vector size + distance) per-collection. This file is the LRR-
specific regression pin so the LRR audit references the test.
"""

from __future__ import annotations

from shared.qdrant_schema import EXPECTED_COLLECTIONS

LRR_PINNED_COLLECTIONS: tuple[str, ...] = (
    "profile-facts",
    "documents",
    "axiom-precedents",
    "operator-episodes",
    "studio-moments",
    "operator-corrections",
    "affordances",
    "stream-reactions",
    "hapax-apperceptions",
    "operator-patterns",
)


class TestLrrQdrantSchemaPin:
    def test_expected_collections_has_at_least_10(self) -> None:
        assert len(EXPECTED_COLLECTIONS) >= 10

    def test_all_lrr_pinned_collections_present(self) -> None:
        missing = [c for c in LRR_PINNED_COLLECTIONS if c not in EXPECTED_COLLECTIONS]
        assert not missing, f"LRR-pinned collections missing from EXPECTED_COLLECTIONS: {missing}"

    def test_q026_phase_4_finding_1_fix_present(self) -> None:
        # The two collections added by Q026 Phase 4 Finding 1 (alpha
        # close-out handoff) MUST be present.
        assert "hapax-apperceptions" in EXPECTED_COLLECTIONS
        assert "operator-patterns" in EXPECTED_COLLECTIONS

    def test_stream_reactions_present_for_lrr_phase_1(self) -> None:
        # LRR Phase 1 backfill (PR #792) tags stream-reactions with
        # condition_id. Schema must list it.
        assert "stream-reactions" in EXPECTED_COLLECTIONS

    def test_each_pinned_collection_has_size_and_distance(self) -> None:
        for name in LRR_PINNED_COLLECTIONS:
            spec = EXPECTED_COLLECTIONS[name]
            assert "size" in spec, f"{name} missing 'size'"
            assert "distance" in spec, f"{name} missing 'distance'"
