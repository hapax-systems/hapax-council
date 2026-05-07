from __future__ import annotations

import json
from pathlib import Path

from agents.hapax_daimonion import daily_segment_prep as prep
from shared.segment_candidate_selection import SEGMENT_CANDIDATE_SELECTION_VERSION


def _manifest(artifact_name: str = "prog-a.json") -> dict:
    payload = {
        "selected_release_manifest_version": SEGMENT_CANDIDATE_SELECTION_VERSION,
        "selected_at": "2026-05-06T00:00:00+00:00",
        "selection_gate": "shared.segment_candidate_selection.selected_release_manifest",
        "selected_count": 1,
        "target_selected_count": 10,
        "programmes": [artifact_name],
        "selected_artifacts": [
            {
                "programme_id": "prog-a",
                "artifact_name": artifact_name,
                "artifact_sha256": "a" * 64,
                "quality_overall": 4.2,
                "live_event_score": 4.5,
                "live_event_band": "excellent",
                "receipt_id": "receipt-a",
            }
        ],
        "violations": [],
        "ok": True,
    }
    payload["selected_release_manifest_sha256"] = prep._sha256_json(payload)
    return payload


def _artifact(path: Path) -> dict:
    return {
        "programme_id": "prog-a",
        "role": "rant",
        "topic": "A selected segment about runtime readbacks",
        "segment_beats": ["premise", "demonstration"],
        "prepared_script": ["full script body should not be needed in the digest"],
        "artifact_path": str(path),
        "artifact_sha256": "a" * 64,
        "authority": "prior_only",
        "model_id": prep.RESIDENT_PREP_MODEL,
        "prep_session_id": "prep-session-a",
        "llm_calls": [],
        "prompt_sha256": "b" * 64,
        "seed_sha256": "c" * 64,
        "source_hashes": {},
        "source_provenance_sha256": "d" * 64,
        "segment_quality_report": {"overall": 4.2, "label": "excellent"},
        "segment_live_event_report": {"score": 4.5, "band": "excellent"},
        "actionability_alignment": {"ok": True},
        "hosting_context": "hapax_responsible_host",
        "runtime_layout_validation": {"status": "pending_runtime_readback"},
        "segment_prep_contract_report": {"ok": True, "violations": []},
        "segment_prep_contract": {
            "role_excellence_plan": {
                "live_event_plan": {
                    "bit_engine": "source-bound object changes public status",
                    "audience_job": "inspect the readback",
                    "payoff": "the visible object resolves the premise",
                }
            }
        },
    }


def _write_selected_manifest(today: Path, manifest: dict) -> None:
    (today / prep.SELECTED_RELEASE_MANIFEST).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def test_selected_release_rag_digest_records_prior_boundary(tmp_path: Path) -> None:
    today = tmp_path / "2026-05-06"
    today.mkdir()
    artifact_path = today / "prog-a.json"
    rag_dir = tmp_path / "rag-sources" / "segment-prep"

    out = prep._write_selected_release_rag_digest(
        today,
        [_artifact(artifact_path)],
        manifest=_manifest(),
        review_receipt={
            "segment_candidate_selection_sha256": "e" * 64,
            "criteria": [{"name": "candidate_set.selected_manifest_ok", "passed": True}],
        },
        rag_dir=rag_dir,
    )

    text = out.read_text(encoding="utf-8")
    assert "authority: prior_only_feedback" in text
    assert "not runtime layout authority" in text
    assert "`prog-a.json`" in text
    assert "`receipt-a`" in text


def test_selected_release_manifest_requires_body_hash(tmp_path: Path) -> None:
    today = tmp_path / "2026-05-06"
    today.mkdir()
    manifest = _manifest()
    _write_selected_manifest(today, manifest)

    assert prep._selected_release_manifest(today) == manifest

    missing_hash = dict(manifest)
    missing_hash.pop("selected_release_manifest_sha256")
    _write_selected_manifest(today, missing_hash)
    assert prep._selected_release_manifest(today) is None

    stale_hash = dict(manifest)
    stale_hash["programmes"] = ["other.json"]
    _write_selected_manifest(today, stale_hash)
    assert prep._selected_release_manifest(today) is None


