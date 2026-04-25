---
type: research-drop
date: 2026-04-25
title: Cross-Account Promotion Across the Hapax Constellation
agent_id: a8835c247999ae34f
status: shaping-in-progress
---

# Cross-Account Promotion Across the Hapax Constellation

## Verdict

Robust full-automation cross-account promotion is achievable across roughly **70% of the Hapax constellation**; the highest-leverage mechanic is the **DataCite RelatedIdentifier graph anchored on Zenodo DOI mints**, because it federates citations into ORCID, DataCite Commons, and Crossref Event Data without any social-platform spam-detection surface. The music side is the structural bottleneck — Bandcamp has no upload API, RYM has none, and only Internet Archive's S3-style `ias3` API is fully daemon-tractable for automated mirror.

## Surface-pair API matrix (concrete, 2024-2026)

| Source | Target | Protocol | Cadence | Risk |
|---|---|---|---|---|
| GitHub release | Zenodo DOI | Native webhook; `.zenodo.json` + `CITATION.cff`; concept + version DOIs | Per-release ~min | None — institutional |
| Zenodo deposit | ORCID record | Auto-update via DataCite when ORCID iD in metadata; one-time consent | Per first-version DOI mint (versions of same concept-DOI NOT pushed) | None |
| Zenodo deposit | DataCite Commons | Automatic; RelatedIdentifier (`IsCitedBy`/`References`/`IsSupplementTo`/`IsContinuedBy`) federates | Per-mint | None |
| GitHub release | DOI mint via daemon | Zenodo REST API: OAuth `deposit:write`+`deposit:actions` | Anytime; ≤100/day polite | None |
| omg.lol weblog (hapax) | omg.lol weblog (oudepode) | Independent Bearer per account; POST `/address/<addr>/weblog/entry/<id>/`; RSS/Atom/JSON native | Per-post | Low |
| omg.lol weblog | Mastodon (fediverse) | Bridgy Publish via Webmention; or Feed2toot RSS→toot | Bridgy ~30min; Feed2toot per-cron | Medium — mark account as automated in profile |
| omg.lol weblog | Bluesky/ATProto | `@atproto/api` SDK; one client per identity; add `bot` self-label via `app.bsky.labeler.service` | Anytime; ~3000/day practical | Low if `bot` self-label set |
| arXiv preprint | DataCite RelatedIdentifier | arXiv assigns DOIs auto since 2022; metadata pushed to DataCite via SWORD/APP | Per submission | None |
| Zenodo community | curated authors | REST `POST /api/communities/{id}/requests/{rid}/actions/accept`; manual curation default | Per submission | None |
| GitHub topics | schema.org indexability | Topics are HTML metadata only; for indexability emit JSON-LD `SoftwareSourceCode` in repo's GitHub Pages | Per-page | None |
| SoundCloud track | mirror anywhere | SC API: 15K stream-access reqs/24h/client_id; 500MB upload cap; 50 tokens/12h/app | Anytime under cap | Medium — bot-cohort disparity already incurred |
| (none → Bandcamp) | mirror release | **No public upload API**; partnership API only for labels/merch | n/a | High — TOS-adjacent |
| (none → Discogs) | release submission | API v2.0 lacks programmatic release-creation; TOS forbids automated submission | n/a | High — explicit TOS bar |
| (none → RYM) | release submission | API does not exist as of April 2026 — RYMzilla #683 still "Accepted, no ETA" | n/a | n/a |
| Audio file (oudepode SC) | Internet Archive | `ias3` S3-like API; `internetarchive` Python lib; `opensource_audio` collection auto-derives FLAC/MP3/Ogg/spectrogram | Anytime; modest courteous cap | None — institutional |

## Five core daemon-implementable mechanics, ranked by leverage

1. **Zenodo DOI mint as relational hub.** Every artifact (Manifesto, Refusal Brief, Cohort Disparity Disclosure, preregistration, oudepode release notes) becomes a DOI with `RelatedIdentifier` block declaring `IsCitedBy`/`IsSupplementTo`/`IsPartOf` against prior artifacts. Cadence: per artifact, <5min via developers.zenodo.org REST. Case study: rOpenSci's full automation chain `cffr → CITATION.cff → .zenodo.json → DOI`.
2. **GitHub release → Zenodo concept-DOI.** Single one-time toggle per repo; subsequent releases mint version DOIs with concept-DOI as `IsVersionOf`. Cadence: per `gh release create`. Implementation: tiny daemon that computes `RelatedIdentifier` set from repo's bibliography YAML and writes to `.zenodo.json` before tagging.
3. **omg.lol cross-weblog RSS+Bearer fanout.** `hapax.weblog.lol` exposes `{rss-url}`; the publish-orchestrator daemon holds two Bearer tokens (one per address) and POSTs to both `weblog/entry/` endpoints with topic-routed templates. Cadence: per artifact. Spam risk zero because both accounts operator-held.
4. **Bridgy Publish via webmention.** Hapax's static site emits `<a class="u-syndication">` markers; webmention to brid.gy publishes to Mastodon, Bluesky, GitHub. ~30min poll cadence. Bridgy IS the daemon; nothing custom needed.
5. **DataCite Commons + GraphQL self-citation graph.** Once `RelatedIdentifier` is populated, `POST https://api.datacite.org/graphql` retrieves the full citation tree as a queryable graph, and **the graph itself becomes a publishable artifact**.

## Music-side specific path

**Internet Archive's `opensource_audio` collection via `ias3`** is the most academic-credible auto-syndication target for the oudepode SC tracks — `internetarchive` Python lib, S3 keys at archive.org/account/s3.php, automatic FLAC/MP3/Ogg/spectrogram derivation, full citability via direct URLs.

