# Sprint 6 — Observability + Reliability

**Date:** 2026-04-13 CDT
**Theme coverage:** N1-N6 (metric coverage, scrape, dashboards, alerts, frame histograms, log/trace plumbing), O1-O6 (watchdogs, restart cascade, recovery FSM, graceful degradation, dependency ordering, postmortem capture)
**Register:** scientific, neutral

## Headline

**Eight findings in Sprint 6:**

1. **Compositor exposes 122 metrics** at `127.0.0.1:9482/metrics` covering camera state machine, kernel drops, frame rate, RTMP encoder, reverie pool, watchdog, source freshness — comprehensive. The metric *production* side is in good shape.
2. **studio-compositor is STILL NOT in Prometheus's scrape targets.** This is queue 024 FINDING-H. Backlog item 47 (`fix(llm-stack): add studio-compositor scrape job to prometheus.yml`) is the open ticket. **PR #755's wiring work, queue 024's audit, queue 026's pickup — none have closed this. The dashboards are flying blind.**
3. **`node-exporter :9100` is DOWN.** Host-level metrics (CPU, memory, disk, network, USB error counters, load average) are not flowing into Prometheus. This is a silent observability gap on the rig itself.
4. **`nvidia-gpu :9835` is UP** but per-GPU labeling needs verification. After the dual-GPU migration, per-GPU breakdown is essential — single-GPU dashboards will hide GPU 1 contention.
5. **FreshnessGauge hyphen bug from Sprint 2 F1 is CONFIRMED in live metrics.** Only 4 cairo source freshness gauges appear: `token_pole`, `album`, `stream_overlay`, `sierpinski`. The 8 hyphenated ones (`brio-operator`, `brio-room`, `brio-synths`, `c920-desk`, `c920-room`, `c920-overhead`, `overlay-zones`, `sierpinski-lines`) are NOT in the metrics output. Each ValueErrors at startup and the gauge object is never created.
6. **Compositor systemd unit has `Type=notify` + `WatchdogSec=60s`** per the camera 24/7 epic. Live metric `studio_compositor_watchdog_last_fed_seconds_ago` is gauge-published. Recovery cascade chain exists.
7. **No alerting rules in Prometheus.** No alertmanager. The dashboards are read-only — there's no thresholded notification path for "compositor RTMP disconnected" or "freshness gauge stale" or "VRAM headroom <2 GB."
8. **Frame-time histograms are MISSING.** The compositor publishes `studio_camera_frames_total` (counter) and `studio_camera_last_frame_age_seconds` (gauge) but **no histogram of frame intervals or per-frame budget time**. P99 frame time, the headline performance target in the research map ("p99 ≤ 34 ms"), is not measurable from current metrics.

## Data

### N1.1 — Metric coverage (122 metrics from compositor)

Sample of metric families published by `studio-compositor` at `:9482`:

| family | metric type | count | purpose |
|---|---|---|---|
| `studio_camera_*` | counter, gauge | ~12 | per-camera frames, kernel drops, bytes, last-frame age, state, transitions, reconnects, fallback flag, consecutive failures |
| `studio_compositor_*` | gauge | ~7 | boot timestamp, uptime, watchdog age, total/healthy cameras, pipeline restarts, memory footprint |
| `studio_rtmp_*` | counter, gauge | ~5 | bytes pushed, connected flag, encoder errors, bin rebuilds, rolling bitrate |
| `reverie_pool_*` | gauge | 7 | bucket count, total textures, acquires, allocations, reuse ratio, slot count |
| `compositor_publish_*` | counter, gauge | ~10 | publish-cost ticks (success, failure, age) |
| `compositor_source_frame_*` | counter, gauge | ~20 | per-source freshness (4 sources only — see F1 below) |
| `compositor_tts_client_*` | counter | 2 | TTS UDS client timeouts |

**The `compositor_source_frame_*` family is incomplete.** Only the 4 non-hyphenated cairo sources have gauges:

```text
compositor_source_frame_token_pole_*       (token_pole)
compositor_source_frame_album_*            (album)
compositor_source_frame_stream_overlay_*   (stream_overlay)
compositor_source_frame_sierpinski_*       (sierpinski)
```

**Missing** (per Sprint 2 F1):

