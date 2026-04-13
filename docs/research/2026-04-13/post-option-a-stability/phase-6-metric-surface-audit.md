# Phase 6 — Full-stack Prometheus metric surface audit

**Queue item:** 023
**Phase:** 6 of 6
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

Queue 022 Phase 4 audited the studio-compositor `:9482` exporter and
its 20 metric series. This phase extends the audit to every Prometheus
surface in the hapax stack. Findings, in order of severity:

1. **`studio_*` metrics are entirely absent from Prometheus**
   (`series_count=0`). The compositor exports 20 series on `:9482`, but
   `prometheus.yml` has no scrape job for it. The
   `grafana/dashboards/studio-cameras.json` dashboard is end-to-end
   dead as a result — every one of its 12 panels returns "No data"
   against the Prometheus datasource. Queue 022 Phase 4 and the
   cameras_healthy finding both measured the compositor endpoint
   directly; neither would have surfaced as "everything's broken
   downstream" without a full Prometheus → Grafana walk. **Severity:
   HIGH**
2. **`node-exporter` scrape is broken** (`up{job=node-exporter}=0`,
   `context deadline exceeded`). Host CPU/mem/disk/net observability
   is entirely offline. All 332 node_exporter metrics (including the
   ones the Bayesian presence engine's `ambient_energy`,
   `keyboard_active`, and operator-face signals depend on for
   correlation) are missing from Prometheus. The host-side
   node_exporter binary is alive and serving 2406 metric lines on
   `:9100`; the Prometheus container cannot reach it (container → host
   network path is up for other services). **Severity: HIGH**
3. **Three critical hapax services have no Prometheus endpoint at
   all** — `hapax-daimonion.service`, `visual-layer-aggregator.service`,
   and `hapax-imagination.service`. CPAL voice state, STT/TTS timing,
   watchdog freshness, VRAM footprint, perception fusion dimensions,
   wgpu pool metrics, shader compile timing — all ungauged, all
   invisible, no way to alert on any of them. This is an entire
   observability wing missing. **Severity: HIGH** (alpha's backlog
   item #10 — "Pool metrics IPC" — addresses the imagination piece;
   the other two have no open ticket.)
4. **`tabbyAPI` has no `/metrics` endpoint**. TabbyAPI is the GPU
   inference backbone serving `local-fast`/`coding`/`reasoning`
   (Qwen3.5-9B EXL3), effectively the single most expensive consumer
   on the GPU. Queue depth, inference latency, KV cache hit rate,
   GPU memory usage from the model-server perspective — all
   ungauged. The nvidia_gpu_exporter `:9835` covers the hardware view
   but not the model-server view. **Severity: MEDIUM**
5. **LiteLLM `/metrics` requires a trailing slash but the scrape
   config uses `/metrics`**. The server responds with
   `307 Temporary Redirect` → `/metrics/`. Prometheus's Go HTTP
   client follows 307s for GETs, so the scrape works today. A library
   upgrade or configuration change that disables redirect-follow
   would break the scrape without any signal in the scrape config.
   Fix: set `metrics_path: /metrics/` explicitly. **Severity: LOW**
6. **`logos-api` and `officium-api` expose only the
   `prometheus_client` default process metrics** — no application-
   level metrics. `council-cockpit` and `officium-cockpit` jobs
   scrape 26 series each, all of them
   `process_*` / `http_request_duration_*` / `python_gc_*`. No
   agent count, no LLM call count, no decision throughput, no
   error rates per endpoint, no consent-gate denial rate. The API
   layer is alive-or-dead observable but not
   behavior-observable. **Severity: MEDIUM**
7. **Prometheus has no alert rules defined**
   (`/etc/prometheus/rules/` directory does not exist). Grafana
   dashboards exist, but there is no Alertmanager integration, no
   recording rules, no threshold-driven pages. A dead scrape stays
   silently dead — the only way "node-exporter is down" surfaces is
   if a human opens the Prometheus UI. **Severity: MEDIUM**

## Method

### Endpoint enumeration

Walked every listening TCP port on the host and inside the
`llm-stack` docker network via `ss -tlnp` and `docker ps`, then
attempted an HTTP GET at both `/metrics` and `/metrics/`.

