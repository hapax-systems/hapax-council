# Refusal Brief: Rate Your Music Submission

**Slug:** `rym-no-api`
**Axiom tag:** `feedback_full_automation_or_no_engagement`
**Refusal classification:** no public API / human-mediated submission surface
**Status:** REFUSED - no Rate Your Music submission daemon is to be built.
**Date:** 2026-04-27
**Related cc-task:** `rym-submission`
**Surface registry entry:** `rym-submission` (REFUSED)

## What was refused

Automated Rate Your Music submission for Hapax releases, including browser
automation against the human submission flow.

## Why this is refused

Rate Your Music does not expose a public submission API suitable for a
publication-bus publisher. A browser-driven workflow would require session
state, site-specific form behavior, and ongoing human-style moderation
semantics. That is not a robust daemon surface.

The system refuses the surface rather than building a brittle automation shim
that depends on manual triage.

## Daemon-tractable boundary

Release metadata can remain in Hapax-controlled files and can flow to
API-backed publication surfaces. It does not flow to Rate Your Music.

## Lift conditions

The refusal can be reconsidered only if Rate Your Music exposes a stable,
documented submission API and explicitly permits automation for the
operator's own releases.

## Cross-references

- Surface registry: `agents/publication_bus/surface_registry.py` (`rym-submission`)
- RefusedPublisher subclass: `agents/publication_bus/publisher_kit/refused.py` (`RymRefusedPublisher`)