```text
compositor_source_frame_brio-operator_*    ← hyphen rejected
compositor_source_frame_brio-room_*        ← hyphen rejected
compositor_source_frame_brio-synths_*      ← hyphen rejected
compositor_source_frame_c920-desk_*        ← hyphen rejected
compositor_source_frame_c920-room_*        ← hyphen rejected
compositor_source_frame_c920-overhead_*    ← hyphen rejected
compositor_source_frame_overlay-zones_*    ← hyphen rejected
compositor_source_frame_sierpinski-lines_* ← hyphen rejected
```

**Sprint 6 confirms the Sprint 2 finding: 8 source freshness gauges silently never instantiate.** Per-camera frame freshness — the most operationally useful series for "is this camera lying down" — is not in Prometheus.

### N2 — Prometheus scrape config (THE BIG GAP)

```text
$ curl -s http://127.0.0.1:9090/api/v1/targets | jq -r '.data.activeTargets[] | "\(.labels.job) -> \(.scrapeUrl) = \(.health)"'
council-cockpit       -> http://host.docker.internal:8051/metrics             = up
litellm               -> http://litellm:4000/metrics                          = up
node-exporter         -> http://host.docker.internal:9100/metrics             = down
nvidia-gpu            -> http://host.docker.internal:9835/metrics             = up
officium-cockpit      -> http://host.docker.internal:8050/metrics             = up
prometheus            -> http://localhost:9090/metrics                        = up
qdrant                -> http://qdrant:6333/metrics                           = up
reverie-predictions   -> http://host.docker.internal:8051/api/predictions/metrics = up
```

**8 active scrape targets. studio-compositor is not among them.** The 122 metrics described above never reach Prometheus. Grafana cannot dashboard them. Alertmanager cannot threshold them. **Everything PR #755 added to the compositor's metric surface is observable only by `curl http://127.0.0.1:9482/metrics` from the host.**

This is a queue 024 finding (FINDING-H). Multiple sessions have flagged it. Backlog item 47 is the open ticket. **It still has not landed.**

**`node-exporter` is DOWN.** Host-level metrics (CPU per core, memory, swap, network, disk space, disk I/O, network errors, USB device counters via textfile collector) are missing. The compositor reports its own RSS but everything around it (system load, kernel allocator state, USB reset events) is opaque.

### N3 — Per-GPU metric labeling (dual-GPU implication)

`nvidia-gpu :9835` is a `dcgm-exporter` or `nvidia-gpu-exporter` style scraper. Need to verify it labels metrics with `gpu_index` (0 / 1) and `gpu_name` (`5060 Ti` / `3090`). After the dual-GPU partition lands (Sprint 5b), dashboards must show per-GPU memory + utilization + encoder sessions side by side.

**Quick verification command** (not run in this sprint):

```bash
curl -s http://127.0.0.1:9835/metrics | grep -E "^DCGM_FI_DEV_FB_USED|^nvidia_gpu_memory" | head -10
```

If labels include `gpu="0"` and `gpu="1"`, the exporter is fine. If they're un-labeled, replace with dcgm-exporter (which is the Prometheus standard).

### N4 — Frame-time histograms (MISSING)

The compositor publishes:

- `studio_camera_frames_total{role="..."}` (counter)
- `studio_camera_last_frame_age_seconds{role="..."}` (gauge)

**It does NOT publish**:

- A histogram of frame intervals
- A histogram of per-frame budget time (Cairo render time, GPU upload time, encoder time)
- A p99 quantile estimator

**Why this matters**: the research map's headline target is "p99 ≤ 34 ms frame time." Without a histogram, you can compute mean fps from the counter delta but you cannot say "the 99th percentile frame time was X ms over the last 5 minutes." A long tail of 100 ms frames hides inside a 30 fps mean.

**Fix**: add a `prometheus_client.Histogram` per camera role with bucket edges `[5, 10, 16, 20, 25, 30, 33, 40, 50, 67, 100, 200, 500]` (ms). Update from the pad probe that already publishes the frame counter.

### N5 — Alerting (NONE)

```bash
$ docker exec litellm-stack-prometheus cat /etc/prometheus/rules.yml 2>/dev/null
(file does not exist)
```

