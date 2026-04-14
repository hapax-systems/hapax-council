# Phase 2 — FINDING-H root cause: Prometheus scrape config + host firewall gap

**Queue item:** 024
**Phase:** 2 of 6
**Depends on:** PR #756 FINDING-H
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

Two independent causes combine to produce the FINDING-H observation
"`studio_*` metrics are invisible to Prometheus and the
`studio-cameras.json` Grafana dashboard is end-to-end dead":

1. **Prometheus config has no scrape job for `:9482`.** The live
   config at `llm-stack/prometheus.yml` lists 8 scrape jobs; none
   targets the compositor exporter on port 9482.
2. **Even if the scrape job existed**, the `node-exporter` scrape
   already shows the bottom half of the problem: port 9100 is listed
   in the Prometheus config but the `node-exporter` target has
   `health=down` with error *"Get "http://host.docker.internal:9100/metrics":
   context deadline exceeded"*. Root cause of the network failure is
   **`ufw` has no allow rule for port 9100 from the Docker llm-stack
   subnet `172.18.0.0/16`.** Only 8050, 8051, 9835, and 11434 are
   whitelisted.

Adding a scrape job alone will not fix `:9482` — the same firewall
gap that blocks `:9100` will block `:9482`. The fix is **one
Prometheus config change + two ufw allow rules**, shipped together.

## Evidence

### Live Prometheus config

```bash
$ docker exec prometheus cat /etc/prometheus/prometheus.yml | wc -l
66
$ docker inspect prometheus --format '{{range .Mounts}}{{.Source}}:{{.Destination}}{{println}}{{end}}'
/store/llm-data/prometheus:/prometheus
llm-stack/prometheus.yml:/etc/prometheus/prometheus.yml
```

**Source of truth:** `llm-stack/prometheus.yml` (mounted
read-only into the container, owned by the `llm-stack` repo, not
`hapax-council--beta`). 8 scrape jobs:

| job_name | target | metrics_path |
|---|---|---|
| council-cockpit | host.docker.internal:8051 | /metrics |
| officium-cockpit | host.docker.internal:8050 | /metrics |
| litellm | litellm:4000 | /metrics |
| qdrant | qdrant:6333 | /metrics |
| prometheus | localhost:9090 | /metrics |
| node-exporter | host.docker.internal:9100 | /metrics |
| reverie-predictions | host.docker.internal:8051 | /api/predictions/metrics |
| nvidia-gpu | host.docker.internal:9835 | /metrics |

**`host.docker.internal:9482` is not in the list.** The compositor
exporter is configured, running, and serving metrics on port 9482 —
but there is no scrape job that reads it.

### Prometheus target health (live)

```bash
$ curl -s http://127.0.0.1:9090/api/v1/query?query=up | python3 -c ...
up{job=prometheus                , instance=localhost:9090}             = 1
up{job=litellm                   , instance=litellm:4000}               = 1
up{job=qdrant                    , instance=qdrant:6333}                = 1
up{job=nvidia-gpu                , instance=host.docker.internal:9835}  = 1
up{job=officium-cockpit          , instance=host.docker.internal:8050}  = 1
up{job=council-cockpit           , instance=host.docker.internal:8051}  = 1
up{job=node-exporter             , instance=host.docker.internal:9100}  = 0
up{job=reverie-predictions       , instance=host.docker.internal:8051}  = 1
```

7 healthy, 1 broken (`node-exporter`), 0 `studio-*` jobs.

Prometheus API label inventory confirms the studio-* blackhole:

```bash
$ curl -s 'http://127.0.0.1:9090/api/v1/label/__name__/values' | jq '.data[] | select(startswith("studio_"))'
# (empty)
```

Zero `studio_*` series. Zero `compositor_*` series. The metrics are
ingested nowhere.

### The node-exporter scrape failure

The `node-exporter` job is configured identically to the working
`nvidia-gpu` job (same `host.docker.internal` gateway, same
`extra_hosts: [host.docker.internal:host-gateway]` docker-compose
entry), yet its target is `down`:

```text
node-exporter  health=down  lastError="Get \"http://host.docker.internal:9100/metrics\": context deadline exceeded"
```

The host-side `prometheus-node-exporter.service` is alive
(`systemctl status` shows active running since 12:05 CDT) and bound
to `*:9100` (ss output confirms wildcard bind). A direct host-side
`curl http://127.0.0.1:9100/metrics` returns 2406 metric lines. So
the service is healthy; the network path between the `prometheus`
container and the host's port 9100 is broken.

