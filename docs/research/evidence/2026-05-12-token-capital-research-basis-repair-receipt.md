---
title: "Token Capital Research Basis Repair Receipt"
date: 2026-05-12
authority_case: REQ-20260512-epistemic-audit-realignment
cc_task: epistemic-token-capital-research-basis-repair
status: receipt
mutation_surface: vault_docs
---

# Token Capital Research Basis Repair Receipt

This receipt records the vault-document repair for
`epistemic-token-capital-research-basis-repair`. The affected documents live in
`~/projects/hapax-research/foundations/`, which has no configured Git remote;
this council PR provides the reviewable task receipt while the Obsidian vault
documents carry the content changes.

## Repaired Vault Documents

- `foundations/token-capital-theory-research-2026-05-11.md`
- `foundations/token-economic-theory-gaps-2026-05-11.md`
- `foundations/token-value-maximization-research-2026-05-11.md`
- `foundations/token-capital-prompt-engineering-2026-05-11.md`
- `foundations/token-capital-prompt-engineering-and-routing-2026-05-11.md`

## Acceptance Mapping

- Shapley language is quarantined as prior art or later work until a cooperative
  game is defined with players, coalitions, and a characteristic function.
- Compounding is reframed as a hypothesis requiring working retrieval,
  cyclic reuse, corpus-utilization metrics, and downstream contribution
  measurement.
- Each affected document now carries claim maturity and construct status:
  hypothesis, observed, instrumented, not benchmarked, not replicated, and not
  publishable as proof.
- N=1 generalization boundaries are explicit: current evidence comes from a
  single-operator repair environment and requires persistent storage,
  provenance, retrieval infrastructure, cyclic reuse, consent boundaries, and
  measured outcomes before generalization.
- Value equations, replacement multipliers, and depreciation curves are demoted
  to heuristics or hypotheses unless operationalized.
- "Construct Status" and "What This Does Not Explain" / "What Token Capital
  Theory Does Not Explain" sections are present where needed.
- Broken RAG is preserved as a design-science falsifier for current compounding
  claims rather than hidden as an implementation detail.

## Verification

Commands run from `~/projects/hapax-research`:

```bash
for f in foundations/token-*.md; do
  echo "$f"
  rg -n "claim_maturity: hypothesis|Construct Status|What .*Does Not Explain|Not benchmarked|Not replicated|Not publishable|N=1|falsifier|broken RAG" "$f"
done

rg -n "Shapley values apply|Apply Shapley values|value is unbounded|unbounded and accrues|200% performance|CFA Institute.*79%|share these properties exactly|No published work considers|No existing technique|No information-flow analysis across multi-agent|Shapley value attribution \(|provides existence proof|tokens exhibit increasing returns:" foundations/token-*.md
```

The first command found the required maturity, boundary, and falsifier markers
in all five target files. The second command returned only explicit negations
or source-disambiguation statements, not positive overclaims.
