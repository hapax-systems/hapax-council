"""FastAPI application for the cockpit API.

Serves data from cockpit/data/ collectors over HTTP.
Designed to be consumed by the React SPA at cockpit-web/.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

try:
    from shared import langfuse_config  # noqa: F401
except Exception:
    pass  # langfuse optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cockpit.api.cache import start_refresh_loop
from cockpit.api.sessions import agent_run_manager

_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_refresh_loop()

    # Start reactive engine
    try:
        from cockpit.engine import ReactiveEngine
        from cockpit.engine.reactive_rules import register_rules

        engine = ReactiveEngine()
        register_rules(engine.registry)
        await engine.start()
        app.state.engine = engine

        # Wire revocation propagator to carrier registry
        from shared.governance.revocation_wiring import get_revocation_propagator

        app.state.revocation_propagator = get_revocation_propagator()
    except Exception:
        _log.exception("Reactive engine failed to start (continuing without it)")
        engine = None

    yield

    if engine is not None:
        await engine.stop()
    await agent_run_manager.shutdown()


app = FastAPI(
    title="cockpit-api",
    description="Cockpit dashboard API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:8051",  # Cockpit API (self-hosted SPA)
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8051",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# OTel: extract incoming trace context + create server spans
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)
except Exception:
    pass  # OTel instrumentation is optional

# Prometheus metrics: request count, latency histograms, error rates
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
except Exception:
    pass  # Prometheus is optional

from cockpit.api.routes.accommodations import router as accommodations_router
from cockpit.api.routes.agents import router as agents_router
from cockpit.api.routes.chat import router as chat_router
from cockpit.api.routes.consent import router as consent_router
from cockpit.api.routes.copilot import router as copilot_router
from cockpit.api.routes.cycle_mode import router as cycle_mode_router
from cockpit.api.routes.data import router as data_router
from cockpit.api.routes.demos import router as demos_router
from cockpit.api.routes.engine import router as engine_router
from cockpit.api.routes.flow import router as flow_router
from cockpit.api.routes.governance import router as governance_router
from cockpit.api.routes.logos import router as logos_router
from cockpit.api.routes.nudges import router as nudges_router
from cockpit.api.routes.profile import router as profile_router
from cockpit.api.routes.query import router as query_router
from cockpit.api.routes.scout import router as scout_router
from cockpit.api.routes.studio import router as studio_router

app.include_router(data_router)
app.include_router(nudges_router)
app.include_router(agents_router)
app.include_router(chat_router)
app.include_router(profile_router)
app.include_router(accommodations_router)
app.include_router(copilot_router)
app.include_router(demos_router)
app.include_router(cycle_mode_router)
app.include_router(scout_router)
app.include_router(query_router)
app.include_router(engine_router)
app.include_router(consent_router)
app.include_router(governance_router)
app.include_router(studio_router)
app.include_router(logos_router)
app.include_router(flow_router)

# Mount HLS segment directory for live stream serving
from pathlib import Path as _Path

_HLS_DIR = _Path.home() / ".cache" / "hapax-compositor" / "hls"
_HLS_DIR.mkdir(parents=True, exist_ok=True)
from starlette.staticfiles import StaticFiles as _StaticFiles

app.mount("/api/studio/hls", _StaticFiles(directory=_HLS_DIR), name="hls-stream")


@app.get("/")
async def root():
    return {"name": "cockpit-api", "version": "0.2.0"}


from pathlib import Path

SPA_DIR = Path(__file__).parent / "static"
if SPA_DIR.is_dir():
    from starlette.responses import FileResponse
    from starlette.staticfiles import StaticFiles

    @app.get("/app/{path:path}")
    async def spa_catchall(path: str):
        index = SPA_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        return {"error": "SPA not built"}

    app.mount("/static", StaticFiles(directory=SPA_DIR), name="spa")
