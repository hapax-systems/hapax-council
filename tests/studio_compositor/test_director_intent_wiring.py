"""Phase-1 wiring tests for director_loop → DirectorIntent → artifacts.

Covers `_parse_intent_from_llm`, `_emit_intent_artifacts`, and the legacy
flag short-circuit. Director loop integration is exercised indirectly
via the parsing helper; full loop tests live elsewhere.
"""

from __future__ import annotations

import json

import pytest

from agents.studio_compositor import director_loop as dl
from shared.director_intent import CompositionalImpingement, DirectorIntent
from shared.stimmung import Stance


def _test_impingement() -> CompositionalImpingement:
    """Stock CompositionalImpingement for DirectorIntent construction in tests.
    Operator invariant (2026-04-18) requires at least one per intent."""
    return CompositionalImpingement(
        narrative="test impingement: wiring exercise",
        intent_family="overlay.emphasis",
    )


class TestParseIntentFromLlm:
    def test_empty_result_returns_silence(self):
        intent = dl._parse_intent_from_llm("")
        assert intent.activity == "silence"
        assert intent.narrative_text == ""

    def test_legacy_shape_react(self):
        intent = dl._parse_intent_from_llm('{"activity": "react", "react": "what caught me"}')
        assert intent.activity == "react"
        assert intent.narrative_text == "what caught me"
        assert intent.stance == Stance.NOMINAL
        # Operator invariant (2026-04-18): legacy-shape fallback must still
        # populate a silence-hold impingement rather than emit empty.
        assert len(intent.compositional_impingements) == 1

    def test_legacy_shape_silence(self):
        intent = dl._parse_intent_from_llm('{"activity": "silence"}')
        assert intent.activity == "silence"
        assert intent.narrative_text == ""

    def test_full_director_intent_shape(self):
        payload = json.dumps(
            {
                "activity": "vinyl",
                "stance": "nominal",
                "narrative_text": "the record keeps going",
                "grounding_provenance": ["album.artist"],
                "compositional_impingements": [
                    {
                        "narrative": "turntable focus",
                        "intent_family": "camera.hero",
                    }
                ],
            }
        )
        intent = dl._parse_intent_from_llm(payload)
        assert intent.activity == "vinyl"
        assert intent.grounding_provenance == ["album.artist"]
        assert len(intent.compositional_impingements) == 1

    def test_malformed_json_returns_silence(self):
        intent = dl._parse_intent_from_llm("{not valid json")
        assert intent.activity == "silence"
        assert intent.narrative_text == ""

    def test_non_dict_json_returns_silence(self):
        intent = dl._parse_intent_from_llm('["a","b"]')
        assert intent.activity == "silence"

    def test_unknown_activity_in_legacy_shape_falls_back(self):
        intent = dl._parse_intent_from_llm('{"activity": "nonexistent", "react": "foo"}')
        assert intent.activity == "react"  # fallback used
        assert intent.narrative_text == ""

    def test_partial_modern_shape_preserves_narrative_text(self):
        """The local-fast LLM frequently emits a partial modern shape
        — {activity, stance, narrative_text} without the required
        compositional_impingements. The strict pydantic validation
        rejects it, falling through to the parser_legacy_shape path.
        Before this fix the parser only read ``react`` from the legacy
        shape; the LLM's ``narrative_text`` was silently discarded,
        leaving the broadcast with empty narrative for every partial
        response. Live regression seen 2026-04-21 — every director tick
        producing micromove fallback with empty narrative.
        """
        payload = json.dumps(
            {
                "activity": "music",
                "stance": "cautious",
                "narrative_text": "Solitude by nthng on the deck — drifting downtempo.",
            }
        )
        intent = dl._parse_intent_from_llm(payload)
        assert intent.activity == "music"
        assert "Solitude" in intent.narrative_text
        assert intent.stance == Stance.NOMINAL  # silence-hold construction sets nominal
        assert len(intent.compositional_impingements) == 1  # silence-hold impingement


