# Zenodo DOI Minting — Research and Execution Playbook

**Date:** 2026-05-10
**Task:** research-zenodo-doi-minting
**Authority:** REQ-20260509-research-positioning-and-publication
**Purpose:** Timestamped archival prior art for CHI 2027 submission (deadline Sep 10, 2026)

## 1. Executive Summary

The Zenodo DOI infrastructure in hapax-council is **largely built but not activated**.
The existing `agents/zenodo_publisher/` handles individual preprint artifacts through
the publication bus. What's needed is a separate, simpler operation: a **repository-level
software deposit** that timestamps the entire codebase and mints a citable DOI.

**Recommended approach:** Zenodo's built-in GitHub integration (toggle-based). This
gives a stable concept DOI plus per-release version DOIs, with zero daemon code.

**Estimated operator time:** 30–45 minutes for sandbox test + production activation.

**Three issues found and resolved in this session:**
1. `PolyForm-Strict-1.0.0` is NOT in Zenodo's license vocabulary (only `polyform-noncommercial` and `polyform-small-business` exist) — `license` field removed from `.zenodo.json`, must be set via web UI post-deposit
2. Community `hapax-publications` does not exist on Zenodo (404) — removed from `.zenodo.json`
3. Creator entry lacked ORCID — added `0009-0001-5146-4548` to `.zenodo.json`, `CITATION.cff`, `codemeta.json`

## 2. Current State

### Already Built

| Component | Location | Status |
|---|---|---|
| Preprint publisher | `agents/zenodo_publisher/publisher.py` | Working; 26 tests |
| Refusal deposit adapter | `agents/refusal_brief_zenodo_adapter/` | Working; 13 tests |
| `.zenodo.json` | repo root | Updated this session |
| `CITATION.cff` | repo root | Updated this session (ORCID, keywords) |
| `codemeta.json` | repo root | Updated this session (ORCID, keywords) |
| Zenodo API token | `pass show zenodo/api-token` | Present |
| ORCID iD | `pass show orcid/orcid` | `0009-0001-5146-4548` |
| Publication bus surfaces | `surface_registry.py` | 4 Zenodo surfaces (FULL_AUTO) |
| Axiom contracts | `axioms/contracts/publication/zenodo-*.yaml` | Rate limits, redactions |
| SWH archival | `agents/attribution/swh_archive_daemon.py` | Independent daemon |

### Not Yet Done

| Item | Blocker |
|---|---|
| GitHub-Zenodo integration | Operator must link accounts via web UI |
| Sandbox deposit test | Requires sandbox.zenodo.org account + separate token |
| Production deposit | Requires GitHub integration toggle + release tag |
| Release tag (v0.1.0) | Requires operator decision on version |
| DOI badge in README | Requires actual DOI (after first deposit) |
| DOI in CITATION.cff | Requires actual DOI |
| DOI in codemeta.json | Requires actual DOI |

## 3. Two Approaches Compared

### A. GitHub Integration (Recommended)

Zenodo's built-in OAuth integration. Toggle a repo on, create a release, Zenodo
auto-archives the source zip and mints a DOI.

**Pros:**
- Simplest setup (5 clicks)
- Automatic versioning: concept DOI (stable, cite this) + version DOI (per release)
- Uses `.zenodo.json` for metadata (already prepared)
- Standard academic workflow — reviewers and citation crawlers expect this pattern
- Zero custom code needed

**Cons:**
- Deposits entire repo as zip (no file selection)
- License must be set manually post-deposit (PolyForm-Strict not in vocabulary)
- OAuth authorization required (one-time)

### B. REST API Direct Deposit

Use the existing PAT (`zenodo/api-token`) to create a deposit via
`POST /api/deposit/depositions`, upload files, publish.

**Pros:**
- Full metadata control
- Can upload specific files
- Existing publisher code provides a template

**Cons:**
- More complex — need to build a new code path (existing publisher is for PreprintArtifact, not repo archives)
- Manual versioning
- No automatic per-release deposits unless wrapped in GitHub Actions

### Decision: GitHub Integration

