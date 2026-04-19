"""Task #122 — DEGRADED-STREAM mode tests.

Coverage:

- :class:`DegradedModeController` round-trip: activate → is_active True →
  deactivate → False.
- TTL expires: is_active returns False after time passes (mocked clock).
- File publication + atomic unpublish.
- FX chain pins all slots to passthrough when active.
- :class:`CairoSourceRunner` returns cached frame when degraded + cached
  exists (render() not called); paints Gruvbox-dark when no cache.
- Director skips LLM call when degraded (emits silence-hold intent
  artifacts, increments dedicated counter).
- Command server routes ``degraded.activate`` / ``degraded.deactivate``
  and rejects malformed args.
"""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agents.studio_compositor.degraded_mode import (
    DEFAULT_TTL_S,
    DegradedMode,
    DegradedModeController,
)

# ---------------------------------------------------------------- helpers


class _FakeClock:
    """Mutable clock for TTL tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, delta: float) -> None:
        self.now += float(delta)


def _isolated_controller(clock: _FakeClock | None = None) -> DegradedModeController:
    """Return a controller that publishes under a unique tmp path.

    Avoids collisions with other tests running in parallel and with any
    out-of-process consumers on the host.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="test-degraded-"))
    return DegradedModeController(path=tmp_dir / "degraded-mode.json", clock=clock)


# ---------------------------------------------------------------- controller


class TestDegradedModeController:
    def test_normal_on_construction(self) -> None:
        c = _isolated_controller()
        assert c.is_active() is False
        assert c.current_reason() is None

    def test_activate_then_deactivate_round_trip(self) -> None:
        c = _isolated_controller()
        c.activate("rebuild")
        assert c.is_active() is True
        assert c.current_reason() == "rebuild"
        c.deactivate()
        assert c.is_active() is False
        assert c.current_reason() is None

    def test_activate_publishes_atomic_file(self) -> None:
        c = _isolated_controller()
        c.activate("rebuild", ttl_s=30.0)
        payload = json.loads(c._path.read_text())
        assert payload["state"] == DegradedMode.DEGRADED.value
        assert payload["reason"] == "rebuild"
        assert payload["ttl_s"] == 30.0

    def test_deactivate_removes_file(self) -> None:
        c = _isolated_controller()
        c.activate("rebuild")
        assert c._path.exists()
        c.deactivate()
        assert not c._path.exists()

    def test_ttl_expires_clears_state(self) -> None:
        clock = _FakeClock(start=1000.0)
        c = _isolated_controller(clock=clock)
        c.activate("rebuild", ttl_s=5.0)
        assert c.is_active() is True
        # Advance past TTL.
        clock.advance(6.0)
        assert c.is_active() is False
        # File should be unpublished after the lazy sweep.
        assert not c._path.exists()

    def test_ttl_not_yet_expired(self) -> None:
        clock = _FakeClock(start=1000.0)
        c = _isolated_controller(clock=clock)
        c.activate("rebuild", ttl_s=60.0)
        clock.advance(30.0)
        assert c.is_active() is True

    def test_activate_idempotent_refreshes_state(self) -> None:
        clock = _FakeClock(start=1000.0)
        c = _isolated_controller(clock=clock)
        c.activate("rebuild", ttl_s=5.0)
        clock.advance(4.0)
        # Re-activate extends the hold.
        c.activate("rebuild-again", ttl_s=5.0)
        clock.advance(4.0)
        assert c.is_active() is True
        assert c.current_reason() == "rebuild-again"

    def test_ttl_below_minimum_rejected(self) -> None:
        c = _isolated_controller()
        with pytest.raises(ValueError):
            c.activate("rebuild", ttl_s=0.0)

    def test_default_ttl_used(self) -> None:
        c = _isolated_controller()
        c.activate("rebuild")
        payload = json.loads(c._path.read_text())
        assert payload["ttl_s"] == DEFAULT_TTL_S


# ---------------------------------------------------------------- fx chain


