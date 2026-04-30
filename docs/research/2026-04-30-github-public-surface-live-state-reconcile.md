---
title: GitHub public surface live state reconcile
date: 2026-04-30
status: evidence-produced
source: github-public-surface-live-state-reconcile
---

# GitHub Public Surface Live State Reconcile

- Generated: `2026-04-30T03:49:18Z`
- Claim ceiling: `public_archive`
- Blocking findings: `4`
- Report schema: `schema_version=1`

## Live Repos

| Repo | Visibility | Default SHA | License | Issues | Discussions | Wiki | Pages |
|---|---:|---|---|---:|---:|---:|---:|
| ryanklee/hapax-council | public | 8d7b3aa37d74 | Apache-2.0 | true | false | false | false |
| ryanklee/hapax-constitution | public | 104a22ac3b24 | Apache-2.0 | true | false | true | false |
| ryanklee/hapax-officium | public | 10bbd0173b79 | NOASSERTION | true | false | false | false |
| ryanklee/hapax-watch | private |  |  |  |  |  | false |
| ryanklee/hapax-phone | private |  |  |  |  |  | false |
| ryanklee/hapax-mcp | private |  |  |  |  |  | false |
| ryanklee/hapax-assets | missing_or_private |  |  |  |  |  | false |

## Drift Findings

| Severity | Category | Surface | Summary |
|---|---|---|---|
| high | license_detection | ryanklee/hapax-constitution | GitHub detected license does not match the repo registry policy. |
| high | license_detection | ryanklee/hapax-officium | GitHub detected license does not match the repo registry policy. |
| high | settings_truth | ryanklee/hapax-watch | An intended public first-party repo is not publicly visible. |
| high | settings_truth | ryanklee/hapax-phone | An intended public first-party repo is not publicly visible. |
| high | settings_truth | ryanklee/hapax-mcp | An intended public first-party repo is not publicly visible. |
| blocking | license_detection | ryanklee/hapax-council | GitHub/root license detection contradicts the repo registry policy. |
| blocking | notice_links | NOTICE.md | NOTICE links to CONTRIBUTING.md, but the linked file is absent. |
| high | contributing_governance | ryanklee/hapax-council | GOVERNANCE.md is missing from the public repo root. |
| high | settings_truth | ryanklee/hapax-council | Issues are enabled while GitHub does not report an issue template. |
| high | readme_currentness | README.md | README currentness must be regenerated after live-state reconciliation. |
| high | citation_codemeta_zenodo | CITATION.cff/codemeta.json/.zenodo.json | Citation/CodeMeta/Zenodo metadata must be reconciled after license drift. |
| blocking | profile_repo_state | ryanklee/ryanklee | User profile README repo is missing, private, or lacks root README.md. |
| blocking | pages_cdn_state | ryanklee/hapax-assets | hapax-assets is not a verified public Pages/CDN surface. |
| medium | package_public_surfaces | packages/ | Some package README/PyPI surfaces contain issue/support language needing claim discipline. |
| high | closed_repo_pres_claims | cc-task closed/repo-pres-* | Closed repo-pres task claims were compared to live state. |

## Profile README Decision

Current GitHub docs require a public user repo named `ryanklee` with a root `README.md` for a user profile README. The `.github/profile/README.md` pattern is for organization profiles, so it is evidence only for this operator-account surface.

## Anti-Overclaim

Observed user-profile candidate: `gh: Not Found (HTTP 404)`.

- live GitHub coherence does not prove research validity.
- live GitHub coherence does not prove livestream health.
- live GitHub coherence does not prove support readiness.
- live GitHub coherence does not prove artifact rights.
- live GitHub coherence does not prove monetization readiness.
