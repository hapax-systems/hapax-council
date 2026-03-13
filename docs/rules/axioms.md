# Axiom Governance

This system is governed by constitutional axioms (system-wide) and domain axioms (functional areas). All architectural decisions must respect them. Domain axioms inherit constitutional constraints (supremacy clause).

## Axiom: single_user (weight: 100, constitutional)

This system is developed for a single user and by that single user, the operator (Hapax). This will always be the case. All decisions must be made respecting and leveraging that fact.

## Axiom: executive_function (weight: 95, constitutional)

This system serves as externalized executive function infrastructure. The operator has ADHD and autism — task initiation, sustained attention, and routine maintenance are genuine cognitive challenges. The system must compensate for these, not add to cognitive load.

## Axiom: interpersonal_transparency (weight: 88, constitutional)

The system must not maintain persistent state about any non-operator person without an active consent contract. A consent contract requires explicit opt-in by the subject, grants the subject inspection access to all data the system holds about them, and is revocable by either party at any time. Upon revocation, the system purges all subject-specific persistent state.

## Axiom: corporate_boundary (weight: 90, domain: infrastructure)

The Obsidian plugin operates across a corporate network boundary via Obsidian Sync. When running on employer-managed devices, all external API calls must use employer-sanctioned providers. No localhost service dependencies may be assumed. The system must degrade gracefully when home-only services are unreachable.

## Axiom: management_governance (weight: 85, domain: management)

Management tooling aggregates signals and prepares context for the operator's relational work. It never substitutes for human judgment in people decisions. LLMs prepare, humans deliver — the system surfaces patterns and open loops, never generates feedback language, coaching hypotheses, or recommendations about individual team members.

## T0 Blocking Implications (single_user)

These are existential violations — code matching these patterns MUST NOT be written:

- **su-auth-001**: All authentication, authorization, and operator management code must be removed or disabled since there is exactly one authorized operator.
- **su-privacy-001**: Privacy controls, data anonymization, and consent mechanisms are unnecessary since the operator is also the developer.
- **su-security-001**: Multi-tenant security measures, rate limiting per operator, and operator input validation for malicious intent are unnecessary.
- **su-feature-001**: Features for operator collaboration, sharing between operators, or multi-operator coordination must not be developed.
- **su-admin-001**: Administrative interfaces, operator management UIs, or role assignment systems must not exist since the single operator is the admin by default.

## T0 Blocking Implications (executive_function)

- **ex-init-001**: All agents must be runnable with zero configuration or setup steps beyond environment variables.
- **ex-err-001**: Error messages must include specific next actions, not just descriptions of what went wrong.
- **ex-routine-001**: Recurring tasks must be automated rather than requiring manual triggering by the operator.
- **ex-attention-001**: Critical alerts must be delivered through external channels (notifications, email) rather than requiring log monitoring.
- **ex-alert-004**: Alert mechanisms must proactively surface actionable items rather than requiring the operator to check status.
- **ex-routine-007**: Routine maintenance agents must run autonomously on schedules, not on-demand.
- **ex-prose-001**: Generated prose must not contain rhetorical pivots, performative insight, dramatic restatement, or contrast structures that exist for rhythm rather than content.

## T0 Blocking Implications (interpersonal_transparency)

- **it-consent-001**: No persistent state about any non-operator person may be created without an active consent contract.
- **it-consent-002**: Consent contracts must enumerate permitted data categories; no blanket consent.
- **it-revoke-001**: Revocation of a consent contract must trigger full purge of subject-specific persistent state.

## T0 Blocking Implications (management_governance)

- **mg-boundary-001**: Never generate feedback language, performance evaluations, or coaching recommendations directed at individual team members.
- **mg-boundary-002**: Never suggest what the operator should say to a team member or draft language for delivery in people conversations.

## Compliance

Before making architectural decisions, consider whether the change violates these axioms. Do not build multi-operator scaffolding, auth systems, operator management, or collaboration features. Do not add cognitive load through unnecessary configuration, manual steps, or missing error context. Do not generate feedback language, coaching recommendations, or people-decision suggestions in management tooling. Do not persist state about non-operator persons without consent contracts.

Run `/axiom-check` to review current compliance status.
