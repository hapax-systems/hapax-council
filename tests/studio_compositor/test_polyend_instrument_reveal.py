"""Tests for the Polyend activity-reveal ward."""

from __future__ import annotations

import importlib.util
import json
import math
import time
import tomllib
from pathlib import Path
from typing import Any

import cairo
import pytest

from agents.studio_compositor.activity_reveal_ward import ActivityRevealMixin
from agents.studio_compositor.activity_router import ActivityRouter
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from agents.studio_compositor.polyend_instrument_reveal import (
    DEFAULT_DEVICE_NAME_PATTERN,
    DEFAULT_SAMPLE_RATE,
    AudioRingBuffer,
    PolyendAudioReader,
    PolyendInstrumentReveal,
    PolyendMidiSubscriber,
)
from shared.affordance_registry import ALL_AFFORDANCES
from shared.audio_topology import TopologyDescriptor

REPO_ROOT = Path(__file__).resolve().parents[2]


class _FakeAudioReader:
    def __init__(self, *, rms: float = 0.0, samples: tuple[float, ...] = ()) -> None:
        self._rms = rms
        self._samples = samples
        self.started = False
        self.stopped = False

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self) -> None:
        self.stopped = True

    def rms(self) -> float:
        return self._rms

    def snapshot(self) -> tuple[float, ...]:
        return self._samples


def _write_usb_vid(root: Path, vendor_id: str = "1fc9") -> None:
    device_dir = root / "1-1"
    device_dir.mkdir(parents=True)
    (device_dir / "idVendor").write_text(f"{vendor_id}\n", encoding="utf-8")


