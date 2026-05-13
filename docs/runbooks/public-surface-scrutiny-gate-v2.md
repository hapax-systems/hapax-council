---
title: "Public Surface Scrutiny Gate V2"
date: 2026-05-13
authority_case: REQ-20260513-token-capital-public-surface-regate-v2
status: runbook
mutation_surface: source_docs
---

# Public Surface Scrutiny Gate V2

Run this gate before publishing weblog or `hapax.omg.lol` copy.

```bash
uv run python scripts/check-public-surface-claims.py --warnings-fail \
  --token-claim-report docs/research/evidence/2026-05-13-token-capital-claim-regate-v2.json \
  --source-reconciliation docs/research/evidence/2026-05-13-public-surface-source-of-truth-reconciliation.json
```

Default targets are:

- `agents/omg_web_builder/static/index.html`
- `docs/publication-drafts`

Exit codes:

- `0`: no blocking findings.
- `1`: public copy violates the deterministic claim ceiling or the current
  source reconciliation has unreconciled live items.
- `2`: a required machine-readable receipt is missing or malformed.

The gate consumes the Token Capital claim re-gate receipt and the public-surface
source-of-truth reconciliation receipt. It is not a replacement for legal,
privacy, entity, citation, or operator override review.
