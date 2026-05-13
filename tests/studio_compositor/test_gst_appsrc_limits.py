"""Tests for live appsrc queue containment defaults."""

from __future__ import annotations

from agents.studio_compositor.gst_appsrc_limits import configure_live_appsrc_queue


class _FakeElement:
    def __init__(self, *, unsupported: set[str] | None = None) -> None:
        self.unsupported = unsupported or set()
        self.props: dict[str, object] = {}

    def set_property(self, name: str, value: object) -> None:
        if name in self.unsupported:
            raise RuntimeError(name)
        self.props[name] = value


def test_configure_live_appsrc_queue_bounds_and_leaks_downstream(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_LIVE_APPSRC_MAX_BUFFERS", raising=False)
    elem = _FakeElement()

    configure_live_appsrc_queue(elem)

    assert elem.props["block"] is False
    assert elem.props["max-buffers"] == 2
    assert elem.props["max-bytes"] == 0
    assert elem.props["max-time"] == 0
    assert elem.props["leaky-type"] == 2


def test_configure_live_appsrc_queue_tolerates_older_gstreamer() -> None:
    elem = _FakeElement(unsupported={"leaky-type", "max-time"})

    configure_live_appsrc_queue(elem)

    assert elem.props["block"] is False
    assert elem.props["max-buffers"] == 2
    assert elem.props["max-bytes"] == 0
    assert "leaky-type" not in elem.props
