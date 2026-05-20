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
| `gemini` | Gemini CLI (Pro) | Research | 2M | Long-doc research, OCR, plan-mode |
| `vibe` | Mistral Medium 3.5 | JR+ | 256K | Mechanical: tests, deps, CI fixes |
| `antigrav` | Antigravity IDE | JR+ | Opus | Directed, bounded, IDE-bound |

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
```

## Derivation

Tasks without explicit `route_metadata` get conservative derived metadata via
`derive_route_metadata_payload()`. The derivation reads `kind`, `tags`,
`risk_tier`, and `authority_case` from existing frontmatter fields.

## Demand Vector

For dispatcher-level routing, `build_demand_vector()` projects route metadata
plus task-specific signals into a 17-dimension `DemandVector` used by the
policy layer.
