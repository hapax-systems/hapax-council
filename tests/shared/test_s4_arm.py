from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shared import s4_arm


class FakeMidiOutput:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _green_probe(label: str) -> dict:
    return {
        "ok": True,
        "s4_wet_return_signal": True,
        "reasons": [],
        "structural_route_present": True,
        "witness_updated": True,
        "playback": {"returncode": 0},
        "captures": {
            "wet_voice_playback": {
                "top_marker_channels": [
                    {
                        "channel": 0,
                        "marker_detected": True,
                        "marker_snr_db": 18.0,
                        "rms_dbfs": -42.0,
                        "peak_dbfs": -30.0,
                    }
                ]
            }
        },
        "label_seen_by_fake": label,
    }


def _dark_probe(label: str) -> dict:
    return {
        "ok": True,
        "s4_wet_return_signal": False,
        "reasons": ["wet_marker_missing"],
        "structural_route_present": True,
        "witness_updated": True,
        "playback": {"returncode": 0},
        "captures": {},
        "label_seen_by_fake": label,
    }


def test_load_gain_ladder_converts_human_channels_to_mido_channels() -> None:
    ladder = s4_arm.load_gain_ladder()

    assert len(ladder.commands) == 5
    assert [command.human_channel for command in ladder.commands] == [16, 16, 16, 2, 2]
    assert [command.midi_channel for command in ladder.commands] == [15, 15, 15, 1, 1]
    assert [command.cc for command in ladder.commands] == [48, 49, 58, 46, 47]
    assert ladder.result_dbfs_at_tap == -23.4


def test_assert_gain_ladder_emits_control_changes_without_program_change() -> None:
    ladder = s4_arm.load_gain_ladder()
    port = MagicMock()
    message_types: list[str] = []

    def fake_message(message_type: str, **kwargs):
        message_types.append(message_type)
        return (message_type, kwargs)

    with (
        patch("shared.s4_midi._MIDO_AVAILABLE", True),
        patch("shared.s4_midi.Message", side_effect=fake_message),
        patch("shared.s4_midi.time.sleep"),
    ):
        result = s4_arm.assert_gain_ladder(port, ladder.commands, delay_ms=0.0)

    assert result.ok is True
    assert result.without_program_change is True
    assert result.emitted == len(ladder.commands)
    assert message_types == ["control_change"] * len(ladder.commands)
    assert "program_change" not in message_types


def test_probe_green_rejects_nonzero_probe_process_returncode() -> None:
    probe = _green_probe("bad-process")
    probe["returncode"] = 2

    assert s4_arm.probe_green(probe) is False
    assert "probe_process_failed" in s4_arm.probe_reason_tags(probe)


def test_run_wet_return_probe_subprocess_fails_closed_when_process_missing() -> None:
    result = s4_arm.run_wet_return_probe_subprocess(
        label="missing",
        probe_script=Path("/tmp/definitely-missing-hapax-s4-probe"),
        timeout_s=0.01,
    )

    assert result["ok"] is False
    assert result["s4_wet_return_signal"] is False
    assert "probe_process_unavailable" in result["reasons"]


def test_run_s4_arm_initial_green_writes_receipt_without_monitor_toggle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = FakeMidiOutput()
    cc_calls: list[tuple[int, int, int]] = []

    def fake_emit_cc(_output, cc: int, value: int, *, channel: int, delay_ms: float) -> bool:
        cc_calls.append((channel, cc, value))
        return True

    def fail_note(*_args, **_kwargs) -> bool:
        raise AssertionError("monitor toggle should not run after a green witness")

    monkeypatch.setattr(s4_arm, "emit_cc", fake_emit_cc)
    monkeypatch.setattr(s4_arm, "emit_note_on", fail_note)

    receipt_path = tmp_path / "s4-arm-receipt.json"
    receipt = s4_arm.run_s4_arm(
        receipt_path=receipt_path,
        midi_output_factory=lambda: output,
        probe_runner=_green_probe,
        monitor_settle_s=0.0,
        cc_delay_ms=0.0,
        now=lambda: "2026-06-11T00:00:00+00:00",
    )

    assert receipt["ok"] is True
    assert receipt["verdict"] == "green"
    assert receipt["ladder_assertion"]["without_program_change"] is True
    assert receipt["monitor_toggle"]["events"] == []
    assert [call[0] for call in cc_calls] == [15, 15, 15, 1, 1]
    assert output.closed is True
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["verdict"] == "green"


