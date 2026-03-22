# H3: Prometheus + Grafana Deployment Plan

**Date:** 2026-03-12
**Status:** Draft
**Scope:** Add Prometheus and Grafana to the Docker LLM stack, scrape all existing `/metrics` endpoints, build a starter dashboard.

---

## 1. Current Stack Topology

The existing `~/llm-stack/docker-compose.yml` runs two profiles:

| Service | Port(s) | Profile |
|---------|---------|---------|
| Qdrant | 6333, 6334 | core |
| PostgreSQL | 5432 | core |
| LiteLLM | 4000 | core |
| Redis | 6379 | full |
| ClickHouse | 8123, 9000 | full |
| Langfuse Worker | 3030 | full |
| Langfuse | 3000 | full |
| Open WebUI | 8080 | full |
| n8n | 5678 | full |
| ntfy | 8090 | full |
| MinIO | 9001, 9002 | full |

Host services (not in Docker):

| Service | Port | Notes |
|---------|------|-------|
| hapax-council cockpit-api | 8051 | FastAPI, `/metrics` endpoint (prometheus-fastapi-instrumentator) |
| hapax-officium cockpit-api | 8050 | FastAPI, `/metrics` endpoint (prometheus-fastapi-instrumentator) |
| Ollama | 11434 | CUDA, no native Prometheus endpoint |

## 2. Existing Metrics Endpoints

Both cockpit APIs already expose Prometheus metrics via `prometheus-fastapi-instrumentator`:

- **Council:** `http://host.docker.internal:8051/metrics` -- request count, latency histograms, in-progress requests, error counts by status code
- **Officium:** `http://host.docker.internal:8050/metrics` -- same instrumentator, same metric families

LiteLLM exposes a built-in Prometheus endpoint at `/metrics` when `prometheus` is in `success_callback`. Currently not enabled -- needs a config change (see section 5).

Qdrant exposes metrics at `http://qdrant:6333/metrics` (built-in, always on).

No existing `prometheus.yml` or Grafana provisioning configs exist in the stack.

## 3. Port Assignments

| Service | Port | Rationale |
|---------|------|-----------|
| Prometheus | 9090 | Standard default, not in use |
| Grafana | 3001 | Langfuse occupies 3000 |

## 4. Docker-Compose Additions

Add to `~/llm-stack/docker-compose.yml` under the `full` profile:

```yaml
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    profiles: [full]
    ports:
      - "127.0.0.1:9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - /home/operator/llm-data/prometheus:/prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time=30d"
      - "--web.enable-lifecycle"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    mem_limit: 1g
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:9090/-/healthy"]
      interval: 30s
      timeout: 10s
      retries: 3

  grafana:
    image: grafana/grafana-oss:latest
    container_name: grafana
    profiles: [full]
    ports:
      - "127.0.0.1:3001:3000"
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-hapax}
      GF_SERVER_ROOT_URL: http://localhost:3001
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - /home/operator/llm-data/grafana:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    depends_on:
      prometheus:
        condition: service_healthy
    mem_limit: 512m
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:3000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

## 5. Prometheus Scrape Config

Create `~/llm-stack/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  # --- Cockpit APIs (host services) ---
  - job_name: "council-cockpit"
    metrics_path: /metrics
    static_configs:
      - targets: ["host.docker.internal:8051"]
        labels:
          project: "hapax-council"
          component: "cockpit-api"

  - job_name: "officium-cockpit"
    metrics_path: /metrics
    static_configs:
      - targets: ["host.docker.internal:8050"]
        labels:
          project: "hapax-officium"
          component: "cockpit-api"

  # --- LiteLLM (container) ---
  # Requires adding "prometheus" to success_callback in litellm-config.yaml
  # and setting LITELLM_PROMETHEUS=true env var
  - job_name: "litellm"
    metrics_path: /metrics
    static_configs:
      - targets: ["litellm:4000"]
        labels:
          component: "llm-proxy"

  # --- Qdrant (container, built-in metrics) ---
  - job_name: "qdrant"
    metrics_path: /metrics
    static_configs:
      - targets: ["qdrant:6333"]
        labels:
          component: "vector-db"

  # --- Prometheus self-monitoring ---
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  # --- NVIDIA GPU (nvidia-gpu-exporter on host) ---
  # Requires nvidia_gpu_exporter running on host:9835
  # Install: paru -S nvidia_gpu_exporter
  # Or run container: see section 7
  - job_name: "nvidia-gpu"
    static_configs:
      - targets: ["host.docker.internal:9835"]
        labels:
          component: "gpu"

  # --- Node exporter (optional, system-level metrics) ---
  # Install: pacman -S prometheus-node-exporter
  # Enable: systemctl enable --now prometheus-node-exporter
  - job_name: "node"
    static_configs:
      - targets: ["host.docker.internal:9100"]
        labels:
          component: "host"
