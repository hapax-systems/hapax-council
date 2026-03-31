"""VisualLayerAggregator — polls logos API and perception state, writes output.

This is the core class. Stimmung/biometric and experiential learning
methods are in stimmung_mixin.py and experiential_mixin.py respectively.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import httpx

from agents._active_correction import CorrectionSeeker
from agents._apperception_tick import ApperceptionTick
from agents._correction_memory import CorrectionStore
from agents._episodic_memory import EpisodeBuilder, EpisodeStore
from agents._stimmung import StimmungCollector, SystemStimmung
from agents._telemetry import (
    hapax_interaction,
    trace_api_poll,
    trace_phone_signals,
    trace_prediction_tick,
    trace_visual_tick,
)
from agents.content_scheduler import (
    ContentPools,
    ContentScheduler,
    ContentSource,
    SchedulerContext,
    SchedulerDecision,
)
from agents.predictive_cache import PredictiveCache
from agents.protention_engine import ProtentionEngine
from agents.temporal_bands import TemporalBandFormatter
from agents.temporal_filter import ClassificationFilter
from agents.temporal_scales import MultiScaleAggregator
from agents.visual_layer_state import (
    AmbientParams,
    BiometricState,
    ClassificationDetection,
    DisplayStateMachine,
    EnvironmentalColor,
    InjectedFeed,
    SignalCategory,
    SignalEntry,
    SignalStaleness,
    SupplementaryContent,
    TemporalContext,
    VisualLayerState,
    VoiceSessionState,
    WatershedEvent,
)

from .constants import (
    AMBIENT_CONTENT_INTERVAL_S,
    CAMERA_FILTERS,
    CAMERA_ROLES,
    HEALTH_POLL_S,
    LOGOS_BASE,
    OUTPUT_DIR,
    OUTPUT_FILE,
    PERCEPTION_STATE_PATH,
    SLOW_POLL_S,
    STATE_TICK_BASE_S,
    WATERSHED_FILE,
)
from .signal_mappers import (
    _map_scene_inventory,
    _persist_minute,
    map_biometrics,
    map_briefing,
    map_copilot,
    map_drift,
    map_goals,
    map_gpu,
    map_health,
    map_nudges,
    map_perception,
    map_phone,
    map_stimmung,
    map_voice_content,
    map_voice_session,
    time_of_day_warmth_offset,
)

log = logging.getLogger("visual_layer_aggregator")


class VisualLayerAggregator:
    """Polls logos API and perception state, runs state machine, writes output."""

    def __init__(self) -> None:
        self._sm = DisplayStateMachine()
        self._client = httpx.AsyncClient(base_url=LOGOS_BASE, timeout=5.0)
        self._fast_signals: list[SignalEntry] = []
        self._slow_signals: list[SignalEntry] = []
        self._perception_signals: list[SignalEntry] = []
        self._voice_signals: list[SignalEntry] = []
        self._phone_signals: list[SignalEntry] = []
        self._flow_score: float = 0.0
        self._audio_energy: float = 0.0
        self._production_active: bool = False

        # Voice session + content state
        self._voice_session = VoiceSessionState()
        self._voice_content: list[SupplementaryContent] = []
        self._biometrics = BiometricState()

        # Classification detection overlay
        self._classification_detections: list[ClassificationDetection] = []
        self._entity_filters: dict[str, ClassificationFilter] = {}

        # Content scheduler
        self._scheduler = ContentScheduler()
        self._ambient_text: str = ""
        self._secondary_ambient_text: str = ""
        self._ambient_facts: list[str] = []
        self._nudge_titles: list[str] = []
        self._ambient_moments: list[str] = []
        self._last_ambient_fetch: float = -300.0
        self._injected_feeds: list[InjectedFeed] = []

        # Staleness tracking
        self._ts_perception: float = 0.0
        self._ts_health: float = 0.0
        self._ts_gpu: float = 0.0
        self._ts_nudges: float = 0.0
        self._ts_briefing: float = 0.0

        # Adaptive cadence state
        self._prev_display_state: str = "ambient"
        self._last_perception_data: dict[str, object] = {}
        self._ambient_fetch_done: bool = False
        self._epoch: int = 0

        # Stimmung: system self-state
        self._stimmung_collector = StimmungCollector()
        self._stimmung: SystemStimmung | None = None
        self._grounding_ledger = None

        # Protention engine: statistical transition predictions
        self._protention = ProtentionEngine()
        self._protention.load()
        self._last_protention_save: float = 0.0

        # Predictive cache: pre-computed visual states
        self._predictive_cache = PredictiveCache()

        # Multi-scale temporal aggregator
        self._multi_scale = MultiScaleAggregator()
        self._temporal_formatter = TemporalBandFormatter(protention_engine=self._protention)

        # Local perception ring
        from agents.hapax_daimonion.perception_ring import PerceptionRing

        self._local_ring = PerceptionRing(maxlen=20)

        # WS3: experiential learning pipeline
        self._episode_builder = EpisodeBuilder()
        self._episode_store: EpisodeStore | None = None
        self._correction_store: CorrectionStore | None = None
        self._correction_seeker = CorrectionSeeker()
        self._pattern_store = None
        self._active_patterns: list = []
        self._last_pattern_query_ts: float = 0.0
        self._last_pattern_activity: str = ""
        self._ws3_initialized = False
        self._ws3_retries: int = 0
        self._ws3_last_attempt: float = 0.0

        # Self-band: apperception tick
        self._apperception = ApperceptionTick()

        # BOCPD: change-point detection
        from agents.bocpd import MultiSignalBOCPD

        self._bocpd = MultiSignalBOCPD(
            signals=["flow_score", "audio_energy", "heart_rate"],
            hazard_lambda=30,
            threshold=0.2,
        )
        self._last_change_points: list[dict] = []

    async def _fetch_json(self, path: str) -> dict | list | None:
        """Fetch a logos API endpoint. Returns None on any error."""
        t0 = time.monotonic()
        try:
            resp = await self._client.get(path)
            latency_ms = (time.monotonic() - t0) * 1000
            if resp.status_code == 200:
                trace_api_poll(path, latency_ms, success=True, status_code=200)
                return resp.json()
            trace_api_poll(path, latency_ms, success=False, status_code=resp.status_code)
        except Exception:
            latency_ms = (time.monotonic() - t0) * 1000
            trace_api_poll(path, latency_ms, success=False)
            log.debug("Failed to fetch %s", path, exc_info=True)
        return None

    def set_grounding_ledger(self, ledger) -> None:
        """Register the voice grounding ledger for stimmung integration."""
        self._grounding_ledger = ledger

    # ── Polling methods ──────────────────────────────────────────────────────

    async def poll_fast(self) -> None:
        """Poll fast-cadence endpoints (health, GPU)."""
        signals: list[SignalEntry] = []
        now = time.monotonic()

        health = await self._fetch_json("/health")
        if isinstance(health, dict):
            signals.extend(map_health(health))
            self._ts_health = now

        gpu = await self._fetch_json("/gpu")
        if isinstance(gpu, dict):
            signals.extend(map_gpu(gpu))
            self._ts_gpu = now

        try:
            dl_path = Path.home() / ".cache" / "rag-ingest" / "dead-letter.jsonl"
            if dl_path.exists():
                dl_count = sum(1 for line in dl_path.read_text().splitlines() if line.strip())
                if dl_count > 0:
                    signals.append(
                        SignalEntry(
                            category=SignalCategory.HEALTH_INFRA,
                            severity=0.6,
                            title=f"{dl_count} dead-letter file{'s' if dl_count != 1 else ''}",
                            detail="Permanently failed RAG ingestion",
                            source_id="ingest-dead-letter",
                        )
                    )
        except OSError:
            pass

        self._fast_signals = signals

    async def poll_slow(self) -> None:
        """Poll slow-cadence endpoints (nudges, briefing, drift, goals, copilot)."""
        signals: list[SignalEntry] = []
        now = time.monotonic()

        nudges = await self._fetch_json("/nudges")
        if isinstance(nudges, list):
            signals.extend(map_nudges(nudges))
            self._ts_nudges = now

        briefing = await self._fetch_json("/briefing")
        if isinstance(briefing, dict):
            signals.extend(map_briefing(briefing))
            self._ts_briefing = now

        drift = await self._fetch_json("/drift")
        if isinstance(drift, dict):
            signals.extend(map_drift(drift))

        goals = await self._fetch_json("/goals")
        if isinstance(goals, dict):
            signals.extend(map_goals(goals))

        copilot = await self._fetch_json("/copilot")
        if isinstance(copilot, dict):
            signals.extend(map_copilot(copilot))

        self._slow_signals = signals

    def poll_perception(self) -> None:
        """Read perception-state.json (local file, no HTTP)."""
        try:
            data = json.loads(PERCEPTION_STATE_PATH.read_text())
            signals, flow, audio, prod = map_perception(data)
            self._perception_signals = signals
            self._flow_score = flow
            self._audio_energy = audio
            self._production_active = prod
            self._ts_perception = time.monotonic()
            self._last_perception_data = data
            self._local_ring.push(data)

            voice_signals, voice_state = map_voice_session(data)
            self._voice_signals = voice_signals
            self._voice_session = voice_state
            self._voice_content = map_voice_content(data)
            self._biometrics = map_biometrics(data)
            self._phone_signals = map_phone(data)

            if self._phone_signals or data.get("phone_kde_connected"):
                trace_phone_signals(
                    signal_count=len(self._phone_signals),
                    battery_pct=data.get("phone_battery_pct", 0),
                    connected=data.get("phone_kde_connected", False),
                    signals=[s.title for s in self._phone_signals],
                )

            genre = data.get("music_genre", "")
            if genre and not self._secondary_ambient_text:
                self._secondary_ambient_text = genre

            llm_act = data.get("llm_activity", "")
            llm_conf = float(data.get("llm_confidence", 0.0))
            prod_act = data.get("production_activity", "")
            if llm_act and llm_act != "idle" and llm_conf >= 0.5:
                if not prod_act or prod_act == "idle":
                    self._secondary_ambient_text = f"{llm_act} (LLM {llm_conf:.0%})"

            if (
                llm_act
                and prod_act
                and llm_act != "idle"
                and prod_act != "idle"
                and llm_conf >= 0.5
            ):
                llm_norm = llm_act.replace("_", " ").lower()
                prod_norm = prod_act.replace("_", " ").lower()
                if llm_norm != prod_norm and not llm_norm.startswith(prod_norm):
                    self._perception_signals.append(
                        SignalEntry(
                            category=SignalCategory.PROFILE_STATE,
                            severity=0.1,
                            title=f"Activity: {prod_act} vs {llm_act}",
                            detail=f"CLAP={prod_act}, LLM={llm_act} ({llm_conf:.0%})",
                            source_id="model-disagreement",
                        )
                    )

            if data.get("phone_media_playing"):
                title = data.get("phone_media_title", "")
                artist = data.get("phone_media_artist", "")
                if title:
                    media_text = f"Now playing: {title}" + (f" -- {artist}" if artist else "")
                    self._ambient_moments = [
                        m for m in self._ambient_moments if not m.startswith("Now playing:")
                    ]
                    self._ambient_moments.append(media_text)

            raw_detections = _map_scene_inventory(data)
            self._classification_detections = self._apply_stability_filter(raw_detections)

            bocpd_cps = self._bocpd.update(
                {
                    "flow_score": self._flow_score,
                    "audio_energy": self._audio_energy,
                    "heart_rate": float(self._biometrics.heart_rate_bpm),
                },
                timestamp=time.time(),
            )
            if bocpd_cps:
                self._last_change_points = [
                    {
                        "signal": cp.signal_name,
                        "probability": cp.probability,
                        "timestamp": cp.timestamp,
                        "run_length": cp.run_length_before,
                    }
                    for cp in bocpd_cps
                ]
                log.info(
                    "Change points detected: %s",
                    ", ".join(f"{cp.signal_name}(p={cp.probability:.2f})" for cp in bocpd_cps),
                )

            minute = self._multi_scale.tick(data)
            if minute is not None:
                _persist_minute(minute)

            best_activity = data.get("production_activity", "")
            if not best_activity:
                la = data.get("llm_activity", "")
                if la and la != "idle":
                    best_activity = la
            self._protention.observe(
                activity=best_activity,
                flow_score=data.get("flow_score", 0.0),
                hour=datetime.now().hour,
            )

            self._tick_experiential(data)

        except (FileNotFoundError, json.JSONDecodeError):
            pass

    async def poll_ambient_content(self) -> None:
        """Fetch ambient content from logos API."""
        now = time.monotonic()
        if now - self._last_ambient_fetch < 300.0:
            return
        self._last_ambient_fetch = now

        data = await self._fetch_json("/studio/ambient-content")
        if isinstance(data, dict):
            facts = data.get("facts", [])
            if facts:
                self._ambient_facts = facts
            moments = data.get("moments", [])
            if moments:
                self._ambient_moments = moments
            nudge_titles = data.get("nudge_titles", [])
            if nudge_titles:
                self._nudge_titles = nudge_titles
        self._ambient_fetch_done = True

    async def poll_hls_segments(self) -> None:
        """Analyze recent HLS segments for temporal action + motion energy."""
        hls_dir = Path.home() / ".cache" / "hapax-compositor" / "hls"
        playlist = hls_dir / "stream.m3u8"
        if not playlist.exists():
            return

        try:
            segments = sorted(hls_dir.glob("segment*.ts"), key=lambda p: p.stat().st_mtime)
            if not segments:
                return

            newest = segments[-1]
            last_processed = getattr(self, "_last_hls_segment", "")
            if newest.name == last_processed:
                return
            self._last_hls_segment = newest.name

            from agents.models.hls_decoder import compute_motion_energy, decode_segment

            frames = decode_segment(newest, max_frames=10)
            if not frames:
                return

            motion_energy = compute_motion_energy(frames)

            action_label = "unknown"
            try:
                from agents.models.movinet import MoViNetA2

                if not hasattr(self, "_hls_movinet"):
                    self._hls_movinet = MoViNetA2()
                for frame in frames:
                    action_label = self._hls_movinet.predict(frame)
            except Exception:
                pass

            analysis = {
                "segment": newest.name,
                "motion_energy": round(motion_energy, 4),
                "action": action_label,
                "timestamp": time.time(),
            }
            out_path = Path("/dev/shm/hapax-compositor/hls-analysis.json")
            tmp = out_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(analysis))
            tmp.rename(out_path)

            if hasattr(self, "_bocpd"):
                self._bocpd.update(
                    {"hls_motion": motion_energy},
                    timestamp=time.time(),
                )

        except Exception:
            log.debug("HLS segment analysis failed", exc_info=True)

    # ── WS3: Experiential learning ───────────────────────────────────────────
    # Imported from experiential_mixin to keep this file focused

    _WS3_RETRY_INTERVAL_S = 60.0
    _WS3_MAX_RETRIES = 5

    def _init_ws3(self) -> None:
        """Lazy-init WS3 stores with bounded retry on failure."""
        if self._ws3_initialized:
            return
        if self._ws3_retries >= self._WS3_MAX_RETRIES:
            return
        now = time.monotonic()
        if now - self._ws3_last_attempt < self._WS3_RETRY_INTERVAL_S:
            return
        self._ws3_last_attempt = now
        self._ws3_retries += 1
        try:
            from agents._correction_memory import CorrectionStore as _CS
            from agents._episodic_memory import EpisodeStore as _ES

            self._correction_store = _CS()
            self._correction_store.ensure_collection()
            self._episode_store = _ES()
            self._episode_store.ensure_collection()
        except Exception:
            log.warning(
                "WS3 stores unavailable (attempt %d/%d)",
                self._ws3_retries,
                self._WS3_MAX_RETRIES,
                exc_info=True,
            )
            self._correction_store = None
            self._episode_store = None
            return
        try:
            from agents._pattern_consolidation import PatternStore

            self._pattern_store = PatternStore()
            self._pattern_store.ensure_collection()
        except Exception:
            log.debug("PatternStore unavailable", exc_info=True)
            self._pattern_store = None
        self._ws3_initialized = True

    def _tick_experiential(self, data: dict) -> None:
        """Feed perception data to the WS3 experiential pipeline."""
        from agents._correction_memory import check_for_corrections
        from agents._telemetry import trace_episode_closed

        self._init_ws3()

        if self._episode_store is not None:
            try:
                episode = self._episode_builder.observe(data)
                if episode is not None:
                    self._episode_store.record(episode)
                    log.info(
                        "Episode recorded: %s (%.0fs, %d snapshots)",
                        episode.activity,
                        episode.duration_s,
                        episode.snapshot_count,
                    )
                    trace_episode_closed(
                        activity=episode.activity,
                        duration_s=episode.duration_s,
                        flow_state=episode.flow_state,
                        snapshot_count=episode.snapshot_count,
                    )
                    dur_label = (
                        f"{episode.duration_s / 3600:.1f}h"
                        if episode.duration_s >= 3600
                        else f"{episode.duration_s / 60:.0f}m"
                        if episode.duration_s >= 60
                        else f"{episode.duration_s:.0f}s"
                    )
                    self._perception_signals.append(
                        SignalEntry(
                            category=SignalCategory.PROFILE_STATE,
                            severity=0.15,
                            title=f"{episode.activity} . {dur_label} . flow {episode.flow_state}",
                            detail=f"Episode closed ({episode.snapshot_count} snapshots)",
                            source_id="episode-boundary",
                        )
                    )
            except Exception:
                log.debug("Episode recording failed", exc_info=True)

        if self._correction_store is not None:
            try:
                check_for_corrections(self._correction_store, data)
            except Exception:
                log.debug("Correction intake failed", exc_info=True)

        if self._correction_store is not None:
            try:
                stimmung_stance = (
                    self._stimmung.overall_stance.value if self._stimmung else "nominal"
                )
                confidence = data.get("aggregate_confidence", 1.0)
                self._correction_seeker.evaluate(
                    activity=data.get("production_activity", ""),
                    flow_score=data.get("flow_score", 0.0),
                    confidence=float(confidence),
                    hour=datetime.now().hour,
                    stimmung_stance=stimmung_stance,
                    correction_store=self._correction_store,
                )
            except Exception:
                log.debug("Active correction seeking failed", exc_info=True)

        if self._pattern_store is not None:
            try:
                activity = data.get("production_activity", "")
                now = time.monotonic()
                activity_changed = activity != self._last_pattern_activity
                cooldown_elapsed = (now - self._last_pattern_query_ts) > 60.0
                if activity_changed or cooldown_elapsed:
                    self._last_pattern_query_ts = now
                    self._last_pattern_activity = activity
                    flow_state = data.get("flow_state", "")
                    hour = datetime.now().hour
                    query = f"activity={activity} flow_state={flow_state} hour={hour}"
                    matches = self._pattern_store.search(query, limit=3, min_score=0.3)
                    self._active_patterns = matches
                    if matches:
                        log.debug(
                            "WS3 patterns: %d matches (top: %.2f -- %s)",
                            len(matches),
                            matches[0].score,
                            matches[0].pattern.prediction[:80],
                        )
                        top = matches[0]
                        self._perception_signals.append(
                            SignalEntry(
                                category=SignalCategory.CONTEXT_TIME,
                                severity=min(0.6, top.pattern.confidence),
                                title=top.pattern.prediction[:60],
                                detail=f"IF {top.pattern.condition[:60]} (conf {top.pattern.confidence:.0%})",
                                source_id="pattern-prediction",
                            )
                        )
            except Exception:
                log.debug("Pattern consultation failed", exc_info=True)

    # ── Stimmung ─────────────────────────────────────────────────────────────

    def _update_stimmung(self) -> None:
        """Collect stimmung readings from all available data sources."""
        from .stimmung_methods import (
            update_stimmung_sources,
            write_stimmung,
            write_temporal_bands,
        )

        update_stimmung_sources(self)  # calls update_biometrics internally
        write_stimmung(self)
        write_temporal_bands(self)

    # ── Content scheduling ───────────────────────────────────────────────────

    def _run_scheduler(self, state: VisualLayerState) -> None:
        """Run the content scheduler and apply its decision."""
        now = time.monotonic()

        self._injected_feeds = [
            f for f in self._injected_feeds if now - f.injected_at < f.duration_s
        ]

        activity_label, _ = self._infer_activity()
        tc = state.temporal_context if state.temporal_context else TemporalContext()
        ctx = SchedulerContext(
            activity=activity_label,
            flow_score=self._flow_score,
            audio_energy=self._audio_energy,
            stress_elevated=self._biometrics.stress_elevated,
            heart_rate=self._biometrics.heart_rate_bpm,
            sleep_quality=self._biometrics.sleep_quality,
            voice_active=self._voice_session.active,
            display_state=state.display_state,
            hour=datetime.now().hour,
            signal_count=sum(len(v) for v in state.signals.values()),
            trend_flow=tc.trend_flow,
            trend_audio=tc.trend_audio,
            perception_age_s=tc.perception_age_s,
            stimmung_stance=self._stimmung.overall_stance.value if self._stimmung else "nominal",
            gaze_direction=self._last_perception_data.get("gaze_direction", "unknown"),
            emotion=self._last_perception_data.get("top_emotion", "neutral"),
            posture=self._last_perception_data.get("posture", "unknown"),
            recent_transition=any(
                time.time() - cp.get("timestamp", 0) < 30.0 for cp in self._last_change_points
            ),
        )

        pools = ContentPools(
            facts=self._ambient_facts,
            moments=self._ambient_moments,
            nudge_titles=self._nudge_titles,
            camera_roles=CAMERA_ROLES,
            camera_filters=CAMERA_FILTERS,
            pool_age_s=now - self._last_ambient_fetch if self._last_ambient_fetch > 0 else 0.0,
        )

        decision = self._scheduler.tick(ctx, pools, now=now)
        if decision:
            self._apply_scheduler_decision(decision, state, now)
            state.scheduler_source = decision.source.value
            state.display_density = self._scheduler._compute_density(ctx).value

    def _apply_scheduler_decision(
        self, decision: SchedulerDecision, state: VisualLayerState, now: float
    ) -> None:
        """Apply a scheduler decision to the visual layer state."""
        if decision.source == ContentSource.PROFILE_FACT and decision.content:
            self._ambient_text = decision.content

        elif decision.source == ContentSource.CAMERA_FEED and decision.camera_role:
            if not self._injected_feeds:
                feed = InjectedFeed(
                    role=decision.camera_role,
                    x=decision.camera_x,
                    y=decision.camera_y,
                    w=decision.camera_w,
                    h=decision.camera_h,
                    opacity=decision.camera_opacity,
                    css_filter=decision.camera_filter,
                    duration_s=decision.dwell_s,
                    injected_at=now,
                )
                self._injected_feeds.append(feed)
                log.debug("Scheduler injected camera: %s", decision.camera_role)

        elif decision.content and decision.source in (
            ContentSource.STUDIO_MOMENT,
            ContentSource.SIGNAL_CARD,
            ContentSource.TIME_OF_DAY,
            ContentSource.SUPPLEMENTARY_CARD,
        ):
            self._ambient_text = decision.content

        elif decision.content and decision.source in (
            ContentSource.ACTIVITY_LABEL,
            ContentSource.BIOMETRIC_MOD,
        ):
            self._secondary_ambient_text = decision.content

        # Apply shader nudge
        nudge = decision.shader_nudge
        state.ambient_params.speed = round(state.ambient_params.speed * nudge.speed_mult, 3)
        state.ambient_params.turbulence = round(
            state.ambient_params.turbulence * nudge.turbulence_mult, 3
        )
        state.ambient_params.color_warmth = round(
            min(1.0, max(0.0, state.ambient_params.color_warmth + nudge.warmth_offset)), 3
        )
        state.ambient_params.brightness = round(
            min(1.0, max(0.0, state.ambient_params.brightness + nudge.brightness_offset)), 3
        )

    # ── Biometric modulation ─────────────────────────────────────────────────

    def _apply_biometric_modulation(self, params: AmbientParams) -> AmbientParams:
        """Modulate ambient params based on biometric state."""
        bio = self._biometrics

        if bio.stress_elevated:
            params.speed = round(params.speed * 0.5, 3)
            params.turbulence = round(params.turbulence * 0.4, 3)
            params.color_warmth = round(min(1.0, params.color_warmth + 0.3), 3)
            params.brightness = round(max(0.12, params.brightness - 0.05), 3)
        elif bio.heart_rate_bpm > 90 and bio.watch_activity not in ("exercise", "workout"):
            params.color_warmth = round(min(1.0, params.color_warmth + 0.2), 3)

        if bio.physiological_load > 0.6:
            params.speed = round(params.speed * 0.4, 3)
            params.turbulence = round(params.turbulence * 0.3, 3)

        if bio.sleep_quality < 0.6:
            params.brightness = round(max(0.10, params.brightness * 0.7), 3)
            params.turbulence = round(params.turbulence * 0.6, 3)

        tod_offset = time_of_day_warmth_offset()
        params.color_warmth = round(min(1.0, max(params.color_warmth, tod_offset)), 3)

        return params

    def _apply_stability_filter(
        self, detections: list[ClassificationDetection]
    ) -> list[ClassificationDetection]:
        """Apply N-of-M hysteresis filter to prevent flickering enrichments."""
        active_ids = {d.entity_id for d in detections}
        stale = [eid for eid in self._entity_filters if eid not in active_ids]
        for eid in stale:
            del self._entity_filters[eid]

        filtered: list[ClassificationDetection] = []
        for det in detections:
            if det.entity_id not in self._entity_filters:
                self._entity_filters[det.entity_id] = ClassificationFilter()

            filt = self._entity_filters[det.entity_id]
            stable = filt.filter(
                gaze_direction=det.gaze_direction,
                emotion=det.emotion,
                posture=det.posture,
                gesture=det.gesture,
                action=det.action,
                mobility=det.mobility,
            )

            filtered.append(
                det.model_copy(
                    update={
                        "gaze_direction": stable.get("gaze_direction"),
                        "emotion": stable.get("emotion"),
                        "posture": stable.get("posture"),
                        "gesture": stable.get("gesture"),
                        "action": stable.get("action"),
                        "mobility": stable.get("mobility") or det.mobility,
                    }
                )
            )

        return filtered

    # ── Activity inference ───────────────────────────────────────────────────

    def _infer_activity(self) -> tuple[str, str]:
        """Infer what the operator is doing from perception state."""
        correction_path = Path("/dev/shm/hapax-compositor/activity-correction.json")
        try:
            correction = json.loads(correction_path.read_text())
            elapsed = time.time() - correction.get("timestamp", 0)
            if elapsed < correction.get("ttl_s", 1800):
                return correction["label"], correction.get("detail", "")
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

        if self._voice_session.active:
            return "talking to hapax", f"turn {self._voice_session.turn_count}"

        perception_data = self._last_perception_data or {}
        production = perception_data.get("production_activity", "")
        music_genre = perception_data.get("music_genre", "")
        flow_state = perception_data.get("flow_state", "idle")

        if production == "coding":
            detail = f"flow: {flow_state}" if flow_state != "idle" else ""
            return "coding", detail
        elif production == "writing":
            return "writing", ""
        elif production == "browsing":
            return "browsing", ""
        elif production == "meeting":
            return "in a meeting", ""
        elif production in ("music_production", "producing"):
            detail = music_genre if music_genre else ""
            return "making music", detail
        elif production == "gaming":
            return "gaming", ""
        elif production:
            return production, ""

        scene_state_clip = perception_data.get("scene_state_clip", "")
        _CLIP_ACTIVITY_MAP = {
            "focused coding": "coding",
            "music production": "making music",
            "video meeting": "in a meeting",
            "reading": "reading",
            "conversation": "in conversation",
        }
        clip_activity = _CLIP_ACTIVITY_MAP.get(scene_state_clip, "")
        if clip_activity:
            return clip_activity, "(CLIP)"

        llm_activity = perception_data.get("llm_activity", "")
        if not production and llm_activity and llm_activity != "idle":
            llm_confidence = perception_data.get("llm_confidence", 0.0)
            if llm_confidence >= 0.5:
                return llm_activity.replace("_", " "), f"(LLM, {llm_confidence:.0%})"

        if music_genre:
            if flow_state == "active":
                return "deep work", music_genre
            return "listening", music_genre

        if flow_state == "active":
            return "deep work", ""
        elif flow_state == "warming":
            return "getting focused", ""

        watch = self._biometrics.watch_activity
        if watch in ("exercise", "workout"):
            return "exercising", ""
        elif watch == "sleeping":
            return "sleeping", ""

        return "present", ""

    # ── Staleness / temporal ─────────────────────────────────────────────────

    def _compute_staleness(self) -> SignalStaleness:
        """Compute per-source staleness from last-update timestamps."""
        now = time.monotonic()
        return SignalStaleness(
            perception_s=round(now - self._ts_perception, 1) if self._ts_perception else 0.0,
            health_s=round(now - self._ts_health, 1) if self._ts_health else 0.0,
            gpu_s=round(now - self._ts_gpu, 1) if self._ts_gpu else 0.0,
            nudges_s=round(now - self._ts_nudges, 1) if self._ts_nudges else 0.0,
            briefing_s=round(now - self._ts_briefing, 1) if self._ts_briefing else 0.0,
        )

    def _compute_temporal_context(self) -> TemporalContext:
        """Build temporal context from the perception ring buffer."""
        try:
            from agents.hapax_daimonion._perception_state_writer import get_perception_ring
        except ImportError:
            return TemporalContext()

        ring = get_perception_ring()
        if ring is None or len(ring) < 2:
            return TemporalContext(
                perception_age_s=round(time.monotonic() - self._ts_perception, 1)
                if self._ts_perception
                else 0.0,
            )

        return TemporalContext(
            trend_flow=round(ring.trend("flow_score", window_s=15.0), 4),
            trend_audio=round(ring.trend("audio_energy_rms", window_s=15.0), 4),
            trend_hr=round(ring.trend("heart_rate_bpm", window_s=20.0), 4),
            perception_age_s=round(time.monotonic() - self._ts_perception, 1)
            if self._ts_perception
            else 0.0,
            ring_depth=len(ring),
        )

    def _adaptive_tick_interval(self, state: VisualLayerState) -> float:
        """Compute adaptive tick interval. Bounded [0.5, 5.0]."""
        interval = STATE_TICK_BASE_S

        if state.display_state != self._prev_display_state:
            return 0.5
        if self._voice_session.active:
            return 1.0

        tc = state.temporal_context
        if abs(tc.trend_flow) > 0.01 or abs(tc.trend_audio) > 0.01:
            return 1.5

        if self._stimmung is not None:
            stance = self._stimmung.overall_stance.value
            if stance == "critical":
                return 5.0
            if stance == "degraded":
                interval = max(interval, 4.0)
            if self._stimmung.resource_pressure.value > 0.7:
                interval = max(interval, 4.0)
            if (
                self._stimmung.error_rate.value > 0.5
                and self._stimmung.error_rate.trend == "rising"
            ):
                interval = min(interval, 1.5)
            if self._stimmung.llm_cost_pressure.value > 0.6:
                interval = max(interval, 3.5)

        if state.display_state == "ambient" and not self._production_active:
            interval = max(interval, 5.0)
        if state.display_density == "presenting":
            interval = max(interval, 4.0)

        tc = state.temporal_context
        if tc.perception_age_s > 10.0:
            interval = max(interval, 5.0)

        return max(0.5, min(5.0, interval))

    # ── Apperception ─────────────────────────────────────────────────────────

    def _tick_apperception(self) -> None:
        self._apperception.tick()

    def _save_apperception_model(self) -> None:
        self._apperception.save_model()

    # ── compute_and_write ────────────────────────────────────────────────────

    def compute_and_write(self) -> VisualLayerState:
        """Run state machine and write output atomically."""
        cache_hit = self._predictive_cache.match(
            flow_score=self._flow_score,
            activity=self._last_perception_data.get("production_activity", ""),
            heart_rate=self._biometrics.heart_rate_bpm,
        )

        all_signals = (
            self._fast_signals
            + self._slow_signals
            + self._perception_signals
            + self._voice_signals
            + self._phone_signals
        )

        stimmung_stance = "nominal"
        if self._stimmung is not None:
            all_signals = all_signals + map_stimmung(self._stimmung)
            stimmung_stance = self._stimmung.overall_stance.value

        staleness = self._compute_staleness()
        self._sm.set_staleness(staleness)

        state = self._sm.tick(
            signals=all_signals,
            flow_score=self._flow_score,
            audio_energy=self._audio_energy,
            production_active=self._production_active,
            stimmung_stance=stimmung_stance,
        )

        self._run_scheduler(state)

        if cache_hit is not None:
            cached = cache_hit.ambient_params
            blend = cache_hit.prediction.probability
            ap = state.ambient_params
            state.ambient_params = AmbientParams(
                speed=round(ap.speed * (1 - blend) + cached.speed * blend, 3),
                turbulence=round(ap.turbulence * (1 - blend) + cached.turbulence * blend, 3),
                color_warmth=round(ap.color_warmth * (1 - blend) + cached.color_warmth * blend, 3),
                brightness=round(ap.brightness * (1 - blend) + cached.brightness * blend, 3),
            )
            total = self._predictive_cache._hits + self._predictive_cache._misses
            if total > 0 and total % 20 == 0:
                log.info(
                    "Predictive cache hit rate: %.0f%% (%d/%d)",
                    self._predictive_cache.hit_rate * 100,
                    self._predictive_cache._hits,
                    total,
                )

        state.ambient_params = self._apply_biometric_modulation(state.ambient_params)

        ambient_brightness = self._last_perception_data.get("ambient_brightness", 0.0)
        color_temperature = self._last_perception_data.get("color_temperature", "unknown")
        if ambient_brightness or color_temperature != "unknown":
            _TEMP_HUE_MAP = {"warm": 15.0, "neutral": 0.0, "cool": -15.0}
            hue_shift = _TEMP_HUE_MAP.get(color_temperature, 0.0)
            source = color_temperature if color_temperature != "unknown" else ""
            lightness_bias = 0.0
            if ambient_brightness:
                lightness_bias = round((ambient_brightness - 0.5) * 0.2, 3)
            state.environmental_color = EnvironmentalColor(
                hue_shift=hue_shift,
                lightness_bias=lightness_bias,
                source=source,
            )

        state.voice_session = self._voice_session
        state.voice_content = self._voice_content
        state.biometrics = self._biometrics
        state.injected_feeds = self._injected_feeds
        state.ambient_text = self._ambient_text
        state.secondary_ambient_text = self._secondary_ambient_text
        state.classification_detections = self._classification_detections

        now_ts = time.time()
        state.recent_change_points = [
            cp for cp in self._last_change_points if now_ts - cp.get("timestamp", 0) < 120.0
        ]

        activity_label, activity_detail = self._infer_activity()
        state.activity_label = activity_label

        if self._flow_score >= 0.3 and self._last_perception_data:
            pd = self._last_perception_data
            contributors = []
            if pd.get("gaze_direction", "") == "screen":
                contributors.append("gaze")
            if pd.get("posture", "") == "upright":
                contributors.append("posture")
            if pd.get("top_emotion", "") in ("neutral", "happy"):
                contributors.append("calm")
            rms = float(pd.get("audio_energy_rms", 0))
            vad = float(pd.get("vad_confidence", 0))
            if rms < 0.05 and vad < 0.3:
                contributors.append("quiet")
            if contributors:
                flow_detail = " + ".join(contributors)
                activity_detail = (
                    f"{activity_detail} . {flow_detail}" if activity_detail else flow_detail
                )

        state.activity_detail = activity_detail
        state.temporal_context = self._compute_temporal_context()
        state.signal_staleness = staleness
        state.stimmung_stance = stimmung_stance

        if not self._last_perception_data:
            state.readiness = "waiting"
        elif not self._ambient_fetch_done:
            state.readiness = "collecting"
        else:
            state.readiness = "ready"

        self._prev_display_state = state.display_state

        protention_snap = self._protention.predict(
            current_activity=self._last_perception_data.get("production_activity", ""),
            flow_score=self._flow_score,
            hour=datetime.now().hour,
        )
        self._predictive_cache.precompute(
            protention=protention_snap,
            current_flow=self._flow_score,
            current_audio=self._audio_energy,
            stimmung_stance=stimmung_stance,
        )

        trace_visual_tick(
            display_state=state.display_state,
            signal_count=sum(len(v) for v in state.signals.values()),
            tick_interval=self._adaptive_tick_interval(state),
            stimmung_stance=stimmung_stance,
            cache_hit=cache_hit is not None,
            scheduler_source=state.scheduler_source,
        )
        trace_prediction_tick(
            predictions=len(protention_snap.predictions),
            cache_hit=cache_hit is not None,
            cache_hit_rate=self._predictive_cache.hit_rate,
        )

        if stimmung_stance in ("degraded", "critical"):
            hapax_interaction(
                "stimmung",
                "visual",
                "ambient_modulation",
                metadata={"stance": stimmung_stance},
            )

        state.watershed_events = self._read_watershed_events()

        try:
            self._epoch += 1
            state.epoch = self._epoch
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            tmp = OUTPUT_FILE.with_suffix(".tmp")
            tmp.write_text(state.model_dump_json(), encoding="utf-8")
            tmp.rename(OUTPUT_FILE)
        except OSError:
            log.debug("Failed to write visual layer state", exc_info=True)

        return state

    def _read_watershed_events(self) -> list[WatershedEvent]:
        """Read and prune watershed events from shared file."""
        try:
            if not WATERSHED_FILE.exists():
                return []
            raw = json.loads(WATERSHED_FILE.read_text())
            now = time.time()
            live: list[WatershedEvent] = []
            for e in raw:
                age = now - e.get("emitted_at", 0)
                ttl = e.get("ttl_s", 30.0)
                if age < ttl:
                    live.append(
                        WatershedEvent(
                            category=e.get("category", "system_state"),
                            severity=e.get("severity", 0.2),
                            title=e.get("title", ""),
                            detail=e.get("detail", ""),
                            emitted_at=e.get("emitted_at", now),
                            ttl_s=ttl,
                        )
                    )
            return live[-10:]
        except (json.JSONDecodeError, OSError, KeyError):
            return []

    # ── Event loops ──────────────────────────────────────────────────────────

    async def _state_tick_loop(self) -> None:
        """Fast state loop: perception -> state machine -> scheduler -> write."""
        tick_interval = STATE_TICK_BASE_S

        while True:
            self.poll_perception()
            state = self.compute_and_write()
            log.debug(
                "Tick %.1fs | %s | signals: %d | flow: %.2f | voice: %s",
                tick_interval,
                state.display_state,
                sum(len(v) for v in state.signals.values()),
                self._flow_score,
                state.voice_session.state if state.voice_session.active else "off",
            )

            try:
                self._tick_apperception()
            except Exception:
                log.debug("Apperception tick failed", exc_info=True)

            tick_interval = self._adaptive_tick_interval(state)
            await asyncio.sleep(tick_interval)

    async def _api_poll_loop(self) -> None:
        """Slow API loop: health/GPU at 15s, slow endpoints at 60s, ambient at 45s."""
        last_health: float = 0.0
        last_slow: float = 0.0
        last_ambient: float = 0.0

        while True:
            now = time.monotonic()

            stimmung_stance = self._stimmung.overall_stance.value if self._stimmung else "nominal"
            health_interval = 5.0 if stimmung_stance in ("degraded", "critical") else HEALTH_POLL_S

            if now - last_health >= health_interval:
                await self.poll_fast()
                engine = await self._fetch_json("/engine/status")
                if isinstance(engine, dict):
                    self._stimmung_collector.update_engine(
                        events_processed=int(engine.get("events_processed", 0)),
                        actions_executed=int(engine.get("actions_executed", 0)),
                        errors=int(engine.get("errors", 0)),
                        uptime_s=float(engine.get("uptime_s", 0)),
                    )
                self._update_stimmung()
                last_health = now

            if now - last_slow >= SLOW_POLL_S:
                await self.poll_slow()
                last_slow = now

            if now - last_ambient >= AMBIENT_CONTENT_INTERVAL_S:
                await self.poll_ambient_content()
                last_ambient = now

            _hls_interval = getattr(self, "_hls_poll_interval", 10.0)
            _last_hls = getattr(self, "_last_hls_poll", 0.0)
            if now - _last_hls >= _hls_interval:
                await self.poll_hls_segments()
                self._last_hls_poll = now

            if now - self._last_protention_save >= 300.0:
                self._protention.save()
                self._last_protention_save = now

            await asyncio.sleep(5.0)

    async def run(self) -> None:
        """Main entry: two concurrent loops."""
        log.info("Visual layer aggregator starting (decoupled fast/slow loops)")
        await asyncio.gather(self._state_tick_loop(), self._api_poll_loop())

    async def close(self) -> None:
        if self._episode_store is not None:
            episode = self._episode_builder.flush()
            if episode is not None:
                try:
                    self._episode_store.record(episode)
                    log.info("Flushed partial episode on shutdown: %s", episode.activity)
                except Exception:
                    log.debug("Failed to flush episode on shutdown", exc_info=True)
        self._protention.save()
        self._save_apperception_model()
        await self._client.aclose()
