# M3: Cross-Service Trace Correlation — Investigation and Decision

**Date:** 2026-03-12
**Status:** NO-GO (services are isolated; cross-service tracing not needed)

## Investigation Findings

### Port and Infrastructure Mapping

Each service uses its own port namespace for shared infrastructure:

| Infrastructure | hapax-council (dev) | hapax-officium (dev) | Shared instance? |
|----------------|--------------------|--------------------|-----------------|
| Cockpit API    | :8051              | :8050              | No — separate processes |
| LiteLLM        | :4000              | :4100              | No — separate proxies |
| Qdrant         | :6333              | :6433              | No — separate instances |
| Langfuse       | :3000              | :3100              | No — separate instances |
| PostgreSQL     | :5432 (shared)     | N/A (no direct DB) | Partially — council monitors postgres; officium has no DATABASE_URL |

In Docker, officium remaps to different host ports (8051, 4100, 6433) to avoid collisions with council's stack on the same host.

### HTTP Client Calls Between Services

**None found.** Exhaustive grep for cross-service HTTP calls:

- hapax-council's voice daemon (`agents/hapax_voice/`) has zero references to officium ports (8050, 8051) or the string "officium"
- hapax-officium's cockpit (`cockpit/`) has zero references to council ports (8051) or the string "council"
- No `httpx`, `requests`, `fetch`, or `aiohttp` call in either codebase targets the other service's API

### Shared Data Stores

Both services use the same Qdrant collection names:

| Collection        | hapax-council | hapax-officium |
|-------------------|:---:|:---:|
| `documents`       | Yes | Yes |
| `axiom-precedents`| Yes | Yes |
| `profile-facts`   | Yes | Yes |
| `samples`         | Yes | No  |
| `claude-memory`   | Yes | No  |

However, this is not shared access — each service connects to a **different Qdrant instance** (council -> :6333, officium -> :6433). The collection names are identical because officium was extracted from council and retains the same schema patterns. They are completely independent data stores.

### Docker Compose Topology

- **Shared infra** (`~/llm-stack/docker-compose.yml`): Qdrant (:6333), PostgreSQL (:5432), LiteLLM (:4000), Langfuse (:3000), plus supporting services. This is council's infra.
- **Council app** (`hapax-council/docker/docker-compose.yml`): cockpit-api + sync-pipeline containers, `network_mode: host`, connecting to shared infra at localhost ports.
- **Officium app**: Runs with its own infra instances on offset ports. No Docker Compose file found in the repo — likely runs via `uv run` in dev or has its own container setup.

There is no Docker network, message queue, or event bus connecting the two services.

### Voice Daemon and Cockpit SPA

- The voice daemon (`hapax-council/agents/hapax_voice/`) calls only LiteLLM (:4000) and Hyprland IPC. No cross-service calls.
- Council's React SPA (`council-web/`) proxies exclusively to council's cockpit API at :8051.
- Officium's cockpit CORS allows only :8050 (its own SPA origin).

## Decision: NO-GO

Cross-service trace correlation is **not needed**. The services are fully isolated:

1. **No runtime communication.** Neither service makes HTTP calls to the other. There are no shared queues, event buses, or pub/sub channels.
2. **No shared data stores.** Despite identical collection names, each service connects to its own Qdrant instance on different ports. PostgreSQL is used only by council's health monitor (read-only checks) and by LiteLLM/Langfuse — not shared between the two application services.
3. **No shared Langfuse project.** Each service traces to its own Langfuse instance (council -> :3000, officium -> :3100) with its own credentials and `service.name` resource attribute (`hapax-council` vs `hapax-officium`).
4. **Independent deployment.** The services have separate Docker Compose files, separate port namespaces, and separate virtual environments.

W3C Trace Context propagation (traceparent/tracestate headers) would have no consumer — there are no cross-service HTTP boundaries to propagate across.

## Future Considerations

Re-evaluate this decision if any of these conditions emerge:

- **Unified cockpit dashboard.** If a single SPA needs to display data from both council and officium APIs, the SPA would make cross-origin calls. Even then, the SPA is the correlation point (client-side), not backend trace propagation.
- **Voice daemon orchestrating officium agents.** If the voice daemon gains the ability to trigger officium management agents (e.g., "prepare my 1:1 notes"), that would introduce a cross-service call requiring trace propagation.
- **Shared Qdrant or Langfuse consolidation.** If both services are pointed at the same Qdrant/Langfuse instance for cost/simplicity, collection-level isolation and Langfuse project separation would be needed, but trace correlation would still be unnecessary without direct service-to-service calls.
- **n8n workflow bridging.** If n8n workflows trigger endpoints on both services as part of a single workflow, trace context could be propagated through n8n webhook headers. This is a plausible future scenario but not current.

Until one of these conditions materializes, each service's independent OpenTelemetry + Langfuse tracing is sufficient. Traces stay within service boundaries.
