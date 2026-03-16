"""Tests for consent-gated reader — provable consent enforcement at retrieval boundary.

Algebraic properties:
1. Operator always passes (degradation_level == 1)
2. No consent = no names in output
3. Full consent = unchanged content
4. Monotonicity: more contracts → degradation_level ≤ fewer contracts
5. Idempotent: filter(filter(datum)) == filter(datum)
6. Writer/Reader symmetry: writer.allowed ↔ reader.degradation_level == 1

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from shared.governance.consent import ConsentContract, ConsentRegistry
from shared.governance.consent_reader import (
    ConsentGatedReader,
    RetrievedDatum,
)
from shared.governance.degradation import (
    degrade,
    degrade_calendar,
    degrade_default,
    degrade_document,
    degrade_email,
)
from shared.governance.person_extract import (
    extract_calendar_persons,
    extract_email_persons,
    extract_emails,
    extract_person_ids,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _registry_with(*contracts: ConsentContract) -> ConsentRegistry:
    reg = ConsentRegistry()
    for c in contracts:
        reg._contracts[c.id] = c
    return reg


def _contract(cid: str, person: str, scope: frozenset[str], active: bool = True) -> ConsentContract:
    return ConsentContract(
        id=cid,
        parties=("operator", person),
        scope=scope,
        revoked_at=None if active else "2026-01-01",
    )


def _reader(
    registry: ConsentRegistry,
    operator_ids: frozenset[str] = frozenset({"operator"}),
) -> ConsentGatedReader:
    return ConsentGatedReader(
        registry=registry,
        operator_ids=operator_ids,
    )


def _datum(
    content: str,
    person_ids: frozenset[str],
    category: str = "document",
    source: str = "test",
) -> RetrievedDatum:
    return RetrievedDatum(
        content=content,
        person_ids=person_ids,
        data_category=category,
        source=source,
    )


# ── Person Extraction Tests ──────────────────────────────────────────────────


class TestPersonExtract(unittest.TestCase):
    def test_extract_emails_from_text(self):
        text = "From alice@corp.com to bob@other.org about the project"
        result = extract_emails(text)
        assert result == frozenset({"alice@corp.com", "bob@other.org"})

    def test_extract_from_metadata_people_list(self):
        result = extract_person_ids("", metadata={"people": ["alice", "bob"]})
        assert result == frozenset({"alice", "bob"})

    def test_extract_from_metadata_from_field(self):
        result = extract_person_ids("", metadata={"from": "alice@corp.com"})
        assert "alice@corp.com" in result

    def test_extract_known_persons(self):
        result = extract_person_ids(
            "Alice mentioned the budget",
            known_persons=frozenset({"Alice"}),
        )
        assert "Alice" in result

    def test_extract_known_persons_case_insensitive(self):
        result = extract_person_ids(
            "alice mentioned the budget",
            known_persons=frozenset({"Alice"}),
        )
        assert "Alice" in result

    def test_extract_calendar_persons(self):
        text = "- 2026-03-15T10:00: Meeting (with Alice, bob@corp.com)"
        result = extract_calendar_persons(text)
        assert "Alice" in result
        assert "bob@corp.com" in result

    def test_extract_email_persons(self):
        text = "- From: alice@corp.com | Subject: Q2 Budget"
        result = extract_email_persons(text)
        assert "alice@corp.com" in result

    def test_empty_input(self):
        result = extract_person_ids("")
        assert result == frozenset()


# ── Degradation Tests ────────────────────────────────────────────────────────


class TestDegradation(unittest.TestCase):
    def test_calendar_all_unconsented(self):
        text = "- 10:00: Meeting (with Alice, Bob, Charlie)"
        result = degrade_calendar(text, frozenset({"Alice", "Bob", "Charlie"}))
        assert "3 people" in result
        assert "Alice" not in result
        assert "Bob" not in result

    def test_calendar_partial_unconsented(self):
        text = "- 10:00: Meeting (with Alice, Bob, Charlie)"
        result = degrade_calendar(text, frozenset({"Bob", "Charlie"}))
        assert "Alice" in result
        assert "2 others" in result
        assert "Bob" not in result

    def test_calendar_no_unconsented(self):
        text = "- 10:00: Meeting (with Alice, Bob)"
        result = degrade_calendar(text, frozenset())
        assert result == text

    def test_email_unconsented(self):
        text = "From: alice@corp.com | Subject: Q2"
        result = degrade_email(text, frozenset({"alice@corp.com"}))
        assert "alice@corp.com" not in result
        assert "[someone at corp.com]" in result
        assert "Q2" in result

    def test_document_name_replacement(self):
        text = "Alice mentioned the budget was over target"
        result = degrade_document(text, frozenset({"Alice"}))
        assert "Alice" not in result
        assert "Someone" in result
        assert "budget" in result

    def test_default_preserves_content(self):
        text = "The weather is nice today"
        result = degrade_default(text, frozenset())
        assert result == text

    def test_dispatch(self):
        text = "From: alice@corp.com"
        result = degrade(text, frozenset({"alice@corp.com"}), "email")
        assert "alice@corp.com" not in result


# ── ConsentGatedReader Core Tests ────────────────────────────────────────────


class TestConsentGatedReader(unittest.TestCase):
    """Property 1: Operator always passes."""

    def test_operator_only_full_access(self):
        registry = _registry_with()
        reader = _reader(registry, operator_ids=frozenset({"operator", "me@home.com"}))
        datum = _datum(
            "Meeting with me@home.com",
            frozenset({"me@home.com"}),
        )
        decision = reader.filter(datum)
        assert decision.degradation_level == 1
        assert decision.filtered_content == datum.content

    def test_no_persons_full_access(self):
        """Data with no person IDs passes through unchanged."""
        reader = _reader(_registry_with())
        datum = _datum("System status: all green", frozenset())
        decision = reader.filter(datum)
        assert decision.degradation_level == 1
        assert decision.filtered_content == datum.content


class TestNoConsentNoNames(unittest.TestCase):
    """Property 2: No consent = no names in output."""

    def test_unconsented_person_abstracted(self):
        reader = _reader(_registry_with())
        datum = _datum(
            "Alice mentioned the budget",
            frozenset({"Alice"}),
        )
        decision = reader.filter(datum)
        assert decision.degradation_level == 2
        assert "Alice" not in decision.filtered_content

    def test_unconsented_email_abstracted(self):
        reader = _reader(_registry_with())
        datum = _datum(
            "From: alice@corp.com | Subject: Q2",
            frozenset({"alice@corp.com"}),
            category="email",
        )
        decision = reader.filter(datum)
        assert "alice@corp.com" not in decision.filtered_content

    def test_mixed_consent(self):
        """Consented person stays, unconsented is abstracted."""
        registry = _registry_with(
            _contract("c1", "alice", frozenset({"document"})),
        )
        reader = _reader(registry)
        datum = _datum(
            "Alice and Bob discussed the budget",
            frozenset({"alice", "Bob"}),
        )
        decision = reader.filter(datum)
        assert decision.degradation_level == 2
        assert "Bob" not in decision.filtered_content
        # alice is consented but the name "Alice" in text is a different case
        # The degradation only replaces unconsented "Bob"


class TestFullConsentUnchanged(unittest.TestCase):
    """Property 3: Full consent = unchanged content."""

    def test_all_consented(self):
        registry = _registry_with(
            _contract("c1", "alice", frozenset({"document"})),
            _contract("c2", "bob", frozenset({"document"})),
        )
        reader = _reader(registry)
        datum = _datum(
            "Alice and Bob discussed the budget",
            frozenset({"alice", "bob"}),
        )
        decision = reader.filter(datum)
        assert decision.degradation_level == 1
        assert decision.filtered_content == datum.content

    def test_operator_plus_consented(self):
        registry = _registry_with(
            _contract("c1", "alice", frozenset({"calendar"})),
        )
        reader = _reader(registry, operator_ids=frozenset({"operator", "me@home.com"}))
        datum = _datum(
            "Meeting with Alice and me@home.com",
            frozenset({"alice", "me@home.com"}),
            category="calendar",
        )
        decision = reader.filter(datum)
        assert decision.degradation_level == 1


class TestMonotonicity(unittest.TestCase):
    """Property 4: More contracts → degradation_level ≤ fewer contracts."""

    def test_adding_contract_improves_level(self):
        # No contracts — should degrade
        reader_none = _reader(_registry_with())
        datum = _datum("Alice discussed budget", frozenset({"alice"}))
        decision_none = reader_none.filter(datum)

        # With contract — should not degrade
        reader_one = _reader(_registry_with(_contract("c1", "alice", frozenset({"document"}))))
        decision_one = reader_one.filter(datum)

        assert decision_one.degradation_level <= decision_none.degradation_level


class TestIdempotent(unittest.TestCase):
    """Property 5: filter(filter(datum)) == filter(datum)."""

    def test_idempotent_degradation(self):
        reader = _reader(_registry_with())
        datum = _datum(
            "Alice and bob@corp.com discussed budget",
            frozenset({"Alice", "bob@corp.com"}),
        )
        decision1 = reader.filter(datum)

        # Apply filter again to the degraded output
        datum2 = _datum(
            decision1.filtered_content,
            frozenset({"Alice", "bob@corp.com"}),
        )
        decision2 = reader.filter(datum2)

        assert decision2.filtered_content == decision1.filtered_content


# ── filter_tool_result Tests ─────────────────────────────────────────────────


class TestFilterToolResult(unittest.TestCase):
    def test_passthrough_system_tools(self):
        reader = _reader(_registry_with())
        result = reader.filter_tool_result("get_system_status", "All systems healthy")
        assert result == "All systems healthy"

    def test_calendar_tool_degraded(self):
        reader = _reader(_registry_with())
        text = "- 2026-03-15T10:00: Team sync (with Alice, bob@corp.com)"
        result = reader.filter_tool_result("get_calendar_today", text)
        assert "Alice" not in result
        assert "bob@corp.com" not in result

    def test_calendar_tool_consented(self):
        registry = _registry_with(
            _contract("c1", "Alice", frozenset({"calendar"})),
            _contract("c2", "bob@corp.com", frozenset({"calendar"})),
        )
        reader = _reader(registry)
        text = "- 2026-03-15T10:00: Team sync (with Alice, bob@corp.com)"
        result = reader.filter_tool_result("get_calendar_today", text)
        assert result == text

    def test_no_persons_passthrough(self):
        reader = _reader(_registry_with())
        text = "Your calendar is clear — no upcoming events."
        result = reader.filter_tool_result("get_calendar_today", text)
        assert result == text

    def test_unknown_tool_passthrough(self):
        reader = _reader(_registry_with())
        result = reader.filter_tool_result("some_future_tool", "data with alice@x.com")
        assert result == "data with alice@x.com"

    def test_search_documents_degraded(self):
        reader = _reader(_registry_with())
        text = "[report.md (gmail), relevance=0.85]\nFrom: alice@corp.com\nBudget report"
        result = reader.filter_tool_result("search_documents", text)
        assert "alice@corp.com" not in result

    def test_decisions_recorded(self):
        reader = _reader(_registry_with())
        reader.filter_tool_result(
            "get_calendar_today",
            "- 10:00: Meeting (with Alice)",
        )
        assert len(reader.decisions) == 1
        assert reader.decisions[0].unconsented_count > 0


# ── Hypothesis Tests ─────────────────────────────────────────────────────────

# Strategy for person IDs
_person_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_.-@"),
    min_size=3,
    max_size=20,
).filter(lambda s: s.strip() == s and len(s) >= 3)

_scope_st = st.frozensets(
    st.sampled_from(["document", "calendar", "email", "perception"]),
    min_size=1,
    max_size=4,
)


class TestHypothesis(unittest.TestCase):
    @given(
        person_ids=st.frozensets(_person_st, min_size=0, max_size=5),
        category=st.sampled_from(["document", "calendar", "email"]),
    )
    @settings(max_examples=100)
    def test_operator_always_passes(self, person_ids: frozenset[str], category: str):
        """Property 1: operator data always gets level 1."""
        operator_ids = frozenset({"operator"}) | person_ids
        reader = _reader(_registry_with(), operator_ids=operator_ids)
        datum = _datum("test content", person_ids, category=category)
        decision = reader.filter(datum)
        assert decision.degradation_level == 1

    @given(
        person=_person_st,
        scope=_scope_st,
    )
    @settings(max_examples=50)
    def test_consented_means_full_access(self, person: str, scope: frozenset[str]):
        """Property 3: full consent = level 1 for matching categories."""
        registry = _registry_with(_contract("c1", person, scope))
        reader = _reader(registry)
        for cat in scope:
            datum = _datum(f"Content about {person}", frozenset({person}), category=cat)
            decision = reader.filter(datum)
            assert decision.degradation_level == 1, (
                f"Expected level 1 for consented person {person} in {cat}"
            )

    @given(
        content=st.text(min_size=1, max_size=100),
        category=st.sampled_from(["document", "calendar", "email", "default"]),
    )
    @settings(max_examples=50)
    def test_empty_persons_is_level_1(self, content: str, category: str):
        """No persons = level 1 regardless of contracts."""
        reader = _reader(_registry_with())
        datum = _datum(content, frozenset(), category=category)
        decision = reader.filter(datum)
        assert decision.degradation_level == 1

    @given(
        person=_person_st,
        category=st.sampled_from(["document", "calendar", "email"]),
    )
    @settings(max_examples=50)
    def test_monotonicity(self, person: str, category: str):
        """Property 4: adding a contract can only improve (lower) degradation level."""
        datum = _datum(f"Content about {person}", frozenset({person}), category=category)

        reader_none = _reader(_registry_with())
        decision_none = reader_none.filter(datum)

        reader_one = _reader(_registry_with(_contract("c1", person, frozenset({category}))))
        decision_one = reader_one.filter(datum)

        assert decision_one.degradation_level <= decision_none.degradation_level


if __name__ == "__main__":
    unittest.main()
