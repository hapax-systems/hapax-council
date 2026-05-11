# Start Here: Hapax as an AI Safety Research Artifact

This page is the short dossier for reviewers, researchers, and automated triage
systems arriving from an application, fellowship review, grant packet, weblog
post, or GitHub profile link.

## One-Sentence Claim

Hapax is a single-operator autonomous grounding lab: a live agentic system that
tries to determine what it knows, what it may claim, what it must refuse, and
what can safely become public evidence.

## Why This Exists

Most agent demonstrations evaluate whether a task was completed. Hapax treats a
larger path as the safety-relevant unit: perception, source recruitment, claim
formation, uncertainty, refusal, correction, public/private boundary handling,
and publication or livestream egress.

That makes this repository relevant to empirical AI safety work around:

- safety evaluation,
- agentic oversight,
- grounded claim authority,
- source/provenance faithfulness,
- refusal and correction behavior,
- privacy-preserving public egress,
- multi-agent coordination under operational pressure.

The intended research output is not "an AI streamer" or a creator product. The
intended output is a benchmarkable and reviewable account of grounding attempts:
episodes where an agentic system makes, refuses, revises, publishes, suppresses,
or corrects claims under real tool, source, privacy, and public-facing
constraints.

For OpenAI Safety Fellowship or similar AI-safety reviewers: this is meant to
fit the lane of empirically grounded safety evaluation, agentic oversight,
robustness, scalable mitigations, and privacy-preserving safety methods, with a
substantial external output in the form of a benchmark, dataset, and methods
paper.

## Review Path

If you have five minutes:

1. Read this file.
2. Read the first half of [`README.md`](README.md), especially "Project spine,"
   "What this is," and "Architecture."
3. Inspect [`research/THEORY-MAP.md`](research/THEORY-MAP.md) for the link
   between grounding theory and implementation surfaces.

If you have fifteen minutes:

1. Inspect [`shared/affordance_pipeline.py`](shared/affordance_pipeline.py) for
   semantic recruitment.
2. Inspect [`shared/system_observability.py`](shared/system_observability.py)
   and [`scripts/hapax-observe`](scripts/hapax-observe) for the current
   observability spine.
3. Inspect [`agents/publication_bus/`](agents/publication_bus/) for public
   egress and refusal/publishing infrastructure.
4. Inspect [`axioms/`](axioms/) and
   [`hapax-constitution`](https://github.com/ryanklee/hapax-constitution) for
   governance commitments.

If you have an hour:

1. Read [`docs/research/2026-04-28-velocity-report-evidence-baseline.md`](docs/research/2026-04-28-velocity-report-evidence-baseline.md)
   for an example of evidence-boundary reconciliation.
2. Read [`research/README.md`](research/README.md) and
   [`research/RESEARCH-INDEX.md`](research/RESEARCH-INDEX.md).
3. Follow one claim from public text to source path to test or runtime
   mechanism. The core question is whether the system's public claims are
   supportable by the code, records, and artifacts it exposes.

## Safety-Relevant Thesis

Hapax studies whether agentic systems can maintain honest claim authority while
operating in the world. A claim is not treated as safe because a model can say it
fluently. A claim is treated as a bounded act that should carry source state,
freshness, uncertainty, rights/privacy posture, public-surface eligibility, and
repair paths.

The practical research question is:

> When an agent is working with tools, sources, private context, public surfaces,
> other agents, and real-time constraints, can it know what it is entitled to
> claim, and can it fail closed when it is not entitled?

This is deliberately narrower than "make an intelligent agent." It is also
broader than answer-level citation checking. The safety question is the whole
path from an impingement or request to a claim-bearing action.

## Current Fellowship-Shaped Project

Working title:

**Grounding Attempts as Safety Artifacts: A Live Benchmark for Agentic Claim
Confidence, Refusal, and Public Egress**

Target outputs:

- a 30-50 item grounding evaluation suite with replayable source packets,
- a dataset/card for grounding attempts, refusals, corrections, and
  public-egress decisions,
- a methods paper or technical report on single-operator live grounding as an
  empirical safety instrument,
- open schemas/contracts for provider routing, claim-authority ceilings,
  no-expert-system gates, public-event mapping, and refusal/correction
  artifacts,
- a reproducible artifact bundle with code, tests, and redacted/anonymized
  traces where public release is safe.

## What Is Unusual

Hapax is a single-operator system. That is a methodological constraint, not a
SaaS limitation. It allows a high-fidelity setting where consent, privacy,
operator context, public egress, and repair obligations can be governed tightly.

The repository includes code for a live studio, voice daemon, visual compositor,
publication bus, governance gates, Obsidian-backed task surfaces, multi-agent
coordination, and research records. These are not separate product features.
They are parts of the same instrument: a situated environment where grounding
failures and corrections can be observed.

## What Not To Infer

- This repository does not claim that a single-operator n=1 lab is already a
  general benchmark.
- It does not claim that every public-facing surface is complete, polished, or
  externally reproducible today.
- It does not claim that Hapax has human mental states. The project studies
  operational grounding, claim authority, refusal, public egress, and
  self-inspection in a computational system.
- It does not claim that all internal records are public. Some source material
  is private by design because the system handles operator context and consent
  boundaries.
- It is not seeking contributors, support tickets, or community governance.

## Public Anchors

- Repository: <https://github.com/hapax-systems/hapax-council>
- Governance specification: <https://github.com/ryanklee/hapax-constitution>
- Public weblog: <https://hapax.weblog.lol/>
- Hapax Manifesto v0: <https://hapax.weblog.lol/hapax-manifesto-v0>
- Refusal Brief: <https://hapax.weblog.lol/refusal-brief>
- Velocity evidence baseline: <https://hapax.weblog.lol/velocity-report-2026-04-25>

## Search Terms

Useful terms inside this repository:

- `grounding`
- `claim authority`
- `refusal`
- `public egress`
- `publication bus`
- `affordance pipeline`
- `observability`
- `axiom`
- `no-expert-system`
- `single-operator`

## Reading Standard

Read this work as research infrastructure, not as a finished product pitch. The
valuable question is not whether every component is already clean. The valuable
question is whether the architecture exposes a credible path toward measuring
grounded agent behavior in a real, privacy-constrained, public-facing system.
