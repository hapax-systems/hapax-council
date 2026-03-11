---
name: status
description: Run the health monitor and report results. Use when the user asks about system health, infrastructure status, or runs /status.
---

Run the health monitor and report results:

```bash
cd ~/projects/ai-agents && uv run python -m agents.health_monitor
```

If checks show FAILED, suggest: `uv run python -m agents.health_monitor --fix`