```text
$ ss -tlnp | grep -E ':(9482|5000|8051|8050|3000|9090|8052|8053|9100|9835)'
LISTEN 0  5     0.0.0.0:9482   0.0.0.0:*  users:(("python",pid=2913194))      — compositor
LISTEN 0  2048  0.0.0.0:5000   0.0.0.0:*  users:(("python3",pid=38671))       — tabbyapi
LISTEN 0  2048  0.0.0.0:8051   0.0.0.0:*  users:(("python3",pid=3084055))     — logos-api
LISTEN 0  2048  0.0.0.0:8050   0.0.0.0:*  users:(("python3",pid=8634))        — officium-api
LISTEN 0  4096    *:9100          *:*                                         — node-exporter
LISTEN 0  4096    *:9835          *:*                                         — nvidia_gpu_exporter
LISTEN 0  128   127.0.0.1:8052 0.0.0.0:*  users:(("hapax-logos"))             — command registry WS
LISTEN 0  128   127.0.0.1:8053 0.0.0.0:*  users:(("hapax-logos"))             — frame HTTP server
LISTEN 0  128   127.0.0.1:8054 0.0.0.0:*  users:(("hapax-logos"))             — NOT metrics
```

`curl -sf http://127.0.0.1:$port/metrics` then `/metrics/` was
attempted against each. Results in the summary table below.

### Series classification per endpoint

For each live endpoint, dumped the full metric-name list, cross-
referenced against Grafana panels + alert rules, and classified every
series:

- **LIVE** — present on the endpoint, populated with non-zero values
  or monotonically incrementing counters
- **DORMANT** — defined but idle (zero value, no recent increment —
  waiting for a fault or an event to fire)
- **DEAD_CALLSITE** — defined in the producer code but no caller path
  reaches the increment (e.g., the dormant budget_signal publisher
  from Phase 3)
- **SCRAPED** — yes/no, whether the Prometheus instance ingests it

### Grafana + alert cross-reference

Read `grafana/dashboards/*.json` to enumerate every panel query.
Alert rules directory (`/etc/prometheus/rules/`) does not exist in
the Prometheus container; the stack has **no alert rules**.

## Master endpoint table

| # | endpoint | service | scraped by Prometheus? | unique series | dashboard consumers |
|---|---|---|---|---|---|
| 1 | `:9482/metrics` | studio-compositor | **NO** | 15 name prefixes, 20 series | `studio-cameras.json` (12 panels, 100% broken) |
| 2 | `:8051/metrics` | logos-api | YES (`council-cockpit`) | 26 (all generic) | indirect via misc dashboards |
| 3 | `:8051/api/predictions/metrics` | logos-api reverie monitor | YES (`reverie-predictions`, 30s cadence) | 39 (hapax_* + reverie_*) | `reverie-predictions` dashboard (localhost:3001/d/reverie-predictions/) |
| 4 | `:8050/metrics` | officium-api | YES (`officium-cockpit`) | 26 (all generic) | none |
| 5 | `:5000/metrics` | tabbyAPI | **endpoint absent** | 0 | none (cannot exist) |
| 6 | `:4000/metrics/` | LiteLLM (docker) | YES (`litellm`, via 307 follow) | 61 (cost, latency, failures, fallbacks) | LiteLLM docker dashboards |
| 7 | `:6333/metrics` | qdrant (docker) | YES (`qdrant`) | 44 (collection, shard, hardware) | qdrant dashboards |
| 8 | `:9100/metrics` | node_exporter (host) | **SCRAPE BROKEN** — timeout | 332 | host system dashboards, broken |
| 9 | `:9835/metrics` | nvidia_gpu_exporter (host) | YES (`nvidia-gpu`) | 136 (clocks, power, temp, utilization) | GPU dashboards |
| 10 | `:9090/metrics` | Prometheus self | YES (self-scrape) | 138+ | Prometheus health |
| 11 | docker: `ntfy :8090/metrics` | ntfy | NO | unknown (200 OK but not classified) | none |
| 12 | `hapax-daimonion.service` | voice daemon | **endpoint absent** | 0 | none |
| 13 | `visual-layer-aggregator.service` | perception fusion | **endpoint absent** | 0 | none |
| 14 | `hapax-imagination.service` | wgpu daemon | **endpoint absent** | 0 | none |
| 15 | `langfuse :3000` | observability | **endpoint absent** | 0 | none (langfuse is itself unobserved) |
| 16 | `grafana :3001/metrics` | Grafana | NO (not scraped) | 3046 lines of Go runtime | none |
| 17 | `postgres :5432` | postgres | **no exporter** | 0 | none |
| 18 | `clickhouse :8123` | clickhouse | **no exporter** | 0 | none |
| 19 | `redis :6379` | redis | **no exporter** | 0 | none |

