# Axiom Governance

This system is governed by constitutional axioms (system-wide) and domain axioms (functional areas). All architectural decisions must respect them. Domain axioms inherit constitutional constraints (supremacy clause).

## Axiom: single_operator (weight: 100)

This system is developed for a single operator and by that single operator, the operator (Hapax). This will always be the case. All decisions must be made respecting and leveraging that fact.

## Axiom: decision_support (weight: 95)

This system supports high-stakes management decisions. It proactively surfaces context, open loops, and patterns so the operator can act with confidence. Recurring management workflows must be automated. The system must reduce cognitive load, not add to it.

## Axiom: management_safety (weight: 95)

LLMs prepare, humans deliver. Management tooling aggregates signals and prepares context for the operator's relational work. It never substitutes for human judgment in people decisions. The system surfaces patterns and open loops but never generates feedback language, coaching hypotheses, or recommendations about individual team members.

## T0 Blocking Implications (single_operator)

These are existential violations — code matching these patterns MUST NOT be written:

- **su-auth-001**: All authentication, authorization, and operator management code must be removed or disabled since there is exactly one authorized operator.
- **su-privacy-001**: Privacy controls, data anonymization, and consent mechanisms are unnecessary since the operator is also the developer.
- **su-security-001**: Multi-tenant security measures, rate limiting per operator, and operator input validation for malicious intent are unnecessary.
- **su-feature-001**: Features for operator collaboration, sharing between operators, or multi-operator coordination must not be developed.
- **su-admin-001**: Administrative interfaces, operator management UIs, or role assignment systems must not exist since the single operator is the admin by default.

## T0 Blocking Implications (decision_support)

- **ex-init-001**: All agents must be runnable with zero configuration or setup steps beyond environment variables.
- **ex-err-001**: Error messages must include specific next actions, not just descriptions of what went wrong.
- **ex-routine-001**: Recurring tasks must be automated rather than requiring manual triggering by the operator.
- **ex-attention-001**: Critical alerts must be delivered through external channels (notifications, email) rather than requiring log monitoring.
- **ex-alert-004**: Alert mechanisms must proactively surface actionable items rather than requiring the operator to check status.
- **ex-routine-007**: Routine maintenance agents must run autonomously on schedules, not on-demand.

## T0 Blocking Implications (management_safety)

- **mg-boundary-001**: Never generate feedback language, performance evaluations, or coaching recommendations directed at individual team members.
- **mg-boundary-002**: Never suggest what the operator should say to a team member or draft language for delivery in people conversations.

## Domain Axiom: corporate_boundary (dormant)

This axiom governed cross-network behavior for the Obsidian plugin. It is currently dormant and not enforced. Retained for reference if cross-boundary operations resume.

## Compliance

Before making architectural decisions, consider whether the change violates these axioms. Do not build multi-operator scaffolding, auth systems, operator management, or collaboration features. Do not add cognitive load through unnecessary configuration, manual steps, or missing error context. Do not generate feedback language, coaching recommendations, or people-decision suggestions in management tooling.

Run `/axiom-check` to review current compliance status.
