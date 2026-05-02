# Velocity arXiv Endorser Path — Supersession Notice

**Authored:** 2026-05-02 by beta.
**cc-task:** `velocity-arxiv-endorser-path-followup` (WSJF 4.5, p3) closes via this doc.
**Superseded architecture:** `docs/research/2026-04-26-arxiv-velocity-preprint-architecture.md` (alpha, 2026-04-26).
**Replacement publication path:** documented in §3 below.

## Decision

The arXiv endorser-courtship architecture (§Missing components in the source arch doc — `endorser-discovery`, `endorser-request publisher`, `courtship daemon`, `integration smoke`, `manuscript-draft deliverables`) is **superseded**. Implementation is **not pursued**. The replacement publication path (§3) exists in tree and ships velocity-class artifacts via existing surfaces.

## §1 Why superseded

The endorser-courtship daemon as described requires **outreach to academic endorsers** to obtain the arXiv first-time-submitter endorsement that arXiv mandated post-Jan 2026 for cs.SE / cs.AI / cs.HC. Three load-bearing constraints make this incompatible with current Hapax architecture:

1. **Direct outreach is REFUSED axiomatically.** `agents/cold_contact/candidate_registry.py:74-76` documents the family-wide refusal:
   > *"a registry row, not a contact-database row. There is no email field, no telephone, no address — direct outreach is REFUSED per the family-wide refusal …"*

   The cold-contact module deliberately omits the very fields a courtship daemon would require. Any "endorser-request publisher" that reaches academics directly violates this posture.

2. **The institutional-email shortcut already documented as REFUSED.** The closed cc-task `leverage-REFUSED-arxiv-institutional-email-shortcut` (status: done) carries the operator-decision provenance for declining the institutional path. The endorser path is a different mechanism but lands in the same operator policy.