Inside the container, `wget http://host.docker.internal:9100/metrics`
times out. The same call to `host.docker.internal:9835` succeeds.
The only difference between 9100 and 9835 is the ufw rule set.

### ufw rule inventory

```bash
$ sudo ufw status numbered
Status: active

     To                       Action      From
     --                       ------      ----
[ 1] 11434/tcp                ALLOW IN    172.18.0.0/16  # Ollama from Docker llm-stack
[ 2] 11434/tcp                ALLOW IN    172.17.0.0/16  # Ollama from Docker bridge
[ 3] 8051/tcp                 ALLOW IN    172.18.0.0/16  # Council cockpit from Docker llm-stack
[ 4] 8050/tcp                 ALLOW IN    172.18.0.0/16  # Officium cockpit from Docker llm-stack
[ 5] 9835/tcp                 ALLOW IN    172.18.0.0/16  # GPU exporter from Docker llm-stack
 ...
```

**No rule for `9100/tcp` from `172.18.0.0/16`.** When the Prometheus
container sends a TCP SYN to `host.docker.internal:9100`, ufw's
input chain default-drops it (ufw policy is DENY by default). The
container sees a connection timeout because no RST or ICMP is
returned — the `pkttype host limit rate 5/second counter reject
with icmpx type admin-prohibited` line in `/etc/nftables.conf`
only fires at rate-limited intervals, so most probes simply time
out.

**Same story for port 9482.** No ufw allow rule for compositor
metrics exists. If the scrape config had a `studio-compositor` job,
it would fail with the same timeout.

### nftables compiled-rule evidence (produced by ufw)

```text
$ sudo nft list ruleset | grep "ip saddr 172.18.0.0/16 tcp dport"
ip saddr 172.18.0.0/16 tcp dport 11434 counter accept
ip saddr 172.18.0.0/16 tcp dport 8051  counter accept
ip saddr 172.18.0.0/16 tcp dport 8050  counter accept
ip saddr 172.18.0.0/16 tcp dport 9835  counter accept
```

4 explicit port allow rules. 9100, 9482, and every future hapax
exporter must each get their own rule.

## Proposed fix — unified diff

Two changes, landed together as a distro-work ticket because they
cross the `llm-stack` repo boundary + a host-firewall change:

### Change 1 — `llm-stack/prometheus.yml` diff

```diff
--- a/llm-stack/prometheus.yml
+++ b/llm-stack/prometheus.yml
@@ -56,3 +56,10 @@ scrape_configs:
     static_configs:
       - targets: ["host.docker.internal:9835"]
         labels:
           component: "gpu"
+
+  # --- Studio compositor (host service, Phase 4 of camera 24/7 epic) ---
+  - job_name: "studio-compositor"
+    metrics_path: /metrics
+    scrape_interval: 5s  # compositor is frame-rate sensitive; 5s supports 30s rate() windows
+    static_configs:
+      - targets: ["host.docker.internal:9482"]
+        labels:
+          component: "compositor"
+          project: "hapax-council"
```

Then reload Prometheus:

```bash
docker kill --signal=HUP prometheus
# or, for a full restart:
docker compose -f llm-stack/docker-compose.yml restart prometheus
```

### Change 2 — ufw host firewall rules

```bash
sudo ufw allow in from 172.18.0.0/16 to any port 9100 proto tcp \
  comment "node-exporter from Docker llm-stack"
sudo ufw allow in from 172.18.0.0/16 to any port 9482 proto tcp \
  comment "studio compositor metrics from Docker llm-stack"
sudo ufw reload
```

These are persistent — ufw writes to `/etc/ufw/user.rules` and
re-applies on boot. No nftables.conf edit needed.

### Verification after applying both changes

```bash
# 1. Prometheus target health
curl -s http://127.0.0.1:9090/api/v1/query?query=up | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  [print(f\"{r['metric']['job']:25s}={r['value'][1]}\") \
   for r in d['data']['result']]"
# Expected: node-exporter=1 AND studio-compositor=1

# 2. studio_* series ingestion
curl -s 'http://127.0.0.1:9090/api/v1/label/__name__/values' | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  print(sum(1 for n in d['data'] if n.startswith('studio_')))"
# Expected: >= 15 (matches the 15 distinct metric names from the compositor exporter)

# 3. Grafana dashboard resurrection
# Open http://127.0.0.1:3001/d/studio-cameras/
# Expected: all 12 panels populate instead of showing "No data"

# 4. A specific compositor query
curl -s 'http://127.0.0.1:9090/api/v1/query?query=sum(studio_camera_state{state="healthy"})' | \
  jq '.data.result[0].value[1]'
# Expected: "6.0" (matches the 6 registered cameras)
```