There are **no alerting rules** in Prometheus. There is **no alertmanager** in the docker-compose stack. The Grafana dashboards exist but are read-only.

**Implication**: a compositor RTMP disconnect, a brio fps drop below 25, a VRAM watchdog trip, a freshness gauge >5 min stale — none of these notify the operator. The operator finds out by looking at the stream and seeing it broken, or by getting a notification from the compositor's own ntfy path (which exists for some events but not all).

**Fix**: add `prometheus.yml` rule_files: + a `rules.yml` with at minimum:

| alert | expr | for | severity |
|---|---|---|---|
| `CompositorDown` | `up{job="studio-compositor"} == 0` | 1m | critical |
| `RTMPDisconnected` | `studio_rtmp_connected == 0` | 30s | critical |
| `CameraFpsBelowTarget` | `rate(studio_camera_frames_total[1m]) < 25` | 2m | warning |
| `CameraStaleFrame` | `studio_camera_last_frame_age_seconds > 5` | 30s | critical |
| `CompositorEncoderErrors` | `rate(studio_rtmp_encoder_errors_total[5m]) > 0` | 1m | warning |
| `CompositorWatchdogStarving` | `studio_compositor_watchdog_last_fed_seconds_ago > 30` | 30s | critical |
| `ReveriePoolReuseRatioLow` | `reverie_pool_reuse_ratio < 0.5` | 5m | warning |
| `GpuMemoryHigh` | `(nvidia_gpu_memory_used_bytes / nvidia_gpu_memory_total_bytes) > 0.9` | 5m | warning |
| `GpuPowerThrottling` | `nvidia_gpu_clocks_throttle_reasons_hw_power_brake_slowdown > 0` | 1m | critical |

(Latter two need `gpu_index` label after Sprint 5b migration.)

### N6 — Tracing + log structure

Compositor logs are systemd-journal text. Not structured. `journalctl --user -u studio-compositor.service -o json` returns wrapper JSON but the log message field is plaintext. Grep-driven debugging works but field-level filtering does not.

**Fix**: switch the compositor's logger to a structured formatter (json) so journal logs can be filtered by `MESSAGE_ID`, `role`, `state`, etc. Cross-reference: Sprint 7 polish.

Langfuse traces exist for `hapax_span` instrumented agents but the compositor's hot path is not currently `hapax_span`-decorated. Tracing the compositor's per-tick work would require adding spans to the pad probes, which would have measurement cost. **Defer to "we have a confirmed slow tick" hypothesis."

### O1 — Watchdog + recovery cascade

Compositor unit: `Type=notify` + `WatchdogSec=60s` + `Restart=on-failure` (per camera 24/7 epic). The compositor must call `sd_notify("WATCHDOG=1")` every <60 s or systemd kills + restarts it.

Live metric `studio_compositor_watchdog_last_fed_seconds_ago` confirms the watchdog feed loop is alive.

**Restart cascade** is correct: secrets → tabbyapi → daimonion → visual-layer-aggregator → studio-compositor. Each unit has `After=` and (mostly) `Requires=` for its dependencies.

**Recovery FSM (per-camera)** lives in `agents/studio_compositor/state_machine.py` (per the CLAUDE.md narrative). 5-state recovery, exponential backoff, hot-swap via `interpipesrc.listen-to`. Confirmed from queue 022 work.

### O2-O3 — Restart policies across the stack

`grep -n "Restart=" systemd/units/*.service` shows:

- `Restart=always`: audio-recorder, contact-mic-recorder, hapax-logos, hapax-watch-receiver, logos-dev
- `Restart=on-failure`: hapax-content-resolver, hapax-dmn, hapax-imagination-loop, hapax-reverie, hapax-stack, hapax-video-cam@, keychron-keepalive, logos-api, midi-route, rag-ingest, studio-fx, studio-fx-output, studio-person-detector, tabbyapi, visual-layer-aggregator
- (studio-compositor.service not shown above — verify it has `Restart=on-failure` + `WatchdogSec=60`)

**Coverage looks complete.** Every long-running service has a restart policy. No gaps.

### O4 — Graceful degradation

`compositor/budget_signal.py` publishes a degraded signal to VLA when the per-frame budget is exceeded. VLA can then back off effects, switch to lower-cost shaders, or warn the operator.