The GitHub integration is the standard path for research software DOIs. It provides
the concept DOI needed for CITATION.cff and CHI 2027 citation. The license issue is
a one-time manual correction after the first deposit.

## 4. License Issue — Detailed

### Problem

Zenodo's license vocabulary (queried live at `GET /api/vocabularies/licenses/?q=polyform`)
returns only:
- `polyform-noncommercial-1.0.0`
- `polyform-small-business-1.0.0`

`PolyForm-Strict-1.0.0` is absent. If `.zenodo.json` includes an unrecognized `license`
value, the GitHub integration will either reject the deposit or assign no license.

### Resolution

1. Removed `"license"` from `.zenodo.json` — the integration will create the deposit
   without a standard license
2. After the first deposit, edit via Zenodo web UI: record → Edit → Licenses →
   "Add custom" → title "PolyForm Strict License 1.0.0", link
   `https://polyformproject.org/licenses/strict/1.0.0/`
3. `CITATION.cff` and `codemeta.json` retain `PolyForm-Strict-1.0.0` — these are
   project-side metadata and are not constrained by Zenodo's vocabulary

### Consistency Across Surfaces

| Surface | License declared | Source |
|---|---|---|
| `LICENSE` file | Apache 2.0 | In transition (see `docs/governance/license-reconciliation-status.md`) |
| `NOTICE.md` | PolyForm Strict 1.0.0 | Canonical |
| `CITATION.cff` | PolyForm-Strict-1.0.0 | SPDX identifier |
| `codemeta.json` | polyformproject.org URL | Schema.org |
| `.zenodo.json` | (removed — set via web UI) | Zenodo vocabulary |

The LICENSE file discrepancy (Apache 2.0 vs PolyForm Strict) is a separate operator
decision documented at `docs/governance/license-reconciliation-status.md`. It does
not block Zenodo deposit — the `.zenodo.json` metadata takes precedence over the
LICENSE file in the GitHub integration.

## 5. Existing Publisher vs Repository DOI

These are distinct use cases that coexist:

| Aspect | Preprint Publisher | Repository DOI |
|---|---|---|
| Purpose | DOI per research artifact | DOI for the codebase itself |
| Upload type | `publication` / `preprint` | `software` |
| Trigger | Publication bus dispatch | GitHub release creation |
| Code | `agents/zenodo_publisher/` | Zenodo GitHub integration (no code) |
| Token | `HAPAX_ZENODO_TOKEN` (PAT) | OAuth (GitHub integration) |
| Versioning | One-off per artifact | Concept + version DOIs |

Both can use the same Zenodo account. They produce separate, independent records.

## 6. Operator Execution Playbook

### Phase 1: Sandbox Test (15 min)

1. **Create sandbox account** at `https://sandbox.zenodo.org/signup/`
   (separate from production — use same email)

2. **Link GitHub** at `https://sandbox.zenodo.org/account/settings/github/`
   - Click "Connect" → authorize OAuth → "Sync now"

3. **Enable repo** — find `ryanklee/hapax-council` in the list, toggle slider on

4. **Create test release** on GitHub:
   ```
   gh release create v0.0.1-sandbox-test --title "Sandbox test" --notes "Zenodo integration test" --prerelease
   ```

5. **Verify deposit** — check `https://sandbox.zenodo.org/me/uploads` within 1–2 minutes
   - Confirm metadata populated from `.zenodo.json`
   - Confirm ORCID linked to creator
   - Confirm keywords present
   - Note: DOI prefix will be `10.5072` (test, not registered with DataCite)

6. **Delete test release** (sandbox deposits are ephemeral):
   ```
   gh release delete v0.0.1-sandbox-test --yes && git push origin --delete v0.0.1-sandbox-test
   ```

### Phase 2: Production Deposit (15 min)

1. **Link GitHub** at `https://zenodo.org/account/settings/github/`
   - Click "Connect" → authorize OAuth → "Sync now"

2. **Enable repo** — find `ryanklee/hapax-council`, toggle on

3. **Create production release**:
   ```
   gh release create v0.1.0 --title "v0.1.0 — Research apparatus archive" --notes "Initial archival deposit for CHI 2027 prior art. Stigmergic cognitive mesh with formal constitutional governance, 200+ agents, voice daemon, GPU visual expression, and 24/7 livestream as research instrument."
   ```