Bandcamp/Discogs/RYM are out (no upload API or TOS-prohibited).

Secondary: minted Zenodo DOI per track in an `oudepode-music` community with `physicalObject`/`audio` resourceType — gives every track a citable identifier that ORCID auto-update will surface on the operator profile alongside research artifacts.

## Self-citation-graph implementation sketch

`.zenodo.json` (per-artifact, root of repo):
```json
{
  "title": "Cohort Disparity Disclosure",
  "creators": [{"name": "Hapax", "orcid": "0000-..."},
                {"name": "Claude Code", "affiliation": "Anthropic"}],
  "related_identifiers": [
    {"identifier": "10.5281/zenodo.<MANIFESTO_DOI>", "relation": "isSupplementTo", "scheme": "doi"},
    {"identifier": "10.5281/zenodo.<REFUSAL_BRIEF_DOI>", "relation": "isContinuedBy", "scheme": "doi"},
    {"identifier": "https://hapax.weblog.lol/cohort-disparity", "relation": "isIdenticalTo", "scheme": "url"}
  ],
  "communities": [{"identifier": "hapax-publications"}]
}
```

`CITATION.cff` declares the human-readable Zenodo concept-DOI; `cffr` converts to BibTeX/RIS/CodeMeta/JSON-LD. `codemeta.json` v4 is the forward-direction schema.org alignment (researchsoft.org 2026 announcement). JSON-LD `Article` in the omg.lol weblog template uses `citation` and `isBasedOn` cross-pointing to sibling DOIs.

## Three "fresh" academic-spectacle patterns

1. **Citation-graph-as-primary-publication.** Mint a Zenodo DOI for the *DataCite GraphQL query* that resolves to the constellation graph; the artifact's `description` is the query, the artifact's `RelatedIdentifier` block is the result set. Reproduces the Tega Brain / Sam Lavigne "infrastructure-as-argument" gesture.

2. **Refusal-as-related-identifier.** Use the underused `IsObsoletedBy` and `IsRequiredBy` relation types to record refusals. A Refusal Brief that says "this institutional surface is corrupted" can be wired as `IsObsoletedBy` against an institutional DOI it rejects. The DataCite event log captures the refusal in the public PID graph — refusal becomes citable infrastructure, not a one-off post.

3. **XXIIVV-style hand-crafted webring with ORCID iD as identity beacon.** Replace social-graph follow with a static webring across hapax.weblog.lol ↔ oudepode.weblog.lol ↔ each repo's README → ORCID profile, where the ORCID iD is the deduplicating anchor. Mirror of Hundred Rabbits / Merveilles webring without becoming a member of any external one (consistent with refusal stance).

## Anti-pattern list

- **Bandcamp upload** — no public API; only TOS-adjacent browser-scraper exists.
- **Discogs release submission** — API for marketplace and personal collection only; release-database submission forbidden under TOS.
- **RateYourMusic submission** — no API at all (April 2026); manual web submission required.
- **Mastodon cross-instance bots** — federation propagation unreliable; instance admins de facto require manual approval. Bridgy is the only tractable path, with bot self-label.
- **Bluesky multi-account "one click" cross-post** — protocol supports unlimited accounts but does NOT support cross-post-with-one-click; each PDS session independent. Daemon can do it, but presentation as "one identity" is false.
- **Crossref Event Data for self-citation discovery** — Crossref announced sunset of Event Data; replaced by narrower data-citation endpoint. Don't build new infra on Event Data.
- **ORCID auto-update for Zenodo versions** — DataCite only pushes the *original* concept-DOI to ORCID, not subsequent versions. Multi-version artifacts must be flattened or each treated as standalone.
- **omg.lol → ActivityPub native** — weblog.lol exposes RSS/Atom/JSON but is **not natively an ActivityPub actor**. Cross-publishing requires Bridgy or Feed2toot.
- **Zenodo community auto-accept** — requires explicit policy setting; default is manual curator review.

## Ready-to-wire SURFACE_REGISTRY entries

`zenodo-deposit`, `zenodo-related-identifier-graph`, `datacite-graphql-mirror`, `orcid-auto-update`, `internet-archive-ias3` (music-side), `omg-lol-weblog-bearer-fanout` (already partially scaffolded), `bridgy-webmention-publish`, `bluesky-atproto-multi-identity`. Bandcamp/Discogs/RYM marked `automation_status: REFUSED` with refusal text linking back to the Refusal Brief — turning the absence into a registered-and-cited stance, consistent with `full-automation-or-no-engagement` constitutional directive.

## Sources

- Zenodo GitHub integration; Zenodo Developers REST API; Zenodo Communities curation
- DataCite RelatedIdentifier Schema 4.6; DataCite Connecting Versions; DataCite GraphQL API Guide
- DataCite/ORCID auto-update explanation
- Crossref ORCID auto-update; Crossref sunset of Event Data
- arXiv API help; arXiv DOI auto-assignment
- Bandcamp developer page + Bandcamp API help (no upload API)
- Discogs API documentation + ToU
- RateYourMusic development page (no API)
- Internet Archive ias3 API + internetarchive Python library
- omg.lol API reference
- Bridgy + IndieWeb POSSE + Webmention
- Bluesky bots & self-labels + moderation/labelers
- SoundCloud rate limits
- OSF API developer portal
- ROR API basics
- Citation File Format
- Researchsoft 2026 software-citation roadmap
- XXIIVV webring + Hundred Rabbits
- Pluralistic POSSE pattern + Doctorow Memex reflection
- Tega Brain & Sam Lavigne — How to Get to Zero
