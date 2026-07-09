---
title: GitHub public surface live state reconcile
date: 2026-04-30
refresh_date: 2026-07-09
generated_at: 2026-07-09T00:20:30Z
status: evidence-produced
source: github-public-surface-live-state-reconcile
---

# GitHub Public Surface Live State Reconcile

- Filename note: the April slug is retained for historical ledger continuity; the YAML `date` field matches that slug, while `refresh_date`, `generated_at`, and `Generated` record the current live-state refresh. Freshness checks must read the refresh fields before treating this as current.
- Generated: `2026-07-09T00:20:30Z`
- Recheck: `uv run python scripts/github-public-surface-reconcile.py`
- Claim ceiling: `public_archive`
- Blocking findings: `0`
- Report schema: `schema_version=1`

## Live Repos

| Repo | Visibility | Default SHA | License | Issues | Discussions | Wiki | Pages |
|---|---:|---|---|---:|---:|---:|---:|
| hapax-systems/agentgov | public | ca8b3bdf7ac9 | MIT | true | false | false | false |
| hapax-systems/hapax-council | public | cdef3adece44 | NOASSERTION | true | false | false | false |
| hapax-systems/hapax-constitution | public | ef1deb6110b3 | Apache-2.0 | true | false | true | false |
| hapax-systems/hapax-officium | public | 69583619391b | NOASSERTION | true | false | false | false |
| hapax-systems/hapax-watch | public | f12bf995be38 | NOASSERTION | true | false | false | false |
| hapax-systems/hapax-phone | public | f2843fc5dd77 | NOASSERTION | true | false | false | false |
| hapax-systems/hapax-mcp | public | 44c70eea4ca4 | MIT | true | false | false | false |
| hapax-systems/hapax-research-ledger | public | 5c99dced93b8 | CC0-1.0 | true | false | false | false |
| hapax-systems/hapax-assets | public | 8c69ac2e52b2 |  | true | false | false | true |
| hapax-systems/reins | public | 882ef2129131 | NOASSERTION | true | false | false | false |

## Drift Findings

| Severity | Category | Surface | Summary |
|---|---|---|---|
| high | license_detection | hapax-systems/hapax-constitution | GitHub license detection does not match the registry's expected detection. |
| info | license_detection | hapax-systems/hapax-officium | License posture proved by the root authority file; GitHub detection matches the expected pin. |
| info | license_detection | hapax-systems/hapax-watch | License posture proved by the root authority file; GitHub detection matches the expected pin. |
| info | license_detection | hapax-systems/hapax-phone | License posture proved by the root authority file; GitHub detection matches the expected pin. |
| info | license_detection | hapax-systems/reins | License posture proved by the root authority file; GitHub detection matches the expected pin. |
| info | license_detection | hapax-systems/hapax-council | License posture proved by the root authority file; GitHub detection matches the expected pin. |
| high | settings_truth | hapax-systems/hapax-council | Issues are enabled while GitHub does not report an issue template. |
| high | readme_currentness | README.md | README currentness must be regenerated after live-state reconciliation. |
| high | citation_codemeta_zenodo | CITATION.cff/codemeta.json/.zenodo.json | Citation/CodeMeta/Zenodo metadata must be reconciled after license drift. |
| info | profile_repo_state | hapax-systems/.github | Organization profile README is present at the selected Hapax Systems path. |
| info | notice_links | NOTICE.md | NOTICE links resolve against the current local public-surface evidence. |
| info | pages_cdn_state | hapax-systems/hapax-assets | hapax-assets is visible with a readable GitHub Pages state. |
| info | package_public_surfaces | packages/ | Package public surfaces were inventoried and did not trigger issue/support drift. |
| info | closed_repo_pres_claims | cc-task closed/repo-pres-* | Closed repo-pres task claims were compared to live state. |
| info | contributing_governance | hapax-systems/hapax-council | Category 'contributing_governance' checks ran and observed no drift. |

## Profile README Decision

Current GitHub docs use a public `.github` repository with `profile/README.md` for organization profile READMEs. Hapax public frontmatter is organization-owned, so the selected profile surface is `hapax-systems/.github/profile/README.md`.

## Anti-Overclaim

Observed organization-profile candidate: `visibility=public, private=False, profile_readme=True`.

- live GitHub coherence does not prove research validity.
- live GitHub coherence does not prove livestream health.
- live GitHub coherence does not prove support readiness.
- live GitHub coherence does not prove artifact rights.
- live GitHub coherence does not prove monetization readiness.
