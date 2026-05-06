"""Polyend instrument activity-reveal ward.

Phase 5 of the activity-reveal ward family adds a Cairo-native source
for a Polyend-class USB instrument. There is no external display
protocol to bridge, so the visual grammar is derived from local UAC
audio and MIDI activity only: waveform in the upper half, 16x8 MIDI
note grid in the lower half.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.activity_reveal_ward import ActivityRevealMixin
from agents.studio_compositor.homage.rendering import active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

DEFAULT_USB_ROOT: Path = Path("/sys/bus/usb/devices")
DEFAULT_USB_VENDOR_ID: str = "0x1fc9"
DEFAULT_DEVICE_NAME_PATTERN: str = "Polyend"
DEFAULT_SAMPLE_RATE: int = 48_000
DEFAULT_CHANNELS: int = 2
DEFAULT_RING_BUFFER_S: float = 0.20
DEFAULT_RECRUITMENT_PATH: Path = Path("/dev/shm/hapax-compositor/recent-recruitment.json")
DEFAULT_RECRUITMENT_WINDOW_S: float = 60.0

_FEATURE_DISABLED_ENV: str = "HAPAX_ACTIVITY_REVEAL_POLYEND_DISABLED"
_POLYEND_REVEAL_CAPABILITY: str = "ward.reveal.polyend-instrument"
_RMS_THRESHOLD_DBFS: float = -40.0
_BASE_SCORE_PRESENT: float = 0.30
_AUDIO_ACTIVE_BOOST: float = 0.30
_AFFORDANCE_RECRUITED_BOOST: float = 0.40
_MIN_RMS_FOR_DBFS: float = 1.0e-12


def _truthy_env(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return False
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def _dbfs_from_rms(rms: float) -> float:
    safe = max(abs(float(rms)), _MIN_RMS_FOR_DBFS)
    return 20.0 * math.log10(safe)


def _normalised_vid(value: str) -> str:
    return value.strip().lower().removeprefix("0x")


def _usb_vid_present(
    *,
    root: Path = DEFAULT_USB_ROOT,
    vendor_id: str = DEFAULT_USB_VENDOR_ID,
) -> bool:
    """Return True when any USB device under ``root`` has ``vendor_id``."""

    wanted = _normalised_vid(vendor_id)
    try:
        candidates = list(root.glob("*/idVendor"))
    except OSError:
        return False
    for id_vendor in candidates:
        try:
            found = _normalised_vid(id_vendor.read_text(encoding="utf-8"))
        except OSError:
            continue
        if found == wanted:
            return True
    return False


def _read_recruitment_age_s(
    path: Path,
    capability: str,
    *,
    now: float | None = None,
) -> float | None:
    """Return age of the recent-recruitment marker for ``capability``."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    families = data.get("families") or {}
    if not isinstance(families, dict):
        return None
    entry = families.get(capability) or {}
    if not isinstance(entry, dict):
        return None
    ts = entry.get("last_recruited_ts")
    if not isinstance(ts, (int, float)):
        return None
    now_ts = time.time() if now is None else now
    return max(0.0, now_ts - float(ts))