```

### LiteLLM Config Change

In `~/llm-stack/litellm-config.yaml`, update `litellm_settings`:

```yaml
litellm_settings:
  success_callback: ["langfuse", "prometheus"]
  failure_callback: ["langfuse", "prometheus"]
```

And add to the LiteLLM service environment in docker-compose.yml:

```yaml
  LITELLM_PROMETHEUS: "true"
```

## 6. Grafana Provisioning

### Directory Structure

```
~/llm-stack/grafana/
  provisioning/
    datasources/
      prometheus.yaml
    dashboards/
      default.yaml
      json/
        hapax-overview.json
```

### Datasource: `grafana/provisioning/datasources/prometheus.yaml`

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

### Dashboard provider: `grafana/provisioning/dashboards/default.yaml`

```yaml
apiVersion: 1
providers:
  - name: default
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /etc/grafana/provisioning/dashboards/json
      foldersFromFilesStructure: false
```

### Dashboard JSON: `grafana/provisioning/dashboards/json/hapax-overview.json`

The starter dashboard should contain the following panels (build as provisioned JSON or create manually on first boot, then export):

## 7. Dashboard Panels

### Row 1: API Request Metrics

| Panel | Type | Query (PromQL) |
|-------|------|----------------|
| Request Rate | Time series | `rate(http_requests_total{job=~"council.*\|officium.*"}[5m])` |
| Request Latency p50 | Time series | `histogram_quantile(0.5, rate(http_request_duration_seconds_bucket{job=~"council.*\|officium.*"}[5m]))` |
| Request Latency p95 | Time series | `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job=~"council.*\|officium.*"}[5m]))` |
| Request Latency p99 | Time series | `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{job=~"council.*\|officium.*"}[5m]))` |
| Error Rate (5xx) | Time series | `rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])` |
| In-Progress Requests | Gauge | `http_requests_in_progress{job=~"council.*\|officium.*"}` |

Note: `prometheus-fastapi-instrumentator` exposes metrics with the prefix `http_` by default. The exact metric names are:
- `http_request_duration_seconds_bucket` (histogram)
- `http_requests_total` (counter)
- `http_requests_in_progress` (gauge)

Verify actual names by curling `http://localhost:8051/metrics` once the service is running.

### Row 2: LiteLLM / Token Usage

| Panel | Type | Query (PromQL) |
|-------|------|----------------|
| LLM Requests/sec | Time series | `rate(litellm_requests_metric_total[5m])` |
| Total Tokens (by model) | Time series | `rate(litellm_total_tokens_total[5m])` |
| Prompt vs Completion Tokens | Stacked bar | `rate(litellm_prompt_tokens_total[5m])` / `rate(litellm_completion_tokens_total[5m])` |
| LLM Request Latency | Time series | `histogram_quantile(0.95, rate(litellm_request_total_latency_metric_bucket[5m]))` |
| LLM Error Rate | Stat | `rate(litellm_error_metric_total[5m])` |
| Spend by Model | Table | `litellm_spend_metric_total` |

### Row 3: Qdrant

| Panel | Type | Query (PromQL) |
|-------|------|----------------|
| Collection Point Count | Bar gauge | `qdrant_points_total` |
| Collection Count | Stat | `qdrant_collections_total` |
| gRPC Request Duration | Time series | `histogram_quantile(0.95, rate(qdrant_grpc_responses_duration_seconds_bucket[5m]))` |
| REST Request Duration | Time series | `histogram_quantile(0.95, rate(qdrant_rest_responses_duration_seconds_bucket[5m]))` |

### Row 4: GPU (NVIDIA)

Requires `nvidia_gpu_exporter` on the host. Install options:

**Option A -- AUR package:**
```bash
paru -S nvidia_gpu_exporter-bin
sudo systemctl enable --now nvidia_gpu_exporter
```

**Option B -- Docker container (add to docker-compose.yml):**
```yaml
  nvidia-gpu-exporter:
    image: utkuozdemir/nvidia_gpu_exporter:1.2.1
    container_name: nvidia-gpu-exporter
    profiles: [full]
    ports:
      - "127.0.0.1:9835:9835"
    devices:
      - /dev/nvidiactl:/dev/nvidiactl
      - /dev/nvidia0:/dev/nvidia0
      - /dev/nvidia-uvm:/dev/nvidia-uvm
    volumes:
      - /usr/bin/nvidia-smi:/usr/bin/nvidia-smi:ro
      - /usr/lib/libnvidia-ml.so.1:/usr/lib/libnvidia-ml.so.1:ro
    mem_limit: 128m
    restart: unless-stopped
```

Option A is recommended since `nvidia-smi` is a host binary and device pass-through is fragile.

| Panel | Type | Query (PromQL) |
|-------|------|----------------|
| GPU Temperature | Gauge | `nvidia_gpu_temperature_celsius` |
| GPU Utilization % | Time series | `nvidia_gpu_duty_cycle` |
| VRAM Used / Total | Bar gauge | `nvidia_gpu_memory_used_bytes / nvidia_gpu_memory_total_bytes * 100` |
| VRAM Used (absolute) | Time series | `nvidia_gpu_memory_used_bytes` |
| GPU Power Draw | Time series | `nvidia_gpu_power_draw_watts` |
| Fan Speed | Gauge | `nvidia_gpu_fan_speed_percent` |

