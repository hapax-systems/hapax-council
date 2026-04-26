"""Tests for ``agents.cold_contact.graph_touch_policy``."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agents.cold_contact.candidate_registry import CandidateEntry
from agents.cold_contact.graph_touch_policy import (
    DEFAULT_MAX_CANDIDATES_PER_DEPOSIT,
    DEFAULT_MAX_TOUCHES_PER_YEAR,
    apply_cadence_rule,
    build_touch_related_identifiers,
    log_touch,
    score_candidate_for_deposit,
    select_candidates_for_deposit,
)


def _entry(
    name: str,
    orcid: str,
    audience_vectors: list[str],
    topic_relevance: list[str] | None = None,
) -> CandidateEntry:
    return CandidateEntry(
        name=name,
        orcid=orcid,
        audience_vectors=audience_vectors,
        topic_relevance=topic_relevance or [],
    )


class TestScoreCandidateForDeposit:
    def test_overlap_score_is_intersection_size(self) -> None:
        candidate = _entry(
            "x",
            "0000-0001-2345-6789",
            audience_vectors=["critical-ai", "infrastructure-studies"],
        )
        score = score_candidate_for_deposit(
            candidate,
            deposit_topics=[],
            deposit_audience_vectors=["critical-ai"],
        )
        assert score == 1.0

    def test_no_overlap_returns_zero(self) -> None:
        candidate = _entry("x", "0000-0001-2345-6789", audience_vectors=["sound-art"])
        score = score_candidate_for_deposit(
            candidate,
            deposit_topics=[],
            deposit_audience_vectors=["critical-ai"],
        )
        assert score == 0.0

    def test_topic_relevance_overlap_adds_bonus(self) -> None:
        candidate = _entry(
            "x",
            "0000-0001-2345-6789",
            audience_vectors=["critical-ai"],
            topic_relevance=["governance"],
        )
        with_topic = score_candidate_for_deposit(
            candidate,
            deposit_topics=["governance"],
            deposit_audience_vectors=["critical-ai"],
        )
        without_topic = score_candidate_for_deposit(
            candidate,
            deposit_topics=[],
            deposit_audience_vectors=["critical-ai"],
        )
        assert with_topic > without_topic


class TestSelectCandidatesForDeposit:
    def test_returns_top_n_by_score(self) -> None:
        a = _entry("a", "0000-0001-aaaa-aaaa", audience_vectors=["critical-ai"])
        b = _entry(
            "b",
            "0000-0001-bbbb-bbbb",
            audience_vectors=["critical-ai", "infrastructure-studies"],
        )
        c = _entry("c", "0000-0001-cccc-cccc", audience_vectors=["sound-art"])
        registry = [a, b, c]
        result = select_candidates_for_deposit(
            deposit_topics=[],
            deposit_audience_vectors=["critical-ai", "infrastructure-studies"],
            registry=registry,
            suppressions=set(),
            max_candidates=2,
        )
        # b has higher overlap than a; c has zero
        assert len(result) == 2
        assert result[0].orcid == "0000-0001-bbbb-bbbb"

    def test_skips_suppressed_orcids(self) -> None:
        a = _entry("a", "0000-0001-aaaa-aaaa", audience_vectors=["critical-ai"])
        b = _entry("b", "0000-0001-bbbb-bbbb", audience_vectors=["critical-ai"])
        result = select_candidates_for_deposit(
            deposit_topics=[],
            deposit_audience_vectors=["critical-ai"],
            registry=[a, b],
            suppressions={"0000-0001-aaaa-aaaa"},
            max_candidates=5,
        )
        assert all(c.orcid != "0000-0001-aaaa-aaaa" for c in result)

    def test_skips_zero_score_candidates(self) -> None:
        a = _entry("a", "0000-0001-aaaa-aaaa", audience_vectors=["sound-art"])
        result = select_candidates_for_deposit(
            deposit_topics=[],
            deposit_audience_vectors=["critical-ai"],
            registry=[a],
            suppressions=set(),
            max_candidates=5,
        )
        assert result == []

    def test_default_max_candidates_is_five(self) -> None:
        assert DEFAULT_MAX_CANDIDATES_PER_DEPOSIT == 5


class TestApplyCadenceRule:
    def test_filters_candidates_with_too_many_touches(self, tmp_path: Path) -> None:
        # Build a touches log: candidate A has 3 touches in last 365d
        log_path = tmp_path / "touches.jsonl"
        now = datetime.now(UTC)
        with log_path.open("w") as fh:
            for _ in range(3):
                fh.write(
                    json.dumps(
                        {
                            "orcid": "0000-0001-aaaa-aaaa",
                            "timestamp": now.isoformat(),
                        }
                    )
                    + "\n"
                )

        a = _entry("a", "0000-0001-aaaa-aaaa", audience_vectors=["critical-ai"])
        b = _entry("b", "0000-0001-bbbb-bbbb", audience_vectors=["critical-ai"])
        result = apply_cadence_rule(
            [a, b],
            log_path=log_path,
            max_touches_per_year=3,
        )
        # A is at the cap, B has zero touches
        assert b in result
        assert a not in result

    def test_old_touches_dont_count(self, tmp_path: Path) -> None:
        log_path = tmp_path / "touches.jsonl"
        old = datetime.now(UTC) - timedelta(days=400)
        with log_path.open("w") as fh:
            for _ in range(5):
                fh.write(
                    json.dumps(
                        {
                            "orcid": "0000-0001-aaaa-aaaa",
                            "timestamp": old.isoformat(),
                        }
                    )
                    + "\n"
                )

        a = _entry("a", "0000-0001-aaaa-aaaa", audience_vectors=["critical-ai"])
        result = apply_cadence_rule([a], log_path=log_path, max_touches_per_year=3)
        # Old touches don't count → A is eligible
        assert a in result

    def test_missing_log_treats_all_as_eligible(self, tmp_path: Path) -> None:
        a = _entry("a", "0000-0001-aaaa-aaaa", audience_vectors=["critical-ai"])
        result = apply_cadence_rule(
            [a], log_path=tmp_path / "missing.jsonl", max_touches_per_year=3
        )
        assert result == [a]

    def test_default_max_per_year_is_three(self) -> None:
        assert DEFAULT_MAX_TOUCHES_PER_YEAR == 3


class TestLogTouch:
    def test_appends_jsonl_entry(self, tmp_path: Path) -> None:
        log_path = tmp_path / "touches.jsonl"
        log_touch(
            orcid="0000-0001-aaaa-aaaa",
            deposit_doi="10.5281/zenodo.123",
            log_path=log_path,
        )
        lines = log_path.read_text().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["orcid"] == "0000-0001-aaaa-aaaa"
        assert entry["deposit_doi"] == "10.5281/zenodo.123"
        assert "timestamp" in entry

    def test_multiple_touches_accumulate(self, tmp_path: Path) -> None:
        log_path = tmp_path / "touches.jsonl"
        log_touch(
            orcid="0000-0001-aaaa-aaaa",
            deposit_doi="10.5281/zenodo.123",
            log_path=log_path,
        )
        log_touch(
            orcid="0000-0001-bbbb-bbbb",
            deposit_doi="10.5281/zenodo.124",
            log_path=log_path,
        )
        assert len(log_path.read_text().splitlines()) == 2


class TestBuildTouchRelatedIdentifiers:
    def test_returns_one_per_candidate(self) -> None:
        a = _entry("a", "0000-0001-aaaa-aaaa", audience_vectors=["critical-ai"])
        b = _entry("b", "0000-0001-bbbb-bbbb", audience_vectors=["critical-ai"])
        result = build_touch_related_identifiers([a, b])
        assert len(result) == 2
        # All should be IsCitedBy ORCID identifier
        for ri in result:
            assert ri.relation_type.value == "IsCitedBy"
            assert ri.identifier_type.value == "ORCID"

    def test_returns_orcid_url_form(self) -> None:
        a = _entry("a", "0000-0001-aaaa-aaaa", audience_vectors=["critical-ai"])
        result = build_touch_related_identifiers([a])
        # Identifier is the ORCID URL form
        assert result[0].identifier == "https://orcid.org/0000-0001-aaaa-aaaa"
