# M2: LLM Cost Anomaly Alerting

**Date:** 2026-03-12
**Status:** Draft
**Depends on:** H3 (Prometheus + Grafana) for Grafana alert path; cron path is independent
**Scope:** Detect unusual LLM spend via cost data and alert before bills spike.

---

## 1. Data Source Analysis

Three sources of cost data exist. Each has different tradeoffs.

### 1a. Langfuse Daily Metrics API

**Endpoint:** `GET http://localhost:3000/api/public/metrics/daily`
**Auth:** Basic auth with Langfuse public key (username) and secret key (password).
**Params:** `?page=1&limit=30&traceName=<optional>&userId=<optional>`

**Response structure:**
```json
{
  "data": [
    {
      "date": "2026-03-12",
      "countTraces": 142,
      "countObservations": 580,
      "totalCost": 3.47,
      "usage": [
        {
          "model": "claude-sonnet-4-20250514",
          "inputUsage": 120000,
          "outputUsage": 45000,
          "totalUsage": 165000,
          "countTraces": 80,
          "countObservations": 320,
          "totalCost": 2.85
        }
      ]
    }
  ],
  "meta": { "page": 1, "limit": 30, "totalItems": 7, "totalPages": 1 }
}
```

**Pros:**
- Already running, receives all LiteLLM traces via `success_callback: ["langfuse"]`
- Per-model cost breakdown built in
- Cost calculated server-side (Langfuse knows Anthropic/OpenAI pricing)
- No dependency on H3 (Prometheus/Grafana)
- Self-hosted, no external API calls needed

**Cons:**
- Daily granularity only (not real-time)
- Requires Langfuse full profile to be running
- Cost inference depends on Langfuse knowing the model -- custom aliases (e.g., "balanced", "fast") may not map correctly unless LiteLLM sends the resolved model name

**Verdict:** Primary data source. Best cost-per-effort ratio.

### 1b. LiteLLM Spend Tracking API

**Endpoint:** `GET http://localhost:4000/user/daily/activity`
**Auth:** Bearer token with `LITELLM_MASTER_KEY`
**Params:** `?start_date=2026-03-01&end_date=2026-03-12`

Returns daily spend, prompt tokens, completion tokens, and API requests, broken down by model, provider, and API key.

Additional endpoints:
- `/spend/tags` -- spend grouped by custom tags
- `/spend/report` -- enterprise feature, may not be available on open-source
- `/global/spend/report` -- aggregate spend report

**Pros:**
- Knows exact resolved model names (no alias confusion)
- Token counts are precise (from provider response)
- LiteLLM is in the core profile (always running)
- Has built-in budget enforcement (`max_budget: 50` / `budget_duration: 30d` already configured)

**Cons:**
- Requires `DATABASE_URL` and `STORE_MODEL_IN_DB: true` (already configured)
- API surface changes between releases
- Spend data stored in PostgreSQL `LiteLLMSpendLogs` table

**Verdict:** Good secondary source. Cross-reference with Langfuse for validation.

### 1c. LiteLLM Prometheus Metrics

**Metric:** `litellm_spend_metric_total` (counter, labels: `model`, `api_provider`, etc.)
**Endpoint:** `http://localhost:4000/metrics` (requires H3 config change: add `"prometheus"` to callbacks)

**Pros:**
- Real-time (15s scrape interval)
- Native Grafana alert rules possible
- Already planned in H3 (`litellm_spend_metric_total` is in the dashboard spec)

**Cons:**
- Hard dependency on H3 being completed first
- Counter resets on LiteLLM restart (need `rate()` or `increase()` functions)
- No historical data until Prometheus starts scraping

**Verdict:** Best long-term option. Use for Grafana alert rules after H3 lands.

### Recommendation

**Phase 1 (no H3 dependency):** Cron script polling Langfuse daily metrics API.
**Phase 2 (after H3):** Grafana alert rule on `litellm_spend_metric_total`.

---

## 2. Cost Calculation Approach

### What "cost" means

Cost = (input_tokens x input_price) + (output_tokens x output_price), per request, summed by model.

### Current model pricing (as of 2026-03-12)

