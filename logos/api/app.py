"""FastAPI application for the logos API.

Serves data from logos/data/ collectors over HTTP.
Consumed by the Tauri desktop app and Vite dev server.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

try:
    from logos import _langfuse_config  # noqa: F401
except Exception:
    pass  # langfuse optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from logos.api.cache import start_refresh_loop
from logos.api.sessions import agent_run_manager

_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_refresh_loop()

    # Recover stale insight queries from prior shutdown
    try:
        from logos.data.insight_queries import recover_stale

        recover_stale()
    except Exception:
        _log.exception("Insight query recovery failed (continuing)")

    # Verify Qdrant collection schemas (non-fatal)
    try:
        from logos._qdrant_schema import log_collection_issues

        await log_collection_issues()
    except Exception:
        _log.exception("Qdrant schema verification failed (continuing)")

    # Initialize effect graph runtime (pure Python — no GPU/GStreamer needed)
    try:
        from pathlib import Path as _Path

        from agents.effect_graph.compiler import GraphCompiler
        from agents.effect_graph.modulator import UniformModulator
        from agents.effect_graph.registry import ShaderRegistry
        from agents.effect_graph.runtime import GraphRuntime
        from logos.api.routes.studio import set_graph_runtime, set_shader_registry

        _shader_nodes_dir = _Path(__file__).parent.parent.parent / "agents" / "shaders" / "nodes"
        _registry = ShaderRegistry(_shader_nodes_dir)
        _compiler = GraphCompiler(_registry)
        _modulator = UniformModulator()
        _runtime = GraphRuntime(registry=_registry, compiler=_compiler, modulator=_modulator)

        set_graph_runtime(_runtime)
        set_shader_registry(_registry)
        _log.info(
            "Effect graph runtime: %d node types loaded (API-local)", len(_registry.node_types)
        )
    except Exception:
        _log.exception("Effect graph runtime failed to initialize (continuing without it)")

    # Start event bus
    from logos.api.routes.events import set_event_bus
    from logos.event_bus import EventBus, set_global_bus

    event_bus = EventBus(maxlen=500)
    app.state.event_bus = event_bus
    set_event_bus(event_bus)
    set_global_bus(event_bus)

    # Start reactive engine
    try:
        from logos.engine import ReactiveEngine
        from logos.engine.reactive_rules import register_rules

        engine = ReactiveEngine(event_bus=event_bus)
        register_rules(engine.registry)
        await engine.start()
        app.state.engine = engine

        # Wire revocation propagator to carrier registry
        from logos._revocation_wiring import get_revocation_propagator

        app.state.revocation_propagator = get_revocation_propagator()
    except Exception:
        _log.exception("Reactive engine failed to start (continuing without it)")
        engine = None

    # Start chronicle sampler and periodic trim
    import asyncio

    from shared.chronicle import trim as chronicle_trim
    from shared.chronicle_sampler import run_sampler

    async def _chronicle_trim_loop():
        while True:
            try:
                chronicle_trim()
            except Exception:
                _log.debug("Chronicle trim failed", exc_info=True)
            await asyncio.sleep(60)

    _sampler_task = asyncio.create_task(run_sampler())
    _trim_task = asyncio.create_task(_chronicle_trim_loop())

    yield

    _sampler_task.cancel()
    _trim_task.cancel()
    if engine is not None:
        await engine.stop()
    await agent_run_manager.shutdown()


app = FastAPI(
    title="logos-api",
    description="Logos dashboard API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "tauri://localhost",  # Tauri desktop app
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

from logos.api.routes.accommodations import router as accommodations_router
from logos.api.routes.agents import router as agents_router
from logos.api.routes.chat import router as chat_router
from logos.api.routes.chronicle import router as chronicle_router
from logos.api.routes.consent import router as consent_router
from logos.api.routes.copilot import router as copilot_router
from logos.api.routes.data import router as data_router
from logos.api.routes.demos import router as demos_router
from logos.api.routes.dmn import router as dmn_router
from logos.api.routes.engine import router as engine_router
from logos.api.routes.events import router as events_router
from logos.api.routes.exploration import router as exploration_router
from logos.api.routes.flow import router as flow_router
from logos.api.routes.fortress import router as fortress_router
from logos.api.routes.governance import router as governance_router
from logos.api.routes.logos import router as logos_router
from logos.api.routes.nudges import router as nudges_router
from logos.api.routes.orientation import router as orientation_router
from logos.api.routes.pi import router as pi_router
from logos.api.routes.profile import router as profile_router
from logos.api.routes.query import router as query_router
from logos.api.routes.scout import router as scout_router
from logos.api.routes.sprint import router as sprint_router
from logos.api.routes.stimmung import router as stimmung_router
from logos.api.routes.studio import router as studio_router
from logos.api.routes.studio_effects import router as studio_effects_router
from logos.api.routes.vault import router as vault_router
from logos.api.routes.working_mode import router as working_mode_router

app.include_router(data_router)
app.include_router(nudges_router)
app.include_router(agents_router)
app.include_router(chat_router)
app.include_router(profile_router)
app.include_router(accommodations_router)
app.include_router(copilot_router)
app.include_router(demos_router)
app.include_router(working_mode_router)
app.include_router(scout_router)
app.include_router(query_router)
app.include_router(engine_router)
app.include_router(consent_router)
app.include_router(governance_router)
app.include_router(studio_router)
app.include_router(studio_effects_router)
app.include_router(logos_router)
app.include_router(flow_router)
app.include_router(fortress_router)
app.include_router(pi_router)
app.include_router(sprint_router)
app.include_router(stimmung_router)
app.include_router(dmn_router)
app.include_router(events_router)
app.include_router(exploration_router)
app.include_router(orientation_router)
app.include_router(vault_router)
app.include_router(chronicle_router)

# Mount HLS segment directory for live stream serving
# Override .ts MIME type: Starlette defaults to Qt Linguist (text/vnd.trolltech.linguist)
# but HLS transport stream segments need video/mp2t.
import mimetypes as _mimetypes

_mimetypes.add_type("video/mp2t", ".ts")

from pathlib import Path as _Path

_HLS_DIR = _Path.home() / ".cache" / "hapax-compositor" / "hls"
_HLS_DIR.mkdir(parents=True, exist_ok=True)
from starlette.staticfiles import StaticFiles as _StaticFiles

app.mount("/api/studio/hls", _StaticFiles(directory=_HLS_DIR), name="hls-stream")


@app.get("/")
async def root():
    return {
        "name": "logos-api",
        "version": "0.2.0",
        "docs": "/docs",
        "app": "/app/",
    }


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