**Summary:** 10 of 19 reachable services have a Prometheus endpoint;
2 of those endpoints (studio-compositor and node-exporter) are either
not scraped or broken at the scrape path; 4 of the remaining 8
endpoints expose rich, useful application data; the other 4 expose
only generic runtime metrics or are never queried by a dashboard.
Nine services have no endpoint at all.

## Deep dive: the studio-compositor scrape-gap

`prometheus.yml` (full, 66 lines):

```yaml
scrape_configs:
  - job_name: "council-cockpit"
    metrics_path: /metrics
    static_configs:
      - targets: ["host.docker.internal:8051"]
  - job_name: "officium-cockpit"
    static_configs:
      - targets: ["host.docker.internal:8050"]
  - job_name: "litellm"
    static_configs:
      - targets: ["litellm:4000"]
  - job_name: "qdrant"
    static_configs:
      - targets: ["qdrant:6333"]
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]
  - job_name: "node-exporter"
    static_configs:
      - targets: ["host.docker.internal:9100"]
  - job_name: "reverie-predictions"
    metrics_path: /api/predictions/metrics
    scrape_interval: 30s
    static_configs:
      - targets: ["host.docker.internal:8051"]
  - job_name: "nvidia-gpu"
    static_configs:
      - targets: ["host.docker.internal:9835"]
```

Eight scrape jobs. **None of them targets port 9482.** The
studio-compositor `:9482` metric endpoint is invisible to the
monitoring stack.

Verification via direct Prometheus query:

```text
$ curl -s http://127.0.0.1:9090/api/v1/label/__name__/values | \
    python3 -c "import json,sys; d=json.load(sys.stdin); \
    print(sum(1 for n in d['data'] if n.startswith('studio_')))"
0
```

Zero `studio_*` series in Prometheus. Any Grafana panel that queries
`studio_camera_frames_total`, `studio_camera_state`,
`studio_compositor_uptime_seconds`, `studio_compositor_watchdog_last_fed_seconds_ago`,
`studio_compositor_pipeline_restarts_total`, etc. returns an empty
series vector. The `studio-cameras.json` dashboard's 12 panels
consistently render "No data."

**Consequence chain.** The queue 022 Phase 4 finding that `studio_rtmp_*`
metrics are dead callsites is real, but the finding that some panels
"show the wrong number" was partially wrong for a different reason:
every panel in the studio-cameras dashboard shows nothing at all,
regardless of whether the underlying counter has been touched. The
`cameras_healthy` bug from queue 022 has zero operational impact not
because the Grafana panel uses a different query (it does — see the
Phase 2 finding) but because the Grafana panel has no data to query
against in the first place.

**Fix**: add a `studio-compositor` scrape job:

```yaml
- job_name: "studio-compositor"
  metrics_path: /metrics
  scrape_interval: 5s  # compositor is frame-rate sensitive; 5s is fine
  static_configs:
    - targets: ["host.docker.internal:9482"]
      labels:
        component: "compositor"
```

Scrape interval 5 s matches the cadence the studio-cameras dashboard's
`rate()` queries are tuned for (the `[30s]` window for
`studio_camera_frames_total` needs at least 3–6 samples per window to
be stable).

## Deep dive: the `node-exporter` broken scrape

