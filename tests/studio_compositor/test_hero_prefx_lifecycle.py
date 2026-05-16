"""Hero pre-FX lifecycle guard tests."""

from __future__ import annotations

from types import SimpleNamespace

from agents.studio_compositor import fx_chain, lifecycle


def test_hero_prefx_effect_is_explicit_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_HERO_PREFX_EFFECT_ENABLED", raising=False)
    monkeypatch.setenv("HAPAX_COMPOSITOR_DISABLE_HERO_EFFECT", "1")

    assert lifecycle._hero_prefx_effect_enabled() is False


def test_hero_prefx_effect_can_be_enabled_explicitly(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_HERO_PREFX_EFFECT_ENABLED", "1")

    assert lifecycle._hero_prefx_effect_enabled() is True


def test_hero_prefx_draw_receives_compositor_and_context() -> None:
    calls: list[tuple[object, object]] = []

    class _HeroPreFx:
        def draw(self, compositor: object, cr: object) -> None:
            calls.append((compositor, cr))

    cr = object()
    compositor = SimpleNamespace(_hero_prefx_effect=_HeroPreFx())

    fx_chain.draw_hero_prefx_effect(compositor, cr)

    assert calls == [(compositor, cr)]
