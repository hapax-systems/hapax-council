---
title: shared/ modules catalog
date: 2026-04-16
queue_item: '316'
epic: lrr
phase: substrate-scenario-2
status: catalog
---

# shared/ modules catalog

## Summary

| Metric | Count |
|---|---|
| .py files | 196 |
| Lines of code | 36263 |
| Packages | 5 |

## Top-level modules

| Module | Lines | First docstring line |
|---|---|---|
| `active_correction.py` | 230 | Active correction seeking — system asks for corrections when uncertain. |
| `affordance_metrics.py` | 258 | Affordance pipeline metrics for validation. |
| `affordance_pipeline.py` | 752 | Unified affordance selection pipeline. |
| `affordance.py` | 100 | Affordance-as-retrieval — relational capability selection models. |
| `affordance_registry.py` | 783 | Centralized affordance registry — Gibson-verb taxonomy for the entire system. |
| `agent_registry.py` | 286 | shared/agent_registry.py — Agent manifest registry. |
| `alert_state.py` | 174 | shared/alert_state.py — Alert state machine for health-watchdog. |
| `apperception.py` | 726 | shared/apperception.py — Self-band architecture for Hapax apperception. |
| `apperception_shm.py` | 82 | Read apperception state from /dev/shm for prompt injection. |
| `apperception_tick.py` | 295 | Apperception tick — standalone self-observation loop. |
| `axiom_audit.py` | 85 | Unified audit finding type for axiom enforcement. |
| `axiom_bindings.py` | 159 | Axiom binding completeness validation (§8.2). |
| `axiom_derivation.py` | 237 | One-shot axiom implication derivation pipeline. |
| `axiom_enforcement.py` | 321 | Framework-agnostic axiom enforcement with hot/cold split. |
| `axiom_enforcer.py` | 222 | shared/axiom_enforcer.py — Output enforcement for LLM-generated text. |
| `axiom_pattern_checker.py` | 144 | shared/axiom_pattern_checker.py — Output pattern matching for axiom enforcement. |
| `axiom_patterns.py` | 134 | Load T0 violation patterns for axiom enforcement scanning. |
| `axiom_precedents.py` | 334 | Qdrant-backed precedent database for axiom enforcement. |
| `axiom_registry.py` | 302 | Load axiom definitions from hapaxromana registry. |
| `axiom_tools.py` | 133 | Decision-time axiom compliance tools for Pydantic AI agents. |
| `beat_tracker.py` | 181 | shared/beat_tracker.py — Beat tracking via beat_this. |
| `browser_services.py` | 56 | shared/browser_services.py — Python-side service registry for browser agents. |
| `calendar_context.py` | 99 | Calendar context query interface for Hapax agents. |
| `cameras.py` | 140 | Shared camera configuration — single source of truth for multi-camera system. |
| `capability_adapters.py` | 44 | Adapters that wrap existing types as Capability protocol instances. |
| `capability.py` | 93 | Shared capability protocol for all Hapax subsystems. |
| `capability_registry.py` | 240 | Capability registry — unified activation interface for the impingement cascade. |
| `capacity.py` | 269 | Capacity monitoring and exhaustion forecasting. |
| `chronicle.py` | 222 | shared/chronicle.py — Unified observability event store. |
| `chronicle_sampler.py` | 182 | shared/chronicle_sampler.py — Periodic 30-second state snapshots. |
| `ci_discovery.py` | 133 | CI discovery — find live Configuration Items for coverage enforcement. |
| `circuit_breaker.py` | 62 | Generic circuit breaker for external service calls. |
| `clap.py` | 202 | shared/clap.py — CLAP audio-text embedding and zero-shot classification. |
| `cli.py` | 84 | shared/cli.py -- Common CLI boilerplate for agents. |
| `coherence.py` | 108 | Coherence checker: validates governance chain integrity (§4.8). |
| `color_utils.py` | 24 | shared/color_utils.py — Color normalization utilities. |
| `compositor_model.py` | 316 | Compositor data model — Source, Surface, Assignment, Layout. |
| `config.py` | 419 | shared/config.py — Central configuration for all agents. |
| `constitutive.py` | 214 | Constitutive rules: explicit 'X counts as Y in context C' mappings (§4.3). |
| `context_compression.py` | 133 | shared/context_compression.py — TOON + LLMLingua-2 compression primitives. |
| `context.py` | 178 | Shared context enrichment for all Hapax subsystems. |
| `context_tools.py` | 244 | shared/context_tools.py — On-demand operator context tools for Pydantic AI agent |
| `control_signal.py` | 48 | ControlSignal — per-component perceptual control error reporting. |
| `correction_memory.py` | 271 | Correction memory — stores and retrieves operator corrections for experiential l |
| `correction_synthesis.py` | 189 | Correction synthesis — extract profile facts from accumulated corrections. |
| `cycle_mode.py` | 13 | shared/cycle_mode.py — DEPRECATED. Use shared.working_mode instead. |
| `deliberation_metrics.py` | 371 | deliberation_metrics.py — Pure metric extraction from deliberation YAML records. |
| `dimensions.py` | 153 | shared/dimensions.py — Profile dimension registry. |
| `document_registry.py` | 146 | Document registry loader — parses document-registry.yaml for drift enforcement. |
| `eigenform_analysis.py` | 111 | Eigenform convergence detection from logged state vectors. |
| `eigenform_logger.py` | 59 | State vector logger for eigenform convergence analysis. |
| `email_utils.py` | 109 | email_utils.py — Shared email parsing utilities. |
| `embed_cache.py` | 95 | Persistent embedding cache — avoids re-embedding static text across restarts. |
| `episodic_memory.py` | 389 | Episodic memory — perception episode store for experiential learning. |
| `exploration.py` | 425 | ExplorationSignal — per-component boredom/curiosity computation. |
| `exploration_tracker.py` | 319 | Reusable exploration tracker bundle for component wiring. |
| `exploration_writer.py` | 52 | Atomic publication of ExplorationSignal to /dev/shm. |
| `expression.py` | 144 | Cross-modal expression coordination. |
| `flow_state.py` | 216 | shared/flow_state.py — Flow state machine for studio production sessions. |
| `frequency_window.py` | 76 | Time-windowed event frequency tracker for distribution shift detection. |
| `freshness_gauge.py` | 201 | Per-producer freshness contracts for always-on loops. |
| `frontmatter.py` | 118 | shared/frontmatter.py — Canonical frontmatter parser. |
| `frontmatter_schemas.py` | 99 | shared/frontmatter_schemas.py — Pydantic schemas for filesystem-as-bus document  |
| `google_auth.py` | 109 | Shared Google OAuth2 credential management. |
| `gpu_semaphore.py` | 78 | System-wide GPU semaphore using flock-based counting slots. |
| `health_analysis.py` | 134 | LLM-powered health analysis — root cause analysis and remediation planning. |
| `health_correlator.py` | 197 | Cross-signal correlation for health events. |
| `health_history.py` | 294 | Health history aggregation and retention. |
| `hsemotion.py` | 130 | shared/hsemotion.py — HSEmotion facial expression analysis. |
| `hyprland.py` | 147 | Thin wrapper over Hyprland IPC for desktop state queries and actions. |
| `impingement_consumer.py` | 198 | shared/impingement_consumer.py — Cursor-tracked JSONL impingement reader. |
| `impingement.py` | 121 | Impingement — a detected deviation from the DMN's predictive model. |
| `incident_knowledge.py` | 116 | Incident knowledge base — structured (failure, fix, outcome) patterns. |
| `incidents.py` | 222 | Incident lifecycle management for health monitoring. |
| `inference_budget.py` | 213 | LRR Phase 9 item 5 — inference budget allocator. |
| `__init__.py` | 0 |  |
| `ir_models.py` | 52 | shared/ir_models.py — Pydantic models for Pi NoIR edge detection reports. |
| `knowledge_search.py` | 306 | shared/knowledge_search.py — Qdrant semantic search & knowledge artifact reads. |
| `labeled_trace.py` | 70 | Consent-labeled /dev/shm trace I/O. |
| `langfuse_client.py` | 177 | shared/langfuse_client.py — Consolidated Langfuse API client. |
| `langfuse_config.py` | 61 | langfuse_config.py — Wire OpenTelemetry traces to self-hosted Langfuse. |
| `litellm_callbacks.py` | 51 | LiteLLM custom callbacks for Langfuse scoring. |
| `llm_export_converter.py` | 402 | llm_export_converter.py — Convert LLM platform data exports to markdown. |
| `llm_health.py` | 101 | shared/llm_health.py — LiteLLM proxy health check with circuit breaker. |
| `log_setup.py` | 97 | shared/log_setup.py -- Centralized structured JSON logging. |
| `mesh_health.py` | 52 | Aggregate mesh-wide health from per-component control signals. |
| `modification_classifier.py` | 85 | Modification classification matrix. |
| `notify.py` | 473 | shared/notify.py — Unified notification dispatch. |
| `olaf.py` | 162 | shared/olaf.py — Olaf audio fingerprinting CLI wrapper. |
| `operator.py` | 343 | shared/operator.py — Operator profile integration for agents. |
| `operator_schema.py` | 191 | Operator Schema: query interface and staleness model over the 11 profile dimensi |
| `ops_db.py` | 266 | shared/ops_db.py — Build in-memory SQLite from operational JSONL/JSON files. |
| `ops_live.py` | 157 | shared/ops_live.py — Live infrastructure queries. |
| `pattern_consolidation.py` | 404 | Pattern consolidation — LLM-driven extraction of if-then rules from episodes. |
| `plugin_manifest.py` | 102 | Plugin manifest schema — the contract every compositor plugin honors. |
| `profile_store.py` | 243 | shared/profile_store.py — Profile fact vector store and digest access. |
| `qdrant_schema.py` | 93 | shared/qdrant_schema.py — Qdrant collection configuration assertions. |
| `registry_checks.py` | 304 | Registry enforcement checks — produces DriftItems from document registry rules. |
| `research_marker.py` | 226 | LRR Phase 1 item 3 — research marker read/write helper. |
| `research_registry_schema.py` | 172 | Pydantic schema for LRR Phase 1 research registry condition files. |
| `sdlc_status.py` | 242 | SDLC pipeline status collector for briefing integration. |
| `sensor_protocol.py` | 123 | Sensor backend protocol — self-modulating data acquisition with impingement emis |
| `service_graph.py` | 94 | Service dependency graph for dependency-aware remediation. |
| `service_tiers.py` | 85 | Service tier classification for health check prioritization. |
| `sheaf_graph.py` | 56 | Reading-dependency graph for the 14-node SCM. |
| `sheaf_health.py` | 113 | Restriction map consistency health monitor for the SCM. |
| `sheaf_stalks.py` | 51 | Linearize /dev/shm JSON traces into numeric vectors for sheaf computation. |
| `signal_bus.py` | 87 | Unified signal bus for perception → modulation flow. |
| `soak.py` | 127 | Soak period tracking for auto-merged PRs. |
| `spec_audit.py` | 627 | Spec audit — verify operational invariants of the Hapax circulatory systems. |
| `spec_principles_audit.py` | 442 | Principled spec audit — discovers and checks invariants from first principles. |
| `spec_registry.py` | 141 | shared/spec_registry.py — Load and query operational specifications. |
| `staleness_emitter.py` | 36 | Rate-limited staleness impingement emitter. |
| `stimmung.py` | 637 | SystemStimmung — unified self-state vector for system self-awareness. |
| `stream_archive.py` | 172 | Shared schema + helpers for the LRR Phase 2 stream archive. |
| `sufficiency_probes.py` | 1205 | Behavioral sufficiency probes — deterministic checks that the system |
| `telemetry.py` | 545 | Circulatory system telemetry — domain-aware Langfuse instrumentation. |
| `temporal_shm.py` | 48 | Read temporal bands from shared memory for prompt injection. |
| `threshold_tuner.py` | 117 | Adaptive threshold tuning for health checks. |
| `tmp_wav.py` | 84 | Managed temporary WAV file creation with leak prevention. |
| `topology_health.py` | 38 | Topological health diagnostics. β₀=components, β₁=cycles. |
| `trace_reader.py` | 42 | Staleness-checked /dev/shm trace reader. |
| `transcript_parser.py` | 258 | shared/transcript_parser.py — Parse meeting transcripts in VTT, SRT, and speaker |
| `vault_note_renderer.py` | 106 | Optional vault note renderer for LRR Phase 2 item 7. |
| `vault_utils.py` | 36 | Shared utilities for reading Obsidian vault content. |
| `vault_writer.py` | 264 | shared/vault_writer.py — System → Obsidian vault egress. |
| `working_mode.py` | 54 | shared/working_mode.py — Working mode reader/writer. |

## Sub-packages

| Package | .py files | First docstring line |
|---|---|---|
| `capabilities/` | 8 | Disposable capability layer: Protocols, Registry, and Adapters. |
| `fix_capabilities/` | 10 | Fix capabilities — structured fix evaluation and execution for health monitor. |
| `governance/` | 24 | Governance package — consent, authority, and values as type-level invariants. |
| `proton/` | 5 |  |
| `takeout/` | 22 | shared.takeout — Multi-modal Google Takeout ingestion pipeline. |
