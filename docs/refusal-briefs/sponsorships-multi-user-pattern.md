# Refusal Brief: GitHub Sponsorships as Multi-User Pattern

**Slug:** `repo-pres-funding-yml-disable`
**Axiom tag:** `single_user` + `corporate_boundary`
**Refusal classification:** Multi-user-shape affordance
**Status:** REFUSED — operator's pushable repos keep `has_sponsorships=false`.
**Date:** 2026-04-26
**Source research:** drop 3 §3, drop 4 §10

## What is refused

GitHub Sponsorships UI on the operator's pushable repos:
- The "Sponsor this project" button on repo headers
- The `.github/FUNDING.yml` file (no funding-link declaration)
- The repo Settings → Sponsorships → "Enable sponsorships" toggle

## Why this is refused

### Multi-user-shape affordance

Sponsorships presupposes a multi-tenant contributor relationship: a sponsor (one party) financially supports a maintainer (another party). The operator's `single_user` axiom (weight 100) explicitly prohibits multi-user shapes — there is no maintainer/contributor distinction to monetise. The work is single-operator personal infrastructure.

### Empty FUNDING.yml is insufficient

Per drop 3 §3: GitHub treats an empty or absent `.github/FUNDING.yml` as a hint, NOT a structural disable. The "Sponsor" button can still surface based on per-account default settings or upstream maintainer-pattern detection. The structural disable is the **repo Settings flag** (`has_sponsorships=false`) — the dual operation (delete file + patch Settings) is required.

### Marketing-shape boundary

Sponsorships is a marketing affordance: it optimises for visibility + monetisation patterns that contradict the corporate-boundary axiom (personal infrastructure ≠ commercial product). The license-request mail-routing path (`agents/mail_monitor/processors/license_request.py`) is the constitutional counterpart for monetary engagement: deterministic, daemon-tractable, refusal-as-data-anchored.

## Daemon-tractable boundary

`scripts/disable-sponsorships.sh` issues `gh api PATCH` for each of the 7 pushable repos to set `has_sponsorships=false`. Idempotent — re-running after first success is a no-op. Operator runs once; CI drift check (monthly) re-asserts the flag.

## Refused implementation

- NO `.github/FUNDING.yml` in any pushable repo
- NO `has_sponsorships=true` in any pushable repo's Settings
- NO recommendation that the operator enable Sponsorships
- NO sponsor-tier rendering on any operator-facing surface

## Lift conditions

This refusal cannot lift while:

- The `single_user` axiom is in effect (constitutional, weight 100)
- The corporate-boundary axiom is in effect (constitutional, weight 90)

Lift would require constitutional amendment on either axis.

## Cross-references

- Source research: drop 3 §3, drop 4 §10 anti-pattern
- Sister refusals: `repo-pres-pinned-repos-removal` (same trying-to-trend family)
- Constitutional alternative: `agents/mail_monitor/processors/license_request.py` (LICENSE-REQUEST routing as the daemon-tractable monetary engagement path)
- Implementation: `scripts/disable-sponsorships.sh`
