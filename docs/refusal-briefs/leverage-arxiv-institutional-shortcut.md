# Refusal Brief: arXiv Institutional-Email Submission Shortcut

**Slug:** `leverage-REFUSED-arxiv-institutional-email-shortcut`
**Refusal classification:** Documentary — path closed by arXiv (Jan 2026), not by constitutional choice
**Status:** REFUSED — closed by upstream; the documentary refusal preserves the historical record.
**Date:** 2026-04-26
**Related cc-task:** `leverage-REFUSED-arxiv-institutional-email-shortcut`
**Cross-links:**
  - Replacement path: `leverage-attrib-arxiv-velocity-preprint` (endorser-courtship, FULL_AUTO via cold-contact mechanic #1)
  - Historical: this brief preserves the closed-shortcut for the refusal-as-data substrate

## What was refused

The institutional-email shortcut for first-time arXiv submissions:
prior to January 2026, submitters with `.edu` (or other approved
institutional) addresses bypassed the endorser-courtship gate and
submitted preprints directly. This was a daemon-tractable shortcut
for first-submission flow.

## Why this is refused

This is a **documentary refusal**, not a constitutional one. The path
is closed by arXiv itself. From January 2026 forward, all first-time
submitters require an endorser — a current arXiv contributor in the
relevant subject area who endorses the new submitter's first paper
before it can post.

There is no daemon-tractable workaround. The institutional-email
verification step is no longer accepted regardless of the operator's
account state. The refusal preserves this fact in the
refusal-as-data substrate so that future audits of the publish-bus
landscape understand why the institutional-email path is unwired.

## Daemon-tractable boundary (the replacement path)

`leverage-attrib-arxiv-velocity-preprint` (cold-contact mechanic #1)
is the FULL_AUTO replacement: identify candidate endorsers in the
operator's audience-vector via the cold-contact candidate registry,
generate Zenodo deposits + named-related-work cross-references that
build endorser awareness, then request endorsement after the citation
graph has produced the relationship signal.

This path is daemon-tractable because:
- Endorser discovery is daemon-side (ORCID public API + DataCite
  Commons GraphQL)
- Citation-graph construction is daemon-side (Zenodo
  RelatedIdentifier graph, shipped in PR #1474)
- Endorsement-request composition is daemon-side via the publication-
  bus

The refused institutional-email shortcut would have bypassed the
endorser-courtship work; with the shortcut closed, the courtship is
not optional but constitutive of the arXiv submission flow.

## Refused implementation

NO `agents/paper_assembler/arxiv_institutional_email.py`. The
`paper_assembler` package, when shipped, must use the endorser-
courtship path exclusively.

## Lift conditions

This is a documentary refusal grounded in upstream policy. Lift
requires arXiv to re-open the institutional-email shortcut. Probe
URL: `https://arxiv.org/help/registerhelp` (or the contemporaneous
arXiv policy page). Lift keyword: presence of "institutional email
verification" / "no endorser required for `.edu` accounts" / similar.

The `refused-lifecycle-structural-watcher` daemon (when shipped)
will check this probe per its weekly cadence (type-A structural
trigger).

## Cross-references

- cc-task vault note: `leverage-REFUSED-arxiv-institutional-email-shortcut.md`
- Replacement cc-task: `leverage-attrib-arxiv-velocity-preprint.md`
- Cold-contact mechanic #1 (drop-2 §3): endorser-courtship via
  citation-graph relationship signal
- Source research: drop-leverage strategy
  (`docs/research/2026-04-25-leverage-strategy.md`)