def test_publish_selected_release_feedback_uses_selected_loader(
    monkeypatch,
    tmp_path: Path,
) -> None:
    today = tmp_path / "2026-05-06"
    today.mkdir()
    artifact_path = today / "prog-a.json"
    manifest = _manifest()
    calls: dict[str, object] = {}
    _write_selected_manifest(today, manifest)

    monkeypatch.setattr(prep, "_today_path", lambda _base: today)

    def fake_load(root: Path, *, require_selected: bool) -> list[dict]:
        calls["load_root"] = root
        calls["require_selected"] = require_selected
        return [_artifact(artifact_path)]

    def fake_upsert(artifacts, *, manifest, review_receipt) -> int:
        calls["upsert_count"] = len(artifacts)
        calls["manifest_hash"] = manifest["selected_release_manifest_sha256"]
        calls["receipt_hash"] = review_receipt["segment_candidate_selection_sha256"]
        return 1

    monkeypatch.setattr(prep, "load_prepped_programmes", fake_load)
    monkeypatch.setattr(prep, "_upsert_artifact_dicts_to_qdrant", fake_upsert)

    result = prep.publish_selected_release_feedback(
        prep_dir=tmp_path,
        review_receipt={
            "ok": True,
            "segment_candidate_selection_sha256": "e" * 64,
            "selected_release_manifest": manifest,
        },
        rag_dir=tmp_path / "rag",
    )

    assert result["ok"] is True
    assert result["qdrant_upserted"] == 1
    assert calls["require_selected"] is True
    assert calls["manifest_hash"] == manifest["selected_release_manifest_sha256"]


def test_publish_selected_release_feedback_fails_when_selected_loader_returns_no_artifacts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    today = tmp_path / "2026-05-06"
    today.mkdir()
    manifest = _manifest()
    _write_selected_manifest(today, manifest)

    monkeypatch.setattr(prep, "_today_path", lambda _base: today)
    monkeypatch.setattr(prep, "load_prepped_programmes", lambda _root, *, require_selected: [])
    monkeypatch.setattr(prep, "_upsert_artifact_dicts_to_qdrant", lambda *a, **k: 0)

    result = prep.publish_selected_release_feedback(
        prep_dir=tmp_path,
        review_receipt={
            "ok": True,
            "segment_candidate_selection_sha256": "e" * 64,
            "selected_release_manifest": manifest,
        },
        rag_dir=tmp_path / "rag",
    )

    assert result["ok"] is False
    assert result["publication_ok"] is False
    assert result["publication_errors"][0] == {
        "surface": "runtime_loader",
        "error": "selected_release_loaded_no_artifacts",
    }


def test_publish_selected_release_feedback_rejects_receipt_manifest_hash_mismatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    today = tmp_path / "2026-05-06"
    today.mkdir()
    artifact_path = today / "prog-a.json"
    disk_manifest = _manifest()
    receipt_manifest = dict(disk_manifest)
    receipt_manifest["selected_release_manifest_sha256"] = "f" * 64
    _write_selected_manifest(today, disk_manifest)

    monkeypatch.setattr(prep, "_today_path", lambda _base: today)
    monkeypatch.setattr(
        prep,
        "load_prepped_programmes",
        lambda _root, *, require_selected: [_artifact(artifact_path)],
    )
    monkeypatch.setattr(prep, "_upsert_artifact_dicts_to_qdrant", lambda *a, **k: 1)

    result = prep.publish_selected_release_feedback(
        prep_dir=tmp_path,
        review_receipt={
            "ok": True,
            "segment_candidate_selection_sha256": "e" * 64,
            "selected_release_manifest": receipt_manifest,
        },
        rag_dir=tmp_path / "rag",
    )

    assert result["ok"] is False
    assert result["publication_errors"][0] == {
        "surface": "selected_release_manifest",
        "error": "receipt_manifest_hash_mismatch",
    }


