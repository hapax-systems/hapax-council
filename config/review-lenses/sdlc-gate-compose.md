---
lens_id: sdlc-gate-compose
version: 1
title: SDLC Gate Composition
---

# SDLC Gate Composition

## Checklist

- [ ] no-deadlock: The new gate composes with existing admission/queue/closure gates without circular waits.
- [ ] fail-closed-default: Missing/malformed inputs block rather than admit.
- [ ] killswitch-documented: An emergency bypass exists and is documented.
- [ ] idempotent-writes: Repeated gate runs do not duplicate side effects.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
