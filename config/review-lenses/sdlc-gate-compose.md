---
lens_id: sdlc-gate-compose
version: 1
title: SDLC Gate Composition
---

# SDLC Gate Composition

## Checklist

- [ ] no-deadlock: The new gate composes with existing admission/queue/closure gates without circular waits.
- [ ] fail-closed-default: Missing/malformed inputs block rather than admit.
- [ ] killswitch-documented: Emergency behavior is documented at the correct layer. Post-dossier admission gates may have an explicit governed bypass, but pre-provider capability gates must document fail-closed repair/retry paths rather than invoking a reviewer outside route/quota/resource admission.
- [ ] idempotent-writes: Repeated gate runs do not duplicate side effects.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
