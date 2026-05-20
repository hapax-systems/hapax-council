---
type: spec
task_id: 20260509195830-quality-preserv-p1-spec-routing-ontology-metadata-schema
title: "Work-Item Routing Metadata Schema & Quality-Floor Representation"
authority_case: CASE-CAPACITY-ROUTING-001
created_at: 2026-05-20T18:50:00Z
cross_refs:
  - 30-areas/hapax/2026-05-20-observable-subscription-quota-signals-research.md
---

# Work-Item Routing Metadata Schema

## Schema (route_metadata v1)

```yaml
# Every dispatchable work item MUST carry these fields.
# Producers populate; the dispatcher consumes mechanically.

schema_version: 1  # required, literal 1

# ── Quality Floor ──────────────────────────────────────
quality_floor:
  type: enum
  required: true
  values:
    frontier_required: >
      Task requires frontier-class model (Opus/Sonnet 4.6+).
      Governance, architecture, novel research, complex refactors.
    frontier_review_required: >
      Output must be frontier-reviewed even if drafted by a junior model.
      Verification, evidence, documentation with claims.
    deterministic_ok: >
      Mechanical/bounded work. Any tier can execute with verification.
      Dep upgrades, lint fixes, test additions, config changes.
    junior_bounded: >
      Well-scoped tasks with explicit acceptance criteria and no
      governance authority. Vibe/Antigrav eligible.

# ── Authority Risk ─────────────────────────────────────
authority_level:
  type: enum
  required: true
  values:
    authoritative: >
      Output becomes source of truth. Governance, specs, architecture
      decisions, axiom changes, publication content.
    review_contained: >
      Output is useful but requires peer review before authority.
      Draft specs, research packets, proposed refactors.
    support_non_authoritative: >
      Output supports but does not establish authority. Research
      notes, exploratory code, fixture data.

# ── Mutation Surface ──────────────────────────────────
mutation_surface:
  type: enum
  required: true
  values:
    source: Code changes (agents/, shared/, hapax-logos/, tests/).
    runtime: Live service state (systemd, PipeWire, Docker, /dev/shm).
    vault: Obsidian vault notes (~/Documents/Personal/).
    system: OS/package/config changes (pacman, systemd units, dotfiles).
    docs: Documentation only (docs/, publication-drafts/).
    none: Read-only research or audit with no mutations.

# ── Spend Posture ─────────────────────────────────────
spend_posture:
  type: enum
  required: false
  default: subscription_quota
  values:
    subscription_quota: >
      Use existing subscription allocation (Claude Code Max, Gemini
      Ultra, Codex Pro). No incremental API spend.
    bootstrap_budget: >
      One-time setup spend acceptable (model downloads, initial
      embeddings, cache priming).
    paid_api: >
      Task may consume metered API tokens (LiteLLM cloud routes).
      Dispatcher should prefer subscription models first.
    incident_override: >
      Incident response — spend constraints relaxed. Use fastest
      available model regardless of cost.
    steady_state_target: >
      Long-running daemon/timer work. Prefer local inference
      (TabbyAPI) over cloud to minimize ongoing cost.

# ── Platform Profile Hints ────────────────────────────
platform_suitability:
  type: list[enum]
  required: false
  default: [claude]
  values: [claude, codex, antigravity, vibe, gemini]
  semantics: >
    Producer suggests eligible platforms. The dispatcher MAY override
    based on capacity, queue depth, and profile fit. This is a hint,
    not a mandate.

# ── Output Finality ───────────────────────────────────
output_finality:
  type: enum
  required: false
  default: pr_merge
  values:
    pr_merge: Output is a PR that must pass CI and merge.
    vault_artifact: Output is a vault note (no PR).
    runtime_receipt: Output is a runtime state change with evidence.
    operator_review: Output requires explicit operator sign-off.

# ── Additional Fields ─────────────────────────────────
effort_class:
  type: enum
  required: false
  values: [trivial, standard, high, max]

risk_tier:
  type: enum
  required: false
  values: [T1, T2, T3]
  semantics: >
    T1 = protected invariants (audio, governance, axioms).
    T2 = standard source/runtime.
    T3 = low-risk docs/config.
```

## Worked Examples

### Example 1: Frontier-Required Task

```yaml
task_id: audio-graph-ssot-p4-daemon-takeover
quality_floor: frontier_required
authority_level: authoritative
mutation_surface: source
spend_posture: subscription_quota
platform_suitability: [claude, codex]
output_finality: pr_merge
effort_class: high
risk_tier: T1
```

The P4 daemon takeover writes to PipeWire configuration and the audio
graph SSOT. It requires frontier reasoning for the atomic apply/rollback
design, is authoritative (becomes the live write path), and mutates source
code. T1 risk because audio routing is a protected invariant.

### Example 2: Quality-Equivalent Downgrade Task

```yaml
task_id: chore-dead-code-pycache-cleanup
quality_floor: deterministic_ok
authority_level: support_non_authoritative
mutation_surface: source
spend_posture: subscription_quota
platform_suitability: [claude, codex, vibe, antigravity]
output_finality: pr_merge
effort_class: standard
risk_tier: T3
```

Vulture whitelist additions and dead-code reclassification. Any tier can
execute — the work is mechanical, the acceptance criteria are objective
(vulture stops flagging), and the output is non-authoritative (whitelist
entries don't establish new architecture).

### Example 3: Review-Contained Support Task

```yaml
task_id: grounding-inventory-audit
quality_floor: frontier_review_required
authority_level: review_contained
mutation_surface: docs
spend_posture: subscription_quota
platform_suitability: [claude, gemini]
output_finality: pr_merge
effort_class: standard
risk_tier: T3
```

Research audit producing a structured catalog. Frontier review required
because claims about the codebase must be verified against actual code.
Review-contained: the audit informs but does not decide architecture.
Gemini eligible for the long-context codebase scan.

## Validation

The `route_metadata_schema` field in cc-task frontmatter (currently `1`)
indicates the task conforms to this schema. Tasks with `route_metadata_schema: 1`
can be mechanically routed by the dispatcher without human triage.
