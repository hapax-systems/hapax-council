"""Tests for ``agents.studio_compositor.reactivity_adapters``.

The adapters wrap existing capture surfaces (compositor mixer capture,
Cortado contact-mic state, generic PipeWire line-ins) into the
``AudioReactivitySource`` Protocol so a unified reactivity bus can poll
them. The contract: a missing or failing source MUST degrade to
``AudioSignals.zero()`` rather than raise — the bus must continue to
hold a valid blend even in headless tests, mic-unplugged sessions, or
when a backend reader transiently fails.

These tests pin that fail-quiet contract for the two adapters that have
zero-signal degradation paths (``ContactMicSource``, ``PipeWireLineInSource``)
plus the composition-root helper ``register_default_sources`` which
must register a contact-mic adapter regardless of whether a reader is
available.
"""

from __future__ import annotations

from agents.studio_compositor.reactivity_adapters import (
    ContactMicSource,
    PipeWireLineInSource,
    register_default_sources,
)
from shared.audio_reactivity import (
    ACTIVITY_FLOOR_RMS,
    AudioSignals,
    UnifiedReactivityBus,
)

# ── ContactMicSource ────────────────────────────────────────────────────


class TestContactMicSource:
    def test_no_reader_returns_zero(self):
        src = ContactMicSource(reader=None)
        assert src.get_signals() == AudioSignals.zero()
        assert src.is_active() is False

    def test_reader_raises_returns_zero(self):
        def failing():
            raise RuntimeError("simulated /dev/shm read failure")

        src = ContactMicSource(reader=failing)
        signals = src.get_signals()
        assert signals == AudioSignals.zero()
        assert src.is_active() is False

    def test_reader_returns_falsy_state_returns_zero(self):
        # Empty dict / None / falsy state means "no fresh data" — adapter
        # must degrade rather than mis-mapping zero-fields as signal.
        for falsy in (None, {}, 0, False):
            src = ContactMicSource(reader=lambda v=falsy: v)
            assert src.get_signals() == AudioSignals.zero(), falsy

    def test_reader_with_state_maps_to_signals(self):
        state = {
            "desk_energy": 0.42,
            "desk_onset_rate": 0.30,
            "desk_centroid": 0.55,
        }
        src = ContactMicSource(reader=lambda: state)
        signals = src.get_signals()
        assert signals.rms == 0.42
        assert signals.onset == 0.30
        assert signals.centroid == 0.55
        # Contact mic is broadband-hit; mid_band carries the energy,
        # bass/treble are zero.
        assert signals.mid_band == 0.42
        assert signals.bass_band == 0.0
        assert signals.treble_band == 0.0

    def test_onset_clamped_to_unit(self):
        # Some upstream paths may emit onset rates > 1.0; the adapter
        # clamps so blending math stays in the documented [0, 1] range.
        state = {"desk_energy": 0.1, "desk_onset_rate": 5.0, "desk_centroid": 0.0}
        src = ContactMicSource(reader=lambda: state)
        assert src.get_signals().onset == 1.0

    def test_is_active_uses_floor(self):
        active = {
            "desk_energy": ACTIVITY_FLOOR_RMS * 10,
            "desk_onset_rate": 0.0,
            "desk_centroid": 0.0,
        }
        dormant = {"desk_energy": 0.0, "desk_onset_rate": 0.0, "desk_centroid": 0.0}
        assert ContactMicSource(reader=lambda: active).is_active() is True
        assert ContactMicSource(reader=lambda: dormant).is_active() is False


# ── PipeWireLineInSource ────────────────────────────────────────────────


class TestPipeWireLineInSource:
    def test_no_provider_returns_zero(self):
        src = PipeWireLineInSource(name="line-in-3")
        assert src.get_signals() == AudioSignals.zero()
        assert src.name == "line-in-3"
        assert src.is_active() is False

    def test_provider_raises_returns_zero(self):
        def failing():
            raise RuntimeError("dsp pipeline crashed")

        src = PipeWireLineInSource(name="x", signal_provider=failing)
        assert src.get_signals() == AudioSignals.zero()

    def test_provider_returning_audio_signals_passes_through(self):
        emit = AudioSignals.zero()
        src = PipeWireLineInSource(name="x", signal_provider=lambda: emit)
        assert src.get_signals() == emit

    def test_provider_returning_dict_is_converted(self):
        full = AudioSignals.zero().__dict__ | {"rms": 0.5, "onset": 0.1}
        src = PipeWireLineInSource(name="x", signal_provider=lambda: full)
        signals = src.get_signals()
        assert signals.rms == 0.5
        assert signals.onset == 0.1

    def test_provider_returning_unknown_type_returns_zero(self):
        # An adapter that returns "garbage" (string, list, int) must
        # degrade — the bus contract is AudioSignals or zero, never a
        # raised TypeError that breaks the polling loop.
        for bad in ("not signals", [1, 2, 3], 42):
            src = PipeWireLineInSource(name="x", signal_provider=lambda v=bad: v)
            assert src.get_signals() == AudioSignals.zero(), bad


# ── register_default_sources ────────────────────────────────────────────


class TestRegisterDefaultSources:
    def test_registers_contact_mic_even_without_reader(self):
        bus = UnifiedReactivityBus()
        result = register_default_sources(capture=None, contact_mic_reader=None, bus=bus)
        assert result is bus
        # The contact-mic adapter is registered with reader=None and
        # returns zero — but the bus contract is satisfied (bus has at
        # least one source named "desk" so the blended view exists).
        names = bus.sources()
        assert "desk" in names

    def test_skips_mixer_when_capture_missing(self):
        bus = UnifiedReactivityBus()
        register_default_sources(capture=None, bus=bus)
        names = bus.sources()
        assert "mixer" not in names

    def test_returns_provided_bus_instance(self):
        bus = UnifiedReactivityBus()
        result = register_default_sources(capture=None, bus=bus)
        # Returns the SAME bus object so callers can chain.
        assert result is bus
