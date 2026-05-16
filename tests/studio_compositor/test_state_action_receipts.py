"""Focused receipt tests for compositor state-file consumers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from agents.studio_compositor import state
from shared.action_receipt import ActionReceipt, ActionReceiptStatus


def _read_receipt(path: Path) -> ActionReceipt:
    return ActionReceipt.model_validate_json(path.read_text().splitlines()[0])


def test_stream_mode_intent_with_request_id_emits_applied_receipt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from shared import stream_mode

    stream_mode_file = tmp_path / "stream-mode"
    monkeypatch.setattr(stream_mode, "STREAM_MODE_FILE", stream_mode_file)
    intent_path = tmp_path / "stream-mode-intent.json"
    receipts_path = tmp_path / "action-receipts.jsonl"
    intent_path.write_text(
        json.dumps(
            {
                "target_mode": "public-research",
                "source_capability": "stream.mode.public-research.transition",
                "request_id": "state:req:stream-mode",
                "set_at": 100.0,
            }
        ),
        encoding="utf-8",
    )
    compositor = SimpleNamespace(_stream_mode_last_applied_set_at=0.0)

    assert state.process_stream_mode_intent(
        compositor,
        intent_path=intent_path,
        receipt_path=receipts_path,
    )

    assert (
        stream_mode.get_stream_mode(path=stream_mode_file) is stream_mode.StreamMode.PUBLIC_RESEARCH
    )
    receipt = _read_receipt(receipts_path)
    assert receipt.request_id == "state:req:stream-mode"
    assert receipt.status is ActionReceiptStatus.APPLIED
    assert receipt.learning_update_allowed is False


def test_stream_mode_intent_with_request_id_emits_blocked_receipt(
    tmp_path: Path,
) -> None:
    intent_path = tmp_path / "stream-mode-intent.json"
    receipts_path = tmp_path / "action-receipts.jsonl"
    intent_path.write_text(
        json.dumps(
            {
                "target_mode": "not-a-mode",
                "source_capability": "stream.mode.invalid.transition",
                "request_id": "state:req:stream-mode-blocked",
                "set_at": 100.0,
            }
        ),
        encoding="utf-8",
    )
    compositor = SimpleNamespace(_stream_mode_last_applied_set_at=0.0)

    assert state.process_stream_mode_intent(
        compositor,
        intent_path=intent_path,
        receipt_path=receipts_path,
    )

    receipt = _read_receipt(receipts_path)
    assert receipt.request_id == "state:req:stream-mode-blocked"
    assert receipt.status is ActionReceiptStatus.BLOCKED
    assert receipt.blocked_reasons == ["invalid_stream_mode"]


def test_stream_mode_stale_intent_with_request_id_emits_blocked_receipt(
    tmp_path: Path,
) -> None:
    intent_path = tmp_path / "stream-mode-intent.json"
    receipts_path = tmp_path / "action-receipts.jsonl"
    intent_path.write_text(
        json.dumps(
            {
                "target_mode": "public-research",
                "source_capability": "stream.mode.public-research.transition",
                "request_id": "state:req:stream-mode-stale",
                "set_at": 100.0,
            }
        ),
        encoding="utf-8",
    )
    compositor = SimpleNamespace(_stream_mode_last_applied_set_at=101.0)

    assert state.process_stream_mode_intent(
        compositor,
        intent_path=intent_path,
        receipt_path=receipts_path,
    )

    receipt = _read_receipt(receipts_path)
    assert receipt.request_id == "state:req:stream-mode-stale"
    assert receipt.status is ActionReceiptStatus.BLOCKED
    assert receipt.blocked_reasons == ["stale_or_duplicate"]


def test_hero_camera_override_with_request_id_emits_applied_receipt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    applied_modes: list[str] = []

    def _apply(_compositor, mode: str) -> None:
        applied_modes.append(mode)

    monkeypatch.setattr(state, "apply_layout_mode", _apply)
    override_path = tmp_path / "hero-camera-override.json"
    receipts_path = tmp_path / "action-receipts.jsonl"
    override_path.write_text(
        json.dumps(
            {
                "camera_role": "brio-operator",
                "ttl_s": 60.0,
                "set_at": time.time(),
                "source_capability": "cam.hero.operator.segment",
                "request_id": "state:req:hero",
            }
        ),
        encoding="utf-8",
    )
    compositor = SimpleNamespace(
        _GLib=None,
        _layout_mode="balanced",
        _hero_override_last_applied_set_at=0.0,
    )

    assert state.process_hero_camera_override(
        compositor,
        override_path=override_path,
        receipt_path=receipts_path,
    )

    assert applied_modes == ["packed/brio-operator"]
    receipt = _read_receipt(receipts_path)
    assert receipt.request_id == "state:req:hero"
    assert receipt.status is ActionReceiptStatus.APPLIED
    assert receipt.applied_refs == ["layout-mode:packed/brio-operator"]


def test_expired_hero_camera_override_with_request_id_emits_blocked_receipt(
    tmp_path: Path,
) -> None:
    override_path = tmp_path / "hero-camera-override.json"
    receipts_path = tmp_path / "action-receipts.jsonl"
    override_path.write_text(
        json.dumps(
            {
                "camera_role": "brio-operator",
                "ttl_s": 1.0,
                "set_at": time.time() - 10.0,
                "source_capability": "cam.hero.operator.segment",
                "request_id": "state:req:hero-expired",
            }
        ),
        encoding="utf-8",
    )
    compositor = SimpleNamespace(
        _GLib=None,
        _layout_mode="balanced",
        _hero_override_last_applied_set_at=0.0,
    )

    assert state.process_hero_camera_override(
        compositor,
        override_path=override_path,
        receipt_path=receipts_path,
    )

    receipt = _read_receipt(receipts_path)
    assert receipt.request_id == "state:req:hero-expired"
    assert receipt.status is ActionReceiptStatus.BLOCKED
    assert receipt.blocked_reasons == ["expired_hero_override"]


def test_debounced_hero_camera_override_with_request_id_emits_blocked_receipt(
    tmp_path: Path,
) -> None:
    now = time.time()
    override_set_at = now
    override_path = tmp_path / "hero-camera-override.json"
    receipts_path = tmp_path / "action-receipts.jsonl"
    override_path.write_text(
        json.dumps(
            {
                "camera_role": "brio-operator",
                "ttl_s": 60.0,
                "set_at": override_set_at,
                "source_capability": "cam.hero.operator.segment",
                "request_id": "state:req:hero-debounced",
            }
        ),
        encoding="utf-8",
    )
    compositor = SimpleNamespace(
        _GLib=None,
        _layout_mode="balanced",
        _hero_override_last_applied_set_at=now - 1.0,
    )

    assert state.process_hero_camera_override(
        compositor,
        override_path=override_path,
        receipt_path=receipts_path,
    )

    receipt = _read_receipt(receipts_path)
    assert receipt.request_id == "state:req:hero-debounced"
    assert receipt.status is ActionReceiptStatus.BLOCKED
    assert receipt.blocked_reasons == ["debounce_active"]