Need to verify: does VLA actually act on the degraded signal, or just publish it to the cockpit? Defer to a follow-up.

### O5 — Dependency ordering

`hapax-secrets.service → hapax-stack` chain ensures credentials before any process opens a CUDA context. The stack ordering is well-thought.

### O6 — Postmortem capture

After a compositor crash + restart, what survives? `studio_compositor_pipeline_restarts_total` counts restart events. The journal preserves logs. **No structured crash dump or per-frame telemetry archive.** A repeated crash leaves only a counter increment + journal lines.

**Fix**: on watchdog timeout or `Restart=on-failure` triggering, capture (a) last 100 metric snapshots from `:9482`, (b) `nvidia-smi --query-gpu=...` dump, (c) `/dev/shm/hapax-compositor/*` state files. Write to `~/hapax-state/postmortem/{ts}/`. Drop into systemd `ExecStopPost=` or a dedicated cleanup hook.

## Findings + fix proposals

### F1 (CRITICAL): studio-compositor STILL not scraped by Prometheus

**Finding**: Prometheus has 8 active scrape targets. studio-compositor :9482 is not one. 122 carefully built metrics never reach the dashboards, the alerts (when they exist), or any operator-visible surface. This is a **multi-session carry-over bug**: queue 024 FINDING-H, queue 026 backlog item 47, and now Sprint 6 F1.

**Fix proposal**: 5-line change to `litellm-stack/prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'studio-compositor'
    static_configs:
      - targets: ['host.docker.internal:9482']
    scrape_interval: 15s
```

Plus the host-firewall rule from queue 024 backlog item 48 (`ufw allow 172.18.0.0/16 → 9482`).

**Priority**: CRITICAL. Highest-leverage observability fix on the rig. Without this, every other finding in this sprint is academic — there's no surface to act on.

### F2 (CRITICAL): node-exporter DOWN

**Finding**: Host-level metrics (CPU, memory, disk, network, USB, kernel) are missing. node-exporter target shows DOWN.

**Fix proposal**: Restart node-exporter or fix its connectivity. Likely fixes:
- `systemctl --user status node-exporter` (does it even run as a user unit?)
- Or it's a Docker container — `docker ps | grep node-exporter` and check why it's failing
- Verify host-firewall allows Docker bridge → 9100

**Priority**: CRITICAL. Same dashboard-blindness logic as F1.

### F3 (HIGH): Sprint 2 F1 hyphen bug confirmed in live metrics

**Finding**: Only 4 of the 12 expected `compositor_source_frame_*` gauge families exist in `:9482`. The 8 hyphenated source IDs (cameras + overlay-zones + sierpinski-lines) silently fail at startup with `ValueError`. Every compositor restart re-fails identically. The per-camera freshness — the most operationally useful series — is invisible.

**Fix proposal**: Same as Sprint 2 F1. One-line in `cairo_source.py:166`:
```python
safe_id = source_id.replace("-", "_")
self._freshness_gauge = FreshnessGauge(name=f"compositor_source_frame_{safe_id}", ...)
```
Plus an audit pass for any other call site that uses a `source_id` to construct a Prometheus metric name.

**Priority**: HIGH. Closes a multi-day silent observability hole.

### F4 (HIGH): no frame-time histograms; p99 unmeasurable

**Finding**: The "p99 ≤ 34 ms" headline target from the research map cannot be validated from existing metrics. Counter + gauge are not enough.

**Fix proposal**: Add a `prometheus_client.Histogram` per camera role with bucket edges `[5, 10, 16, 20, 25, 30, 33, 40, 50, 67, 100, 200, 500]`. Update from the pad probe that already increments the frame counter. Cost: 1 small allocation + 1 bucket update per frame. Negligible.

**Priority**: HIGH. Required for the entire research map's success criterion.

### F5 (HIGH): no alerting rules anywhere

**Finding**: Prometheus has no `rule_files`. No alertmanager. The dashboards are read-only. Operator finds out about failures by looking.

**Fix proposal**: Add `rules.yml` with the 9 alerts in the N5 table above. Wire alertmanager → ntfy. Cross-reference: ntfy is already in the docker-compose stack and the hapax stack uses it for nudges; piping Prometheus alerts through it is one config change.

