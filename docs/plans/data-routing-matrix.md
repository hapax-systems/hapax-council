# Data Routing Matrix: All Right Data -> All Right Consumers

**Date:** 2026-03-13
**Status:** Analysis (not implementation-ready)
**Purpose:** Map every data source to every consumer, find missing connections

---

## Consumer Inventory

### C1. Operator (Human)
**Surfaces:** Cockpit SPA, voice daemon (audio), ntfy (push), VS Code extension, Grafana, Langfuse UI, Open WebUI, Obsidian vault, CLI output, notify-send (desktop)

### C2. Briefing Agent
**Reads:** activity_analyzer output, live health, goals, scout report, digest, deliberation metrics, axiom governance, calendar, Drive, Gmail state, Claude Code state, Obsidian state, audio state, SDLC status, profile health

### C3. Activity Analyzer
**Reads:** Langfuse traces, health-history.jsonl, drift-history.jsonl, journald

### C4. Health Monitor
**Reads:** Docker, systemd, Qdrant health, GPU, profiles, HTTP endpoints, credentials (pass), disk

### C5. Health Watchdog (Fix Pipeline)
**Reads:** health-history.jsonl (failures), Docker/systemd for remediation. Executes fixes.

### C6. Nudges System
**Reads:** health, briefing, readiness, profile analysis, scout, drift, goals, sufficiency probes, knowledge gaps, precedent store, emergence, decision log, accommodations

### C7. Digest Agent
**Reads:** Qdrant documents (recent), collection stats, vault inbox

### C8. Drift Detector
**Reads:** live manifest (introspect), documentation files, drift history

### C9. Scout
**Reads:** component-registry.yaml, Tavily (web), scout-decisions.jsonl, Langfuse (usage context)

### C10. Profiler
**Reads:** local data sources (configs, shell history, git, transcripts), external exports

### C11. Voice Daemon
**Reads (tools):** Qdrant (documents, profile-facts, claude-memory), calendar, Gmail, Drive, desktop state (hyprland), watch signals
**Reads (perception):** PipeWire, hyprland events, watch sensors, health status, circadian state
**Reads (notifications):** ntfy SSE stream

### C12. Introspect
**Reads:** Docker, systemd, Qdrant collections, Ollama, GPU, LiteLLM, disk, network ports

### C13. Knowledge Maintenance
**Reads:** all Qdrant collections (documents, samples, claude-memory, profile-facts)

### C14. Ingest Pipeline
**Reads:** watch directories (RAG_SOURCES), file content (Docling parser), state tracking

### C15. SDLC Metrics
**Reads:** sdlc-events.jsonl, git state

### C16. Deliberation Eval
**Reads:** deliberation event logs, concession records

### C17. Prometheus
**Scrapes:** council-cockpit (:8051), officium-cockpit (:8050), LiteLLM (:4000), Qdrant (:6333), nvidia-gpu (:9835), self (:9090)

### C18. Grafana
**Reads:** Prometheus

### C19. LLM Cost Alert
**Reads:** Langfuse daily metrics API