def test_publish_selected_release_feedback_records_qdrant_diagnostic_without_blocking_release(
    monkeypatch,
    tmp_path: Path,
) -> None:
    today = tmp_path / "2026-05-06"
    today.mkdir()
    artifact_path = today / "prog-a.json"
    _write_selected_manifest(today, _manifest())

    monkeypatch.setattr(prep, "_today_path", lambda _base: today)
    monkeypatch.setattr(
        prep,
        "load_prepped_programmes",
        lambda _root, *, require_selected: [_artifact(artifact_path)],
    )
    monkeypatch.setattr(prep, "_upsert_artifact_dicts_to_qdrant", lambda *a, **k: 0)

    result = prep.publish_selected_release_feedback(
        prep_dir=tmp_path,
        review_receipt={
            "ok": True,
            "segment_candidate_selection_sha256": "e" * 64,
            "selected_release_manifest": _manifest(),
        },
        rag_dir=tmp_path / "rag",
    )

    assert result["ok"] is True
    assert result["publication_ok"] is False
    assert result["qdrant_upserted"] == 0
    assert result["publication_errors"] == [
        {
            "surface": "qdrant",
            "error": "selected_release_qdrant_publication_incomplete",
        }
    ]


def test_publish_selected_release_feedback_records_rag_diagnostic_without_blocking_release(
    monkeypatch,
    tmp_path: Path,
) -> None:
    today = tmp_path / "2026-05-06"
    today.mkdir()
    artifact_path = today / "prog-a.json"
    _write_selected_manifest(today, _manifest())

    monkeypatch.setattr(prep, "_today_path", lambda _base: today)
    monkeypatch.setattr(
        prep,
        "load_prepped_programmes",
        lambda _root, *, require_selected: [_artifact(artifact_path)],
    )
    monkeypatch.setattr(prep, "_upsert_artifact_dicts_to_qdrant", lambda *a, **k: 1)

    def boom(*_args, **_kwargs) -> Path:
        raise RuntimeError("disk unavailable")

    monkeypatch.setattr(prep, "_write_selected_release_rag_digest", boom)

    result = prep.publish_selected_release_feedback(
        prep_dir=tmp_path,
        review_receipt={
            "ok": True,
            "segment_candidate_selection_sha256": "e" * 64,
            "selected_release_manifest": _manifest(),
        },
        rag_dir=tmp_path / "rag",
    )

    assert result["ok"] is True
    assert result["publication_ok"] is False
    assert result["publication_errors"][0]["surface"] == "rag_digest"


def test_selected_release_qdrant_points_are_available_for_retrieval(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from shared import affordance_pipeline, config

    today = tmp_path / "2026-05-06"
    today.mkdir()
    artifact_path = today / "prog-a.json"
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        affordance_pipeline,
        "embed_batch_safe",
        lambda texts, *, prefix: [[0.1, 0.2, 0.3] for _text in texts],
    )

    class FakeQdrant:
        def upsert(self, *, collection_name, points) -> None:
            captured["collection_name"] = collection_name
            captured["points"] = points

    monkeypatch.setattr(config, "get_qdrant", lambda: FakeQdrant())

    count = prep._upsert_artifact_dicts_to_qdrant(
        [_artifact(artifact_path)],
        manifest=_manifest(),
        review_receipt={
            "ok": True,
            "segment_candidate_selection_sha256": "e" * 64,
        },
    )

    assert count == 1
    point = captured["points"][0]  # type: ignore[index]
    assert point.payload["available"] is True
    assert point.payload["selected_release"] is True
    assert point.payload["authority"] == "prior_only"