```text
$ curl -s http://127.0.0.1:9090/api/v1/query?query=up | \
    python3 -c "import json,sys; \
    [print(f\"{r['metric']['job']:20s}={r['value'][1]}\") \
     for r in json.load(sys.stdin)['data']['result']]"
prometheus           =1
litellm              =1
qdrant               =1
nvidia-gpu           =1
officium-cockpit     =1
council-cockpit      =1
node-exporter        =0
reverie-predictions  =1
```

Error: `Get "http://host.docker.internal:9100/metrics": context deadline exceeded`.

The host-side service is alive — the host shell serves 2406 lines of
metrics from `curl http://127.0.0.1:9100/metrics`. The failure is on
the container-to-host network path, specifically for port 9100.

Diagnostic from inside the container:

```text
$ docker exec prometheus nslookup host.docker.internal
Server:   127.0.0.11
Address:  127.0.0.11:53
** server can't find host.docker.internal: NXDOMAIN

$ docker exec prometheus wget -q -O - --timeout=3 http://172.17.0.1:9100/metrics
wget: download timed out

$ docker exec prometheus wget -q -O - --timeout=3 http://172.18.0.1:9100/metrics
wget: download timed out
```

`nslookup` returns NXDOMAIN inside the container. The container's
`/etc/hosts` has a static entry `172.17.0.1 host.docker.internal` (the
`host-gateway` alias from the compose `extra_hosts` config), so the
entry exists in the hosts file even though the DNS resolver cannot
find it. Prometheus itself resolves through a different code path and
successfully hits `:8051`, `:8050`, `:9835` via `host.docker.internal` —
five of the eight scrape jobs talk to the host through the same DNS
name. Only port 9100 is unreachable from the container.

Two plausible causes:

1. **node_exporter is bound but firewalled** from container-to-host
   traffic on port 9100. The host's nftables rule set has explicit
   allow for container networks on :8050 / :8051 / :9835 but not
   :9100. This is the most likely explanation given the specificity of
   the failure.
2. **`nftables docker chain`** has been reloaded out-of-band and
   the Docker bridge's outbound rule lost its masquerade. Less likely
   but possible; would be easy to rule out with `nft list ruleset`.

Both fixes are host-side, not container-side. Evidence collection for
the next session: `sudo nft list ruleset | grep -E '(9100|9835|8051)'`
to see if the firewall has a 9100 entry.

## Deep dive: three missing hapax endpoints

### `hapax-daimonion.service` (voice daemon)

Status: alive (PID ~2902187, lingered, 5h+ uptime).

Prometheus instrumentation: none.

Journal grep: no `prometheus`, `metrics_server`, `start_http_server`,
or `prometheus_client` reference. The daimonion is built around an
`asyncio.start_unix_server`-based UDS server pattern (the new TtsServer,
HotkeyServer) and has no HTTP server at all.

What it would want to expose:

- CPAL state (listening / thinking / speaking / idle) + transition counts
- TTS synthesize call counts, latency, errors (alpha's post-Option-A
  UDS path in particular — beta observed a `tts client: synthesize
  timed out after 30.0s` on the compositor side at 17:01:03 today,
  which corresponds to an untraced daimonion-side event)
- STT transcription latency, VAD flip counts, wake-word fires
- Watchdog freshness + ratio-of-expected-ticks
- Active affordance count, recruitment-threshold crossings
- Working-mode + stance transitions
- VRAM allocated by the daimonion's STT model

Implementation pattern: add `prometheus_client.start_http_server(9483)`
to `daemon.py::_init_core_subsystems`, import `metrics.py` with
module-level Counter/Gauge definitions mirroring the compositor
pattern. Zero extra processes, zero new dependencies. Estimated
scope: 300 lines for a minimum useful set.

### `visual-layer-aggregator.service`

Status: alive (PID 8568, 4h55m uptime at measurement time).

Prometheus instrumentation: none.

What it would want to expose:

- Per-dimension current value + per-dimension source attribution
- Stance transitions + hysteresis dwell times
- Perception backend health (ir_presence, contact_mic_ir, watch,
  fortress camera)
- Fusion freshness (how stale is each input source)
- Exploration aggregate boredom / curiosity / deficit
- Stimmung → stance transition latency

Implementation pattern: identical to daimonion. Port `9484`.

