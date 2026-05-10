"""Tests for the segmented-content visual ward metadata path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.studio_compositor.segment_content_ward import (
    _read_segment_state,
    _role_label,
    _role_ward_defaults,
)
from shared.programme import SEGMENTED_CONTENT_FORMAT_SPECS


def test_role_label_covers_segmented_formats() -> None:
    assert _role_label("tier_list") == "TIER LIST"
    assert _role_label("top_10") == "TOP 10"
    assert _role_label("iceberg") == "ICEBERG"


@pytest.mark.parametrize("role_value,spec", list(SEGMENTED_CONTENT_FORMAT_SPECS.items()))
def test_role_ward_defaults_use_format_specs(role_value: str, spec) -> None:
    ward_profile, accent_role = _role_ward_defaults(role_value)
    assert ward_profile == spec.ward_profile
    assert accent_role == spec.ward_accent_role


def test_read_segment_state_preserves_sources_and_attribution(tmp_path: Path) -> None:
    state_path = tmp_path / "active-segment.json"
    state_path.write_text(
        json.dumps(
            {
                "programme_id": "prog-rant",
                "role": "rant",
                "topic": "source-backed topic",
                "narrative_beat": "rant on source-backed topic",
                "segment_beats": ["hook: open", "body: cite source"],
                "current_beat_index": 1,
                "started_at": 123.0,
                "planned_duration_s": 600.0,
                "source_refs": ["vault:source.md"],
                "asset_attributions": [
                    {
                        "source_ref": "vault:source.md",
                        "asset_kind": "vault_note",
                        "title": "Source Note",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    state = _read_segment_state(state_path)

    assert state.role == "rant"
    assert state.ward_profile == "argument_crescendo"
    assert state.ward_accent_role == "accent_red"
    assert state.source_refs == ("vault:source.md",)
    assert state.asset_attributions == ("Source Note [vault:source.md]",)
