---
lens_id: silent-failure-hunting
version: 1
title: Silent-Failure Hunting
---

# Silent-Failure Hunting

## Checklist

- [ ] no-swallowed-exceptions: No new bare or over-broad except that drops the error.
- [ ] loud-fallbacks: Fallback-on-dependency-down logs at WARNING+ and surfaces in receipts.
- [ ] error-paths-reach-operator: Failures reach logs/ntfy with next actions.
- [ ] partial-success-honest: Multi-step operations report which steps succeeded and which did not.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
