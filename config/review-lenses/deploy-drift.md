---
lens_id: deploy-drift
version: 1
title: Deployed-vs-Repo Drift
---

# Deployed-vs-Repo Drift

## Checklist

- [ ] deployed-vs-repo: Tracked vs runtime inventory is reconciled for every touched unit/script.
- [ ] pre-staging: Models/data/assets the change needs are staged before activation, not fetched mid-activation.
- [ ] activation-path: The change reaches its host via the governed deploy loop (main-only source activation).

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
