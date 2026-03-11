# Document Registry & Coverage Enforcement — Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a formal document registry and coverage enforcement layer to the drift detector, enabling detection of absent documents, structural violations, and cross-repo mutual awareness gaps.

**Architecture:** A YAML registry file declares document archetypes (with required sections), CI-to-document coverage rules, and mutual awareness constraints. The drift detector reads this registry and runs deterministic checks against live filesystem/infrastructure state. Missing coverage produces drift items alongside existing findings. The fix+apply pipeline can scaffold missing documents from templates.

**Tech Stack:** Python, YAML (PyYAML already a dependency), existing drift_detector.py infrastructure.

---

## Background & Research

### Problem Statement

The drift detector compares existing documentation against live infrastructure but has no concept of what documentation *should* exist. It cannot detect:

- A new agent module with no entry in `agent-architecture.md`
- A new systemd timer with no row in `system-context.md`
- A repo that exists but isn't listed in hapaxromana's Related Repos table
- Documents missing required structural sections
- Repos that are blind to sibling repos' existence

### Formal Foundations

The design draws from three established systems:

**CMDB (Configuration Management Database):** Every significant system element is a Configuration Item (CI) with typed attributes and declared relationships. Documents are CIs that must have relationships to the infrastructure CIs they describe. Coverage gaps are detected by checking that every CI of type X has a corresponding reference in a document of type Y. ([Wikipedia: CMDB](https://en.wikipedia.org/wiki/Configuration_management_database))

**DITA (Darwin Information Typing Architecture):** Documents are classified by information type — concept, task, reference, troubleshooting. Each type has a schema defining required structural elements. We adapt this by defining document archetypes with required markdown sections. ([OASIS: DITA Information Typing](https://dita-lang.org/dita/archspec/base/information-typing))

**ADR (Architecture Decision Records):** Point-in-time design documents with standardized structure (context, decision, consequences). We incorporate this as the `design-record` archetype. ([ADR GitHub](https://adr.github.io/))

### Audit Findings

An audit of all 73+ documents across 8 hapax repos revealed:

- **60% of documents are single-archetype** (clean fit): rules files, design docs, audit findings, cross-project specs
- **40% are hybrid** (mix archetypes): most CLAUDE.md files, operations-manual.md
- **Key problem is duplication, not typing:** model aliases in 4 places, agent rosters in 3, no single authoritative reference
- **Coverage gaps are invisible:** new agents/timers/services can be added with zero documentation updates
- **Two repos missing from scan scope:** hapax-vscode and hapax-containerization not in HAPAX_REPO_DIRS

---

## Type System

### Configuration Item Types

Things that exist in the system. Discovered by introspecting live state:

| CI Type | Discovery Method | Source |
|---------|-----------------|--------|
| `repo` | Git repos in `~/projects/` with hapax-related CLAUDE.md | Filesystem scan |
| `agent` | Python modules in `agents/` with `if __name__` or `__main__.py` | Filesystem scan |
| `timer` | `systemctl --user list-unit-files '*.timer'` | Systemd query |
| `service` | Docker containers from `docker compose ps` in `~/llm-stack/` | Docker query |
| `mcp-server` | Entries in Claude Code MCP config | JSON parse |
| `rule` | `.md` files in `~/.claude/rules/` and `hapax-system/rules/` | Filesystem scan |
| `axiom` | Axiom registry entries | `shared/axiom_registry.py` |

### Document Archetypes

Classification of what kind of document something is, adapted from DITA information typing:

| Archetype | Purpose | Composite? | Required Sections |
|-----------|---------|------------|-------------------|
| `project-context` | Per-repo working context for Claude Code | Yes | `## Project Memory`, `## Conventions` |
| `specification` | Architectural design, invariants, contracts | No | `## Architecture` |
| `reference` | Canonical lookup tables (single source of truth) | No | Content-dependent |
| `operational` | Procedures, workflows, troubleshooting | No | — |
| `governance` | Axioms, rules, constraints, boundaries | No | — |
| `design-record` | Point-in-time design decisions | No | `## Goal`, `## Architecture` |

`project-context` is explicitly composite — CLAUDE.md files are allowed to blend interface docs, conventions, and project memory by design. All other archetypes should be single-purpose.

### Coverage Rules

Typed assertions: "for every CI of type X, there must exist a reference in document Y."

| CI Type | Canonical Reference Document | Section | Match Strategy |
|---------|------------------------------|---------|----------------|
| `agent` | `system-context.md` | `## Management Agents` | Agent name in table |
| `agent` | `agent-architecture.md` | Any `### ` heading | Agent name in heading |
| `timer` | `system-context.md` | `## Management Timers` | Timer name in table |
| `service` | `environment.md` | Core Infrastructure table | Service name in table |
| `repo` | `hapaxromana/CLAUDE.md` | `## Related Repos` | Repo name in table |
| `repo` | own `CLAUDE.md` | — | File must exist |
| `mcp-server` | `~/.claude/CLAUDE.md` | `## MCP Servers` | Server name in list |
| `axiom` | `axioms.md` | `## Axiom:` sections | Axiom ID in heading |

### Mutual Awareness Rules

Cross-repo relationship enforcement:

1. **Repo registry completeness:** Every hapax-related git repo must appear in hapaxromana's Related Repos table.
2. **Spec source reference:** Every repo's CLAUDE.md should reference hapaxromana as the architectural spec source (or state its relationship to the wider system).
3. **Boundary doc symmetry:** Documents declared as byte-identical across repos are compared.

---

## Registry File Format

A single YAML file at `hapaxromana/docs/document-registry.yaml` declares the full schema. The drift detector reads this file and runs checks against live state.

```yaml
version: 1

# ── Document archetypes ──────────────────────────────────────────────
archetypes:
  project-context:
    description: "Per-repo working context for Claude Code"
    required_sections: ["## Project Memory", "## Conventions"]
    composite: true
  specification:
    description: "Architectural design, invariants, contracts"
    required_sections: ["## Architecture"]
    composite: false
  reference:
    description: "Canonical lookup tables, single source of truth"
    required_sections: []
    composite: false
  operational:
    description: "Procedures, workflows, troubleshooting"
    required_sections: []
    composite: false
  governance:
    description: "Axioms, rules, constraints, boundaries"
    required_sections: []
    composite: false
  design-record:
    description: "Point-in-time design decisions"
    required_sections: ["## Goal"]
    composite: false

# ── Repo declarations ────────────────────────────────────────────────
repos:
  ai-agents:
    path: ~/projects/ai-agents
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
    ci_sources:
      agents: "agents/"  # discover agent modules here
  hapaxromana:
    path: ~/projects/hapaxromana
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
      - path: agent-architecture.md
        archetype: specification
      - path: operations-manual.md
        archetype: operational
      - path: README.md
        archetype: project-context
      - path: docs/document-registry.yaml
        archetype: governance
  hapax-system:
    path: ~/projects/hapax-system
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
      - path: rules/axioms.md
        archetype: governance
      - path: rules/system-context.md
        archetype: reference
      - path: rules/management-context.md
        archetype: governance
  cockpit-web:
    path: ~/projects/cockpit-web
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
  hapax-vscode:
    path: ~/projects/hapax-vscode
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
  rag-pipeline:
    path: ~/projects/rag-pipeline
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
  obsidian-hapax:
    path: ~/projects/obsidian-hapax
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
  hapax-containerization:
    path: ~/projects/hapax-containerization
    required_docs:
      - path: CLAUDE.md
        archetype: project-context

# ── Coverage rules ───────────────────────────────────────────────────
coverage_rules:
  - ci_type: agent
    reference_doc: "~/projects/hapax-system/rules/system-context.md"
    reference_section: "## Management Agents"
    match_by: name
    severity: medium
  - ci_type: agent
    reference_doc: "~/projects/hapaxromana/agent-architecture.md"
    match_by: name_in_heading
    severity: low  # architecture doc lags implementation
  - ci_type: timer
    reference_doc: "~/projects/hapax-system/rules/system-context.md"
    reference_section: "## Management Timers"
    match_by: name
    severity: medium
  - ci_type: service
    reference_doc: "~/.claude/rules/environment.md"
    match_by: name
    severity: medium
  - ci_type: repo
    reference_doc: "~/projects/hapaxromana/CLAUDE.md"
    reference_section: "## Related Repos"
    match_by: name
    severity: medium
  - ci_type: mcp_server
    reference_doc: "~/.claude/CLAUDE.md"
    reference_section: "## MCP Servers"
    match_by: name
    severity: low

# ── Mutual awareness ────────────────────────────────────────────────
mutual_awareness:
  - type: repo_registry
    description: "All hapax repos must appear in hapaxromana's Related Repos"
    registry_doc: "~/projects/hapaxromana/CLAUDE.md"
    registry_section: "## Related Repos"
    severity: medium
  - type: spec_reference
    description: "Every repo should reference hapaxromana as spec source"
    target_phrase: "hapaxromana"
    severity: low
  - type: byte_identical
    description: "Cross-project boundary must be identical in both repos"
    docs:
      - "~/projects/hapaxromana/docs/cross-project-boundary.md"
      - "~/projects/hapax-containerization/docs/cross-project-boundary.md"
    severity: high
```

---

## Enforcement Mechanics

### Integration with drift_detector.py

A new deterministic check function `check_document_registry()` is added alongside the existing six:

```
scan_axiom_violations()          # existing
scan_sufficiency_gaps()          # existing
check_doc_freshness()            # existing
check_screen_context_drift()     # existing
check_cross_project_boundary()   # existing (subsumed by registry)
check_project_memory()           # existing (subsumed by registry)
check_document_registry()        # NEW — replaces and extends the above two
```

`check_document_registry()` performs four sub-checks:

1. **Required document existence:** For each repo, verify every `required_docs` entry exists on disk.
2. **Archetype section validation:** For docs with an archetype, verify the archetype's `required_sections` headings are present.
3. **Coverage rule evaluation:** Discover live CIs, then for each coverage rule, check that every CI appears in the referenced document section.
4. **Mutual awareness evaluation:** Run each mutual awareness rule (repo registry completeness, spec references, byte-identical comparisons).

### CI Discovery

Each CI type has a discovery function:

- **agents:** Scan `agents/` directory for Python modules with `if __name__` blocks. Normalize names: `drift_detector.py` → `drift-detector`.
- **timers:** `systemctl --user list-unit-files '*.timer' --no-legend` → parse timer names.
- **services:** `docker compose -f ~/llm-stack/docker-compose.yml ps --format '{{.Name}}'` → service names.
- **repos:** Scan `~/projects/` for directories containing `.git/` and either `CLAUDE.md` mentioning "hapax" or directory names matching `hapax-*`.
- **mcp_servers:** Parse `~/.claude/mcp_servers.json` for server names.

### DriftItem Categories

New drift item categories produced by registry checks:

| Category | Severity | Example |
|----------|----------|---------|
| `missing-required-doc` | medium | CLAUDE.md missing from a declared repo |
| `missing-section` | medium | `## Project Memory` absent from CLAUDE.md |
| `coverage-gap` | medium/low | Agent `gmail_sync` not in system-context.md |
| `repo-awareness-gap` | medium | `hapax-vscode` not in Related Repos table |
| `spec-reference-gap` | low | Repo CLAUDE.md doesn't mention hapaxromana |
| `boundary-mismatch` | high | Byte-identical docs differ |

### Fix+Apply Support

When `--fix --apply` is used, coverage gaps can be partially auto-fixed:

- **Missing required doc:** Generate from archetype template (CLAUDE.md with `## Project Memory` and `## Conventions` stubs).
- **Missing section:** Append a stub section to the document.
- **Coverage gap in reference table:** The LLM fix agent can be told "add a row for agent X to the Management Agents table in system-context.md" — it already handles table insertions.
- **Repo awareness gap:** LLM fix agent adds a row to the Related Repos table.

Items that require substantive new content (specification entries, operational procedures) are flagged but not auto-fixed — they produce drift items with actionable suggestions.

### Subsumption

`check_document_registry()` subsumes two existing checks:

- `check_project_memory()` → replaced by archetype section validation (project-context requires `## Project Memory`)
- `check_cross_project_boundary()` → replaced by mutual awareness byte-identical rule

These two functions can be removed once the registry checker is active.

---

## HAPAX_REPO_DIRS Update

As part of this work, `HAPAX_REPO_DIRS` in `drift_detector.py` and `shared/config.py` must be updated to include:

- `hapax-vscode` (active Tier 1 UI)
- `hapax-containerization` (management extraction)

The registry's `repos:` section becomes the authoritative list, and `HAPAX_REPO_DIRS` is derived from it.

---

## Testing Strategy

- Unit tests for each CI discovery function (mocked filesystem/subprocess)
- Unit tests for each registry check (coverage rules, section validation, mutual awareness)
- Integration test: load the actual registry YAML, run against mocked CI state, verify expected drift items
- Existing drift detector tests continue to pass (no regression)

---

## What This Does NOT Do

- **No CI/CD hooks or pre-commit enforcement.** Drift detection remains a periodic scan, not a gate.
- **No document content quality assessment.** We check structure (sections exist) and coverage (CIs are referenced), not prose quality.
- **No automatic document refactoring.** The audit identified hybrid documents and duplication, but this design doesn't restructure existing docs — it enforces that required information exists *somewhere*.
- **No graph database.** The CI-document relationship graph is implicit in the YAML rules, checked by code. YAGNI.
