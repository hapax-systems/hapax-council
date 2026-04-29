# Autonomous Grounding Value Stream Registry - Design Spec

**Status:** schema seed for `autonomous-grounding-value-stream-registry`
**Task:** `active/autonomous-grounding-value-stream-registry.md`
**Date:** 2026-04-29
**Depends on:** `autonomous-grounding-value-stream-research`
**Scope:** canonical value stream schema, seeded registry rows, automation class,
operator boundary, public claim policy, privacy/rights posture, train position,
and downstream packet mapping.
**Non-scope:** payment processing, platform API writes, grant submission,
artifact packaging, public fanout execution, or monetization readiness
implementation.

## Purpose

Hapax value work should not scatter into normal creator-business features.
The monetizable object is the single-operator autonomous grounding lab: one
operator, one studio, one vault, one governance system, one archive, and one
public surface attempting to expose what it knows and what it may claim.

The registry makes that object operational. Each row says what value stream is
being built, why it has n=1 value, who owns the evidence, how money could flow,
which prerequisites gate it, what it may claim publicly, how privacy/rights fail
closed, and which downstream packet should move next.

## Machine-Readable Registry

The canonical files are:

- `schemas/autonomous-grounding-value-stream.schema.json`
- `config/autonomous-grounding-value-streams.json`

The schema requires every stream row to include:

- `stream_id`
- `category`
- `automation_class`
- `n1_value_claim`
- `evidence_owner`
- `revenue_path`
- `prerequisites`
- `public_claim_policy`
- `privacy_rights_posture`
- `operator_boundary`
- `status`
- `next_packet`

Rows also carry `guardrails`, `train_position`, and `refusal_conversions` so the
registry can be used directly by train packetization and refusal publishing.

## Automation Doctrine

The global policy is strict:

- single operator only;
- no recurring operator labor;
- no supporter perks;
- no supporter identity persistence;
- public claims require an evidence owner;
- unknown rights block public claims;
- only `bootstrap` and `legal_attestation` may remain as operator actions.

Automation classes:

| Class | Meaning |
|---|---|
| `AUTO` | Hapax can run it after setup without recurring operator work. |
| `BOOTSTRAP` | One-time account, credential, hardware, or source setup remains. |
| `LEGAL_ATTEST` | Law or platform policy requires explicit operator attestation. |
| `GUARDED` | Build only behind readiness, privacy, consent, rights, and policy gates. |
| `REFUSAL_ARTIFACT` | The generic revenue shape is refused and converted into an artifact. |

Statuses are intentionally train-facing: `offered`, `blocked`, `guarded`, and
`refusal_artifact`.

## Seeded Streams

The seeded registry covers the streams from the 2026-04-29 synthesis:

| Stream id | Category | Automation | Status | Next packet |
|---|---|---|---|---|
| `livestream_public_aperture` | live aperture | `GUARDED` | guarded | `youtube-captions-cuepoints-sections-shorts-reconcile` closed evidence |
| `vod_archive_replay_shorts_chapters` | archive replay | `AUTO` | blocked | `archive-replay-public-event-link-adapter` |
| `cross_surface_publication_bus` | publication bus | `AUTO` | offered | `cross-surface-event-contract` closed evidence |
| `direct_no_perk_support_rails` | support rail | `AUTO` | offered | `support-surface-registry` |
| `commercial_license_agent_payment_rail` | commercial license | `GUARDED` | guarded | `license-request-price-class-router` |
| `product_tool_ip_artifact_packs` | artifact product | `AUTO` | blocked | `artifact-catalog-release-workflow` |
| `research_artifacts_datasets_papers_identifiers` | research artifact | `GUARDED` | guarded | `research-corpus-anonymization-rights-ledger` |
| `grants_fellowships_credits_institutional_patronage` | institutional grant | `LEGAL_ATTEST` | offered | `grant-opportunity-scout-attestation-queue` |
| `aesthetic_media_condition_editions` | aesthetic edition | `GUARDED` | blocked | `aesthetic-condition-editions-ledger` |
| `studio_operator_adjacent_value` | studio adjacent | `BOOTSTRAP` | guarded | `strategic-artifact-lane-reconfirm-and-split` |
| `consulting_by_artifact` | artifact product | `AUTO` | offered | `conversion-broker` |
| `refusal_conversions` | refusal conversion | `REFUSAL_ARTIFACT` | refusal artifact | `refusal-annex-publish-fanout-closeout` |

