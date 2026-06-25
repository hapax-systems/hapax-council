# Routing Ontology Reference

Canonical reference for the quality-preserving capacity routing ontology.
Source of truth: `shared/route_metadata_schema.py`.

## Quality Floor Categories

| Floor | Meaning | Dispatch constraint |
|-------|---------|---------------------|
| `frontier_required` | Task requires frontier-class model (Opus/Sonnet) | Claude Code or Codex only |
| `frontier_review_required` | Support artifact; must be independently reviewed | Support lane + frontier review |
| `deterministic_ok` | Mechanical work; any capable platform | All platforms including JR+ |

## Authority Levels

| Level | Meaning |
|-------|---------|
| `authoritative` | Output is directly authoritative (governance, specs) |
| `support_non_authoritative` | Output supports decisions but requires review |
| `evidence_receipt` | Observes and records; no claims |
| `relay_only` | Coordination messages; no content claims |

## Mutation Surfaces

| Surface | What changes |
|---------|-------------|
| `none` | Read-only / coordination |
| `vault_docs` | Obsidian vault notes, research, specs |
| `source` | Python / Rust / TypeScript source code |
| `runtime` | Running services, systemd, Docker |
| `public` | Anything visible to non-operator |
| `provider_spend` | API calls that cost money |

## Platform Taxonomy

Defined in `RouteConstraints.preferred_platforms` / `allowed_platforms` / `prohibited_platforms`.

| Platform | Profile | Tier | Context | Strengths |
|----------|---------|------|---------|-----------|
| `claude` | Claude Code (Opus/Sonnet) | Frontier | 1M | Multi-file refactors, governance, architecture |
| `codex` | Codex headless | Frontier | 192K | Bounded implementation, parallel lanes |
| `vibe` | Mistral Medium 3.5 | JR+ | 256K | Mechanical: tests, deps, CI fixes |
| `antigrav` | Antigravity/agy (Gemini-family) | JR+ | large | Directed, bounded, agy-backed CLI/IDE work |

## Reaching the Opus Route (signed route-authority receipts)

