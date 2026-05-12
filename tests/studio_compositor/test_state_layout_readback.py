from __future__ import annotations

import json
from types import SimpleNamespace

from agents.studio_compositor import active_wards
from agents.studio_compositor import state as state_module


class _Registry:
    def __init__(self, surfaces: dict[str, object | None]) -> None:
        self._surfaces = surfaces

    def get_current_surface(self, source_id: str) -> object | None:
        if source_id not in self._surfaces:
            raise KeyError(source_id)
        return self._surfaces[source_id]


def test_publish_active_layout_readback_uses_live_registry(monkeypatch, tmp_path) -> None:
    active_path = tmp_path / "active_wards.json"
    current_layout_path = tmp_path / "current-layout-state.json"
    monkeypatch.setattr(active_wards, "ACTIVE_WARDS_FILE", active_path)
    monkeypatch.setattr(active_wards, "CURRENT_LAYOUT_STATE_FILE", current_layout_path)

    layout = SimpleNamespace(
        name="operator-layout",
        assignments=[
            SimpleNamespace(source="red", surface="a"),
            SimpleNamespace(source="missing-source", surface="b"),
            SimpleNamespace(source="none-surface", surface="c"),
            SimpleNamespace(source="missing-surface", surface="absent"),
        ],
        surface_by_id=lambda surface_id: object() if surface_id != "absent" else None,
    )
    compositor = SimpleNamespace(
        _layout_mode="sierpinski",
        layout_state=SimpleNamespace(get=lambda: layout),
        source_registry=_Registry({"red": object(), "none-surface": None}),
    )

    state_module.publish_active_layout_readback(compositor)

    assert active_wards.read(path=active_path, stale_s=60.0) == ["red"]
    current_layout = json.loads(current_layout_path.read_text(encoding="utf-8"))
    assert current_layout["layout_name"] == "operator-layout"
    assert current_layout["layout_mode"] == "sierpinski"
    assert current_layout["active_ward_ids"] == ["red"]
    assert current_layout["schema_version"] == 1
