from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script_module():
    path = REPO_ROOT / "scripts" / "review_segment_candidate_set.py"
    spec = importlib.util.spec_from_file_location("review_segment_candidate_set", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_write_manifest_failed_review_writes_no_release_outcome(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_script_module()

    def forbidden_publication(**_kwargs):
        raise AssertionError("failed review must not publish selected-release feedback")

    monkeypatch.setattr(module, "publish_selected_release_feedback", forbidden_publication)
    receipt_out = tmp_path / "candidate-review.json"

    rc = module.main(
        [
            "--prep-dir",
            str(tmp_path),
            "--write-manifest",
            "--receipt-out",
            str(receipt_out),
        ]
    )

    assert rc == 2
    assert receipt_out.exists()
    receipt = json.loads(receipt_out.read_text(encoding="utf-8"))
    assert receipt["ok"] is False
    assert "selected_release_publication" not in receipt
    assert not list(tmp_path.rglob("selected-release-manifest.json"))
    outcome_path = Path(receipt["terminal_outcome_path"])
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    assert outcome["outcome_type"] == "no_release"
    assert outcome["authority"] == "diagnostic_only"
    assert outcome["release_boundary"] == {
        "listed_in_manifest": False,
        "selected_release_eligible": False,
        "runtime_pool_eligible": False,
    }
    assert outcome["counts"]["selected_count"] == 0
    captured = capsys.readouterr()
    assert '"outcome_type": "no_release"' not in captured.out


def test_write_manifest_publication_block_removes_selected_manifest_and_writes_no_release(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    receipt_out = tmp_path / "candidate-review.json"
    manifest = {
        "ok": True,
        "programmes": ["prog-a.json"],
        "selected_artifacts": [
            {
                "programme_id": "prog-a",
                "artifact_name": "prog-a.json",
                "artifact_sha256": "a" * 64,
            }
        ],
        "violations": [],
        "review_gaps": [],
        "selected_count": 1,
        "target_selected_count": 1,
        "eligible_artifact_count": 1,
        "reviewed_candidate_count": 1,
    }
    receipt = {
        "ok": True,
        "criteria": [],
        "selected_release_manifest": manifest,
        "segment_candidate_selection_sha256": "b" * 64,
    }

    monkeypatch.setattr(module, "load_prepped_programmes", lambda *_args, **_kwargs: [{"ok": True}])
    monkeypatch.setattr(module, "read_candidate_ledger", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        module,
        "review_segment_candidate_set",
        lambda *_args, **_kwargs: dict(receipt),
    )
    monkeypatch.setattr(
        module,
        "assert_segment_prep_allowed",
        lambda *_args, **_kwargs: SimpleNamespace(
            mode="runtime_pool_load_allowed",
            reason="test",
            source="test",
        ),
    )
    monkeypatch.setattr(
        module,
        "publish_selected_release_feedback",
        lambda **_kwargs: {
            "ok": False,
            "publication_ok": False,
            "publication_errors": [
                {"surface": "runtime_loader", "error": "selected_release_loaded_no_artifacts"}
            ],
        },
    )

    rc = module.main(
        [
            "--prep-dir",
            str(tmp_path),
            "--selected-count",
            "1",
            "--write-manifest",
            "--receipt-out",
            str(receipt_out),
        ]
    )

    assert rc == 2
    rendered = json.loads(receipt_out.read_text(encoding="utf-8"))
    assert rendered["closure_ok"] is False
    assert rendered["selected_release_publication_blocked"] is True
    assert not list(tmp_path.rglob("selected-release-manifest.json"))
    assert (
        json.loads(Path(rendered["terminal_outcome_path"]).read_text())["outcome_type"]
        == "no_release"
    )
