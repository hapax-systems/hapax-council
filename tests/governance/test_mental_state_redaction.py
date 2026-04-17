"""Tests for shared.governance.mental_state_redaction (LRR Phase 6 §4.E)."""

from __future__ import annotations

import pytest


class TestIsMentalStateCollection:
    @pytest.mark.parametrize(
        "collection",
        [
            "operator-episodes",
            "operator-corrections",
            "operator-patterns",
            "profile-facts",
            "hapax-apperceptions",
        ],
    )
    def test_returns_true_for_mental_state(self, collection):
        from shared.governance.mental_state_redaction import is_mental_state_collection

        assert is_mental_state_collection(collection) is True

    @pytest.mark.parametrize(
        "collection",
        ["documents", "stream-reactions", "studio-moments", "affordances", "axiom-precedents"],
    )
    def test_returns_false_for_non_mental_state(self, collection):
        from shared.governance.mental_state_redaction import is_mental_state_collection

        assert is_mental_state_collection(collection) is False


class TestGetSafeSummary:
    def test_present_non_empty(self):
        from shared.governance.mental_state_redaction import get_safe_summary

        assert (
            get_safe_summary({"mental_state_safe_summary": "brief neutral summary"})
            == "brief neutral summary"
        )

    def test_strips_whitespace(self):
        from shared.governance.mental_state_redaction import get_safe_summary

        assert get_safe_summary({"mental_state_safe_summary": "  with padding  "}) == "with padding"

    def test_absent_returns_none(self):
        from shared.governance.mental_state_redaction import get_safe_summary

        assert get_safe_summary({"other_field": "x"}) is None

    def test_empty_returns_none(self):
        from shared.governance.mental_state_redaction import get_safe_summary

        assert get_safe_summary({"mental_state_safe_summary": ""}) is None
        assert get_safe_summary({"mental_state_safe_summary": "   "}) is None

    def test_non_string_returns_none(self):
        from shared.governance.mental_state_redaction import get_safe_summary

        assert get_safe_summary({"mental_state_safe_summary": 12}) is None
        assert get_safe_summary({"mental_state_safe_summary": ["list"]}) is None


class TestRedactMentalStateIfPublic:
    def test_non_mental_state_collection_passthrough(self, monkeypatch):
        from shared.governance import mental_state_redaction as mod

        monkeypatch.setattr(mod, "is_publicly_visible", lambda: True)
        payload = {"episode_text": "private narrative"}
        result = mod.redact_mental_state_if_public("documents", payload)
        assert result == payload

    def test_private_stream_passthrough(self, monkeypatch):
        from shared.governance import mental_state_redaction as mod

        monkeypatch.setattr(mod, "is_publicly_visible", lambda: False)
        payload = {"episode_text": "private narrative"}
        result = mod.redact_mental_state_if_public("operator-episodes", payload)
        assert result["episode_text"] == "private narrative"

    def test_public_with_safe_summary(self, monkeypatch):
        from shared.governance import mental_state_redaction as mod

        monkeypatch.setattr(mod, "is_publicly_visible", lambda: True)
        payload = {
            "episode_text": "operator was frustrated at vite hot-reload + mentioned frontend lead by name",
            "mental_state_safe_summary": "operator in frustrated-with-tooling mode for 2h",
            "timestamp": "2026-04-17T12:00",
        }
        result = mod.redact_mental_state_if_public("operator-episodes", payload)
        assert result["episode_text"] == "operator in frustrated-with-tooling mode for 2h"
        assert (
            result["mental_state_safe_summary"] == "operator in frustrated-with-tooling mode for 2h"
        )
        # Non-content fields unchanged
        assert result["timestamp"] == "2026-04-17T12:00"

    def test_public_without_safe_summary_uses_placeholder(self, monkeypatch):
        from shared.governance import mental_state_redaction as mod

        monkeypatch.setattr(mod, "is_publicly_visible", lambda: True)
        payload = {"episode_text": "original narrative"}
        result = mod.redact_mental_state_if_public("operator-episodes", payload)
        assert "redacted" in result["episode_text"].lower()
        assert "original narrative" not in result["episode_text"]

    def test_public_redacts_multiple_content_fields(self, monkeypatch):
        """If a payload has more than one raw-content field, all get redacted."""
        from shared.governance import mental_state_redaction as mod

        monkeypatch.setattr(mod, "is_publicly_visible", lambda: True)
        payload = {
            "episode_text": "narrative A",
            "narrative": "narrative B",
            "text": "narrative C",
            "mental_state_safe_summary": "neutral",
        }
        result = mod.redact_mental_state_if_public("operator-episodes", payload)
        assert result["episode_text"] == "neutral"
        assert result["narrative"] == "neutral"
        assert result["text"] == "neutral"

    def test_input_payload_not_mutated(self, monkeypatch):
        """Call sites can safely pass originals — redaction returns a copy."""
        from shared.governance import mental_state_redaction as mod

        monkeypatch.setattr(mod, "is_publicly_visible", lambda: True)
        payload = {"episode_text": "original"}
        original_snapshot = dict(payload)
        mod.redact_mental_state_if_public("operator-episodes", payload)
        assert payload == original_snapshot


class TestRedactQueryResult:
    def test_redacts_points(self, monkeypatch):
        from shared.governance import mental_state_redaction as mod

        monkeypatch.setattr(mod, "is_publicly_visible", lambda: True)
        points = [
            {
                "id": "a",
                "score": 0.9,
                "payload": {"episode_text": "A", "mental_state_safe_summary": "safe A"},
            },
            {
                "id": "b",
                "score": 0.8,
                "payload": {"episode_text": "B"},  # no safe summary → placeholder
            },
        ]
        result = mod.redact_query_result("operator-episodes", points)
        assert result[0]["payload"]["episode_text"] == "safe A"
        assert "redacted" in result[1]["payload"]["episode_text"].lower()

    def test_handles_malformed_points_gracefully(self, monkeypatch):
        from shared.governance import mental_state_redaction as mod

        monkeypatch.setattr(mod, "is_publicly_visible", lambda: True)
        points: list = [{"id": "a"}, "not a dict", None, {"id": "b", "payload": "not a dict"}]
        # Should not crash; preserves input shape
        result = mod.redact_query_result("operator-episodes", points)
        assert len(result) == 4

    def test_non_mental_state_collection_passthrough(self, monkeypatch):
        from shared.governance import mental_state_redaction as mod

        monkeypatch.setattr(mod, "is_publicly_visible", lambda: True)
        points = [{"id": "a", "payload": {"episode_text": "raw"}}]
        result = mod.redact_query_result("documents", points)
        assert result[0]["payload"]["episode_text"] == "raw"
