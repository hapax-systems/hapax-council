---
lens_id: security
version: 1
title: Security
---

# Security (trust boundaries)

## Checklist

- [ ] input-validation-boundary: External input is validated at the trust boundary.
- [ ] secret-handling: No secrets in code, logs, or receipts.
- [ ] least-privilege: New processes/commands run with minimal capability.
- [ ] injection-surfaces: Shell/YAML/SQL/prompt-injection surfaces are enumerated and constrained.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
