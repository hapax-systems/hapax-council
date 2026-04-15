# Prometheus alert-rule ↔ metric cross-reference audit

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #148)
**Scope:** Verify every Prometheus alert rule in `~/llm-stack/grafana/provisioning/alerting/rules.yaml` references a metric that actually exists in the running Prometheus. First of 3 follow-up audits proposed in queue #132 (Prometheus metrics registry audit).
**Register:** scientific, neutral

## 1. Headline

**2 ORPHAN ALERTS found.** Both reference metric names that do not exist in the current Prometheus registry — the alerts will never fire.

| # | Alert UID | Referenced metric (wrong) | Actual metric (right) | Severity |
|---|---|---|---|---|
| O1 | `gpu-temp-high` | `nvidia_gpu_temperature_celsius` | `nvidia_smi_temperature_gpu` | **HIGH** — GPU thermal safety monitoring is silently broken |
| O2 | `qdrant-latency-high` | `qdrant_rest_response_duration_seconds_bucket` | `rest_responses_duration_seconds_bucket` (no `qdrant_` prefix) | MEDIUM — Qdrant latency monitoring silently broken |

**4 other alerts** (disk-usage-high, litellm-error-rate, cockpit-error-rate, scrape-target-down) reference metrics that do exist and have current samples.

**Additional observation:** **zero alert rules cover studio-compositor metrics** despite the compositor defining 41 Prometheus metrics (per queue #132 audit). This is an alert-coverage gap, not a drift.

## 2. Method

```bash
# Alert rule file
cat ~/llm-stack/grafana/provisioning/alerting/rules.yaml

# Extract metric names from expr: fields
grep -A 2 "^              expr:" rules.yaml

# Verify each metric exists via Prometheus query API
for metric in <list>; do
  curl -s "http://localhost:9090/api/v1/query?query=$metric" | jq .data.result
done

# List all known metric names
curl -s 'http://localhost:9090/api/v1/label/__name__/values' | jq .data
```

## 3. Alert rules inventory

`~/llm-stack/grafana/provisioning/alerting/rules.yaml` contains 6 alert rules in one group (`infrastructure`, 5m interval, `hapax-alerts` folder):

| UID | Title | Metric expression | Severity label |
|---|---|---|---|
| `disk-usage-high` | Disk usage >90% | `100 - (node_filesystem_avail_bytes{fstype!~"tmpfs\|devtmpfs\|overlay"} / node_filesystem_size_bytes{...} * 100)` | critical |
| `qdrant-latency-high` | Qdrant p99 latency >2s | `histogram_quantile(0.99, sum(rate(qdrant_rest_response_duration_seconds_bucket[5m])) by (le))` | critical |
| `litellm-error-rate` | LiteLLM error rate >5% | `sum(rate(litellm_request_total_latency_metric_count{status_code=~"5.."}[5m])) / sum(rate(litellm_request_total_latency_metric_count[5m]))` | warning |
| `gpu-temp-high` | GPU temperature >85C | `nvidia_gpu_temperature_celsius` | warning |
| `cockpit-error-rate` | Cockpit API error rate >5% | `sum(rate(http_requests_total{job=~".*cockpit",status=~"5.."}[5m])) / sum(rate(http_requests_total{job=~".*cockpit"}[5m]))` | warning |
| `scrape-target-down` | Prometheus scrape target down | `up == 0` | critical |

## 4. Per-metric verification

### 4.1 `disk-usage-high` — ✓ HEALTHY

- **Referenced:** `node_filesystem_avail_bytes` + `node_filesystem_size_bytes`
- **Live query:** 15 samples each
- **Source:** node-exporter
- **Verdict:** healthy, alert will fire correctly

### 4.2 `qdrant-latency-high` — ❌ ORPHAN (O2, MEDIUM)

- **Referenced:** `qdrant_rest_response_duration_seconds_bucket`
- **Live query:** **0 samples**
- **Problem:** metric name is wrong. The running Qdrant exposes `rest_responses_duration_seconds_bucket` (without the `qdrant_` prefix).
- **Actual metric names** (verified via `/api/v1/label/__name__/values`):
  - `rest_responses_avg_duration_seconds`
  - `rest_responses_duration_seconds_bucket`
  - `rest_responses_duration_seconds_count`
  - `rest_responses_duration_seconds_sum`
  - `rest_responses_max_duration_seconds`
  - `rest_responses_min_duration_seconds`
  - `rest_responses_total`
- **Also:** no metrics with `job=qdrant` label at all — Qdrant may be exposing metrics under a different job label.
- **Remediation:** update the alert rule to use the correct metric name:
  ```yaml
  expr: >
    histogram_quantile(0.99,
      sum(rate(rest_responses_duration_seconds_bucket[5m])) by (le))
  ```

### 4.3 `litellm-error-rate` — ✓ HEALTHY

- **Referenced:** `litellm_request_total_latency_metric_count`
- **Live query:** 2 samples
- **Source:** LiteLLM container `/metrics` endpoint
- **Verdict:** healthy, alert will fire correctly (low sample count is normal — this is rate()-derived)

### 4.4 `gpu-temp-high` — ❌ ORPHAN (O1, HIGH severity)

- **Referenced:** `nvidia_gpu_temperature_celsius`
- **Live query:** **0 samples**
- **Problem:** metric name is wrong. The running NVIDIA exporter exposes `nvidia_smi_temperature_gpu`.
- **Actual metric names** (verified, filtered for `nvidia/gpu`):
  - `nvidia_smi_temperature_gpu` — the one we want
  - `nvidia_smi_temperature_gpu_tlimit`
  - `node_hwmon_temp_celsius`, `node_thermal_zone_temp` (host-level, not GPU-specific)
- **Why this is HIGH severity:** GPU thermal safety monitoring is silently broken. A GPU overheating event would not fire the alert — the operator would only notice via visible glitches or the hardware watchdog.
- **Remediation:** update the alert rule to use the correct metric name:
  ```yaml
  expr: nvidia_smi_temperature_gpu
  ```
  Threshold may also need recalibration depending on the exporter's unit (°C vs °F).

### 4.5 `cockpit-error-rate` — ✓ HEALTHY

- **Referenced:** `http_requests_total{job=~".*cockpit"}`
- **Live query:** 20 samples
- **Source:** council-cockpit + officium-cockpit FastAPI instrumentation
- **Verdict:** healthy

### 4.6 `scrape-target-down` — ✓ HEALTHY

- **Referenced:** `up == 0`
- **Live query:** 9 samples (one per scrape target)
- **Source:** Prometheus meta-metric, always present
- **Verdict:** healthy, alert will fire correctly if any target goes DOWN

## 5. Coverage-gap analysis

### 5.1 Studio-compositor metrics have zero alert coverage

Per queue #132 audit, `agents/studio_compositor/metrics.py` defines **41 Prometheus metrics**:

- Camera metrics: CAM_FRAMES_TOTAL, CAM_KERNEL_DROPS_TOTAL, CAM_BYTES_TOTAL, CAM_LAST_FRAME_AGE, CAM_FRAME_INTERVAL, CAM_STATE, CAM_TRANSITIONS_TOTAL, CAM_RECONNECT_ATTEMPTS_TOTAL, CAM_CONSECUTIVE_FAILURES, CAM_IN_FALLBACK, CAM_FRAME_FLOW_STALE_TOTAL
- Compositor core: COMP_VOICE_ACTIVE, COMP_MUSIC_DUCKED, COMP_GLFEEDBACK_RECOMPILE_TOTAL, COMP_BOOT_TIMESTAMP, COMP_UPTIME, COMP_WATCHDOG_LAST_FED, COMP_CAMERAS_TOTAL, COMP_CAMERAS_HEALTHY, COMP_PIPELINE_RESTARTS_TOTAL, COMP_PROCESS_FD_COUNT, COMP_CAMERA_REBUILD_TOTAL, COMP_PIPELINE_TEARDOWN_DURATION_MS, COMP_SOURCE_RENDER_DURATION_MS
- ... and ~15 more

**Zero alert rules reference any of these.** The studio-compositor exposes metrics at `:9482` and is scraped (per queue #132 — target is UP), but nothing alerts on frame stalls, watchdog timeouts, camera failures, etc.

**This matches queue #128 (LRR Phase 10 §3.3 18-item stability matrix runbook).** The 18 signals in that runbook ARE the alert-rule gap — Phase 10 §3.3 execution session will author alert rules covering these metrics.

**Not a drift finding.** Coverage gap is expected pending Phase 10 §3.3 execution.

### 5.2 What alert coverage exists today vs what should exist

| Category | Current alerts | Referenced in queue #128 stability matrix |
|---|---|---|
| Disk / inode usage | 1 (disk-usage-high) | S15 (`/data` inode), S16 (`/dev/shm`) |
| Qdrant latency | 1 (broken — see O2) | not directly, but Q023 audit |
| LiteLLM errors | 1 | not in matrix |
| GPU temperature | 1 (broken — see O1) | not in matrix directly |
| Cockpit errors | 1 | not in matrix directly |
| Scrape health | 1 (up == 0) | S10 (Pi heartbeats), S11 (pipewire alive) |
| **Studio-compositor frame/camera** | **0** | **S1-S6, S14 (14 total)** |
| **HLS / mediamtx** | **0** | **S13, S17** |
| **Memory growth** | **0** | **S2, S7** |
| **Rebuild interference** | **0** | **S18** |

Current infrastructure alert coverage is thin. The Phase 10 §3.3 execution will dramatically expand it. Until then, studio-compositor is uninstrumented at the alert level.

## 6. Remediation proposals

### 6.1 Priority (file as follow-up queue items)

1. **Fix O1 (gpu-temp-high)** — rename metric reference to `nvidia_smi_temperature_gpu`. **HIGH severity** because GPU thermal safety is silently broken. 1-line yaml change in `rules.yaml`, 10 min including restart.
2. **Fix O2 (qdrant-latency-high)** — rename metric reference to `rest_responses_duration_seconds_bucket` (drop `qdrant_` prefix). Verify exporter job label. 1-line yaml change, 10 min.

Both fixes are cross-repo (they touch `~/llm-stack/grafana/provisioning/alerting/rules.yaml`, not this council repo). They should either be shipped directly to the llm-stack + a restart, OR be a separate follow-up queue item for delta.

### 6.2 Deferred (already tracked by other queue items)

- **Studio-compositor alert coverage** — Phase 10 §3.3 execution via queue #128 stability matrix runbook. Already tracked; no new work needed here.
- **Additional scrape target verification** — queue #132 follow-up #3 (per-target metric-count verification).

## 7. Closing

6 alert rules audited. **2 ORPHANS found** (gpu-temp-high, qdrant-latency-high) — both reference metric names that do not exist in the running Prometheus. The GPU thermal alert is a **HIGH-severity silent-broken** case. Alpha recommends immediate remediation of both orphan alerts + continuation of queue #128 Phase 10 §3.3 stability matrix work for the studio-compositor alert-coverage gap.

Branch-only commit per queue item #148 acceptance criteria.

## 8. Cross-references

- Queue item #132 (PR #891): Prometheus metrics registry audit — upstream
- Queue item #128 (PR #887): LRR Phase 10 §3.3 stability matrix runbook
- `~/llm-stack/grafana/provisioning/alerting/rules.yaml` — alert rule source
- Prometheus targets API: `http://localhost:9090/api/v1/targets`
- Prometheus metric names API: `http://localhost:9090/api/v1/label/__name__/values`

— alpha, 2026-04-15T21:02Z
