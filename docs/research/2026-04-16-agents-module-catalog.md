---
title: agents/ module catalog
date: 2026-04-16
queue_item: '313'
epic: lrr
phase: substrate-scenario-2
status: catalog
---

# agents/ module catalog

Top-level modules and packages in `agents/` grouped by responsibility.

## Summary

| Metric | Count |
|---|---|
| Top-level files | 140 |
| Top-level packages | 84 |
| Total .py files (agents/) | 654 |
| Lines of code (agents/) | 146124 |

## Top-level files

| Module | Lines | Purpose (first docstring line) |
|---|---|---|
| `_active_correction.py` | 215 | Vendored active correction seeking for the agents package. |
| `activity_analyzer.py` | 1011 | activity_analyzer.py — System activity observation via universal telemetry. |
| `_affordance_metrics.py` | 3 | agents/_affordance_metrics.py -- Re-export shim for shared.affordance_metrics. |
| `_affordance_pipeline.py` | 3 | agents/_affordance_pipeline.py -- Re-export shim for shared.affordance_pipeline. |
| `_affordance.py` | 3 | agents/_affordance.py -- Re-export shim for shared.affordance. |
| `_agent_registry.py` | 286 | shared/agent_registry.py — Agent manifest registry. |
| `alignment_tax_meter.py` | 308 | Alignment tax measurement — governance overhead as percentage of total cost. |
| `_apperception.py` | 826 | shared/apperception.py — Self-band architecture for Hapax apperception. |
| `_apperception_shm.py` | 4 | Vendored shim: re-exports shared/apperception_shm.py for agents/. |
| `audio_processor.py` | 1744 | audio_processor.py — Ambient audio processing for RAG pipeline. |
| `av_correlator.py` | 1051 | av_correlator.py — Cross-modal audio/video correlation agent. |
| `_axiom_enforcement.py` | 314 | Vendored axiom enforcement for the agents package. |
| `_axiom_enforcer.py` | 222 | shared/axiom_enforcer.py — Output enforcement for LLM-generated text. |
| `_axiom_pattern_checker.py` | 144 | shared/axiom_pattern_checker.py — Output pattern matching for axiom enforcement. |
| `_axiom_precedents.py` | 359 | Qdrant-backed precedent database for axiom enforcement. |
| `_axiom_registry.py` | 302 | Load axiom definitions from hapaxromana registry. |
| `_axiom_tools.py` | 133 | Decision-time axiom compliance tools for Pydantic AI agents. |
| `bocpd.py` | 279 | Bayesian Online Change Point Detection (Adams & MacKay, 2007). |
| `briefing.py` | 1036 | briefing.py — Daily system briefing generator. |
| `browser_agent.py` | 163 | agents/browser_agent.py — Agent for web content interaction. |
| `_browser_services.py` | 58 | Vendored browser services registry for the agents package. |
| `byte_tracker.py` | 228 | ByteTrack multi-object tracker — proper association across frames. |
| `_calendar_context.py` | 99 | Calendar context query interface for Hapax agents. |
| `_cameras.py` | 140 | Vendored camera configuration for the agents package. |
| `_capability.py` | 13 | agents/_capability.py — Re-export shim for shared.capability. |
| `_capacity.py` | 269 | Capacity monitoring and exhaustion forecasting. |
| `chrome_sync.py` | 622 | Chrome RAG sync — browsing history and bookmarks. |
| `_circuit_breaker.py` | 3 | agents/_circuit_breaker.py -- Re-export shim for shared.circuit_breaker. |
| `_clap.py` | 14 | agents/_clap.py — Shim for shared.clap. |
| `claude_code_sync.py` | 631 | Claude Code transcript sync — JSONL transcript parsing for RAG. |
| `_cli.py` | 84 | shared/cli.py -- Common CLI boilerplate for agents. |
| `code_review.py` | 151 | code_review.py — LLM-powered code review agent. |
| `_color_utils.py` | 24 | shared/color_utils.py — Color normalization utilities. |
| `_config.py` | 309 | Vendored config constants for the agents package. |
| `consent_audit.py` | 189 | Historical consent audit — scan for pre-gate person-adjacent data. |
| `_consent_channels.py` | 19 | agents/_consent_channels.py — Shim for shared.governance.consent_channels. |
| `_consent_context.py` | 14 | agents/_consent_context.py — Shim for shared.governance.consent_context. |
| `_consent_gate.py` | 10 | agents/_consent_gate.py — Shim for shared.governance.consent_gate. |
| `_consent_reader.py` | 11 | agents/_consent_reader.py — Shim for shared.governance.consent_reader. |
| `content_scheduler.py` | 744 | Content scheduler — weighted softmax sampler for ambient content decisions. |
| `_context_compression.py` | 11 | agents/_context_compression.py — Re-export shim for shared.context_compression. |
| `_context.py` | 10 | agents/_context.py — Re-export shim for shared.context. |
| `context_restore.py` | 636 | Context restoration — proactive cognitive state recovery after interruption. |
| `_context_tools.py` | 244 | shared/context_tools.py — On-demand operator context tools for Pydantic AI agent |
| `contradiction_detector.py` | 259 | Cross-domain contradiction detection — carrier dynamics in practice. |
| `_correction_memory.py` | 253 | Vendored correction memory for the agents package. |
| `deliberation_eval.py` | 124 | deliberation_eval.py — CLI for deliberation metric extraction and probe evaluati |
| `_deliberation_metrics.py` | 371 | deliberation_metrics.py — Pure metric extraction from deliberation YAML records. |
| `demo_eval.py` | 317 | Demo evaluation agent — generates, evaluates, and iteratively improves demos. |
| `demo_models.py` | 301 | Data models for the demo generator agent. |
| `demo.py` | 1703 | Demo generator agent — produces audience-tailored demos from natural language re |
| `digest.py` | 440 | digest.py — Content digest generator. |
| `_dimensions.py` | 135 | agents/_dimensions.py — Vendored profile dimension registry. |
| `_episodic_memory.py` | 414 | Episodic memory — perception episode store for experiential learning. |
| `_expression.py` | 14 | Vendored shim: re-exports shared.expression for consumer code. |
| `_fix_capabilities.py` | 8 | agents/_fix_capabilities.py — Shim for shared.fix_capabilities. |
| `flow_journal.py` | 188 | Flow journal — persist flow state transitions to RAG for behavioral profiling. |
| `_frontmatter.py` | 87 | agents/_frontmatter.py — Vendored frontmatter parser. |
| `_frontmatter_schemas.py` | 99 | shared/frontmatter_schemas.py — Pydantic schemas for filesystem-as-bus document  |
| `gcalendar_sync.py` | 689 | Google Calendar RAG sync — event indexing and behavioral tracking. |
| `gdrive_sync.py` | 974 | Google Drive RAG sync — smart tiered strategy. |
| `git_sync.py` | 693 | Git commit history RAG sync — local repository commit extraction. |
| `gmail_sync.py` | 739 | Gmail RAG sync — email metadata indexing and behavioral tracking. |
| `_google_auth.py` | 108 | Shared Google OAuth2 credential management. |
| `_governance.py` | 772 | agents/_governance.py — Vendored governance types. |
| `_gpu_semaphore.py` | 81 | Vendored GPU semaphore for the agents package. |
| `_guest_detection.py` | 11 | agents/_guest_detection.py — Shim for shared.governance.guest_detection. |
| `health_connect_parser.py` | 291 | Health Connect SQLite parser — extracts daily summaries from backup ZIPs. |
| `_health_history.py` | 294 | Health history aggregation and retention. |
| `_hyprland.py` | 150 | Vendored Hyprland IPC client for the agents package. |
| `imagination_context.py` | 93 | Imagination context formatter — salience-graded Current Thoughts for conversatio |
| `imagination_loop.py` | 236 | Imagination loop — LLM-driven imagination tick via pydantic-ai. |
| `imagination.py` | 372 | Imagination bus — fragment publishing and escalation to impingement cascade. |
| `imagination_resolver.py` | 280 | Imagination content resolver — rasterizes slow content references to JPEG. |
| `imagination_source_protocol.py` | 133 | Content source protocol writer for imagination fragments. |
| `_impingement_consumer.py` | 3 | agents/_impingement_consumer.py -- Re-export shim for shared.impingement_consume |
| `_impingement.py` | 3 | agents/_impingement.py -- Re-export shim for shared.impingement. |
| `ingest.py` | 800 | ingest.py — RAG document ingestion pipeline. |
| `__init__.py` | 0 |  |
| `introspect.py` | 605 | introspect.py — Live infrastructure manifest generator. |
| `knowledge_maint.py` | 638 | knowledge_maint.py — Knowledge base maintenance agent. |
| `_knowledge_search.py` | 288 | shared/knowledge_search.py — Qdrant semantic search & knowledge artifact reads. |
| `_langfuse_client.py` | 157 | Vendored Langfuse API client for the agents package. |
| `_langfuse_config.py` | 61 | agents/_langfuse_config.py — Wire OpenTelemetry traces to self-hosted Langfuse. |
| `_langfuse_local.py` | 150 | Local Langfuse trace reader — durable consumer-side store. |
| `langfuse_sync.py` | 939 | Langfuse RAG sync — LLM trace summaries and cost tracking. |
| `_log_setup.py` | 85 | Vendored logging setup for the agents package. |
| `notification_capability.py` | 52 | Notification capability — recruited affordance for operator alerting. |
| `_notify.py` | 376 | Vendored notification dispatch for the agents package. |
| `obsidian_sync.py` | 733 | Obsidian vault RAG sync — scan vault, write changed notes with metadata. |
| `_operator.py` | 289 | agents/_operator.py — Vendored operator profile integration. |
| `_ops_db.py` | 267 | Vendored ops database for the agents package. |
| `_ops_live.py` | 157 | shared/ops_live.py — Live infrastructure queries. |
| `_pattern_consolidation.py` | 404 | Pattern consolidation — LLM-driven extraction of if-then rules from episodes. |
| `predictive_cache.py` | 189 | Predictive pre-computation cache for visual layer transitions. |
| `proactive_gate.py` | 67 | Proactive gate — conditions for system-initiated speech. |
| `profiler.py` | 2102 | profiler.py — User profile extraction agent. |
| `profiler_sources.py` | 1370 | profiler_sources.py — Data source discovery, reading, and chunking for the profi |
| `_profile_store.py` | 243 | shared/profile_store.py — Profile fact vector store and digest access. |
| `protention_engine.py` | 431 | Protention engine — statistical transition probability model. |
| `query.py` | 136 | query.py — CLI tool for testing RAG retrieval against Qdrant. |
| `research.py` | 196 | research.py — RAG-enabled research agent using Pydantic AI + LiteLLM + Qdrant. |
| `retroactive_label.py` | 249 | Retroactive person labeling — batch scan Qdrant docs and tag with person_ids. |
| `reverie_prediction_monitor.py` | 782 | Reverie prediction monitor — tracks 7 post-fix behavioral predictions. |
| `_revocation.py` | 12 | agents/_revocation.py — Shim for shared.governance.revocation. |
| `scout.py` | 711 | scout.py — Horizon scanner for external fitness evaluation. |
| `screen_context.py` | 261 | Screen context sync — capture active window context for behavioral profiling. |
| `sdlc_metrics.py` | 464 | SDLC pipeline health metrics — deterministic aggregation. |
| `_sdlc_status.py` | 242 | SDLC pipeline status collector for briefing integration. |
| `_sensor_protocol.py` | 3 | agents/_sensor_protocol.py -- Re-export shim for shared.sensor_protocol. |
| `_service_graph.py` | 94 | Service dependency graph for dependency-aware remediation. |
| `_service_tiers.py` | 85 | Service tier classification for health check prioritization. |
| `sprint_tracker.py` | 580 | Sprint tracker agent — vault-native R&D schedule management. |
| `_stimmung.py` | 20 | Re-export from shared.stimmung — canonical source for stimmung types. |
| `stimmung_sync.py` | 215 | Stimmung sync — persist system self-state history to RAG. |
| `storage_arbiter.py` | 335 | storage_arbiter.py — Orchestrates audio archive value assessment and lifecycle. |
| `studio_person_detector.py` | 123 | Studio Person Detector — lightweight YOLOv8n person detection on camera snapshot |
| `_sufficiency_probes.py` | 1205 | Behavioral sufficiency probes — deterministic checks that the system |
| `_telemetry.py` | 472 | Vendored telemetry for the agents package. |
| `temporal_bands.py` | 319 | Temporal band formatter — retention/impression/protention for LLM context. |
| `temporal_delta.py` | 159 | Temporal delta correlator — derive motion signals from sightings history. |
| `temporal_filter.py` | 104 | Temporal stability filter — hysteresis to prevent flickering classifications. |
| `temporal_models.py` | 76 | Temporal band data models — retention, impression, protention, surprise. |
| `temporal_scales.py` | 407 | Multi-scale temporal hierarchy — minute/session/day summaries. |
| `temporal_surprise.py` | 121 | Surprise computation — compare protention predictions against observed state. |
| `temporal_trend.py` | 108 | Trend-based protention — simple fallback predictions from ring buffer slopes. |
| `temporal_xml.py` | 100 | Temporal bands XML formatter — renders TemporalBands as XML for LLM injection. |
| `_threshold_tuner.py` | 117 | Adaptive threshold tuning for health checks. |
| `_tmp_wav.py` | 69 | Vendored temporary WAV file management for the agents package. |
| `vault_canvas_writer.py` | 122 | Vault canvas writer — generates a JSON Canvas goal dependency map. |
| `vault_context_writer.py` | 211 | Vault context writer — persists working context to the daily note. |
| `_vault_writer.py` | 264 | shared/vault_writer.py — System → Obsidian vault egress. |
| `video_capture.py` | 257 | video_capture.py — Multi-camera video capture service. |
| `video_processor.py` | 1136 | video_processor.py — Video segment classification and retention pipeline. |
| `visual_chain.py` | 258 | Visual chain capability — semantic visual affordances for wgpu shader modulation |
| `visual_layer_state.py` | 624 | Visual communication layer — data models and display state machine. |
| `watch_receiver.py` | 431 | FastAPI sensor receiver — writes atomic JSON files to filesystem-as-bus. |
| `weather_sync.py` | 179 | Weather sync — local weather conditions for energy/mood correlation. |
| `_working_mode.py` | 44 | Vendored working mode reader for the agents package. |
| `youtube_sync.py` | 635 | YouTube RAG sync — subscriptions, likes, and playlists. |