### `hapax-imagination.service` (Rust wgpu)

Status: alive (PID 3084028).

Prometheus instrumentation: none.

What it would want to expose:

- Frame rate + frame-time budget
- `DynamicPipeline::pool_metrics()` — bucket count, total textures,
  acquires, allocations, reuse ratio (already exposed from Rust, just
  not lifted to Prometheus)
- Shader compile count + duration
- Uniform buffer update rate
- SHM write count + last-write age

This one is Rust-side. The `prometheus` crate in Rust provides an
in-process exporter. Alpha has this as task #10 in the backlog
already — suggested port `:9485`. The existence of beta's phase 6
finding makes the case stronger: the imagination daemon is the
single largest invisible consumer in the stack.

## Deep dive: observation on `reverie-predictions` scrape

One surprise in the audit: the `reverie-predictions` job scrapes a
rich `hapax_*`/`reverie_*` series set at `host.docker.internal:8051/api/predictions/metrics`
on a 30 s cadence. The 39 series include:

```text
hapax_dmn_tick                    — DMN tick counter
hapax_dmn_uptime_s                — daimonion uptime
hapax_dmn_buffer_entries          — DMN buffer depth
hapax_dmn_satellites_active       — reverie satellite count
hapax_cpal_gain                   — voice gain modulation value
hapax_cpal_error                  — cpal error count
hapax_capability_uses             — affordance use counter
hapax_content_sources_active      — active content source count
hapax_exploration_boredom         — exploration boredom aggregate
hapax_exploration_coherence       — exploration coherence aggregate
hapax_exploration_curiosity       — exploration curiosity aggregate
hapax_exploration_error           — exploration error count
hapax_exploration_stagnation_s    — stagnation duration
hapax_feature_flag                — feature flag gauge
hapax_hebbian_associations        — hebbian association count
hapax_imagination_continuation    — imagination continuation flag
hapax_imagination_dimension       — per-dimension value
hapax_imagination_salience        — salience aggregate
hapax_mesh_error                  — mesh error count
hapax_mesh_perception             — perception aggregate
reverie_prediction_actual         — prediction actual value
reverie_prediction_healthy        — prediction health flag
reverie_hours_since_deploy        — hours since last reverie deploy
reverie_alert_count               — active alert count
reverie_uniform_value             — per-uniform GPU value
```

This is the current primary path for cross-system hapax observability.
It sidesteps the compositor / daimonion / VLA missing-endpoints gap
by aggregating everything through a single logos-api route that reads
`/dev/shm/hapax-*` files + makes subprocess queries. The data is
rich, but the collection path is indirect:

- 30 s cadence means all `hapax_*` metrics lag by ≤ 30 s
- File-poll-based collection means the exporter cannot see
  high-cardinality detail (e.g., per-satellite timings, per-turn
  latency)
- It is a single point of failure — `logos-api` dying would take
  out the entire custom metric set
- Cross-cuts clean responsibility lines — reverie metrics, CPAL
  metrics, exploration metrics, DMN metrics, capability metrics all
  flow through one unrelated route

This is a valid short-term pattern but is not the long-term shape.
The right pattern is per-daemon in-process exporters, as recommended
above for daimonion / VLA / imagination. The predictions endpoint
should decay to exposing only the prediction-monitor's own state
(which predictions it is checking, what their thresholds are) and
leave the underlying metrics to the daemons that produce them.

## Ranked observability gap list (top 10)

