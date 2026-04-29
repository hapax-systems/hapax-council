### Purpose

This is the Codex-visible operator dossier summary. It is decision-predictive,
not biographical. It exists so Codex sessions can keep moving during operator
absence without copying private memory, raw conversation logs, or credential
values into generated prompts.

### Safe Pointer

- Private dossier source: `~/.claude/projects/-home-hapax-projects/memory/user_profile.md`
- Activation relay: `~/.cache/hapax/relay/inflections/20260424T150500Z-beta-all-operator-dossier-active.md`
- Codex rule: treat those as private source pointers. Do not paste or summarize
  their raw contents into bootstrap prompts.

### Decision Heuristics

- Prefer reversible action over waiting when the operator is away.
- Choose a coherent fix-forward or a clean revert for broken shipped work; do
  not leave a known broken baseline dormant.
- Escalate only when the next move is irreversible, outside the task scope, or
  ambiguous against governance constraints.
- Keep work visible through the cc-task note, relay YAML, branch, PR, and exact
  verification evidence.
- Respect the single-operator axiom. Do not introduce auth, roles, multi-user
  flows, or collaboration abstractions.
- Preserve privacy and redaction by default. Do not copy private memory,
  personal logs, credential material, or raw dialogue into Codex context.
- Use direct engineering prose: findings and blockers first, concise evidence,
  no performative reassurance.

### Update And Invalidation

- Update this file only from explicit durable operator directives, broad
  operator corrections, or reviewed safe relay summaries.
- Do not update it with narrow technical fixes, temporary task state, or
  ephemeral observations.
- Invalidate or downgrade to pointer-only if the operator contradicts a rule,
  if a source is found to contain private material, or if the summary has not
  been reviewed after a major workflow change.
- Review any edit as prompt-visible material before merging.
