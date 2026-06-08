"""Recruit-before-plan + thesis-object — inform authorship from RESOLVED sources.

The informed-authorship core (CASE-AUDIT-REMEDIATION-20260606): the planner must
author FROM resolved sources rather than inventing handles blind. Built on main's
``src:N`` handle-citation primitives (``build_resolved_source_set`` /
``validate_cited_handles``) — a thesis grounds in handles that dereference to a
recruited packet; a fabricated handle cannot resolve.
"""

from __future__ import annotations

import pytest

from shared.source_packet import (
    ResolvedSourceSet,
    SourcePacket,
    ThesisObject,
    affirmative_grounds,
    build_resolved_source_set,
    validate_cited_handles,
)


def _packet(idx: int, *, snippet: str = "operator reflection") -> SourcePacket:
    return SourcePacket(
        source_ref=f"vault:note-{idx}.md",
        content_hash=f"contenthash{idx:04d}",
        snippet=f"{snippet} {idx}",
        freshness="fresh",
        source_consequence=f"without note-{idx}, this perspective is absent",
    )


def _set(*idxs: int, topic: str = "operator reflective practice") -> ResolvedSourceSet:
    idxs = idxs or (0,)
    source_set = build_resolved_source_set(topic, tuple(_packet(i) for i in idxs))
    assert source_set is not None
    return source_set


# ── Layer 1: ThesisObject (Toulmin) grounded in src:N handles ────────────────


class TestThesisObject:
    def test_requires_non_empty_grounds(self) -> None:
        with pytest.raises(ValueError):
            ThesisObject(
                topic="t",
                claim="c",
                grounds=(),
                warrant="w",
                falsifier="f",
                source_consequence="sc",
            )

    def test_is_frozen(self) -> None:
        thesis = ThesisObject(
            topic="t",
            claim="c",
            grounds=("src:0",),
            warrant="w",
            falsifier="f",
            source_consequence="sc",
        )
        with pytest.raises(ValueError):
            thesis.claim = "mutated"  # type: ignore[misc]

    def test_grounds_validate_against_resolved_set(self) -> None:
        """A thesis grounded in real handles passes main's load-bearing gate."""
        source_set = _set(0, 1)
        thesis = ThesisObject(
            topic="t",
            claim="c",
            grounds=("src:0", "src:1"),
            warrant="w",
            falsifier="f",
            source_consequence="sc",
        )
        result = validate_cited_handles(source_set, thesis.grounds)
        assert result["ok"] is True
        assert result["unresolved"] == []

    def test_fabricated_handle_is_unresolved(self) -> None:
        source_set = _set(0)
        result = validate_cited_handles(source_set, ("src:0", "vault:governance-failures.md"))
        assert result["ok"] is False
        assert "vault:governance-failures.md" in result["unresolved"]


class TestAffirmativeGrounds:
    def test_keeps_resolvable_handles_drops_fabricated(self) -> None:
        source_set = _set(0, 1)
        bound = affirmative_grounds(("src:0", "vault:hallucinated.md", "src:1"), source_set)
        assert bound == ("src:0", "src:1")

    def test_no_resolvable_candidate_binds_to_full_set_not_empty(self) -> None:
        """The eval found over-bail on reflective vault notes. When nothing
        resolves, bind to EVERY handle — never empty (relevance was decided
        upstream by recruitment)."""
        source_set = _set(0, 1)
        bound = affirmative_grounds(("web:invented.com", "src:99"), source_set)
        assert bound == source_set.handles
        assert bound  # affirmative, never empty

    def test_dedupes_preserving_order(self) -> None:
        source_set = _set(0, 1)
        bound = affirmative_grounds(("src:1", "src:1", "src:0"), source_set)
        assert bound == ("src:1", "src:0")