| rank | gap | severity | effort | evidence-backed |
|---|---|---|---|---|
| 1 | studio-compositor not in `prometheus.yml` scrape config | HIGH | 5 lines of yaml + prometheus restart | `series_count({__name__=~"studio_.*"})=0` |
| 2 | node-exporter scrape broken (firewall or DNS) | HIGH | host firewall rule | `up{job="node-exporter"}=0`, `context deadline exceeded` |
| 3 | hapax-daimonion has no Prometheus endpoint | HIGH | 300 lines for a minimum set | source grep returns nothing; TTS UDS timeout at 17:01:03 today is ungauged |
| 4 | visual-layer-aggregator has no Prometheus endpoint | HIGH | 200 lines | source grep |
| 5 | hapax-imagination (Rust wgpu) has no Prometheus endpoint | HIGH | Rust `prometheus` crate integration; alpha task #10 already tracks this | source grep |
| 6 | tabbyAPI has no `/metrics` endpoint at `:5000` | MEDIUM | upstream project PR or sidecar exporter | `curl :5000/metrics → fail` |
| 7 | Prometheus has no alert rules (`/etc/prometheus/rules/` does not exist) | MEDIUM | an initial rule file covering scrape-down + compositor OOM + VRAM ceiling + disk-full | `docker exec prometheus ls /etc/prometheus/rules` → not found |
| 8 | logos-api `:8051/metrics` exposes only generic process metrics | MEDIUM | add 10–20 application-level counters | endpoint dump shows only `process_*` / `python_gc_*` / `http_*` |
| 9 | officium-api `:8050/metrics` same gap | MEDIUM | same as #8 | same |
| 10 | LiteLLM scrape uses `/metrics` but server responds 307 to `/metrics/` | LOW | 1 line yaml change | `curl -v :4000/metrics → 307 /metrics/` |
| 11 (bonus) | budget_signal + budget Phase 7 publishers are dormant — see Phase 3 | MEDIUM (correctness) | per Phase 3 retire recommendation | Phase 3 detail |
| 12 (bonus) | Grafana has no dashboard panel for `nvidia_gpu_exporter` series | LOW | add a GPU stat panel to the studio-cameras dashboard | manual inspection of panels |
| 13 (bonus) | langfuse is itself unobserved (no `/metrics`) | LOW | langfuse team's problem; nothing to do in-repo | `curl :3000/metrics → fail` |

## Backlog additions (for retirement handoff)

1. **`fix(monitoring): add studio-compositor scrape job to prometheus.yml`** — trivial, 5 lines. Should ship as a dedicated PR because it affects the Docker-compose observability stack and is the kind of change the operator wants visible.
2. **`fix(monitoring): diagnose + fix node-exporter scrape gap`** — probably a host-side firewall fix. File as a distro-work ticket. Run `sudo nft list ruleset | grep 9100` as the first diagnostic.
3. **`feat(daimonion): in-process Prometheus exporter`** — new module `agents/hapax_daimonion/metrics.py` + `start_http_server(9483)` in daemon startup. Mirror the compositor pattern. Initial series list: CPAL state + TTS latency + STT latency + watchdog + affordance use + VRAM.
4. **`feat(vla): in-process Prometheus exporter`** — new module `agents/visual_layer_aggregator/metrics.py` + `start_http_server(9484)`. Initial series: per-dimension values + stance state + per-backend freshness.
5. **`feat(imagination): Prometheus exporter via Rust prometheus crate`** — alpha already has this as task #10. Include `DynamicPipeline::pool_metrics()` export + shader compile timing + frame-time histogram.
6. **`feat(monitoring): initial alert rules`** — file `monitoring/alerts/basic.yml` with at minimum: `up == 0` for 2 min, `studio_compositor_watchdog_last_fed_seconds_ago > 30`, `nvidia_smi_memory_used_bytes / _total_bytes > 0.9`, `node_memory_MemAvailable_bytes < 2e9`, `compositor_publish_degraded_failed_total > 0`. Wire through Alertmanager to ntfy.
7. **`fix(monitoring): LiteLLM scrape path`** — change `metrics_path: /metrics` to `metrics_path: /metrics/` for the litellm job. One-line diff; zero risk.
8. **`chore(monitoring): enumerate and fix Grafana panels broken by upstream metric changes`** — the studio-cameras dashboard is end-to-end dead until #1 lands; pre-emptive check of other dashboards for the same class of issue.
9. **`feat(logos-api): application-level metrics beyond process_*`** — add counters for agent runs, LLM call counts per model, consent-gate denials, affordance recruitment counts, SDLC state transitions.
10. **`feat(tabbyapi): expose /metrics via a sidecar or upstream PR`** — GPU inference observability is entirely absent below the nvidia_gpu_exporter layer. Low urgency (the exporter covers hardware) but medium cost (an upstream contribution).
