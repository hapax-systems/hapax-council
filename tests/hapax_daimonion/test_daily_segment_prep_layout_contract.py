from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agents.hapax_daimonion.daily_segment_prep import _today_dir, load_prepped_programmes


def test_load_prepped_programmes_accepts_prior_only_responsible_artifact(tmp_path: Path) -> None:
    artifact = _artifact("prog-1")
    artifact_path = _write_artifact(tmp_path, artifact)
    artifact_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    loaded = load_prepped_programmes(tmp_path)

    assert len(loaded) == 1
    assert loaded[0]["programme_id"] == "prog-1"
    assert loaded[0]["authority"] == "prior_only"
    assert loaded[0]["artifact_path_diagnostic"].endswith("prog-1.json")
    assert loaded[0]["artifact_sha256"] == artifact_sha256
    assert loaded[0]["prepared_artifact_ref"]["ref"].startswith("prepared_artifact:")
    assert loaded[0]["prepared_artifact_ref"]["artifact_sha256"] == loaded[0]["artifact_sha256"]
    assert loaded[0]["prepared_artifact_ref"]["projected_authority"] == (
        "declares_layout_needs_only"
    )
    assert loaded[0]["projected_layout_contract"]["authority"] == "declares_layout_needs_only"
    assert loaded[0]["projected_layout_contract"]["parent_artifact_authority"] == "prior_only"
    assert loaded[0]["beat_layout_intents"][0]["needs"] == ["evidence_visible"]


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
    return {
        "programme_id": programme_id,
        "segment_id": programme_id,
        "parent_show_id": "show-1",
        "parent_condition_id": "condition-1",
        "hosting_context": "hapax_responsible_live",
        "authority": "prior_only",
        "role": "rant",
        "topic": "topic",
        "segment_beats": ["hook: show source"],
        "beat_layout_intents": [
            {
                "beat_id": "hook",
                "beat_index": 0,
                "needs": ["evidence_visible"],
                "evidence_refs": ["vault:source-note"],
                "source_affordances": ["asset:source-card"],
                "default_static_success_allowed": False,
            }
        ],
        "layout_decision_contract": {
            "may_command_layout": False,
            "bounded_vocabulary": ["asset_front", "camera_subject", "spoken_only_fallback"],
            "min_dwell_s": 8,
            "ttl_s": 30,
            "conflict_order": ["safety", "action_visibility", "readability"],
            "receipt_required": True,
        },
        "runtime_layout_validation": {
            "receipt_required": True,
            "layout_state_hash_required": True,
            "layout_state_signature_required": True,
            "ward_visibility_required": True,
            "readback_kinds_required": ["wcs", "layout_state", "ward_visibility"],
        },
        "prepared_script": ["prepared words"],
        "prepped_at": "2026-05-06T00:00:00Z",
    }


def _write_artifact(tmp_path: Path, artifact: dict, *, filename: str = "prog-1.json") -> Path:
    today = _today_dir(tmp_path)
    path = today / filename
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path
