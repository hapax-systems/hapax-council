---
name: briefing
description: Generate a system briefing covering the last 24 hours. Use when the user asks for a briefing, daily summary, or runs /briefing.
---

Generate a system briefing covering the last 24 hours:

```bash
cd ~/projects/ai-agents && eval "$(<.envrc)" && uv run python -m agents.briefing --hours 24 --save
```

If action items show high priority, suggest running the relevant fix commands.
The latest briefing is always saved to `~/projects/ai-agents/profiles/briefing.md`.
