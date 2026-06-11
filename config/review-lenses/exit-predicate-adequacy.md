---
lens_id: exit-predicate-adequacy
version: 1
title: Exit-Predicate Adequacy
---

# Exit-Predicate Adequacy (always-on)

## Checklist

- [ ] predicate-testable: The task's exit predicate is phrased as something a command or test can demonstrate.
- [ ] predicate-evidenced: The PR contains or links the evidence that the predicate actually holds.
- [ ] diff-matches-predicate: The shipped diff serves the predicate — no scope drift in, no required half missing.
- [ ] witness-durability: Evidence is reproducible (a test or recheck command), not a one-off transcript claim.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
