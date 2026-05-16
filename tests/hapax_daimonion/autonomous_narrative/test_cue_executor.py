"""Tests for segment cue SHM execution."""

from __future__ import annotations

import json
from pathlib import Path

from agents.hapax_daimonion.autonomous_narrative import cue_executor as ce
from shared.action_receipt import ActionReceipt, ActionReceiptStatus


def test_front_homage_emits_structural_reflex_action_receipt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(ce, "_SHM_DIR", tmp_path)
    monkeypatch.setattr(ce, "_HOMAGE_ACTIVE_ARTEFACT", tmp_path / "homage-active-artefact.json")
    monkeypatch.setattr(
        ce,
        "_NARRATIVE_STRUCTURAL_INTENT",
        tmp_path / "narrative-structural-intent.json",
    )
    monkeypatch.setattr(ce, "_ACTION_RECEIPTS_JSONL", tmp_path / "action-receipts.jsonl")

    ce.execute_cue("front.homage bitchx", request_id="cue:req:front-homage")

    active = json.loads((tmp_path / "homage-active-artefact.json").read_text())
    structural = json.loads((tmp_path / "narrative-structural-intent.json").read_text())
    receipt = ActionReceipt.model_validate_json(
        (tmp_path / "action-receipts.jsonl").read_text().splitlines()[0]
    )

    assert active["package"] == "bitchx"
    assert structural["homage_rotation_mode"] == "paused"
    assert receipt.request_id == "cue:req:front-homage"
    assert receipt.status is ActionReceiptStatus.APPLIED
    assert receipt.structural_reflex is True
    assert receipt.readback_required is True
    assert receipt.learning_update_allowed is False
    assert receipt.can_support_affordance_success() is False


def test_front_homage_write_failure_emits_error_receipt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(ce, "_SHM_DIR", tmp_path)
    monkeypatch.setattr(ce, "_ACTION_RECEIPTS_JSONL", tmp_path / "action-receipts.jsonl")
    monkeypatch.setattr(ce, "_atomic_write_json", lambda *_args, **_kwargs: False)

    ce.execute_cue("front.homage bitchx", request_id="cue:req:front-homage-error")

    receipt = ActionReceipt.model_validate_json(
        (tmp_path / "action-receipts.jsonl").read_text().splitlines()[0]
    )
    assert receipt.request_id == "cue:req:front-homage-error"
    assert receipt.status is ActionReceiptStatus.ERROR
    assert receipt.error_refs == ["front_homage_write_failed"]
    assert receipt.applied_refs == []
    assert receipt.structural_reflex is True
