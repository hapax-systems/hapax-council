# Refusal Brief: Pinned Repos as Trending Affordance

**Slug:** `repo-pres-pinned-repos-removal`
**Axiom tag:** `corporate_boundary` (anti-marketing) + `interpersonal_transparency` (canonical-surface discipline)
**Refusal classification:** Trending-affordance anti-pattern
**Status:** REFUSED — operator's GitHub profile keeps zero pinned repos.
**Date:** 2026-04-26
**Source research:** drop 3 anti-pattern §10, drop 4 §10

## What is refused

Pinned repositories on `github.com/ryanklee` profile (the GitHub UI feature that highlights up to 6 repos at the top of a user profile).

## Why this is refused

### Trying-to-trend affordance

Pinned repos exist to optimise discoverability via GitHub's recommendation surfaces. They are explicitly designed to make a user's work more visible, more clickable, more rankable. This is a marketing-shape affordance — the operator's anti-marketing constitutional stance treats marketing-shape as a refusal axis. The corporate-boundary axiom forbids treating personal infrastructure work as commercial product.

### Canonical-surface discipline

Per drop 4 §4, the canonical operator presence on GitHub is the org-level profile-README at `github.com/ryanklee/.github`. That single surface carries the constitutional posture, the project list, the contribution policy. Pinned repos compete with this canonical surface — they fragment attention and re-introduce the very "marketing collage" pattern the canonical surface is designed to displace.

### Refusal-as-data

The empty pinned-repo slot, paired with the populated org-level profile-README, is itself a first-class constitutional artefact. A visitor to `github.com/ryanklee` sees the absence and is routed (by GitHub's UI) to the README — that's the architectural argument made structural.

## Daemon-tractable boundary

`scripts/remove-pinned-repos.sh` issues `gh api` GraphQL mutations to unpin all currently-pinned items. Idempotent. CI drift check (monthly) re-asserts zero pinned items.

## Refused implementation

- NO `gh api graphql ... pinItem` calls in agents
- NO recommendation that the operator pin "their best work" anywhere
- NO ranking / popularity heuristic for which repos to surface
- NO automation that re-pins after a manual unpin

## Lift conditions

This refusal cannot lift while:

- The corporate-boundary axiom is in effect
- The canonical-surface-discipline directive (drop 4 §4) is in effect

Lift would require either retiring those axioms or constitutional re-evaluation of the marketing-shape boundary.

## Cross-references

- Source research: drop 3 §10, drop 4 §10
- Canonical surface: `repo-pres-org-level-github` (sister cc-task; populates `ryanklee/.github`)
- Implementation: `scripts/remove-pinned-repos.sh`
- Sister refusals: `repo-pres-shared-workflows`, `repo-pres-issues-redirect-walls` (same canonical-surface family)
