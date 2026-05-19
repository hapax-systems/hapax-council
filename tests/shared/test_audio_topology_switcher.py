"""Tests for shared/audio_topology_switcher.py — dual-fx-routing Phase 4.

Verifies the live-graph switcher emits the right pw-cli + pactl
commands and migrates only the sink-inputs the caller asked for.
Uses an injected runner so no subprocess fires.
"""

from __future__ import annotations

from textwrap import dedent

from shared.audio_topology_switcher import (
    CommandResult,
    SwitchResult,
    switch_voice_path,
)


class _RunnerStub:
    """Captures every (cmd, response) interaction for assertion."""

    def __init__(self, responses: dict[str, CommandResult]) -> None:
        # responses keyed by the first command word (e.g. "pw-cli", "pactl")
        # plus the second word for pactl variants ("pactl list", "pactl move-sink-input").
        self.responses = responses
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> CommandResult:
        self.calls.append(cmd)
        # Resolve key: try the longest prefix match (4 words → 1 word).
        for n in (4, 3, 2, 1):
            key = " ".join(cmd[:n])
            if key in self.responses:
                return self.responses[key]
        return CommandResult(returncode=0, stdout="", stderr="")


_SHORT_SINKS = dedent(
    """
    42\thapax-livestream-tap\tPipeWire\tfloat32le 2ch 44100Hz\tIDLE
    63\talsa_output.pci-0000_73_00.6.analog-stereo\tPipeWire\ts24-3le 2ch 44100Hz\tRUNNING
    99\talsa_output.usb-Torso_Electronics_S-4\tPipeWire\ts32le 2ch 44100Hz\tIDLE
    """
).strip()


# ── Default-sink update ───────────────────────────────────────────────


class TestDefaultSinkUpdate:
    def test_invokes_pw_cli_set_default_audio_sink(self) -> None:
        runner = _RunnerStub(
            {
                "pw-cli set-default-audio-sink": CommandResult(0, "", ""),
                "pactl list": CommandResult(0, _SHORT_SINKS, ""),
            }
        )
        result = switch_voice_path(
            "alsa_output.usb-Torso_Electronics_S-4",
            _runner=runner,
        )
        assert result.default_set_ok
        # First call must be the set-default-audio-sink with the target.
        assert runner.calls[0] == [
            "pw-cli",
            "set-default-audio-sink",
            "alsa_output.usb-Torso_Electronics_S-4",
        ]

    def test_default_set_failure_records_warning_but_continues(self) -> None:
        runner = _RunnerStub(
            {
                "pw-cli set-default-audio-sink": CommandResult(1, "", "no such sink"),
                "pactl list": CommandResult(0, _SHORT_SINKS, ""),
            }
        )
        result = switch_voice_path(
            "alsa_output.usb-Torso_Electronics_S-4",
            _runner=runner,
        )
        assert not result.default_set_ok
        assert any("set-default-audio-sink failed" in w for w in result.warnings)


# ── Sink-id resolution ────────────────────────────────────────────────


class TestSinkIdResolution:
    def test_target_sink_missing_skips_migration(self) -> None:
        runner = _RunnerStub(
            {
                "pw-cli set-default-audio-sink": CommandResult(0, "", ""),
                "pactl list": CommandResult(0, _SHORT_SINKS, ""),
            }
        )
        result = switch_voice_path(
            "alsa_output.usb-NonExistent",
            _runner=runner,
        )
        assert result.moved_input_ids == ()
        assert any("not found in pactl listing" in w for w in result.warnings)
        # No move-sink-input call should have fired.
        assert not any(c[:2] == ["pactl", "move-sink-input"] for c in runner.calls)

    def test_pactl_list_failure_skips_migration(self) -> None:
        runner = _RunnerStub(
            {
                "pw-cli set-default-audio-sink": CommandResult(0, "", ""),
                "pactl list short sinks": CommandResult(2, "", "broken"),
            }
        )
        result = switch_voice_path(
            "alsa_output.usb-Torso_Electronics_S-4",
            _runner=runner,
        )
        assert result.moved_input_ids == ()
        assert any("pactl list short sinks failed" in w for w in result.warnings)


# ── Sink-input migration ──────────────────────────────────────────────


