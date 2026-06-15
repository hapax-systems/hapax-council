# Prometheus — repo SSOT + deploy procedure

Source of truth for the llm-stack Prometheus running on hapax-podium
(`docker compose` service `prometheus`, config mounted ro from
`/home/hapax/llm-stack/prometheus.yml`, `--web.enable-lifecycle` enabled).
Introduced by `audit-w4-observability-honesty-20260611`; before this the
deployed config was unversioned and carried **zero** alert rules.

```
config/prometheus/prometheus.yml            → /home/hapax/llm-stack/prometheus.yml
config/prometheus/rules/*.yml               → /home/hapax/llm-stack/rules/  (new compose mount)
```

## Deploy (podium, after merge)

1. Copy config + rules out of the deployed main clone:

   ```bash
   cd ~/llm-stack
   cp ~/projects/hapax-council/config/prometheus/prometheus.yml .
   mkdir -p rules && cp ~/projects/hapax-council/config/prometheus/rules/*.yml rules/
   ```

2. Add the rules mount to the prometheus service in `docker-compose.yml`
   (one-time):

   ```yaml
   volumes:
     - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
     - ./rules:/etc/prometheus/rules:ro          # ← add
     - ./litellm-key:/etc/prometheus/litellm-key:ro   # ← add (step 3)
   ```

3. Materialize the litellm scrape credential (one-time; key NEVER enters
   the repo). The scrape job reads `/etc/prometheus/litellm-key` via
   `authorization.credentials_file`:

   ```bash
   # from llm-stack .env LITELLM_MASTER_KEY
   grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2- | tr -d '\n' > litellm-key
   chmod 600 litellm-key
   ```

4. node_exporter textfile collector (one-time, **sudo — PENDING-OPERATOR**).
   The Arch package unit reads `/etc/conf.d/prometheus-node-exporter`; the
   whole audio M-suite + echo-probe + recovery `.prom` files sit orphaned in
   `/var/lib/node_exporter/textfile_collector/` until this flag exists
   (W4-TEXTFILE-ORPHAN):

   ```
   NODE_EXPORTER_ARGS="--collector.textfile.directory=/var/lib/node_exporter/textfile_collector"
   ```

   ```bash
   sudo systemctl restart prometheus-node-exporter
   curl -s localhost:9100/metrics | grep -c ^hapax_   # expect > 0
   ```

   Second orphan dir: `hapax-live-surface-guard` writes its textfiles to
   `~/.local/share/node_exporter/textfile_collector/` — consolidate by
   pointing its `--textfile-path` at the `/var/lib` dir (or symlink) so one
   collector serves everything.

5. Apply (container recreate picks up new mounts, then hot-reload on
   subsequent rule edits):

   ```bash
   docker compose up -d prometheus
   curl -X POST 127.0.0.1:9090/-/reload
   ```

6. Verify:

   ```bash
   curl -s 127.0.0.1:9090/api/v1/rules | jq '.data.groups | length'   # ≥ 1
   curl -s 127.0.0.1:9090/api/v1/targets | jq -r '.data.activeTargets[] | "\(.labels.job) \(.health)"'
   # hapax-daimonion/hapax-lufs-panic-cap/hapax-youtube-telemetry → up
   # litellm → up (was 401)
   ```

## Honest-scope notes

- **No alertmanager exists.** Rules are evaluated and visible
  (`/api/v1/rules`, `/api/v1/alerts`, the `ALERTS` series) — that is the
  claim, nothing more. ntfy delivery bridge is follow-on work.
- **studio-compositor (:9482) scrape is commented out** — the GStreamer
  compositor is parked; a registered always-down target would make
  `HapaxExporterDown` fire forever and train everyone to ignore it.
  Re-enable the job in the PR that unparks the compositor.
- The appendix llm-stack runs a separate "ghost twin" Prometheus (1/10
  targets up) — explicitly out of scope here; this SSOT targets the podium
  estate instance.
