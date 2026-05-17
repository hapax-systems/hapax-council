from __future__ import annotations

from types import SimpleNamespace

from agents.studio_compositor import lifecycle


def test_3d_compositor_starts_director_runtime(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_3D_COMPOSITOR", "1")
    started: list[object] = []

    class FakeLoader:
        def start(self) -> None:
            started.append(self)

    monkeypatch.setattr(
        "agents.studio_compositor.sierpinski_loader.SierpinskiLoader",
        FakeLoader,
    )
    compositor = SimpleNamespace(_sierpinski_loader=None)

    assert lifecycle._start_3d_director_runtime(compositor) is True
    assert isinstance(compositor._sierpinski_loader, FakeLoader)
    assert started == [compositor._sierpinski_loader]


def test_3d_compositor_does_not_duplicate_existing_director_runtime(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_3D_COMPOSITOR", "1")
    existing = object()
    compositor = SimpleNamespace(_sierpinski_loader=existing)

    assert lifecycle._start_3d_director_runtime(compositor) is False
    assert compositor._sierpinski_loader is existing


def test_non_3d_compositor_does_not_start_director_runtime(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_3D_COMPOSITOR", raising=False)
    compositor = SimpleNamespace(_sierpinski_loader=None)

    assert lifecycle._start_3d_director_runtime(compositor) is False
    assert compositor._sierpinski_loader is None
