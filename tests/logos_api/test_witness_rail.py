from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from logos.api.witness_rail import LogosWitnessProducer


def _app() -> FastAPI:
    app = FastAPI(title="logos-api", version="0.2.0")

    @app.get("/api/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_openapi_snapshot_written_and_rewritten_on_schema_change(tmp_path: Path) -> None:
    app = _app()
    producer = LogosWitnessProducer(root=tmp_path)

    first = producer.write_openapi_snapshot(app, force=True)
    assert first.written is True
    assert first.path == tmp_path / "openapi.json"
    assert first.route_count == 1

    schema = json.loads(first.path.read_text(encoding="utf-8"))
    assert schema["info"]["title"] == "logos-api"
    assert "/api/ping" in schema["paths"]

    @app.get("/api/second")
    async def second() -> dict[str, bool]:
        return {"ok": True}

    app.openapi_schema = None
    second_state = producer.write_openapi_snapshot(app)
    assert second_state.written is True
    assert second_state.sha256 != first.sha256
    assert second_state.route_count == 2


def test_health_snapshot_points_to_openapi_snapshot(tmp_path: Path) -> None:
    app = _app()
    producer = LogosWitnessProducer(root=tmp_path)

    openapi = producer.write_openapi_snapshot(app, force=True)
    payload = producer.write_health_snapshot(app, openapi=openapi)

    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health == payload
    assert health["component"] == "logos-api"
    assert health["status"] == "ok"
    assert health["ready"] is True
    assert health["openapi"]["path"] == str(tmp_path / "openapi.json")
    assert health["openapi"]["sha256"] == openapi.sha256


@pytest.mark.asyncio()
async def test_witness_loop_updates_health_at_cadence(tmp_path: Path) -> None:
    app = _app()
    producer = LogosWitnessProducer(root=tmp_path, interval_seconds=0.01)

    task = asyncio.create_task(producer.run(app))
    try:
        await asyncio.sleep(0.025)
        health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
        assert (tmp_path / "openapi.json").exists()
        assert health["cadence_seconds"] == 0.01
        assert health["uptime_seconds"] > 0
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
