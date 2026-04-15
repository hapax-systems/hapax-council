# Docker Compose Containers Audit — 13 running containers

**Queue:** #175
**Author:** alpha
**Date:** 2026-04-15
**Source of truth:** `~/llm-stack/docker-compose.yml` (not the council repo)

---

## §0. TL;DR

All 13 containers are running + healthy. The workspace CLAUDE.md phrase "Docker Compose for infrastructure" is **accurate** for the service list but **mis-locates the compose file**: the actual compose file lives at `~/llm-stack/docker-compose.yml`, not at `hapax-council/docker/docker-compose.yml`. The council repo's own compose file defines only two services (`logos-api`, `sync-pipeline`) and neither of them is currently running.

**One live HIGH finding:** LiteLLM is at 1.9 GiB of its 2 GiB memory limit (~95%). Under load spikes it will hit OOM and restart. Recommend raising `mem_limit` to 3 GiB or investigating the leak.

**Count reconciliation:** CLAUDE.md lists "Langfuse" as a single bullet but Langfuse v3 ships as two containers (`langfuse` web + `langfuse-worker`). Split across the pair, the container count is exactly 13. Counting one "Langfuse" as one line produces the CLAUDE.md phrase but the actual process count is 13. This is a documentation-only drift.

---

## §1. Enumerated containers

All 13 containers use `restart: always` + a healthcheck + JSON-file logging capped at 50 MB × 3 files. Start time across all 13 is `2026-04-15T15:56:21Z` (≈ 5 hours before audit), implying a recent clean restart of the full profile.

| # | Name | Image | Ports | mem_limit | Profile | Healthcheck | Health |
|---|------|-------|-------|-----------|---------|-------------|--------|
| 1 | qdrant | `qdrant/qdrant:latest` | 127.0.0.1:6333–6334 | 6g | core,full,analytics | tcp /6333 | healthy |
| 2 | postgres | `pgvector/pgvector:pg16` | 127.0.0.1:5432 | 6g | core,full,analytics | pg_isready | healthy |
| 3 | litellm | `ghcr.io/berriai/litellm:main-stable` | 127.0.0.1:4000 | 2g | core,full,analytics | /health/readiness | healthy |
| 4 | redis | `redis:7-alpine` | 127.0.0.1:6379 | 2g | full,analytics | redis-cli ping | healthy |
| 5 | clickhouse | `clickhouse/clickhouse-server:24.8` | 127.0.0.1:8123, 9000 | 4g | full,analytics | /ping | healthy |
| 6 | langfuse-worker | `langfuse/langfuse-worker:3` | 127.0.0.1:3030 | 2g | full,analytics | /api/health | healthy |
| 7 | langfuse | `langfuse/langfuse:3` | 127.0.0.1:3000 | 2g | full,analytics | /api/public/health | healthy |
| 8 | open-webui | `ghcr.io/open-webui/open-webui:main` | 127.0.0.1:8080 | 2g | full,analytics | /health | healthy |
| 9 | n8n | `n8nio/n8n:latest` | 127.0.0.1:5678 | 1g | full,analytics | /healthz | healthy |
| 10 | ntfy | `binwiederhier/ntfy:latest` | **0.0.0.0:8090** → 80 | 256m | full,analytics | /v1/health | healthy |
| 11 | prometheus | `prom/prometheus:latest` | 127.0.0.1:9090 | 1g | full,analytics | /-/healthy | healthy |
| 12 | grafana | `grafana/grafana-oss:latest` | 127.0.0.1:3001 → 3000 | 768m | full,analytics | /api/health | healthy |
| 13 | minio | `minio/minio:latest` | 127.0.0.1:9001 → 9000, 9002 → 9001 | 4g | full,analytics | `mc ready local` | healthy |

**Total mem_limit:** 33.25 GiB reservation (container ceilings, not actual usage).

**Total running images:** 13 distinct. All pinned to `latest` / `main-stable` / `pg16` / `24.8` / `7-alpine` / `3` — **no SHA pinning**. This is a supply-chain surface but out of scope for this audit.

---

## §2. Live resource metrics (audit snapshot)

