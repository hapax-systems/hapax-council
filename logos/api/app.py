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


# Phase 6d-i.B drift signal bridge. Adapts logos/data/drift.py's
# DriftSummary into the _DriftSource Protocol that
# drift_significant_observation expects. Saturation point of 10 high-
# severity items lines up with the "operator burnt by drift" threshold
# the session-context hook has surfaced (~16 high items at audit time).
class LogosDriftBridge:
    """Bridge collect_drift() → drift_score() Protocol for SystemDegradedEngine."""

    def drift_score(self) -> float:
        from logos.data.drift import collect_drift

        summary = collect_drift()
        if summary is None:
            return 0.0
        high = sum(1 for i in summary.items if i.severity.upper() == "HIGH")
        return min(1.0, high / 10.0)


# Phase 6d-i.B GPU pressure bridge. Reads the same infra-snapshot.json
# that logos/data/gpu.py:collect_vram() consumes, but synchronously so
# the Protocol stays sync (gpu_pressure_observation is called inside
# the SystemDegradedEngine tick loop without awaiting). The snapshot
# is host-written by the health monitor; missing/stale file → (0, 0)
# which the adapter treats as "pressure unknown" (False, instrument
# fault tolerance).
class LogosGpuBridge:
    """Bridge infra-snapshot.json gpu block → gpu_memory_used_total() Protocol."""

    def gpu_memory_used_total(self) -> tuple[int, int]:
        import json

        from logos._config import PROFILES_DIR

        try:
            data = json.loads((PROFILES_DIR / "infra-snapshot.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return (0, 0)
        gpu = data.get("gpu") or {}
        return (int(gpu.get("used_mb", 0)), int(gpu.get("total_mb", 0)))


# Phase 6a-i.B perception-state bridge. Reads the daimonion-side
# perception-state.json (atomic write-then-rename by
# ``agents.hapax_daimonion._perception_state_writer``) for the
# OperatorActivityEngine signal stream. Wires ``keyboard_active``
# (#1389) + ``desk_active`` (this PR). Remaining 3 activity signals
# (midi_clock_active, desktop_focus_changed_recent, watch_movement)
# wire in follow-up PRs as their adapter contracts land.
#
# Missing/stale file → ``None`` from every accessor, which the engine
# treats as "skip this signal" (no positive nor negative evidence) per
# the ``ClaimEngine.tick`` contract — the alternative (assume idle on
# missing file) would let a daimonion crash spuriously decay the
# posterior to IDLE.
class LogosPerceptionStateBridge:
    """Bridge perception-state.json → activity-signal Protocol for OAE."""

    # ``desk_activity`` is a string enum from the contact-mic DSP
    # gesture classifier. Anything other than these idle states counts
    # as engaged-with-the-desk activity. Centralised so the mapping is
    # reviewable in one place when tuning later.
    _DESK_IDLE_STATES: frozenset[str] = frozenset({"idle", "none"})

    def _load(self) -> dict | None:
        import json
        from pathlib import Path

        path = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def keyboard_active(self) -> bool | None:
        data = self._load()
        if data is None or "keyboard_active" not in data:
            return None
        return bool(data["keyboard_active"])

    def desk_active(self) -> bool | None:
        data = self._load()
        if data is None or "desk_activity" not in data:
            return None
        activity = str(data["desk_activity"]).lower()
        return activity not in self._DESK_IDLE_STATES


# Phase 6b-i.B partial wire-in. Bridge contract for the four
# mood-arousal signals (``ambient_audio_rms_high``,
# ``contact_mic_onset_rate_high``, ``midi_clock_bpm_high``,
# ``hr_bpm_above_baseline``) defined in
# ``mood_arousal_engine.DEFAULT_SIGNAL_WEIGHTS``. Per-signal sources
# live in heterogeneous backends — ambient_audio.py / contact_mic.py /
# midi_clock.py / health.py — each with its own quantile or baseline
# threshold semantics. Part 1 (this PR) ships the protocol-matching
# bridge with all accessors returning ``None`` so the engine math runs
# cleanly with no live signal contribution. Subsequent PRs wire each
# threshold reference as the per-backend quantile / baseline references
# stabilise — same additive pattern delta used in #1389 and beta used
# across #1379 + #1377.
class LogosStimmungBridge:
    """Bridge stimmung-derived signals → MoodArousalEngine signal Protocol."""

    def ambient_audio_rms_high(self) -> bool | None:
        return None

    def contact_mic_onset_rate_high(self) -> bool | None:
        return None

    def midi_clock_bpm_high(self) -> bool | None:
        return None

    def hr_bpm_above_baseline(self) -> bool | None:
        return None


# Phase 6b-ii.B partial wire-in. Bridge contract for the four
# mood-valence signals (``hrv_below_baseline``, ``skin_temp_drop``,
# ``sleep_debt_high``, ``voice_pitch_elevated``) defined in
# ``mood_valence_engine.DEFAULT_SIGNAL_WEIGHTS``. Per-signal sources
# live in heterogeneous backends — health.py (Pixel Watch HRV /
# skin temp / sleep) + voice-side speech analysis (pitch baseline).
# Part 1 (this PR) ships the protocol-matching bridge with all
# accessors returning ``None`` so the engine math runs cleanly with
# no live signal contribution. Subsequent PRs wire each threshold
# reference as the per-backend baseline references stabilise — same
# additive pattern delta used in #1389 and alpha used in #1392.
class LogosMoodValenceBridge:
    """Bridge health/voice signals → MoodValenceEngine signal Protocol."""

    def hrv_below_baseline(self) -> bool | None:
        return None

    def skin_temp_drop(self) -> bool | None:
        return None

    def sleep_debt_high(self) -> bool | None:
        return None

    def voice_pitch_elevated(self) -> bool | None:
        return None


# Phase 6b-iii.B partial wire-in. Bridge contract for the four
# mood-coherence (low-tier) signals (``hrv_variability_high``,
# ``respiration_irregular``, ``movement_jitter_high``,
# ``skin_temp_volatility_high``) defined in
# ``mood_coherence_engine.DEFAULT_SIGNAL_WEIGHTS``. Per-signal sources
# live in heterogeneous backends — mostly Pixel Watch volatility/
# variance metrics in health.py. Part 1 (this PR) ships the protocol-
# matching bridge with all accessors returning ``None`` so the engine
# math runs cleanly with no live signal contribution. Subsequent PRs
# wire each threshold reference as the per-backend volatility windows
# stabilise — same additive pattern alpha used in #1392 / #1399 and
# delta used in #1389.
class LogosMoodCoherenceBridge:
    """Bridge health-volatility signals → MoodCoherenceEngine signal Protocol."""

    def hrv_variability_high(self) -> bool | None:
        return None

    def respiration_irregular(self) -> bool | None:
        return None

    def movement_jitter_high(self) -> bool | None:
        return None

    def skin_temp_volatility_high(self) -> bool | None:
        return None


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

    # Phase 6d-i.B wire-in: SystemDegradedEngine observes (1) the
    # ReactiveEngine watcher's consumer-queue depth and (2) the drift
    # detector's high-severity item count (post-#1379) and exposes a
    # Bayesian posterior for downstream consumers (DMN governor,
    # narration cadence, recruitment pipeline). Sourced from #1357
    # (engine + signal contract) + #1362 (queue-depth adapter) +
    # #1377 (drift / gpu / director adapters). Remaining 2 signals
    # (gpu / director_cadence) wire in subsequent PRs as their
    # production sources land daimonion-side.
    sde = None
    if engine is not None:
        try:
            from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine

            sde = SystemDegradedEngine()
            app.state.system_degraded_engine = sde
        except Exception:
            _log.exception("SystemDegradedEngine wire-in failed (continuing without it)")

    # Phase 6a-i.B partial wire-in: OperatorActivityEngine observes the
    # daimonion-side perception-state.json (currently keyboard_active
    # only; midi_clock_active / desk_active / focus_changed /
    # watch_movement wire in follow-up PRs as their adapters land).
    # The engine math + signal contract shipped in #1375; this PR
    # activates the live consumer. Posterior + state are exposed at
    # GET /api/engine/operator_activity for the DMN governor + future
    # narration-cadence consumers.
    oae = None
    try:
        from agents.hapax_daimonion.operator_activity_engine import OperatorActivityEngine

        oae = OperatorActivityEngine()
        app.state.operator_activity_engine = oae
    except Exception:
        _log.exception("OperatorActivityEngine wire-in failed (continuing without it)")

    # Phase 6b-i.B partial wire-in: MoodArousalEngine observes the four
    # stimmung-derived arousal signals (ambient room mic RMS, contact mic
    # onset rate, MIDI clock BPM, watch HR vs baseline). Engine math +
    # signal contract shipped in #1368; this PR activates the live
    # consumer + adapter contract. All four signal accessors return
    # ``None`` from LogosStimmungBridge until per-backend quantile /
    # baseline references stabilise — same additive pattern delta used
    # for OAE in #1389. Posterior + state will be exposed at
    # GET /api/engine/mood_arousal in a follow-up route PR for the DMN
    # governor + future stimmung-routing consumers.
    mae = None
    try:
        from agents.hapax_daimonion.mood_arousal_engine import MoodArousalEngine

        mae = MoodArousalEngine()
        app.state.mood_arousal_engine = mae
    except Exception:
        _log.exception("MoodArousalEngine wire-in failed (continuing without it)")

    # Phase 6b-ii.B partial wire-in: MoodValenceEngine observes the four
    # health/voice valence signals (HRV vs baseline, skin temp drop,
    # sleep debt, voice pitch elevated). Engine math + signal contract
    # shipped in #1371; this PR activates the live consumer + adapter
    # contract. All four signal accessors return ``None`` from
    # LogosMoodValenceBridge until per-backend baseline references
    # stabilise — same additive pattern alpha used for MAE in #1392 and
    # delta used for OAE in #1389.
    mve = None
    try:
        from agents.hapax_daimonion.mood_valence_engine import MoodValenceEngine

        mve = MoodValenceEngine()
        app.state.mood_valence_engine = mve
    except Exception:
        _log.exception("MoodValenceEngine wire-in failed (continuing without it)")

    # Phase 6b-iii.B partial wire-in: MoodCoherenceEngine observes the
    # four health-volatility coherence signals (HRV CV, respiration
    # variance, movement jitter, skin temp volatility). Engine math +
    # signal contract shipped in #1374; this PR activates the live
    # consumer + adapter contract. All four signal accessors return
    # ``None`` from LogosMoodCoherenceBridge until per-backend
    # volatility windows stabilise — same additive pattern alpha used
    # for MAE in #1392 and MVE in #1399.
    mce = None
    try:
        from agents.hapax_daimonion.mood_coherence_engine import MoodCoherenceEngine

        mce = MoodCoherenceEngine()
        app.state.mood_coherence_engine = mce
    except Exception:
        _log.exception("MoodCoherenceEngine wire-in failed (continuing without it)")

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

    async def _system_degraded_tick_loop():
        """1s-cadence tick — observes queue depth + drift + gpu pressure + contributes."""
        from agents.hapax_daimonion.backends.drift_significant import (
            drift_significant_observation,
        )
        from agents.hapax_daimonion.backends.engine_queue_depth import (
            queue_depth_observation,
        )
        from agents.hapax_daimonion.backends.gpu_pressure import (
            gpu_pressure_observation,
        )

        drift_bridge = LogosDriftBridge()
        gpu_bridge = LogosGpuBridge()

        while True:
            try:
                if engine is not None and sde is not None:
                    obs: dict[str, bool | None] = {}
                    obs.update(queue_depth_observation(engine.watcher))
                    obs.update(drift_significant_observation(drift_bridge))
                    obs.update(gpu_pressure_observation(gpu_bridge))
                    sde.contribute(obs)
            except Exception:
                _log.debug("SystemDegradedEngine tick failed", exc_info=True)
            await asyncio.sleep(1.0)

    async def _operator_activity_tick_loop():
        """1s-cadence tick — observes keyboard_active + contributes to OAE."""
        from agents.hapax_daimonion.backends.operator_activity_observation import (
            operator_activity_observation,
        )

        perception_bridge = LogosPerceptionStateBridge()

        while True:
            try:
                if oae is not None:
                    oae.contribute(operator_activity_observation(perception_bridge))
            except Exception:
                _log.debug("OperatorActivityEngine tick failed", exc_info=True)
            await asyncio.sleep(1.0)

    async def _mood_arousal_tick_loop():
        """1s-cadence tick — observes 4 mood-arousal signals + contributes to MAE."""
        from agents.hapax_daimonion.backends.mood_arousal_observation import (
            mood_arousal_observation,
        )

        stimmung_bridge = LogosStimmungBridge()

        while True:
            try:
                if mae is not None:
                    mae.contribute(mood_arousal_observation(stimmung_bridge))
            except Exception:
                _log.debug("MoodArousalEngine tick failed", exc_info=True)
            await asyncio.sleep(1.0)

    async def _mood_valence_tick_loop():
        """1s-cadence tick — observes 4 mood-valence signals + contributes to MVE."""
        from agents.hapax_daimonion.backends.mood_valence_observation import (
            mood_valence_observation,
        )

        valence_bridge = LogosMoodValenceBridge()

        while True:
            try:
                if mve is not None:
                    mve.contribute(mood_valence_observation(valence_bridge))
            except Exception:
                _log.debug("MoodValenceEngine tick failed", exc_info=True)
            await asyncio.sleep(1.0)

    async def _mood_coherence_tick_loop():
        """1s-cadence tick — observes 4 mood-coherence signals + contributes to MCE."""
        from agents.hapax_daimonion.backends.mood_coherence_observation import (
            mood_coherence_observation,
        )

        coherence_bridge = LogosMoodCoherenceBridge()

        while True:
            try:
                if mce is not None:
                    mce.contribute(mood_coherence_observation(coherence_bridge))
            except Exception:
                _log.debug("MoodCoherenceEngine tick failed", exc_info=True)
            await asyncio.sleep(1.0)

    _sampler_task = asyncio.create_task(run_sampler())
    _trim_task = asyncio.create_task(_chronicle_trim_loop())
    _sde_task = asyncio.create_task(_system_degraded_tick_loop()) if sde is not None else None
    _oae_task = asyncio.create_task(_operator_activity_tick_loop()) if oae is not None else None
    _mae_task = asyncio.create_task(_mood_arousal_tick_loop()) if mae is not None else None
    _mve_task = asyncio.create_task(_mood_valence_tick_loop()) if mve is not None else None
    _mce_task = asyncio.create_task(_mood_coherence_tick_loop()) if mce is not None else None

    yield

    _sampler_task.cancel()
    _trim_task.cancel()
    if _sde_task is not None:
        _sde_task.cancel()
    if _oae_task is not None:
        _oae_task.cancel()
    if _mae_task is not None:
        _mae_task.cancel()
    if _mve_task is not None:
        _mve_task.cancel()
    if _mce_task is not None:
        _mce_task.cancel()
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
from logos.api.routes.cbip import router as cbip_router
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
from logos.api.routes.predictions import router as predictions_router
from logos.api.routes.profile import router as profile_router
from logos.api.routes.query import router as query_router
from logos.api.routes.scout import router as scout_router
from logos.api.routes.sprint import router as sprint_router
from logos.api.routes.stimmung import router as stimmung_router
from logos.api.routes.stream import router as stream_router
from logos.api.routes.studio import router as studio_router
from logos.api.routes.studio_compositor import router as studio_compositor_router
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
app.include_router(studio_compositor_router)
app.include_router(cbip_router)
app.include_router(logos_router)
app.include_router(flow_router)
app.include_router(fortress_router)
app.include_router(pi_router)
app.include_router(sprint_router)
app.include_router(stimmung_router)
app.include_router(stream_router)
app.include_router(dmn_router)
app.include_router(events_router)
app.include_router(exploration_router)
app.include_router(orientation_router)
app.include_router(vault_router)
app.include_router(chronicle_router)
app.include_router(predictions_router)

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
