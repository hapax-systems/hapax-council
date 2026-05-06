from __future__ import annotations

import json
from pathlib import Path

from agents.hapax_daimonion import daily_segment_prep as prep


def test_load_prepped_programmes_accepts_prior_only_responsible_artifact(tmp_path: Path) -> None:
    artifact = _artifact("prog-1")
    _write_artifact(tmp_path, artifact)

    loaded = load_prepped_programmes(tmp_path)

    assert len(loaded) == 1
    assert loaded[0]["programme_id"] == "prog-1"
    assert loaded[0]["authority"] == "prior_only"
    assert loaded[0]["artifact_path_diagnostic"].endswith("prog-1.json")
    assert loaded[0]["artifact_sha256"] == artifact["artifact_sha256"]
    assert loaded[0]["prepared_artifact_ref"]["ref"].startswith("prepared_artifact:")
    assert loaded[0]["prepared_artifact_ref"]["artifact_sha256"] == loaded[0]["artifact_sha256"]
    assert loaded[0]["prepared_artifact_ref"]["projected_authority"] == (
        "declares_layout_needs_only"
    )
    assert loaded[0]["projected_layout_contract"]["authority"] == "declares_layout_needs_only"
    assert loaded[0]["projected_layout_contract"]["parent_artifact_authority"] == "prior_only"
    assert loaded[0]["beat_layout_intents"][0]["needs"] == ["comparison_visible"]
    assert set(loaded[0]["beat_layout_intents"][0]["proposed_postures"]) == {
        "ranked_visual",
        "comparison",
    }


def test_load_prepped_programmes_rejects_missing_contract(tmp_path: Path) -> None:
    _write_artifact(
        tmp_path,
        {
            "programme_id": "prog-1",
            "prepared_script": ["words"],
            "segment_beats": ["hook"],
        },
    )

    assert load_prepped_programmes(tmp_path) == []


def test_load_prepped_programmes_rejects_forbidden_layout_command(tmp_path: Path) -> None:
    artifact = _artifact("prog-1")
    artifact["LayoutName"] = "garage-door"
    _write_artifact(tmp_path, artifact)

    assert load_prepped_programmes(tmp_path) == []


def test_load_prepped_programmes_rejects_programme_id_mismatch(tmp_path: Path) -> None:
    artifact = _artifact("prog-1")
    artifact["programme_id"] = "prog-2"
    _write_artifact(tmp_path, artifact, filename="prog-2.json")

    assert load_prepped_programmes(tmp_path) == []


def test_load_prepped_programmes_rejects_responsible_segment_cues(tmp_path: Path) -> None:
    artifact = _artifact("prog-1")
    artifact["segment_cues"] = ["camera.hero tight"]
    _write_artifact(tmp_path, artifact)

    assert load_prepped_programmes(tmp_path) == []


def _artifact(programme_id: str) -> dict:
    prompt_sha256 = prep._sha256_text("prompt")
    seed_sha256 = prep._sha256_text("seed")
    segment_beats = ["rank alpha with a visible tier decision"]
    prepared_script = ["Place Alpha in S-tier because the ranking makes the evidence legible."]
    actionability = prep.validate_segment_actionability(prepared_script, segment_beats)
    layout = prep.validate_layout_responsibility(actionability["beat_action_intents"])
    source_hashes = prep._source_hashes_from_fields(
        programme_id=programme_id,
        role="tier_list",
        topic="topic",
        segment_beats=segment_beats,
        seed_sha256=seed_sha256,
        prompt_sha256=prompt_sha256,
    )
    artifact = {
        "schema_version": prep.PREP_ARTIFACT_SCHEMA_VERSION,
        "programme_id": programme_id,
        "segment_id": programme_id,
        "parent_show_id": "show-1",
        "parent_condition_id": "condition-1",
        "hosting_context": "hapax_responsible_live",
        "authority": prep.PREP_ARTIFACT_AUTHORITY,
        "role": "tier_list",
        "topic": "topic",
        "segment_beats": segment_beats,
        "prepared_script": prepared_script,
        "segment_quality_rubric_version": prep.QUALITY_RUBRIC_VERSION,
        "actionability_rubric_version": prep.ACTIONABILITY_RUBRIC_VERSION,
        "layout_responsibility_version": prep.LAYOUT_RESPONSIBILITY_VERSION,
        "segment_quality_report": prep.score_segment_quality(prepared_script, segment_beats),
        "beat_action_intents": actionability["beat_action_intents"],
        "actionability_alignment": {
            "ok": actionability["ok"],
            "removed_unsupported_action_lines": actionability["removed_unsupported_action_lines"],
        },
        "beat_layout_intents": layout["beat_layout_intents"],
        "layout_decision_contract": layout["layout_decision_contract"],
        "runtime_layout_validation": layout["runtime_layout_validation"],
        "layout_decision_receipts": layout["layout_decision_receipts"],
        "prepped_at": "2026-05-06T00:00:00Z",
        "prep_session_id": "segment-prep-layout-contract-test",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "prompt_sha256": prompt_sha256,
        "seed_sha256": seed_sha256,
        "source_hashes": source_hashes,
        "source_provenance_sha256": prep._sha256_json(source_hashes),
        "llm_calls": [
            {
                "call_index": 1,
                "phase": "compose",
                "programme_id": programme_id,
                "model_id": prep.RESIDENT_PREP_MODEL,
                "prompt_sha256": prompt_sha256,
                "prompt_chars": 123,
                "called_at": "2026-05-06T00:00:00+00:00",
            }
        ],
        "beat_count": 1,
        "avg_chars_per_beat": len(prepared_script[0]),
        "refinement_applied": True,
    }
    artifact["artifact_sha256"] = prep._artifact_hash(artifact)
    return artifact


def _write_artifact(tmp_path: Path, artifact: dict, *, filename: str = "prog-1.json") -> Path:
    today = prep._today_dir(tmp_path)
    path = today / filename
    artifact["artifact_sha256"] = prep._artifact_hash(artifact)
    path.write_text(json.dumps(artifact), encoding="utf-8")
    (today / "manifest.json").write_text(
        json.dumps({"programmes": [path.name]}),
        encoding="utf-8",
    )
    return path


load_prepped_programmes = prep.load_prepped_programmes
