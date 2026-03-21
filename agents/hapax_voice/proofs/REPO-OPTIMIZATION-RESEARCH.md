# Repository Optimization for Voice Grounding Research

**Date:** 2026-03-21
**Purpose:** Comprehensive research on optimizing all hapax GitHub repositories to support a single goal — operationalizing Clark & Brennan's (1991) conversational grounding theory in a production voice AI.

Six independent research streams, 140+ sources consulted.

---

## Table of Contents

1. [Current State Audit](#1-current-state-audit)
2. [Repository Organization](#2-repository-organization)
3. [README Strategy](#3-readme-strategy)
4. [GitHub Actions & CI/CD](#4-github-actions--cicd)
5. [Research Documentation](#5-research-documentation)
6. [Open Science Infrastructure](#6-open-science-infrastructure)
7. [Synthesis: The Plan](#7-synthesis-the-plan)

---

## 1. Current State Audit

### Summary Matrix

| Repo | README | Workflows | Docs | License | CITATION.cff | Research Role |
|------|--------|-----------|------|---------|-------------|---------------|
| hapax-council | ✓ 217 lines | ✓ 9 | ✓ extensive | ✓ AL2 | ✗ | **Primary artifact** |
| hapax-constitution | ✓ 136 lines | ✓ 7 | ✓ extensive | ✓ AL2 | ✗ | Research artifact (spec) |
| hapax-officium | ✓ 133 lines | ✓ 8 | ✓ extensive | ✓ AL2 | ✗ | Supporting software |
| hapax-watch | ✓ 58 lines | ✗ | ✗ | ✗ | ✗ | Research instrument |
| cockpit-mcp | ✓ 32 lines | ✗ | ✗ | ✗ | ✗ | Infrastructure |
| tabbyAPI | ✓ ~50 lines | ✓ 4 | ✓ | ✓ AGPL3 | ✗ | Infrastructure (external) |
| distro-work | ✗ | ✓ 3 | ✓ rich | ✗ | ✗ | System scripts |

### Critical Gaps

- **No CITATION.cff** in any repository
- **No LICENSE** in hapax-watch, cockpit-mcp, distro-work
- **No GitHub Actions** in hapax-watch, cockpit-mcp
- **No README** in distro-work
- Research artifacts (proofs/) scattered within agent code, not extracted
- No OSF project, no DOIs, no pre-registration filed
- Lab journal exists but not deployed to GitHub Pages

---

## 2. Repository Organization

### Keep vs. Consolidate

**Keep separate (3):** hapax-watch (Kotlin/Android), tabbyAPI (external fork), distro-work (not software).

**Keep separate but tighten (4):** constitution, council, officium, cockpit-mcp — real dependencies exist but lifecycles differ enough that consolidation adds friction. Tighten via cross-repo tags, shared CI workflows, and a hub README.

The monorepo question was examined against DeepMind (per-project repos), FAIR (per-project repos), and Allen AI (561 separate repos + Tango for experiment orchestration). Consensus: for a single operator, the discoverability advantage of a monorepo is real but offset by the different tech stacks (Python, Kotlin, external forks). The hybrid approach — separate repos with a hub and coordinated tooling — is the right fit.

### Research Compendium Structure (hapax-council)

Based on TIER Protocol 4.0, BIDS, Psych-DS, The Turing Way, and Marwick et al.:

```
hapax-council/
├── agents/                     # Production agent code (existing)
├── shared/                     # Shared libraries (existing)
├── cockpit/                    # API server (existing)
│
├── research/                   # ← Research compendium root
│   ├── protocols/              # Pre-registrations, experiment protocols (versioned)
│   ├── theory/                 # ← Move proofs/ content here
│   ├── data/
│   │   ├── raw/                # Immutable original data
│   │   └── processed/          # Derived datasets
│   ├── analysis/               # Analysis scripts (Bayesian models, visualizations)
│   ├── results/
│   │   ├── figures/
│   │   └── tables/
│   ├── config/                 # Experiment configurations (versioned)
│   └── dataset_description.json  # Psych-DS metadata
│
├── docs/                       # Technical documentation
├── lab-journal/                # Quarto lab journal (existing)
└── tests/
```

**Key principle:** Separate input (data), methods (analysis), and output (results). Raw data is immutable. Current `proofs/` content moves to `research/theory/`.

### Experiment Version Control

- **Tag convention:** `experiment/v{major}.{minor}-{phase}` (e.g., `experiment/v2.0-baseline`)
- **Cross-repo tags:** Tag all dependent repos simultaneously at phase transitions
- **Protocol versions:** `protocol-v1.0.md`, `protocol-v1.1-amendment.md` — never overwrite, append
- **Config snapshots:** Committed as versioned files, not environment variables

### GitHub Features for Research

| Feature | Use |
|---------|-----|
| Organization-level Project | Cross-repo kanban spanning all research repos |
| Milestones | Map to experiment phases (baseline, intervention, analysis) |
| Labels | Standardize across repos: `research`, `infrastructure`, `experiment`, `analysis` |
| Releases | Snapshot experiment epochs with attached artifacts |
| Discussions | Low value for solo operator |
| Wiki | Low value — committed docs are better |

---

## 3. README Strategy

### Audience Analysis

Research READMEs serve six audiences with different needs:

| Audience | Needs | Priority |
|----------|-------|----------|
| **Future self** | Context reconstruction after 6+ months | Highest |
| **Journal reviewers** (JOSS, venue) | Methodological rigor, software quality, statement of need | High |
| **Replicators** | Exact reproduction: deps, hardware, step-by-step | High |
| **Open science community** | Purpose in seconds, navigate to what matters | Medium |
| **Tenure/hiring committees** | Scholarly impact signals: citations, DOIs, badges | Medium |
| **GitHub visitors** | Quick comprehension, badges, structure | Lower |

**Key finding:** Empirical research shows README update frequency and structural features (links, images, sections) differentiate popular from non-popular repos. Structure and maintenance matter more than content cleverness.

### Mandatory README Sections (JOSS + rOpenSci + RSQKit + Social Science Data Editors consensus)

1. **Title + one-line description**
2. **Badges** — CI, license, DOI, pre-registration, Open Science badges
3. **Statement of need** — problem, audience, relationship to existing work
4. **Installation** — dependencies with versions, automated procedure
5. **Quick start / Usage** — minimal working example
6. **Reproduction instructions** — how to reproduce reported results
7. **Computational requirements** — OS, CPU, memory, disk, wall-clock time
8. **Citation** — CITATION.cff plus inline citation block
9. **License**
10. **Data availability statement**

### Research-Specific Additions

- **Theoretical grounding** — brief description of Clark & Brennan, with citation
- **Pre-registration link** — timestamped OSF registration
- **Study design description** — SCED phase structure, standards referenced
- **Ethics statement** — if applicable
- **Related publications**

### Hub-and-Spoke Pattern

**Hub (hapax-council):** Full research context, architecture diagram, table mapping all repos to roles, citation info, reproduction instructions.

**Spokes (all other repos):** Self-contained description + "Part of Hapax Research Project" banner linking to hub. Only research context relevant to that specific component. Own installation/usage (fully self-contained). Pointer to hub for full context.

### Per-Repo README Classification

| Repo | Type | Research Context | README Length |
|------|------|-----------------|--------------|
| hapax-council | Hub / Primary artifact | Full | Comprehensive |
| hapax-constitution | Research artifact (spec) | Moderate | Medium |
| hapax-watch | Research instrument | Moderate (sensor specs) | Medium |
| hapax-officium | Supporting software | Minimal (pointer) | Medium |
| cockpit-mcp | Infrastructure | Minimal (pointer) | Short-medium |
| tabbyAPI | Infrastructure (external) | Minimal (pointer) | Short |
| distro-work | Not research | None | Minimal |

### Anti-Patterns to Avoid

1. Implementation-heavy, context-light (pages of API docs, no "why")
2. Missing citation information
3. "Works on my machine" — no versions, no hardware specs
4. No reproduction path from data to results
5. Stale README never updated
6. Monolithic README instead of navigating to focused docs
7. No license (legally unusable)
8. Under-documenting the theory being operationalized

---

## 4. GitHub Actions & CI/CD

### Current State

Council has 9 workflows including full SDLC pipeline (Triage → Plan → Implement → Adversarial Review → Axiom Gate → Auto-merge). Constitution has 7. Officium has 8. Watch and cockpit-mcp have none.

### Research-Specific Gates to Add

1. **Experiment Impact Gate** (Plan → Implement): If PR touches `research/` or `agents/hapax_voice/`, require linked experiment issue with hypothesis and expected outcome.

2. **Pre-registration Compliance Gate** (Implement → Review): During active data collection, use `prevent-file-change-action` to block changes to `research/analysis/` unless accompanied by a protocol deviation document. Phase state tracked in `experiment-phase.json`.

3. **Statistical Reproducibility Gate** (Review → Axiom Gate): Run `dvc repro` to verify analysis outputs are current and reproducible from tracked inputs.

4. **Data Integrity Gate**: Validate new experiment data conforms to Pydantic schemas.

### Cross-Repo CI Coordination

- **Repository dispatch** via `peter-evans/repository-dispatch` — when constitution merges governance changes, trigger compatibility checks in council/officium.
- **Reusable workflows** in a shared `.github` repo — shared linting, SDLC stages, experiment validation.
- **Composite actions** for shared steps (install uv + sync, run axiom gate).

### Lab Journal Automation

- Quarto + GitHub Actions via `quarto-dev/quarto-actions`
- Use `freeze: true` in `_quarto.yml` to avoid re-executing old entries
- Deploy to GitHub Pages on push
- Post-session action that pulls Langfuse metadata, extracts key metrics, appends structured entry

### Data Management

- **DVC (Data Version Control)** for experiment data versioning — session logs, posteriors, GQI series
- Each experiment phase as a `dvc.yaml` pipeline stage
- CI validates pipeline integrity (all stages reproducible from inputs)
- **Artifact tiers:** small (configs, stats) → Git; medium (processed data, plots) → DVC local; large (raw audio, traces) → DVC cloud

### SDLC Tuning for Research

- **Adversarial Review:** Add research methods review prompts — p-hacking detection, degrees-of-freedom checks, pre-registration consistency
- **Path-based gating:** Full experiment integrity pipeline for `research/` and `agents/hapax_voice/`; lighter pipeline for infrastructure
- **Fast-track label:** Skip triage + plan for infrastructure-only fixes that block data collection

### Anti-Patterns

1. Not versioning analysis scripts separately from application code
2. Not testing statistical code (need known-answer tests with synthetic data)
3. Over-engineering CI for a single operator (keep gates automated/binary, not procedural)
4. Treating experiment infrastructure as stable (changes can invalidate ongoing experiments)
5. Not pinning analysis dependencies
6. Not archiving experiment snapshots at phase completion

---

## 5. Research Documentation

### Theory-to-Code Traceability

**Numpydoc with theory references** (LSST pattern): Every module/class implementing a theoretical construct carries a `Notes` section naming the source and a `References` section with full citations. Example:

```python
def compute_gqi(self) -> float:
    """Grounding Quality Index: composite of acceptance and engagement signals.

    Notes
    -----
    Operationalizes Clark & Brennan's (1991) grounding criterion as a
    weighted composite. The EWMA component tracks the acceptance ratio
    from Traum's (1994) DU model. The trend component detects shifts
    in grounding quality that threshold-based methods miss.

    References
    ----------
    .. [1] Clark, H. H., & Brennan, S. E. (1991). Grounding in
       communication. Perspectives on socially shared cognition, 13, 127-149.
    .. [2] Traum, D. R. (1994). A computational theory of grounding
       in natural language conversation. (Doctoral dissertation).
    """
```

Additionally: a **traceability matrix** (`research/theory/THEORY-MAP.md`) mapping theoretical claims → code locations → test coverage.

### Documentation Tiers (Diataxis Framework)

| Tier | Location | Content | Audience |
|------|----------|---------|----------|
| Explanation | `research/theory/` | Theoretical foundations, position papers, literature review | Researchers, reviewers |
| Reference | `docs/` + docstrings | Architecture, API, configuration | Developers |
| How-to | `docs/` | Reproduction guide, experiment setup | Replicators |
| Tutorial | README quick start | Minimal working example | New visitors |

### Decision Records (MADR + Research Extensions)

Use MADR template stored in `docs/decisions/` with two research-specific additions:

```markdown
## Theoretical Basis
[Which papers/theories support this decision]

## Reversal Criteria
[What evidence would invalidate this decision]
```

Current "Critical Decisions" in RESEARCH-STATE.md should reference full decision records.

### Proof Document Lifecycle

| Document Type | Lifecycle | Update Policy |
|---------------|-----------|---------------|
| Literature review | **Living** | Update when new work found; version log at top |
| Position papers | **Snapshot** | Status field (Draft/Active/Superseded); new paper supersedes old |
| Refinement research | **Snapshot** | Dated, with Findings Status (Current/Superseded) |
| RESEARCH-STATE.md | **Living** | Always reflects current truth |
| Pre-registration | **Frozen** | Amendments documented separately |

### Cross-Referencing

- **Master index** (`research/theory/README.md`): Lists all documents with descriptions and relative links
- **Header anchors** for deep linking: `./LITERATURE-REVIEW.md#grounding-theory`
- **Backlinks section** at bottom of each document: "Referenced by: ..."
- Consider MkDocs or Sphinx if navigability becomes a bottleneck

### Changelog Strategy (Two-Track)

- `CHANGELOG.md` — Standard Keep a Changelog for software changes (audience: developers)
- `RESEARCH-STATE.md` — Research-specific changelog (audience: researchers, future self, reviewers)

A code change (refactored acceptance classifier) → CHANGELOG. A research change (switched from binary to graded acceptance based on Traum 1994) → RESEARCH-STATE with link to decision record.

---

## 6. Open Science Infrastructure

### OSF Project Architecture

```
OSF Project: "Operationalizing Conversational Grounding in Voice AI"
├── Component: Pre-registration (frozen OSF Registration)
├── Component: hapax-council (linked to GitHub)
├── Component: hapax-constitution (linked to GitHub)
├── Component: Lab Journal (linked or hosted)
└── Component: Data (session logs, posteriors, GQI series)
```

OSF GitHub add-on links one repo per OSF component. OSF provides the project hub; GitHub hosts the code; Zenodo archives releases with DOIs.

### Pre-registration for SCED

**No OSF template exists for SCED.** Use the comprehensive OSF template + a SCED-specific addendum covering Johnson & Cook's (2019) eight elements:

1. Basic descriptive information
2. Research questions
3. Participant characteristics (single operator)
4. Baseline conditions
5. Independent variable (grounding system components)
6. Dependent variable (GQI, turn_pair_coherence, etc.)
7. Hypotheses
8. Phase-change decision criteria

Pre-register the **model specification** (BEST, priors, chains, convergence criteria), **decision rules** (95% HDI excluding zero), and **phase-change criteria** (minimum data points, stability). Include analysis script commit hash.

### Citation & DOI Strategy

**CITATION.cff** in every research-relevant repo. GitHub renders "Cite this repository" automatically. Zenodo reads it on release.

```yaml
cff-version: 1.2.0
message: "If you use this software, please cite it as below."
type: software
title: "hapax-council"
authors:
  - given-names: [name]
    family-names: [name]
    orcid: "https://orcid.org/XXXX-XXXX-XXXX-XXXX"
repository-code: "https://github.com/[org]/hapax-council"
license: Apache-2.0
```

**DOIs needed:** hapax-council (primary artifact), hapax-constitution (governance contribution). Others: only if independently cited.

**Setup:** Connect Zenodo to GitHub → enable repos → add CITATION.cff → create Release → Zenodo auto-archives and mints DOI.

### Reproducibility Packaging (Tiered)

| Tier | Scope | Approach | Achievability |
|------|-------|----------|---------------|
| 1 | Analysis reproducibility | `uv.lock`, pinned seeds, Docker Compose for analysis pipeline, ArviZ InferenceData files | **Prioritize this** |
| 2 | Experiment reproducibility | Docker Compose for core services, model version docs, representative transcripts | Partial |
| 3 | Full system reproducibility | Architecture diagrams, systemd docs, hardware requirements doc | Document only |

Full reproduction of a 45+ agent system with GPU inference, Qdrant, PostgreSQL, LiteLLM, Ollama, and Langfuse is unrealistic to package. The contribution is the design and evidence, not the deployable package.

### Licensing

| Repo/Artifact | License | Rationale |
|---------------|---------|-----------|
| Code repos | Apache 2.0 | Permissive + patent grant + attribution |
| hapax-constitution (spec docs) | CC-BY 4.0 | Textual/conceptual works |
| Data deposits (Zenodo) | ODC-By or CC0 | CC licenses not for data (CC's own recommendation) |

Add LICENSE files to hapax-watch, cockpit-mcp, distro-work.

### Lab Journal Deployment

Quarto + GitHub Pages:
- `freeze: true` in `_quarto.yml` — avoids re-executing old entries
- Deploy via GitHub Actions (`quarto-dev/quarto-actions`)
- Entry structure: date, title, context, what was done, results, interpretation, links (commit hashes, Langfuse traces)
- Write rough entries in real-time — never "clean up" (destroys evidentiary value)
- Polished narratives go in separate documents linked from journal entries

---

## 7. Synthesis: The Plan

### Priority 1 — Blocking research launch

These must be done before Cycle 2 data collection can begin:

1. **Add CITATION.cff** to hapax-council and hapax-constitution
2. **Add LICENSE** (Apache 2.0) to hapax-watch, cockpit-mcp, distro-work
3. **Create OSF project** with component structure; link GitHub repos
4. **File pre-registration** on OSF (comprehensive template + SCED addendum)
5. **Restructure council:** Create `research/` compendium directory; move `proofs/` content to `research/theory/`
6. **Rewrite hapax-council README** as hub: research context, ecosystem table, citation, reproduction path, computational requirements
7. **Deploy lab journal** to GitHub Pages via GitHub Actions
8. **Add experiment-phase.json** state file for CI gating

### Priority 2 — Supporting research integrity

9. **Add pre-registration compliance gate** to council CI (prevent-file-change-action on `research/analysis/`)
10. **Add DVC** for experiment data versioning
11. **Create traceability matrix** (`research/theory/THEORY-MAP.md`)
12. **Add MADR decision records** for existing critical decisions (10 decisions in RESEARCH-STATE.md)
13. **Rewrite spoke READMEs** with "Part of Hapax Research Project" banners and standardized navigation
14. **Add cross-repo tags** at experiment phase boundaries
15. **Standardize labels** across all repos (`research`, `infrastructure`, `experiment`, `analysis`)

### Priority 3 — Long-term quality

16. **Add Numpydoc theory references** to grounding_ledger.py, grounding_evaluator.py, conversation_pipeline.py
17. **Set up Zenodo-GitHub integration** for automatic DOI on release
18. **Extract shared CI** into reusable workflows
19. **Add GitHub Actions** to hapax-watch and cockpit-mcp
20. **Create Tier 1 reproducibility package** (Docker Compose for analysis pipeline)
21. **Add GitHub Organization Project** for cross-repo research tracking
22. **Tune adversarial review** for research methods checking

---

## Key Sources

### Research Software Engineering
- Wilson et al. (2017) "Good Enough Practices in Scientific Computing" — PLOS Comp Bio
- Lee (2018) "Ten Simple Rules for Documenting Scientific Software" — PLOS Comp Bio
- Nust et al. "Ten Simple Rules for Writing Dockerfiles" — PLOS Comp Bio
- Nature Scientific Reports (2022) "Documenting Research Software in Engineering Science"

### Repository Organization
- Project TIER Protocol 4.0
- BIDS (Brain Imaging Data Structure)
- Psych-DS Specification
- The Turing Way Research Compendium
- Marwick et al. (2018) "Packaging Data Analytical Work Reproducibly"
- AI2 Tango (experiment orchestration)

### README & Documentation
- JOSS Review Criteria
- rOpenSci Packaging Guide
- RSQKit "Creating a Good README"
- Social Science Data Editors Template README
- CodeRefinery "Writing Good README Files"
- Diataxis Documentation Framework
- LSST Developer Guide (Numpydoc conventions)
- MADR (Markdown Architectural Decision Records)

### Open Science
- Johnson & Cook (2019) "Preregistration in Single-Case Design Research"
- Schnell (2015) "Ten Simple Rules for a Computational Biologist's Laboratory Notebook"
- CITATION.cff Format Specification
- Zenodo-GitHub Integration Documentation
- FAIR Data Principles

### CI/CD
- prevent-file-change-action (file modification guard)
- peter-evans/repository-dispatch (cross-repo triggers)
- quarto-dev/quarto-actions (lab journal CI)
- DVC (Data Version Control) documentation
- GitHub Rulesets for file path restrictions

### Theoretical
- Clark & Brennan (1991) "Grounding in Communication"
- Traum (1994) "A Computational Theory of Grounding"
- Shaikh et al. (ACL 2025) "Navigating Rifts in Human-LLM Grounding"
