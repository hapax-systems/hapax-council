---
title: GitHub public surface live state reconcile
date: 2026-07-08
status: evidence-produced
source: github-public-surface-live-state-reconcile
---

# GitHub Public Surface Live State Reconcile

- Filename note: the April slug is retained for historical ledger continuity; the YAML `date` and `Generated` fields record the current live-state refresh. Freshness checks must read those fields, not the filename slug. Re-run the `Recheck` command below before treating this as current.
- Generated: `2026-07-08T10:05:30Z`
- Recheck: `uv run python scripts/github-public-surface-reconcile.py`
- Claim ceiling: `public_archive`
- Blocking findings: `1`
- Report schema: `schema_version=1`

## Live Repos

| Repo | Visibility | Default SHA | License | Issues | Discussions | Wiki | Pages |
|---|---:|---|---|---:|---:|---:|---:|
| hapax-systems/hapax-council | public | 21b9e9153e98 | NOASSERTION | true | false | false | false |
| hapax-systems/hapax-constitution | public | 96ea7f557e50 | Apache-2.0 | true | false | true | false |
| hapax-systems/hapax-officium | public | 69583619391b | NOASSERTION | true | false | false | false |
| hapax-systems/hapax-watch | public | f12bf995be38 | NOASSERTION | true | false | false | false |
| hapax-systems/hapax-phone | public | f2843fc5dd77 | NOASSERTION | true | false | false | false |
| hapax-systems/hapax-mcp | public | 44c70eea4ca4 | MIT | true | false | false | false |
| hapax-systems/hapax-assets | public | 1890c08b4d72 |  | true | false | false | true |

## Drift Findings

| Severity | Category | Surface | Summary |
|---|---|---|---|
| high | license_detection | hapax-systems/hapax-constitution | GitHub detected license does not match the repo registry policy. |
| high | license_detection | hapax-systems/hapax-officium | GitHub detected license does not match the repo registry policy. |
| high | license_detection | hapax-systems/hapax-watch | GitHub detected license does not match the repo registry policy. |
| high | license_detection | hapax-systems/hapax-phone | GitHub detected license does not match the repo registry policy. |
| blocking | license_detection | hapax-systems/hapax-council | GitHub/root license detection contradicts the repo registry policy. |
| high | contributing_governance | hapax-systems/hapax-council | GOVERNANCE.md is missing from the public repo root. |
| high | settings_truth | hapax-systems/hapax-council | Issues are enabled while GitHub does not report an issue template. |
| high | readme_currentness | README.md | README currentness must be regenerated after live-state reconciliation. |
| high | citation_codemeta_zenodo | CITATION.cff/codemeta.json/.zenodo.json | Citation/CodeMeta/Zenodo metadata must be reconciled after license drift. |
| info | profile_repo_state | hapax-systems/.github | Organization profile README is present at the selected Hapax Systems path. |
| info | notice_links | NOTICE.md | NOTICE links resolve against the current local public-surface evidence. |
| info | pages_cdn_state | hapax-systems/hapax-assets | hapax-assets is visible with a readable GitHub Pages state. |
| medium | package_public_surfaces | packages/ | Some package README/PyPI surfaces contain issue/support language needing claim discipline. |
| high | closed_repo_pres_claims | cc-task closed/repo-pres-* | Closed repo-pres task claims were compared to live state. |

## Profile README Decision

Current GitHub docs use a public `.github` repository with `profile/README.md` for organization profile READMEs. Hapax public frontmatter is organization-owned, so the selected profile surface is `hapax-systems/.github/profile/README.md`.

## Anti-Overclaim

Observed organization-profile candidate: `visibility=public, private=False, profile_readme=True`.

- live GitHub coherence does not prove research validity.
- live GitHub coherence does not prove livestream health.
- live GitHub coherence does not prove support readiness.
- live GitHub coherence does not prove artifact rights.
- live GitHub coherence does not prove monetization readiness.