def _colour(
    pkg: Any,
    role: str,
    *,
    alpha: float | None = None,
    fallback: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    try:
        rgba = tuple(float(v) for v in pkg.resolve_colour(role))
    except Exception:
        rgba = fallback
    if len(rgba) < 4:
        rgba = (*rgba[:3], 1.0)
    if alpha is not None:
        return (rgba[0], rgba[1], rgba[2], alpha)
    return (rgba[0], rgba[1], rgba[2], rgba[3])


@dataclass(frozen=True, slots=True)
class MidiNoteEvent:
    note: int
    velocity: int
    channel: int
    ts: float


class AudioRingBuffer:
    """Thread-safe mono ring buffer for a short UAC audio snapshot."""

    def __init__(
        self,
        *,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        duration_s: float = DEFAULT_RING_BUFFER_S,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        maxlen = max(1, int(sample_rate * duration_s))
        self._samples: deque[float] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def append(self, frames: Any) -> None:
        """Append interleaved or frame-shaped samples.

        ``sounddevice`` usually supplies a NumPy array shaped
        ``(frames, channels)``. Tests and fallback callers may supply
        plain Python sequences; both shapes are accepted.
        """

        if hasattr(frames, "tolist"):
            frames = frames.tolist()
        samples: list[float] = []
        try:
            iterator = iter(frames)
        except TypeError:
            return
        for frame in iterator:
            try:
                if isinstance(frame, (int, float)):
                    mono = float(frame)
                else:
                    values = [float(value) for value in frame]
                    if not values:
                        continue
                    mono = sum(values[: self.channels]) / min(len(values), self.channels)
            except (TypeError, ValueError):
                continue
            samples.append(max(-1.0, min(1.0, mono)))
        if not samples:
            return
        with self._lock:
            self._samples.extend(samples)

    def snapshot(self) -> tuple[float, ...]:
        with self._lock:
            return tuple(self._samples)

    def rms(self) -> float:
        samples = self.snapshot()
        if not samples:
            return 0.0
        return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def _import_sounddevice() -> Any | None:
    try:
        import sounddevice as sd
    except ImportError:
        return None
    return sd


def _sounddevice_input_index(sd_module: Any, name_pattern: str) -> int | None:
    """Find the first input-capable sounddevice device matching pattern."""

    try:
        devices = sd_module.query_devices()
    except Exception:
        log.debug("polyend: sounddevice query_devices failed", exc_info=True)
        return None
    if isinstance(devices, dict):
        devices = [devices]
    needle = name_pattern.casefold()
    for index, device in enumerate(devices):
        if not isinstance(device, dict):
            continue
        name = str(device.get("name", ""))
        try:
            max_inputs = int(device.get("max_input_channels", 0))
        except (TypeError, ValueError):
            max_inputs = 0
        if max_inputs > 0 and needle in name.casefold():
            return index
    return None


class PolyendAudioReader:
    """Owns the sounddevice UAC stream and the 200 ms waveform buffer."""

    def __init__(
        self,
        *,
        name_pattern: str = DEFAULT_DEVICE_NAME_PATTERN,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        ring_buffer_s: float = DEFAULT_RING_BUFFER_S,
        sd_module: Any | None = None,
    ) -> None:
        self.name_pattern = name_pattern
        self.sample_rate = sample_rate
        self.channels = channels
        self.ring = AudioRingBuffer(
            sample_rate=sample_rate,
            channels=channels,
            duration_s=ring_buffer_s,
        )
        self._sd_module = sd_module
        self._stream: Any | None = None
        self.device_index: int | None = None

    def start(self) -> bool:
        sd_module = self._sd_module or _import_sounddevice()
        if sd_module is None:
            log.debug("polyend: sounddevice unavailable; audio reader dormant")
            return False
        device_index = _sounddevice_input_index(sd_module, self.name_pattern)
        if device_index is None:
            log.debug("polyend: no input device matching %r", self.name_pattern)
            return False
        try:
            stream = sd_module.InputStream(
                samplerate=self.sample_rate,
                device=device_index,
                channels=self.channels,
                callback=self._callback,
            )
            stream.start()
        except Exception:
            log.debug("polyend: failed to open sounddevice input stream", exc_info=True)
            return False
        self._sd_module = sd_module
        self._stream = stream
        self.device_index = device_index
        return True

    def _callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        del frames, time_info
        if status:
            log.debug("polyend: sounddevice callback status=%s", status)
        self.ring.append(indata)

    def snapshot(self) -> tuple[float, ...]:
        return self.ring.snapshot()

    def rms(self) -> float:
        return self.ring.rms()

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        for method_name in ("stop", "close"):
            method = getattr(stream, method_name, None)
            if method is None:
                continue
            try:
                method()
            except Exception:
                log.debug("polyend: sounddevice stream %s failed", method_name, exc_info=True)


def _import_rtmidi() -> Any | None:
    try:
        import rtmidi
    except ImportError:
        return None
    return rtmidi


class PolyendMidiSubscriber:
    """Subscribes to a Polyend MIDI input and stores the last 32 note-ons."""

    def __init__(
        self,
        *,
        name_pattern: str = DEFAULT_DEVICE_NAME_PATTERN,
        rtmidi_module: Any | None = None,
    ) -> None:
        self.name_pattern = name_pattern
        self._rtmidi_module = rtmidi_module
        self._midi_in: Any | None = None
        self._events: deque[MidiNoteEvent] = deque(maxlen=32)
        self._lock = threading.Lock()

    def start(self) -> bool:
        rtmidi_module = self._rtmidi_module or _import_rtmidi()
        if rtmidi_module is None:
            log.debug("polyend: python-rtmidi unavailable; MIDI subscriber dormant")
            return False
        try:
            midi_in = rtmidi_module.MidiIn()
            port_index = self._find_port_index(midi_in)
            if port_index is None:
                return False
            self._open_port(midi_in, port_index)
            ignore_types = getattr(midi_in, "ignore_types", None)
            if ignore_types is not None:
                try:
                    ignore_types(sysex=True, timing=True, active_sense=True)
                except TypeError:
                    ignore_types(True, True, True)
            else:
                ignore_types = getattr(midi_in, "ignoreTypes", None)
                if ignore_types is not None:
                    ignore_types(True, True, True)
            midi_in.set_callback(self._on_midi)
        except Exception:
            log.debug("polyend: failed to open MIDI input", exc_info=True)
            return False
        self._rtmidi_module = rtmidi_module
        self._midi_in = midi_in
        return True

    def _find_port_index(self, midi_in: Any) -> int | None:
        needle = self.name_pattern.casefold()
        get_ports = getattr(midi_in, "get_ports", None)
        if get_ports is not None:
            try:
                ports = list(get_ports())
            except Exception:
                return None
            for index, name in enumerate(ports):
                if needle in str(name).casefold():
                    return index
            return None
        try:
            count = int(midi_in.getPortCount())
        except Exception:
            return None
        for index in range(count):
            try:
                name = str(midi_in.getPortName(index))
            except Exception:
                continue
            if needle in name.casefold():
                return index
        return None

    @staticmethod
    def _open_port(midi_in: Any, port_index: int) -> None:
        open_port = getattr(midi_in, "open_port", None)
        if open_port is not None:
            open_port(port_index)
            return
        midi_in.openPort(port_index)

    def _on_midi(self, event: Any, data: Any = None) -> None:
        del data
        message = event
        if isinstance(event, tuple) and event:
            message = event[0]
        self.record_message(message)

    def record_message(self, message: Any, *, ts: float | None = None) -> bool:
        try:
            status = int(message[0])
            note = int(message[1])
            velocity = int(message[2])
        except (TypeError, ValueError, IndexError):
            return False
        if status & 0xF0 != 0x90 or velocity <= 0:
            return False
        event = MidiNoteEvent(
            note=max(0, min(127, note)),
            velocity=max(1, min(127, velocity)),
            channel=status & 0x0F,
            ts=time.monotonic() if ts is None else ts,
        )
        with self._lock:
            self._events.append(event)
        return True

    def snapshot(self) -> tuple[MidiNoteEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def stop(self) -> None:
        midi_in = self._midi_in
        self._midi_in = None
        if midi_in is None:
            return
        for method_name in ("cancel_callback", "close_port", "closePort"):
            method = getattr(midi_in, method_name, None)
            if method is None:
                continue
            try:
                method()
            except Exception:
                log.debug("polyend: MIDI %s failed", method_name, exc_info=True)


class PolyendInstrumentReveal(HomageTransitionalSource, ActivityRevealMixin):
    """Cairo ward for Polyend UAC waveform plus MIDI note-grid activity."""

    WARD_ID = "polyend-instrument"
    SOURCE_KIND = "cairo"
    DEFAULT_HYSTERESIS_S = 30.0
    VISIBILITY_CEILING_PCT = 0.15
    SUPPRESS_WHEN_ACTIVE = frozenset()

    def __init__(
        self,
        *,
        usb_root: Path | None = None,
        usb_vendor_id: str = DEFAULT_USB_VENDOR_ID,
        recruitment_path: Path | None = None,
        recruitment_window_s: float = DEFAULT_RECRUITMENT_WINDOW_S,
        rms_threshold_dbfs: float = _RMS_THRESHOLD_DBFS,
        audio_reader: PolyendAudioReader | None = None,
        midi_subscriber: PolyendMidiSubscriber | None = None,
        start_io: bool = True,
        start_poll_thread: bool = False,
    ) -> None:
        HomageTransitionalSource.__init__(self, source_id=self.WARD_ID)
        self._usb_root = usb_root if usb_root is not None else DEFAULT_USB_ROOT
        self._usb_vendor_id = usb_vendor_id
        self._recruitment_path = (
            recruitment_path if recruitment_path is not None else DEFAULT_RECRUITMENT_PATH
        )
        self._recruitment_window_s = recruitment_window_s
        self._rms_threshold_dbfs = rms_threshold_dbfs
        self._audio_reader = audio_reader if audio_reader is not None else PolyendAudioReader()
        self._midi_subscriber = (
            midi_subscriber if midi_subscriber is not None else PolyendMidiSubscriber()
        )
        ActivityRevealMixin.__init__(self, start_poll_thread=start_poll_thread)
        if start_io:
            self._start_io()

    def _start_io(self) -> None:
        for endpoint in (self._audio_reader, self._midi_subscriber):
            try:
                endpoint.start()
            except Exception:
                log.debug("polyend: endpoint start failed", exc_info=True)

    def _disabled(self) -> bool:
        return _truthy_env(_FEATURE_DISABLED_ENV)

    def _usb_present(self) -> bool:
        return _usb_vid_present(root=self._usb_root, vendor_id=self._usb_vendor_id)

    def _audio_rms(self) -> float:
        try:
            return max(0.0, float(self._audio_reader.rms()))
        except Exception:
            return 0.0

    def _audio_rms_dbfs(self) -> float:
        return _dbfs_from_rms(self._audio_rms())

    def _audio_active(self) -> bool:
        return self._audio_rms_dbfs() >= self._rms_threshold_dbfs

    def _affordance_recruited(self, *, now: float | None = None) -> bool:
        age = _read_recruitment_age_s(
            self._recruitment_path,
            _POLYEND_REVEAL_CAPABILITY,
            now=now,
        )
        if age is None:
            return False
        return age <= self._recruitment_window_s

    def _compute_claim_score(self) -> float:
        if self._disabled() or not self._usb_present():
            return 0.0
        score = _BASE_SCORE_PRESENT
        if self._audio_active():
            score += _AUDIO_ACTIVE_BOOST
        if self._affordance_recruited():
            score += _AFFORDANCE_RECRUITED_BOOST
        return max(0.0, min(1.0, score))

    def _want_visible(self) -> bool:
        if self._disabled():
            return False
        return self._usb_present() and self._audio_active() and self._affordance_recruited()

    def _mandatory_invisible(self) -> bool:
        return self._disabled()

    def _claim_source_refs(self) -> tuple[str, ...]:
        return (
            f"usb:vid:{self._usb_vendor_id}",
            f"sounddevice:{DEFAULT_DEVICE_NAME_PATTERN}:48khz:2ch",
            f"rtmidi:{DEFAULT_DEVICE_NAME_PATTERN}:note-on:last32",
            f"affordance:{_POLYEND_REVEAL_CAPABILITY}",
        )

    def _describe_source_registration(self) -> dict[str, Any]:
        return {
            "id": self.WARD_ID,
            "class_name": "PolyendInstrumentReveal",
            "kind": "cairo",
            "natural_w": 640,
            "natural_h": 360,
        }

    def state(self) -> dict[str, Any]:
        state = ActivityRevealMixin.state(self)
        state.update(
            {
                "usb_present": self._usb_present(),
                "audio_rms": self._audio_rms(),
                "audio_rms_dbfs": self._audio_rms_dbfs(),
                "midi_note_events": len(self._midi_subscriber.snapshot()),
            }
        )
        return state

    def _hardm_check(self) -> None:
        return None

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        del state
        self._hardm_check()
        pkg = active_package()
        width = max(1.0, float(canvas_w))
        height = max(1.0, float(canvas_h))
        bg = _colour(pkg, "background", alpha=0.20, fallback=(0.0, 0.0, 0.0, 0.20))
        cr.set_source_rgba(*bg)
        cr.rectangle(0.0, 0.0, width, height)
        cr.fill()
        self._render_waveform(cr, width, height * 0.5, t, pkg)
        self._render_midi_grid(cr, width, height * 0.5, height, pkg)

    def _render_waveform(
        self,
        cr: cairo.Context,
        width: float,
        height: float,
        t: float,
        pkg: Any,
    ) -> None:
        samples = self._audio_reader.snapshot()
        if not samples:
            samples = (0.0,) * 64
        bins = max(32, min(192, int(width // 4) or 32))
        chunk = max(1, len(samples) // bins)
        center = height * 0.5
        scale = height * 0.42
        muted = _colour(pkg, "muted", alpha=0.28, fallback=(0.6, 0.6, 0.6, 0.28))
        accent = _colour(pkg, "accent_cyan", alpha=0.82, fallback=(0.0, 0.85, 1.0, 0.82))

        cr.set_line_width(max(1.0, height * 0.012))
        cr.set_source_rgba(*muted)
        phase = (math.sin(t * 2.0) + 1.0) * 0.5
        cr.move_to(0.0, center + (phase - 0.5) * height * 0.03)
        cr.line_to(width, center - (phase - 0.5) * height * 0.03)
        cr.stroke()

        cr.set_line_width(max(1.5, width / max(240.0, bins * 1.8)))
        cr.set_source_rgba(*accent)
        for index in range(bins):
            start = min(len(samples) - 1, index * chunk)
            end = min(len(samples), start + chunk)
            window = samples[start:end] or (0.0,)
            amplitude = max(abs(sample) for sample in window)
            x = (index + 0.5) * width / bins
            y0 = center - amplitude * scale
            y1 = center + amplitude * scale
            cr.move_to(x, y0)
            cr.line_to(x, y1)
        cr.stroke()

    def _render_midi_grid(
        self,
        cr: cairo.Context,
        width: float,
        y0: float,
        height: float,
        pkg: Any,
    ) -> None:
        grid_h = max(1.0, height - y0)
        cell_w = width / 16.0
        cell_h = grid_h / 8.0
        grid = _colour(pkg, "muted", alpha=0.18, fallback=(0.6, 0.6, 0.6, 0.18))
        lit = _colour(pkg, "accent_magenta", alpha=0.86, fallback=(1.0, 0.0, 0.75, 0.86))
        hot = _colour(pkg, "accent_yellow", alpha=0.76, fallback=(1.0, 0.95, 0.2, 0.76))

        cr.set_source_rgba(*grid)
        cr.set_line_width(1.0)
        for col in range(17):
            x = col * cell_w
            cr.move_to(x, y0)
            cr.line_to(x, height)
        for row in range(9):
            y = y0 + row * cell_h
            cr.move_to(0.0, y)
            cr.line_to(width, y)
        cr.stroke()

        now = time.monotonic()
        for event in self._midi_subscriber.snapshot():
            col = event.note % 16
            row = 7 - (event.note // 16)
            age = max(0.0, now - event.ts)
            age_alpha = max(0.18, 1.0 - age / 6.0)
            velocity_alpha = max(0.25, min(1.0, event.velocity / 127.0))
            alpha = 0.18 + 0.70 * min(age_alpha, velocity_alpha)
            base = hot if event.velocity >= 96 else lit
            cr.set_source_rgba(base[0], base[1], base[2], alpha)
            pad_x = max(1.0, cell_w * 0.18)
            pad_y = max(1.0, cell_h * 0.18)
            cr.rectangle(
                col * cell_w + pad_x,
                y0 + row * cell_h + pad_y,
                max(1.0, cell_w - 2.0 * pad_x),
                max(1.0, cell_h - 2.0 * pad_y),
            )
            cr.fill()

    def stop(self) -> None:
        try:
            self._audio_reader.stop()
        finally:
            try:
                self._midi_subscriber.stop()
            finally:
                ActivityRevealMixin.stop(self)

    def cleanup(self) -> None:
        self.stop()


__all__ = [
    "DEFAULT_CHANNELS",
    "DEFAULT_DEVICE_NAME_PATTERN",
    "DEFAULT_RING_BUFFER_S",
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_USB_VENDOR_ID",
    "AudioRingBuffer",
    "MidiNoteEvent",
    "PolyendAudioReader",
    "PolyendInstrumentReveal",
    "PolyendMidiSubscriber",
]
