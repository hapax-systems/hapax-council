---
name: diagnose
description: Full service triage. Auto-run when: a service is unreachable (connection refused, timeout), systemctl shows a failed unit (PostToolUse suggests it), session-context reports failed units, or user mentions something is broken/down/crashed. Takes optional service name as argument. Invoke proactively without asking.
---

Run a full diagnostic sweep on a service. Argument: service name (e.g., `/diagnose logos-api`).

If no argument given, check all core services.

**Step 1 — API health (if applicable):**

```bash
curl -sf http://localhost:8051/health 2>/dev/null && echo "logos-api: healthy" || echo "logos-api: unreachable"
curl -sf http://localhost:8050/health 2>/dev/null && echo "officium-api: healthy" || echo "officium-api: unreachable"
```

**Step 2 — Shared memory state:**

```bash
ls -la /dev/shm/hapax* 2>/dev/null || echo "No hapax shared memory segments"
```

**Step 3 — Process check:**

```bash
ps aux | grep -iE 'logos|voice|compositor|aggregator' | grep -v grep
```

**Step 4 — Systemd status (for specific service or all hapax units):**

```bash
systemctl --user status {args} --no-pager 2>/dev/null || systemctl --user list-units 'hapax-*' 'logos-*' 'studio-*' 'visual-*' --no-pager 2>/dev/null
```

**Step 5 — Recent logs:**

```bash
journalctl --user -u {args} --since "30 min ago" --no-pager -n 50 2>/dev/null || journalctl --user --since "10 min ago" --priority=0..4 --no-pager -n 30
```

Analyze top-down: if API is healthy, report green. If process runs but API is down, check binding/port. If service is failed, check journal for root cause and suggest restart. If start-limit-hit, suggest `systemctl --user reset-failed {service} && systemctl --user start {service}`.
