---
name: restore
description: Restore cognitive context after an interruption. Use when the user returns to work, asks what they were doing, needs to re-orient, or runs /restore.
---

Collect and display context restoration data — what the operator was doing, what's next, and what accumulated while they were away:

```bash
cd ~/projects/hapax-council && uv run python -m agents.context_restore
```

After displaying the output, briefly highlight the most actionable item (an open PR that needs merging, an upcoming meeting that needs prep, or uncommitted work that should be committed).

This implements the executive_function axiom: the system compensates for working memory gaps during task-switching.
