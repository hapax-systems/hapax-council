# Content Format Source Pool Rights Ledger - Design Spec

**Status:** schema/config seed for `content-format-source-pool-rights-ledger`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/content-format-source-pool-rights-ledger.md`
**Date:** 2026-04-29
**Depends on:** `content-opportunity-input-source-registry`, `research-corpus-anonymization-rights-ledger`, `livestream-substrate-registry`
**Scope:** rights classes, source-pool records, public/private eligibility, third-party AV fail-closed defaults, Bayesian source and rights-pass priors, WCS substrate refs, evidence refs, and per-format source postures.
**Non-scope:** crawler implementation, media acquisition, license negotiation, fair-use legal judgment, scheduler implementation, public-event adapter writes, or monetization readiness decisions.

## Purpose

The source-pool rights ledger is the handoff between content opportunity
discovery and content programme execution. It answers one question before any
runner, scheduler, public adapter, conversion broker, or monetization ledger can
use a source:

What may this source do, with which evidence, under which public/private mode,
and with what Bayesian prior for rights pass/fail?

Discovery is not permission. A candidate can be interesting, timely, and
grounding-rich while still blocked from autonomous public use because the media
rights, provenance, WCS witness, privacy state, or platform scope is not clear.

## Machine-Readable Ledger

The schema and seeded ledger live at:

- `schemas/content-format-source-pool-rights-ledger.schema.json`
- `config/content-format-source-pool-rights-ledger.json`

Required top-level fields:

| Field | Meaning |
|---|---|
| `schema_version` | Ledger schema version. Initial value is `1`. |
| `ledger_id` | Stable ledger id for downstream refs. |
| `declared_at` | UTC timestamp for this declaration. |
| `producer` | Session or component that produced the ledger. |
| `global_policy` | Cross-source fail-closed rules. |
| `rights_class_definitions` | Canonical rights classes and required evidence. |
| `source_posture_definitions` | Machine-readable source-use postures. |
| `source_pool` | Concrete source-pool rows with provenance, rights, WCS, eligibility, and priors. |
| `format_policies` | Per-format source posture and third-party AV policy. |
| `downstream_contract` | Fields that consumers must preserve without re-inferring rights. |

The ledger is config rather than prose so later code can reject a candidate
without scraping a spec paragraph.

## Rights Classes

The ledger defines exactly these source rights classes:

- `owned`
- `public_domain`
- `cc_compatible`
- `licensed`
- `platform_embed_only`
- `fair_use_candidate`
- `forbidden`
- `unknown`

`unknown` means unavailable for public or monetized use. `fair_use_candidate`
means legal analysis may be possible later; it is not an autonomous publication
grant. `platform_embed_only` permits metadata, link-along, or embed posture
only; it does not permit Hapax to rebroadcast, cache, remix, or publish the
third-party media.

Every rights class declares:

- default public/private mode,
- whether autonomous public use is allowed by default,
- whether monetization is allowed by default,
- required evidence before a source row may claim that class.

## Source Pool Records

Every source row records:

- `source_url`
- `title`
- `creator`
- `rightsholder`
- `platform`
- `license`
- `permission`
- `acquisition_method`
- `capture_method`
- `date_checked`

Rows also carry `rights_class`, `media_profile`, `eligibility`, `postures`,
`wcs_substrate_refs`, `evidence_refs`, `provenance_requirements`,
`bayesian_priors`, and `downstream_consumers`.

The initial seeded source pool covers:

| Source id | Rights class | Default posture | Public posture |
|---|---|---|---|
| `operator_owned_archive_segments` | `owned` | owned/cleared + archive | Public/archive/monetizable after egress, privacy, and monetization gates. |
| `aesthetic_library_cleared_assets` | `cc_compatible` | owned/cleared + metadata | Public live/archive with attribution; monetization blocked by license constraints. |
| `research_corpus_export_rows` | `owned` | metadata/archive | Public archive only through export ledger gates. |
| `youtube_platform_metadata` | `platform_embed_only` | metadata/link-along | Metadata/archive claims only; no rebroadcast. |
| `third_party_av_link_along_pool` | `platform_embed_only` | link-along/metadata/refusal | Private/dry-run only for media; public output may cite/link without carrying AV. |
| `public_domain_reference_assets` | `public_domain` | owned/cleared + metadata | Public after source-specific public-domain evidence. |
| `licensed_review_copy_or_partner_asset` | `licensed` | metadata/link-along/refusal | Held private/dry-run until license scope and legal attestation exist. |
| `fair_use_candidate_commentary_refs` | `fair_use_candidate` | link-along/metadata/refusal | Private/dry-run only; legal attestation required for any later public use. |
| `forbidden_uncleared_media_cache` | `forbidden` | refusal artifact | No acquisition or capture; refusal artifact only. |
| `unknown_source_intake_hold` | `unknown` | metadata/refusal | Private/dry-run hold until rights research exists. |

## Public Private Eligibility

Each source carries machine-readable booleans for:

- `private_allowed`
- `dry_run_allowed`
- `public_live_allowed`
- `public_archive_allowed`
- `public_monetizable_allowed`
- `autonomous_public_allowed`
- `link_along_allowed`
- `metadata_first_allowed`
- `archive_only_allowed`
- `refusal_artifact_allowed`

It also carries `allowed_public_modes` and `block_reasons`.

Downstream code must use the source row's eligibility ceiling. It may add a
stricter gate result, but it may not upgrade a source by inferring new rights.

## Third Party AV Default

Third-party AV is non-autonomous-public by default.

That rule applies to react/commentary, watch-along, reviews, what-is-this,
rundowns, and every other content format. The format may be public, but the
third-party media itself may not be autonomously carried, rebroadcast, cached,
uploaded, clipped, or converted into Shorts unless the source row has explicit
clearance evidence for the exact public surface.

Default safe conversions are:

- `link_along`,
- `metadata_first`,
- `owned_cleared` replacement media,
- `archive_only` evidence when the source itself is safe,
- `refusal_artifact` when the desired public shape is blocked.

Uncleared third-party AV rows must set:

- `media_profile.third_party_av = true`,
- `media_profile.explicitly_cleared_for_autonomous_public = false`,
- `eligibility.autonomous_public_allowed = false`,
- no public-live, public-archive, or public-monetizable media mode,
- a `third_party_av_uncleared` or stricter block reason.

## Bayesian Rights Priors

The ledger feeds source priors and rights-pass priors into the Bayesian
opportunity model. Every source row has:

- `bayesian_priors.source_prior`
- `bayesian_priors.rights_pass_prior`
- `bayesian_priors.provenance_strength_prior`
- `bayesian_priors.risk_prior`
- `bayesian_priors.posterior_refs`

Each prior is a Beta-style record with `alpha`, `beta`, `mean`, and
`evidence_refs`. The priors attach to the existing model posterior families:

- `content-opportunity-model.posterior_state.source_prior`
- `content-opportunity-model.posterior_state.rights_pass_probability`

These priors are not gates. They help rank and route opportunities after hard
eligibility has already failed closed or passed.

## WCS Evidence And Downstream Consumers

Every source row preserves WCS substrate refs and evidence refs. Required
consumer set:

- `scheduler`
- `run_store`
- `public_adapter`
- `conversion_broker`
- `monetization_ledger`

Consumers must preserve these fields:

- source identity and URL,
- creator and rightsholder,
- rights class, license, and permission,
- acquisition and capture method,
- date checked,
- media profile,
- eligibility,
- postures,
- WCS substrate refs,
- evidence refs,
- Bayesian priors.

This prevents the scheduler, run store, public adapter, conversion broker, and
monetization ledger from re-inferring rights from topic names or source URLs.

WCS refs connect each source to concrete substrate rows such as
`archive.vod_sidecar`, `public.youtube_metadata`, `asset.provenance_manifest`,
`tool.web_search_openai`, `browser_surface`, and `archive.refusal_artifact`.

## Format Posture Matrix

Each format row declares:

- allowed source postures,
- public mode ceiling,
- third-party AV default,
- required rights classes for public modes,
- blocked rights classes,
- Bayesian source/right/risk prior refs,
- downstream fields that must survive into the run store.

All seeded `ContentProgrammeFormat` ids are represented:

- `tier_list`
- `react_commentary`
- `ranking`
- `comparison`
- `review`
- `watch_along`
- `explainer`
- `rundown`
- `debate`
- `bracket`
- `what_is_this`
- `refusal_breakdown`
- `evidence_audit`

Every format sets `third_party_av_default` to `non_autonomous_public`,
`autonomous_public_third_party_av_allowed` to false, and
`clearance_required_for_third_party_av_public` to true.

## Acceptance Pin

This packet is complete only if:

- rights classes are exactly `owned`, `public_domain`, `cc_compatible`,
  `licensed`, `platform_embed_only`, `fair_use_candidate`, `forbidden`, and
  `unknown`,
- every source records source URL, title, creator, rightsholder, platform,
  license, permission, acquisition method, capture method, and date checked,
- public/private eligibility is machine-readable per source,
- third-party AV remains non-autonomous-public unless explicitly cleared,
- Bayesian source and rights-pass priors are present for every source,
- WCS substrate refs and evidence refs are present for every source,
- scheduler, run store, public adapter, conversion broker, and monetization
  ledger consume preserved fields instead of re-inferring rights,
- link-along, metadata-first, owned/cleared, archive-only, and
  refusal-artifact postures are machine-readable per source and per format,
- config uses repo/local logical refs rather than absolute workstation paths.
