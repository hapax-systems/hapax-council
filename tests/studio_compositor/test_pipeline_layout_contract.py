from __future__ import annotations

from agents.studio_compositor.pipeline import _pin_black_background


class _Element:
    def __init__(self) -> None:
        self.props: dict[str, object] = {}

    def set_property(self, name: str, value: object) -> None:
        self.props[name] = value


class _NoBackgroundElement:
    def set_property(self, name: str, value: object) -> None:
        raise AttributeError(name)


def test_pin_black_background_sets_compositor_fill() -> None:
    element = _Element()

    _pin_black_background(element)

    assert element.props["background"] == 1


def test_pin_black_background_is_tolerant_of_elements_without_property() -> None:
    _pin_black_background(_NoBackgroundElement())
