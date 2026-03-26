---
name: briefing
description: Generate a system briefing. Auto-run when: this is the first session of the day (session-context shows briefing >20h old), operator says good morning or start of day, or user asks for a briefing. Invoke proactively without asking.
---

Generate a system briefing covering the last 24 hours:

```bash
cd ~/projects/hapax-council && LITELLM_API_KEY=$(pass show litellm/master-key) LANGFUSE_PUBLIC_KEY=$(pass show langfuse/public-key) LANGFUSE_SECRET_KEY=$(pass show langfuse/secret-key) uv run python -m agents.briefing --hours 24 --save
```

If action items show high priority, suggest running the relevant fix commands.
The latest briefing is always saved to `~/projects/hapax-council/profiles/briefing.md`.