class TestFxChainDegradedPin:
    def _build_compositor(self, num_slots: int = 4) -> Any:
        """Minimal stub compositor with the attributes fx_tick needs."""

        slots: list[Any] = []
        for i in range(num_slots):
            slot = MagicMock()
            slot.name = f"slot-{i}"
            slots.append(slot)

        slot_pipeline = MagicMock()
        slot_pipeline._slots = slots
        slot_pipeline._slot_assignments = [f"shader-{i}" for i in range(num_slots)]
        slot_pipeline._slot_last_frag = [f"frag-{i}" for i in range(num_slots)]

        compositor = MagicMock()
        compositor._slot_pipeline = slot_pipeline
        return compositor

    def test_pin_slots_to_passthrough_when_degraded(self) -> None:
        from agents.effect_graph.pipeline import PASSTHROUGH_SHADER
        from agents.studio_compositor.fx_tick import tick_slot_pipeline

        compositor = self._build_compositor()
        clock = _FakeClock()
        controller = _isolated_controller(clock=clock)

        with patch(
            "agents.studio_compositor.degraded_mode.get_controller",
            return_value=controller,
        ):
            controller.activate("rebuild")
            tick_slot_pipeline(compositor, t=0.0)

        # Every slot fragment was reset to passthrough.
        slot_pipeline = compositor._slot_pipeline
        for slot in slot_pipeline._slots:
            slot.set_property.assert_called_with("fragment", PASSTHROUGH_SHADER)
        # Assignments cleared so the next NORMAL tick starts from a
        # clean slate rather than re-applying old preset params.
        assert all(a is None for a in slot_pipeline._slot_assignments)

    def test_pin_noop_when_already_passthrough(self) -> None:
        from agents.effect_graph.pipeline import PASSTHROUGH_SHADER
        from agents.studio_compositor.fx_tick import tick_slot_pipeline

        compositor = self._build_compositor()
        compositor._slot_pipeline._slot_last_frag = [PASSTHROUGH_SHADER] * len(
            compositor._slot_pipeline._slots
        )

        controller = _isolated_controller()
        with patch(
            "agents.studio_compositor.degraded_mode.get_controller",
            return_value=controller,
        ):
            controller.activate("rebuild")
            tick_slot_pipeline(compositor, t=0.0)

        # No slot was re-pinned since all were already passthrough.
        for slot in compositor._slot_pipeline._slots:
            slot.set_property.assert_not_called()


# ---------------------------------------------------------------- cairo source