3. **The 2026-04-26 architecture doc itself was preliminary** and shipped only the **deposit composer** (PR #1677, `feat(publish): velocity-findings preprint composer`). The "Missing components" enumerated there were never implemented; the dep that this followup waited for (`velocity-report-identifiers-metrics-reconcile`, now closed/done) confirms the velocity rails are truthful but does NOT change the outreach posture.

## §2 Acceptance criteria mapping (cc-task closure)

| Criterion | Disposition |
|---|---|
| Re-evaluate endorser-discovery / endorser-request publisher / courtship daemon / integration smoke / manuscript-draft deliverables | DONE: each is incompatible with no-direct-outreach posture (§1). |
| If still desired, split architecture into precise implementation tasks and keep formal arXiv action operator-mediated | NOT desired (§1). No splits filed. |
| If no longer desired, mark architecture superseded and explain replacement publication path | DONE (this doc, §3). |
| Do not mint or submit arXiv artifacts from unreconciled old velocity prose | OBSERVED: PR #1677 ships only the composer; no arXiv submission daemon exists. |

## §3 Replacement publication path

Velocity-class findings already ship via the operator-curated publication-bus surfaces (registered in `agents/publication_bus/surface_registry.py`):

| Surface | Slug | Citation-graph contribution |
|---|---|---|
| Zenodo (concept-DOI) | `zenodo-doi`, `zenodo-related-identifier-graph` | DataCite RelatedIdentifier graph; concept-DOI granularity per ORCID auto-update (`orcid-auto-update`) |
| Zenodo refusal-shaped deposit | `zenodo-refusal-deposit` | refusal-as-data DOI nodes; refusal-shaped RelatedIdentifier edges |
| OSF preregistration | `osf-prereg` | named-related-work cross-references |
| OSF preprint | `osf-preprint` | DataCite-discoverable DOI |
| PhilArchive deposit | `philarchive-deposit` (CONDITIONAL_ENGAGE) | philosophy-side discoverability; bootstrap one-time login via Playwright session daemon |
| Internet Archive | `internet-archive-ias3` | durable preservation rail |
| omg.lol weblog (operator + oudepode) | `omg-weblog`, `oudepode-omg-weblog` | operator-owned narrative surface |
| Bluesky (operator + oudepode) | `bluesky-atproto-multi-identity`, `oudepode-bluesky-atproto` | social-graph touch (no facilitator outreach required) |
| Bridgy webmention fanout | `bridgy-webmention-publish` | weblog → social cross-link |
| omg.lol bearer fanout | `omg-lol-weblog-bearer-fanout` | scheduled cross-weblog amplification |
| Marketing refusal annex | `marketing-refusal-annex` | local refusal-as-data file |

The combined effect:

- **Discoverability:** Zenodo concept-DOIs are crawled by Google Scholar, Semantic Scholar, and OpenAlex. ORCID auto-update propagates concept-DOIs onto the operator's ORCID record. DataCite citation-graph snapshot (`agents/attribution/datacite_graphql_snapshot.py`) tracks the resulting citation network.
- **No outreach required:** every surface above is either operator-credentialed (one-time bootstrap) or wholly daemon-side after credential bootstrap. No academic endorsers are courted.
- **Refusal-as-data preservation:** the supersession itself is publishable via `zenodo-refusal-deposit` (with refusal-shaped RelatedIdentifier edges per `agents/publication_bus/related_identifier.py`) if the operator wants the supersession itself to be a citable artifact.

## §4 What stays in tree

- `docs/research/2026-04-26-arxiv-velocity-preprint-architecture.md` — kept as historical record of the considered path. Future readers should be directed here via a header note (operator may add post-merge if desired; this PR does not edit the source arch doc, only adds the supersession doc adjacent to it).
- PR #1677's `velocity-findings preprint composer` (`agents/preprint_composer/`) — STAYS. The composer outputs are still useful for `osf-preprint`, `zenodo-doi`, and `philarchive-deposit` surfaces. The composer is **architecture-agnostic** about which deposit surface consumes its output.
- `agents/cold_contact/` — STAYS. The graph-touch policy (citation-graph-only touches, ≤5 candidates/deposit, ≤3/year/candidate) remains the active receive-only path for academic-graph touches without direct outreach.

## §5 What does NOT need to be created

- `agents/arxiv/` (or any other arXiv-specific publisher subclass) — NOT created.
- `endorser_discovery_*.py` / `endorser_request_publisher_*.py` / `courtship_daemon_*.py` — NOT created.
- arXiv-specific `SurfaceSpec` in `surface_registry.py` — NOT added (and intentionally — the existing `arxiv-*` slug-space is reserved for refusal entries).
- `tests/agents/arxiv_*` integration smoke — NOT created.

## §6 Prevent-requeue note

Future cc-tasks framed as "implement arXiv X for the operator" should be **declined or redirected to one of the §3 surfaces**. The 3 incompatibility constraints in §1 are stable architecture; flipping them requires:

- An operator-level inflection reversing `feedback_full_automation_or_no_engagement` (currently active per CLAUDE.md governance)
- Removal of the family-wide refusal documented at `cold_contact/candidate_registry.py:74-76`
- A new Refusal Brief reversal artifact (per the existing `leverage-REFUSED-arxiv-institutional-email-shortcut` precedent)

Until those three reversals happen, **arXiv endorser-courtship is structurally unreachable**. Any future cc-task asking to revisit this path should be checked against this doc first.

## Cross-references

- Source architecture: `docs/research/2026-04-26-arxiv-velocity-preprint-architecture.md` (alpha)
- Refusal precedent: `closed/leverage-REFUSED-arxiv-institutional-email-shortcut.md`
- Refusal brief: `docs/refusal-briefs/leverage-arxiv-institutional-shortcut.md`
- Composer that stays: PR #1677 `feat(publish): velocity-findings preprint composer (WSJF 8.0)`
- Cold-contact no-outreach posture: `agents/cold_contact/candidate_registry.py:74-76`
- Replacement surfaces: `agents/publication_bus/surface_registry.py` (entries enumerated in §3)
- Pattern: `feedback_status_doc_pattern` memory ("defer-with-concrete-blockers governance status docs are a high-leverage autonomous tool")
- Companion reconciles: `docs/governance/alpha-audit-closeout-2026-04-20-reconcile.md` (PR #2260), `docs/governance/r18-qdrant-twin-collapse-2026-04-26-reconcile.md` (PR #2262), `docs/governance/x402-receive-endpoint-implementation` shipped-status update (PR #2263)
