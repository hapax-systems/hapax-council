from __future__ import annotations

import json
from pathlib import Path

from agents.hapax_daimonion.programme_delivery_smoke import run_smoke
from agents.hapax_daimonion.programme_loop import (
    _active_segment_payload,
    programme_from_prepped_artifact,
)


def test_programme_delivery_smoke_completes_full_cycle(tmp_path: Path) -> None:
    result = run_smoke(output_dir=tmp_path, programme_id="programme-delivery-smoke-test")

    assert result.receipt["ok"] is True
    assert result.receipt["prep_manifest_ok"] is True
    assert result.receipt["programme_loaded"] is True
    assert result.receipt["beat_transition_count"] == 3
    assert result.receipt["director_command_count"] == 3
    assert result.receipt["tts_delivered_count"] == 3
    assert len(result.receipt["accepted_layouts"]) == 3
    assert len(result.receipt["screenshot_paths"]) == 3
    assert all(Path(path).exists() for path in result.receipt["screenshot_paths"])

    saved = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    assert saved["ok"] is True


def test_prepped_artifact_missing_bridge_fields_still_builds_programme() -> None:
    programme = programme_from_prepped_artifact(_prepped_artifact_without_bridge_fields())

    assert programme.role.value == "lecture"
    assert programme.content.role_contract["role"] == "lecture"
    assert "vault:hn-readiness-tree.md" in programme.content.source_refs

    active = programme.model_copy(update={"actual_started_at": 1000.0})
    payload = _active_segment_payload(active, programme.role.value, 0)

    assert payload["source_refs"]
    assert payload["current_beat_layout_intents"]


def test_programme_delivery_smoke_accepts_real_prepped_artifact_shape(tmp_path: Path) -> None:
    result = run_smoke(
        output_dir=tmp_path,
        prepped_artifact=_prepped_artifact_without_bridge_fields(),
        write_screenshots=False,
    )

    assert result.receipt["ok"] is True
    assert result.receipt["programme_id"] == "segment-01"
    assert result.receipt["beat_transition_count"] == 2
    assert result.receipt["director_command_count"] == 2
    assert len(result.receipt["accepted_layouts"]) == 2
    assert result.receipt["active_segment_layout_intent_counts"] == [1, 1]
    assert all(Path(path).exists() for path in result.receipt["active_segment_snapshot_paths"])


def _prepped_artifact_without_bridge_fields() -> dict:
    return {
        "programme_id": "segment-01",
        "role": "lecture",
        "topic": "How source receipts keep HN readiness auditable",
        "authority": "prior_only",
        "hosting_context": "hapax_responsible_live",
        "prepared_script": [
            "According to HN Readiness Tree, source receipts keep the launch claim inspectable.",
            "Compare the scratch receipt with the live runtime receipt before calling it ready.",
        ],
        "segment_beats": [
            "open: cite the readiness tree source receipt",
            "compare: separate scratch proof from live runtime proof",
        ],
        "segment_prep_contract": {
            "source_packet_refs": [
                {
                    "id": "packet:hn-readiness-tree",
                    "source_ref": "vault:hn-readiness-tree.md",
                    "evidence_refs": ["vault:hn-readiness-tree.md"],
                }
            ],
            "claim_map": [
                {
                    "claim_id": "claim:segment:1",
                    "beat_id": "beat-1",
                    "grounds": ["vault:hn-readiness-tree.md"],
                }
            ],
        },
        "beat_action_intents": [
            {
                "beat_index": 0,
                "beat_direction": "open: cite the readiness tree source receipt",
                "intents": [
                    {
                        "kind": "source_citation",
                        "evidence_refs": ["vault:hn-readiness-tree.md"],
                        "object_ref": "object:HN Readiness Tree",
                    }
                ],
            },
            {
                "beat_index": 1,
                "beat_direction": "compare: separate scratch proof from live runtime proof",
                "intents": [
                    {
                        "kind": "comparison",
                        "evidence_refs": [
                            "action:comparison:spoken",
                            "vault:hn-readiness-tree.md",
                        ],
                        "object_ref": "object:comparison:spoken",
                    }
                ],
            },
        ],
        "beat_layout_intents": [
            {
                "beat_id": "beat-1",
                "parent_beat_index": 0,
                "action_intent_kinds": ["cite_source"],
                "needs": ["source_visible"],
                "proposed_postures": ["asset_front"],
                "expected_effects": ["source_context_legible"],
                "evidence_refs": ["vault:hn-readiness-tree.md", "object:HN Readiness Tree"],
                "source_affordances": ["source_context"],
                "default_static_success_allowed": False,
            },
            {
                "beat_id": "beat-2",
                "parent_beat_index": 1,
                "action_intent_kinds": ["compare_referents"],
                "needs": ["comparison_visible"],
                "proposed_postures": ["comparison"],
                "expected_effects": ["comparison_legible"],
                "evidence_refs": [
                    "action:comparison:spoken",
                    "vault:hn-readiness-tree.md",
                    "object:comparison:spoken",
                ],
                "source_affordances": ["comparison"],
                "default_static_success_allowed": False,
            },
        ],
        "prepared_artifact_ref": {
            "ref": "prepared_artifact:"
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "artifact_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "authority": "prior_only",
            "projected_authority": "declares_layout_needs_only",
        },
        "layout_decision_contract": {"may_command_layout": False},
    }
