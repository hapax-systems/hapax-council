# Research Compendium

Research artifacts for **Operationalizing Conversational Grounding in Production Voice AI** — a Single Case Experimental Design (SCED) study implementing Clark & Brennan's (1991) grounding theory.

## Directory Structure

```
research/
├── protocols/          Pre-registrations, experiment protocols, amendments
├── data/
│   ├── raw/            Immutable original data (session logs, traces)
│   └── processed/      Derived datasets ready for analysis
├── analysis/           Bayesian models, visualization scripts
├── results/
│   ├── figures/        Generated graphics
│   └── tables/         Statistical tables
└── config/             Experiment configurations (versioned)
```

## Theoretical Foundations

Theory documents live in [`../agents/hapax_voice/proofs/`](../agents/hapax_voice/proofs/):

| Document | Content |
|----------|---------|
| [RESEARCH-STATE.md](../agents/hapax_voice/proofs/RESEARCH-STATE.md) | Current research state (living document) |
| [THEORETICAL-FOUNDATIONS.md](../agents/hapax_voice/proofs/THEORETICAL-FOUNDATIONS.md) | Literature review: Clark, Traum, Brennan, SCED methodology |
| [POSITION.md](../agents/hapax_voice/proofs/POSITION.md) | Counter-positioning vs profile retrieval |
| [REFINEMENT-RESEARCH.md](../agents/hapax_voice/proofs/REFINEMENT-RESEARCH.md) | 8 research streams, refined model design |
| [PACKAGE-ASSESSMENT.md](../agents/hapax_voice/proofs/PACKAGE-ASSESSMENT.md) | Component analysis, 2x2 matrix, SCED methodology |
| [WHY-NO-ONE-IMPLEMENTED-CLARK.md](../agents/hapax_voice/proofs/WHY-NO-ONE-IMPLEMENTED-CLARK.md) | 32-year gap analysis |
| [CYCLE-2-PREREGISTRATION.md](../agents/hapax_voice/proofs/CYCLE-2-PREREGISTRATION.md) | Experiment design: ABA, BEST, HDI+ROPE |
| [CYCLE-1-PILOT-REPORT.md](../agents/hapax_voice/proofs/CYCLE-1-PILOT-REPORT.md) | Pilot methods, results, deviations |
| [BASELINE-ANALYSIS.md](../agents/hapax_voice/proofs/BASELINE-ANALYSIS.md) | 17 sessions, 8 patterns |
| [REPO-OPTIMIZATION-RESEARCH.md](../agents/hapax_voice/proofs/REPO-OPTIMIZATION-RESEARCH.md) | Repository optimization for research support |

## Lab Journal

The lab journal is a Quarto site deployed to GitHub Pages: [`../lab-journal/`](../lab-journal/).

## Theory-to-Code Traceability

See [THEORY-MAP.md](./THEORY-MAP.md) for a matrix mapping theoretical claims to code locations.

## Pre-registration

*OSF registration pending. Will be linked here when filed.*

## Data Availability

*Data collection has not yet begun for Cycle 2. Data availability statement will be added when the experiment is complete.*

## Conventions

- **Raw data is immutable.** Never modify files in `data/raw/`. Process into `data/processed/`.
- **Protocols are versioned.** Use `protocol-v{N}.{M}.md` naming. Never overwrite — create amendments.
- **Configs are committed.** Experiment configurations must be version-controlled, not set via environment variables.
- **Results are reproducible.** Every file in `results/` must be regenerable from `data/` + `analysis/` scripts.