def test_run_s4_arm_toggles_monitor_once_when_initial_witness_is_dark(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = FakeMidiOutput()
    labels: list[str] = []
    note_calls: list[tuple[int, int, int]] = []
    probes = iter([_dark_probe, _green_probe])

    monkeypatch.setattr(s4_arm, "emit_cc", lambda *_args, **_kwargs: True)

    def fake_note(_output, note: int, velocity: int, *, channel: int, delay_ms: float) -> bool:
        note_calls.append((channel, note, velocity))
        return True

    def probe(label: str) -> dict:
        labels.append(label)
        return next(probes)(label)

    monkeypatch.setattr(s4_arm, "emit_note_on", fake_note)

    receipt = s4_arm.run_s4_arm(
        receipt_path=tmp_path / "receipt.json",
        midi_output_factory=lambda: output,
        probe_runner=probe,
        monitor_settle_s=0.0,
        cc_delay_ms=0.0,
    )

    assert receipt["ok"] is True
    assert labels == ["initial_marker_witness", "after_monitor_toggle"]
    assert note_calls == [(15, 41, 127)]
    assert receipt["monitor_toggle"]["events"][0]["requires_followup_witness"] is True


def test_run_s4_arm_closes_failed_monitor_toggle_cycle_with_restore_witness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    labels: list[str] = []
    note_calls: list[tuple[int, int, int]] = []
    probes = iter([_dark_probe, _dark_probe, _dark_probe])

    monkeypatch.setattr(s4_arm, "emit_cc", lambda *_args, **_kwargs: True)

    def fake_note(_output, note: int, velocity: int, *, channel: int, delay_ms: float) -> bool:
        note_calls.append((channel, note, velocity))
        return True

    def probe(label: str) -> dict:
        labels.append(label)
        return next(probes)(label)

    monkeypatch.setattr(s4_arm, "emit_note_on", fake_note)

    receipt = s4_arm.run_s4_arm(
        receipt_path=tmp_path / "receipt.json",
        midi_output_factory=FakeMidiOutput,
        probe_runner=probe,
        monitor_settle_s=0.0,
        cc_delay_ms=0.0,
    )

    assert receipt["ok"] is False
    assert receipt["verdict"] == "red"
    assert labels == [
        "initial_marker_witness",
        "after_monitor_toggle",
        "after_monitor_toggle_restore",
    ]
    assert note_calls == [(15, 41, 127), (15, 41, 127)]
    assert "wet_marker_missing" in receipt["failure_reasons"]
    assert "s4_wet_return_signal_false" in receipt["failure_reasons"]


def test_main_pre_segment_check_prints_and_writes_green_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt_path = tmp_path / "receipt.json"
    monkeypatch.setattr(s4_arm, "emit_cc", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        s4_arm,
        "emit_note_on",
        lambda *_args, **_kwargs: pytest.fail("monitor toggle should not run"),
    )

    rc = s4_arm.main(
        ["--pre-segment-check", "--receipt-path", str(receipt_path), "--compact"],
        midi_output_factory=FakeMidiOutput,
        probe_runner=_green_probe,
    )

    assert rc == 0
    printed = json.loads(capsys.readouterr().out)
    written = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert printed["pre_segment_check"] is True
    assert written["ok"] is True
    assert written["contract"]["scene_recall_policy"] == "no_program_change_in_arm_path"
