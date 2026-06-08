"""Recruit-before-plan + thesis-object — inform authorship from RESOLVED sources.

The informed-authorship core (CASE-AUDIT-REMEDIATION-20260606): the planner must
author FROM resolved sources rather than inventing handles blind. Built on main's
``src:N`` handle-citation primitives (``build_resolved_source_set`` /
``validate_cited_handles``) — a thesis grounds in handles that dereference to a
recruited packet; a fabricated handle cannot resolve.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agents.hapax_daimonion import angle_resolver
from agents.hapax_daimonion.angle_resolver import (
    rank_source_sets_by_density,
    recruit_source_sets,
)
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


# ── Layer 2: recruit_source_sets — plan-time slate recruiter ─────────────────


def _clock(*values: float):
    seq = iter(values)
    last = [0.0]

    def _now() -> float:
        try:
            last[0] = next(seq)
        except StopIteration:
            pass
        return last[0]

    return _now


def _gatherer(table: dict[str, list[int]]):
    """Stub _gather_sources: topic -> packet count (via _packet indices)."""

    def _gather(topic: str, *, max_per_collection: int = 5) -> list[SourcePacket]:
        return [_packet(i, snippet=topic) for i in table.get(topic, [])]

    return _gather


class TestRecruitSourceSets:
    def test_ranks_by_resolved_material_density(self, monkeypatch) -> None:
        monkeypatch.setattr(
            angle_resolver,
            "_gather_sources",
            _gatherer({"thin": [0], "dense": [1, 2, 3], "mid": [4, 5]}),
        )
        sets = recruit_source_sets(["thin", "dense", "mid"], use_web=False)
        assert [s.topic for s in sets] == ["dense", "mid", "thin"]
        assert all(isinstance(s, ResolvedSourceSet) for s in sets)

    def test_skips_topics_with_no_resolved_material(self, monkeypatch) -> None:
        monkeypatch.setattr(
            angle_resolver, "_gather_sources", _gatherer({"grounded": [0], "empty": []})
        )
        sets = recruit_source_sets(["grounded", "empty"], use_web=False)
        assert [s.topic for s in sets] == ["grounded"]

    def test_sets_are_handle_addressable(self, monkeypatch) -> None:
        monkeypatch.setattr(angle_resolver, "_gather_sources", _gatherer({"t": [0, 1]}))
        sets = recruit_source_sets(["t"], use_web=False)
        assert sets[0].handles == ("src:0", "src:1")
        assert sets[0].set_hash

    def test_caps_candidate_slate_width(self, monkeypatch) -> None:
        monkeypatch.setattr(
            angle_resolver,
            "_gather_sources",
            _gatherer({f"topic-{i}": [i] for i in range(10)}),
        )
        sets = recruit_source_sets(
            [f"topic-{i}" for i in range(10)], max_candidates=3, use_web=False
        )
        assert len(sets) == 3

    def test_budget_halts_recruitment(self, monkeypatch) -> None:
        calls: list[str] = []

        def _gather(topic: str, *, max_per_collection: int = 5) -> list[SourcePacket]:
            calls.append(topic)
            return [_packet(0)]

        monkeypatch.setattr(angle_resolver, "_gather_sources", _gather)
        sets = recruit_source_sets(
            ["t0", "t1", "t2"], budget_s=500.0, use_web=False, now=_clock(0.0, 0.0, 999.0)
        )
        assert calls == ["t0"]
        assert [s.topic for s in sets] == ["t0"]

    def test_web_supplements_when_local_is_sparse(self, monkeypatch) -> None:
        monkeypatch.setattr(angle_resolver, "_gather_sources", _gatherer({"open": []}))

        def _tavily(topic: str, *, max_results: int = 3) -> list[SourcePacket]:
            return [
                SourcePacket(
                    source_ref="web:tavily:https://example.com/a",
                    content_hash="webhash01",
                    snippet=f"web hit for {topic}",
                    freshness="fresh",
                    rights_status="web",
                    source_consequence="without web only local",
                )
            ]

        monkeypatch.setattr(angle_resolver, "_tavily_packets", _tavily)
        sets = recruit_source_sets(["open"], use_web=True)
        assert len(sets) == 1
        assert sets[0].packets[0].source_ref.startswith("web:tavily:")

    def test_web_not_called_when_disabled(self, monkeypatch) -> None:
        monkeypatch.setattr(angle_resolver, "_gather_sources", _gatherer({"t": []}))

        def _boom(*_a, **_k):  # pragma: no cover - must not run
            raise AssertionError("tavily must not run when use_web=False")

        monkeypatch.setattr(angle_resolver, "_tavily_packets", _boom)
        assert recruit_source_sets(["t"], use_web=False) == []


class TestRankSourceSetsByDensity:
    def test_orders_by_packet_count_descending(self) -> None:
        a = _set(0, topic="one")
        b = _set(1, 2, topic="two")
        assert [s.topic for s in rank_source_sets_by_density([a, b])] == ["two", "one"]


class TestTavilyPackets:
    def test_uses_a_configured_lane(self, monkeypatch) -> None:
        """Open-world recruit must use a lane present in config/tavily.yaml — an
        unconfigured lane raises TavilyConfigError, which _tavily_packets
        swallows, so the open-world recruit would silently yield nothing."""
        captured: dict[str, str] = {}

        class _Result:
            content = "a web hit about the topic"
            url = "https://example.com/a"

        class _Response:
            results = [_Result()]

        class _Client:
            def __init__(self, **_kwargs) -> None:
                pass

            def search(self, request) -> _Response:
                captured["lane"] = request.lane
                return _Response()

        monkeypatch.setattr("shared.tavily_client.TavilyClient", _Client)
        packets = angle_resolver._tavily_packets("open world topic")
        configured = yaml.safe_load(
            (Path(__file__).resolve().parents[2] / "config" / "tavily.yaml").read_text(
                encoding="utf-8"
            )
        )["lanes"]
        assert captured["lane"] in configured
        assert packets and packets[0].source_ref.startswith("web:tavily:")