The rows preserve the synthesis categories: livestream, VOD/archive,
cross-surface, support rails, commercial license, products/templates, research
artifacts, grants, aesthetic editions, studio-adjacent value,
consulting-by-artifact, and refusal conversions.

## Evidence Ownership

`evidence_owner` is not a person assignment. It names the system object that
proves the stream can claim value. Examples:

- `ResearchVehiclePublicEvent and MonetizationReadiness` for the live aperture;
- `ArchiveReplayRef` for VOD/archive products;
- `SurfacePolicy` for cross-surface fanout;
- `support-surface-registry` for no-perk support rails;
- `research-corpus-anonymization-rights-ledger` for datasets and papers.

Public language may not claim a stream is live, safe, monetizable, replayable,
or sellable unless the named evidence owner has current proof.

## Public Claim Policy

Every stream row declares:

- allowed claims;
- forbidden claims;
- gate refs that must be true before public output;
- missing-evidence behavior.

Missing evidence never means "probably okay." It blocks public claims,
downgrades to dry-run/private, or emits a refusal artifact.

## Privacy Rights And Operator Boundary

Every stream declares a `privacy_rights_posture` with privacy floor, rights
floor, consent posture, and fail-closed reasons.

Every stream declares an `operator_boundary` with
`recurring_operator_labor_allowed: false`. Any row that needs hidden repeated
manual work is invalid. The only allowed operator actions are:

- one-time bootstrap;
- explicit legal attestation.

This keeps revenue work inside the constitutional single-operator system
instead of creating client, community, supporter, or creator-service obligations.

## Downstream Packet Mapping

Each row points at an exact task note in
`~/Documents/Personal/20-projects/hapax-cc-tasks/`. The current high-WSJF
streams already have downstream packets, so this task does not create new task
notes.

Exact next packet notes:

- `closed/youtube-captions-cuepoints-sections-shorts-reconcile.md`
- `active/archive-replay-public-event-link-adapter.md`
- `closed/cross-surface-event-contract.md`
- `active/support-surface-registry.md`
- `active/license-request-price-class-router.md`
- `active/artifact-catalog-release-workflow.md`
- `closed/research-corpus-anonymization-rights-ledger.md`
- `active/grant-opportunity-scout-attestation-queue.md`
- `active/aesthetic-condition-editions-ledger.md`
- `active/strategic-artifact-lane-reconfirm-and-split.md`
- `active/conversion-broker.md`
- `active/refusal-annex-publish-fanout-closeout.md`

## Refusal Conversions

The registry refuses generic business forms that would create recurring labor,
supporter identity, community management, or multi-user product pressure.

Canonical conversions:

- Patreon -> no-perk public support page with Liberapay/Lightning.
- GitHub Sponsors funding file -> support rails and license-request routing.
- Stripe Payment Links -> Lightning, Liberapay, or x402 receive-only routes.
- Discord community subscriptions -> one-way publication webhook.
- Paid subscriber access -> public newsletter/RSS only when automated.
- Sponsor ad reads -> non-deliverable research-instrument support copy.
- Consulting service -> self-serve artifact packs, reports, rubrics, or checklists.

The refusal is not a pause awaiting manual operator work. It is the product
boundary.

## Downstream Consumers

Expected consumers:

- `support-surface-registry` uses support stream and refusal conversion rows;
- `payment-aggregator-v2-support-normalizer` consumes aggregate-only support
  policy;
- `replay-demo-residency-kit` consumes archive/replay and grant/demo posture;
- `artifact-catalog-release-workflow` consumes artifact product and
  consulting-by-artifact rows;
- `grant-opportunity-scout-attestation-queue` consumes legal attestation
  boundaries;
- future revenue dashboards consume `train_position`, `status`, and
  `evidence_owner`.

No downstream consumer may treat this registry as permission to publish or
monetize. It is a value map and gate vocabulary; evidence owners still decide
whether a live action is allowed.
