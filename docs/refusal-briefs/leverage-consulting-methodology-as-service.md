# Refusal Brief: Consulting / Methodology-as-Service

**Slug:** `leverage-REFUSED-consulting-methodology-as-service`
**Axiom tag:** `feedback_full_automation_or_no_engagement`, `single_user`
**Refusal classification:** Operator-mediated client engagement — not daemon-tractable
**Status:** REFUSED — no consulting offering, no `agents/consulting_dispatcher/`, no Cal.com / Calendly integration.
**Date:** 2026-04-26
**Related cc-task:** `leverage-REFUSED-consulting-methodology-as-service`
**CI guard:** `tests/test_forbidden_social_media_imports.py` (`FORBIDDEN_PACKAGE_PATHS`)

## What was refused

- Consulting offering / methodology-as-service business model
- Discovery / scoping calls
- Iterative client-deliverable sessions
- Client-relationship management
- Cal.com / Calendly / similar booking-platform integration
- `agents/consulting_dispatcher/`, `agents/consulting/`,
  `agents/calcom_integration/`, `agents/calendly_integration/`

## Why this is refused

### Operator-mediated client engagement

Consulting requires sustained operator-physical engagement:

- **Discovery / scoping calls** — synchronous conversations to map
  client problem space; cannot be daemonized
- **Iterative deliverable sessions** — per-client revision cycles
  driven by client feedback; operator-physical iteration
- **Client-relationship management** — proposal authoring, contract
  negotiation, scope-creep mediation, retainer-renewal conversations

Each is operator-physical. Even with LLM-assisted draft generation,
the surfaces require operator-physical client-meeting attendance and
operator-physical accountability.

### Constitutional incompatibility

Per `feedback_full_automation_or_no_engagement` (operator
constitutional directive 2026-04-25T16:55Z): the operator refuses
research / monetization surfaces not fully Hapax-automated. A
consulting business model is the canonical example of an
operator-physical revenue stream — there is no daemon-tractable
pathway through client engagement.

### Single-operator axiom

Consulting implies a service-provider role with multiple clients.
The single-operator axiom precludes maintaining a CRM / pipeline /
multi-tenant client database; even a single-client consulting
arrangement requires operator-physical relationship maintenance.

## Daemon-tractable boundary (the replacement path)

The same intellectual content is delivered via **PyPI packaging**:

- **`hapax-axioms`** — axiom-enforcement primitives as importable
  Python package
- **`hapax-refusals`** — refusal-brief writer + RefusalEvent model
  + log rotation
- **`hapax-velocity-meter`** — sprint-velocity instrumentation
- **`hapax-swarm`** — multi-session relay protocol primitives

These packages deliver the methodology as **daemon-tractable
artifacts**: anyone can `pip install hapax-axioms` and adopt the
single-operator + full-automation envelope without operator
engagement. Documentation, examples, and CI patterns ship with the
package. There is no operator-physical channel.

The PyPI packaging path is the constitutional fit: methodology as
infrastructure-as-argument, not methodology as ongoing service
relationship.

## CI guard

`tests/test_forbidden_social_media_imports.py` enforces a path-based
guard. Forbidden paths added:

- `agents/consulting_dispatcher/`
- `agents/consulting/`
- `agents/calcom_integration/`
- `agents/calendly_integration/`

CI fails if any of these directories are introduced.

## Lift conditions

This is a constitutional refusal grounded in the full-automation
envelope + single-operator axiom. Lift requires either:

- `feedback_full_automation_or_no_engagement` retirement
- Single-operator axiom retirement (extremely unlikely; foundational
  axiom)

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check both probes per its cadence policy.

## Cross-references

- cc-task vault note: `leverage-REFUSED-consulting-methodology-as-service.md`
- Replacement path: `leverage-workflow-hapax-axioms-pypi`
- CI guard: `tests/test_forbidden_social_media_imports.py`
- Methodology-as-PyPI examples: `hapax_sdlc/`,
  `agents/refusal_brief/` (would be packaged as `hapax-refusals`)
- Source research: `docs/research/2026-04-25-leverage-strategy.md`
