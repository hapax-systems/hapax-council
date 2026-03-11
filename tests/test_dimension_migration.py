"""Tests for the dimension migration script."""

import json

from scripts.migrate_profile_dimensions import migrate_profile, remap_dimension


def test_remap_identity_unchanged():
    assert remap_dimension("identity", "name") == "identity"


def test_remap_neurocognitive_profile():
    assert remap_dimension("neurocognitive_profile", "any_key") == "neurocognitive"


def test_remap_philosophy():
    assert remap_dimension("philosophy", "any_key") == "values"


def test_remap_team_leadership():
    assert remap_dimension("team_leadership", "any_key") == "management"


def test_remap_management_practice():
    assert remap_dimension("management_practice", "any_key") == "management"


def test_remap_workflow_tool_key():
    assert remap_dimension("workflow", "preferred_python_tool") == "tool_usage"


def test_remap_workflow_schedule_key():
    assert remap_dimension("workflow", "daily_schedule") == "work_patterns"


def test_remap_workflow_ambiguous_key():
    assert remap_dimension("workflow", "some_random_thing") == "work_patterns"


def test_remap_technical_skills_tool_key():
    assert remap_dimension("technical_skills", "python_proficiency") == "identity"


def test_remap_music_production_gear_key():
    assert remap_dimension("music_production", "sp404_workflow") == "creative_process"


def test_remap_music_production_aesthetic():
    assert remap_dimension("music_production", "preferred_bpm_range") == "values"


def test_remap_software_preferences():
    assert remap_dimension("software_preferences", "ide_choice") == "tool_usage"


def test_remap_hardware_dropped():
    assert remap_dimension("hardware", "gpu_model") is None


def test_remap_knowledge_domains():
    assert remap_dimension("knowledge_domains", "any_key") == "information_seeking"


def test_remap_decision_patterns_to_values():
    assert remap_dimension("decision_patterns", "risk_tolerance") == "values"


def test_remap_chrome_interests():
    """Sync agent drift dimension 'interests' maps correctly."""
    assert remap_dimension("interests", "top_domains") == "information_seeking"


def test_remap_gmail_communication():
    """Sync agent drift dimension 'communication' maps correctly."""
    assert remap_dimension("communication", "email_volume") == "communication_patterns"


def test_remap_obsidian_knowledge():
    """Sync agent drift dimension 'knowledge' maps correctly."""
    assert remap_dimension("knowledge", "active_areas") == "information_seeking"


def test_migrate_profile_remaps_facts(tmp_path):
    profile = {
        "name": "Operator",
        "summary": "Test",
        "version": 42,
        "updated_at": "2026-03-09",
        "sources_processed": ["test"],
        "dimensions": [
            {
                "name": "workflow",
                "summary": "Old summary",
                "facts": [
                    {
                        "dimension": "workflow",
                        "key": "preferred_editor",
                        "value": "vscode",
                        "confidence": 0.9,
                        "source": "config",
                        "evidence": "test",
                    },
                    {
                        "dimension": "workflow",
                        "key": "daily_standup_time",
                        "value": "9am",
                        "confidence": 0.8,
                        "source": "interview",
                        "evidence": "test",
                    },
                ],
            },
            {
                "name": "hardware",
                "summary": "Hardware info",
                "facts": [
                    {
                        "dimension": "hardware",
                        "key": "gpu_model",
                        "value": "RTX 3090",
                        "confidence": 1.0,
                        "source": "config",
                        "evidence": "test",
                    },
                ],
            },
        ],
    }
    input_path = tmp_path / "operator-profile.json"
    input_path.write_text(json.dumps(profile))

    result = migrate_profile(input_path)

    dim_names = {d["name"] for d in result["dimensions"]}
    assert "workflow" not in dim_names
    assert "hardware" not in dim_names
    assert "tool_usage" in dim_names
    assert "work_patterns" in dim_names

    # Hardware facts should be in review file
    review_path = tmp_path / "migration-review.jsonl"
    assert review_path.exists()
