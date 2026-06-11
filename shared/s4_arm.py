"""Witness-verified Torso S-4 segment arm flow.

This module encodes the 2026-06-10 bench landing sequence:

1. Assert the empirical gain ladder from ``config/equipment`` using CC only.
2. Run the marker wet-return witness against the live tap path.
3. If the witness is dark, use the S-4 monitor toggle and witness again.

The S-4 is write-only. This code never treats a MIDI send as proof of state;
only the marker witness can make the final verdict green.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from shared.s4_midi import (
    DEFAULT_CC_DELAY_MS,
    close_output,
    emit_cc,
    emit_note_on,
    find_s4_midi_output,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LADDER_PATH = REPO_ROOT / "config" / "equipment" / "s4-gain-ladder-20260610.yaml"
DEFAULT_PROBE_SCRIPT = REPO_ROOT / "scripts" / "hapax-s4-wet-return-probe"
DEFAULT_RECEIPT_PATH = Path("/dev/shm/hapax-audio/s4-arm-receipt.json")
DEFAULT_TASK_ID = "voice-w1-s4-arm-script-20260611"
DEFAULT_AUTHORITY_CASE = "CASE-VOICE-FOUNDATION-20260610"
DEFAULT_PARENT_SPEC = (
    "/home/hapax/Documents/Personal/30-areas/hapax/"
    "tts-voice-foundation-audit-2026-06-10-v2-execution.md"
)

DEFAULT_MONITOR_TOGGLE_NOTE = 41
DEFAULT_MONITOR_TOGGLE_HUMAN_CHANNEL = 16
DEFAULT_MONITOR_TOGGLE_VELOCITY = 127
DEFAULT_MONITOR_SETTLE_S = 0.25
DEFAULT_PROBE_TIMEOUT_S = 20.0


class S4ArmError(RuntimeError):
    """Configuration or runtime failure that prevents a valid arm attempt."""


@dataclass(frozen=True)
class GainLadderCommand:
    """One empirically verified S-4 gain command.

    ``human_channel`` is 1-indexed as written in the YAML and on the device.
    ``midi_channel`` is 0-indexed for mido.
    """

    human_channel: int
    midi_channel: int
    cc: int
    value: int

    @classmethod
    def from_mapping(cls, entry: Any, *, index: int) -> GainLadderCommand:
        if not isinstance(entry, dict):
            raise S4ArmError(f"ladder[{index}] must be a mapping")
        try:
            human_channel = int(entry["channel"])
            cc = int(entry["cc"])
            value = int(entry["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise S4ArmError(f"ladder[{index}] must carry integer channel/cc/value") from exc
        if not 1 <= human_channel <= 16:
            raise S4ArmError(f"ladder[{index}] channel out of range: {human_channel}")
        if not 0 <= cc <= 127:
            raise S4ArmError(f"ladder[{index}] cc out of range: {cc}")
        if not 0 <= value <= 127:
            raise S4ArmError(f"ladder[{index}] value out of range: {value}")
        return cls(
            human_channel=human_channel,
            midi_channel=human_channel - 1,
            cc=cc,
            value=value,
        )


@dataclass(frozen=True)
class GainLadder:
    path: str
    sha256: str
    discovered_at: str
    method: str
    transport: str
    result_dbfs_at_tap: float | None
    commands: tuple[GainLadderCommand, ...]


@dataclass(frozen=True)
class MidiAssertionResult:
    expected: int
    emitted: int
    ok: bool
    without_program_change: bool
    failures: tuple[str, ...]


ProbeRunner = Callable[[str], dict[str, Any]]
MidiOutputFactory = Callable[[], Any]


def load_gain_ladder(path: Path = DEFAULT_LADDER_PATH) -> GainLadder:
    """Load and validate the empirical gain ladder YAML."""

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise S4ArmError(f"could not read gain ladder: {path}") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise S4ArmError(f"gain ladder YAML is invalid: {path}") from exc
    if not isinstance(data, dict):
        raise S4ArmError("gain ladder YAML must be a mapping")

    entries = data.get("ladder")
    if not isinstance(entries, list) or not entries:
        raise S4ArmError("gain ladder YAML must contain a non-empty ladder list")

    commands = tuple(
        GainLadderCommand.from_mapping(entry, index=index) for index, entry in enumerate(entries)
    )
    result_raw = data.get("result_dbfs_at_tap")
    result_dbfs = float(result_raw) if isinstance(result_raw, int | float) else None
    return GainLadder(
        path=str(path),
        sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        discovered_at=str(data.get("discovered_at") or ""),
        method=str(data.get("method") or ""),
        transport=str(data.get("transport") or ""),
        result_dbfs_at_tap=result_dbfs,
        commands=commands,
    )


def assert_gain_ladder(
    output: Any,
    commands: Sequence[GainLadderCommand],
    *,
    delay_ms: float = DEFAULT_CC_DELAY_MS,
) -> MidiAssertionResult:
    """Emit the empirical gain ladder as CC messages only."""

    failures: list[str] = []
    emitted = 0
    for index, command in enumerate(commands):
        if emit_cc(
            output,
            command.cc,
            command.value,
            channel=command.midi_channel,
            delay_ms=delay_ms,
        ):
            emitted += 1
        else:
            failures.append(
                f"ladder_emit_failed:index={index}:channel={command.human_channel}:cc={command.cc}"
            )
    return MidiAssertionResult(
        expected=len(commands),
        emitted=emitted,
        ok=emitted == len(commands),
        without_program_change=True,
        failures=tuple(failures),
    )


def emit_monitor_toggle(
    output: Any,
    *,
    note: int = DEFAULT_MONITOR_TOGGLE_NOTE,
    human_channel: int = DEFAULT_MONITOR_TOGGLE_HUMAN_CHANNEL,
    velocity: int = DEFAULT_MONITOR_TOGGLE_VELOCITY,
    delay_ms: float = DEFAULT_CC_DELAY_MS,
) -> bool:
    """Emit the write-only S-4 monitor toggle note.

    The caller must run a marker witness after this. Sending the note is never
    recorded as proof that monitor state changed.
    """

    if not 1 <= human_channel <= 16:
        return False
    return emit_note_on(
        output,
        note,
        velocity,
        channel=human_channel - 1,
        delay_ms=delay_ms,
    )


def run_wet_return_probe_subprocess(
    *,
    label: str,
    probe_script: Path = DEFAULT_PROBE_SCRIPT,
    update_witness: bool = True,
    timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
    extra_args: Sequence[str] = (),
) -> dict[str, Any]:
    """Run the existing marker probe script and return its JSON payload."""

    argv = [str(probe_script)]
    if update_witness:
        argv.append("--update-witness")
    argv.extend(extra_args)
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_s,
        )
    except OSError as exc:
        return {
            "ok": False,
            "s4_wet_return_signal": False,
            "reasons": ["probe_process_unavailable"],
            "probe_label": label,
            "probe_command": argv,
            "stderr_tail": str(exc)[-1000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "s4_wet_return_signal": False,
            "reasons": ["probe_timeout"],
            "probe_label": label,
            "probe_command": argv,
            "stderr_tail": str(exc)[-1000:],
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "s4_wet_return_signal": False,
            "reasons": ["probe_json_parse_failed"],
            "probe_label": label,
            "probe_command": argv,
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-1000:],
            "stderr_tail": completed.stderr[-1000:],
        }
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "s4_wet_return_signal": False,
            "reasons": ["probe_json_not_object"],
            "probe_label": label,
            "probe_command": argv,
            "returncode": completed.returncode,
        }
    payload.setdefault("reasons", [])
    payload["probe_label"] = label
    payload["probe_command"] = argv
    payload["returncode"] = completed.returncode
    payload["stderr_tail"] = completed.stderr[-1000:]
    if completed.returncode != 0:
        reasons = payload.get("reasons")
        if isinstance(reasons, list):
            reasons.append("probe_process_failed")
    return payload


def probe_green(probe: dict[str, Any]) -> bool:
    """True when the marker probe completed and witnessed wet return signal."""

    return (
        probe.get("returncode") in (None, 0)
        and bool(probe.get("ok"))
        and bool(probe.get("s4_wet_return_signal"))
    )


def probe_reason_tags(probe: dict[str, Any]) -> list[str]:
    reasons = probe.get("reasons")
    tags = [str(reason) for reason in reasons] if isinstance(reasons, list) else []
    if probe.get("returncode") not in (None, 0):
        tags.append("probe_process_failed")
    if not probe.get("ok"):
        tags.append("probe_not_ok")
    if not probe.get("s4_wet_return_signal"):
        tags.append("s4_wet_return_signal_false")
    return sorted(set(tags))


def _capture_marker_summary(capture: Any) -> list[dict[str, Any]]:
    if not isinstance(capture, dict):
        return []
    top = capture.get("top_marker_channels")
    if isinstance(top, list):
        return [entry for entry in top if isinstance(entry, dict)][:5]
    return []


def summarize_probe(label: str, probe: dict[str, Any]) -> dict[str, Any]:
    captures = probe.get("captures") if isinstance(probe.get("captures"), dict) else {}
    return {
        "label": label,
        "ok": bool(probe.get("ok")),
        "green": probe_green(probe),
        "s4_wet_return_signal": bool(probe.get("s4_wet_return_signal")),
        "reasons": probe_reason_tags(probe),
        "structural_route_present": bool(probe.get("structural_route_present")),
        "witness_updated": bool(probe.get("witness_updated")),
        "playback_returncode": (
            probe.get("playback", {}).get("returncode")
            if isinstance(probe.get("playback"), dict)
            else None
        ),
        "capture_markers": {
            name: _capture_marker_summary(capture)
            for name, capture in captures.items()
            if name
            in {
                "dry_loudnorm_playback",
                "mk5_input_aux2_aux3_raw",
                "wet_voice_playback",
                "broadcast_normalized",
            }
        },
    }


def write_receipt(receipt: dict[str, Any], path: Path) -> None:
    """Atomically write the arm receipt JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def run_s4_arm(
    *,
    ladder_path: Path = DEFAULT_LADDER_PATH,
    receipt_path: Path | None = DEFAULT_RECEIPT_PATH,
    task_id: str = DEFAULT_TASK_ID,
    authority_case: str = DEFAULT_AUTHORITY_CASE,
    parent_spec: str = DEFAULT_PARENT_SPEC,
    pre_segment_check: bool = False,
    update_witness: bool = True,
    probe_script: Path = DEFAULT_PROBE_SCRIPT,
    probe_timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
    probe_extra_args: Sequence[str] = (),
    monitor_toggle: bool = True,
    restore_on_failed_toggle: bool = True,
    monitor_toggle_note: int = DEFAULT_MONITOR_TOGGLE_NOTE,
    monitor_toggle_human_channel: int = DEFAULT_MONITOR_TOGGLE_HUMAN_CHANNEL,
    monitor_settle_s: float = DEFAULT_MONITOR_SETTLE_S,
    cc_delay_ms: float = DEFAULT_CC_DELAY_MS,
    midi_output_factory: MidiOutputFactory = find_s4_midi_output,
    probe_runner: ProbeRunner | None = None,
    now: Callable[[], str] = _now_iso,
) -> dict[str, Any]:
    """Run the full arm sequence and return the receipt payload."""

    generated_at = now()
    ladder = load_gain_ladder(ladder_path)
    output = midi_output_factory()
    probes: list[dict[str, Any]] = []
    probe_summaries: list[dict[str, Any]] = []
    monitor_events: list[dict[str, Any]] = []
    failure_reasons: list[str] = []
    ladder_result = MidiAssertionResult(
        expected=len(ladder.commands),
        emitted=0,
        ok=False,
        without_program_change=True,
        failures=("midi_output_missing",),
    )

    def run_probe(label: str) -> dict[str, Any]:
        runner = probe_runner
        if runner is None:
            result = run_wet_return_probe_subprocess(
                label=label,
                probe_script=probe_script,
                update_witness=update_witness,
                timeout_s=probe_timeout_s,
                extra_args=probe_extra_args,
            )
        else:
            result = runner(label)
        probes.append(result)
        probe_summaries.append(summarize_probe(label, result))
        return result

    try:
        if output is None:
            failure_reasons.append("midi_output_missing")
        else:
            ladder_result = assert_gain_ladder(output, ladder.commands, delay_ms=cc_delay_ms)
            if not ladder_result.ok:
                failure_reasons.extend(ladder_result.failures)

            if ladder_result.ok:
                initial = run_probe("initial_marker_witness")
                if not probe_green(initial) and monitor_toggle:
                    first_toggle = emit_monitor_toggle(
                        output,
                        note=monitor_toggle_note,
                        human_channel=monitor_toggle_human_channel,
                        delay_ms=cc_delay_ms,
                    )
                    monitor_events.append(
                        {
                            "label": "monitor_toggle_attempt",
                            "sent": first_toggle,
                            "note": monitor_toggle_note,
                            "human_channel": monitor_toggle_human_channel,
                            "requires_followup_witness": True,
                        }
                    )
                    if first_toggle:
                        if monitor_settle_s > 0:
                            time.sleep(monitor_settle_s)
                        after_toggle = run_probe("after_monitor_toggle")
                        if not probe_green(after_toggle) and restore_on_failed_toggle:
                            restore = emit_monitor_toggle(
                                output,
                                note=monitor_toggle_note,
                                human_channel=monitor_toggle_human_channel,
                                delay_ms=cc_delay_ms,
                            )
                            monitor_events.append(
                                {
                                    "label": "monitor_toggle_restore_after_dark",
                                    "sent": restore,
                                    "note": monitor_toggle_note,
                                    "human_channel": monitor_toggle_human_channel,
                                    "requires_followup_witness": True,
                                }
                            )
                            if restore:
                                if monitor_settle_s > 0:
                                    time.sleep(monitor_settle_s)
                                run_probe("after_monitor_toggle_restore")
                    else:
                        failure_reasons.append("monitor_toggle_emit_failed")
    finally:
        close_output(output)

    final_probe = probes[-1] if probes else {}
    verdict = "green" if probe_green(final_probe) and ladder_result.ok else "red"
    if verdict != "green":
        failure_reasons.extend(probe_reason_tags(final_probe))
    receipt = {
        "s4_arm_receipt_version": 1,
        "task_id": task_id,
        "authority_case": authority_case,
        "parent_spec": parent_spec,
        "generated_at": generated_at,
        "pre_segment_check": pre_segment_check,
        "ok": verdict == "green",
        "verdict": verdict,
        "contract": {
            "sequence": [
                "assert_empirical_gain_ladder_without_program_change",
                "marker_witness_vs_tap",
                "monitor_toggle_only_if_dark_with_followup_witness",
            ],
            "stateless_toggle_doctrine": (
                "monitor note is a toggle; final state claims require a fresh marker witness"
            ),
            "scene_recall_policy": "no_program_change_in_arm_path",
        },
        "ladder": {
            **asdict(ladder),
            "commands": [asdict(command) for command in ladder.commands],
        },
        "ladder_assertion": asdict(ladder_result),
        "probe_sequence": probe_summaries,
        "monitor_toggle": {
            "enabled": monitor_toggle,
            "restore_on_failed_toggle": restore_on_failed_toggle,
            "events": monitor_events,
        },
        "failure_reasons": sorted(set(failure_reasons)),
        "receipt_path": str(receipt_path) if receipt_path is not None else None,
    }
    if receipt_path is not None:
        write_receipt(receipt, receipt_path)
    return receipt


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Witness-verified Torso S-4 segment arm")
    parser.add_argument("--ladder-path", type=Path, default=DEFAULT_LADDER_PATH)
    parser.add_argument("--receipt-path", type=Path, default=DEFAULT_RECEIPT_PATH)
    parser.add_argument("--no-receipt", action="store_true")
    parser.add_argument("--probe-script", type=Path, default=DEFAULT_PROBE_SCRIPT)
    parser.add_argument("--probe-timeout-s", type=float, default=DEFAULT_PROBE_TIMEOUT_S)
    parser.add_argument("--probe-arg", action="append", default=[])
    parser.add_argument("--no-update-witness", action="store_true")
    parser.add_argument("--no-monitor-toggle", action="store_true")
    parser.add_argument("--no-restore-on-failed-toggle", action="store_true")
    parser.add_argument("--monitor-toggle-note", type=int, default=DEFAULT_MONITOR_TOGGLE_NOTE)
    parser.add_argument(
        "--monitor-toggle-channel",
        type=int,
        default=DEFAULT_MONITOR_TOGGLE_HUMAN_CHANNEL,
        help="1-indexed MIDI channel for the S-4 monitor toggle",
    )
    parser.add_argument("--monitor-settle-s", type=float, default=DEFAULT_MONITOR_SETTLE_S)
    parser.add_argument("--cc-delay-ms", type=float, default=DEFAULT_CC_DELAY_MS)
    parser.add_argument("--pre-segment-check", action="store_true")
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    parser.add_argument("--authority-case", default=DEFAULT_AUTHORITY_CASE)
    parser.add_argument("--parent-spec", default=DEFAULT_PARENT_SPEC)
    parser.add_argument("--compact", action="store_true")
    return parser.parse_args(list(argv))


