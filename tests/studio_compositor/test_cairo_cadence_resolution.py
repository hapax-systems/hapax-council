"""Perf pass 2026-04-17 — cairo source cadence now actually honors layout JSON.

Before this, ``source.rate_hz`` on the Layout schema was parsed but
silently ignored by ``SourceRegistry._construct_cairo_runner``; every
cairo source ran at the 10 fps default regardless of what the layout
declared. Rate-limited sources (legibility, hothouse chrome) were
rendering 5-10× more often than intended, burning CPU for output
nobody saw.

These tests pin the new precedence order:
  1. ``params.fps`` (explicit override)
  2. ``source.rate_hz`` (layout JSON authoring slot)
  3. 30 fps for ``update_cadence="always"``
  4. 10 fps fallback
"""

from __future__ import annotations

import pytest

from agents.studio_compositor.budget import BudgetTracker
from agents.studio_compositor.source_registry import (
    SourceRegistry,
    UnknownBackendError,
    V4L2SourceHandle,
)
from shared.compositor_model import SourceSchema


@pytest.fixture
def registry():
    return SourceRegistry()


@pytest.fixture
def budget():
    return BudgetTracker()


def _cairo_source(**params):
    return SourceSchema(
        id=params.pop("id", "test_source"),
        kind="cairo",
        backend="cairo",
        params={"class_name": "ActivityHeaderCairoSource", **params.pop("class_params", {})},
        update_cadence=params.pop("update_cadence", "always"),
        rate_hz=params.pop("rate_hz", None),
    )


def _v4l2_source(**params):
    return SourceSchema(
        id=params.pop("id", "darkplaces"),
        kind="video",
        backend="v4l2",
        params=params.pop(
            "source_params",
            {"device": "/dev/video52", "natural_w": 1280, "natural_h": 720},
        ),
    )


def test_v4l2_source_constructs_passive_handle(registry):
    source = _v4l2_source()

    handle = registry.construct_backend(source)

    assert isinstance(handle, V4L2SourceHandle)
    assert handle.device == "/dev/video52"
    assert handle.width == 1280
    assert handle.height == 720
    assert handle.get_current_surface() is None


def test_v4l2_source_requires_device(registry):
    source = _v4l2_source(source_params={"natural_w": 1280, "natural_h": 720})

    with pytest.raises(UnknownBackendError, match="missing params.device"):
        registry.construct_backend(source)


def test_rate_hz_from_layout_honored(registry, budget):
    source = _cairo_source(update_cadence="rate", rate_hz=2)
    runner = registry.construct_backend(source, budget_tracker=budget)
    assert runner._period == pytest.approx(0.5)


def test_params_fps_takes_precedence(registry, budget):
    source = _cairo_source(
        update_cadence="rate",
        rate_hz=2,
        class_params={"fps": 6.0},
    )
    runner = registry.construct_backend(source, budget_tracker=budget)
    assert runner._period == pytest.approx(1.0 / 6.0)


def test_update_cadence_always_defaults_10fps(registry, budget):
    # 2026-04-17 perf pass briefly bumped "always" to 30 fps, driving
    # studio-compositor to 214% CPU and janking the cameras. Reverted:
    # "always" falls through to the 10 fps default alongside every
    # other cadence that doesn't explicitly declare rate_hz/params.fps.
    source = _cairo_source(update_cadence="always")
    runner = registry.construct_backend(source, budget_tracker=budget)
    assert runner._period == pytest.approx(0.1)


def test_default_10fps_when_no_hints(registry, budget):
    source = _cairo_source(update_cadence="on_change")
    runner = registry.construct_backend(source, budget_tracker=budget)
    assert runner._period == pytest.approx(0.1)