## Observability signals unlocked by the fix

### From studio-compositor :9482 (15 metric names, 20+ series with labels)

Per queue 022 Phase 4 + this phase:

| series | consumer | impact when broken |
|---|---|---|
| `studio_camera_frames_total` | studio-cameras.json panel 1 | cannot see frame rate per camera |
| `studio_camera_kernel_drops_total` | panel 3 | cannot alert on USB frame drops |
| `studio_camera_bytes_total` | derived panels | cannot compute bitrate per camera |
| `studio_camera_last_frame_age_seconds` | panel 2 | cannot detect camera stall |
| `studio_camera_state` | panels 0, 4 | cannot see FSM state timeline |
| `studio_camera_transitions_total` | panel 6 | cannot count state transitions |
| `studio_camera_reconnect_attempts_total` | panel 5 | cannot see reconnect activity |
| `studio_camera_consecutive_failures` | derived | cannot gate alerts on brio-room flapping |
| `studio_camera_in_fallback` | derived | cannot see fallback engagement |
| `studio_compositor_boot_timestamp_seconds` | — | cannot compute uptime cleanly |
| `studio_compositor_uptime_seconds` | panel 7 | cannot see uptime |
| `studio_compositor_watchdog_last_fed_seconds_ago` | panel 9 | cannot alert on sd_notify watchdog staleness |
| `studio_compositor_cameras_total` | — | cannot see compositor's view of camera count |
| `studio_compositor_cameras_healthy` | — | PR #756 Phase 2 noted: broken accumulator AND dead-end consumer |
| `studio_compositor_pipeline_restarts_total` | panel 8 | cannot count pipeline rebuilds |
| `studio_rtmp_*` (5 series) | panels 10, 11 | cannot see RTMP state |

### From PR #755's FreshnessGauge wiring

Alpha's PR #755 wired `FreshnessGauge` through the compositor's
custom metrics REGISTRY. These series also live on `:9482`:

