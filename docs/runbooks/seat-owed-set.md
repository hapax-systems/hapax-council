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

The seat SessionStart hook matches `startup`, `resume`, and `clear`. It injects `OWED BY THE SEAT (n)` for the incumbent role. The hook source is `frame/coordinator-succession-20260924/seat-clear-hook.json`.
