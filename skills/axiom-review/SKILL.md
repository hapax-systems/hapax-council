---
name: axiom-review
description: Review pending axiom precedents. Auto-run when: session-context reports pending precedents, after an agent run that may have created new precedents (PostToolUse suggests it), or user asks to review axiom decisions. Invoke proactively without asking.
---

Review pending axiom precedents that agents have created.

Run:

```bash
cd ~/projects/hapax-council && eval "$(direnv export bash 2>/dev/null)" && uv run python -c "
from shared.axiom_precedents import PrecedentStore

store = PrecedentStore()
pending = store.get_pending_review()
if not pending:
    print('No pending precedents to review.')
else:
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
"
```

For each precedent, ask the operator whether to CONFIRM (promote to operator authority) or REJECT (with correction).