`--policy-rollback` is **retired** (#3792). It is now a deprecated no-op alias
that HOLDs every route (`policy_rollback_retired`) — passing it does not launch
opus. A structurally degraded frontier route un-degrades only with a **signed
route-authority receipt**, not a flag:

| Receipt type | Removes blockers | Effect |
|--------------|------------------|--------|
| `opus_model_entitlement` | `opus_model_entitlement_receipt_absent`, `fresh_capability_evidence_absent` | Raises the opus authority ceiling so `claude.headless.opus` can LAUNCH |
| `quality_equivalence` | `quality_equivalence_record_absent`, `fresh_capability_evidence_absent` | Records a bounded-floor equivalence for a fallback route (e.g. sonnet); does **not** widen the authority ceiling |

**Opus is reachable by default — no flag, no manual step.** The operator's
standing OQ-5 authorization is kept live by
`hapax-opus-route-authority-receipt.timer`, which re-signs a fresh
`opus_model_entitlement` receipt for `claude.headless.opus` into the default
receipt dir every 6h (`hapax-mint-route-authority-receipt --ensure-fresh`, a 24h
window with an 8h re-sign floor). So a plain `--profile full` dispatch reaches
the opus route with nothing extra — the old workaround (dispatching from a
*stale* council worktree with `HAPAX_CLAUDE_MODEL=opus` + `--policy-rollback`)
is retired; do not reintroduce it.

Mint or re-mint a receipt by hand — the executable form of OQ-5 (the operator
signs the entitlement) — for bootstrap, a custom route, or a quality floor:

```bash
# One-off mint (the timer keeps it fresh thereafter):
scripts/hapax-mint-route-authority-receipt \
    --receipt-type opus_model_entitlement --route-id claude.headless.opus

# Idempotent upkeep — exactly what the timer runs: a stable receipt id,
# re-minting only once the live receipt is within --refresh-within of staleness:
scripts/hapax-mint-route-authority-receipt --ensure-fresh \
    --receipt-type opus_model_entitlement --route-id claude.headless.opus

# Record sonnet quality-equivalence for a bounded floor:
scripts/hapax-mint-route-authority-receipt \
    --receipt-type quality_equivalence --route-id claude.headless.sonnet \
    --quality-floor frontier_required --evidence-ref isap:SLICE-123
```

The receipt is written to `<receipt-dir>/route-authority/<id>.json`. The dispatch
read-path (`load_dispatch_policy_sources`) defaults `receipt_dir` to
`~/.cache/hapax/platform-capability-receipts` (override with
`HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR`; set it to `none`/`0`/`false` to disable
receipt loading). Receipts carry a `stale_after` window (default `24h`) and a
`signed_payload_sha256` — a tampered or stale receipt fails closed. An
`opus_model_entitlement` receipt must target a route ending in `.opus`; a
`quality_equivalence` receipt requires at least one `--quality-floor`.

Source of truth: `shared/dispatcher_policy.py`
(`build_route_authority_receipt`, `apply_route_authority_receipts`),
`scripts/hapax-mint-route-authority-receipt` (`--ensure-fresh`), and
`systemd/units/hapax-opus-route-authority-receipt.{service,timer}`.

## Route Metadata Schema (v1)

Every cc-task and request carries `route_metadata` in YAML frontmatter:

```yaml
route_metadata:
  route_metadata_schema: 1
  quality_floor: frontier_required
  authority_level: authoritative
  mutation_surface: source
  mutation_scope_refs: [shared/route_metadata_schema.py]
  risk_flags:
    governance_sensitive: false
    privacy_or_secret_sensitive: false
    public_claim_sensitive: false
  context_shape:
    codebase_locality: module
    vault_context_required: true
  verification_surface:
    deterministic_tests: [pytest]
    static_checks: [ruff, pyright]
  route_constraints:
    preferred_platforms: [claude]
    allowed_platforms: [claude, codex]
    prohibited_platforms: []
  review_requirement:
    support_artifact_allowed: false
    independent_review_required: false
  route_envelope:
    classification_envelope:
      label: source_python
      classifier: deterministic-route-classifier
      source_kind: deterministic
      confidence: 0.9
      evidence_refs: [route-classifier:source-python]
      freshness: fresh
      authority_ceiling: authoritative
      validity_mask:
        label: true
        source: true
        confidence: true
        freshness: true
        authority_ceiling: true
      deterministic_facts_used: [mutation_surface:source]
      consumer_floor: frontier_required
    eligibility:
      authority_allowed: true
      privacy_allowed: true
      freshness_ok: true
      quality_floor_satisfied: true
      required_tools_available: true
      budget_allowed: true
      reason_codes: [eligibility_witnessed]
    admission:
      admission_action: route
      reason_codes: [route_envelope_route]
```

Missing or invalid `route_envelope` / `DemandVector` evidence is not
dispatchable: primary dispatch holds before `policy_launch`. Recheck with:

```bash
uv run pytest tests/shared/test_dispatcher_policy.py
```

## Derivation

Tasks without explicit `route_metadata` get conservative derived metadata via
`derive_route_metadata_payload()`. The derivation reads `kind`, `tags`,
`risk_tier`, and `authority_case` from existing frontmatter fields.

## Demand Vector

For dispatcher-level routing, `build_demand_vector()` projects route metadata
plus task-specific signals into the `DemandVector` used by the policy layer. The
vector is capacity-oriented: it carries quality, authority, mutation, risk,
context, verification, tool, budget, benchmark, public-projection, and hardening
allocation fields rather than exposing a fixed numbered dimension set.

## Task Dimension Fit Extension

The Obsidian vault packet
`[[task-dimensions-platform-profile-fit-research-2026-05-20]]` extends the R1
route ontology with the ranked dimensions that predict platform/profile fit.
Its main additions for later schema work are:

| Predictor | Proposed field | Why it matters |
|-----------|----------------|----------------|
| Output finality | `output_finality` | Irreversible artifacts need stronger routes than repairable drafts. |
| Review containment | `review_containment` | Support routes are safe only when review can cheaply catch failures. |
| Claim scope | `claim_scope` | Public, scientific, revenue, and support claims need stricter evidence gates. |
| Context budget | `context_budget_class` | A route is not quality-equivalent if it cannot fit the required context. |
| Operator obligation | `operator_obligation` | Legal, account, financial, and live-observation actions stay operator-owned. |

The packet preserves the existing invariant: quota, cost, latency, and
parallelism rank routes only after quality and authority gates pass.
