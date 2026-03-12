---
name: axiom-review
description: Review pending axiom precedents that agents have created. Use when the user asks to review precedents, axiom decisions, or runs /axiom-review.
---

Review pending axiom precedents that agents have created.

Run:

```bash
cd ~/projects/hapax-council && eval "$(direnv export bash 2>/dev/null)" && uv run python -c "
import asyncio
from shared.axiom_precedents import PrecedentStore

async def review():
    store = PrecedentStore()
    pending = await store.get_pending_review()
    if not pending:
        print('No pending precedents to review.')
        return
    for p in pending:
        print('---')
        print(f'ID: {p.id}')
        print(f'Axiom: {p.axiom_id}')
        print(f'Tier: {p.tier}')
        print(f'Decision: {p.decision}')
        print(f'Situation: {p.situation}')
        print(f'Reasoning: {p.reasoning}')
        print(f'Distinguishing facts: {p.distinguishing_facts}')
        print()

asyncio.run(review())
"
```

For each precedent, ask the operator whether to CONFIRM (promote to operator authority) or REJECT (with correction).
