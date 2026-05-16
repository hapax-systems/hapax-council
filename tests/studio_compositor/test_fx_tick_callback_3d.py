from __future__ import annotations

from agents.studio_compositor.fx_chain import fx_tick_callback


class _Modulator:
    def __init__(self) -> None:
        self.ticks = 0

    def maybe_tick(self) -> None:
        self.ticks += 1


class _Compositor:
    def __init__(self) -> None:
        self._running = True
        self._ward_stimmung_modulator = _Modulator()
        self._slot_pipeline = None


def test_3d_fx_tick_keeps_ward_modulator_alive_without_slot_pipeline(
    monkeypatch,
) -> None:
    monkeypatch.setenv("HAPAX_3D_COMPOSITOR", "1")
    compositor = _Compositor()

    assert fx_tick_callback(compositor) is True

    assert compositor._ward_stimmung_modulator.ticks == 1


def test_non_3d_fx_tick_stays_alive_when_modulator_present_without_slot_pipeline(
    monkeypatch,
) -> None:
    monkeypatch.delenv("HAPAX_3D_COMPOSITOR", raising=False)
    compositor = _Compositor()

    assert fx_tick_callback(compositor) is True

    assert compositor._ward_stimmung_modulator.ticks == 1


def test_fx_tick_stops_without_slot_pipeline_when_no_live_modulator(
    monkeypatch,
) -> None:
    monkeypatch.delenv("HAPAX_3D_COMPOSITOR", raising=False)
    compositor = _Compositor()
    compositor._ward_stimmung_modulator = None

    assert fx_tick_callback(compositor) is False
