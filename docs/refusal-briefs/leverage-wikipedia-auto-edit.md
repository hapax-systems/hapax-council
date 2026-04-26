# Refusal Brief: Wikipedia Automated Editing

**Slug:** `leverage-REFUSED-wikipedia-auto-edit`
**Axiom tag:** `single_user`, `feedback_full_automation_or_no_engagement`
**Refusal classification:** ToS prohibition + multi-user platform — double constitutional barrier
**Status:** REFUSED — no Wikipedia bot account, no `agents/wikipedia_writer/`.
**Date:** 2026-04-26
**Related cc-task:** `leverage-REFUSED-wikipedia-auto-edit`
**CI guard:** `tests/test_forbidden_social_media_imports.py` (now general "multi-user-platform" guard)

## What was refused

- Wikipedia bot account creation (any operator-flagged or unflagged)
- `agents/wikipedia_writer/` package
- Automated edits to Hapax-relevant articles (single-operator axiom)
- Automated edits to operator's own biographical record (vanity-edit policy + per-edit operator decisions)
- `pywikibot` / `mwclient` client adoption (CI guard)

## Why this is refused

### Wikipedia ToS prohibition

Wikipedia's bot policy requires:
1. **Bot flag approval** via Bot Approvals Group (multi-week per-task review)
2. **Per-task scope** — every edit type requires separate approval
3. **Active operator oversight** — operator monitors the bot's edits, responds to user complaints, halts on consensus dispute

Even with bot-flag approval, the per-edit operator-oversight requirement
makes this operator-physical, not daemon-tractable.

### Single-operator axiom (constitutional)

Wikipedia is inherently multi-user — articles are co-authored by many
parties; edit conflicts require talk-page negotiation; consensus
disputes require operator-physical engagement. The single-operator
axiom precludes daemon participation as an authoring agent.

### Full-automation envelope

Per `feedback_full_automation_or_no_engagement` (operator
constitutional directive 2026-04-25T16:55Z): the operator refuses
research / engagement surfaces not fully Hapax-automated. Even a
"flagged bot" pattern would either be:
- Operator-mediated (per-edit decisions in conventional Wikipedia
  workflow)
- Engagement-bait (talk-page replies require operator attention)

Both violate the constitutional posture.

## Daemon-tractable boundary

Hapax does NOT need to participate in Wikipedia for academic-citation
discoverability. Wikipedia citations to Hapax can arrive **organically**:

1. Third-party editors notice operator's arXiv preprint or Zenodo DOI
2. They cite Hapax in articles within their topic-area expertise
3. Wikipedia's reference style + citation graph carry the citation

The operator's role in this flow is to **publish** (Zenodo, arXiv,
omg.lol weblog) and **maintain CITATION.cff metadata**, not to edit
Wikipedia. The publish-bus already covers this; no Wikipedia client
is needed.

## CI guard

`tests/test_forbidden_social_media_imports.py` (now a general
multi-user-platform guard) scans `agents/`, `shared/`, `scripts/`,
`logos/` for any import of:

- `pywikibot` (Wikimedia Foundation's Python framework)
- `mwclient` (community-maintained MediaWiki client)

CI fails on any match.

## Refused implementation

- NO `agents/wikipedia_writer/`
- NO `pywikibot` or `mwclient` in `pyproject.toml` deps
- NO Wikipedia API key in `pass` store
- NO bot-account creation in any Wikipedia language edition
- License-request auto-reply does NOT mention Wikipedia citations as a
  request channel

## Lift conditions

This is a constitutional + ToS-grounded refusal. Lift requires
either:
- Wikipedia ToS revision permitting unflagged bot editing without
  per-edit oversight (extremely unlikely; multi-decade community
  norm)
- Single-operator axiom retirement
- Full-automation envelope removal

The `refused-lifecycle-conditional-watcher` daemon (when shipped)
will check both probes per its cadence policy.

## Cross-references

- cc-task vault note: `leverage-REFUSED-wikipedia-auto-edit.md`
- CI guard: `tests/test_forbidden_social_media_imports.py`
- Bridgy POSSE alternative for general public-feed reach:
  `agents/publication_bus/bridgy_publisher.py`
- Citation discoverability path: `agents/publication_bus/datacite_mirror.py`
  (DataCite Commons GraphQL mirror) + `agents/attribution/`
- Source research: drop-leverage strategy
  (`docs/research/2026-04-25-leverage-strategy.md`)
