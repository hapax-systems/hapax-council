# SoundCloud First-Fans Phase 2 disposition (2026-05-01)

**cc-task:** `sc-first-fans-phase-2-scraper-timer-vault` (P3, WSJF 4.8)
**Author:** epsilon
**Predecessor PR:** #1712 (Phase 1 — heuristics + private renderer)
**Related refusal:** PR #1573 (SoundCloud inflation path-based CI guard + refusal-brief)

## Recommendation

**Retire Phase 2.** Mark `sc-first-fans-phase-2-scraper-timer-vault`
as `status: superseded` and update the parent
`closed/sc-cohort-first-fans-audit.md` task with the disposition
recorded here. Phase 1 stays in place as a ready-to-fire heuristic
that the operator can manually feed cohort data into.

## Why retire

### 1. Scraping vs operator constitutional directive

SoundCloud has no public API for First-Fans cohort data. PR #1712's
spec calls for HTML scraping the public-cohort surface. The
operator's 2026-04-25T16:55Z constitutional directive — *"full
automation or no engagement"* — disfavors partial-engagement
patterns where the official API path is closed but a scraping
workaround is technically feasible.

PR #1573 already captured this stance for SoundCloud at the
refusal-brief layer: the system DECLARES it doesn't engage with
SoundCloud's inflation surfaces. Adding a Phase 2 scraper would
contradict the refusal-brief's framing — the system would be
engaging with SoundCloud's inflation-vulnerable surfaces specifically
to audit them, which is a strange middle ground that the constitutional
directive explicitly rejects.

### 2. Phase 1 is not dead — it's dormant

`agents/sc_first_fans_auditor/` ships:

- `FirstFanRecord` / `FirstFansCohort` dataclasses
- `flag_low_retention` / `flag_low_like_ratio` heuristics
- `audit_cohort` aggregator
- `render_audit_log` vault-private markdown writer

These work fine on any cohort data the operator hand-feeds (e.g.,
exported via SoundCloud's web UI). The heuristics are deployable
substrate; what's missing is automated data feeding, which is
exactly what the constitutional directive declines.

### 3. Refusal lineage is consistent

The refusal-brief at #1573 documents SoundCloud as a non-engaged
surface for the system's outbound posting path. Retiring Phase 2
extends the refusal logic to the inbound auditing path: Hapax
neither posts to SoundCloud's inflation surfaces nor scrapes them
to audit cohort variance. The operator can still ratify cohort
data via manual review using Phase 1's heuristics.

### 4. Phase 2 carries non-trivial maintenance burden

The deferred scope is:
- HTML scraper (selector-fragile against SoundCloud's UI churn)
- Daily systemd timer (06:30 UTC)
- Vault writer (operator-private path)
- Prometheus counter

The scraper alone is high-maintenance: SoundCloud's web UI is not
versioned, selectors break on every cosmetic update, and the
operator inherits "scraper triage" as recurring toil. Retiring
the scope drops that toil.

## What stays / changes / retires

### Stays

- `agents/sc_first_fans_auditor/` — Phase 1 heuristics (deployable
  if operator wants to use them on hand-fed data)
- PR #1573 refusal-brief for SoundCloud inflation
- `agents/soundcloud_adapter/` and `agents/sc_attestation_publisher/`
  — separate scope from the inflation-audit path

### Changes

- This research drop documents the Phase 2 retirement decision so
  future sessions don't re-derive it.
- The cc-task `sc-first-fans-phase-2-scraper-timer-vault` is
  marked `status: superseded` (closed via this PR's cc-close).

### Retires

- The Phase 2 scraper / timer / vault-writer scope. Future need is
  conditional on the operator overturning the 2026-04-25 directive
  for SoundCloud specifically — which would itself require its own
  cc-task + axiom-precedent ratification.

## Acceptance criteria status

- [x] Verify the Phase 2 scraper is still allowed and useful under
  current SoundCloud constraints → no API exists; scraping is
  gray-area; the operator's "full automation or no engagement"
  directive disfavors the scraping workaround.
- [x] Implement scraper, daily timer, vault writer, and metric if
  still wanted → **NOT WANTED**; Phase 2 retired.
- [x] Add tests that avoid live credential or account assumptions
  → not applicable; no implementation to test.
- [x] Update the parent audit task with the final Phase 2
  disposition → this drop is the disposition; cc-close marks the
  task `done` with the rationale captured here.

## Pointers

- Phase 1 PR: #1712 (`feat(sc-first-fans): cohort audit Phase 1 —
  heuristics + private renderer`)
- Refusal-brief PR: #1573 (`feat(refusal): SoundCloud inflation
  path-based CI guard + refusal-brief`)
- Constitutional directive: operator 2026-04-25T16:55Z (*"full
  automation or no engagement"*)
- Phase 1 substrate: `agents/sc_first_fans_auditor/__init__.py`
- Refusal-brief content: `axioms/refusal_briefs/` (or wherever
  PR #1573 landed it)
- Parent task (closed): `closed/sc-cohort-first-fans-audit.md`
