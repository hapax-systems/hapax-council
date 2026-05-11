"""Tests for layout authority validation — beat_id exemptions."""

from __future__ import annotations

import pytest

from shared.programme import _reject_layout_authority_fields


class TestBeatIdExemption:
    def test_surface_beat_id_allowed(self) -> None:
        intent = {
            "beat_id": "surface",
            "action_intent_kinds": ["show_evidence"],
            "needs": ["evidence_visible"],
            "proposed_postures": ["asset_front"],
            "expected_effects": ["evidence_on_screen"],
            "evidence_refs": ["vault:research-notes"],
            "source_affordances": ["asset:source-card"],
            "default_static_success_allowed": False,
        }
        _reject_layout_authority_fields(intent)

    def test_surface_level_beat_id_allowed(self) -> None:
        intent = {"beat_id": "surface_level", "needs": ["depth_visual"]}
        _reject_layout_authority_fields(intent)

    def test_layout_key_still_rejected(self) -> None:
        with pytest.raises(ValueError, match="layout authority"):
            _reject_layout_authority_fields({"layout": "segment-tier"})

    def test_surface_key_still_rejected(self) -> None:
        with pytest.raises(ValueError, match="layout authority"):
            _reject_layout_authority_fields({"surface": "compositor-main"})

    def test_command_value_still_rejected(self) -> None:
        with pytest.raises(ValueError, match="layout authority"):
            _reject_layout_authority_fields({"action": "command:switch-layout"})

    def test_nested_beat_id_in_list(self) -> None:
        intents = [
            {"beat_id": "hook", "needs": ["tier_visual"]},
            {"beat_id": "surface", "needs": ["depth_visual"]},
            {"beat_id": "close", "needs": ["chat_prompt"]},
        ]
        _reject_layout_authority_fields(intents)
