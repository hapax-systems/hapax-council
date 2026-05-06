"""M8 sampler capture orchestration.

Routes a Hapax-owned PipeWire source into the Dirtywave M8 USB audio
input, drives the existing M8 button daemon to start/stop sample
recording, and always tears the loopback route back down.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from agents.m8_control.client import M8ControlClient
from agents.m8_control.daemon import BUTTON_BITS

DEFAULT_M8_USB_SINK = "alsa_output.usb-Dirtywave_M8_16558390-02.analog-stereo"
DEFAULT_LOOPBACK_NAME = "hapax-m8-sample-input"
DEFAULT_HOLD_MS = 80
DEFAULT_MAX_DURATION_S = 30.0
DEFAULT_SOURCE_NODES: dict[str, str] = {
    # The dedicated Reverie audio tap does not exist yet. Until that lands,
    # the broadcast monitor tap is the operator-owned software audio bus.
    "reverie": "hapax-livestream-tap.monitor",
    "livestream_tap": "hapax-livestream-tap.monitor",
    "daimonion_voice": "hapax-voice-fx-capture.monitor",
}
DEFAULT_START_SEQUENCE: tuple[tuple[str, ...], ...] = (("EDIT",),)
DEFAULT_STOP_SEQUENCE: tuple[tuple[str, ...], ...] = (("EDIT",),)

PactlRunner = Callable[[Sequence[str]], str]
SleepFn = Callable[[float], None]


class M8ButtonClient(Protocol):
    def button(self, *names: str, hold_ms: int = DEFAULT_HOLD_MS) -> dict: ...


class M8SampleCaptureError(RuntimeError):
    """Typed error for sample-capture failures."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True)
class M8SampleCaptureConfig:
    """Runtime-configurable PipeWire and M8 button settings."""

    audio_sources: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_SOURCE_NODES))
    m8_sink: str = DEFAULT_M8_USB_SINK
    loopback_name: str = DEFAULT_LOOPBACK_NAME
    hold_ms: int = DEFAULT_HOLD_MS
    max_duration_s: float = DEFAULT_MAX_DURATION_S
    start_sequence: tuple[tuple[str, ...], ...] = DEFAULT_START_SEQUENCE
    stop_sequence: tuple[tuple[str, ...], ...] = DEFAULT_STOP_SEQUENCE
    latency_msec: int = 20


