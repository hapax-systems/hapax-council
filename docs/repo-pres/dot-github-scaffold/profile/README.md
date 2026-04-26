# The Operator — Hapax

Single-operator infrastructure for externalised executive function. Grounded LLM tier, refusal-as-data substrate, full-automation-or-no-engagement.

## Stance

This account ships infrastructure that argues against itself. Three constitutional commitments shape what is published and what is refused:

- **Single-operator.** No auth, no roles, no multi-user code. The operator is the only formal-action actor.
- **Full automation or no engagement.** Surfaces that cannot be daemon-tractable end-to-end are refused entirely, and the refusal is published as data via the [Refusal Briefs](#refusal-briefs).
- **Interpersonal transparency.** No persistent state about non-operator persons without an active consent contract. Non-formal contexts use one of four sanctioned referents only — _The Operator_, _Oudepode_, _Oudepode The Operator_, _OTO_.

Governance specification: [`hapax-constitution`](https://github.com/ryanklee/hapax-constitution).

## Repos

| Repo | Role |
|---|---|
| [`hapax-constitution`](https://github.com/ryanklee/hapax-constitution) | Governance spec — axioms, implications, canons. Publishes the `hapax-sdlc` package. |
| [`hapax-council`](https://github.com/ryanklee/hapax-council) | Personal operating environment — 200+ agents, voice daemon, studio compositor, reactive engine. |
| [`hapax-officium`](https://github.com/ryanklee/hapax-officium) | Management decision support — filesystem-as-bus data model. |
| [`hapax-watch`](https://github.com/ryanklee/hapax-watch) | Wear OS biometric companion (heart rate, HRV, skin temperature, sleep). |
| [`hapax-phone`](https://github.com/ryanklee/hapax-phone) | Android health-summary + phone-context companion. |
| [`hapax-mcp`](https://github.com/ryanklee/hapax-mcp) | MCP server bridging logos APIs to Claude Code. |
| [`hapax-assets`](https://github.com/ryanklee/hapax-assets) | SHA-pinned aesthetic library CDN (BitchX, Px437 IBM VGA). |

## Refusal Briefs

A growing catalogue of surfaces, mechanisms, and practices the operator has refused — with the reason recorded as data. Refusals are first-class citizens of the publication graph, deposited as Zenodo records with `IsRequiredBy` / `IsObsoletedBy` `RelatedIdentifier` edges (see [V5 publication bus](https://github.com/ryanklee/hapax-council/tree/main/agents/publication_bus)).

Recent examples:
- arXiv institutional-email shortcut (closed by upstream Jan 2026 — documentary refusal)
- Bandcamp / Discogs / RYM / Crossref Event Data — direct outreach is REFUSED per family-wide stance; refusal subclasses auto-record via `__init_subclass__`
- omg.lol mailhook — vapor (announced ~2021, never publicly shipped)

The full refusal corpus lives in `hapax-council/docs/refusal-briefs/` and is mirrored to Zenodo under the [Hapax Refusal Briefs](https://zenodo.org) concept-DOI.

## Identifiers

- ORCID: configured via `HAPAX_OPERATOR_ORCID`
- Hapax Citation Graph concept-DOI: minted via `agents/publication_bus/datacite_mirror.py`
- Software Heritage: SWHID per repo via `agents/attribution/swh_register.py`

## Contact

Direct contact channels are intentionally absent from this surface. The operator participates in the citation graph via DOI cross-references; cold-contact outreach is structurally refused (see `agents/cold_contact/candidate_registry.py` — no email/telephone fields by design). Engagement happens through the work itself.
