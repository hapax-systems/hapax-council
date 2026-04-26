# Refusal Brief: Journal/Conf Methodology Paper Track

**Slug:** `leverage-workflow-methodology-paper-CONDITIONAL`
**Axiom tag:** `single_user` + `executive_function` + `interpersonal_transparency`
**Refusal classification:** CONDITIONAL_ENGAGE → REFUSED (failed full-automation gate)
**Status:** REFUSED — peer-review track is not fully daemon-tractable.
**Date:** 2026-04-26
**Source research:** `docs/research/2026-04-25-leverage-strategy.md` §workflow-methodology

## What is refused

Submitting the velocity-meter methodology paper to a peer-reviewed journal or conference (ICSE, FSE, MSR, or similar). The arXiv preprint already in `closed/` (`leverage-attrib-arxiv-velocity-preprint`) and the Zenodo concept-DOI deposit (V5 publication-bus) cover the auto-tractable surface. The journal-track adds peer-review cycle handling, page-fee filing, camera-ready signoff, and editorial conferences — the load-bearing question is whether all of these can run daemon-side without operator hand-off.

## Why this is refused

### Per the original task's verification protocol

The cc-task itself encodes the gate (verbatim from `verification_required`):

> Demonstrable full-daemon peer-review cycle handler — including rebuttal letter drafting + page-fee filing — without operator hand-off. If not demonstrable, demote to REFUSED.

The verification protocol enumerated six steps (submission, reviewer feedback, rebuttal drafting, rebuttal submission, page-fee handling, camera-ready signoff). Of those:

| Step | Daemon-tractable? | Notes |
|---|---|---|
| Submit paper to EasyChair / OpenReview | **No** | Operator-physical KYC at first registration; many venues require ORCID + institutional affiliation |
| Receive reviewer feedback | **Yes** | mail-monitor handles inbox |
| Draft rebuttal | **Partial** | `agents/composer/` can draft, but rebuttal style varies per reviewer + camera-ready demands operator-physical signoff per author-list-integrity norms |
| Submit rebuttal | **Yes** | mail-monitor reply path |
| Handle page-fee | **No** | Most venues use Stripe / institutional credit / wire transfer with operator-physical KYC at the publisher; Lightning is rejected by ACM/IEEE/USENIX |
| Sign camera-ready | **No** | Author-list integrity requires operator-physical cryptographic signature |

Three of six steps fail the daemon-tractable gate. The constitutional posture per `feedback_full_automation_or_no_engagement` (2026-04-25T16:55Z) is REFUSE.

### Per `single_user` (weight 100)

Author-list integrity in peer review is a multi-party shape: the operator is one author, a reviewer is another, a program chair is a third, a publisher is a fourth. The single-operator axiom does not absolutely prohibit multi-party correspondence (mail-monitor handles incoming reviews), but it does prohibit *binding signatures on behalf of* multi-party agreements (camera-ready copyright transfer, ACM Digital Library license).

### Per `executive_function` (weight 95)

The cc-task's effort estimate did not capture the recurring-attention cost of peer-review cycles: reviewer feedback may arrive 6-9 months after submission, page-fee invoices may arrive 12-15 months later, and camera-ready deadlines are typically 2-week windows. Each is a unit of operator attention that the daemon cannot defer or batch. Promoting to FULL_AUTO would demand a 12+ month infrastructure investment for one paper's worth of citations.

### Per `interpersonal_transparency` (weight 88)

Reviewer-anonymity contracts are a property of the venue, not the author. Many venues bind submitting authors to NOT disclose under-review status. Daemon-side Bridgy POSSE of submission-status would violate that contract. Full-automation thus requires either daemon-aware bypass of POSSE or operator-physical decision-making about which surfaces to publish — both of which break the FULL_AUTO contract.

## What remains engaged

- arXiv preprint (deposited via `leverage-attrib-arxiv-velocity-preprint`, CLOSED)
- Zenodo concept-DOI deposit (V5 publication-bus)
- Self-citation graph DOI minting (per `pub-bus-datacite-graphql-mirror` Phase 3)
- Internet Archive S3 deposit (per `pub-bus-internet-archive-ias3`)
- omg.lol weblog publication
- Software Heritage register (per `swh_register`)

The arXiv-then-Zenodo path covers academic citation discoverability without invoking the peer-review infrastructure tax. The methodology paper IS published — just not via journal/conf track.

## Constitutional alternative

If a venue exists that genuinely supports daemon-only peer review (open peer review, public review threads, no page fees, daemon-cryptographic-signature accepted as author signature), it can be re-evaluated under the same gate. The current conference list does NOT contain any such venue per drop-leverage §workflow-methodology.

The operator can override this REFUSE at any time by re-classifying the cc-task `automation_status: FULL_AUTO` with the venue specified — the refusal is not permanent.

## Refusal-as-data

This brief lands in `~/hapax-state/publications/refusal-annex-leverage-workflow-methodology-paper-CONDITIONAL.md` via `RefusalAnnexPublisher` Phase 1 + the Phase 2 cross-linker. The Zenodo refusal-deposit (per `pub-bus-internet-archive-ias3` sibling refusal-DOI minting) carries a `RelatedIdentifier` of relation `IsRequiredBy` pointing at the velocity-meter arXiv preprint DOI — making this REFUSE participate in the citation graph as a structured node.

The refusal narrative — "academic publishing's peer-review cycle is not daemon-tractable" — is itself a research artefact, surfaced via Hapax authorship rather than concealed.