class _StubCairoSource:
    """Records whether render() was called and draws a marker color."""

    def __init__(self) -> None:
        self.render_calls = 0

    def render(
        self,
        cr: Any,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        self.render_calls += 1
        cr.set_source_rgba(1.0, 0.0, 0.0, 1.0)  # red marker
        cr.paint()

    def state(self) -> dict[str, Any]:
        return {}

    def cleanup(self) -> None:
        pass


class TestCairoSourceDegraded:
    def test_cached_surface_preserved_when_degraded(self) -> None:
        from agents.studio_compositor.cairo_source import CairoSourceRunner

        source = _StubCairoSource()
        runner = CairoSourceRunner(
            source_id="stub",
            source=source,
            canvas_w=32,
            canvas_h=32,
            natural_w=32,
            natural_h=32,
            target_fps=10.0,
        )
        # Prime with one successful render under NORMAL mode.
        runner.tick_once()
        initial_calls = source.render_calls
        initial_surface = runner.get_output_surface()
        assert initial_surface is not None
        assert initial_calls == 1

        controller = _isolated_controller()
        with (
            patch(
                "agents.studio_compositor.cairo_source.get_controller",
                return_value=controller,
                create=True,
            ),
            patch(
                "agents.studio_compositor.degraded_mode.get_controller",
                return_value=controller,
            ),
        ):
            controller.activate("rebuild")
            runner.tick_once()

        # render() not called again — cached surface preserved.
        assert source.render_calls == initial_calls
        # The output pointer is still the prior surface.
        assert runner.get_output_surface() is initial_surface

    def test_gruvbox_fallback_when_no_cache_and_degraded(self) -> None:
        from agents.studio_compositor.cairo_source import (
            _GRUVBOX_BG0_RGB,
            CairoSourceRunner,
        )

        source = _StubCairoSource()
        runner = CairoSourceRunner(
            source_id="stub2",
            source=source,
            canvas_w=8,
            canvas_h=8,
            natural_w=8,
            natural_h=8,
            target_fps=10.0,
        )
        assert runner.get_output_surface() is None

        controller = _isolated_controller()
        with patch(
            "agents.studio_compositor.degraded_mode.get_controller",
            return_value=controller,
        ):
            controller.activate("rebuild")
            runner.tick_once()

        # render() was never called.
        assert source.render_calls == 0
        surface = runner.get_output_surface()
        assert surface is not None
        # Sample a pixel and check it matches Gruvbox bg0 (ARGB32
        # is premultiplied BGRA little-endian on our target).
        data = bytes(surface.get_data())
        # 8×8 ARGB32 → 256 bytes, per-pixel B,G,R,A.
        b, g, r, a = data[0], data[1], data[2], data[3]
        assert a == 255
        # Allow rounding in ARGB32 conversion.
        expected_r = int(round(_GRUVBOX_BG0_RGB[0] * 255))
        expected_g = int(round(_GRUVBOX_BG0_RGB[1] * 255))
        expected_b = int(round(_GRUVBOX_BG0_RGB[2] * 255))
        assert abs(r - expected_r) <= 1
        assert abs(g - expected_g) <= 1
        assert abs(b - expected_b) <= 1


# ---------------------------------------------------------------- director


class TestDirectorDegraded:
    def test_emit_degraded_silence_hold_produces_artifacts_and_skips_llm(self) -> None:
        # Use a fresh controller wired into the director's lazy lookup.
        controller = _isolated_controller()

        # Mock the director without running its __init__ — we only
        # need the method under test.
        from agents.studio_compositor.director_loop import DirectorLoop

        director = DirectorLoop.__new__(DirectorLoop)

        emitted: list[Any] = []

        def _fake_emit(intent: Any, *, condition_id: str) -> None:
            emitted.append((intent, condition_id))

        with (
            patch("agents.studio_compositor.director_loop._emit_intent_artifacts", _fake_emit),
            patch(
                "agents.studio_compositor.degraded_mode.get_controller",
                return_value=controller,
            ),
        ):
            controller.activate("rebuild")
            director._emit_degraded_silence_hold()

        assert len(emitted) == 1, "director must emit exactly one silence-hold artifact"
        intent, _cid = emitted[0]
        assert intent.activity == "silence"
        assert len(intent.compositional_impingements) == 1

    def test_degraded_counter_increments_on_hold(self) -> None:
        """The dedicated per-surface counter must tick on each hold."""
        controller = _isolated_controller()
        mock_counter = MagicMock()
        mock_counter.labels.return_value = mock_counter
        controller._holds_counter = mock_counter

        controller.activate("rebuild")
        controller.record_hold("director")
        controller.record_hold("director")
        controller.record_hold("fx_chain")

        assert mock_counter.inc.call_count == 3
        # record_hold passes the surface label positionally via
        # ``.labels(surface=...)`` — inspect both positional and kw args.
        surfaces: list[str] = []
        for call in mock_counter.labels.call_args_list:
            if call.args:
                surfaces.append(call.args[0])
            elif "surface" in call.kwargs:
                surfaces.append(call.kwargs["surface"])
        assert surfaces.count("director") == 2
        assert surfaces.count("fx_chain") == 1


# ---------------------------------------------------------------- command server


class TestCommandServerDegraded:
    def test_activate_command_dispatch(self) -> None:
        from agents.studio_compositor.command_server import _COMMANDS

        handler = _COMMANDS["degraded.activate"]
        controller = _isolated_controller()
        with patch(
            "agents.studio_compositor.degraded_mode.get_controller",
            return_value=controller,
        ):
            result = handler(None, {"reason": "rebuild", "ttl_s": 15.0})

        assert result["state"] == "degraded"
        assert controller.is_active() is True
        assert controller.current_reason() == "rebuild"

    def test_activate_rejects_missing_reason(self) -> None:
        from agents.studio_compositor.command_server import _COMMANDS, _CommandError

        handler = _COMMANDS["degraded.activate"]
        with pytest.raises(_CommandError):
            handler(None, {})

    def test_activate_rejects_non_numeric_ttl(self) -> None:
        from agents.studio_compositor.command_server import _COMMANDS, _CommandError

        handler = _COMMANDS["degraded.activate"]
        with pytest.raises(_CommandError):
            handler(None, {"reason": "rebuild", "ttl_s": "not-a-number"})

    def test_deactivate_command_dispatch(self) -> None:
        from agents.studio_compositor.command_server import _COMMANDS

        activate = _COMMANDS["degraded.activate"]
        deactivate = _COMMANDS["degraded.deactivate"]
        controller = _isolated_controller()
        with patch(
            "agents.studio_compositor.degraded_mode.get_controller",
            return_value=controller,
        ):
            activate(None, {"reason": "rebuild"})
            assert controller.is_active() is True
            result = deactivate(None, {})

        assert result["state"] == "normal"
        assert controller.is_active() is False


# ---------------------------------------------------------------- concurrency


class TestConcurrency:
    def test_activate_is_threadsafe_under_contention(self) -> None:
        """Twenty threads calling activate()/deactivate() must not crash."""
        controller = _isolated_controller()

        errors: list[BaseException] = []

        def _hammer() -> None:
            try:
                for _ in range(50):
                    controller.activate("contention")
                    controller.is_active()
                    controller.deactivate()
            except BaseException as exc:  # noqa: BLE001 - collect for assertion
                errors.append(exc)

        threads = [threading.Thread(target=_hammer) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert not errors, f"thread errors: {errors!r}"
