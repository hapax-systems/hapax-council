"""Keep compositor tests away from live Polyend audio and MIDI devices."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from agents.studio_compositor import polyend_instrument_reveal


class _DisconnectedMidiIn:
    def get_ports(self) -> list[str]:
        return []


@pytest.fixture(autouse=True)
def _isolate_polyend_io(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Supply disconnected devices and fail if a test reaches the real MIDI path."""
    fallback_calls: list[object] = []

    def forbidden_midi_in(*args: object, **kwargs: object) -> Any:
        fallback_calls.append((args, kwargs))
        raise AssertionError("studio compositor test reached real rtmidi.MidiIn")

    loaded_rtmidi = sys.modules.get("rtmidi")
    if loaded_rtmidi is not None:
        monkeypatch.setattr(loaded_rtmidi, "MidiIn", forbidden_midi_in, raising=False)
    trapped_rtmidi = ModuleType("rtmidi")
    trapped_rtmidi.MidiIn = forbidden_midi_in  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rtmidi", trapped_rtmidi)

    fake_rtmidi = SimpleNamespace(MidiIn=_DisconnectedMidiIn)
    fake_sounddevice = SimpleNamespace(query_devices=lambda: [])
    monkeypatch.setattr(polyend_instrument_reveal, "_import_rtmidi", lambda: fake_rtmidi)
    monkeypatch.setattr(polyend_instrument_reveal, "_import_sounddevice", lambda: fake_sounddevice)

    yield
    assert not fallback_calls, "studio compositor test reached real rtmidi.MidiIn"
