---
lens_id: test-validity
version: 1
title: Test Validity
---

# Test Validity (does it test the claim?)

## Checklist

- [ ] tests-the-claim: Each test exercises the behavior it names, on the real code path.
- [ ] fails-on-regression: Reverting the fix makes the test fail.
- [ ] no-tautology: No assertions that are true by construction.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
