"""Phase-5c tests for StructuralDirector."""

from __future__ import annotations

import json

import pytest

from agents.studio_compositor import structural_director as sd


@pytest.fixture(autouse=True)
def _redirect_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(sd, "_STRUCTURAL_INTENT_PATH", tmp_path / "intent.json")
    monkeypatch.setattr(sd, "_STRUCTURAL_INTENT_JSONL", tmp_path / "structural-intent.jsonl")
    return tmp_path


class TestParseStructuralIntent:
    def test_full_shape_parses(self):
        raw = json.dumps(
            {
                "scene_mode": "hardware-play",
                "preset_family_hint": "audio-reactive",
                "long_horizon_direction": "the vinyl session is starting; sit with it for a while",
            }
        )
        intent = sd.parse_structural_intent(raw)
        assert intent is not None
        assert intent.scene_mode == "hardware-play"
        assert intent.preset_family_hint == "audio-reactive"
        assert "vinyl" in intent.long_horizon_direction

    def test_missing_field_returns_none(self):
        raw = json.dumps({"scene_mode": "hardware-play"})  # missing others
        assert sd.parse_structural_intent(raw) is None

    def test_unknown_scene_mode_rejected(self):
        raw = json.dumps(
            {
                "scene_mode": "bogus",
                "preset_family_hint": "audio-reactive",
                "long_horizon_direction": "x",
            }
        )
        assert sd.parse_structural_intent(raw) is None

    def test_empty_string_returns_none(self):
        assert sd.parse_structural_intent("") is None

    def test_non_json_returns_none(self):
        assert sd.parse_structural_intent("not json") is None


class TestTickOnce:
    def test_tick_writes_intent_file_and_jsonl(self, tmp_path):
        def stub_llm(prompt: str) -> str:
            return json.dumps(
                {
                    "scene_mode": "hardware-play",
                    "preset_family_hint": "audio-reactive",
                    "long_horizon_direction": "vinyl session",
                }
            )

        d = sd.StructuralDirector(llm_fn=stub_llm)
        out = d.tick_once()
        assert out is not None
        assert (tmp_path / "intent.json").exists()
        persisted = json.loads((tmp_path / "intent.json").read_text())
        assert persisted["scene_mode"] == "hardware-play"
        # JSONL also appended
        jsonl_lines = (tmp_path / "structural-intent.jsonl").read_text().splitlines()
        assert len(jsonl_lines) == 1

    def test_llm_failure_returns_none_and_keeps_prior(self, tmp_path):
        def failing_llm(prompt: str) -> str:
            raise RuntimeError("simulated LLM failure")

        d = sd.StructuralDirector(llm_fn=failing_llm)
        assert d.tick_once() is None
        # No intent file written
        assert not (tmp_path / "intent.json").exists()

    def test_unparseable_response_returns_none(self, tmp_path):
        def bad_llm(prompt: str) -> str:
            return "just some prose with no json"

        d = sd.StructuralDirector(llm_fn=bad_llm)
        assert d.tick_once() is None

    def test_multiple_ticks_accumulate_jsonl(self, tmp_path):
        calls = [
            json.dumps(
                {
                    "scene_mode": "hardware-play",
                    "preset_family_hint": "audio-reactive",
                    "long_horizon_direction": "vinyl",
                }
            ),
            json.dumps(
                {
                    "scene_mode": "idle-ambient",
                    "preset_family_hint": "calm-textural",
                    "long_horizon_direction": "operator stepped away",
                }
            ),
        ]
        idx = [0]

        def seq_llm(prompt: str) -> str:
            out = calls[idx[0]]
            idx[0] += 1
            return out

        d = sd.StructuralDirector(llm_fn=seq_llm)
        d.tick_once()
        d.tick_once()
        jsonl_lines = (tmp_path / "structural-intent.jsonl").read_text().splitlines()
        assert len(jsonl_lines) == 2

    def test_intent_carries_emitted_at_and_condition(self, tmp_path):
        def stub_llm(prompt: str) -> str:
            return json.dumps(
                {
                    "scene_mode": "desk-work",
                    "preset_family_hint": "warm-minimal",
                    "long_horizon_direction": "focused writing block",
                }
            )

        d = sd.StructuralDirector(llm_fn=stub_llm)
        out = d.tick_once()
        assert out is not None
        assert out.emitted_at > 0
        # condition_id falls back to "none" without a research-marker
        assert out.condition_id in ("none", "")
