---
lens_id: formal-soundness
version: 1
title: Formal Soundness
---

# Formal Soundness (algebra laws)

## Checklist

- [ ] idempotence: Re-running the operation yields the same state — no duplicate side effects.
- [ ] monotone-gates: Gates only tighten with more evidence; no blocker that flickers with evaluation order.
- [ ] round-trip-lossless: Serialize/parse pairs round-trip without loss for every field added.
- [ ] composition-laws: Composed operators preserve their documented invariants — no law broken by the new case.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
