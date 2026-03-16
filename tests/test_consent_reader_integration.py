"""Integration tests for ConsentGatedReader with real tool output formats.

Tests against the actual output formats produced by voice tool handlers,
ensuring the reader correctly identifies and degrades person data.

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import unittest

from shared.governance.consent import ConsentContract, ConsentRegistry
from shared.governance.consent_reader import ConsentGatedReader


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
    operator_ids: frozenset[str] = frozenset({"operator", "me@home.com"}),
) -> ConsentGatedReader:
    return ConsentGatedReader(registry=registry, operator_ids=operator_ids)


class TestCalendarIntegration(unittest.TestCase):
    """Test against real get_calendar_today output format."""

    CALENDAR_OUTPUT = (
        "- 2026-03-15T09:00:00-05:00: 1:1 with Manager (with alice@corp.com)\n"
        "- 2026-03-15T10:00:00-05:00: Team standup (with alice@corp.com, bob@corp.com, charlie@corp.com)\n"
        "- 2026-03-15T14:00:00-05:00: Budget review (with dave@corp.com) @ Room 3B"
    )

    def test_no_consent_all_abstracted(self):
        reader = _reader(_registry_with())
        result = reader.filter_tool_result("get_calendar_today", self.CALENDAR_OUTPUT)

        # No email addresses should remain
        assert "alice@corp.com" not in result
        assert "bob@corp.com" not in result
        assert "charlie@corp.com" not in result
        assert "dave@corp.com" not in result

        # Event structure preserved
        assert "1:1 with Manager" in result
        assert "Team standup" in result
        assert "Budget review" in result
        assert "Room 3B" in result
        assert "2026-03-15" in result

    def test_partial_consent(self):
        registry = _registry_with(
            _contract("c1", "alice@corp.com", frozenset({"calendar"})),
        )
        reader = _reader(registry)
        result = reader.filter_tool_result("get_calendar_today", self.CALENDAR_OUTPUT)

        # Alice should remain, others abstracted
        assert "alice@corp.com" in result
        assert "bob@corp.com" not in result
        assert "charlie@corp.com" not in result

    def test_full_consent(self):
        registry = _registry_with(
            _contract("c1", "alice@corp.com", frozenset({"calendar"})),
            _contract("c2", "bob@corp.com", frozenset({"calendar"})),
            _contract("c3", "charlie@corp.com", frozenset({"calendar"})),
            _contract("c4", "dave@corp.com", frozenset({"calendar"})),
        )
        reader = _reader(registry)
        result = reader.filter_tool_result("get_calendar_today", self.CALENDAR_OUTPUT)
        assert result == self.CALENDAR_OUTPUT

    def test_empty_calendar(self):
        reader = _reader(_registry_with())
        result = reader.filter_tool_result(
            "get_calendar_today",
            "Your calendar is clear — no upcoming events.",
        )
        assert result == "Your calendar is clear — no upcoming events."


class TestEmailIntegration(unittest.TestCase):
    """Test against real search_emails output formats."""

    QDRANT_EMAIL_OUTPUT = (
        "[inbox-2026-03-14.md (gmail), relevance=0.92]\n"
        "From: alice@corp.com\n"
        "Subject: Q2 Budget Draft\n"
        "Hi team, attached is the Q2 budget draft...\n\n"
        "---\n\n"
        "[inbox-2026-03-13.md (gmail), relevance=0.78]\n"
        "From: bob@corp.com\n"
        "Subject: RE: Q2 Budget Draft\n"
        "Looks good, but can we adjust the R&D line?"
    )

    GMAIL_API_OUTPUT = (
        "- From: Alice Smith <alice@corp.com> | Subject: Q2 Budget | Date: 2026-03-14\n"
        "  Hi team, attached is the Q2 budget draft...\n"
        "- From: Bob Jones <bob@corp.com> | Subject: RE: Q2 Budget | Date: 2026-03-13\n"
        "  Looks good, but can we adjust the R&D line?"
    )

    def test_qdrant_email_no_consent(self):
        reader = _reader(_registry_with())
        result = reader.filter_tool_result("search_emails", self.QDRANT_EMAIL_OUTPUT)
        assert "alice@corp.com" not in result
        assert "bob@corp.com" not in result
        assert "Q2 Budget" in result

    def test_gmail_api_no_consent(self):
        reader = _reader(_registry_with())
        result = reader.filter_tool_result("search_emails", self.GMAIL_API_OUTPUT)
        assert "alice@corp.com" not in result
        assert "bob@corp.com" not in result

    def test_email_partial_consent(self):
        registry = _registry_with(
            _contract("c1", "alice@corp.com", frozenset({"email"})),
        )
        reader = _reader(registry)
        result = reader.filter_tool_result("search_emails", self.QDRANT_EMAIL_OUTPUT)
        assert "alice@corp.com" in result
        assert "bob@corp.com" not in result


class TestDocumentSearchIntegration(unittest.TestCase):
    """Test against real search_documents output format."""

    DOC_OUTPUT = (
        "[meeting-notes-2026-03-10.md (obsidian), relevance=0.88]\n"
        "# Team Meeting Notes\n"
        "Attendees: alice@corp.com, bob@corp.com\n"
        "Alice presented the roadmap update.\n"
        "Bob raised concerns about timeline.\n\n"
        "---\n\n"
        "[report.md (gdrive), relevance=0.75]\n"
        "The analysis by charlie@corp.com suggests..."
    )

    def test_no_consent_all_abstracted(self):
        reader = _reader(_registry_with())
        result = reader.filter_tool_result("search_documents", self.DOC_OUTPUT)
        assert "alice@corp.com" not in result
        assert "bob@corp.com" not in result
        assert "charlie@corp.com" not in result
        # Content preserved
        assert "Team Meeting Notes" in result
        assert "roadmap" in result


class TestSearchDriveIntegration(unittest.TestCase):
    """Test search_drive uses document category."""

    def test_drive_uses_document_category(self):
        reader = _reader(_registry_with())
        text = "[budget.xlsx (gdrive), relevance=0.9]\nShared by alice@corp.com"
        result = reader.filter_tool_result("search_drive", text)
        assert "alice@corp.com" not in result


class TestPassthroughTools(unittest.TestCase):
    """Verify system/UI tools pass through unfiltered."""

    PASSTHROUGH = [
        ("get_system_status", "All 99 checks healthy"),
        ("focus_window", '{"status": "focused", "window": "Firefox"}'),
        ("switch_workspace", '{"status": "switched", "workspace": 3}'),
        ("send_sms", '{"status": "pending_confirmation", "confirmation_id": "abc123"}'),
        ("check_consent_status", "wife has an active consent contract"),
        ("get_desktop_state", '{"windows": []}'),
    ]

    def test_all_passthrough(self):
        reader = _reader(_registry_with())
        for tool_name, content in self.PASSTHROUGH:
            result = reader.filter_tool_result(tool_name, content)
            assert result == content, f"{tool_name} should pass through"


class TestRevokedContract(unittest.TestCase):
    """Revoked contracts should not grant access."""

    def test_revoked_contract_degrades(self):
        registry = _registry_with(
            _contract("c1", "alice@corp.com", frozenset({"calendar"}), active=False),
        )
        reader = _reader(registry)
        text = "- 10:00: Meeting (with alice@corp.com)"
        result = reader.filter_tool_result("get_calendar_today", text)
        assert "alice@corp.com" not in result

    def test_scope_mismatch_degrades(self):
        """Contract for 'email' doesn't cover 'calendar' data."""
        registry = _registry_with(
            _contract("c1", "alice@corp.com", frozenset({"email"})),
        )
        reader = _reader(registry)
        text = "- 10:00: Meeting (with alice@corp.com)"
        result = reader.filter_tool_result("get_calendar_today", text)
        assert "alice@corp.com" not in result


class TestOperatorIdentity(unittest.TestCase):
    """Operator's own data always passes through."""

    def test_operator_email_passes(self):
        reader = _reader(
            _registry_with(),
            operator_ids=frozenset({"operator", "me@home.com"}),
        )
        text = "- 10:00: Meeting (with me@home.com, alice@corp.com)"
        result = reader.filter_tool_result("get_calendar_today", text)
        assert "me@home.com" in result
        assert "alice@corp.com" not in result


if __name__ == "__main__":
    unittest.main()