def main(
    argv: Sequence[str] | None = None,
    *,
    midi_output_factory: MidiOutputFactory = find_s4_midi_output,
    probe_runner: ProbeRunner | None = None,
) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    receipt_path = None if args.no_receipt else args.receipt_path
    try:
        receipt = run_s4_arm(
            ladder_path=args.ladder_path,
            receipt_path=receipt_path,
            task_id=args.task_id,
            authority_case=args.authority_case,
            parent_spec=args.parent_spec,
            pre_segment_check=args.pre_segment_check,
            update_witness=not args.no_update_witness,
            probe_script=args.probe_script,
            probe_timeout_s=args.probe_timeout_s,
            probe_extra_args=tuple(args.probe_arg),
            monitor_toggle=not args.no_monitor_toggle,
            restore_on_failed_toggle=not args.no_restore_on_failed_toggle,
            monitor_toggle_note=args.monitor_toggle_note,
            monitor_toggle_human_channel=args.monitor_toggle_channel,
            monitor_settle_s=args.monitor_settle_s,
            cc_delay_ms=args.cc_delay_ms,
            midi_output_factory=midi_output_factory,
            probe_runner=probe_runner,
        )
    except S4ArmError as exc:
        error_receipt = {
            "s4_arm_receipt_version": 1,
            "task_id": args.task_id,
            "authority_case": args.authority_case,
            "generated_at": _now_iso(),
            "pre_segment_check": args.pre_segment_check,
            "ok": False,
            "verdict": "red",
            "failure_reasons": [str(exc)],
            "receipt_path": str(receipt_path) if receipt_path is not None else None,
        }
        if receipt_path is not None:
            write_receipt(error_receipt, receipt_path)
        print(json.dumps(error_receipt, indent=None if args.compact else 2, sort_keys=True))
        return 2
    print(json.dumps(receipt, indent=None if args.compact else 2, sort_keys=True))
    return 0 if receipt.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
