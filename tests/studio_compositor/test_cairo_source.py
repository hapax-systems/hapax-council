from __future__ import annotations

from typing import Any

import cairo  # noqa: TC002 — runtime use: Cairo Context in render methods

from agents.studio_compositor.cairo_source import CairoSource, CairoSourceRunner


class _FlatSource(CairoSource):
    def __init__(self) -> None:
        self.red = 1.0

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        cr.set_source_rgba(self.red, 0.0, 0.0, 1.0)
        cr.paint()


def test_source_protocol_skips_unchanged_cairo_surface_until_heartbeat(
    monkeypatch,
) -> None:
    from agents.reverie import content_injector
    from agents.studio_compositor import cairo_source

    calls: list[dict[str, Any]] = []

    def _record_inject(*args: Any, **kwargs: Any) -> bool:
        calls.append({"args": args, "kwargs": kwargs})
        return True

    now = 100.0
    monkeypatch.setattr(content_injector, "inject_rgba", _record_inject)
    monkeypatch.setattr(cairo_source.time, "monotonic", lambda: now)

    source = _FlatSource()
    runner = CairoSourceRunner(
        source_id="flat",
        source=source,
        canvas_w=2,
        canvas_h=2,
        target_fps=10.0,
        publish_to_source_protocol=True,
        natural_w=2,
        natural_h=2,
        publish_ttl_ms=3000,
    )

    runner.tick_once()
    assert len(calls) == 1

    now = 100.2
    runner.tick_once()
    assert len(calls) == 1

    now = 101.6
    runner.tick_once()
    assert len(calls) == 2


def test_source_protocol_publishes_changed_cairo_surface_before_heartbeat(
    monkeypatch,
) -> None:
    from agents.reverie import content_injector
    from agents.studio_compositor import cairo_source

    calls: list[dict[str, Any]] = []
    now = 100.0
    monkeypatch.setattr(
        content_injector,
        "inject_rgba",
        lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}) is None or True,
    )
    monkeypatch.setattr(cairo_source.time, "monotonic", lambda: now)

    source = _FlatSource()
    runner = CairoSourceRunner(
        source_id="flat",
        source=source,
        canvas_w=2,
        canvas_h=2,
        target_fps=10.0,
        publish_to_source_protocol=True,
        natural_w=2,
        natural_h=2,
        publish_ttl_ms=3000,
    )

    runner.tick_once()
    assert len(calls) == 1

    source.red = 0.5
    now = 100.2
    runner.tick_once()
    assert len(calls) == 2
