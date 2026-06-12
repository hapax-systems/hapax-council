---
lens_id: canonical-root
version: 2
title: Canonical Root
---

# Canonical Root

## The estate convention (ratified — do NOT flag conformance to it)

Per merged #4090 (S1 release-pinning) and the durable-deploy design (#4064/#4077):

- **The activation worktree IS the canonical root.** Production units ExecStart
  from `%h/.cache/hapax/source-activation/worktree/...` (or an analogous
  per-repo activation worktree such as `coord-activation/worktree`). This is
  the ratified pattern, not a violation: literal release-SHA roots are
  explicitly NOT used (releases GC; the activation alias survives; governed
  deploy is the alias's only writer).
- A unit pointing at a **mutable dev tree** (`~/projects/<repo>/...`) IS a
  finding — that is what this lens exists to catch.

## Checklist

- [ ] release-root-pinning: Services run from an ACTIVATION WORKTREE or
      release root — never from a mutable dev tree (`~/projects/...`).
      The activation-worktree alias pattern above is conforming.
- [ ] no-live-pid-deletion: No cleanup path can delete a directory that has live PIDs.
- [ ] ghost-release-detection: Stale/ghost releases remain detectable after this change.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
