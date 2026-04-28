# Refusal Brief: Crossref Event Data

**Slug:** `crossref-event-data-sunset`
**Axiom tag:** `feedback_full_automation_or_no_engagement`
**Refusal classification:** upstream service sunset / superseded surface
**Status:** REFUSED - no Crossref Event Data ingestion or publisher is to be built.
**Date:** 2026-04-27
**Related cc-task:** `crossref-event-data`
**Surface registry entry:** `crossref-event-data` (REFUSED)

## What was refused

Building or maintaining Crossref Event Data as a publication-bus event stream,
citation graph source, or public-surface engagement target.

## Why this is refused

Crossref Event Data has been sunset and is not a stable daemon surface. The
role originally imagined for it is now covered by DataCite Commons GraphQL and
the Zenodo/DataCite related-identifier graph. Keeping Crossref Event Data in
the implementation path would create a dead integration and false operational
confidence.

## Daemon-tractable boundary

DataCite Commons GraphQL remains the supported citation graph mirror. Crossref
deposit work is tracked separately from the refused Event Data surface and must
not be conflated with this refusal.

## Lift conditions

The refusal can be reconsidered only if Crossref restores a supported event
data product with a stable API and a role not already covered by DataCite.

## Cross-references

- Surface registry: `agents/publication_bus/surface_registry.py` (`crossref-event-data`)
- RefusedPublisher subclass: `agents/publication_bus/publisher_kit/refused.py` (`CrossrefEventDataRefusedPublisher`)
- Replacement surface: `datacite-graphql-mirror`