- `compositor_publish_costs_{published_total, failed_total, age_seconds}` — Phase 7 budget-publish heartbeat
- `compositor_publish_degraded_{published_total, failed_total, age_seconds}` — F3 dead-path heartbeat (will show `age_seconds=+Inf` until PR #756 Phase 3 decides retire-or-resurrect)
- `compositor_source_frame_<source_id>_{published_total, failed_total, age_seconds}` — per-CairoSource heartbeat

**None of these are currently ingested.** They are new observability
work that is invisible despite being wired correctly at the producer
side. PR #755's value is currently zero operator impact because
Prometheus has no knowledge of the series.

### From node-exporter :9100 (~332 system metric names)

| concern | relevant series |
|---|---|
| CPU saturation | `node_cpu_seconds_total`, `node_load1`, `node_load5`, `node_load15` |
| Memory pressure | `node_memory_MemAvailable_bytes`, `node_memory_SwapFree_bytes` |
| Disk usage | `node_filesystem_avail_bytes`, `node_filesystem_size_bytes` |
| Disk latency | `node_disk_io_time_seconds_total`, `node_disk_read_time_seconds_total` |
| Network | `node_network_receive_bytes_total`, `node_network_transmit_bytes_total` |
| Uptime | `node_boot_time_seconds` |
| Thermal | `node_thermal_zone_temp` |

The Bayesian presence engine's `ambient_energy` signal depends on
contact-mic RMS, which correlates with `node_cpu_seconds_total` usage
patterns — secondary signal loss.

## Ranked unlock list

With both changes applied, these observability signals come back online
in priority order:

1. **`studio_camera_last_frame_age_seconds`** — directly detects the
   Phase 1 brio-room flap + the FINDING-G TTS regression symptom
   (stream silence despite alive producer).
2. **`studio_compositor_watchdog_last_fed_seconds_ago`** — sd_notify
   watchdog freshness, the primary liveness signal for the compositor.
3. **`studio_camera_frames_total` rate** — per-camera fps; reveals
   the brio-operator 27.97 vs 30 fps deficit from PR #752 Phase 2.
4. **`studio_camera_transitions_total`** — FSM event counter; lets
   Prometheus `rate()` queries see flap storms like the brio-room
   event at 17:00:47 (PR #756 Phase 4).
5. **`compositor_source_frame_<id>_age_seconds`** — per-source
   FreshnessGauge from PR #755; detects cairo runner hangs.
6. **`compositor_publish_degraded_age_seconds`** — FINDING-I's
   "+Inf" tombstone; lets the dead-path state be Prometheus-visible.
7. **`node_memory_MemAvailable_bytes`** — host memory pressure, was
   blind throughout today's session.
8. **`node_cpu_seconds_total`** — the PID 3145327 finding of 5.87
   cores sustained would have been visible in real-time.
9. **`node_filesystem_avail_bytes`** — disk full would be silent
   until an agent tried to write.
10. **`studio_compositor_pipeline_restarts_total`** — compositor
    restart counter; would let Prometheus see the 3 restart events
    during PR #756's observation window.

## Secondary finding: Grafana dashboard source-of-truth drift risk

`hapax-council/grafana/dashboards/studio-cameras.json` exists in the
hapax-council repo. But the **actual Grafana provisioning path** is
`llm-stack/grafana/provisioning` (per the `docker-compose.yml` mount).
If the Grafana container has not been restarted since the hapax-council
dashboard JSON was updated, the live dashboard may be a stale copy.

Out of scope for this phase — mark as a follow-up observation. Phase 6
of the round-3 research (data plane audit) may pick this up.

## Backlog additions (for retirement handoff)

47. **`fix(llm-stack): add studio-compositor scrape job to
    prometheus.yml`** [Phase 2 Change 1] — lives in the llm-stack
    repo, not hapax-council. Coordinate with operator since it's a
    cross-repo change. 7 lines of yaml + `docker kill --signal=HUP
    prometheus`.
48. **`fix(host): ufw allow in from 172.18.0.0/16 to any port 9100,
    9482 proto tcp`** [Phase 2 Change 2] — distro-work ticket, needs
    sudo. Host-side persistent firewall change.
49. **`fix(prometheus): scrape interval 5s for studio-compositor
    job`** [Phase 2, bundled with #47] — the default 15s interval
    is too coarse for the studio-cameras dashboard's
    `rate(studio_camera_frames_total[30s])` query, which needs at
    least 3–6 samples per 30s window to be stable.
50. **`feat(monitoring): add scrape jobs for hapax-daimonion :9483,
    visual-layer-aggregator :9484, hapax-imagination :9485 once
    those exporters exist`** [Phase 2 + PR #756 Phase 6 forward
    link] — pre-emptively add the jobs so that landing the
    exporter code is a single small PR with zero Prometheus-side
    change needed.
51. **`fix(monitoring): add ufw allow rules for :9483, :9484, :9485`**
    [Phase 2 + PR #756 Phase 6] — paired with #50. Every new
    hapax host-exporter needs both a scrape job AND a ufw rule.
    Consider factoring into a helper script so new exporters do
    not silently drop on the firewall side.
52. **`docs(distro-work): add a "hapax host metric exporter
    onboarding" checklist`** — every new Prometheus endpoint needs
    (a) the exporter running with `0.0.0.0` bind, (b) ufw rule,
    (c) llm-stack/prometheus.yml scrape job, (d) Grafana
    dashboard, (e) alert rule. Today this is tribal knowledge; a
    checklist would prevent the FINDING-H class of failure from
    recurring.
53. **`research(grafana): verify studio-cameras.json is the live
    dashboard path once the scrape lands`** — cross-check against
    llm-stack/grafana/provisioning/dashboards/ to confirm.
54. **`feat(monitoring): Prometheus alert rules for dead scrape
    targets`** [PR #756 Phase 6 follow-up] — `up == 0 for 2m`
    should page. Today node-exporter has been dead since the last
    reboot with no alert.

## Reproduction commands

```bash
# 1. Live prometheus config
docker exec prometheus cat /etc/prometheus/prometheus.yml

# 2. Target health
curl -s http://127.0.0.1:9090/api/v1/targets | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  [print(t['labels'].get('job'), t['health'], t.get('lastError','')[:80]) \
   for t in d['data']['activeTargets']]"

# 3. studio_* series count
curl -s 'http://127.0.0.1:9090/api/v1/label/__name__/values' | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
  print('studio_*=', sum(1 for n in d['data'] if n.startswith('studio_')))"

# 4. ufw rules
sudo ufw status numbered | grep -E "9100|9482|172.18"

# 5. nftables compiled rules
sudo nft list ruleset | grep "172.18.0.0/16 tcp dport"
```
