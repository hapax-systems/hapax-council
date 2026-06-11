---
lens_id: tests-cover-the-diff
version: 1
title: Tests Cover the Diff
---

# Tests Cover the Diff (always-on)

## Checklist

- [ ] diff-behavior-coverage: Every behavior changed in the diff has a test that exercises it through the real code path.
- [ ] red-before-green: Bugfix tests demonstrably fail without the fix — they assert on the regression, not on incidentals.
- [ ] new-paths-tested: New functions and branches each have at least one direct test, including their error paths.
- [ ] no-coverage-theater: Tests assert outcomes, not implementation echoes — "the mock was called" is never the only assertion.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