From `docker stats --no-stream` at `2026-04-15T23:02Z`:

| Container | CPU % | Memory used | mem_limit | % of limit |
|-----------|-------|-------------|-----------|------------|
| litellm | 14.9 | **1.90 GiB** | **2 GiB** | **~95%** |
| minio | 10.5 | 1.93 GiB | 4 GiB | 48% |
| clickhouse | 29.3 | 596 MiB | 4 GiB | 14% |
| redis | 0.8 | 272 MiB | 2 GiB | 13% |
| n8n | 0.1 | 213 MiB | 1 GiB | 21% |
| langfuse-worker | 0.9 | 196 MiB | 2 GiB | 10% |
| prometheus | 0.2 | 136 MiB | 1 GiB | 13% |
| grafana | 0.3 | 114 MiB | 768 MiB | 15% |
| postgres | 0.0 | 93 MiB | 6 GiB | 1.5% |
| qdrant | 0.2 | 57 MiB | 6 GiB | 0.9% |
| open-webui | 0.1 | 50 MiB | 2 GiB | 2.5% |
| langfuse | 0.4 | 489 MiB | 2 GiB | 24% |
| ntfy | 0.0 | 30 MiB | 256 MiB | 12% |

**Aggregate memory used:** ≈ 6.1 GiB across 13 containers.

**Aggregate CPU at snapshot:** ≈ 58% (summed across containers, not host-normalised).

---

## §3. Drift vs workspace CLAUDE.md

### §3.1. Compose file location drift (MEDIUM)

**Claim:** Workspace CLAUDE.md says "Docker Compose for infrastructure" in the context of the council repo. Council CLAUDE.md says "Docker Compose for databases/proxies (13 containers, `restart: always`)".

**Reality:** The authoritative compose file for the 13 running containers is `~/llm-stack/docker-compose.yml`. The file at `hapax-council/docker/docker-compose.yml` defines only `logos-api` and `sync-pipeline`, neither currently running. A reader who tries `cd hapax-council && docker compose up -d` will start two unrelated services.

**Recommendation:** Update council CLAUDE.md to explicitly cite `~/llm-stack/docker-compose.yml` as the source of truth for the infrastructure stack. The council-repo `docker/` directory manages only `logos-api` and `sync-pipeline`, which should be documented as a separate opt-in bring-up.

### §3.2. Container count reconciliation (documentation drift, LOW)

**Claim:** CLAUDE.md says "Docker containers (13, restart: always)" and lists 12 bullets (LiteLLM, Qdrant, PostgreSQL, Langfuse, Prometheus, Grafana, Redis, ClickHouse, MinIO, n8n, ntfy, OpenWebUI).

**Reality:** Langfuse v3 is two containers (`langfuse` web + `langfuse-worker`). Counting the pair as two yields 13. The CLAUDE.md phrase "13 containers" is numerically correct, but the enumeration at 12 bullets is one short.

**Recommendation:** Add `langfuse-worker` to the CLAUDE.md bullet list, or rephrase "Langfuse" as "Langfuse (web + worker)" so the bullet count matches the container count.

### §3.3. ntfy binds to 0.0.0.0 (audit observation, INFORMATIONAL)

**Claim:** CLAUDE.md notes firewall LAN allowance to port 8051 (Logos API). No mention of ntfy's network binding.

**Reality:** ntfy publishes `0.0.0.0:8090` — not `127.0.0.1`. Every other container is bound to `127.0.0.1:*`. ntfy is the one exception because the operator's phone client needs to reach it over LAN.

**Recommendation:** Document in council CLAUDE.md that ntfy is the intentional exception to the 127.0.0.1-only binding pattern + that its public binding is covered by the host firewall, not by Docker's internal network isolation.

### §3.4. Profile system not documented (LOW)

**Claim:** CLAUDE.md does not mention Docker Compose profiles.

**Reality:** The compose file uses three profiles: `core` (qdrant + postgres + litellm — 3 containers), `full` (all 13), `analytics` (all 13 — same as full, an alias). A fresh `docker compose up -d` would start zero containers because the default profile is empty. The expected bring-up is `docker compose --profile full up -d`.

