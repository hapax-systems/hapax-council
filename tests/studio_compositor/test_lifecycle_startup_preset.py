from __future__ import annotations

from types import SimpleNamespace

from agents.studio_compositor import lifecycle


def test_startup_preset_uses_env_clean(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setenv("HAPAX_COMPOSITOR_STARTUP_PRESET", "clean")
    monkeypatch.setattr(
        "agents.studio_compositor.effects.try_graph_preset",
        lambda _compositor, name: calls.append(name) or True,
    )
    compositor = SimpleNamespace()

    assert lifecycle.apply_startup_preset(compositor) == "clean"
    assert calls == ["clean"]
    assert compositor._current_preset_name == "clean"


def test_startup_preset_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_COMPOSITOR_STARTUP_PRESET", "disabled")
    monkeypatch.setattr(
        "agents.studio_compositor.effects.try_graph_preset",
        lambda *_args: (_ for _ in ()).throw(AssertionError("should not activate preset")),
    )

    assert lifecycle.apply_startup_preset(SimpleNamespace()) is None
