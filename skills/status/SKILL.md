---
name: status
description: "Run the health monitor and report results. Auto-run when: session-context shows health is degraded or failed, after infrastructure changes (docker, systemd), when a service appears unreachable, or user asks about system health. Invoke proactively without asking."
---

Run the health monitor and report results. Unset `LITELLM_API_KEY` so the check falls through to `pass` (avoids stale shell env overriding the correct key):

```bash
cd ~/projects/hapax-council && env -u LITELLM_API_KEY uv run python -m agents.health_monitor 2>&1 | grep -v -e "LITELLM_API_KEY is not set" -e "warnings.warn("
```

Report the score, then list FAILED and DEGRADED items grouped by severity.

## Triage

If `--fix` can handle it, suggest: `uv run python -m agents.health_monitor --fix --yes`

For items `--fix` cannot resolve, investigate using the patterns below.

### auth.litellm FAILED (HTTP 0 or 401)

The most common cause is an env var overriding `pass` with a bad value. Check in order:

1. **Fish universal variables** — `grep LITELLM ~/.config/fish/fish_variables`. If the value is missing the `sk-` prefix, remove it: `fish -c "set -Ue LITELLM_API_KEY"`
2. **direnv not loaded** — `direnv status` in hapax-council. If `.envrc` is not loaded, the env may have a stale value from session init.
3. **pass store** — `pass show litellm/master-key` should return `sk-...` (67 chars). If not, the key itself needs updating.
4. **LiteLLM container** — `curl -s -o /dev/null -w "%{http_code}" http://localhost:4000/health` should return 200 (even without auth).

### Stale sync agents (gdrive, gmail, youtube >24h)

Restart the stale services:

```bash
systemctl --user start gdrive-sync.service gmail-sync.service youtube-sync.service
```

If gdrive-sync fails with `Invalid Value` on `pageToken`, the sync state is corrupted. Reset the token in `~/.cache/gdrive-sync/state.json` — set `start_page_token` to empty string, then restart the service.

### profile-update.service failed

```bash
systemctl --user reset-failed profile-update.service && systemctl --user start profile-update.service
```

Check journal if it keeps failing: `journalctl --user -eu profile-update.service --no-pager -n 30`

### axiom.ef_automated — missing timers

The check compares agent manifest `systemd_unit` values against active timers. If an agent's timer exists but under a different name, fix the manifest in `agents/manifests/<agent>.yaml` to match the actual unit name. Verify with:

```bash
systemctl --user list-timers --no-pager | grep <keyword>
```

### connectivity.gdrive-sync stale

This follows from stale gdrive sync — fix the sync agent (above) and the connectivity warning clears.

### systemd unit failed (timer will retry)

```bash
systemctl --user reset-failed <service> && systemctl --user start <service>
```

If the service has a MemoryMax drop-in and is OOM-killed, check `journalctl --user -eu <service>` for `oom-kill` entries.