**Recommendation:** Add a one-line note to council CLAUDE.md: "Infrastructure bring-up: `cd ~/llm-stack && docker compose --profile full up -d`."

### §3.5. LiteLLM at memory ceiling (HIGH — runtime risk)

**Observation:** LiteLLM is using 1.90 GiB of its 2 GiB `mem_limit` at audit snapshot. The container has restarted once since boot (5-hour uptime, restart count = 1 — this may be from a previous load spike or from the same restart that brought the stack up).

**Risk:** Under any sudden traffic burst (e.g., 200+ concurrent inference calls), the Node.js process will trip the cgroup memory limit and OOM-kill. `restart: always` will bring it back, but all in-flight requests will fail and the Redis response cache warmup will repeat.

**Root cause hypothesis (unverified):** LiteLLM's in-process model routing table + the LangFuse SDK (1024-event flush buffer) + the Prometheus metrics collector accrete memory over time. A known pattern for this class of Node services.

**Recommendation:** Raise `litellm.mem_limit` from `2g` to `3g`. This is a one-line change in `~/llm-stack/docker-compose.yml` at line 110. A more surgical fix would be investigating the specific memory growth (requires heap snapshot) but the blunt fix is cheap and cleanly reversible. This is a follow-up candidate for a beta or operator session.

**Alternative:** If the host is memory-constrained, reduce `LANGFUSE_FLUSH_AT` from 1024 to 256 to shrink the per-process buffer. Less effective but zero-cost.

### §3.6. redis password hardcoded (LOW, intentional)

**Observation:** `redis-server --requirepass redissecret` and `redis-cli -a redissecret ping` have the literal password `redissecret` hardcoded, not via env var.

**Reality check:** redis is bound to `127.0.0.1` only, access is localhost-scoped, and the value is not a secret in any meaningful sense. All the other containers read it as the literal `redissecret` via `REDIS_AUTH`. This is deliberate — the password is a layer of defence-in-depth against accidental cross-process access, not a credential. **No action required.**

### §3.7. MinIO port swap (informational)

**Observation:** MinIO has `127.0.0.1:9001->9000/tcp` and `127.0.0.1:9002->9001/tcp`. The S3 API is on internal :9000 but external :9001, while the console is on internal :9001 but external :9002. This is unusual.

**Reason:** Internal port :9000 conflicts with ClickHouse :9000 on the host, so MinIO is remapped. Deliberate, not a bug. The confusion cost for a new operator is real but small.

**Recommendation:** Add a one-line inline comment in the compose file noting the port swap is intentional due to ClickHouse collision. Not needed in CLAUDE.md.

---

## §4. Healthcheck sanity

All 13 healthchecks were run by Docker at least once in the last 30 seconds and all returned healthy. Spot-check of probe URLs:

- qdrant: TCP probe to :6333 ✓
- postgres: `pg_isready -U hapax` ✓
- litellm: Python `urllib.request.urlopen('http://localhost:4000/health/readiness')` ✓
- redis: `redis-cli -a redissecret ping` ✓
- clickhouse: `wget -qO- http://localhost:8123/ping` ✓
- langfuse + langfuse-worker: `wget -qO- http://$(hostname -i):{3000,3030}/api/{public/,}health` (note the `hostname -i` indirection — the probe runs inside the container and targets its own IP, which is more robust than `localhost` inside a custom network) ✓
- open-webui: `curl -sf http://localhost:8080/health` ✓
- n8n: `wget -qO- http://localhost:5678/healthz` ✓
- ntfy: `wget -qO- http://localhost:80/v1/health` ✓
- prometheus: `wget -qO- http://localhost:9090/-/healthy` ✓
- grafana: `wget -qO- http://localhost:3000/api/health` ✓
- minio: `mc ready local` ✓

Healthcheck coverage is **complete and consistent**. No gaps.

---

## §5. Dependency graph

```
postgres  ←── litellm
   ↑            ↓ (depends_on service_healthy)
   │
   ├── langfuse-worker ──┐
   ├── langfuse          ├── redis  ←── langfuse-worker, langfuse
   │                     ├── clickhouse ←── langfuse-worker, langfuse
   │                     └── minio ←── langfuse-worker, langfuse
   │
prometheus ←── grafana
```

