# Refusal Brief: Bandcamp Upload

**Slug:** `bandcamp-no-upload-api`
**Axiom tag:** `feedback_full_automation_or_no_engagement`
**Refusal classification:** no public daemon-tractable upload API
**Status:** REFUSED - no Bandcamp upload daemon or browser upload bot is to be built.
**Date:** 2026-04-27
**Related cc-task:** `bandcamp-upload`
**Surface registry entry:** `bandcamp-upload` (REFUSED)

## What was refused

Daemon-side publication of Hapax music releases to Bandcamp through either a
direct API client or automated browser upload workflow.

## Why this is refused

Bandcamp does not expose a documented public upload API suitable for a
fully automated publication-bus surface. The available path is an
authenticated, multi-step browser workflow around release metadata, audio
assets, artwork, pricing, and account state. That creates an operator-session
and approval dependency instead of a repeatable daemon contract.

Per `feedback_full_automation_or_no_engagement`, surfaces that cannot run
end-to-end without per-release operator handling are refused rather than
queued behind manual review.

## Daemon-tractable boundary

Music release state may still be published through first-party Hapax surfaces
and through surfaces with stable API contracts. The absence of a Bandcamp
publisher is intentional governance state, not an implementation backlog.

## Lift conditions

The refusal can be reconsidered only if Bandcamp publishes a stable upload API
with account-safe automation terms and a credential flow compatible with
Hapax's pass-backed secret handling.

## Cross-references

- Surface registry: `agents/publication_bus/surface_registry.py` (`bandcamp-upload`)
- RefusedPublisher subclass: `agents/publication_bus/publisher_kit/refused.py` (`BandcampRefusedPublisher`)
