# Refusal Brief: Discogs Submission

**Slug:** `discogs-tos-forbids`
**Axiom tag:** `feedback_full_automation_or_no_engagement`
**Refusal classification:** Terms-of-Service automation barrier
**Status:** REFUSED - no Discogs release-submission daemon is to be built.
**Date:** 2026-04-27
**Related cc-task:** `discogs-submission`
**Surface registry entry:** `discogs-submission` (REFUSED)

## What was refused

Automated submission of Hapax releases to Discogs, including any scraper,
browser bot, or API-backed release-submission client.

## Why this is refused

Discogs release submission is a community-curated workflow and the project
policy in the publication bus treats automated submission as forbidden by the
surface's rules. A daemon that submits releases would shift a human-mediated
cataloging process into an automated marketing/distribution workflow.

Per `feedback_full_automation_or_no_engagement`, the correct posture is no
engagement rather than a partial operator-review workflow.

## Daemon-tractable boundary

Hapax may maintain local release metadata and publish to API-backed surfaces.
It does not submit releases to Discogs or build infrastructure that would make
that submission path easy to activate later.

## Lift conditions

The refusal can be reconsidered only if Discogs publishes an automation-safe
release-submission API and terms that explicitly permit daemon-side release
submission for the operator's own catalog.

## Cross-references

- Surface registry: `agents/publication_bus/surface_registry.py` (`discogs-submission`)
- RefusedPublisher subclass: `agents/publication_bus/publisher_kit/refused.py` (`DiscogsRefusedPublisher`)
