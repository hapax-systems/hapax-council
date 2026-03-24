"""Thin reactive wrapper over GObject signals and properties.

Provides Variable, Binding, and hook() for auto-disconnect-on-destroy.
Inspired by astal-py patterns but without the external dependency.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from gi.repository import GLib, GObject

T = TypeVar("T")


class Variable(GObject.Object):
    """Reactive value container. Emits 'changed' when value is set."""

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, initial: Any = None) -> None:
        super().__init__()
        self._value = initial
        self._poll_source: int | None = None

    def get(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        if self._value != value:
            self._value = value
            self.emit("changed")

    def subscribe(self, callback: Callable[[Any], None]) -> Callable[[], None]:
        """Subscribe to changes. Returns unsubscribe function."""
        handler_id = self.connect("changed", lambda _: callback(self._value))
        return lambda: self.disconnect(handler_id)

    def poll(self, interval_ms: int, fn: Callable[[], Any]) -> Variable:
        """Poll a function on interval and update value."""
        if self._poll_source is not None:
            GLib.source_remove(self._poll_source)

        def tick(*_args: Any) -> bool:
            try:
                self.set(fn())
            except Exception:
                pass  # polling failures are silent — stale data is shown
            return GLib.SOURCE_CONTINUE

        tick()  # initial value
        self._poll_source = GLib.timeout_add(interval_ms, tick)
        return self

    def stop_poll(self) -> None:
        if self._poll_source is not None:
            GLib.source_remove(self._poll_source)
            self._poll_source = None


class Binding:
    """Wraps a GObject property or Variable into a subscribable stream."""

    def __init__(
        self,
        emitter: GObject.Object,
        prop: str | None = None,
        transform: Callable[[Any], Any] = lambda x: x,
    ) -> None:
        self.emitter = emitter
        self.prop = prop
        self.transform = transform

    def get(self) -> Any:
        if self.prop is not None:
            raw = self.emitter.get_property(self.prop.replace("-", "_"))
        elif isinstance(self.emitter, Variable):
            raw = self.emitter.get()
        else:
            raise ValueError("Binding requires a property name or a Variable")
        return self.transform(raw)

    def as_(self, fn: Callable[[Any], Any]) -> Binding:
        """Chain a transform. Returns a new Binding."""
        prev = self.transform
        return Binding(self.emitter, self.prop, lambda x: fn(prev(x)))

    def subscribe(self, callback: Callable[[Any], None]) -> Callable[[], None]:
        signal = "changed" if self.prop is None else f"notify::{self.prop}"
        handler_id = self.emitter.connect(signal, lambda *_: callback(self.get()))
        return lambda: self.emitter.disconnect(handler_id)


def bind(emitter: GObject.Object, prop: str | None = None) -> Binding:
    """Shorthand: bind(speaker, 'volume') -> Binding."""
    return Binding(emitter, prop)


def hook(
    widget: Any,
    emitter: GObject.Object,
    signal: str,
    callback: Callable[..., None],
) -> int:
    """Connect a signal and auto-disconnect when widget is destroyed."""
    handler_id = emitter.connect(signal, callback)
    widget.connect("destroy", lambda *_: emitter.disconnect(handler_id))
    return handler_id


def bind_property_to_label(
    widget: Any,
    binding: Binding,
) -> None:
    """Subscribe a Binding to a Gtk.Label, auto-disconnect on destroy."""
    widget.set_label(str(binding.get()))
    unsub = binding.subscribe(lambda v: widget.set_label(str(v)))
    widget.connect("destroy", lambda *_: unsub())


def bind_property_to_css_classes(
    widget: Any,
    binding: Binding,
) -> None:
    """Subscribe a Binding that returns a list of CSS class names."""
    widget.set_css_classes(binding.get())
    unsub = binding.subscribe(lambda v: widget.set_css_classes(v))
    widget.connect("destroy", lambda *_: unsub())