Grafana waits on Prometheus. Langfuse (both containers) wait on Postgres + ClickHouse + Redis + MinIO. LiteLLM waits on Postgres. ntfy + open-webui + n8n + qdrant have no deps and come up first.

The `depends_on` uses `condition: service_healthy` throughout, so partial-healthy startup can stall the downstream containers. In practice this has not been observed — the 5-hour uptime suggests the chain is stable.

---

## §6. Volume mount summary

**Persistent storage paths:**

| Volume path | Service(s) | Purpose |
|-------------|------------|---------|
| `/store/llm-data/qdrant` + `qdrant-snapshots` | qdrant | vector storage |
| `/store/llm-data/postgres` | postgres | relational data |
| `/store/llm-data/redis` | redis | RDB + AOF |
| `/store/llm-data/clickhouse` + `clickhouse-logs` | clickhouse | analytics columnar + server logs |
| `/store/llm-data/prometheus` | prometheus | TSDB (7d retention) |
| `/store/llm-data/grafana` | grafana | dashboard + datasource state |
| `/data/open-webui` | open-webui | user sessions + chat history |
| `/data/n8n` | n8n | workflow definitions + exec history |
| `/data/ntfy` | ntfy | message cache |
| `/data/minio` | minio | S3-style object store (Langfuse events + media) |

**Config mounts (read-only):**
- `./litellm-config.yaml:/app/config.yaml` — LiteLLM model routing
- `./prometheus.yml:/etc/prometheus/prometheus.yml:ro` — scrape targets
- `./clickhouse/users.d` + `./clickhouse/config.d:ro` — ClickHouse tuning
- `./grafana/provisioning:/etc/grafana/provisioning:ro` — dashboards + datasources

**Volume bisection:** the `/store/llm-data/` partition holds the durable analytical storage; `/data/` holds the less-critical app state. This separation is sensible but undocumented — worth noting in CLAUDE.md if a future audit looks at backup coverage.

---

## §7. Follow-up candidates

| Priority | Item | Size |
|----------|------|------|
| HIGH | Raise `litellm.mem_limit` from 2g to 3g; investigate LiteLLM memory growth if time permits | 1 LOC + optional heap profiling |
| MEDIUM | Update council CLAUDE.md: compose file lives at `~/llm-stack/`, not the council repo | 2-line edit |
| MEDIUM | Update council CLAUDE.md: add `langfuse-worker` to the bullet list (or fold it into "Langfuse (web + worker)") | 1-line edit |
| LOW | Document the `--profile full` bring-up invocation in council CLAUDE.md | 1-line edit |
| LOW | Inline comment on MinIO port swap in `~/llm-stack/docker-compose.yml` | 1-line comment |
| LOW | Consider SHA pinning vs `latest` tags for supply-chain hygiene | out of scope, ≈ 13 image digest lookups |

None of these are immediately shippable from the current queue #175 scope; this is a research-only drop.

---

## §8. Cross-references

- `~/llm-stack/docker-compose.yml` — actual source of truth for the 13-container stack
- `hapax-council/docker/docker-compose.yml` — defines 2 optional services (logos-api, sync-pipeline), currently not running
- Council `CLAUDE.md § Infrastructure` — the "13 containers" claim being audited
- Workspace `CLAUDE.md § Shared Infrastructure` — workspace-level claim
- Queue #148 (PR #905) — Prometheus alert-rule vs metric cross-ref (complementary observability audit)
- Queue #175 — this item

---

## §9. Verdict

The 13-container infrastructure is **correctly running and healthy**. The primary audit finding is a **documentation drift**: council CLAUDE.md cites the 13 containers but does not point at the actual compose file location. Second finding is a **runtime risk**: LiteLLM is memory-saturated and will OOM under spike load.

No immediate execution required — findings are routed as follow-up candidates per queue #175 spec. The LiteLLM memory ceiling is the most operationally urgent and should be lifted opportunistically.
