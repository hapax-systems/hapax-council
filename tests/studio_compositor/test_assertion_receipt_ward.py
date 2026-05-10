"""Tests for agents.studio_compositor.assertion_receipt_ward (avsdlc-004).

Pin the SHM reader, snapshot construction, reason label formatting,
FSM gate behavior, and render-no-crash on edge cases. Cairo render
is exercised against an in-memory ImageSurface so no display server
or GStreamer is needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import cairo
import pytest

from agents.studio_compositor.assertion_receipt_ward import (
    _EMPTY,
    AssertionReceiptWard,
    ReceiptSnapshot,
    _read_receipt,
    _reason_label,
)

# ── SHM reader ──────────────────────────────────────────────────────────


class TestReadReceipt:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = _read_receipt(tmp_path / "nonexistent.json")
        assert result.status == ""

    def test_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{broken", encoding="utf-8")
        result = _read_receipt(bad)
        assert result.status == ""

    def test_empty_dict_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.json"
        f.write_text("{}", encoding="utf-8")
        result = _read_receipt(f)
        assert result.status == ""

    def test_accepted_receipt_parses(self, tmp_path: Path) -> None:
        payload = {
            "status": "accepted",
            "reason": "accepted",
            "selected_posture": "ranked_list",
            "selected_layout": "segment-list",
            "previous_layout": "default",
            "evidence_refs": ["ev1", "ev2"],
            "input_refs": ["in1"],
            "readback_refs": ["rb1", "rb2", "rb3"],
            "satisfied_effects": ["eff1"],
            "unsatisfied_effects": [],
            "denied_intents": [],
            "applied_layout_changes": ["switch:segment-list"],
            "applied_ward_changes": [],
            "applied_action_changes": [],
            "fallback_reason": None,
            "spoken_text_altered": False,
            "grants_playback_authority": False,
            "grants_audio_authority": False,
        }
        f = tmp_path / "receipt.json"
        f.write_text(json.dumps(payload), encoding="utf-8")
        snap = _read_receipt(f)
        assert snap.status == "accepted"
        assert snap.reason == "accepted"
        assert snap.selected_posture == "ranked_list"
        assert snap.selected_layout == "segment-list"
        assert snap.previous_layout == "default"
        assert snap.evidence_count == 2
        assert snap.input_count == 1
        assert snap.readback_count == 3
        assert snap.satisfied_count == 1
        assert snap.unsatisfied == ()
        assert snap.applied_layout_changes == ("switch:segment-list",)
        assert snap.has_refusal is False

    def test_refused_receipt_with_refusal_detail(self, tmp_path: Path) -> None:
        payload = {
            "status": "refused",
            "reason": "no_layout_needs",
            "selected_posture": None,
            "selected_layout": None,
            "previous_layout": "default",
            "evidence_refs": [],
            "input_refs": ["in1"],
            "readback_refs": ["rb1"],
            "satisfied_effects": [],
            "unsatisfied_effects": ["intent:layout_need"],
            "denied_intents": [],
            "applied_layout_changes": [],
            "applied_ward_changes": [],
            "applied_action_changes": [],
            "refusal": {
                "proposal_refusals": [
                    {"reason": "missing_or_unsupported_hosting_context", "beat_index": 3},
                    {"reason": "missing_current_beat_layout_intents", "beat_index": 3},
                ]
            },
        }
        f = tmp_path / "receipt.json"
        f.write_text(json.dumps(payload), encoding="utf-8")
        snap = _read_receipt(f)
        assert snap.status == "refused"
        assert snap.has_refusal is True
        assert "missing_or_unsupported" in snap.refusal_summary
        assert snap.unsatisfied == ("intent:layout_need",)

    def test_non_dict_json_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "list.json"
        f.write_text("[1, 2, 3]", encoding="utf-8")
        assert _read_receipt(f).status == ""

    def test_refusal_message_fallback(self, tmp_path: Path) -> None:
        payload = {
            "status": "refused",
            "reason": "no_layout_needs",
            "refusal": {"message": "some refusal message here"},
        }
        f = tmp_path / "receipt.json"
        f.write_text(json.dumps(payload), encoding="utf-8")
        snap = _read_receipt(f)
        assert snap.refusal_summary == "some refusal message here"


# ── Reason label ─────────────────────────────────────────────────────────


class TestReasonLabel:
    def test_accepted(self) -> None:
        assert _reason_label("accepted") == "ACCEPTED"

    def test_underscore_conversion(self) -> None:
        assert _reason_label("no_layout_needs") == "NO LAYOUT NEEDS"

    def test_empty_string(self) -> None:
        assert _reason_label("") == ""


# ── Snapshot model ───────────────────────────────────────────────────────


class TestReceiptSnapshot:
    def test_frozen(self) -> None:
        with pytest.raises(AttributeError):
            _EMPTY.status = "changed"  # type: ignore[misc]

    def test_empty_sentinel(self) -> None:
        assert _EMPTY.status == ""
        assert _EMPTY.unsatisfied == ()


# ── Ward lifecycle ───────────────────────────────────────────────────────


class TestAssertionReceiptWardLifecycle:
    def test_construct_without_thread(self) -> None:
        ward = AssertionReceiptWard(start_thread=False)
        assert ward.source_id == "assertion-receipt"
        assert ward._poll_thread is None

    def test_poll_once_with_missing_file(self, tmp_path: Path) -> None:
        ward = AssertionReceiptWard(
            receipt_file=tmp_path / "missing.json",
            start_thread=False,
        )
        snap = ward._poll_once(now=1000.0)
        assert snap.status == ""

    def test_poll_once_with_valid_receipt(self, tmp_path: Path) -> None:
        f = tmp_path / "receipt.json"
        f.write_text(
            json.dumps({"status": "held", "reason": "hysteresis_hold"}),
            encoding="utf-8",
        )
        ward = AssertionReceiptWard(receipt_file=f, start_thread=False)
        snap = ward._poll_once(now=1000.0)
        assert snap.status == "held"

    def test_stop_idempotent(self) -> None:
        ward = AssertionReceiptWard(start_thread=False)
        ward.stop()
        ward.stop()

    def test_state_returns_snapshot(self, tmp_path: Path) -> None:
        f = tmp_path / "receipt.json"
        f.write_text(
            json.dumps({"status": "accepted", "reason": "accepted"}),
            encoding="utf-8",
        )
        ward = AssertionReceiptWard(receipt_file=f, start_thread=False)
        ward._poll_once(now=1000.0)
        s = ward.state()
        assert isinstance(s["snapshot"], ReceiptSnapshot)
        assert s["snapshot"].status == "accepted"
        assert "alpha" in s


# ── Render no-crash ──────────────────────────────────────────────────────


class TestAssertionReceiptWardRender:
    @pytest.fixture
    def ward_with_receipt(self, tmp_path: Path) -> AssertionReceiptWard:
        f = tmp_path / "receipt.json"
        f.write_text(
            json.dumps(
                {
                    "status": "refused",
                    "reason": "no_layout_needs",
                    "selected_posture": None,
                    "selected_layout": None,
                    "previous_layout": "default",
                    "evidence_refs": ["ev1"],
                    "input_refs": ["in1", "in2"],
                    "readback_refs": ["rb1"],
                    "satisfied_effects": [],
                    "unsatisfied_effects": ["intent:layout_need"],
                    "denied_intents": ["some_intent"],
                    "applied_layout_changes": [],
                    "applied_ward_changes": [],
                    "applied_action_changes": [],
                    "refusal": {
                        "proposal_refusals": [
                            {"reason": "missing_hosting_context", "beat_index": 0}
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        ward = AssertionReceiptWard(receipt_file=f, start_thread=False)
        ward._poll_once(now=1000.0)
        return ward

    def test_render_content_no_crash(self, ward_with_receipt: AssertionReceiptWard) -> None:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 440, 260)
        cr = cairo.Context(surface)
        state = ward_with_receipt.state()
        state["alpha"] = 0.85
        ward_with_receipt.render_content(cr, 440, 260, 0.0, state)

    def test_render_zero_alpha_noop(self, ward_with_receipt: AssertionReceiptWard) -> None:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 440, 260)
        cr = cairo.Context(surface)
        ward_with_receipt.render_content(cr, 440, 260, 0.0, {"alpha": 0.0, "snapshot": _EMPTY})

    def test_render_empty_snapshot_noop(self, ward_with_receipt: AssertionReceiptWard) -> None:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 440, 260)
        cr = cairo.Context(surface)
        ward_with_receipt.render_content(cr, 440, 260, 0.0, {"alpha": 0.85, "snapshot": _EMPTY})

    def test_render_accepted_no_crash(self, tmp_path: Path) -> None:
        f = tmp_path / "receipt.json"
        f.write_text(
            json.dumps(
                {
                    "status": "accepted",
                    "reason": "accepted",
                    "selected_posture": "ranked_list",
                    "selected_layout": "segment-list",
                    "previous_layout": "default",
                    "evidence_refs": ["ev1", "ev2"],
                    "input_refs": [],
                    "readback_refs": [],
                    "satisfied_effects": ["eff1"],
                    "unsatisfied_effects": [],
                    "denied_intents": [],
                    "applied_layout_changes": ["switch:segment-list"],
                    "applied_ward_changes": ["show:content-panel"],
                    "applied_action_changes": [],
                }
            ),
            encoding="utf-8",
        )
        ward = AssertionReceiptWard(receipt_file=f, start_thread=False)
        ward._poll_once(now=1000.0)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 440, 260)
        cr = cairo.Context(surface)
        state = ward.state()
        state["alpha"] = 0.85
        ward.render_content(cr, 440, 260, 0.0, state)


# ── Registration ─────────────────────────────────────────────────────────


class TestRegistration:
    def test_registered_in_cairo_sources(self) -> None:
        from agents.studio_compositor.cairo_sources import get_cairo_source_class

        cls = get_cairo_source_class("AssertionReceiptWard")
        assert cls is AssertionReceiptWard
