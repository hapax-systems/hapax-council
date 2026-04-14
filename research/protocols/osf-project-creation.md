# OSF Project Creation Procedure (LRR Phase 1 item 6)

**Date:** 2026-04-14
**Phase:** LRR Phase 1 (Research Registry Foundation)
**Owner:** alpha (procedure) → operator (execution)
**Source:** Bundle 2 §2 (`~/.cache/hapax/relay/context/2026-04-14-lrr-bundle-2-methodology-refs.md`)

This document is the verbatim procedure for creating an OSF project for the voice grounding research. **Phase 1 ships the procedure document only** — actual filing happens in **LRR Phase 4** (Phase A Completion + OSF Pre-Registration). The condition.yaml's `pre_registration.filed` flag flips to `true` at that point.

## Why OSF (Open Science Framework)

The LRR epic frames the voice grounding research as a public, pre-registered scientific claim — specifically the Shaikh claim (`claim-shaikh-sft-vs-dpo`) which tests SFT-only vs DPO post-training under identical grounding directives. OSF gives:

- A persistent project URL (and DOI) anyone can cite
- A pre-registration record that locks the analysis plan before data is collected (research-validity guard against post-hoc fishing)
- A version-controlled record of the protocol document
- An audit trail of when each artifact was added

Per LRR epic §3 P-2 ("Research validity is load-bearing"), pre-registration is not optional polish — it is a constitutive prerequisite for Phase A completion.

## Prerequisites

- Operator has an OSF account (free at https://osf.io/register/). If not, create one and link an ORCID iD.
- The research-registry CLI (`scripts/research-registry.py`) is operational and `cond-phase-a-baseline-qwen-001` exists in `~/hapax-state/research-registry/`.
- The pre-registration markdown template is filled in for the Shaikh claim (Bundle 2 §2 has a verbatim draft; the actual fill happens in Phase 4).

## Procedure (operator action)

1. **Create OSF project**
   - Navigate to https://osf.io
   - Click **New Project**
   - Project title: `Conversational grounding under SFT vs DPO post-training`
   - Description: paste the one-paragraph TL;DR from the Shaikh research summary
   - Storage region: any (US-East is default)
   - Click **Create**
2. **Add a registration**
   - Inside the project, click **Registrations** in the left sidebar
   - Click **New registration**
   - Choose **OSF Preregistration** (NOT "Open-Ended Registration" — pre-registration locks the analysis plan)
   - Continue
3. **Fill in the registration form**
   - OSF doesn't accept raw markdown — each field is a separate textarea
   - Use the verbatim template from Bundle 2 §2:
     - Metadata
     - Study Information
     - Design Plan (between-subjects vs within-subjects, blinding, etc.)
     - Sampling Plan (sample size justification, stopping rule)
     - Variables (manipulated, measured, indices)
     - Analysis Plan (statistical model, inference criteria, missing data handling, exploratory analysis labeled as such)
     - Other (any additional context — e.g., references to LRR epic + research registry condition.yaml)
4. **Submit and embargo**
   - Click **Continue** → **Submit registration**
   - Choose embargo period if desired (typical: 6-12 months for a paper-in-progress)
   - OSF generates a registration URL like `https://osf.io/abcde/` and a DOI like `10.17605/OSF.IO/ABCDE`
5. **Update the condition.yaml**
   ```bash
   # In the alpha worktree, edit:
   #   ~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/condition.yaml
   # Change:
   #   osf_project_id: <project-id>           # e.g. "abcde"
   #   pre_registration:
   #     filed: true                           # was: false
   #     url: https://osf.io/<reg-id>/
   #     filed_at: 2026-04-XX                  # actual date of filing
   ```
6. **Commit the registry update**
   - Note: `~/hapax-state/research-registry/` is **not in git** (it's runtime state). The "commit" step lives in the LRR Phase 4 close handoff, which records the OSF URL + DOI as a permanent reference.
   - The handoff doc cites the OSF URL so future sessions can verify pre-registration provenance without reaching into runtime state.

## Phase 1 deliverable

This document. The actual project + registration are Phase 4 work.

## Cross-references

- **Bundle 2 §2** — full pre-registration template draft + the procedure context
- **LRR epic §Phase 4** — when this procedure executes and what it gates
- **`research/protocols/deviations/`** — where deviations from the pre-registered protocol live (e.g., DEVIATION-037 documents the Hermes 3 substrate transition as a deliberate within-experiment manipulation, not a confound)
- **`agents/hapax_daimonion/proofs/RESEARCH-STATE.md`** — the voice grounding research state pin updated 2026-04-14 by LRR Phase 0 PR #1

## Open questions deferred to Phase 4

- **OSF account ownership:** is the project owned by the operator's personal OSF account or a project-specific account?
- **ORCID linking:** confirm the operator's ORCID iD is linked to the OSF account before the project is created
- **Embargo policy:** how long? Tradeoff is replication speed (no embargo) vs. paper-first publication (longer embargo)
- **Co-authorship:** does the OSF project list any collaborators? (Phase 7 persona spec authoring may add the operator + alpha as co-authors)
- **Pre-registration vs. registered report:** OSF supports both. Pre-registration locks the analysis plan; a registered report goes further and locks the *introduction* + *methods* sections to a journal before data collection. The Shaikh claim is currently planned as pre-registration only; upgrading to a registered report is a Phase 4 decision.

These questions do not block Phase 1. They block **Phase 4 step 4** (file the pre-registration). Phase 4 must resolve them before clicking Submit.