4. **Wait for deposit** — check `https://zenodo.org/me/uploads` (1–2 min)

5. **Set custom license** via web UI:
   - Open the deposit record → Edit
   - Under Licenses → "Add custom"
   - Title: `PolyForm Strict License 1.0.0`
   - URL: `https://polyformproject.org/licenses/strict/1.0.0/`
   - Save → Publish

6. **Record the DOIs** — the deposit page shows:
   - **Concept DOI** (stable): `10.5281/zenodo.NNNNNNN` — use this in citations
   - **Version DOI**: `10.5281/zenodo.MMMMMMM` — specific to v0.1.0

### Phase 3: Post-DOI File Updates (5 min)

After obtaining the concept DOI, a follow-up commit updates three files:

**CITATION.cff** — add after `url:` line:
```yaml
doi: 10.5281/zenodo.NNNNNNN
```

**codemeta.json** — add after `"url":` field:
```json
"identifier": "https://doi.org/10.5281/zenodo.NNNNNNN",
```

**README.md** — add DOI badge after the CI badge (line 5):
```markdown
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.NNNNNNN.svg)](https://doi.org/10.5281/zenodo.NNNNNNN)
```

## 7. Relationship to CHI 2027

The Zenodo DOI serves three functions for the CHI 2027 submission (deadline Sep 10, 2026):

1. **Timestamped prior art** — the deposit proves the codebase existed at the release date,
   independent of GitHub (which is not an archival platform)

2. **Citable reference** — the DOI is the canonical citation in the paper's references section.
   ACM requires DOIs where available.

3. **Supplementary material** — the Zenodo record can be linked from the paper as
   supplementary software. The `.zenodo.json` keywords are optimized for discoverability
   by reviewers in the "Systems, Tools, Architectures" subcommittee.

The concept DOI should be obtained well before the July 2027 drafting window. The
current timeline (deposit by end of May 2026) provides 4 months of buffer.

## 8. Relationship to Existing Infrastructure

### Software Heritage (SWH)

SWH archival (`agents/attribution/swh_archive_daemon.py`) provides a SWHID — a
content-addressed identifier for the exact source tree. SWHIDs complement DOIs:
- DOI → "this project" (Zenodo landing page)
- SWHID → "this exact commit/tree" (byte-for-byte content)

Both should appear in the CHI 2027 paper. SWH archival runs independently and
does not require any changes for the Zenodo DOI.

### Publication Bus Preprint Publisher

The existing `zenodo_publisher` continues to serve individual preprint DOIs via
the publication bus. The repository DOI is a separate record. No code changes
needed — the two are orthogonal.

### Revenue Infrastructure

The Zenodo DOI is not a revenue surface. It's a citation/archival surface. The
revenue infrastructure (GitHub Sponsors, payment rails) is a separate activation
tracked in the parent spec's Phase 5.

## 9. Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| PolyForm-Strict rejected by Zenodo UI | Low | Custom license feature is documented and tested; fall back to `access_right: restricted` |
| GitHub integration fails silently | Low | Check sandbox first; Zenodo shows failed deposits in upload dashboard |
| Large repo size causes timeout | Low | Repo is ~130K lines; well within Zenodo's 50GB limit |
| Community `hapax-publications` needed | None | Removed from `.zenodo.json`; can create community later and add via edit |
| License reconciliation blocks deposit | None | `.zenodo.json` omits license; CITATION.cff/codemeta.json are project-side |

## 10. Files Modified in This Session

| File | Change | Purpose |
|---|---|---|
| `.zenodo.json` | ORCID added, license removed, community removed, description expanded, keywords expanded | Fix three blocking issues |
| `CITATION.cff` | ORCID added, abstract expanded, keywords expanded | Align with `.zenodo.json` |
| `codemeta.json` | ORCID `@id` added, description expanded, keywords expanded | Align with `.zenodo.json` |
| `docs/research/2026-05-10-zenodo-doi-minting-research.md` | Created | This document |
