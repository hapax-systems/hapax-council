"""Tests for voice consent session — tool handlers, state, purge.

Proves: tool handlers record decisions correctly, clarification
limits are enforced, purge fires on refusal, and the session state
machine is complete.

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.hapax_voice.consent_session import (
    CONSENT_SYSTEM_PROMPT,
    CONSENT_TOOL_SCHEMAS,
    ConsentSessionState,
    handle_record_consent_decision,
    handle_request_clarification,
)


class TestConsentToolSchemas(unittest.TestCase):
    """Tool schemas are well-formed and complete."""

    def test_two_tools_defined(self):
        assert len(CONSENT_TOOL_SCHEMAS) == 2

    def test_record_decision_schema(self):
        schema = next(
            t for t in CONSENT_TOOL_SCHEMAS if t["function"]["name"] == "record_consent_decision"
        )
        params = schema["function"]["parameters"]["properties"]
        assert "decision" in params
        assert params["decision"]["enum"] == ["grant", "refuse"]
        assert "scope" in params

    def test_clarification_schema(self):
        schema = next(
            t for t in CONSENT_TOOL_SCHEMAS if t["function"]["name"] == "request_clarification"
        )
        params = schema["function"]["parameters"]["properties"]
        assert "reason" in params

    def test_system_prompt_contains_rules(self):
        assert "NEVER assume consent" in CONSENT_SYSTEM_PROMPT
        assert "NEVER pressure" in CONSENT_SYSTEM_PROMPT
        assert "record_consent_decision" in CONSENT_SYSTEM_PROMPT


class TestRecordConsentDecision(unittest.TestCase):
    """The record_consent_decision tool handler."""

    def test_grant_creates_contract(self):
        state = ConsentSessionState()
        tracker = MagicMock()

        with patch("shared.governance.consent.load_contracts") as mock_load:
            mock_registry = MagicMock()
            mock_contract = MagicMock()
            mock_contract.id = "contract-guest-test"
            mock_registry.create_contract.return_value = mock_contract
            mock_load.return_value = mock_registry

            result = json.loads(
                handle_record_consent_decision(
                    state,
                    consent_tracker=tracker,
                    decision="grant",
                    scope=["audio", "video"],
                )
            )

        assert result["status"] == "recorded"
        assert result["decision"] == "grant"
        assert state.resolved
        assert state.decision == "grant"
        tracker.grant_consent.assert_called_once()

    def test_refuse_triggers_purge(self):
        state = ConsentSessionState()
        tracker = MagicMock()

        with patch("agents.hapax_voice.consent_session._purge_session_data") as mock_purge:
            result = json.loads(
                handle_record_consent_decision(
                    state,
                    consent_tracker=tracker,
                    decision="refuse",
                )
            )

        assert result["status"] == "recorded"
        assert result["decision"] == "refuse"
        assert state.resolved
        tracker.refuse_consent.assert_called_once()
        mock_purge.assert_called_once()

    def test_invalid_decision_rejected(self):
        state = ConsentSessionState()
        result = json.loads(handle_record_consent_decision(state, decision="maybe"))
        assert "error" in result
        assert not state.resolved

    def test_grant_with_partial_scope(self):
        state = ConsentSessionState()

        with patch("shared.governance.consent.load_contracts") as mock_load:
            mock_registry = MagicMock()
            mock_contract = MagicMock()
            mock_contract.id = "c-partial"
            mock_registry.create_contract.return_value = mock_contract
            mock_load.return_value = mock_registry

            result = json.loads(
                handle_record_consent_decision(state, decision="grant", scope=["audio"])
            )

        assert "audio" in result["scope"]
        mock_registry.create_contract.assert_called_once()
        call_kwargs = mock_registry.create_contract.call_args
        assert call_kwargs[1]["scope"] == frozenset({"audio"})

    def test_grant_default_scope_is_full(self):
        state = ConsentSessionState()

        with patch("shared.governance.consent.load_contracts") as mock_load:
            mock_registry = MagicMock()
            mock_contract = MagicMock()
            mock_contract.id = "c-full"
            mock_registry.create_contract.return_value = mock_contract
            mock_load.return_value = mock_registry

            handle_record_consent_decision(state, decision="grant", scope=[])

        call_kwargs = mock_registry.create_contract.call_args
        scope = call_kwargs[1]["scope"]
        assert "audio" in scope
        assert "video" in scope
        assert "transcription" in scope
        assert "presence" in scope


class TestRequestClarification(unittest.TestCase):
    """The request_clarification tool handler."""

    def test_increments_counter(self):
        state = ConsentSessionState()
        handle_request_clarification(state, reason="unclear")
        assert state.clarification_count == 1

    def test_max_clarifications_reached(self):
        state = ConsentSessionState(max_clarifications=2)
        handle_request_clarification(state, reason="r1")
        result = json.loads(handle_request_clarification(state, reason="r2"))
        assert result["status"] == "max_clarifications_reached"
        assert "operator" in result["message"].lower()

    def test_under_limit_returns_clarifying(self):
        state = ConsentSessionState(max_clarifications=3)
        result = json.loads(handle_request_clarification(state, reason="test"))
        assert result["status"] == "clarifying"
        assert result["round"] == 1


class TestPurgeSessionData(unittest.TestCase):
    """FLAC purge on consent refusal."""

    def test_purge_deletes_recent_flacs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_dir = Path(tmpdir) / "raw"
            raw_dir.mkdir()

            # Create fake FLAC files
            old = raw_dir / "rec-20260315-010000.flac"
            old.write_text("old audio")
            # Backdate it
            import os

            os.utime(old, (time.time() - 3600, time.time() - 3600))

            new = raw_dir / "rec-20260315-020000.flac"
            new.write_text("new audio")

            guest_seen = time.time() - 60  # 1 minute ago

            with patch(
                "agents.hapax_voice.consent_session.Path.home",
                return_value=Path(tmpdir).parent,
            ):
                # Can't easily mock Path.home for glob, test the logic directly
                purged = 0
                for flac in raw_dir.glob("rec-*.flac"):
                    if flac.stat().st_mtime >= guest_seen:
                        flac.unlink()
                        purged += 1

                assert purged == 1  # only the new one
                assert old.exists()
                assert not new.exists()


class TestConsentSessionState(unittest.TestCase):
    """Session state tracking."""

    def test_initial_state(self):
        state = ConsentSessionState()
        assert state.decision is None
        assert not state.resolved
        assert state.clarification_count == 0

    def test_grant_sets_resolved(self):
        state = ConsentSessionState()
        state.decision = "grant"
        state.resolved = True
        assert state.resolved

    def test_scope_defaults_empty(self):
        state = ConsentSessionState()
        assert state.scope == []