class TestEmitIntentArtifacts:
    @pytest.fixture
    def tmp_paths(self, tmp_path, monkeypatch):
        jsonl = tmp_path / "director-intent.jsonl"
        narrative_state = tmp_path / "narrative-state.json"
        monkeypatch.setattr(dl, "_DIRECTOR_INTENT_JSONL", jsonl)
        monkeypatch.setattr(dl, "_NARRATIVE_STATE_PATH", narrative_state)
        return jsonl, narrative_state

    def test_jsonl_appended(self, tmp_paths):
        jsonl, _ = tmp_paths
        intent = DirectorIntent(
            activity="react",
            stance=Stance.NOMINAL,
            narrative_text="hello",
            compositional_impingements=[_test_impingement()],
        )
        dl._emit_intent_artifacts(intent, condition_id="cond-test-001")
        assert jsonl.exists()
        line = jsonl.read_text().strip()
        payload = json.loads(line)
        assert payload["activity"] == "react"
        assert payload["stance"] == "nominal"
        assert payload["condition_id"] == "cond-test-001"
        assert "emitted_at" in payload

    def test_narrative_state_written(self, tmp_paths):
        _, narrative_state = tmp_paths
        intent = DirectorIntent(
            activity="vinyl",
            stance=Stance.SEEKING,
            narrative_text="",
            compositional_impingements=[_test_impingement()],
        )
        dl._emit_intent_artifacts(intent, condition_id="cond-x")
        assert narrative_state.exists()
        state = json.loads(narrative_state.read_text())
        assert state["stance"] == "seeking"
        assert state["activity"] == "vinyl"
        assert state["condition_id"] == "cond-x"
        assert "last_tick_ts" in state

    def test_narrative_state_atomic_replace(self, tmp_paths):
        """Writing twice should not leave tmp files behind."""
        _, narrative_state = tmp_paths
        intent_a = DirectorIntent(
            activity="react",
            stance=Stance.NOMINAL,
            narrative_text="",
            compositional_impingements=[_test_impingement()],
        )
        intent_b = DirectorIntent(
            activity="silence",
            stance=Stance.CAUTIOUS,
            narrative_text="",
            compositional_impingements=[_test_impingement()],
        )
        dl._emit_intent_artifacts(intent_a, condition_id="c")
        dl._emit_intent_artifacts(intent_b, condition_id="c")
        state = json.loads(narrative_state.read_text())
        assert state["activity"] == "silence"
        # No stray tmp files
        leftover = list(narrative_state.parent.glob("*.tmp"))
        assert leftover == []

    def test_jsonl_failure_does_not_raise(self, tmp_path, monkeypatch):
        """If the JSONL write fails, the function swallows and continues."""
        # Point at a path that can't be created (parent is a file, not a dir).
        bad_parent = tmp_path / "file-not-dir"
        bad_parent.write_text("x")
        bad_jsonl = bad_parent / "director-intent.jsonl"
        monkeypatch.setattr(dl, "_DIRECTOR_INTENT_JSONL", bad_jsonl)
        monkeypatch.setattr(dl, "_NARRATIVE_STATE_PATH", tmp_path / "narrative-state.json")
        intent = DirectorIntent(
            activity="react",
            stance=Stance.NOMINAL,
            narrative_text="",
            compositional_impingements=[_test_impingement()],
        )
        # Should not raise
        dl._emit_intent_artifacts(intent, condition_id="c")
        # Narrative-state should still succeed independently.
        assert (tmp_path / "narrative-state.json").exists()


class TestLegacyFlag:
    def test_legacy_mode_env_true(self, monkeypatch):
        monkeypatch.setenv("HAPAX_DIRECTOR_MODEL_LEGACY", "1")
        assert dl._director_model_legacy_mode() is True

    def test_legacy_mode_env_yes(self, monkeypatch):
        monkeypatch.setenv("HAPAX_DIRECTOR_MODEL_LEGACY", "yes")
        assert dl._director_model_legacy_mode() is True

    def test_legacy_mode_env_unset(self, monkeypatch):
        monkeypatch.delenv("HAPAX_DIRECTOR_MODEL_LEGACY", raising=False)
        assert dl._director_model_legacy_mode() is False

    def test_legacy_mode_env_off(self, monkeypatch):
        monkeypatch.setenv("HAPAX_DIRECTOR_MODEL_LEGACY", "off")
        assert dl._director_model_legacy_mode() is False
