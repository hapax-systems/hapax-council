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

    def test_markdown_code_fences_are_stripped(self):
        """Local LLMs routinely wrap their JSON response in ```json\\n...\\n```
        markdown fences even when the prompt asks for bare JSON. Without
        stripping, ``text.startswith('{')`` returns False, ``obj`` stays
        None, and _parse_intent_from_llm returns the parser_non_dict
        silence fallback (activity='silence', narrative_text='').

        Live regression seen 2026-04-21: every director tick through the
        director LLM produced `UNGROUNDED intent (activity=silence)` and
        `director micromove fallback reason=silence_or_empty`, because
        every raw response was fenced. Broadcast narrative was empty for
        hours until the fence was stripped.
        """
        fenced = (
            "```json\n"
            '{"activity": "music", "stance": "cautious",'
            ' "narrative_text": "drifting downtempo at dusk"}\n'
            "```"
        )
        intent = dl._parse_intent_from_llm(fenced)
        assert intent.activity == "music"
        assert "drifting" in intent.narrative_text

    def test_markdown_fence_without_language_tag(self):
        """Also handles ``` (no language tag) and trailing whitespace."""
        fenced = '```\n{"activity": "observe", "react": "glimmer at the edge"}\n```\n'
        intent = dl._parse_intent_from_llm(fenced)
        assert intent.activity == "observe"
        assert intent.narrative_text == "glimmer at the edge"

    def test_plain_json_still_works_after_fence_strip(self):
        """Regression guard: fence-strip must not break unfenced JSON."""
        intent = dl._parse_intent_from_llm('{"activity": "react", "react": "no fences here"}')
        assert intent.activity == "react"
        assert intent.narrative_text == "no fences here"

    def test_prose_markdown_fallback_extracts_fields(self):
        """Qwen3.5 and other local models occasionally emit markdown prose
        instead of JSON, like:

            **Activity:** music
            **Stance:** nominal
            **Narrative Text:** The track's rhythm carries a unique energy.

        Before this regex fallback every such response fell through to
        parser_non_dict → silence fallback → broadcast narrative empty.
        Observed 2026-04-21 post-TabbyAPI-restart.
        """
        prose = (
            "**Activity:** music\n"
            "**Stance:** nominal\n"
            "**Narrative Text:** The track's rhythm carries a unique, "
            "almost tribal energy through intricate hand drums."
        )
        intent = dl._parse_intent_from_llm(prose)
        assert intent.activity == "music"
        assert "tribal energy" in intent.narrative_text

    def test_prose_without_markdown_bold(self):
        """Plain 'Key: value' form without **bold** should also parse."""
        prose = (
            "Activity: observe\n"
            "Stance: cautious\n"
            "Narrative Text: a slow drift across the visual field"
        )
        intent = dl._parse_intent_from_llm(prose)
        assert intent.activity == "observe"
        assert "slow drift" in intent.narrative_text

    def test_prose_fallback_does_not_swallow_garbage(self):
        """Non-JSON, non-keyed text should still silence-fallback."""
        intent = dl._parse_intent_from_llm("just a paragraph of text nothing parsable")
        assert intent.activity == "silence"
        assert intent.narrative_text == ""


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


class TestSilenceHoldImpingementDiagnostic:
    """``_silence_hold_impingement`` must mark itself ``diagnostic=True`` so
    the ActivityHeader gloss never renders silence-hold routing text on
    broadcast. Regression pin for the 2026-04-21 operator screenshot of
    ``MUSIC | Silence hold: maintain the current surface. stay``.
    """

    def test_silence_hold_is_diagnostic(self):
        imp = dl._silence_hold_impingement()
        assert imp.diagnostic is True

    def test_silence_hold_reason_propagates_to_grounding(self):
        imp = dl._silence_hold_impingement(reason="parser_non_dict")
        assert imp.grounding_provenance == []
        assert imp.synthetic_grounding_markers == ["fallback.parser_non_dict"]
        assert imp.diagnostic is True

    def test_parser_silence_fallback_carries_diagnostic_flag(self):
        """End-to-end: an empty LLM result flows through the parser and
        the resulting DirectorIntent's sole impingement is diagnostic."""
        intent = dl._parse_intent_from_llm("")
        assert intent.activity == "silence"
        assert len(intent.compositional_impingements) == 1
        assert intent.compositional_impingements[0].diagnostic is True


