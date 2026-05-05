"""Runtime witness files for the Logos executive-function rail."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

DEFAULT_WITNESS_ROOT = Path("/dev/shm/hapax-logos")
_log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


@dataclass(frozen=True)
class OpenAPISnapshotState:
    path: Path
    sha256: str
    route_count: int
    written: bool
    updated_at: str


class LogosWitnessProducer:
    """Write the live Logos witnesses consumed by the braid snapshot rail."""

    def __init__(
        self,
        *,
        root: Path = DEFAULT_WITNESS_ROOT,
        interval_seconds: float = 1.0,
    ) -> None:
        self.root = root
        self.interval_seconds = interval_seconds
        self.health_path = root / "health.json"
        self.openapi_path = root / "openapi.json"
        self._started_at = _utc_now()
        self._started_monotonic = time.monotonic()
        self._openapi_sha256: str | None = None
        self._openapi_route_count = 0
        self._openapi_updated_at: str | None = None

    def write_openapi_snapshot(self, app: FastAPI, *, force: bool = False) -> OpenAPISnapshotState:
        schema = app.openapi()
        canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        route_count = len(schema.get("paths") or {})
        written = force or digest != self._openapi_sha256 or not self.openapi_path.exists()
        if written:
            _atomic_write_json(self.openapi_path, schema)
            self._openapi_updated_at = _iso_z(_utc_now())
        self._openapi_sha256 = digest
        self._openapi_route_count = route_count
        return OpenAPISnapshotState(
            path=self.openapi_path,
            sha256=digest,
            route_count=route_count,
            written=written,
            updated_at=self._openapi_updated_at or _iso_z(self._started_at),
        )

    def build_health_payload(
        self,
        app: FastAPI,
        *,
        openapi: OpenAPISnapshotState | None = None,
    ) -> dict[str, Any]:
        if openapi is None:
            openapi = self.write_openapi_snapshot(app)
        return {
            "schema_version": 1,
            "component": "logos-api",
            "producer": "logos_health_openapi_witness",
            "status": "ok",
            "ready": True,
            "timestamp": _iso_z(_utc_now()),
            "started_at": _iso_z(self._started_at),
            "uptime_seconds": round(time.monotonic() - self._started_monotonic, 3),
            "pid": os.getpid(),
            "cadence_seconds": self.interval_seconds,
            "app": {
                "title": app.title,
                "version": app.version,
                "route_count": len(app.routes),
            },
            "openapi": {
                "path": str(openapi.path),
                "sha256": openapi.sha256,
                "route_count": openapi.route_count,
                "updated_at": openapi.updated_at,
            },
            "health_path": str(self.health_path),
        }

    def write_health_snapshot(
        self,
        app: FastAPI,
        *,
        openapi: OpenAPISnapshotState | None = None,
    ) -> dict[str, Any]:
        payload = self.build_health_payload(app, openapi=openapi)
        _atomic_write_json(self.health_path, payload)
        return payload

    def write_once(self, app: FastAPI, *, force_openapi: bool = False) -> None:
        openapi = self.write_openapi_snapshot(app, force=force_openapi)
        self.write_health_snapshot(app, openapi=openapi)

    async def run(self, app: FastAPI) -> None:
        force_openapi = True
        while True:
            try:
                self.write_once(app, force_openapi=force_openapi)
                force_openapi = False
            except Exception:
                _log.debug("Logos witness write failed", exc_info=True)
            await asyncio.sleep(self.interval_seconds)


def start_logos_witness_producer(app: FastAPI) -> asyncio.Task[None]:
    producer = LogosWitnessProducer()
    app.state.logos_witness_producer = producer
    return asyncio.create_task(producer.run(app))