## Packages

| Package | .py files | Purpose |
|---|---|---|
| `activity_analyzer/` | 0 | - |
| `alignment_tax_meter/` | 0 | - |
| `audio_processor/` | 0 | - |
| `av_correlator/` | 0 | - |
| `bocpd/` | 0 | - |
| `briefing/` | 0 | - |
| `browser_agent/` | 0 | - |
| `byte_tracker/` | 0 | - |
| `chrome_sync/` | 0 | - |
| `claude_code_sync/` | 0 | - |
| `code_review/` | 0 | - |
| `consent_audit/` | 0 | - |
| `content_resolver/` | 2 |  |
| `content_scheduler/` | 0 | - |
| `context_restore/` | 0 | - |
| `contradiction_detector/` | 0 | - |
| `deliberation_eval/` | 0 | - |
| `demo/` | 0 | - |
| `demo_eval/` | 0 | - |
| `demo_models/` | 0 | - |
| `demo_pipeline/` | 26 | Demo generation pipeline — screenshots, slides, voice, video, title cards. |
| `dev_story/` | 12 | Dev Story — development archaeology agent. |
| `digest/` | 0 | - |
| `dmn/` | 6 |  |
| `drift_detector/` | 39 | Agent package for drift_detector. |
| `effect_graph/` | 11 | Effect node graph — composable GPU shader pipeline. |
| `flow_journal/` | 0 | - |
| `fortress/` | 38 | Fortress governance agent — Dwarf Fortress forcing function. |
| `gcalendar_sync/` | 0 | - |
| `gdrive_sync/` | 0 | - |
| `git_sync/` | 0 | - |
| `gmail_sync/` | 0 | - |
| `_governance/` | 24 | Governance package — consent, authority, and values as type-level invariants. |
| `hapax_daimonion/` | 184 | Hapax Daimonion — persistent voice interaction daemon. |
| `health_connect_parser/` | 0 | - |
| `health_monitor/` | 35 | health_monitor package -- Deterministic stack health check suite. |
| `imagination/` | 0 | - |
| `imagination_context/` | 0 | - |
| `imagination_daemon/` | 2 |  |
| `imagination_resolver/` | 0 | - |
| `ingest/` | 0 | - |
| `introspect/` | 0 | - |
| `knowledge/` | 2 | Knowledge & Context — semantic search and knowledge artifact query agent. |
| `knowledge_maint/` | 0 | - |
| `langfuse_sync/` | 0 | - |
| `manifests/` | 0 | - |
| `models/` | 7 | Model wrappers for the temporal classification pipeline. |
| `obsidian_sync/` | 0 | - |
| `predictive_cache/` | 0 | - |
| `proactive_gate/` | 0 | - |
| `profiler/` | 0 | - |
| `profiler_sources/` | 0 | - |
| `protention_engine/` | 0 | - |
| `query/` | 0 | - |
| `research/` | 0 | - |
| `retroactive_label/` | 0 | - |
| `reverie/` | 14 | Hapax Reverie — visual actuation daemon. |
| `scout/` | 0 | - |
| `screen_context/` | 0 | - |
| `sdlc_metrics/` | 0 | - |
| `session_conductor/` | 12 | Session Conductor — deterministic sidecar for Claude Code session automation. |
| `shaders/` | 0 | - |
| `sprint_tracker/` | 0 | - |
| `stimmung_sync/` | 0 | - |
| `storage_arbiter/` | 0 | - |
| `studio_compositor/` | 66 | Studio Compositor package — backward-compatible re-exports. |
| `studio_effects/` | 0 | - |
| `studio_fx/` | 23 | Studio FX — independent Python visual effects pipeline. |
| `studio_person_detector/` | 0 | - |
| `studio_stutter/` | 0 | - |
| `system_ops/` | 2 | System Operations — infrastructure health and operational analytics agent. |
| `temporal_bands/` | 0 | - |
| `temporal_delta/` | 0 | - |
| `temporal_filter/` | 0 | - |
| `temporal_scales/` | 0 | - |
| `video_capture/` | 0 | - |
| `video_processor/` | 0 | - |
| `vision_observer/` | 2 |  |
| `visual_chain/` | 0 | - |
| `visual_layer_aggregator/` | 7 | Visual layer signal aggregator package. |
| `visual_layer_state/` | 0 | - |
| `watch_receiver/` | 0 | - |
| `weather_sync/` | 0 | - |
| `youtube_sync/` | 0 | - |
