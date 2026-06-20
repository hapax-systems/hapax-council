"""S-4 durable re-arm — witness_mode gating (the silent recurring path).

Pins the safety thesis of the arm-on-boot durability fix: the recurring
re-arm path (``witness_mode="none"``) re-asserts the empirical gain ladder
**silently** — no tone probe to air, no monitor toggle, no program_change —
and is idempotent, while still surfacing ``midi_output_missing``. The default
(``"tone"``) preserves the existing boot-service / CLI behaviour exactly.

Why this matters: the existing arm unconditionally runs the wet-return probe
when the ladder emits, and that probe plays a 1397 Hz marker to the broadcast
bus. Putting the *existing* arm on a recurring timer would beep to air every
tick. ``witness_mode="none"`` is the cut that makes the automatic re-arm safe.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared import s4_arm


def _green_probe(label: str) -> dict:
    return {
        "ok": True,
        "s4_wet_return_signal": True,
        "reasons": [],
        "structural_route_present": True,
        "witness_updated": True,
        "returncode": 0,
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


def _spy():
    calls: list[str] = []

    def runner(label: str) -> dict:
        calls.append(label)
        return _green_probe(label)

    return runner, calls


def _run(witness_mode: str, *, probe_runner, output_factory=None):
    """Drive run_s4_arm with a fake MIDI port that records message types."""
    port = MagicMock()
    types: list[str] = []

    def fake_message(message_type: str, **kwargs):
        types.append(message_type)
        return (message_type, kwargs)

    factory = output_factory if output_factory is not None else (lambda: port)
    with (
        patch("shared.s4_midi._MIDO_AVAILABLE", True),
        patch("shared.s4_midi.Message", side_effect=fake_message),
        patch("shared.s4_midi.time.sleep"),
        patch("shared.s4_arm.time.sleep"),
    ):
        receipt = s4_arm.run_s4_arm(
            witness_mode=witness_mode,
            receipt_path=None,
            midi_output_factory=factory,
            probe_runner=probe_runner,
        )
    return receipt, types


# ── THE SAFETY THESIS: silent recurring path ──────────────────────────────────


def test_none_mode_emits_ladder_only_no_probe_no_toggle() -> None:
    runner, calls = _spy()
    receipt, types = _run("none", probe_runner=runner)

    # (a) the tone probe is NEVER invoked on the recurring path
    assert calls == []
    # (b) exactly the 5 ladder control-changes — zero note_on (toggle), zero program_change
    assert types == ["control_change"] * 5
    assert "program_change" not in types
    assert "note_on" not in types
    # (c) the ladder is asserted and the verdict is green WITHOUT a probe
    assert receipt["ladder_assertion"]["emitted"] == 5
    assert receipt["ladder_assertion"]["ok"] is True
    assert receipt["verdict"] == "green"
    assert receipt["monitor_toggle"]["events"] == []


def test_none_mode_is_idempotent_across_runs() -> None:
    runner, calls = _spy()
    for _ in range(3):
        receipt, types = _run("none", probe_runner=runner)
        assert types == ["control_change"] * 5
        assert receipt["verdict"] == "green"
    assert calls == []  # never a tone, however many ticks


def test_none_mode_surfaces_midi_missing_as_red() -> None:
    runner, calls = _spy()
    with patch("shared.s4_midi._MIDO_AVAILABLE", True):
        receipt = s4_arm.run_s4_arm(
            witness_mode="none",
            receipt_path=None,
            midi_output_factory=lambda: None,
            probe_runner=runner,
        )
    assert receipt["verdict"] == "red"
    assert "midi_output_missing" in receipt["failure_reasons"]
    assert calls == []


# ── the default path is untouched ─────────────────────────────────────────────


def test_tone_mode_is_the_default_and_still_probes() -> None:
    runner, calls = _spy()
    receipt, types = _run("tone", probe_runner=runner)
    assert calls == ["initial_marker_witness"]
    assert types == ["control_change"] * 5
    assert receipt["verdict"] == "green"


def test_default_witness_mode_is_tone() -> None:
    runner, calls = _spy()
    port = MagicMock()
    with (
        patch("shared.s4_midi._MIDO_AVAILABLE", True),
        patch("shared.s4_midi.Message", side_effect=lambda mt, **k: (mt, k)),
        patch("shared.s4_midi.time.sleep"),
        patch("shared.s4_arm.time.sleep"),
    ):
        s4_arm.run_s4_arm(
            receipt_path=None,
            midi_output_factory=lambda: port,
            probe_runner=runner,
        )
    assert calls == ["initial_marker_witness"]  # default behaviour = tone
