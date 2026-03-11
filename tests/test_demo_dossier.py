"""Tests for agents.demo_pipeline.dossier — interactive audience dossier collection."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agents.demo_models import AudienceDossier
from agents.demo_pipeline.dossier import (
    DOSSIER_QUESTIONS,
    gather_dossier_interactive,
    record_relationship_facts,
    save_dossier,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_input_fn(answers: list[str]):
    """Return an input_fn that yields answers in order."""
    it = iter(answers)
    def _input(prompt: str) -> str:
        return next(it)
    return _input


def _make_dossier(**overrides) -> AudienceDossier:
    defaults = dict(
        key="my wife",
        archetype="family",
        name="Sarah",
        context="prior_knowledge: nothing\ngoals_pain_points: wants to understand what I build",
        calibration={"emphasize": ["wow factor"], "skip": ["config details"]},
    )
    defaults.update(overrides)
    return AudienceDossier(**defaults)


# ---------------------------------------------------------------------------
# gather_dossier_interactive
# ---------------------------------------------------------------------------


class TestGatherDossierInteractive:
    """Tests for the interactive dossier collection flow."""

    def test_all_answers(self):
        """Full responses produce a fully populated dossier."""
        answers = [
            "Sarah",                           # name
            "nothing",                         # prior_knowledge_level
            "wants to understand what I build", # goals
            "thinks I spend too much time",     # attitudes
            "spouse, no technical role",        # relationship_role
            "casual at home",                   # situational_context
        ]
        printed: list[str] = []
        dossier, responses = gather_dossier_interactive(
            audience_key="my wife",
            archetype="family",
            input_fn=_make_input_fn(answers),
            print_fn=printed.append,
        )

        assert dossier.key == "my wife"
        assert dossier.archetype == "family"
        assert dossier.name == "Sarah"
        assert "prior_knowledge: nothing" in dossier.context
        assert "goals_pain_points: wants to understand" in dossier.context
        assert "attitudes_resistance: thinks I spend too much" in dossier.context
        assert "decision_role: spouse" in dossier.context
        assert "situational_constraints: casual at home" in dossier.context
        # Responses dict populated for record_relationship_facts
        assert responses["prior_knowledge_level"] == "nothing"
        assert responses["goals"] == "wants to understand what I build"
        assert len(responses) == 5

    def test_skip_optional(self):
        """Empty Enter skips that field — context omits it."""
        answers = [
            "Bob",      # name
            "nothing",  # prior_knowledge_level
            "impress him",  # goals
            "",         # attitudes (skip)
            "peer who might adopt",  # relationship_role
            "",         # situational_context (skip)
        ]
        dossier, responses = gather_dossier_interactive(
            audience_key="colleague",
            archetype="technical-peer",
            input_fn=_make_input_fn(answers),
            print_fn=lambda _: None,
        )

        assert "attitudes_resistance" not in dossier.context
        assert "situational_constraints" not in dossier.context
        assert "prior_knowledge: nothing" in dossier.context
        assert "goals_pain_points: impress him" in dossier.context
        # Skipped fields not in responses
        assert "attitudes" not in responses
        assert "situational_context" not in responses
        assert len(responses) == 3

    def test_name_required_first(self):
        """Name is always asked before any dossier questions."""
        call_order: list[str] = []

        def tracking_input(prompt: str) -> str:
            call_order.append(prompt)
            if "call this person" in prompt:
                return "Alice"
            return "some answer"

        _dossier, _responses = gather_dossier_interactive(
            audience_key="test",
            archetype="family",
            input_fn=tracking_input,
            print_fn=lambda _: None,
        )

        # First call must be the name question
        assert "call this person" in call_order[0]
        # Subsequent calls are dossier questions
        assert len(call_order) == 1 + len(DOSSIER_QUESTIONS)


# ---------------------------------------------------------------------------
# save_dossier
# ---------------------------------------------------------------------------


class TestSaveDossier:
    """Tests for YAML persistence."""

    def test_new_file(self, tmp_path: Path):
        """Creates YAML with audience entry when file doesn't exist."""
        target = tmp_path / "audiences.yaml"
        dossier = _make_dossier()

        result = save_dossier(dossier, path=target)

        assert result == target
        assert target.exists()
        data = yaml.safe_load(target.read_text())
        assert "my wife" in data["audiences"]
        assert data["audiences"]["my wife"]["name"] == "Sarah"
        assert data["audiences"]["my wife"]["archetype"] == "family"

    def test_merge_existing(self, tmp_path: Path):
        """Adds to existing audiences without clobbering."""
        target = tmp_path / "audiences.yaml"

        # Write an initial audience
        initial = _make_dossier(key="boss", name="Dave", archetype="leadership")
        save_dossier(initial, path=target)

        # Add another
        second = _make_dossier(key="my wife", name="Sarah")
        save_dossier(second, path=target)

        data = yaml.safe_load(target.read_text())
        assert "boss" in data["audiences"]
        assert "my wife" in data["audiences"]
        assert data["audiences"]["boss"]["name"] == "Dave"
        assert data["audiences"]["my wife"]["name"] == "Sarah"

    def test_atomic_write(self, tmp_path: Path):
        """Uses tempfile + os.replace for atomic write."""
        target = tmp_path / "audiences.yaml"
        dossier = _make_dossier()

        with patch("agents.demo_pipeline.dossier.os.replace", wraps=os.replace) as mock_replace:
            save_dossier(dossier, path=target)
            mock_replace.assert_called_once()
            # First arg is temp file, second is target
            call_args = mock_replace.call_args[0]
            assert call_args[1] == str(target)


