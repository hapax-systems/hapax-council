from __future__ import annotations

import asyncio
from pathlib import Path

from starlette.responses import JSONResponse

import logos.api.routes.studio as studio_routes


def test_studio_layout_api_accepts_aoa_as_preferred_mode(monkeypatch, tmp_path: Path) -> None:
    layout_file = tmp_path / "layout-mode.txt"
    monkeypatch.setattr(studio_routes, "Path", lambda _value: layout_file)

    response = asyncio.run(
        studio_routes.set_layout_mode(studio_routes.LayoutModeRequest(mode="aoa"))
    )

    assert response == {"mode": "aoa"}
    assert layout_file.read_text(encoding="utf-8") == "aoa"


def test_studio_layout_api_accepts_sierpinski_as_legacy_alias(monkeypatch, tmp_path: Path) -> None:
    layout_file = tmp_path / "layout-mode.txt"
    monkeypatch.setattr(studio_routes, "Path", lambda _value: layout_file)

    response = asyncio.run(
        studio_routes.set_layout_mode(studio_routes.LayoutModeRequest(mode="sierpinski"))
    )

    assert response == {"mode": "aoa", "legacy_alias": "sierpinski"}
    assert layout_file.read_text(encoding="utf-8") == "aoa"


def test_studio_layout_api_rejects_unknown_mode() -> None:
    response = asyncio.run(
        studio_routes.set_layout_mode(studio_routes.LayoutModeRequest(mode="triangle"))
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
