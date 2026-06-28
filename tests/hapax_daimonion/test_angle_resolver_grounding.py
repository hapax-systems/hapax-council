"""Grounding-source recruitment invariants (agents/hapax_daimonion/angle_resolver.py).

Pins the self-generated-slop exclusion: Hapax's own prior live-stream generations
("stream-reactions") must not be recruited as grounding sources — doing so both
grounds claims circularly on the system's own output and STYLE-CONTAMINATES the
composer, which mimics the slop it is shown as exemplars. Verified 2026-06-14: the
live 35B regressed into the stream-reactions phrasing, yet the same model scores
coherence 4.25 (vs 2.0) when composing against clean sources.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

from agents.hapax_daimonion import angle_resolver


def _packet(ref: str, content: str) -> angle_resolver.SourcePacket:
    return angle_resolver.SourcePacket(
        source_ref=ref,
        content_hash=hashlib.sha256(content.encode()).hexdigest()[:16],
        snippet=content[:200],
        freshness="fresh",
        source_consequence="test",
    )


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

    def _fake_qdrant_search_by_vector(
        collection: str, vector: list[float], *, limit: int = 5
    ) -> list:
        queried.append(collection)
        return []

    with (
        patch(
            "agents.programme_authors.asset_resolver._qdrant_search_by_vector",
            _fake_qdrant_search_by_vector,
        ),
        patch("agents.programme_authors.asset_resolver._vault_notes_for_topic", lambda *a, **k: []),
        patch("shared.config.embed_safe", lambda text, prefix=None: [0.0] * 768),
    ):
        angle_resolver._gather_sources("any topic")

    assert "stream-reactions" not in queried
    assert queried  # it did query the remaining (grounding) collections


def test_gather_sources_embeds_topic_once_not_per_collection() -> None:
    # Fix B: the recruit-density probe must embed the topic ONCE and reuse the vector
    # across all collections — was: one embed per collection (N re-embeds of the same
    # query, the probe's embed cost). One embed regardless of how many collections queried.
    embed_calls: list[str] = []

    def _fake_embed_safe(text, model=None, prefix=None, block_gpu=True):
        embed_calls.append(text)
        return [0.0] * 768

    with (
        patch(
            "agents.programme_authors.asset_resolver._qdrant_search_by_vector",
            lambda collection, vector, *, limit=5: [],
        ),
        patch("agents.programme_authors.asset_resolver._vault_notes_for_topic", lambda *a, **k: []),
        patch("shared.config.embed_safe", _fake_embed_safe),
    ):
        angle_resolver._gather_sources("a single topic")

    assert embed_calls == ["a single topic"]


def test_recruit_source_set_supplements_via_web_when_local_dry() -> None:
    # The load-bearing segment-time recruiter must reach the SAME web leg that the
    # plan-time recruiter (recruit_source_sets) and resolve_angle already have.
    # Without it, an open-world topic the planner grounded via web dies at segment
    # compose-time with no_resolved_sources — refused before the council ever sees
    # it (the recruiter asymmetry observed 2026-06-21).
    web_called: list[str] = []

    def _fake_tavily(topic: str, *, max_results: int = 3) -> list:
        web_called.append(topic)
        return [_packet("web:tavily:example", "real web grounding content")]

    with (
        patch.object(angle_resolver, "_gather_sources", lambda *a, **k: []),
        patch.object(angle_resolver, "_tavily_packets", _fake_tavily),
    ):
        result = angle_resolver.recruit_source_set("Operate Now Hospital governance")

    assert web_called, "recruit_source_set must supplement via web when local is dry"
    assert result is not None, "a web-groundable topic must resolve, not refuse"
    assert len(result.packets) == 1
    assert result.packets[0].source_ref.startswith("web:")


def test_recruit_source_set_prefers_local_no_web_when_local_present() -> None:
    # Local-first: when local packets already resolve, the web leg is NOT consulted
    # (the corpus-thickest-first philosophy + cost), mirroring recruit_source_sets'
    # _MIN_LOCAL_PACKETS_BEFORE_WEB gate.
    web_called: list[str] = []

    def _spy_tavily(topic: str, *, max_results: int = 3) -> list:
        web_called.append(topic)
        return []

    with (
        patch.object(
            angle_resolver,
            "_gather_sources",
            lambda *a, **k: [_packet("vault:note", "local content")],
        ),
        patch.object(angle_resolver, "_tavily_packets", _spy_tavily),
    ):
        result = angle_resolver.recruit_source_set("topic with local sources")

    assert not web_called, "web must not be consulted when local packets suffice"
    assert result is not None
    assert result.packets[0].source_ref.startswith("vault:")


def test_recruit_source_set_use_web_false_stays_local_only() -> None:
    # Escape hatch preserved: use_web=False reproduces the prior local-only behavior
    # (a dry local corpus refuses, never reaching the web).
    def _must_not_call(*_a: object, **_k: object) -> list:
        raise AssertionError("web consulted despite use_web=False")

    with (
        patch.object(angle_resolver, "_gather_sources", lambda *a, **k: []),
        patch.object(angle_resolver, "_tavily_packets", _must_not_call),
        # Re-angle uses the LOCAL model (not the web), so it is consistent with use_web=False;
        # mock it dry to keep this unit hermetic and assert the local-only exhaustion refusal.
        patch.object(angle_resolver, "_reangle_queries", lambda *a, **k: []),
    ):
        result = angle_resolver.recruit_source_set("dry topic", use_web=False)

    assert result is None


def test_gather_sources_reads_vault_note_content_not_path(tmp_path: Path) -> None:
    # Phase 0 ("make the matter readable"): a vault packet must carry the note's
    # ACTUAL TEXT (its named specifics), not the legacy "Vault note: <path>" stub —
    # the composer can only name what its sources contain, and the path names
    # nothing. The content_hash must bind to the real content, not the path.
    note = tmp_path / "attribution-void.md"
    note_text = (
        "The Brubaker v. Tidal case (2024) voided 412 licenses when the composer field went blank."
    )
    note.write_text(note_text, encoding="utf-8")

    with (
        patch("agents.programme_authors.asset_resolver.VAULT_ROOT", tmp_path),
        patch("agents.programme_authors.asset_resolver._qdrant_search", lambda *a, **k: []),
        patch(
            "agents.programme_authors.asset_resolver._vault_notes_for_topic",
            lambda *a, **k: ["attribution-void.md"],
        ),
    ):
        packets = angle_resolver._gather_sources("attribution void")

    vault = [p for p in packets if p.source_ref.startswith("vault:")]
    assert vault, "vault note should produce a packet"
    snippet = vault[0].snippet
    assert "Brubaker v. Tidal" in snippet and "412 licenses" in snippet, (
        "snippet must be the note's CONTENT (named specifics), not the path"
    )
    assert not snippet.startswith("Vault note:"), "must not be the legacy path stub"
    assert vault[0].content_hash == hashlib.sha256(note_text.encode()).hexdigest()[:16], (
        "content_hash must bind to the real note content, not the path"
    )
