"""Tests for consent degradation levels 1-4 in agents._governance.degradation."""

from __future__ import annotations

from agents._governance.degradation import (
    degrade,
    degrade_to_existence,
    degrade_to_suppression,
)

UNCONSENTED = frozenset({"Alice", "bob@corp.com"})
CONTENT = "Meeting with Alice and bob@corp.com at 3pm"


def test_level1_returns_content_unchanged() -> None:
    result = degrade(CONTENT, UNCONSENTED, "calendar", level=1)
    assert result == CONTENT


def test_level2_abstracts_names() -> None:
    result = degrade(CONTENT, UNCONSENTED, "default", level=2)
    assert "Alice" not in result
    assert "bob@corp.com" not in result


def test_level2_is_default() -> None:
    explicit = degrade(CONTENT, UNCONSENTED, "default", level=2)
    implicit = degrade(CONTENT, UNCONSENTED, "default")
    assert explicit == implicit


def test_level3_returns_existence_only() -> None:
    result = degrade(CONTENT, UNCONSENTED, "calendar", level=3, item_count=2)
    assert "2 calendar events" in result
    assert "details withheld" in result
    assert "Alice" not in result
    assert "3pm" not in result


def test_level3_does_not_invoke_level2() -> None:
    result = degrade(CONTENT, UNCONSENTED, "calendar", level=3, item_count=1)
    assert "Someone" not in result
    assert "people" not in result


def test_level3_singular() -> None:
    result = degrade_to_existence("calendar", 1)
    assert "1 calendar event" in result
    assert "events" not in result


def test_level3_plural() -> None:
    result = degrade_to_existence("email", 5)
    assert "5 emails" in result


def test_level3_zero() -> None:
    result = degrade_to_existence("document", 0)
    assert "No documents found" in result


def test_level3_unknown_category() -> None:
    result = degrade_to_existence("sms", 3)
    assert "3 sms items" in result


def test_level4_returns_empty() -> None:
    result = degrade(CONTENT, UNCONSENTED, "calendar", level=4)
    assert result == ""


def test_level4_suppression_function() -> None:
    assert degrade_to_suppression() == ""


def test_level4_with_high_level() -> None:
    result = degrade(CONTENT, UNCONSENTED, "default", level=99)
    assert result == ""


def test_no_unconsented_returns_content_at_any_level() -> None:
    empty: frozenset[str] = frozenset()
    for level in (1, 2, 3, 4):
        result = degrade(CONTENT, empty, "calendar", level=level)
        assert result == CONTENT, f"level {level} should return content with no unconsented"


def test_level3_independent_of_content() -> None:
    result1 = degrade("sensitive data", UNCONSENTED, "email", level=3, item_count=1)
    result2 = degrade("different sensitive data", UNCONSENTED, "email", level=3, item_count=1)
    assert result1 == result2
    assert "sensitive" not in result1
