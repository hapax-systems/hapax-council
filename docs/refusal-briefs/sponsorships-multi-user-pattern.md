# Refusal Brief: GitHub Sponsorships as Multi-User Pattern

**Slug:** `repo-pres-funding-yml-disable`
**Axiom tag:** `single_user` + `corporate_boundary`
**Refusal classification:** Multi-user-shape affordance
**Status:** SUPERSEDED for `hapax-systems/hapax-council` receive-only org support; still refused for sponsorware, perks, private access, repo-setting automation, and generic multi-user monetization shapes.
**Date:** 2026-04-26
**Source research:** drop 3 §3, drop 4 §10

## What is refused

GitHub Sponsorships UI that sells or implies a multi-party service relationship:
- Sponsor tiers with access, requests, private advice, priority, shoutouts,
  guarantees, client service, deliverables, or control
- Sponsorware, early-access, exclusive-content, role-gate, or request-queue copy
- Agent/script automation that toggles repo Settings with `has_sponsorships=true`

The `research-github-sponsors` task reopens one narrow receive-only surface:
`hapax-systems` org Sponsors metadata, `.github/FUNDING.yml`, and no-perk
donation tiers whose public receipts remain aggregate-only.

## Why this is refused

### Multi-user-shape affordance

Sponsorships presupposes a multi-tenant contributor relationship: a sponsor (one party) financially supports a maintainer (another party). The operator's `single_user` axiom (weight 100) explicitly prohibits multi-user shapes — there is no maintainer/contributor distinction to monetise. The work is single-operator personal infrastructure.

### Empty FUNDING.yml is insufficient

Per drop 3 §3: GitHub treats an empty or absent `.github/FUNDING.yml` as a hint, NOT a structural disable. The "Sponsor" button can still surface based on per-account default settings or upstream maintainer-pattern detection. The structural disable is the **repo Settings flag** (`has_sponsorships=false`) — the dual operation (delete file + patch Settings) is required.

### Marketing-shape boundary

Sponsorships is a marketing affordance: it optimises for visibility + monetisation patterns that contradict the corporate-boundary axiom (personal infrastructure ≠ commercial product). The license-request mail-routing path (`agents/mail_monitor/processors/license_request.py`) is the constitutional counterpart for monetary engagement: deterministic, daemon-tractable, refusal-as-data-anchored.

## Daemon-tractable boundary

`scripts/disable-sponsorships.sh` remains the rollback path for repositories
that should not expose Sponsorships. It is not the activation path for
`hapax-systems/hapax-council`; activation uses GitHub Sponsors profile/tier
GraphQL/dashboard setup plus `.github/FUNDING.yml`.

## Refused implementation

- NO perk-bearing GitHub Sponsors tiers
- NO sponsorware, early access, private channels, request queues, role gates,
  priority response, name acknowledgments, leaderboards, client service, or
  ad-read deliverables
- NO agent/script mutation that sets `has_sponsorships=true`
- NO sponsor identity or comment projection in public receipt state

## Lift conditions

The original broad refusal cannot lift while:

- The `single_user` axiom is in effect (constitutional, weight 100)
- The corporate-boundary axiom is in effect (constitutional, weight 90)

The receive-only org support exception is valid only while it preserves the
no-perk doctrine and aggregate-only receipt policy.

## Cross-references

- Source research: drop 3 §3, drop 4 §10 anti-pattern
- Sister refusals: `repo-pres-pinned-repos-removal` (same trying-to-trend family)
- Constitutional alternative: `agents/mail_monitor/processors/license_request.py` (LICENSE-REQUEST routing as the daemon-tractable monetary engagement path)
- Implementation: `scripts/disable-sponsorships.sh`
