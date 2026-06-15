---
lens_id: correctness
version: 1
title: Correctness
---

# Correctness

## Checklist

- [ ] state-machine-honesty: Every state/transition added is reachable and every claimed state is real — no label-only states.
- [ ] abi-version-windows: ABI/protocol/schema version windows are checked at boundaries; mixed-version peers are handled.
- [ ] none-empty-zero: None/empty/zero/missing-key paths are handled at each new call site.
- [ ] boundary-arithmetic: Ring/window/index arithmetic is checked at the boundaries — off-by-one, wraparound, clamp.
- [ ] concurrency-safety: Shared state is mutated under the documented lock/loop discipline; no check-then-act races introduced.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