### Row 5: Infrastructure (optional, with node_exporter)

| Panel | Type | Query (PromQL) |
|-------|------|----------------|
| CPU Usage | Time series | `100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)` |
| RAM Usage | Gauge | `(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100` |
| Disk Usage /data | Gauge | `(1 - node_filesystem_avail_bytes{mountpoint="/data"} / node_filesystem_size_bytes{mountpoint="/data"}) * 100` |
| Network I/O | Time series | `rate(node_network_receive_bytes_total{device="enp6s0"}[5m])` |

## 8. Storage Estimate (30-day retention)

Assumptions:
- 5 scrape targets at 15s intervals = 20 scrapes/min
- ~200 unique time series per target (FastAPI instrumentator ~50, LiteLLM ~80, Qdrant ~40, GPU exporter ~20, Prometheus self ~10)
- Total: ~1000 active time series
- Prometheus TSDB: ~1-2 bytes per sample after compression
- Samples per day: 1000 series x (86400/15) samples = 5,760,000 samples/day
- 30 days: ~172.8M samples
- At ~1.5 bytes/sample: **~260 MB for 30 days**

With node_exporter (adds ~800 series): estimate climbs to ~700 MB.

**Allocate 2 GB** for `/home/operator/llm-data/prometheus` to be safe (WAL, compaction overhead).

Grafana storage is negligible (<100 MB for dashboards and SQLite).

## 9. Data Directory Setup

```bash
mkdir -p /home/operator/llm-data/prometheus
mkdir -p /home/operator/llm-data/grafana
mkdir -p ~/llm-stack/grafana/provisioning/datasources
mkdir -p ~/llm-stack/grafana/provisioning/dashboards/json
```

## 10. Implementation Steps

1. Create data directories (section 9)
2. Write `~/llm-stack/prometheus.yml` (section 5)
3. Write Grafana provisioning files (section 6)
4. Update `litellm-config.yaml` to add `"prometheus"` callback (section 5)
5. Add `LITELLM_PROMETHEUS=true` to LiteLLM env in docker-compose.yml
6. Add `prometheus` and `grafana` services to docker-compose.yml (section 4)
7. Install `nvidia_gpu_exporter` on host (section 7, option A)
8. Optionally install `prometheus-node-exporter` (`pacman -S prometheus-node-exporter && sudo systemctl enable --now prometheus-node-exporter`)
9. Restart the stack: `cd ~/llm-stack && docker compose --profile full up -d`
10. Verify Prometheus targets: `http://localhost:9090/targets`
11. Log into Grafana: `http://localhost:3001` (admin / env password)
12. Build or import the dashboard (create manually from PromQL in section 7, then export JSON to provisioning dir)

## 11. Verification Checklist

- [ ] Prometheus is up at `http://localhost:9090` and shows healthy
- [ ] All scrape targets show `UP` at `http://localhost:9090/targets`:
  - [ ] `council-cockpit` (host.docker.internal:8051)
  - [ ] `officium-cockpit` (host.docker.internal:8050)
  - [ ] `litellm` (litellm:4000)
  - [ ] `qdrant` (qdrant:6333)
  - [ ] `nvidia-gpu` (host.docker.internal:9835)
  - [ ] `prometheus` (localhost:9090)
  - [ ] `node` (host.docker.internal:9100) -- optional
- [ ] Grafana is up at `http://localhost:3001`
- [ ] Prometheus datasource is auto-provisioned and shows green in Grafana > Settings > Data Sources
- [ ] Run a test query in Grafana Explore: `up` returns all targets
- [ ] `curl -s http://localhost:8051/metrics | head` returns Prometheus text format
- [ ] `curl -s http://localhost:8050/metrics | head` returns Prometheus text format
- [ ] `curl -s http://localhost:4000/metrics | head` returns LiteLLM metrics
- [ ] LiteLLM token metrics populate after sending a test request via `m "hello"`
- [ ] GPU metrics appear: `nvidia_gpu_temperature_celsius` returns a value
- [ ] Qdrant metrics appear: `qdrant_points_total` returns collection sizes
- [ ] Dashboard panels render without "No data" warnings

## 12. Future Enhancements

- **Alerting:** Add Alertmanager for GPU temp > 85C, error rate > 5%, disk > 90%. Route to ntfy (already in stack at :8090).
- **Langfuse metrics:** Langfuse v3 does not expose a `/metrics` endpoint natively. Monitor via PostgreSQL/ClickHouse queries or wait for upstream support.
- **Docker container metrics:** Add cAdvisor for per-container CPU/memory/network.
- **Loki:** Add log aggregation (Grafana Loki) for centralized log search alongside metrics.
- **Recording rules:** Pre-compute expensive quantile queries as recording rules to speed up dashboard load.