**Priority**: HIGH. Operator should never first learn of a compositor crash from "the livestream went black."

### F6 (MEDIUM): per-GPU label coverage in nvidia-gpu exporter

**Finding**: Single-GPU dashboards will hide GPU 1 contention after the dual-GPU partition. Need to verify the exporter labels metrics by `gpu_index` and `gpu_name`.

**Fix proposal**: Quick verification: `curl http://127.0.0.1:9835/metrics | grep gpu`. If un-labeled, swap to dcgm-exporter (NVIDIA's official Prometheus exporter, supports per-device labels out of the box).

**Priority**: MEDIUM. Becomes HIGH after Sprint 5b migration lands.

### F7 (MEDIUM): postmortem capture missing

**Finding**: After a compositor crash + restart, only a counter increment + plaintext journal lines survive. The per-frame state, GPU snapshot, /dev/shm artifacts at the moment of crash are lost.

**Fix proposal**: On `WatchdogSec` timeout or `Restart=on-failure` event, dump:
- `curl :9482/metrics` (last metric snapshot)
- `nvidia-smi --query-gpu=index,name,memory.used,encoder.stats.sessionCount,clocks.current.graphics,clocks_throttle_reasons.* --format=csv`
- `/dev/shm/hapax-compositor/*`
- `journalctl --user -u studio-compositor.service --since "2 minutes ago"`

Save to `~/hapax-state/postmortem/{ts}/`. systemd `ExecStopPost=` is the natural hook.

**Priority**: MEDIUM. Pays off after the first real production incident.

### F8 (LOW): structured logging for the compositor

**Finding**: Compositor logs are plaintext. Field-level filtering not possible without grep.

**Fix proposal**: Switch logger to JSON. journalctl already supports JSON output; Loki/Promtail can ingest naturally.

**Priority**: LOW. Nice-to-have polish.

## Sprint 6 backlog additions (items 214+)

214. **`fix(prometheus): add studio-compositor scrape job to prometheus.yml`** [Sprint 6 F1, queue 024 FINDING-H carry-over, backlog 47] — 5 lines. Highest-leverage observability fix. **Carry-over from at least three prior sessions; must land in the next session.**
215. **`fix(host): ufw allow 172.18.0.0/16 → 9482`** [Sprint 6 F1 sub, queue 024 backlog 48] — host-firewall rule for the prometheus → compositor scrape path.
216. **`fix(node-exporter): restore the DOWN target`** [Sprint 6 F2] — diagnose whether node-exporter is a docker container or systemd unit, fix accordingly.
217. **`fix(freshness-gauge): replace hyphens in metric names for cairo_source.py`** [Sprint 6 F3, Sprint 2 F1, Sprint 6 confirmation] — one-line `source_id.replace("-", "_")`. Closes the per-camera freshness hole.
218. **`feat(metrics): per-camera frame-time histograms`** [Sprint 6 F4] — `prometheus_client.Histogram` with bucket edges for p99 measurement. Required by the research map's headline criterion.
219. **`feat(prometheus): rules.yml with 9 baseline alerts`** [Sprint 6 F5] — wire to alertmanager + ntfy.
220. **`fix(alertmanager): wire to ntfy for operator notifications`** [Sprint 6 F5 sub] — ntfy is already in the stack; one config change away.
221. **`research(nvidia-gpu): verify per-GPU labels; consider dcgm-exporter swap`** [Sprint 6 F6] — needed before Sprint 5b dual-GPU partition lands.
222. **`feat(compositor): postmortem dump on watchdog/crash`** [Sprint 6 F7] — `ExecStopPost=` hook; saves last metric snapshot + nvidia-smi + /dev/shm to dated dir.
223. **`feat(compositor): structured JSON logging`** [Sprint 6 F8] — switch logger formatter; journal JSON ingestion.
224. **`feat(metrics): per-camera frame-budget breakdown gauges`** [Sprint 6 cross-Sprint 2] — split the per-frame work into cairo + upload + composite + encoder sub-budgets so the offender of any over-budget tick is visible.
225. **`research(grafana): build a 'livestream cockpit' dashboard`** [Sprint 6 follow-on] — single dashboard with the 9 alert series + per-camera freshness + per-GPU usage + RTMP bitrate. Operator's one place to look.