def _write_recruitment(path: Path, capability: str, *, age_s: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "families": {
            capability: {
                "last_recruited_ts": time.time() - age_s,
                "ttl_s": 60.0,
            },
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _nonzero_bytes(surface: cairo.ImageSurface, *, y0: int, y1: int) -> int:
    data = bytes(surface.get_data())
    stride = surface.get_stride()
    return sum(1 for byte in data[stride * y0 : stride * y1] if byte != 0)


class TestFamilyContract:
    def test_subclasses_activity_reveal_and_homage_source(self) -> None:
        assert issubclass(PolyendInstrumentReveal, ActivityRevealMixin)
        assert issubclass(PolyendInstrumentReveal, HomageTransitionalSource)

    def test_source_kind_is_cairo(self) -> None:
        assert PolyendInstrumentReveal.WARD_ID == "polyend-instrument"
        assert PolyendInstrumentReveal.SOURCE_KIND == "cairo"

    def test_registered_in_cairo_sources(self) -> None:
        pytest.importorskip("googleapiclient.discovery")
        from agents.studio_compositor.cairo_sources import get_cairo_source_class

        assert get_cairo_source_class("PolyendInstrumentReveal") is PolyendInstrumentReveal

    def test_instance_accepted_by_activity_router(self) -> None:
        ward = PolyendInstrumentReveal(
            audio_reader=_FakeAudioReader(),
            midi_subscriber=PolyendMidiSubscriber(),
            start_io=False,
        )
        try:
            router = ActivityRouter([ward])
            assert ward in router.wards
            assert "polyend-instrument" in router.describe()["ward_ids"]
        finally:
            ward.stop()


class TestAudioAndMidiIngest:
    def test_audio_ring_buffer_keeps_200ms_window(self) -> None:
        ring = AudioRingBuffer(sample_rate=10, channels=2, duration_s=0.2)
        ring.append([[0.5, 0.5], [0.25, 0.25], [0.0, 0.0]])
        assert ring.snapshot() == pytest.approx((0.25, 0.0))
        assert ring.rms() == pytest.approx(math.sqrt((0.25 * 0.25) / 2.0))

    def test_sounddevice_reader_selects_polyend_input(self) -> None:
        class FakeStream:
            def __init__(self, callback: Any) -> None:
                self.callback = callback
                self.started = False
                self.stopped = False
                self.closed = False

            def start(self) -> None:
                self.started = True

            def stop(self) -> None:
                self.stopped = True

            def close(self) -> None:
                self.closed = True

        class FakeSoundDevice:
            def __init__(self) -> None:
                self.stream: FakeStream | None = None

            def query_devices(self) -> list[dict[str, Any]]:
                return [
                    {"name": "Webcam Mic", "max_input_channels": 1},
                    {"name": "Polyend Tracker Mini", "max_input_channels": 2},
                ]

            def InputStream(self, **kwargs: Any) -> FakeStream:  # noqa: N802
                assert kwargs["samplerate"] == DEFAULT_SAMPLE_RATE
                assert kwargs["device"] == 1
                assert kwargs["channels"] == 2
                self.stream = FakeStream(kwargs["callback"])
                return self.stream

        sd_module = FakeSoundDevice()
        reader = PolyendAudioReader(sd_module=sd_module)
        assert reader.start() is True
        assert sd_module.stream is not None
        assert sd_module.stream.started is True
        sd_module.stream.callback([[0.5, 0.5], [0.25, -0.25]], 2, None, None)
        assert reader.rms() > 0.3
        reader.stop()
        assert sd_module.stream.stopped is True
        assert sd_module.stream.closed is True

    def test_midi_subscriber_keeps_note_on_events_only(self) -> None:
        midi = PolyendMidiSubscriber()
        assert midi.record_message([0x90, 60, 100], ts=1.0) is True
        assert midi.record_message([0x90, 61, 0], ts=2.0) is False
        assert midi.record_message([0x80, 60, 100], ts=3.0) is False
        events = midi.snapshot()
        assert len(events) == 1
        assert events[0].note == 60
        assert events[0].velocity == 100

    def test_rtmidi_subscriber_opens_polyend_port_and_callback(self) -> None:
        class FakeMidiIn:
            def __init__(self) -> None:
                self.opened: int | None = None
                self.callback: Any | None = None
                self.ignored: tuple[bool, bool, bool] | None = None
                self.closed = False

            def get_ports(self) -> list[str]:
                return ["Other MIDI", "Polyend Tracker Mini MIDI"]

            def open_port(self, index: int) -> None:
                self.opened = index

            def ignore_types(
                self,
                *,
                sysex: bool = True,
                timing: bool = True,
                active_sense: bool = True,
            ) -> None:
                self.ignored = (sysex, timing, active_sense)

            def set_callback(self, callback: Any) -> None:
                self.callback = callback

            def cancel_callback(self) -> None:
                self.callback = None

            def close_port(self) -> None:
                self.closed = True

        class FakeRtMidi:
            def __init__(self) -> None:
                self.midi_in = FakeMidiIn()

            def MidiIn(self) -> FakeMidiIn:  # noqa: N802
                return self.midi_in

        rtmidi_module = FakeRtMidi()
        midi = PolyendMidiSubscriber(rtmidi_module=rtmidi_module)
        assert midi.start() is True
        assert rtmidi_module.midi_in.opened == 1
        assert rtmidi_module.midi_in.ignored == (True, True, True)
        assert rtmidi_module.midi_in.callback is not None
        rtmidi_module.midi_in.callback(([0x90, 64, 127], 0.0), None)
        assert midi.snapshot()[0].note == 64
        midi.stop()
        assert rtmidi_module.midi_in.closed is True


class TestGateLogic:
    def test_fail_closed_when_usb_absent(self, tmp_path: Path) -> None:
        ward = PolyendInstrumentReveal(
            usb_root=tmp_path / "usb",
            recruitment_path=tmp_path / "recruitment.json",
            audio_reader=_FakeAudioReader(rms=0.25),
            midi_subscriber=PolyendMidiSubscriber(),
            start_io=False,
        )
        try:
            claim = ward.poll_once()
            assert claim.want_visible is False
            assert claim.score == pytest.approx(0.0)
        finally:
            ward.stop()

    def test_usb_audio_and_recruitment_gate_visible(self, tmp_path: Path) -> None:
        usb_root = tmp_path / "usb"
        _write_usb_vid(usb_root)
        recruitment_path = tmp_path / "recent-recruitment.json"
        _write_recruitment(recruitment_path, "ward.reveal.polyend-instrument")
        ward = PolyendInstrumentReveal(
            usb_root=usb_root,
            recruitment_path=recruitment_path,
            audio_reader=_FakeAudioReader(rms=0.02),
            midi_subscriber=PolyendMidiSubscriber(),
            start_io=False,
        )
        try:
            claim = ward.poll_once()
            assert claim.want_visible is True
            assert claim.score == pytest.approx(1.0)
            assert "affordance:ward.reveal.polyend-instrument" in claim.source_refs
        finally:
            ward.stop()

    def test_recruitment_missing_suppresses_visible_but_keeps_base_score(
        self,
        tmp_path: Path,
    ) -> None:
        usb_root = tmp_path / "usb"
        _write_usb_vid(usb_root)
        ward = PolyendInstrumentReveal(
            usb_root=usb_root,
            recruitment_path=tmp_path / "missing.json",
            audio_reader=_FakeAudioReader(rms=0.02),
            midi_subscriber=PolyendMidiSubscriber(),
            start_io=False,
        )
        try:
            claim = ward.poll_once()
            assert claim.want_visible is False
            assert claim.score == pytest.approx(0.60)
        finally:
            ward.stop()

    def test_opt_out_env_forces_mandatory_invisible(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        usb_root = tmp_path / "usb"
        _write_usb_vid(usb_root)
        recruitment_path = tmp_path / "recent-recruitment.json"
        _write_recruitment(recruitment_path, "ward.reveal.polyend-instrument")
        monkeypatch.setenv("HAPAX_ACTIVITY_REVEAL_POLYEND_DISABLED", "1")
        ward = PolyendInstrumentReveal(
            usb_root=usb_root,
            recruitment_path=recruitment_path,
            audio_reader=_FakeAudioReader(rms=0.02),
            midi_subscriber=PolyendMidiSubscriber(),
            start_io=False,
        )
        try:
            claim = ward.poll_once()
            assert claim.want_visible is False
            assert claim.mandatory_invisible is True
            assert claim.score == pytest.approx(0.0)
        finally:
            ward.stop()


class TestRendering:
    def test_waveform_and_midi_grid_render_pixels(self) -> None:
        samples = tuple(math.sin(i / 5.0) * 0.5 for i in range(240))
        midi = PolyendMidiSubscriber()
        midi.record_message([0x90, 0, 96], ts=time.monotonic())
        midi.record_message([0x90, 127, 120], ts=time.monotonic())
        ward = PolyendInstrumentReveal(
            audio_reader=_FakeAudioReader(rms=0.25, samples=samples),
            midi_subscriber=midi,
            start_io=False,
        )
        try:
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 320, 180)
            cr = cairo.Context(surface)
            ward.render_content(cr, 320, 180, 1.0, {})
            assert _nonzero_bytes(surface, y0=0, y1=90) > 0
            assert _nonzero_bytes(surface, y0=90, y1=180) > 0
        finally:
            ward.stop()

    def test_hardm_clean_render_path_has_no_text_calls(self) -> None:
        source = (REPO_ROOT / "agents/studio_compositor/polyend_instrument_reveal.py").read_text(
            encoding="utf-8"
        )
        assert "show_text(" not in source
        assert "render_text(" not in source
        assert "paint_bitchx_header" not in source


class TestRegistrationAndConfig:
    def test_affordance_registry_contains_polyend_visual_reveal(self) -> None:
        records = {record.name: record for record in ALL_AFFORDANCES}
        record = records["ward.reveal.polyend-instrument"]
        assert record.daemon == "compositor"
        assert record.operational.medium == "visual"
        assert record.operational.consent_required is False

    def test_pyproject_audio_extra_has_required_deps(self) -> None:
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        audio_deps = data["project"]["optional-dependencies"]["audio"]
        joined = "\n".join(audio_deps)
        assert "sounddevice" in joined
        assert "python-rtmidi" in joined

    def test_pipewire_and_wireplumber_polyend_config(self) -> None:
        pipewire = (REPO_ROOT / "config/pipewire/hapax-polyend-loudnorm.conf").read_text(
            encoding="utf-8"
        )
        wireplumber = (REPO_ROOT / "config/wireplumber/55-hapax-polyend-instrument.conf").read_text(
            encoding="utf-8"
        )
        udev = (
            REPO_ROOT / "config/udev/rules.d/50-hapax-usb-audio-video-noautosuspend.rules"
        ).read_text(encoding="utf-8")
        assert 'target.object = "hapax-livestream-tap"' in pipewire
        assert "ZOOM_Corporation_L-12" not in pipewire
        assert 'device.vendor.id = "0x1fc9"' in wireplumber
        assert "node.dont-reconnect = true" in wireplumber
        assert 'ATTR{idVendor}=="1fc9"' in udev

    def test_canonical_audio_topology_declares_polyend_direct_tap(self) -> None:
        descriptor = TopologyDescriptor.from_yaml(REPO_ROOT / "config/audio-topology.yaml")
        loudnorm = descriptor.node_by_id("polyend-loudnorm")
        assert loudnorm.pipewire_name == "hapax-polyend-loudnorm"
        assert loudnorm.target_object == "hapax-livestream-tap"
        assert loudnorm.params["playback_target"] == "hapax-livestream-tap"

    def test_audio_conf_consistency_gate_accepts_polyend_conf(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "check_audio_conf_consistency",
            REPO_ROOT / "scripts/check-audio-conf-consistency.py",
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        code, message = module.check()
        assert code == 0, message

    def test_default_device_pattern_is_polyend(self) -> None:
        assert DEFAULT_DEVICE_NAME_PATTERN == "Polyend"