### C20. Cockpit Cache (council)
**Reads:** all cockpit/data/* collectors (health, GPU, infra, briefing, scout, drift, cost, goals, readiness, nudges, emergence, decisions, knowledge sufficiency)

### C21. Cockpit Cache (officium)
**Reads:** management state, goals, team health, nudges, OKRs, incidents, postmortems, review cycles, status reports, briefing

### C22. Reactive Engine (officium)
**Reads:** DATA_DIR filesystem events (inotify), file content (YAML frontmatter)

### C23. VS Code Extension
**Reads:** LiteLLM (chat), Qdrant (search), Ollama (embeddings)

### C24. Backup Scripts
**Reads:** Postgres dumps, Qdrant snapshots, filesystem state

### C25. Sync Agents (6)
**Read:** Gmail API, Calendar API, Drive API, YouTube API, Chrome DB, Obsidian vault
**Write to:** RAG_SOURCES/*, profile facts, state JSON

### C26. Capacity Forecaster
**Reads:** health history, resource trends

### C27. Auto-Fix Workflow (constitution)
**Reads:** CI failure logs, yamllint output

### C28. SDLC Implement Workflow (constitution)
**Reads:** GitHub issue body, repository state

---

## Gap Analysis: Data Produced But Under-Consumed

### GAP-1: Prometheus metrics reach nobody actionable
- **Source:** 6 scrape targets producing continuous metrics
- **Current consumers:** Grafana (display only, no alert rules)
- **Missing:** No alert rules. No agent reads Prometheus. GPU temp, disk usage, error rate spikes, Qdrant latency — all collected, none acted on.
- **Should reach:** Health watchdog (for metric-informed health checks), cost alert (for LiteLLM token metrics), operator (via Grafana alerts → ntfy)

### GAP-2: Structured logs (H4) reach nobody
- **Source:** All agents now produce JSON logs with trace IDs to journald
- **Current consumers:** Nobody reads them programmatically. journalctl is manual.
- **Missing:** No log anomaly detection. No agent counts ERROR-level entries. No correlation with Langfuse traces.
- **Should reach:** Health monitor (error spike detection), activity analyzer (agent error rates), operator (via anomaly alerts)

### GAP-3: Langfuse traces under-utilized
- **Source:** All agents + RAG pipeline produce OTel spans to Langfuse
- **Current consumers:** activity_analyzer (cost totals), cost alert (daily totals), scout (usage context). That's it.
- **Missing:** No agent reads its own performance. No RAG quality monitoring (zero-result queries invisible). No latency trend detection. No error trace → health correlation.
- **Should reach:** Each agent (self-awareness per G2), RAG quality monitor (G3), health watchdog (G4), operator (via Langfuse dashboards)

### GAP-4: Health check results don't inform agent behavior
- **Source:** health-history.jsonl (every 15 min, 44 checks)
- **Current consumers:** activity_analyzer (trends), briefing (display), nudges (failing checks), voice perception (health status), capacity forecaster
- **Missing:** No agent adjusts behavior based on infrastructure state. If Ollama is down, agents still try to call it and fail. If Qdrant is slow, no backoff.
- **Should reach:** All agents that use Ollama/Qdrant (graceful degradation), LiteLLM (dynamic model routing based on health)

### GAP-5: Watch/wearable data isolated to voice daemon
- **Source:** Pixel Watch 4 → watch_receiver → hapax-state/watch/*.json (HR, HRV, EDA, activity, sleep)
- **Current consumers:** Voice daemon perception backends only
- **Missing:** Briefing doesn't know sleep quality. Nudges don't adjust priority by energy level. Scheduling agents don't know activity state.
- **Should reach:** Briefing (sleep/recovery context), nudges (energy-aware priority), accommodations system (already has framework but no watch input)

### GAP-6: Drift report findings not routed to fixers
- **Source:** drift-detector produces severity-rated drift items with suggestions
- **Current consumers:** nudges (display), briefing (display), cockpit (display)
- **Missing:** High-severity drift items sit as nudges until operator manually acts. No auto-fix for documentation drift. No escalation path.
- **Should reach:** SDLC implement workflow (auto-PR for doc fixes), health watchdog (if drift indicates config mismatch)

### GAP-7: Scout recommendations not actionable
- **Source:** scout produces adopt/evaluate/monitor/current-best tiers
- **Current consumers:** nudges (display), briefing (display), cockpit (display)
- **Missing:** "evaluate" recommendations have no follow-up. No automatic research spike. No tracking of whether operator acted.
- **Should reach:** Research agent (auto-spike on "evaluate" items), SDLC (issue creation for "adopt" items), decision log (track recommendation outcomes)

### GAP-8: Deliberation metrics not escalated
- **Source:** deliberation_eval detects pseudo-deliberation, stores in JSONL
- **Current consumers:** briefing (display section)
- **Missing:** Pseudo-deliberation detected but no action taken. Per closing-feedback-loops.md G5: 3+ pseudo-deliberations should trigger precedent review.
- **Should reach:** Precedent store (flag for review), nudges (deliberation nudge source), operator (ntfy alert on pattern)

### GAP-9: SDLC events not feeding back to governance
- **Source:** sdlc-events.jsonl (PR stages, axiom gates, review rounds)
- **Current consumers:** sdlc_metrics agent (velocity/quality metrics)
- **Missing:** Axiom gate failures don't feed back into precedent store. Repeated review rounds don't trigger process improvement. No correlation between SDLC velocity and agent quality.
- **Should reach:** Precedent store (gate failure → precedent refinement), nudges (process health), briefing (SDLC health trend)

### GAP-10: Cost data fragmented across three sources
- **Source:** Langfuse API (per-trace costs), LiteLLM Prometheus metrics (per-model token counts), LiteLLM budget ($50/30d cap)
- **Current consumers:** cost alert (Langfuse daily totals), cockpit cost collector (Langfuse 7d), activity_analyzer (Langfuse lookback)
- **Missing:** Prometheus token metrics not correlated with Langfuse costs. LiteLLM budget status not surfaced. No per-agent cost attribution (agent spans exist but cost rollup doesn't happen).
- **Should reach:** Per-agent cost dashboard (Grafana), budget status in cockpit, briefing (cost-per-agent trend)

### GAP-11: Profile facts write-only for most consumers
- **Source:** Profiler extracts facts → Qdrant profile-facts collection. Sync agents also write profile facts.
- **Current consumers:** Voice tools (search_profile), context_tools (get_operator_profile), nudges (profile completeness)
- **Missing:** Agents don't use profile facts to personalize their behavior. Scout doesn't know operator preferences when evaluating alternatives. Briefing doesn't adapt tone/detail level.
- **Should reach:** All agents (via system prompt fragment — partially exists via get_system_prompt_fragment() but underused)

### GAP-12: Officium reactive engine events invisible
- **Source:** DATA_DIR filesystem changes → ChangeEvent → rule execution → cascades
- **Current consumers:** cockpit cache (refresh trigger)
- **Missing:** No logging of what rules fired, what cascades ran, what failed. No visibility into reactive engine health. No metrics.
- **Should reach:** Structured logs (rule execution traces), Prometheus (rule execution counts), cockpit (engine status panel)

### GAP-13: Backup status not monitored
- **Source:** hapax-backup-local.sh (daily), hapax-backup-remote.sh (weekly)
- **Current consumers:** notify-send (desktop notification, ephemeral)
- **Missing:** No persistent record of backup success/failure. No alerting on missed backups. No tracking of backup size growth.
- **Should reach:** Health monitor (backup age check), ntfy (persistent notification), cockpit (backup status panel)

### GAP-14: External service sync failures silent
- **Source:** 6 sync agents (Gmail, Calendar, Drive, YouTube, Chrome, Obsidian) each have state files
- **Current consumers:** Briefing reads state files for activity stats
- **Missing:** Sync failures (API errors, auth expiry, quota limits) don't alert. Stale sync state goes unnoticed.
- **Should reach:** Health monitor (sync freshness checks), ntfy (auth expiry alerts), nudges (stale sync warning)

---

## Gap Priority Matrix

| Gap | Severity | Effort | Dependencies | Category |
|-----|----------|--------|--------------|----------|
| GAP-1 | HIGH | Low | H3 running | Alert rules (G7) |
| GAP-2 | HIGH | Medium | H4 deployed | Log anomaly (G6) |
| GAP-3 | HIGH | Medium | H1/H2 deployed | Agent self-awareness (G2), RAG quality (G3), trace-health (G4) |
| GAP-4 | MEDIUM | Medium | None | Graceful degradation |
| GAP-5 | MEDIUM | Low | Watch pipeline running | Biometric routing |
| GAP-6 | MEDIUM | Medium | SDLC workflow | Auto-fix drift |
| GAP-7 | MEDIUM | Medium | Research agent | Scout follow-through |
| GAP-8 | LOW | Low (30 LOC) | None | Deliberation escalation (G5) |
| GAP-9 | MEDIUM | Medium | Constitution SDLC | Governance feedback |
| GAP-10 | MEDIUM | Low | H3 running | Cost consolidation |
| GAP-11 | LOW | Low | None | Profile utilization |
| GAP-12 | MEDIUM | Low | H4 deployed | Engine observability |
| GAP-13 | MEDIUM | Low | None | Backup monitoring |
| GAP-14 | MEDIUM | Low | None | Sync monitoring |

---

## Proposed Routing Architecture

### Principle: Push, Don't Pull
The current architecture requires consumers to poll or manually query. The fix is to add event-driven routing where data producers push to interested consumers.

### Existing Routing Mechanisms
1. **Filesystem-as-bus** (officium reactive engine) — works for DATA_DIR, not used elsewhere
2. **ntfy** (push notifications) — works for operator alerts, underused
3. **Cockpit cache** (polling collectors) — works for dashboard, not for agent consumption
4. **Langfuse** (trace ingestion) — works for storage, no downstream triggers
5. **Prometheus** (scrape) — works for metrics, no alert rules

### Missing Routing Mechanisms
1. **Health-aware agent bootstrapping** — agents check health before calling services
2. **Event-to-ntfy bridge** — structured log errors → ntfy alerts
3. **Prometheus alerting** — metric thresholds → Alertmanager → ntfy
4. **Langfuse query cronjob** — periodic trace analysis → nudges/alerts
5. **Sync health checks** — state file freshness → health monitor

### Implementation Groups

**Group A: Wire existing data to existing consumers (no new infrastructure)**
- GAP-8: Deliberation escalation (30 LOC in deliberation_eval.py)
- GAP-13: Backup age check in health monitor (add 1 check)
- GAP-14: Sync freshness checks in health monitor (add 6 checks)
- GAP-5: Read watch state in accommodations/nudges (extend existing framework)

**Group B: Add alert rules to existing infrastructure**
- GAP-1: Prometheus alert rules → Alertmanager → ntfy
- GAP-10: Grafana dashboard for per-agent costs

**Group C: New lightweight consumers (cronjobs/timers)**
- GAP-2: Log anomaly detection script (journalctl JSON parsing → ntfy)
- GAP-3: Langfuse query cronjob for RAG quality, agent perf, error correlation

**Group D: Agent behavior changes (requires architectural decisions)**
- GAP-3 (agent self-awareness): Each agent queries own performance → adaptation policy TBD
- GAP-4: Health-aware service calls (retry/backoff/fallback)
- GAP-6: Drift → auto-PR pipeline
- GAP-7: Scout → research spike pipeline
- GAP-9: SDLC gate failures → precedent refinement
- GAP-12: Reactive engine instrumentation

---

## Cross-Reference with closing-feedback-loops.md

| Feedback Loop Gap | Data Routing Gap |
|-------------------|------------------|
| G1 (cost trend in briefing) | GAP-10 (cost fragmentation) |
| G2 (agent self-awareness) | GAP-3 (Langfuse under-utilized) |
| G3 (RAG failure feedback) | GAP-3 (Langfuse under-utilized) |
| G4 (trace-to-health correlation) | GAP-3 (Langfuse under-utilized) |
| G5 (pseudo-deliberation escalation) | GAP-8 (deliberation not escalated) |
| G6 (log anomaly detection) | GAP-2 (structured logs reach nobody) |
| G7 (Prometheus alert rules) | GAP-1 (metrics reach nobody) |
| — | GAP-4 (health → agent behavior) NEW |
| — | GAP-5 (watch data isolated) NEW |
| — | GAP-6 (drift → auto-fix) NEW |
| — | GAP-7 (scout → research) NEW |
| — | GAP-9 (SDLC → governance) NEW |
| — | GAP-11 (profile underused) NEW |
| — | GAP-12 (engine invisible) NEW |
| — | GAP-13 (backup unmonitored) NEW |
| — | GAP-14 (sync failures silent) NEW |

The routing analysis found 8 additional gaps beyond the 7 identified in closing-feedback-loops.md.
