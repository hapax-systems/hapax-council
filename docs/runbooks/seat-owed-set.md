---
title: Seat owed set
date: 2026-09-25
authority_case: CASE-SYSTEM-INTEGRITY-20260611
status: runbook
mutation_surface: source_docs
---

# Seat owed set

The owed set is the control point. Section 5 of the seat note is narrative.

CLEAR-READY and YIELD checkpoints paste the generated block above the narrative:

```bash
hapax-seat-owed-set --commit WORKTREE --text-block
```

An item leaves the set only by a disposition on its own record. A line in the checkpoint does not remove it. Age does not remove it. Items created at or after the activation instant are `new` (disposition within 30 minutes). Older items, and items whose `created_at` does not parse, are `backlog` (one disposition within 24 hours of activation).

The seat SessionStart hook matches `startup`, `resume`, and `clear`. It fires when `HAPAX_AGENT_ROLE` equals the process role named in the §0 incumbent row. The bus inbox stays the `family/name` token on that row. The injection lists new rows and undisposed bus asks in full, then backlog counts per class and the oldest 15 backlog rows. The full list is `~/.cache/hapax/seat-owed-set.txt`, and that path is printed.

A bus ask is disposed by a receipt, or by a seat drop in the sender's inbox whose `re:` names the drop (filename, stem, or a shared `#NNNN`) or whose later `created_at` shares `thread`. The injection states the residual of that rule. A line in section 5 does not dispose an ask.