class TestR8GroundingActGate:
    """Pin the R8 grounding-act gate behavior.

    The gate REJECTS impingements with empty ``grounding_provenance`` AND
    no ``synthetic_grounding_markers``. This forces the LLM to emit real
    perceptual-field evidence per impingement. Without per-impingement
    provenance, all creative impingements get dropped → silence-hold
    fallback → lifeless broadcast. Regression for F6 audit finding.
    """

    def test_grounded_impingement_passes_gate(self):
        """Impingement with real grounding_provenance passes R8."""
        imp = CompositionalImpingement(
            narrative="cut to turntable close-up",
            intent_family="camera.hero",
            grounding_provenance=["ir.ir_hand_zone.turntable"],
        )
        result = dl._ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
        assert result is not None
        assert result.grounding_provenance == ["ir.ir_hand_zone.turntable"]

    def test_ungrounded_impingement_rejected(self):
        """Impingement with empty grounding_provenance AND no synthetic
        markers is REJECTED (returns None)."""
        imp = CompositionalImpingement(
            narrative="bias toward warm tones",
            intent_family="preset.bias",
        )
        result = dl._ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
        assert result is None

    def test_synthetic_marker_passes_gate(self):
        """Impingement with synthetic_grounding_markers (fallback path)
        passes the gate — silence-hold and parser-error impingements
        must survive."""
        imp = CompositionalImpingement(
            narrative="silence hold: maintain the current surface",
            intent_family="preset.bias",
            synthetic_grounding_markers=["fallback.silence_hold"],
        )
        result = dl._ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
        assert result is not None

    def test_ensure_intent_grounded_keeps_grounded_impingements(self):
        """Intent with grounded impingements passes through unchanged."""
        imp = CompositionalImpingement(
            narrative="beat-synced preset shift",
            intent_family="preset.bias",
            grounding_provenance=["audio.midi.beat_position"],
        )
        intent = DirectorIntent(
            activity="music",
            stance=Stance.NOMINAL,
            narrative_text="the beat opens up",
            compositional_impingements=[imp],
        )
        result = dl._ensure_intent_grounded(intent)
        assert len(result.compositional_impingements) == 1
        assert result.compositional_impingements[0].grounding_provenance == [
            "audio.midi.beat_position"
        ]

    def test_ensure_intent_grounded_substitutes_silence_hold(self):
        """If ALL impingements are ungrounded, the gate substitutes a
        silence-hold fallback so the no-vacuum invariant holds."""
        imp = CompositionalImpingement(
            narrative="ungrounded guess",
            intent_family="camera.hero",
        )
        intent = DirectorIntent(
            activity="react",
            stance=Stance.NOMINAL,
            narrative_text="hmm",
            compositional_impingements=[imp],
        )
        result = dl._ensure_intent_grounded(intent)
        assert len(result.compositional_impingements) == 1
        assert result.compositional_impingements[0].synthetic_grounding_markers == [
            "fallback.all_impingements_rejected_ungrounded"
        ]
        assert result.compositional_impingements[0].diagnostic is True

    def test_full_parse_with_per_impingement_provenance(self):
        """End-to-end: LLM emits per-impingement grounding_provenance →
        parse → R8 gate → impingement survives. Regression pin for the
        prompt-schema fix (F6)."""
        payload = json.dumps(
            {
                "activity": "music",
                "stance": "nominal",
                "narrative_text": "the beat opens up with hand drums",
                "grounding_provenance": ["audio.midi.beat_position"],
                "compositional_impingements": [
                    {
                        "narrative": "beat-synced camera cut to overhead",
                        "intent_family": "camera.hero",
                        "grounding_provenance": ["audio.midi.beat_position"],
                    },
                    {
                        "narrative": "warm tone preset bias",
                        "intent_family": "preset.bias",
                        "grounding_provenance": ["audio.spectral.warm_dominant"],
                    },
                ],
            }
        )
        intent = dl._parse_intent_from_llm(payload)
        # Both impingements should survive the R8 gate
        assert len(intent.compositional_impingements) == 2
        assert all(imp.grounding_provenance for imp in intent.compositional_impingements)