class M8SampleCapture:
    """Route one audio source to the M8 sampler and press start/stop.

    The operator template leaves the M8 in Sample Editor with cursor on
    START. Pressing EDIT starts recording; pressing EDIT again stops it.
    Those defaults can be replaced at construction time if a project
    template needs a longer navigation sequence.
    """

    def __init__(
        self,
        *,
        client: M8ButtonClient | None = None,
        config: M8SampleCaptureConfig | None = None,
        pactl_runner: PactlRunner | None = None,
        sleep_fn: SleepFn = time.sleep,
    ) -> None:
        self._client = client or M8ControlClient()
        self._config = config or M8SampleCaptureConfig()
        self._pactl_runner = pactl_runner or _default_pactl_runner
        self._sleep_fn = sleep_fn
        _validate_button_sequence(self._config.start_sequence, "start_sequence")
        _validate_button_sequence(self._config.stop_sequence, "stop_sequence")

    def capture(self, audio_source: str, duration_s: float, sample_slot_name: str) -> dict:
        """Capture a single sample slot and return a structured report."""

        module_id: str | None = None
        recording_started = False
        try:
            source_node = self._resolve_audio_source(audio_source)
            duration = self._validate_duration(duration_s)
            slot_name = self._validate_slot_name(sample_slot_name)
            module_id = self._load_loopback(source_node)
            self._dispatch_sequence(self._config.start_sequence)
            recording_started = True
            self._sleep_fn(duration)
            self._dispatch_sequence(self._config.stop_sequence)
            recording_started = False
        except M8SampleCaptureError as exc:
            stop_error = self._stop_if_recording(recording_started)
            restore_error = self._restore_route(module_id)
            return _error_payload(exc, stop_error=stop_error, restore_error=restore_error)
        except Exception as exc:  # noqa: BLE001
            stop_error = self._stop_if_recording(recording_started)
            restore_error = self._restore_route(module_id)
            typed = M8SampleCaptureError(type(exc).__name__, str(exc))
            return _error_payload(typed, stop_error=stop_error, restore_error=restore_error)

        restore_error = self._restore_route(module_id)
        if restore_error is not None:
            return _error_payload(
                M8SampleCaptureError("route_restore", restore_error),
            )

        return {
            "ok": True,
            "audio_source": audio_source,
            "source_node": source_node,
            "slot_name": slot_name,
            "duration_s": duration,
            "loopback_module_id": module_id,
        }

    def _resolve_audio_source(self, audio_source: str) -> str:
        try:
            return self._config.audio_sources[audio_source]
        except KeyError as exc:
            known = ", ".join(sorted(self._config.audio_sources))
            raise M8SampleCaptureError(
                "audio_source",
                f"unknown audio_source {audio_source!r}; known: {known}",
            ) from exc

    def _validate_duration(self, duration_s: float) -> float:
        duration = float(duration_s)
        if duration <= 0:
            raise M8SampleCaptureError("duration", "duration_s must be greater than zero")
        if duration > self._config.max_duration_s:
            raise M8SampleCaptureError(
                "duration",
                f"duration_s {duration:g} exceeds cap {self._config.max_duration_s:g}",
            )
        return duration

    def _validate_slot_name(self, sample_slot_name: str) -> str:
        slot_name = sample_slot_name.strip()
        if not slot_name:
            raise M8SampleCaptureError("slot_name", "sample_slot_name must not be blank")
        return slot_name

    def _load_loopback(self, source_node: str) -> str:
        module_id = self._pactl(
            [
                "load-module",
                "module-loopback",
                f"source={source_node}",
                f"sink={self._config.m8_sink}",
                "source_dont_move=true",
                "sink_dont_move=true",
                "remix=false",
                f"latency_msec={self._config.latency_msec}",
                (
                    "source_output_properties="
                    f"media.name='{self._config.loopback_name} capture {source_node}' "
                    "node.dont-reconnect=true node.passive=true"
                ),
                (
                    "sink_input_properties="
                    f"media.name='{self._config.loopback_name} playback to M8 USB' "
                    "node.dont-reconnect=true"
                ),
            ]
        )
        if not module_id:
            raise M8SampleCaptureError("pipewire_route", "pactl returned an empty module id")
        return module_id

    def _dispatch_sequence(self, sequence: Sequence[Sequence[str]]) -> None:
        for step_idx, chord in enumerate(sequence):
            ack = self._client.button(*chord, hold_ms=self._config.hold_ms)
            if not ack.get("ok"):
                error = ack.get("error", "unknown")
                raise M8SampleCaptureError(
                    "m8_control",
                    f"button sequence failed at step {step_idx}: {error}",
                )

    def _restore_route(self, module_id: str | None) -> str | None:
        if module_id is None:
            return None
        try:
            self._pactl(["unload-module", module_id])
        except M8SampleCaptureError as exc:
            return str(exc)
        return None

    def _stop_if_recording(self, recording_started: bool) -> str | None:
        if not recording_started:
            return None
        try:
            self._dispatch_sequence(self._config.stop_sequence)
        except M8SampleCaptureError as exc:
            return str(exc)
        return None

    def _pactl(self, args: Sequence[str]) -> str:
        try:
            return self._pactl_runner(args).strip()
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            detail = stderr or str(exc)
            raise M8SampleCaptureError("pipewire_route", detail) from exc


def _validate_button_sequence(sequence: Sequence[Sequence[str]], field_name: str) -> None:
    if not sequence:
        raise M8SampleCaptureError(field_name, f"{field_name} must not be empty")
    for step_idx, chord in enumerate(sequence):
        if not chord:
            raise M8SampleCaptureError(field_name, f"{field_name}[{step_idx}] is empty")
        for name in chord:
            if name not in BUTTON_BITS:
                known = ", ".join(sorted(BUTTON_BITS))
                raise M8SampleCaptureError(
                    field_name,
                    f"unknown button {name!r} in {field_name}[{step_idx}]; known: {known}",
                )


def _default_pactl_runner(args: Sequence[str]) -> str:
    completed = subprocess.run(
        ["pactl", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _error_payload(
    exc: M8SampleCaptureError,
    *,
    stop_error: str | None = None,
    restore_error: str | None = None,
) -> dict:
    payload = {"ok": False, "error_type": exc.error_type, "error": str(exc)}
    if stop_error is not None:
        payload["stop_error"] = stop_error
    if restore_error is not None:
        payload["restore_error"] = restore_error
    return payload
