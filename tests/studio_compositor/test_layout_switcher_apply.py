"""R9 follow-up: ``apply_layout_switch`` adapter contract tests.

cc-task: dynamic-compositor-layout-switching-followup.

The adapter combines select_layout + LayoutSwitcher cooldown + an
arbitrary layout-state mutator + an arbitrary loader. Tests use light
fakes for layout_state and loader so the adapter contract is pinned
without depending on the production LayoutStore / LayoutState shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.studio_compositor.layout_switcher import (
    LayoutSelection,
    LayoutSwitcher,
    apply_layout_switch,
)


@dataclass
class _FakeLayoutState:
    """Mirrors ``LayoutState.mutate(fn: Callable[[Layout], Layout])``."""

    current: Any = None
    mutations: list[Any] = field(default_factory=list)

    def mutate(self, fn: Any) -> None:
        new_layout = fn(self.current)
        self.current = new_layout
        self.mutations.append(new_layout)


@dataclass
class _FakeLayout:
    name: str


@dataclass
class _FakeLoader:
    """Mirrors ``LayoutLoader.load(name)``."""

    layouts: dict[str, Any] = field(default_factory=dict)
    load_calls: list[str] = field(default_factory=list)

    def load(self, name: str) -> Any:
        self.load_calls.append(name)
        if name not in self.layouts:
            raise KeyError(name)
        return self.layouts[name]


# ── happy path ──────────────────────────────────────────────────────


def test_apply_returns_true_and_mutates_on_first_switch() -> None:
    state = _FakeLayoutState(current=_FakeLayout("garage-door"))
    loader = _FakeLoader(layouts={"default": _FakeLayout("default")})
    switcher = LayoutSwitcher(initial_layout="garage-door")

    applied = apply_layout_switch(state, loader, switcher, vinyl_playing=True)

    assert applied is True
    assert len(state.mutations) == 1
    assert state.mutations[0].name == "default"
    assert loader.load_calls == ["default"]
    assert switcher.current_layout == "default"


def test_apply_returns_false_when_same_layout() -> None:
    state = _FakeLayoutState(current=_FakeLayout("default"))
    loader = _FakeLoader(layouts={"default": _FakeLayout("default")})
    switcher = LayoutSwitcher(initial_layout="default")

    applied = apply_layout_switch(state, loader, switcher)

    assert applied is False
    assert state.mutations == []
    assert loader.load_calls == []  # short-circuited; loader untouched


def test_apply_returns_false_when_cooldown_blocks() -> None:
    clock = [1000.0]
    state = _FakeLayoutState(current=_FakeLayout("default"))
    loader = _FakeLoader(
        layouts={
            "default": _FakeLayout("default"),
            "consent-safe": _FakeLayout("consent-safe"),
        }
    )
    switcher = LayoutSwitcher(initial_layout="default", clock=lambda: clock[0])

    # First switch goes through.
    apply_layout_switch(state, loader, switcher, consent_safe_active=True)
    assert switcher.current_layout == "consent-safe"
    assert len(state.mutations) == 1

    # Same tick: try to switch back. Cooldown blocks.
    applied = apply_layout_switch(state, loader, switcher)
    assert applied is False
    assert len(state.mutations) == 1  # no new mutation


def test_apply_consent_safe_bypasses_cooldown() -> None:
    clock = [1000.0]
    state = _FakeLayoutState(current=_FakeLayout("garage-door"))
    loader = _FakeLoader(
        layouts={
            "default": _FakeLayout("default"),
            "consent-safe": _FakeLayout("consent-safe"),
        }
    )
    switcher = LayoutSwitcher(initial_layout="garage-door", clock=lambda: clock[0])

    apply_layout_switch(state, loader, switcher, vinyl_playing=True)
    assert switcher.current_layout == "default"

    # Cooldown not elapsed, but consent_safe bypasses.
    applied = apply_layout_switch(state, loader, switcher, consent_safe_active=True)
    assert applied is True
    assert switcher.current_layout == "consent-safe"
    assert len(state.mutations) == 2


def test_apply_records_switch_via_record_switch() -> None:
    """After a successful switch, the cooldown clock advances."""
    clock = [1000.0]
    state = _FakeLayoutState(current=_FakeLayout("garage-door"))
    loader = _FakeLoader(layouts={"default": _FakeLayout("default")})
    switcher = LayoutSwitcher(initial_layout="garage-door", clock=lambda: clock[0])

    apply_layout_switch(state, loader, switcher, vinyl_playing=True, now=1000.0)

    # record_switch stamped now=1000.0. Advance 29s — cooldown still
    # active (default 30s) — the switcher should refuse a follow-up
    # switch even via direct should_switch().
    clock[0] = 1029.0
    can_switch = switcher.should_switch(LayoutSelection("garage-door", "test_back_to_boot"))
    assert can_switch is False
    # Advance past cooldown, switch is allowed again.
    clock[0] = 1031.0
    assert switcher.should_switch(LayoutSelection("garage-door", "test_back_to_boot")) is True


# ── failure modes ───────────────────────────────────────────────────


def test_apply_propagates_loader_keyerror() -> None:
    """An unknown layout in the loader propagates KeyError so the
    caller can decide between log+skip and escalate."""
    state = _FakeLayoutState(current=_FakeLayout("garage-door"))
    loader = _FakeLoader(layouts={})  # no layouts at all
    switcher = LayoutSwitcher(initial_layout="garage-door")

    try:
        apply_layout_switch(state, loader, switcher, vinyl_playing=True)
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError to propagate")

    # State unchanged; switcher state also unchanged (record_switch not
    # called when loader fails).
    assert state.mutations == []
    assert switcher.current_layout == "garage-door"


# ── stream_mode integration ─────────────────────────────────────────


def test_apply_stream_mode_deep_returns_default_not_retired_layout() -> None:
    state = _FakeLayoutState(current=_FakeLayout("garage-door"))
    loader = _FakeLoader(layouts={"default": _FakeLayout("default")})
    switcher = LayoutSwitcher(initial_layout="garage-door")

    applied = apply_layout_switch(state, loader, switcher, stream_mode="deep")

    assert applied is True
    assert switcher.current_layout == "default"
    assert state.mutations[0].name == "default"
