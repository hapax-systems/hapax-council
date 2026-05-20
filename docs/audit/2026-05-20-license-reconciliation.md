# License Reconciliation

CC-task: `20260509-research-positioning-phase0-license-zenodo`
Date: 2026-05-20

## License Posture By Repository

| Repository | License | SPDX ID | Rationale |
|-----------|---------|---------|-----------|
| hapax-council | PolyForm Strict 1.0.0 | LicenseRef-PolyForm-Strict-1.0.0 | Personal operating environment — not for reuse or redistribution. Research artifact published for inspection, not consumption. |
| hapax-constitution | Apache 2.0 | Apache-2.0 | Governance specification — open for academic reference and downstream adoption of governance patterns. |
| hapax-officium | Apache 2.0 | Apache-2.0 | Management decision support — same rationale as constitution. |
| hapax-mcp | Apache 2.0 | Apache-2.0 | MCP server bridging logos APIs — utility layer, open for reference. |
| hapax-watch | PolyForm Strict 1.0.0 | LicenseRef-PolyForm-Strict-1.0.0 | Wear OS companion — tightly coupled to council, not independently useful. |
| hapax-phone | PolyForm Strict 1.0.0 | LicenseRef-PolyForm-Strict-1.0.0 | Android companion — same as watch. |

## Intentional Inconsistency

The split is deliberate: governance specs and utility layers use Apache 2.0 so patterns can be studied and reused; the personal operating environment and its device companions use PolyForm Strict because they are the operator's research instrument, not a software product.

## Zenodo DOI

- DOI: `10.5281/zenodo.20113515`
- CITATION.cff: present in repo root, references DOI
- Status: minted and reachable

## Remaining Operator Actions

- [ ] Update Zenodo record metadata with expanded keyword set (novel architectural patterns added to CITATION.cff)
- [ ] Trigger Software Heritage deposit for current HEAD SHA
- [ ] Verify DOI resolves correctly after Zenodo metadata refresh