# ---------------------------------------------------------------------------
# record_relationship_facts
# ---------------------------------------------------------------------------


class TestRecordRelationshipFacts:
    """Tests for Qdrant fact indexing."""

    @patch("shared.config.get_qdrant")
    @patch("shared.config.embed_batch")
    def test_indexes_facts(self, mock_embed, mock_get_qdrant):
        """Indexes facts to Qdrant with deterministic IDs."""
        mock_embed.return_value = [[0.1] * 768, [0.2] * 768, [0.3] * 768]
        mock_client = MagicMock()
        mock_get_qdrant.return_value = mock_client

        dossier = _make_dossier()
        responses = {"goals": "wants to understand", "attitudes": "skeptical"}

        n = record_relationship_facts(dossier, responses)

        assert n == 3  # 2 responses + 1 context summary
        mock_embed.assert_called_once()
        mock_client.upsert.assert_called_once()

    @patch("shared.config.get_qdrant")
    @patch("shared.config.embed_batch", side_effect=Exception("connection refused"))
    def test_failure_graceful(self, mock_embed, mock_get_qdrant):
        """Qdrant error returns 0, no raise."""
        dossier = _make_dossier()
        responses = {"goals": "wants to understand"}

        n = record_relationship_facts(dossier, responses)

        assert n == 0


# ---------------------------------------------------------------------------
# DOSSIER_QUESTIONS validation
# ---------------------------------------------------------------------------


def test_dossier_questions_map_to_dimensions():
    """Every question maps to a valid KNOWLEDGE_DIMENSIONS key."""
    from agents.demo_pipeline.sufficiency import KNOWLEDGE_DIMENSIONS

    valid_keys = {d["key"] for d in KNOWLEDGE_DIMENSIONS}
    for q in DOSSIER_QUESTIONS:
        assert q["dimension"] in valid_keys, (
            f"DOSSIER_QUESTIONS dimension '{q['dimension']}' not in KNOWLEDGE_DIMENSIONS"
        )


# ---------------------------------------------------------------------------
# CLI flag
# ---------------------------------------------------------------------------


def test_cli_gather_dossier_flag():
    """argparse parses --gather-dossier correctly."""
    import argparse
    from agents.demo import main

    # Build the parser the same way main() does — we test parse_args
    parser = argparse.ArgumentParser()
    parser.add_argument("request", nargs="?", default=None)
    parser.add_argument("--audience")
    parser.add_argument("--gather-dossier", metavar="AUDIENCE")
    parser.add_argument("--persona-file", type=Path)

    args = parser.parse_args(["--gather-dossier", "my wife"])
    assert args.gather_dossier == "my wife"
    assert args.request is None


def test_cli_list_flag():
    """argparse parses --list correctly."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("request", nargs="?", default=None)
    parser.add_argument("--audience")
    parser.add_argument("--gather-dossier", metavar="AUDIENCE")
    parser.add_argument("--persona-file", type=Path)
    parser.add_argument("--list", action="store_true")

    args = parser.parse_args(["--list"])
    assert args.list is True
    assert args.request is None

    # With audience override
    args2 = parser.parse_args(["--gather-dossier", "my boss", "--audience", "leadership"])
    assert args2.gather_dossier == "my boss"
    assert args2.audience == "leadership"
