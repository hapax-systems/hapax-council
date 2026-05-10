"""R9 phase-2: ``apply_layout_switch_via_store`` adapter contract tests.

cc-task: dynamic-compositor-layout-switching-followup-phase-2.

Mirrors the phase-1 test shape (``test_layout_switcher_apply.py``) but
exercises the LayoutStore-binding adapter — same selection policy and
cooldown semantics, different production-shape collaborator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.studio_compositor.layout_switcher import (
    LayoutSelection,
    LayoutSwitcher,
    apply_layout_switch_via_store,
)


@dataclass
class _FakeLayoutStore:
    """Mirrors the LayoutStore API surface this adapter touches."""

    layouts: dict[str, Any] = field(default_factory=dict)
    active: str | None = None
    set_active_calls: list[str] = field(default_factory=list)

    def get(self, name: str) -> Any:
        return self.layouts.get(name)

    def set_active(self, name: str) -> bool:
        if name not in self.layouts:
            return False
        self.active = name
        self.set_active_calls.append(name)
        return True


# ── happy path ──────────────────────────────────────────────────────


def test_apply_returns_true_and_sets_active_on_first_switch() -> None:
    store = _FakeLayoutStore(layouts={"default": object()}, active="garage-door")
    switcher = LayoutSwitcher(initial_layout="garage-door")

    applied = apply_layout_switch_via_store(store, switcher, vinyl_playing=True)

    assert applied is True
    assert store.active == "default"
    assert store.set_active_calls == ["default"]
    assert switcher.current_layout == "default"


def test_apply_returns_false_when_same_layout() -> None:
    store = _FakeLayoutStore(layouts={"default": object()}, active="default")
    switcher = LayoutSwitcher(initial_layout="default")

    applied = apply_layout_switch_via_store(store, switcher)

    assert applied is False
    assert store.set_active_calls == []


def test_apply_returns_false_when_cooldown_blocks() -> None:
    clock = [1000.0]
    store = _FakeLayoutStore(
        layouts={"default": object(), "consent-safe": object()}, active="default"
    )
    switcher = LayoutSwitcher(initial_layout="default", clock=lambda: clock[0])

    apply_layout_switch_via_store(store, switcher, consent_safe_active=True)
    assert switcher.current_layout == "consent-safe"

    applied = apply_layout_switch_via_store(store, switcher)
    assert applied is False
    assert store.set_active_calls == ["consent-safe"]  # still just the first


def test_apply_consent_safe_bypasses_cooldown() -> None:
    clock = [1000.0]
    store = _FakeLayoutStore(
        layouts={"default": object(), "consent-safe": object()}, active="garage-door"
    )
    switcher = LayoutSwitcher(initial_layout="garage-door", clock=lambda: clock[0])

    apply_layout_switch_via_store(store, switcher, vinyl_playing=True)
    assert switcher.current_layout == "default"

    applied = apply_layout_switch_via_store(store, switcher, consent_safe_active=True)
    assert applied is True
    assert switcher.current_layout == "consent-safe"
    assert store.set_active_calls == ["default", "consent-safe"]


def test_apply_records_switch_via_record_switch() -> None:
    clock = [1000.0]
    store = _FakeLayoutStore(layouts={"default": object()}, active="garage-door")
    switcher = LayoutSwitcher(initial_layout="garage-door", clock=lambda: clock[0])

    apply_layout_switch_via_store(store, switcher, vinyl_playing=True, now=1000.0)

    clock[0] = 1029.0
    assert switcher.should_switch(LayoutSelection("garage-door", "test_back_to_boot")) is False
    clock[0] = 1031.0
    assert switcher.should_switch(LayoutSelection("garage-door", "test_back_to_boot")) is True


# ── failure modes ───────────────────────────────────────────────────


def test_apply_raises_keyerror_when_layout_not_loaded() -> None:
    """KeyError propagates so the caller's failure policy stays explicit."""
    store = _FakeLayoutStore(layouts={}, active="garage-door")
    switcher = LayoutSwitcher(initial_layout="garage-door")

    try:
        apply_layout_switch_via_store(store, switcher, vinyl_playing=True)
    except KeyError as exc:
        assert "default" in str(exc)
    else:
        raise AssertionError("expected KeyError for missing layout")
    assert store.set_active_calls == []
    assert switcher.current_layout == "garage-door"


# ── stream_mode integration ─────────────────────────────────────────


def test_apply_stream_mode_deep_returns_default_not_retired_layout() -> None:
    store = _FakeLayoutStore(layouts={"default": object()}, active="garage-door")
    switcher = LayoutSwitcher(initial_layout="garage-door")

    applied = apply_layout_switch_via_store(store, switcher, stream_mode="deep")

    assert applied is True
    assert switcher.current_layout == "default"
    assert store.active == "default"
