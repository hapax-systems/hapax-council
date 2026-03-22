---
name: nudges
description: Review and act on active nudges from logos. Use when the user asks about nudges, suggestions, or runs /nudges.
---

Show active nudges from the logos API.

**Default (no args):** List active nudges:

```bash
curl -s http://127.0.0.1:8051/api/nudges | jq '.nudges[] | {id: .id, text: .text, source: .source, priority: .priority, age: .age_human}'
```

If no nudges, report "No active nudges."

**Act on a nudge** (`/nudges act <id>`):

```bash
curl -s -X POST http://127.0.0.1:8051/api/nudges/<ID>/act | jq .
```

**Dismiss a nudge** (`/nudges dismiss <id>`):

```bash
curl -s -X POST http://127.0.0.1:8051/api/nudges/<ID>/dismiss | jq .
```

If the logos API is not running (connection refused), suggest:
`cd ~/projects/hapax-council && uv run python -m logos.api`
