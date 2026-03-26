---
name: status
description: Run the health monitor. Auto-run when: session-context shows health is degraded or failed, after infrastructure changes (docker, systemd), when a service appears unreachable, or user asks about system health. Invoke proactively without asking.
---

Run the health monitor and report results:

```bash
cd ~/projects/hapax-council && uv run python -m agents.health_monitor
```

If checks show FAILED, suggest: `uv run python -m agents.health_monitor --fix`