class TestSinkInputMigration:
    def test_moves_only_inputs_bound_to_prior_sink(self) -> None:
        # Two active inputs; only #100 is bound to the prior sink (id 63).
        sink_inputs_stdout = dedent(
            """
            100\tPipeWire\t-\t63\ts24-3le 2ch 44100Hz
            101\tPipeWire\t-\t42\tfloat32le 2ch 44100Hz
            """
        ).strip()
        responses = {
            "pw-cli set-default-audio-sink": CommandResult(0, "", ""),
            "pactl list short sinks": CommandResult(0, _SHORT_SINKS, ""),
            "pactl list short sink-inputs": CommandResult(0, sink_inputs_stdout, ""),
            "pactl move-sink-input": CommandResult(0, "", ""),
        }
        runner = _RunnerStub(responses)
        result = switch_voice_path(
            "alsa_output.usb-Torso_Electronics_S-4",
            prior_sink_name="alsa_output.pci-0000_73_00.6.analog-stereo",
            _runner=runner,
        )
        # Only input 100 moved.
        assert result.moved_input_ids == ("100",)
        # The move call used the numeric sink id (99 from _SHORT_SINKS).
        move_call = next(c for c in runner.calls if c[:2] == ["pactl", "move-sink-input"])
        assert move_call == ["pactl", "move-sink-input", "100", "99"]

    def test_moves_all_inputs_when_prior_sink_unspecified(self) -> None:
        sink_inputs_stdout = dedent(
            """
            100\tPipeWire\t-\t63\ts24-3le 2ch 44100Hz
            101\tPipeWire\t-\t42\tfloat32le 2ch 44100Hz
            """
        ).strip()
        responses = {
            "pw-cli set-default-audio-sink": CommandResult(0, "", ""),
            "pactl list short sinks": CommandResult(0, _SHORT_SINKS, ""),
            "pactl list short sink-inputs": CommandResult(0, sink_inputs_stdout, ""),
            "pactl move-sink-input": CommandResult(0, "", ""),
        }
        runner = _RunnerStub(responses)
        result = switch_voice_path(
            "alsa_output.usb-Torso_Electronics_S-4",
            _runner=runner,
        )
        assert set(result.moved_input_ids) == {"100", "101"}

    def test_individual_move_failure_recorded_as_warning(self) -> None:
        sink_inputs_stdout = "100\tPipeWire\t-\t63\ts24-3le 2ch 44100Hz"
        responses = {
            "pw-cli set-default-audio-sink": CommandResult(0, "", ""),
            "pactl list short sinks": CommandResult(0, _SHORT_SINKS, ""),
            "pactl list short sink-inputs": CommandResult(0, sink_inputs_stdout, ""),
            "pactl move-sink-input": CommandResult(1, "", "device busy"),
        }
        runner = _RunnerStub(responses)
        result = switch_voice_path(
            "alsa_output.usb-Torso_Electronics_S-4",
            prior_sink_name="alsa_output.pci-0000_73_00.6.analog-stereo",
            _runner=runner,
        )
        assert result.moved_input_ids == ()
        assert any("move-sink-input 100" in w for w in result.warnings)

    def test_no_active_inputs_returns_empty_moved(self) -> None:
        responses = {
            "pw-cli set-default-audio-sink": CommandResult(0, "", ""),
            "pactl list short sinks": CommandResult(0, _SHORT_SINKS, ""),
            "pactl list short sink-inputs": CommandResult(0, "", ""),
        }
        runner = _RunnerStub(responses)
        result = switch_voice_path(
            "alsa_output.usb-Torso_Electronics_S-4",
            _runner=runner,
        )
        assert result.moved_input_ids == ()
        assert result.default_set_ok


# ── Result shape ──────────────────────────────────────────────────────


class TestSwitchResultShape:
    def test_target_sink_field_carries_intended_target(self) -> None:
        runner = _RunnerStub(
            {
                "pw-cli set-default-audio-sink": CommandResult(0, "", ""),
                "pactl list short sinks": CommandResult(0, _SHORT_SINKS, ""),
                "pactl list short sink-inputs": CommandResult(0, "", ""),
            }
        )
        result = switch_voice_path(
            "alsa_output.usb-Torso_Electronics_S-4",
            _runner=runner,
        )
        assert isinstance(result, SwitchResult)
        assert result.target_sink == "alsa_output.usb-Torso_Electronics_S-4"
