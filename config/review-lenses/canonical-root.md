---
lens_id: canonical-root
version: 1
title: Canonical Root
---

# Canonical Root

## Checklist

- [ ] release-root-pinning: Services run from release roots, not working trees.
- [ ] no-live-pid-deletion: No cleanup path can delete a directory that has live PIDs.
- [ ] ghost-release-detection: Stale/ghost releases remain detectable after this change.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
