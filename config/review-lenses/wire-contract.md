---
lens_id: wire-contract
version: 1
title: Wire Contract
---

# Wire Contract (systemd)

## Checklist

- [ ] six-predicates: The 6 wire predicates hold for every unit touched.
- [ ] units-canonical-dir: New units live in systemd/units/ only.
- [ ] dependency-sanity: WantedBy/Requires/BindsTo/After relations are correct and minimal.
- [ ] env-and-paths-resolved: ExecStart paths, users, and environment files resolve on the target host.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