| Model | Input ($/1M tokens) | Output ($/1M tokens) | Risk tier |
|-------|---------------------|----------------------|-----------|
| claude-opus-4 | $15.00 | $75.00 | HIGH |
| claude-sonnet-4 | $3.00 | $15.00 | MEDIUM |
| claude-haiku-4.5 | $0.80 | $4.00 | LOW |
| gemini-2.5-pro | $1.25 | $10.00 | MEDIUM |
| gemini-2.5-flash | $0.15 | $0.60 | LOW |
| ollama/* (local) | $0.00 | $0.00 | NONE |

### Who calculates cost

Both Langfuse and LiteLLM calculate cost server-side using their internal pricing tables. The alerting script does not need to do its own math -- it reads the `totalCost` field from the API response.

For local Ollama models, cost is always $0. The script should exclude them from anomaly detection to avoid skewing the baseline.

### LiteLLM budget enforcement (already configured)

```yaml
general_settings:
  max_budget: 50        # USD
  budget_duration: 30d  # rolling 30-day window
```

This is a hard cap, not an anomaly alert. It will reject requests once $50 is hit. The anomaly alerter complements this by warning at lower thresholds before the hard cap triggers.

---

## 3. Threshold Algorithm Design

### Rolling average with deviation detection

```
daily_cost[today]  = sum of all model costs for today
baseline           = mean(daily_cost[today-14 .. today-1])  # 14-day trailing average
stddev             = stddev(daily_cost[today-14 .. today-1])

alert if:
  daily_cost[today] > baseline * 2.0                        # 2x average
  OR daily_cost[today] > baseline + 3 * stddev              # 3-sigma outlier
  OR daily_cost[today] > $10.00                             # absolute threshold (safety net)
```

### Why these thresholds

- **2x average:** Simple, catches sudden doubling (runaway agent loop, model upgrade with higher pricing).
- **3-sigma:** Statistical anomaly detection, handles variable baselines (weekdays vs weekends).
- **$10 absolute:** Safety net for early days when baseline is near-zero (avoids div-by-zero and "2x of $0.50 is fine" scenarios).

### Cold start (< 14 days of data)

If fewer than 7 days of history exist, use only the absolute threshold ($10). Log a warning that baseline is insufficient.

### Per-model vs aggregate

Alert on **aggregate daily cost** for simplicity. Include per-model breakdown in the alert body so the operator can see which model spiked.

---

## 4. Alerting Mechanism

### Option A: ntfy (recommended for Phase 1)

ntfy is already in the Docker stack at `localhost:8090`, profile `full`.

```bash
curl -s -d "LLM spend alert: $14.32 today (baseline: $5.20, 2.75x)
Top model: claude-sonnet-4 ($11.80)
Action: check Langfuse dashboard" \
  -H "Title: LLM Cost Anomaly" \
  -H "Priority: high" \
  -H "Tags: money_with_wings,warning" \
  http://localhost:8090/hapax-cost-alerts
```

**Pros:**
- Already deployed, zero additional infra
- Push notifications to phone (ntfy app subscribes to topic)
- Simple HTTP POST, no auth needed for local topics
- Can add webhook forwarding to email/Slack later

**Cons:**
- Requires `full` Docker profile to be running
- No escalation or acknowledgment workflow
- No alert history (notifications are ephemeral unless cached)

### Option B: Grafana alerting (Phase 2, requires H3)

After H3 deploys Prometheus + Grafana:

```yaml
# Grafana alert rule (provisioned as YAML or created in UI)
alert: LLMCostAnomaly
expr: |
  increase(litellm_spend_metric_total[24h]) > 2 * avg_over_time(
    increase(litellm_spend_metric_total[24h])[14d:24h]
  )
for: 1h
labels:
  severity: warning
annotations:
  summary: "LLM spend is {{ $value | humanize }}x above 14-day average"
```

Contact point: ntfy webhook (`http://ntfy:80/hapax-cost-alerts`).

**Pros:**
- Real-time (evaluates every scrape interval)
- Built-in silencing, grouping, escalation
- Alert history in Grafana
- Visual correlation with other metrics (GPU, latency, error rate)

**Cons:**
- Hard dependency on H3 (Prometheus + Grafana must be running)
- More complex to configure initially
- PromQL for rolling averages of counters is non-trivial

### Option C: GitHub Issue (not recommended)

Create a GitHub issue on `distro-work` repo when cost anomaly detected. Over-engineered for a single-user system. Skip.

### Recommendation

**Phase 1:** Cron script + ntfy. Works today with zero new infrastructure.
**Phase 2:** Add Grafana alert rule after H3 lands. Keep the cron script as a fallback (belt and suspenders).

---

## 5. Implementation Approach

### Phase 1: Cron script + systemd timer

**Script:** `~/projects/distro-work/scripts/llm-cost-alert.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

# Config
LANGFUSE_HOST="http://localhost:3000"
LANGFUSE_PUBLIC_KEY="$(pass show langfuse/public-key)"
LANGFUSE_SECRET_KEY="$(pass show langfuse/secret-key)"
NTFY_URL="http://localhost:8090/hapax-cost-alerts"
ABSOLUTE_THRESHOLD=10.00
MULTIPLIER_THRESHOLD=2.0
MIN_HISTORY_DAYS=7
LOOKBACK_DAYS=14
STATE_FILE="$HOME/.local/state/llm-cost-alert/history.json"

# Fetch daily metrics for the last $LOOKBACK_DAYS + 1 days
response=$(curl -sf -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
  "$LANGFUSE_HOST/api/public/metrics/daily?limit=$((LOOKBACK_DAYS + 1))")

# Parse with jq:
# - Extract today's cost
# - Extract previous N days' costs
# - Calculate mean and stddev
# - Compare against thresholds
# - If anomaly detected, POST to ntfy with breakdown

today_cost=$(echo "$response" | jq -r '.data[0].totalCost // 0')
today_date=$(echo "$response" | jq -r '.data[0].date // "unknown"')

# Get previous days (skip index 0 = today)
previous_costs=$(echo "$response" | jq -r '[.data[1:] | .[].totalCost] | map(select(. != null))')
num_days=$(echo "$previous_costs" | jq 'length')

if [ "$num_days" -lt "$MIN_HISTORY_DAYS" ]; then
  # Cold start: only check absolute threshold
  if (( $(echo "$today_cost > $ABSOLUTE_THRESHOLD" | bc -l) )); then
    curl -sf -d "LLM spend alert (cold start): \$$today_cost on $today_date
Insufficient history ($num_days days) for baseline comparison.
Absolute threshold: \$$ABSOLUTE_THRESHOLD exceeded." \
      -H "Title: LLM Cost Alert" \
      -H "Priority: high" \
      -H "Tags: money_with_wings,warning" \
      "$NTFY_URL"
  fi
  exit 0
fi

baseline=$(echo "$previous_costs" | jq 'add / length')
# stddev calculation
stddev=$(echo "$previous_costs" | jq --argjson mean "$baseline" \
  '[.[] | (. - $mean) | . * .] | add / length | sqrt')

multiplier=$(echo "$today_cost / $baseline" | bc -l 2>/dev/null || echo "0")

# Check thresholds
alert=false
reason=""
if (( $(echo "$today_cost > $baseline * $MULTIPLIER_THRESHOLD" | bc -l) )); then
  alert=true
  reason="$(printf '%.1fx above 14-day average ($%.2f)' "$multiplier" "$baseline")"
elif (( $(echo "$today_cost > $baseline + 3 * $stddev" | bc -l) )); then
  alert=true
  reason="3-sigma outlier (baseline: \$$(printf '%.2f' "$baseline"), stddev: \$$(printf '%.2f' "$stddev"))"
elif (( $(echo "$today_cost > $ABSOLUTE_THRESHOLD" | bc -l) )); then
  alert=true
  reason="absolute threshold \$$ABSOLUTE_THRESHOLD exceeded"
fi

if [ "$alert" = true ]; then
  # Build per-model breakdown
  model_breakdown=$(echo "$response" | jq -r \
    '.data[0].usage | sort_by(-.totalCost) | .[0:3] | .[] |
     "  \(.model): $\(.totalCost | tostring)"')

  curl -sf -d "LLM spend anomaly on $today_date: \$$(printf '%.2f' "$today_cost")
Reason: $reason
Top models:
$model_breakdown
Dashboard: http://localhost:3000" \
    -H "Title: LLM Cost Anomaly" \
    -H "Priority: high" \
    -H "Tags: money_with_wings,warning" \
    "$NTFY_URL"
fi
```

**Timer:** `~/.config/systemd/user/llm-cost-alert.timer`

```ini
[Unit]
Description=LLM cost anomaly check

[Timer]
OnCalendar=*-*-* 09:00:00
OnCalendar=*-*-* 18:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

**Service:** `~/.config/systemd/user/llm-cost-alert.service`

```ini
[Unit]
Description=LLM cost anomaly alerter
After=network-online.target

[Service]
Type=oneshot
ExecStart=%h/projects/distro-work/scripts/llm-cost-alert.sh
Environment=PATH=/usr/bin:/usr/local/bin
```

Runs twice daily (9 AM and 6 PM). Checks the current day's spend against the 14-day baseline.

### Phase 2: Grafana alert rule (after H3)

Once H3 is complete and LiteLLM exposes `litellm_spend_metric_total` to Prometheus:

1. Add a Grafana alert rule under a "Cost Alerts" folder:
   - **Query A:** `increase(litellm_spend_metric_total[24h])` -- today's spend
   - **Query B:** `avg_over_time(increase(litellm_spend_metric_total[24h])[14d:24h])` -- 14-day average
   - **Condition:** A > B * 2 OR A > 10
   - **Evaluation:** every 1h, for 0s (instant)
   - **Labels:** `severity: warning`, `team: hapax`

2. Add a contact point for ntfy:
   - Type: Webhook
   - URL: `http://ntfy:80/hapax-cost-alerts`
   - HTTP method: POST
   - Custom headers: `Title: LLM Cost Anomaly`, `Priority: high`, `Tags: money_with_wings`

3. Add a notification policy routing `severity=warning` to the ntfy contact point.

4. Keep the cron script running as a fallback (it uses Langfuse API, so it catches costs even if Prometheus has gaps).

---

## 6. What Can Be Done Without H3

Everything in Phase 1 is independent of H3:

| Component | H3 dependency | Status |
|-----------|---------------|--------|
| Langfuse daily metrics API | None (Langfuse already running) | Ready |
| LiteLLM spend API | None (LiteLLM already running) | Ready |
| ntfy alerting | None (ntfy already in stack) | Ready |
| Cron script + systemd timer | None | Implement now |
| Grafana alert rules | **YES** (needs Prometheus scraping LiteLLM) | After H3 |
| PromQL-based anomaly detection | **YES** (needs Prometheus) | After H3 |
| Visual correlation with GPU/latency | **YES** (needs Grafana dashboards) | After H3 |

---

## 7. Verification Checklist

### Phase 1 (cron script)

- [ ] `pass show langfuse/public-key` and `pass show langfuse/secret-key` return valid keys
- [ ] Langfuse API responds: `curl -sf -u "$PK:$SK" http://localhost:3000/api/public/metrics/daily | jq .`
- [ ] Script runs without error: `bash ~/projects/distro-work/scripts/llm-cost-alert.sh`
- [ ] ntfy topic accessible: `curl -sf http://localhost:8090/hapax-cost-alerts/json?poll=1`
- [ ] Force an alert (temporarily set `ABSOLUTE_THRESHOLD=0.01`) and confirm ntfy notification arrives
- [ ] systemd timer installed: `systemctl --user enable --now llm-cost-alert.timer`
- [ ] Timer listed: `systemctl --user list-timers | grep llm-cost`
- [ ] Test timer fires: `systemctl --user start llm-cost-alert.service` (manual trigger)
- [ ] Subscribe to ntfy topic on phone: open `ntfy.sh` app, add server `http://<tailscale-ip>:8090`, subscribe to `hapax-cost-alerts`

### Phase 2 (Grafana alerting, after H3)

- [ ] `litellm_spend_metric_total` appears in Prometheus: `curl -s http://localhost:9090/api/v1/query?query=litellm_spend_metric_total`
- [ ] Grafana alert rule created under Alerting > Alert rules > "Cost Alerts"
- [ ] ntfy contact point configured and test notification sent from Grafana
- [ ] Notification policy routes `severity=warning` to ntfy
- [ ] Send a test LLM request (`m "hello"`) and verify spend metric increments
- [ ] Wait for alert evaluation cycle and confirm no false positive on normal spend
- [ ] Force an alert (temporarily lower threshold) and confirm ntfy notification

### Ongoing validation

- [ ] Weekly: check `systemctl --user status llm-cost-alert.timer` shows recent successful runs
- [ ] Monthly: review alert thresholds against actual spend patterns (adjust multiplier if too noisy or too quiet)
- [ ] After model pricing changes: verify Langfuse cost inference still accurate (check Langfuse model pricing config)
