"""Grounding-source recruitment invariants (agents/hapax_daimonion/angle_resolver.py).

Pins the self-generated-slop exclusion: Hapax's own prior live-stream generations
("stream-reactions") must not be recruited as grounding sources — doing so both
grounds claims circularly on the system's own output and STYLE-CONTAMINATES the
composer, which mimics the slop it is shown as exemplars. Verified 2026-06-14: the
live 35B regressed into the stream-reactions phrasing, yet the same model scores
coherence 4.25 (vs 2.0) when composing against clean sources.
"""

from __future__ import annotations

from unittest.mock import patch

from agents.hapax_daimonion import angle_resolver


def test_stream_reactions_excluded_from_grounding_collections() -> None:
    assert "stream-reactions" not in angle_resolver.QDRANT_COLLECTIONS
    # documents (external) remains the primary grounding corpus.
    assert "documents" in angle_resolver.QDRANT_COLLECTIONS


def test_stream_reactions_classified_self_generated() -> None:
    # The exclusion is principled and named, not an incidental omission.
    assert "stream-reactions" in angle_resolver._SELF_GENERATED_COLLECTIONS
    # A self-generated collection is never also a grounding collection.
    assert not set(angle_resolver._SELF_GENERATED_COLLECTIONS) & set(
        angle_resolver.QDRANT_COLLECTIONS
    )


def test_gather_sources_never_queries_self_generated_collection() -> None:
    # Behavioral pin (not just the constant): the recruiter must never ISSUE a
    # qdrant query against stream-reactions, so a future code path cannot
    # reintroduce self-citation while the constant test still passes.
    queried: list[str] = []

    def _fake_qdrant_search(collection: str, topic: str, limit: int = 5) -> list:
        queried.append(collection)
        return []

    with (
        patch("agents.programme_authors.asset_resolver._qdrant_search", _fake_qdrant_search),
        patch("agents.programme_authors.asset_resolver._vault_notes_for_topic", lambda *a, **k: []),
    ):
        angle_resolver._gather_sources("any topic")

    assert "stream-reactions" not in queried
    assert queried  # it did query the remaining (grounding) collections
